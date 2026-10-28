"""🧪 가상매매 — 전략 5개를 각각 따로 장부로 돌려 어느 방식의 승률이 좋은지 비교한다. (2026-10-27 전략별 장부로 개편)

전략(장부)과 매수 시점:
  rank  🏁 종합 순위        매일 아침 종합 순위 1~N위를 직전 종가로
  pick  🎯 PICK +30%        PICK 통과 '유력' 종목을 그날 가격으로(같은 종목은 30일에 한 번)
  close 🎯 장마감 체크리스트 장마감 전 BEST·후보로 판정된 순간 가격으로(스캐너) → 시간외 · 다음 거래일 종가까지
  piggy 🐷 저금통            저금통 종목이 🟢 저점 구간에 들어오면 그 가격으로. 익절 = 박스 상단 · 손절 = 박스 이탈 · 저금통 기준에서 벗어나면 그날 가격으로 정리
  after 🌙 애프터 스캘핑      애프터 진입 구간 신호 가격으로(스캐너) → 그날 매도 마감(애프터 끝 10분 전)까지

청산 판정 = '익절·손절 중 먼저 닿은 쪽', 정규장만이 아니라 데이마켓·프리·애프터까지 본다:
  ① 스캐너가 돌 때마다 열린 포지션의 1분봉(모든 세션)으로 바로 판정(live_check) — 분 단위라 순서가 정확.
  ② 아침 갱신(update)이 빠진 구간을 보완: 세션별 고점·저점 기록(ext_hilo)을 세션 순서(데이마켓→프리→정규→애프터)로 확인,
     기록이 없는 날은 정규장 일봉. 같은 구간에서 둘 다 닿았으면 손절로 본다(보수적).
규칙(익절·손절·보유일)은 ⚙️ 관리 모드에서 전략별로 바꾸며, 매수할 때 그 순간 값을 거래 행에 같이 적어 둔다 → 설정을 바꿔도 지난 거래는 그대로,
새 매수부터 적용(그래야 '익절 10%일 때 vs 20%일 때'를 나중에 비교할 수 있다). 장부(book)는 전략별로 '초기화' 때마다 새로 시작하고 예전 장부는 기록으로 남는다.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import db

ET = ZoneInfo("America/New_York")
DDL = """CREATE TABLE IF NOT EXISTS pt_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT, day TEXT, ticker TEXT, rank INTEGER, score REAL, parts TEXT,
         entry REAL, qty REAL, exit_day TEXT, exit REAL, reason TEXT, status TEXT)"""
# 2026-10-27 추가 열(ALTER TABLE ADD COLUMN · 기존 데이터 보존): 전략 · 매수 때 규칙 스냅샷 · 신호 시각 · 절대 익절/손절가(저금통 박스) · 실시간 판정 진행 시각
NEW_COLS = {"strategy": "TEXT", "tp": "REAL", "sl": "REAL", "hold": "INTEGER", "sig_at": "TEXT", "tp_px": "REAL", "sl_px": "REAL", "checked_at": "TEXT", "note": "TEXT"}

STRATEGIES: dict[str, dict] = {
    "rank": {"name": "🏁 종합 순위", "desc": "매일 아침 종합 순위 1~N위를 직전 종가로 매수", "tp": 20.0, "sl": 10.0, "hold": 3, "usd": 1000.0, "n": 3, "on": True},
    "rank6": {"name": "🏁 순위(⑥ 반영)", "desc": "종합 순위에 ⑥ 직전 분기 주식수 변동 감점(+20% 초과 −10 · 10~20% −5, 희석 감점이 이미 있으면 절반)을 적용한 순위 1~N위를 직전 종가로 매수 — 2026-10-28 부터 4주간 🏁 종합 순위와 비교해 감점 여부 결정",
              "tp": 20.0, "sl": 10.0, "hold": 3, "usd": 1000.0, "n": 3, "on": True},
    "pick": {"name": "🎯 PICK +30%", "desc": "PICK 통과 '유력' 종목을 그날 가격으로 매수(같은 종목은 30일에 한 번)", "tp": 30.0, "sl": 15.0, "hold": 20, "usd": 1000.0, "n": 3, "on": True},
    "close": {"name": "🎯 장마감 체크리스트", "desc": "장마감 전 BEST·후보 판정 순간 가격으로 매수 → 시간외 포함, 다음 거래일 종가까지", "tp": 10.0, "sl": 5.0, "hold": 1, "usd": 1000.0, "n": 5, "on": True},
    "piggy": {"name": "🐷 저금통", "desc": "저금통 종목이 🟢 저점 구간에 들어오면 매수. 익절 0 = 박스 상단 · 손절 0 = 박스 이탈 · 보유 0 = 제한 없음 · 저금통 기준 이탈 시 정리",
              "tp": 0.0, "sl": 0.0, "hold": 0, "usd": 1000.0, "n": 5, "on": True},
    "after": {"name": "🌙 애프터 스캘핑", "desc": "애프터 진입 구간 신호 가격으로 매수 → 그날 매도 마감(애프터 끝 10분 전)까지. 보유일은 쓰지 않음",
              "tp": 5.0, "sl": 5.0, "hold": 0, "usd": 1000.0, "n": 5, "on": True},
    "master": {"name": "📐 스승 눌림목", "desc": "아침 차트 관점 점검에서 '급등 후 눌림 타점(무릎~허리 지지)' 신호가 난 종목을 직전 종가로 매수(같은 종목 10일에 한 번). 키쟈키라 단타 6단계: 반등 +10% 목표 · 지지 깨면 −7%",
               "tp": 10.0, "sl": 7.0, "hold": 5, "usd": 1000.0, "n": 3, "on": True},
}
FIELDS = ("on", "tp", "sl", "hold", "usd", "n")
LIMITS = {"tp": (0.0, 200.0), "sl": (0.0, 90.0), "hold": (0, 60), "usd": (10.0, 100000.0), "n": (1, 20)}
COOLDOWN_DAYS = {"pick": 30, "piggy": 5, "master": 10}      # 같은 전략·같은 종목을 다시 사기까지(달력일)
SESS = ("night", "pre", "reg", "post")
SESS_KO = {"night": "데이마켓", "pre": "프리장", "reg": "정규장", "post": "애프터"}
_SESS_START = {"night": (20, 0), "pre": (4, 0), "reg": (9, 30), "post": (16, 0)}
_SESS_END = {"night": (4, 0), "pre": (9, 30), "reg": (16, 0), "post": (20, 0)}


# ---------------------------------------------------------------- 설정(전략별 규칙) · 장부
def _defaults() -> dict[str, dict]:
    import config
    d = {k: {f: v[f] for f in FIELDS} for k, v in STRATEGIES.items()}
    d["rank"].update({"tp": float(getattr(config, "PT_TP", 20)), "sl": float(getattr(config, "PT_SL", 10)), "hold": int(getattr(config, "PT_HOLD", 3)),
                      "usd": float(getattr(config, "PT_USD", 1000)), "n": int(getattr(config, "PT_TOP_N", 3))})  # 예전 config 값은 종합 순위의 기본값으로
    return d


def _clip(f: str, v):
    if f == "on":
        return bool(v)
    lo, hi = LIMITS[f]
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = lo
    x = min(max(x, lo), hi)
    return int(x) if f in ("hold", "n") else x


def settings() -> dict[str, dict]:
    """{전략: {on, tp, sl, hold, usd, n}} — DB(meta pt_strategies)에 저장한 값 위에 기본값."""
    d = _defaults()
    try:
        m = db.get_meta("pt_strategies")
        saved = json.loads(m["value"]) if m and m.get("value") else {}
    except Exception:  # noqa: BLE001
        saved = {}
    for k in d:
        for f, v in (saved.get(k) or {}).items():
            if f in FIELDS:
                d[k][f] = _clip(f, v)
    return d


def save_settings(values: dict[str, dict]) -> dict[str, dict]:
    clean = {k: {f: _clip(f, v[f]) for f in FIELDS if f in v} for k, v in values.items() if k in STRATEGIES}
    db.set_meta("pt_strategies", json.dumps(clean, ensure_ascii=False))
    return settings()


def cfg(strategy: str = "rank") -> dict:
    return settings()[strategy]


def _cfg():  # 예전 이름(종합 순위 규칙) — 다른 모듈 호환
    return cfg("rank")


def rule_text(c: dict, strategy: str) -> str:
    tp = "박스 상단" if strategy == "piggy" and not c["tp"] else f"+{c['tp']:g}%"
    sl = "박스 이탈" if strategy == "piggy" and not c["sl"] else f"−{c['sl']:g}%"
    hold = "당일 마감" if strategy == "after" else ("제한 없음" if not c["hold"] else f"{c['hold']}거래일")
    return f"익절 {tp} · 손절 {sl} · {hold}"


def _book_key(strategy: str) -> str:
    return "pt_book" if strategy == "rank" else f"pt_book_{strategy}"


def book(strategy: str = "rank") -> str:
    m = db.get_meta(_book_key(strategy))
    if m and m.get("value"):
        return m["value"]
    b = date.today().isoformat()
    db.set_meta(_book_key(strategy), b)
    return b


def reset(strategy: str = "rank") -> str:
    """그 전략의 장부를 닫고 새 장부 시작(열린 포지션은 새 장부로 넘어가지 않고 그대로 정리 대상)."""
    b = date.today().isoformat() + "-" + pd.Timestamp.now().strftime("%H%M%S")
    db.set_meta(_book_key(strategy), b)
    return b


def ensure(conn) -> None:
    conn.execute(DDL)
    have = {r[1] for r in conn.execute("PRAGMA table_info(pt_trades)")}
    for c, typ in NEW_COLS.items():
        if c not in have:
            conn.execute(f"ALTER TABLE pt_trades ADD COLUMN {c} {typ}")
    if "strategy" not in have or conn.execute("SELECT 1 FROM pt_trades WHERE strategy IS NULL LIMIT 1").fetchone():
        c = _defaults()["rank"]   # 개편 전 거래는 모두 종합 순위 전략 · 그때 규칙(config)으로 스냅샷
        conn.execute("UPDATE pt_trades SET strategy='rank', tp=COALESCE(tp,?), sl=COALESCE(sl,?), hold=COALESCE(hold,?) WHERE strategy IS NULL", (c["tp"], c["sl"], c["hold"]))
    conn.commit()


# ---------------------------------------------------------------- 시간 도우미
def _utc(ts) -> datetime:
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.to_pydatetime()


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else _utc(dt).isoformat()


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _since(r: dict) -> datetime:
    """이 거래의 가격 확인 시작 시각: 신호 시각, 없으면(종합 순위 = 직전 종가 매수) 매수일 정규장 마감 16:00 ET."""
    s = _parse(r.get("sig_at"))
    if s is not None:
        return s
    d = date.fromisoformat(r["day"])
    return datetime.combine(d, time(16, 0), tzinfo=ET).astimezone(timezone.utc)


def _sess_of(ts_et: datetime) -> str:
    m = ts_et.hour * 60 + ts_et.minute
    if m >= 20 * 60 or m < 4 * 60:
        return "night"
    if m < 9 * 60 + 30:
        return "pre"
    if m < 16 * 60:
        return "reg"
    return "post"


def _trade_day(ts_et: datetime) -> str:
    """봉의 거래일: 20:00 ET 이후는 다음 거래일의 데이마켓(exthilo 와 같은 기준)."""
    d = ts_et.date()
    if ts_et.hour >= 20:
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _seg_bounds(d: date, s: str) -> tuple[datetime, datetime]:
    """거래일 d 의 세션 s 시작·끝(UTC). 데이마켓은 전날 20:00 ~ 당일 04:00."""
    h0, m0 = _SESS_START[s]
    h1, m1 = _SESS_END[s]
    start_day = d - timedelta(days=1) if s == "night" else d
    while s == "night" and start_day.weekday() >= 5:
        start_day -= timedelta(days=1)
    a = datetime.combine(start_day, time(h0, m0), tzinfo=ET).astimezone(timezone.utc)
    b = datetime.combine(d, time(h1, m1), tzinfo=ET).astimezone(timezone.utc)
    return a, b


# ---------------------------------------------------------------- 판정 핵심
def levels(r: dict, k: float = 1.0) -> tuple[float | None, float | None]:
    """(익절가, 손절가). 절대가(tp_px·sl_px, 저금통 박스)가 있으면 그것, 없으면 진입가 × 비율. 0·None 이면 그 쪽은 없음. k = 병합 단위 배수."""
    e = float(r["entry"]) * k
    tp = float(r["tp_px"]) * k if r.get("tp_px") else (e * (1 + float(r["tp"]) / 100) if r.get("tp") else None)
    sl = float(r["sl_px"]) * k if r.get("sl_px") else (e * (1 - float(r["sl"]) / 100) if r.get("sl") else None)
    return tp, sl


def first_touch(segs: list[tuple[str, float | None, float | None]], tp_px: float | None, sl_px: float | None) -> tuple[int, str] | None:
    """segs = [(이름, 고가, 저가)] 시간 순. 익절·손절 중 먼저 닿은 (칸 번호, 'tp'|'sl'). 같은 칸에서 둘 다 닿으면 손절(보수적)."""
    for i, (_, hi, lo) in enumerate(segs):
        if sl_px is not None and lo is not None and float(lo) <= sl_px:
            return i, "sl"
        if tp_px is not None and hi is not None and float(hi) >= tp_px:
            return i, "tp"
    return None


def _why(r: dict, kind: str, where: str) -> str:
    if kind == "tp":
        base = "익절 박스 상단" if (r.get("strategy") == "piggy" and r.get("tp_px") and not r.get("tp")) else f"익절 +{float(r['tp']):g}%"
    else:
        base = "손절 박스 이탈" if (r.get("strategy") == "piggy" and r.get("sl_px") and not r.get("sl")) else f"손절 −{float(r['sl']):g}%"
    return f"{base} ({where})" if where else base


def _close(conn, r: dict, exit_day: str, exit_px: float, why: str, n_units: float = 1.0) -> None:
    """장부에는 진입가와 같은 단위(병합 전)로 저장 → 수익률 = exit/entry 그대로."""
    conn.execute("UPDATE pt_trades SET exit_day=?, exit=?, reason=?, status='closed' WHERE id=?",
                 (exit_day, float(exit_px) / n_units, why + (" · 병합 단위 맞춤" if abs(n_units - 1) > 1e-9 else ""), r["id"]))


def open_rows(conn) -> list[dict]:
    ensure(conn)
    return [dict(x) for x in conn.execute("SELECT * FROM pt_trades WHERE status='open' ORDER BY id")]


def open_tickers() -> list[str]:
    """열린 포지션 종목 — 스캐너가 1분봉을 꼭 받아 오도록 우선 종목에 넣는다."""
    try:
        with closing(db.connect()) as conn:
            ensure(conn)
            return [x[0] for x in conn.execute("SELECT DISTINCT ticker FROM pt_trades WHERE status='open'")]
    except Exception:  # noqa: BLE001
        return []


def _after_deadline(day: str) -> datetime | None:
    """애프터 전략의 매도 마감(애프터 끝 10분 전, UTC). 스캐너 meta 가 그날 것일 때만."""
    try:
        import afterscalp
        m = db.get_meta("us_after_end")
        end = datetime.fromisoformat(m["value"])
        if end.astimezone(ET).date().isoformat() != day:
            return None
        return afterscalp.deadline_of(end)
    except Exception:  # noqa: BLE001
        return None


def live_check(conn, frames: dict, now: datetime | None = None) -> int:
    """스캐너 사이클마다: 열린 포지션의 1분봉(모든 세션)으로 익절·손절 중 먼저 닿은 쪽을 바로 판정. 청산 수.
    병합 의심(한 봉 가격이 진입가의 3배↑·1/3↓)이면 건너뛰고 아침 갱신(분할 보정)에 맡긴다."""
    now = _utc(now or datetime.now(timezone.utc))
    n = 0
    for r in open_rows(conn):
        df = frames.get(r["ticker"])
        if df is None or df.empty or "High" not in df or "Low" not in df:
            continue
        idx = pd.DatetimeIndex(df.index)
        idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
        d = df.set_axis(idx).sort_index().dropna(subset=["High", "Low"])
        start = max(_since(r), _parse(r.get("checked_at")) or _since(r))
        a = d[d.index > start]
        if a.empty:
            continue
        tp_px, sl_px = levels(r)
        e = float(r["entry"])
        if ((a["High"] / e) > 3).any() or ((a["Low"] / e) < 1 / 3).any():
            continue
        deadline = _after_deadline(r["day"]) if r.get("strategy") == "after" else None
        if deadline is not None:
            a = a[a.index <= deadline]
        hit = first_touch([(str(t), h, l) for t, h, l in zip(a.index, a["High"], a["Low"])], tp_px, sl_px)
        if hit is not None:
            i, kind = hit
            ts = a.index[i].to_pydatetime().astimezone(ET)
            _close(conn, r, _trade_day(ts), tp_px if kind == "tp" else sl_px, _why(r, kind, SESS_KO[_sess_of(ts)] + " 실시간"))
            n += 1
        elif deadline is not None and now >= deadline and len(a):
            ts = a.index[-1].to_pydatetime().astimezone(ET)
            _close(conn, r, ts.date().isoformat(), float(a["Close"].iloc[-1]) if "Close" in a else float(a["High"].iloc[-1]), "매도 마감 가격(애프터 끝 10분 전)")
            n += 1
        else:
            conn.execute("UPDATE pt_trades SET checked_at=? WHERE id=?", (_iso(a.index[-1].to_pydatetime()), r["id"]))
    conn.commit()
    return n


def _day_segments(r: dict, d: date, ext: dict | None, bar) -> list[tuple[str, float | None, float | None]]:
    """거래일 d 의 확인 칸들(세션 순서). ext = ext_hilo 행(없으면 일봉 한 칸). 진입 전 세션·실시간으로 이미 본 세션은 뺀다."""
    since = _since(r)
    checked = _parse(r.get("checked_at"))
    out = []
    if ext:
        for s in SESS:
            a, b = _seg_bounds(d, s)
            if a < since or (checked is not None and b <= checked):
                continue
            hi, lo = ext.get(f"{s}_high"), ext.get(f"{s}_low")
            if s == "reg" and bar is not None:   # 정규장은 일봉이 더 완전(스캐너가 못 본 분도 포함)
                hi = max([x for x in (hi, bar["High"]) if x is not None], default=None)
                lo = min([x for x in (lo, bar["Low"]) if x is not None], default=None)
            if hi is None and lo is None:
                continue
            out.append((s, hi, lo))
    elif bar is not None:
        a, b = _seg_bounds(d, "reg")
        if not (a < since or (checked is not None and b <= checked)):
            out.append(("reg", bar["High"], bar["Low"]))
    return out


def update(bars: dict, today: str | None = None, piggy_out: set[str] | None = None) -> int:
    """아침 갱신: 열린 포지션을 세션별 고점·저점 기록(+일봉)으로 청산 판정. bars: {티커: 일봉 DataFrame}. 청산 수.
    piggy_out = 저금통 기준에서 벗어난 종목(그날 종가로 정리). 🗄 못 받은 종목은 주가 보관소 일봉으로, 병합 뒤 가격 단위는 진입가를 맞춰서(그때는 일봉만),
    주가가 끊긴 지 7일 넘은 종목은 마지막 가격으로 정리."""
    import exthilo
    import pricevault as pv
    n = 0
    today_d = date.fromisoformat(today) if today else date.today()
    piggy_out = set(piggy_out or ())
    with closing(db.connect()) as conn:
        ensure(conn)
        opened = open_rows(conn)
        pv.fill(bars, [r["ticker"] for r in opened], conn)
        gone = pv.gone(conn)
        ext_all = exthilo.rows_for(conn, [r["ticker"] for r in opened], min((r["day"] for r in opened), default=today_d.isoformat()))
        try:
            piggy_have = {x[0] for x in conn.execute("SELECT ticker FROM piggy_list")}
        except Exception:  # noqa: BLE001
            piggy_have = None
        after_rows = {(x[0], x[1]): dict(x) for x in conn.execute("SELECT date, ticker, first_hit, exit_price FROM after_signals")} if _table(conn, "after_signals") else {}
        for r in opened:
            df = bars.get(r["ticker"])
            df = None if df is None or df.empty else df.dropna(subset=["Close"])
            closed_now = False
            k = 1.0
            if df is not None and len(df):
                adj, _why_k = pv.fix_entry(r["ticker"], r["day"], r["entry"], df, conn)
                k = (adj / r["entry"]) if (adj and r["entry"]) else 1.0
            strat = r.get("strategy") or "rank"
            tp_px, sl_px = levels(r, k)
            hold = int(r.get("hold") or 0)
            # 🌙 애프터: 그날 매도 마감까지 — 스캐너가 기록한 분봉 결과(먼저 닿은 쪽·마감 가격)로
            if strat == "after" and not closed_now:
                ar = after_rows.get((r["day"], r["ticker"]))
                last_day = df.index[-1].strftime("%Y-%m-%d") if df is not None and len(df) else today_d.isoformat()
                if ar and (ar.get("first_hit") or ar.get("exit_price") is not None):
                    fh = ar.get("first_hit") or ""
                    if fh.startswith("목표") and tp_px:
                        _close(conn, r, r["day"], tp_px, _why(r, "tp", "애프터 분봉 기록"), k)
                    elif fh.startswith("손절") and sl_px:
                        _close(conn, r, r["day"], sl_px, _why(r, "sl", "애프터 분봉 기록"), k)
                    elif fh.startswith("동시") and sl_px:
                        _close(conn, r, r["day"], sl_px, _why(r, "sl", "같은 분에 둘 다 · 보수적"), k)
                    else:
                        _close(conn, r, r["day"], float(ar["exit_price"]) * k, "매도 마감 가격(애프터 분봉 기록)", k)
                    n += 1
                    closed_now = True
                elif last_day > r["day"]:   # 기록이 없는데 날이 지남 → 애프터 세션 고점·저점 기록, 그것도 없으면 그날 정규장 종가(근사)
                    ext = (ext_all.get(r["ticker"]) or {}).get(r["day"])
                    segs = [s for s in _day_segments(r, date.fromisoformat(r["day"]), ext, None) if s[0] == "post"] if (ext and k == 1.0) else []
                    hit = first_touch(segs, tp_px, sl_px)
                    if hit is not None:
                        _close(conn, r, r["day"], tp_px if hit[1] == "tp" else sl_px, _why(r, hit[1], "애프터 세션 기록"), k)
                    else:
                        px = float(df.loc[df.index.strftime("%Y-%m-%d") == r["day"], "Close"].iloc[-1]) if df is not None and (df.index.strftime("%Y-%m-%d") == r["day"]).any() else float(r["entry"]) * k
                        _close(conn, r, r["day"], px, "매도 마감 가격 기록 없음 — 그날 정규장 종가로 근사", k)
                    n += 1
                    closed_now = True
            # 🐷 저금통: 저금통에서 빠졌거나 기준에서 벗어남 → 그날(마지막) 종가로 정리(익절이든 손절이든)
            if strat == "piggy" and not closed_now and df is not None and len(df) and (r["ticker"] in piggy_out or (piggy_have is not None and r["ticker"] not in piggy_have)):
                last_row = df.iloc[-1]
                why = "저금통 기준 이탈 — 그날 종가로 정리" if r["ticker"] in piggy_out else "저금통에서 빠짐 — 그날 종가로 정리"
                # 그 전에 익절·손절이 먼저 닿았는지는 아래 일반 판정이 먼저 봐야 하므로 '마지막 날 정리'는 일반 판정 뒤에 한다
                pending_piggy = (last_row.name.strftime("%Y-%m-%d"), float(last_row["Close"]), why)
            else:
                pending_piggy = None
            if not closed_now and df is not None and len(df):
                ext_t = ext_all.get(r["ticker"]) or {}
                days = sorted({d.strftime("%Y-%m-%d") for d in df.index if d.strftime("%Y-%m-%d") >= r["day"]} | {d for d in ext_t if d >= r["day"]})
                bars_by_day = {d.strftime("%Y-%m-%d"): row for d, row in df.iterrows()}
                i = 0
                for ds in days:
                    if ds > today_d.isoformat():
                        break
                    d = date.fromisoformat(ds)
                    bar = bars_by_day.get(ds)
                    if bar is not None and ds > r["day"]:
                        i += 1
                    ext = ext_t.get(ds) if k == 1.0 else None    # 병합이 있었던 거래는 단위가 섞이는 세션 기록 대신 일봉만
                    segs = _day_segments(r, d, ext, bar)
                    pre_close = [s for s in segs if s[0] != "post"]
                    hit = first_touch(pre_close, tp_px, sl_px)
                    if hit is not None:
                        _close(conn, r, ds, tp_px if hit[1] == "tp" else sl_px, _why(r, hit[1], SESS_KO[pre_close[hit[0]][0]]), k)
                        closed_now = True
                    elif hold and bar is not None and i >= hold:
                        _close(conn, r, ds, float(bar["Close"]), f"{hold}일 보유 종가", k)
                        closed_now = True
                    else:
                        post = [s for s in segs if s[0] == "post"]
                        hit = first_touch(post, tp_px, sl_px)
                        if hit is not None:
                            _close(conn, r, ds, tp_px if hit[1] == "tp" else sl_px, _why(r, hit[1], "애프터"), k)
                            closed_now = True
                    if closed_now:
                        n += 1
                        break
            if not closed_now and pending_piggy is not None:
                _close(conn, r, pending_piggy[0], pending_piggy[1], pending_piggy[2], k)
                n += 1
                closed_now = True
            g = gone.get(r["ticker"])
            if not closed_now and g and (g.get("detected") or "9999") <= (today_d - timedelta(days=pv.GONE_GRACE_DAYS)).isoformat():
                # 주가가 끊긴 지 7일 넘게 그대로 → 마지막 가격으로 정리(실제로는 더 낮을 수 있음 · 가격 기록이 없으면 −100%)
                last = None
                if df is not None and len(df):
                    last = float(df.iloc[-1]["Close"]) / k
                ex = last if last is not None else 0.0
                conn.execute("UPDATE pt_trades SET exit_day=?, exit=?, reason=?, status='closed' WHERE id=?",
                             (g.get("last_date") or today_d.isoformat(), ex, f"주가 끊김({g.get('reason') or '상폐·정지 추정'}) — 마지막 가격, 실제로는 더 낮을 수 있음"
                              if last is not None else "주가 끊김 — 가격 기록 없음, 전액 손실로 처리", r["id"]))
                n += 1
        conn.commit()
    return n


def _table(conn, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


# ---------------------------------------------------------------- 매수
def open_trade(conn, strategy: str, day: str, ticker: str, price: float, *, rank: int | None = None, score: float | None = None, parts: dict | None = None,
               sig_at: datetime | None = None, tp_px: float | None = None, sl_px: float | None = None, note: str | None = None, c: dict | None = None) -> bool:
    """전략 규칙 스냅샷과 함께 가상 매수. 꺼진 전략 · 이미 보유 · 하루 한도(n) 초과 · 재매수 대기 중이면 False."""
    ensure(conn)
    c = c or cfg(strategy)
    if not c["on"] or not price or price <= 0:
        return False
    b = book(strategy)
    if conn.execute("SELECT 1 FROM pt_trades WHERE strategy=? AND ticker=? AND status='open' LIMIT 1", (strategy, ticker)).fetchone():
        return False
    if conn.execute("SELECT COUNT(*) FROM pt_trades WHERE strategy=? AND day=? AND book=?", (strategy, day, b)).fetchone()[0] >= int(c["n"]):
        return False
    cd = COOLDOWN_DAYS.get(strategy, 0)
    since = (date.fromisoformat(day) - timedelta(days=cd)).isoformat() if cd else day
    if conn.execute("SELECT 1 FROM pt_trades WHERE strategy=? AND ticker=? AND day>=? LIMIT 1", (strategy, ticker, since)).fetchone():
        return False
    conn.execute("""INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, status, strategy, tp, sl, hold, sig_at, tp_px, sl_px, note)
                    VALUES (?,?,?,?,?,?,?,?,'open',?,?,?,?,?,?,?,?)""",
                 (b, day, ticker, rank, score, json.dumps(parts or {}, ensure_ascii=False), float(price), float(c["usd"]) / float(price),
                  strategy, float(c["tp"]), float(c["sl"]), int(c["hold"]), _iso(sig_at), tp_px, sl_px, note))
    return True


def open_new(rank_df: pd.DataFrame, last_close: dict, day: str | None = None, strategy: str = "rank") -> list[str]:
    """🏁 종합 순위 상위 N개를 직전 종가로(이미 들고 있는 종목·가격 없는 종목은 건너뜀). 같은 날 두 번 사지 않음.
    strategy="rank6"(2026-10-28): 같은 표를 ⑥ 반영 점수(score6)로 다시 줄 세워 상위 N개 — 4주 비교용."""
    c = cfg(strategy)
    day = day or date.today().isoformat()
    bought = []
    if rank_df is None or rank_df.empty:
        return []
    if strategy == "rank6":
        if "score6" not in rank_df.columns:
            return []
        cols = ["score6"] + (["urgency"] if "urgency" in rank_df.columns else [])
        rank_df = rank_df.sort_values(cols, ascending=False).reset_index(drop=True).assign(rank=lambda d: range(1, len(d) + 1), score=lambda d: d["score6"])
    with closing(db.connect()) as conn:
        ensure(conn)
        if conn.execute("SELECT 1 FROM pt_trades WHERE strategy=? AND day=? AND book=? LIMIT 1", (strategy, day, book(strategy))).fetchone():
            return []
        for r in rank_df.head(int(c["n"])).to_dict("records"):
            t, px = r["ticker"], last_close.get(r["ticker"])
            if open_trade(conn, strategy, day, t, px, rank=int(r["rank"]), score=float(r["score"]), parts=r.get("parts") or {}, c=c):
                bought.append(t)
        conn.commit()
    return bought


def open_pick(scan: dict | None, day: str, now: datetime | None = None) -> list[str]:
    """🎯 PICK 통과 '유력'(약한 목표 제외) 종목을 그날 가격으로. 같은 종목은 30일에 한 번."""
    if not scan or not scan.get("pass"):
        return []
    import pick30
    c = cfg("pick")
    rows = [r for r in pick30.sort(scan["pass"], "유력·임박 순") if r.get("status") == "유력" and not r.get("weak") and r.get("price")]
    bought = []
    with closing(db.connect()) as conn:
        ensure(conn)
        for i, r in enumerate(rows, 1):
            if open_trade(conn, "pick", day, r["ticker"], float(r["price"]), rank=i, sig_at=now or datetime.now(timezone.utc),
                          note=f"{r.get('target_name') or ''} ${r.get('target') or 0:.4f}".strip(), c=c):
                bought.append(r["ticker"])
        conn.commit()
    return bought


def open_piggy(prices: dict, day: str, now: datetime | None = None) -> list[str]:
    """🐷 저금통 종목이 🟢 저점 구간이면 그 가격으로. 익절가 = 박스 상단(설정 0일 때) · 손절가 = 박스 이탈선(하단 −5%, 설정 0일 때)."""
    import piggy
    c = cfg("piggy")
    if not c["on"]:
        return []
    mm = piggy.metrics_map()
    bought = []
    with closing(db.connect()) as conn:
        ensure(conn)
        for r in piggy.items().to_dict("records"):
            t = r["ticker"]
            px = prices.get(t)
            lo, hi, _src = piggy.box_of(r, mm.get(t))
            if not px or piggy.zone(px, lo, hi) != "🟢 저점 구간":
                continue
            tp_px = hi if not c["tp"] else None
            sl_px = lo * 0.95 if not c["sl"] else None
            if open_trade(conn, "piggy", day, t, float(px), sig_at=now or datetime.now(timezone.utc), tp_px=tp_px, sl_px=sl_px,
                          note=f"박스 ${lo:.4f}~${hi:.4f} · {r.get('category') or ''}", c=c):
                bought.append(t)
                conn.execute("INSERT OR IGNORE INTO piggy_events (date, ticker, price, box_low, box_high) VALUES (?,?,?,?,?)", (day, t, float(px), lo, hi))
        conn.commit()
    return bought


def master_candidates(conn, day: str) -> list[dict]:
    """📐 최근 2일 안 '눌림 타점' 신호(chart_signals kind='pullback') — 종목당 가장 최근 1건."""
    try:
        rows = [dict(r) for r in conn.execute("SELECT ticker, price, note, date FROM chart_signals WHERE kind='pullback' AND date >= date(?, '-1 day') ORDER BY date DESC, ticker",
                                              (day,))]
    except Exception:  # noqa: BLE001
        return []
    seen, out = set(), []
    for r in rows:
        if r["ticker"] not in seen:
            seen.add(r["ticker"])
            out.append(r)
    return out


def open_master(day: str, last: dict, now: datetime | None = None) -> list[str]:
    """📐 스승 눌림목: 아침 차트 관점 점검에서 눌림 타점이 난 종목을 직전 종가(없으면 신호 가격)로. 같은 종목 10일에 한 번."""
    c = cfg("master")
    if not c["on"]:
        return []
    bought = []
    with closing(db.connect()) as conn:
        ensure(conn)
        for i, r in enumerate(master_candidates(conn, day), 1):
            t = r["ticker"]
            px = last.get(t) or r.get("price")
            if not px:
                continue
            if open_trade(conn, "master", day, t, float(px), rank=i, sig_at=now or datetime.now(timezone.utc), note=(f"눌림 타점 {r['date']} · {r.get('note') or ''}")[:140], c=c):
                bought.append(t)
        conn.commit()
    return bought


def open_after(conn, day: str, ticker: str, price: float, now: datetime | None = None) -> bool:
    """🌙 애프터 진입 구간 신호가 처음 난 순간(스캐너) 그 가격으로."""
    ok = open_trade(conn, "after", day, ticker, float(price), sig_at=now or datetime.now(timezone.utc), note="애프터 진입 구간")
    conn.commit()
    return ok


def scan_close(conn, day: str, tickers: list[str], now: datetime | None = None) -> list[str]:
    """🎯 장마감 체크리스트: 고정된 대상 중 지금 BEST·후보로 판정된 종목을 지금 가격으로(스캐너가 매 사이클 부름 · 하루 한도 n · BEST 먼저)."""
    import closewatch as cw
    c = cfg("close")
    if not c["on"] or not tickers:
        return []
    cand = []
    for t in tickers:
        row = conn.execute("SELECT metrics FROM close_state WHERE date=? AND ticker=?", (day, t)).fetchone()
        if not row or not row[0]:
            continue
        m = json.loads(row[0])
        g = cw.evaluate(m)["grade"]
        if g in ("BEST", "후보") and m.get("price"):
            cand.append((cw.GRADE_ORDER.get(g, 9), tickers.index(t), t, float(m["price"]), g))
    bought = []
    for _o, i, t, px, g in sorted(cand):
        if open_trade(conn, "close", day, t, px, rank=i + 1, sig_at=now or datetime.now(timezone.utc), note=g, c=c):
            bought.append(t)
    conn.commit()
    return bought


# ---------------------------------------------------------------- 보기
def trades(book_id: str | None = None, strategy: str | None = None) -> pd.DataFrame:
    with closing(db.connect()) as conn:
        ensure(conn)
    where, params = [], []
    if book_id:
        where.append("book=?")
        params.append(book_id)
    if strategy:
        where.append("COALESCE(strategy,'rank')=?")
        params.append(strategy)
    df = db.read_df("SELECT * FROM pt_trades" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY day DESC, rank", tuple(params))
    if not df.empty:
        df["strategy"] = df["strategy"].fillna("rank")
        df["ret"] = (df["exit"] / df["entry"] - 1) * 100
        df["pnl"] = (df["exit"] - df["entry"]) * df["qty"]
    return df


def summary(df: pd.DataFrame, last_close: dict | None = None) -> dict:
    if df.empty:
        return {"n": 0, "closed": 0, "open": 0, "win": None, "pnl": 0.0, "ret": None, "avg": None, "open_pnl": 0.0}
    cl = df[df["status"] == "closed"]
    op = df[df["status"] == "open"]
    open_pnl = sum(((last_close or {}).get(r.ticker, r.entry) - r.entry) * r.qty for r in op.itertuples())
    inv = (cl["entry"] * cl["qty"]).sum()
    return {"n": len(df), "closed": len(cl), "open": len(op), "win": None if cl.empty else (cl["ret"] > 0).mean() * 100, "pnl": float(cl["pnl"].sum()),
            "ret": None if not inv else float(cl["pnl"].sum() / inv * 100), "avg": None if cl.empty else float(cl["ret"].mean()), "open_pnl": float(open_pnl)}


def compare(last_close: dict | None = None, strategies: list[str] | None = None) -> pd.DataFrame:
    """전략 비교표(각 전략의 이번 장부): 거래·청산·승률·평균 수익률·실현 손익·열린 포지션·규칙."""
    st = settings()
    rows = []
    for k in (strategies or list(STRATEGIES)):
        c = st[k]
        s = summary(trades(book(k), k), last_close)
        rows.append({"전략": STRATEGIES[k]["name"], "key": k, "켜짐": "✅" if c["on"] else "⏸", "규칙": rule_text(c, k), "거래": s["n"], "청산": s["closed"],
                     "승률(%)": s["win"], "평균 수익률(%)": s["avg"], "청산 수익률(%)": s["ret"], "실현 손익($)": s["pnl"], "열린": s["open"], "평가 손익($)": s["open_pnl"]})
    return pd.DataFrame(rows)


def by_signal(df: pd.DataFrame) -> pd.DataFrame:
    """신호(순위 구성)가 있었을 때 vs 없었을 때 청산 수익률 — 가중치 조정 참고용(종합 순위 전략)."""
    cl = df[df["status"] == "closed"]
    if cl.empty:
        return pd.DataFrame()
    rows = []
    parts = [json.loads(p or "{}") for p in cl["parts"]]
    for k in sorted({k for p in parts for k in p}):
        on = [r for r, p in zip(cl["ret"], parts) if p.get(k)]
        off = [r for r, p in zip(cl["ret"], parts) if not p.get(k)]
        rows.append({"신호": k, "있을 때 거래": len(on), "있을 때 평균(%)": None if not on else sum(on) / len(on),
                     "없을 때 거래": len(off), "없을 때 평균(%)": None if not off else sum(off) / len(off)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 아침 작업
def daily(out=print) -> dict:
    """아침 작업: 열린 포지션 청산 판정(세션 기록 + 일봉 · 저금통 기준 이탈) → 종합 순위 · PICK 유력 · 저금통 저점 매수.
    (장마감·애프터 전략의 매수는 스캐너가 장중·애프터에 한다)"""
    import market
    import rank
    st = settings()
    with closing(db.connect()) as conn:
        ensure(conn)
        held = [x[0] for x in conn.execute("SELECT DISTINCT ticker FROM pt_trades WHERE status='open'")]
    try:
        rk = rank.compute() if (st["rank"]["on"] or st.get("rank6", {}).get("on")) else pd.DataFrame()
    except Exception as e:  # noqa: BLE001
        out(f"가상매매: 종합 순위 계산 실패({e})")
        rk = pd.DataFrame()
    piggy_tk: list[str] = []
    breakers: set[str] = set()
    try:
        import piggy
        piggy_tk = list(piggy.items()["ticker"]) if st["piggy"]["on"] else []
        breakers = piggy.rule_breakers()
    except Exception as e:  # noqa: BLE001
        out(f"가상매매: 저금통 확인 실패({e})")
    master_tk: list[str] = []
    if st.get("master", {}).get("on"):
        try:
            with closing(db.connect()) as conn:
                master_tk = [r["ticker"] for r in master_candidates(conn, date.today().isoformat())]
        except Exception as e:  # noqa: BLE001
            out(f"가상매매: 스승 눌림목 후보 확인 실패({e})")
    rk6_tk = [] if (rk.empty or "score6" not in rk.columns or not st.get("rank6", {}).get("on")) else list(rk.sort_values(["score6", "urgency"], ascending=False)["ticker"].head(int(st["rank6"]["n"])))
    tick = list(dict.fromkeys(held + ([] if rk.empty else list(rk["ticker"].head(int(st["rank"]["n"])))) + rk6_tk + piggy_tk + master_tk))
    bars = market.download_daily(tick, period="3mo") if tick else {}  # 3개월: 병합 보정·보관소 겹침 확인에 충분
    closed = update(bars, piggy_out=breakers)
    last = {t: float(df["Close"].dropna().iloc[-1]) for t, df in bars.items() if df is not None and not df.dropna(subset=["Close"]).empty}
    lastday = max((df.index[-1].strftime("%Y-%m-%d") for df in bars.values() if df is not None and len(df)), default=date.today().isoformat())
    bought = {"rank": [] if rk.empty else open_new(rk, last, lastday)}
    if st.get("rank6", {}).get("on") and not rk.empty:
        try:
            bought["rank6"] = open_new(rk, last, lastday, "rank6")
        except Exception as e:  # noqa: BLE001
            out(f"가상매매: 순위(⑥ 반영) 매수 실패({e})")
    if st["pick"]["on"]:
        try:
            import pick30
            bought["pick"] = open_pick(pick30.scan(), lastday)
        except Exception as e:  # noqa: BLE001
            out(f"가상매매: PICK 매수 실패({e})")
    if st["piggy"]["on"]:
        try:
            bought["piggy"] = open_piggy(last, lastday)
        except Exception as e:  # noqa: BLE001
            out(f"가상매매: 저금통 매수 실패({e})")
    if st.get("master", {}).get("on"):
        try:
            bought["master"] = open_master(lastday, last)
        except Exception as e:  # noqa: BLE001
            out(f"가상매매: 스승 눌림목 매수 실패({e})")
    out("가상매매: 청산 " + str(closed) + " · 매수 " + " / ".join(f"{STRATEGIES[k]['name']} {', '.join(v) or '-'}" for k, v in bought.items()))
    return {"closed": closed, "bought": bought}
