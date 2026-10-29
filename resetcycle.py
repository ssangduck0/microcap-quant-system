"""🔁 리셋 사이클 — '우선주 월례 상환 → 기준가 리셋 → 전환가 할인 → 신주 → 병합' 구조(WHLR 형) 계산기 (2026-10-30).

설정형: `reset_config` 에 행이 있는 종목만 🏢 기업 분석 화면에 '🔁 리셋 사이클' 탭이 뜬다(방문객 숨김). 비슷한 종목은 행만 추가.
공식·숫자의 근거는 docs/whlr_check_2026-10-30.md (SEC 8-K 원문 확인) — 요청서의 '10거래일 최저 VWAP' 가 아니라
  기준가  = 상환일 **직전(당일 제외)** window_days 거래일 **종가의 거래량 가중 평균**   (37차: 재계산 4.957 vs 발표 4.96)
  전환가  = 기준가 × (1 − 할인율)                                                      (WHLR 45% → ×0.55)
  D 1주당 보통주 = 우선주 상환가 ÷ 전환가,  어음 하루 신주 = 일일 상환액 ÷ max(전일 종가, 하한)
컨닝 없음: 과거 사이클 재측정은 그 상환일 **이전** 봉만으로 기준가를 만들고, 상환일 이후 봉은 '결과' 로만 쓴다.
병합 환산: 야후는 병합이 지나면 과거 가격을 고쳐 주지만 병합 당일·전날엔 안 고친 자료가 올 수 있어, rs_events + 설정의 예정 병합으로
  '아직 환산 안 된 봉' 을 찾아 ×(1/비율) 한다(현재 주식 기준으로 통일). 발표 전환가도 그 뒤 병합을 곱해 같은 기준으로.
투자 권유가 아니라 검증·관찰용. AI 비용 0.
"""
from __future__ import annotations

import math
from contextlib import closing
from datetime import date, timedelta

import pandas as pd

import db

DDL = [
    """CREATE TABLE IF NOT EXISTS reset_config (
        ticker TEXT PRIMARY KEY, label TEXT,
        window_days INTEGER DEFAULT 10,      -- 기준가 창(거래일 수, 상환일 제외)
        discount_pct REAL DEFAULT 45,        -- 전환가 할인율(%)
        redeem_day INTEGER DEFAULT 5,        -- 매월 상환일(그날이 휴장이면 다음 거래일)
        pref_price REAL,                     -- 우선주 1주 상환가($, 주식 결제 기준)
        pref_remaining REAL,                 -- 남은 우선주 수(마지막 공시)
        shares_out REAL, shares_asof TEXT,   -- 보통주 발행주식(현재 기준) · 기준일
        note_daily_usd REAL,                 -- 어음 일일 상환액($)
        note_active INTEGER DEFAULT 0,       -- 어음 가동 중이면 1(승인·등록 전엔 0 = 시나리오만)
        note_floor REAL,                     -- 어음 결제가 하한($, 고정 문구)
        note_start TEXT,                     -- 가동 조건·예정(설명)
        split_date TEXT, split_ratio REAL,   -- 예정·방금 병합(야후가 아직 안 고친 봉 환산용; rs_events 와 합침)
        memo TEXT, updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS reset_cycles (
        ticker TEXT NOT NULL, redeem_date TEXT NOT NULL, seq INTEGER,
        announced_px REAL,                   -- 발표 전환가(발표 당시 주식 기준)
        base_px REAL,                        -- 발표 기준가(있으면)
        src TEXT, memo TEXT, PRIMARY KEY (ticker, redeem_date))""",
]

# WHLR 초기값 — docs/whlr_check_2026-10-30.md 의 원문 확인 숫자(관리 모드에서 수정 가능 · INSERT OR IGNORE 라 한 번만 들어감)
WHLR_SEED = dict(
    ticker="WHLR", label="Series D 우선주 월례 상환(매월 5일) → WHLRL 전환가 45% 할인 리셋 · 38차 = 2026-11-05",
    window_days=10, discount_pct=45.0, redeem_day=5,
    pref_price=41.96, pref_remaining=1_703_374,                 # 10/5 기준 Series D 잔여 · $41.96 상환가
    shares_out=979_000, shares_asof="2026-10-30(1:6 병합 후 추정 ≈ 587만÷6)",
    note_daily_usd=100_000, note_active=0, note_floor=0.25, note_start="12/4 주총 승인(19.9% 한도) + 등록 뒤 가동 · 결제가 = 전일 종가",
    split_date="2026-10-30", split_ratio=1 / 6,
    memo="10월 희석의 주 출처는 어음(미발행)이 아니라 Series B·D → 보통주 3(a)(9) 교환(병합 전 약 280만 주/월). 출처 docs/whlr_check_2026-10-30.md",
)
WHLR_CYCLES = [("2026-08-05", 35, 0.40, "8-K 2026-08-07"), ("2026-09-08", 36, 0.54, "8-K 2026-09-09"), ("2026-10-05", 37, 2.73, "8-K 2026-10-06 (기준가 4.96)")]
PCTS = (0.2, 0.0, -0.2, -0.4)          # 남은 창 날짜의 가격 가정(마지막 종가 대비)
AFTER_BARS = 10                        # 과거 사이클 재측정: 상환일 뒤 몇 봉을 '결과' 로 보나
NASDAQ_CUM = 250.0                     # 나스닥 5810(c)(3)(A)(iv): 2년 누적 병합 250:1 이상(또는 1년 안 병합) → $1 미달 유예 없음


# ---------------------------------------------------------------- 표 · 설정
def ensure(conn) -> None:
    for d in DDL:
        conn.execute(d)
    seed(conn)


def seed(conn) -> None:
    cols = ", ".join(WHLR_SEED)
    conn.execute(f"INSERT OR IGNORE INTO reset_config ({cols}, updated_at) VALUES ({','.join('?' * len(WHLR_SEED))}, ?)", (*WHLR_SEED.values(), db.utcnow_iso()))
    conn.executemany("INSERT OR IGNORE INTO reset_cycles (ticker, redeem_date, seq, announced_px, src) VALUES ('WHLR',?,?,?,?)", WHLR_CYCLES)


def config(t: str, conn=None) -> dict | None:
    t = t.upper()
    if conn is None:
        with closing(db.connect()) as c:
            return config(t, c)
    ensure(conn)
    conn.row_factory = None
    cur = conn.execute("SELECT * FROM reset_config WHERE ticker=?", (t,))
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip([d[0] for d in cur.description], row))


def has(t: str) -> bool:
    try:
        return config(t) is not None
    except Exception:  # noqa: BLE001
        return False


def tickers() -> list[str]:
    try:
        with closing(db.connect()) as conn:
            ensure(conn)
            return [r[0] for r in conn.execute("SELECT ticker FROM reset_config ORDER BY ticker")]
    except Exception:  # noqa: BLE001
        return []


def save_config(t: str, **fields) -> None:
    """관리 모드에서 설정 저장(없으면 새 행 = 다른 종목 추가)."""
    t = t.upper()
    allowed = {"label", "window_days", "discount_pct", "redeem_day", "pref_price", "pref_remaining", "shares_out", "shares_asof", "note_daily_usd",
               "note_active", "note_floor", "note_start", "split_date", "split_ratio", "memo"}
    f = {k: v for k, v in fields.items() if k in allowed}
    with closing(db.connect()) as conn:
        ensure(conn)
        conn.execute("INSERT OR IGNORE INTO reset_config (ticker, updated_at) VALUES (?, ?)", (t, db.utcnow_iso()))
        if f:
            conn.execute(f"UPDATE reset_config SET {', '.join(k + '=?' for k in f)}, updated_at=? WHERE ticker=?", (*f.values(), db.utcnow_iso(), t))
        conn.commit()


def add_cycle(t: str, redeem_date: str, seq: int | None, announced_px: float | None, src: str = "", memo: str = "", base_px: float | None = None) -> None:
    with closing(db.connect()) as conn:
        ensure(conn)
        conn.execute("INSERT OR REPLACE INTO reset_cycles (ticker, redeem_date, seq, announced_px, base_px, src, memo) VALUES (?,?,?,?,?,?,?)",
                     (t.upper(), redeem_date, seq, announced_px, base_px, src, memo))
        conn.commit()


def cycles(t: str, conn=None) -> list[dict]:
    if conn is None:
        with closing(db.connect()) as c:
            return cycles(t, c)
    ensure(conn)
    return [dict(redeem_date=r[0], seq=r[1], announced_px=r[2], base_px=r[3], src=r[4] or "", memo=r[5] or "")
            for r in conn.execute("SELECT redeem_date, seq, announced_px, base_px, src, memo FROM reset_cycles WHERE ticker=? ORDER BY redeem_date", (t.upper(),))]


def splits(t: str, cfg: dict | None = None, conn=None) -> list[tuple[str, float]]:
    """[(날짜, 비율)] 오름차순. 비율 < 1 = 병합(1:6 → 1/6). rs_events(야후) + 설정의 예정 병합(같은 날짜면 하나로)."""
    if conn is None:
        with closing(db.connect()) as c:
            return splits(t, cfg, c)
    out: dict[str, float] = {}
    try:
        for d, r in conn.execute("SELECT date, ratio FROM rs_events WHERE ticker=?", (t.upper(),)):
            if r and 0 < float(r) < 1:
                out[str(d)[:10]] = float(r)
    except Exception:  # noqa: BLE001  (표가 없는 새 DB)
        pass
    if cfg and cfg.get("split_date") and cfg.get("split_ratio") and 0 < float(cfg["split_ratio"]) < 1:
        out.setdefault(str(cfg["split_date"])[:10], float(cfg["split_ratio"]))
    return sorted(out.items())


def factor_after(sp: list[tuple[str, float]], d: str | date) -> float:
    """그 날짜 **뒤**에 있었던 병합을 모두 곱한 배수(그날 가격을 현재 주식 기준으로)."""
    ds = d.isoformat() if isinstance(d, date) else str(d)[:10]
    f = 1.0
    for sd, r in sp:
        if sd > ds:
            f *= 1.0 / r
    return f


# ---------------------------------------------------------------- 달력(NYSE 근사: 연방 공휴일 − 콜럼버스·재향군인 + 성금요일)
def holidays(y0: int, y1: int) -> set[date]:
    from pandas.tseries.holiday import GoodFriday, USFederalHolidayCalendar
    hs = {d.date() for d in USFederalHolidayCalendar().holidays(f"{y0}-01-01", f"{y1}-12-31")}
    for y in range(y0, y1 + 1):
        oct1 = date(y, 10, 1)
        hs.discard(oct1 + timedelta(days=(7 - oct1.weekday()) % 7 + 7))           # 콜럼버스의 날(10월 둘째 월요일) — NYSE 개장
        v = date(y, 11, 11)                                                         # 재향군인의 날(관측일 포함) — NYSE 개장
        hs.discard(v - timedelta(days=1) if v.weekday() == 5 else v + timedelta(days=1) if v.weekday() == 6 else v)
    hs |= {d.date() for d in GoodFriday.dates(f"{y0}-01-01", f"{y1}-12-31")}
    return hs


def is_trading_day(d: date, hol: set[date]) -> bool:
    return d.weekday() < 5 and d not in hol


def roll_forward(d: date, hol: set[date]) -> date:
    while not is_trading_day(d, hol):
        d += timedelta(days=1)
    return d


def redeem_for(y: int, m: int, day: int, hol: set[date]) -> date:
    return roll_forward(date(y, m, min(day, 28)), hol)


def next_redeem(today: date, cfg: dict, hol: set[date]) -> date:
    day = int(cfg.get("redeem_day") or 5)
    r = redeem_for(today.year, today.month, day, hol)
    if r < today:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        r = redeem_for(y, m, day, hol)
    return r


def trading_days_between(a: date, b: date, hol: set[date]) -> list[date]:
    """a < d < b 인 거래일."""
    out, d = [], a + timedelta(days=1)
    while d < b:
        if is_trading_day(d, hol):
            out.append(d)
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- 봉 정리 · 병합 환산
def _frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:   # 빈 표도 날짜 인덱스로(안 그러면 `index < 날짜` 비교가 예외 → '일봉 없음' 대신 '계산 실패' 가 됨)
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"], index=pd.DatetimeIndex([]), dtype=float)
    d = df.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(d.index))
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    d.index = idx.normalize()
    d = d[~d.index.duplicated(keep="last")].sort_index()
    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c not in d.columns:
            d[c] = float("nan")
    return d[["Open", "High", "Low", "Close", "Volume"]].astype(float).dropna(subset=["Close"])


def to_current(df: pd.DataFrame | None, sp: list[tuple[str, float]]) -> tuple[pd.DataFrame, list[str]]:
    """아직 환산 안 된 봉을 현재 주식 기준으로. 병합일이 마지막 봉보다 뒤면 무조건, 아니면 병합일 전후 종가가 ×√배수 이상 튀면(미환산 자료) 환산."""
    d = _frame(df)
    notes: list[str] = []
    if d.empty:
        return d, notes
    for sd, r in sp:
        f = 1.0 / r
        sdt = pd.Timestamp(sd)
        if sdt > d.index.max():
            apply = True
        else:
            before, after = d.loc[d.index < sdt, "Close"], d.loc[d.index >= sdt, "Close"]
            if before.empty or after.empty or before.iloc[-1] <= 0:
                continue
            apply = (after.iloc[0] / before.iloc[-1]) > math.sqrt(f)   # 환산된 자료면 이런 점프가 없다(병합 당일 급등도 √배수는 잘 안 넘음)
        if apply:
            m = d.index < sdt
            if not m.any():
                continue
            for c in ("Open", "High", "Low", "Close"):
                d.loc[m, c] = d.loc[m, c] * f
            d.loc[m, "Volume"] = d.loc[m, "Volume"] / f
            notes.append(f"{sd} 1:{round(f):g} 병합 환산(×{f:g})")
    return d, notes


# ---------------------------------------------------------------- 계산
def base_price(closes, vols) -> float | None:
    c = pd.Series(list(closes), dtype=float)
    v = pd.Series(list(vols), dtype=float).fillna(0)
    if c.empty or v.sum() <= 0:
        return None
    return float((c * v).sum() / v.sum())


def window_rows(d: pd.DataFrame, redeem: date, n: int, hol: set[date]) -> list[dict]:
    """상환일 직전 n 거래일: 봉이 있는 날은 known=True, 아직 없는 날(미래·미수신)은 known=False."""
    bars = d[d.index < pd.Timestamp(redeem)]
    known = [{"date": ts.date(), "known": True, "close": float(row.Close), "vol": float(row.Volume or 0)} for ts, row in bars.tail(n).iterrows()]
    last = known[-1]["date"] if known else redeem - timedelta(days=60)
    future = [{"date": x, "known": False, "close": None, "vol": None} for x in trading_days_between(last, redeem, hol)]
    return (known + future)[-n:]


def scenarios(rows: list[dict], last_close: float | None, assume_vol: float, disc: float, pcts=PCTS, pref_price: float | None = None) -> list[dict]:
    out = []
    for p in pcts:
        closes = [r["close"] if r["known"] else (last_close or 0) * (1 + p) for r in rows]
        vols = [r["vol"] if r["known"] else assume_vol for r in rows]
        b = base_price(closes, vols)
        conv = None if b is None else b * (1 - disc)
        fut_w = sum(v for r, v in zip(rows, vols) if not r["known"]) / max(sum(vols), 1e-9)
        out.append({"pct": p, "px": None if last_close is None else last_close * (1 + p), "base": b, "conv": conv,
                    "pref_shares": (pref_price / conv) if (conv and pref_price) else None,
                    "cur_over_conv": (last_close / conv) if (conv and last_close) else None, "future_weight": fut_w})
    return out


def note_shares(cfg: dict, px: float | None) -> dict | None:
    usd = cfg.get("note_daily_usd")
    if not usd or not px:
        return None
    settle = max(float(px), float(cfg.get("note_floor") or 0))
    sh = float(usd) / settle
    so = cfg.get("shares_out") or 0
    return {"active": bool(cfg.get("note_active")), "usd": float(usd), "settle": settle, "shares": sh, "pct_out": (sh / so * 100) if so else None,
            "pct_4d": (sh * 4 / so * 100) if so else None}


def replay(d: pd.DataFrame, cyc: list[dict], sp: list[tuple[str, float]], n: int, disc: float, hol: set[date]) -> list[dict]:
    """과거 사이클: 상환일 이전 봉만으로 기준가·전환가를 다시 만들고(컨닝 없음), 발표 전환가(현재 기준 환산)와 비교, 뒤 10봉은 결과."""
    out = []
    for c in cyc:
        r = date.fromisoformat(c["redeem_date"])
        if d.empty or r > d.index.max().date():
            continue
        before = d[d.index < pd.Timestamp(r)].tail(n)
        after = d[d.index >= pd.Timestamp(r)].head(AFTER_BARS)
        fac = factor_after(sp, r)
        ann = (c["announced_px"] * fac) if c.get("announced_px") else None
        b = base_price(before["Close"], before["Volume"]) if len(before) == n else None
        calc = (b * (1 - disc)) if b else None
        ref = ann or calc
        row = {"seq": c.get("seq"), "redeem": r.isoformat(), "announced": ann, "announced_raw": c.get("announced_px"), "factor": fac, "calc": calc,
               "calc_vs_ann": ((calc / ann - 1) * 100) if (calc and ann) else None, "bars_before": len(before), "src": c.get("src", ""),
               "close_ratio": None, "low_ratio": None, "high_ratio": None, "days_to_high": None, "split_after": None}
        if ref and not after.empty:
            row["close_ratio"] = float(after["Close"].iloc[0]) / ref * 100
            row["low_ratio"] = float(after["Low"].min()) / ref * 100
            hi = after["High"].idxmax()
            row["high_ratio"] = float(after["High"].max()) / ref * 100
            row["days_to_high"] = int(after.index.get_loc(hi))
            end = after.index.max().date()
            row["split_after"] = next((sd for sd, _ in sp if r < date.fromisoformat(sd) <= end), None)
        out.append(row)
    return out


def split_rule(sp: list[tuple[str, float]], today: date) -> dict:
    y2 = (today - timedelta(days=730)).isoformat()
    y1 = (today - timedelta(days=365)).isoformat()
    s2 = [(d, r) for d, r in sp if d >= y2 and d <= today.isoformat()]
    cum = 1.0
    for _, r in s2:
        cum *= 1.0 / r
    within1y = any(d >= y1 for d, _ in s2)
    return {"n2y": len(s2), "cum2y": cum, "within1y": within1y, "flag": cum >= NASDAQ_CUM or within1y,
            "last": s2[-1][0] if s2 else None, "pending": [d for d, _ in sp if d > today.isoformat()]}


def compute(t: str, df: pd.DataFrame | None, cfg: dict | None = None, today: date | None = None, assume_vol: float | None = None, pcts=PCTS,
            now_et: pd.Timestamp | None = None) -> dict | None:
    """탭 하나에 필요한 모든 숫자. df = 야후 일봉(Open/High/Low/Close/Volume, 날짜 index) — 현재 주식 기준으로 환산해서 쓴다.
    today 를 안 주면 미국 동부 지금 날짜. 정규장 마감(16:00 ET) 전이면 오늘 봉은 '진행 중'(live) 표시 — 사용자가 보는 한국 저녁이 미국 장중이라서."""
    t = t.upper()
    with closing(db.connect()) as conn:
        cfg = cfg or config(t, conn)
        if not cfg:
            return None
        sp = splits(t, cfg, conn)
        cyc = cycles(t, conn)
    if today is None:
        now_et = now_et if now_et is not None else pd.Timestamp.now(tz="America/New_York")
        today = now_et.date()
    live_day = now_et.date() if (now_et is not None and now_et.hour < 16) else None
    hol = holidays(today.year - 2, today.year + 1)
    d, adj_notes = to_current(df, sp)
    n = int(cfg.get("window_days") or 10)
    disc = float(cfg.get("discount_pct") or 45) / 100.0
    redeem = next_redeem(today, cfg, hol)
    rows = window_rows(d, redeem, n, hol)
    for w in rows:
        w["live"] = bool(live_day and w["known"] and w["date"] == live_day)
    known = [r for r in rows if r["known"]]
    last_close = float(d["Close"].iloc[-1]) if not d.empty else None
    last_date = d.index.max().date() if not d.empty else None
    if assume_vol is None:
        tail = d["Volume"].tail(n).dropna()
        assume_vol = float(tail.median()) if len(tail) else 0.0
    sc = scenarios(rows, last_close, assume_vol, disc, pcts, cfg.get("pref_price"))
    base_known = base_price([r["close"] for r in known], [r["vol"] for r in known]) if known else None
    so = cfg.get("shares_out") or 0
    pref_usd = (cfg.get("pref_remaining") or 0) * (cfg.get("pref_price") or 0)
    mcap = (so * last_close) if (so and last_close) else None
    sc0 = next((s for s in sc if s["pct"] == 0), sc[0] if sc else None)
    return {"ticker": t, "cfg": cfg, "today": today, "redeem": redeem, "dday": (redeem - today).days, "window": rows, "known_n": len(known), "n": n,
            "disc": disc, "base_known": base_known, "scenarios": sc, "assume_vol": assume_vol, "last_close": last_close, "last_date": last_date,
            "note": note_shares(cfg, last_close), "pref_usd": pref_usd, "mcap": mcap, "pref_over_mcap": (pref_usd / mcap) if (mcap and pref_usd) else None,
            "pref_shares_0": sc0["pref_shares"] if sc0 else None, "replay": replay(d, cyc, sp, n, disc, hol), "split_rule": split_rule(sp, today),
            "adjust_notes": adj_notes, "splits": sp, "bars": d}


ALERT_DDAYS = 3   # 상환일 D-3 안이면 아침 작업이 텔레그램으로 한 줄(화~토 07:30 KST 에만 도니 D-3 이 월요일이면 D-2 부터)


def summary_line(r: dict) -> str:
    t, dd, rd = r["ticker"], r["dday"], r["redeem"].isoformat()
    if r["last_close"] is None:
        return f"🔁 {t} 리셋 사이클 D-{dd}({rd}) · 일봉 없음"
    convs = [s["conv"] for s in r["scenarios"] if s["conv"]]
    sc0 = next((s for s in r["scenarios"] if s["pct"] == 0), None)
    base = f"${r['base_known']:.2f}" if r["base_known"] else "-"
    line = f"🔁 {t} 리셋 사이클 D-{dd}({rd}) · 기준가 {base}({r['known_n']}/{r['n']}일)"
    if convs:
        line += f" · 전환가 시나리오 ${min(convs):.2f}~${max(convs):.2f}"
    if sc0 and sc0.get("cur_over_conv"):
        line += f" · 현재가÷전환가 {sc0['cur_over_conv'] * 100:.0f}%"
    if r.get("note"):
        line += " · 어음 가동 중" if r["note"]["active"] else " · 어음 미가동"
    return line + f" · 마지막 종가 ${r['last_close']:.2f}({r['last_date']})"


def morning(out=print, today: date | None = None, download=None, send=None) -> list[str]:
    """아침 작업(cases.update): 설정 종목마다 한 줄 로그, 상환일 D-3 안이면 텔레그램(주인 전용 정보 — 방문객 화면엔 안 나감). 보낸 줄을 돌려줌."""
    import market
    import notify
    dl = download or (lambda tk: market.download_daily([tk], period="6mo").get(tk))
    snd = send or notify.send_telegram
    sent: list[str] = []
    for t in tickers():
        try:
            r = compute(t, dl(t), today=today)
        except Exception as e:  # noqa: BLE001
            out(f"🔁 {t} 리셋 사이클 계산 실패: {e}")
            continue
        if not r:
            continue
        line = summary_line(r)
        out(line)
        if r["dday"] <= ALERT_DDAYS and r["last_close"] is not None:
            try:
                snd(line)
                sent.append(line)
            except Exception as e:  # noqa: BLE001
                out(f"🔁 {t} 텔레그램 실패: {e}")
    return sent


def kst_note(redeem: date) -> str:
    """미국 거래일 → 한국 시간 안내(서머타임이면 22:30~05:00, 아니면 23:30~06:00)."""
    try:
        ts = pd.Timestamp(redeem).tz_localize("America/New_York")
        dst = bool(ts.dst())
    except Exception:  # noqa: BLE001
        dst = False
    o, c = ("22:30", "05:00") if dst else ("23:30", "06:00")
    return f"한국 시간 {redeem.month}/{redeem.day} {o} ~ {(redeem + timedelta(days=1)).month}/{(redeem + timedelta(days=1)).day} {c}"
