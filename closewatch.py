"""장마감 펌핑 체크리스트(토스증권 기준).

퀀트 스냅샷과는 **기준이 다른 별도 체크리스트**입니다(스냅샷 점수·모델과 섞이지 않음).
정규장 중 스캐너가 후보(오늘 크게 하락한 종목)의 아래 데이터를 사이클마다 기록하고, 대시보드가 기준값(슬라이더)으로 판정합니다.

토스증권 데이터(Open API)
  낙폭·전일 종가 = 토스 1분봉/일봉, 거래량 배수 = 토스 오늘 거래량 / 토스 20일 일봉 평균(출처 통일),
  거래량 폭발 후 감소 = 1분봉 60분 합계의 피크 대비 최근 값, 공급 제한 = 토스 발행주식수,
  체결강도 = 토스 실시간 웹소켓(체결·호가)으로 계산: 체결가를 그 순간의 호가와 비교해 매수/매도 체결량을 나눈 비(토스 화면의 체결강도와 같은 정의, 추정치. tossws.py)
  — 웹소켓 데이터가 부족하면 1분봉 방향 기반 추정으로 대체(출처를 항목에 표시),
  매도 호가 얇아짐·매도벽 = 호가 깊이의 시계열(웹소켓 분 단위, 없으면 REST 샘플)
SEC 공시(토스에는 없음, 키워드 판정이라 원문 확인 필요)
  장중 신규 희석 공시, 워런트 공시, 최근 자금조달 유형(공모/사모/ELOC/CB/ATM)과 '출회 제한' 여부(사모·ELOC의 재판매 등록 전/대기/효력 발생)
거래정지(halts.py: 업킷 API, 실패 시 나스닥 공식 RSS): 하킷(하한)·상킷(상한) = LULD 정지의 밴드 가격을 정지 직전 가격과 비교한 추정
공매도(shortdata.py): FINRA 일별 공매도 거래량(당일치는 장 마감 뒤)·IBKR 대차 수수료·가능 수량(+ Fintel 키가 있으면 공매도 잔고) — 참고 항목이라 등급에는 반영하지 않음
확인 불가로 두는 경우: 각 데이터가 없거나 조회에 실패하면 '➖'(충족으로도 위험으로도 세지 않음)
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import db
import halts
import market
import sec

log = logging.getLogger("closewatch")
ET = ZoneInfo("America/New_York")

DDL = [
    """CREATE TABLE IF NOT EXISTS close_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, date TEXT NOT NULL, ticker TEXT NOT NULL,
        price REAL, best_ask REAL, best_bid REAL, ask_depth_sh REAL, ask_depth_usd REAL, bid_depth_usd REAL,
        n_ask INTEGER, top_ask_ratio REAL)""",
    "CREATE INDEX IF NOT EXISTS idx_close_samples ON close_samples (date, ticker, ts)",
    "CREATE TABLE IF NOT EXISTS close_state (date TEXT NOT NULL, ticker TEXT NOT NULL, metrics TEXT, updated_at TEXT, PRIMARY KEY (date, ticker))",
    """CREATE TABLE IF NOT EXISTS close_flow (
        minute TEXT NOT NULL, ticker TEXT NOT NULL, date TEXT NOT NULL, buy_sh REAL, sell_sh REAL, mid_sh REAL, n_trades INTEGER,
        ask_usd_avg REAL, ask_usd_last REAL, n_books INTEGER, PRIMARY KEY (minute, ticker))""",
    "CREATE INDEX IF NOT EXISTS idx_close_flow ON close_flow (date, ticker, minute)",
    "CREATE TABLE IF NOT EXISTS close_filing_cache (accession TEXT PRIMARY KEY, tags TEXT, fetched_at TEXT)",
    """CREATE TABLE IF NOT EXISTS close_watchlist (date TEXT NOT NULL, kind TEXT NOT NULL, ticker TEXT NOT NULL, rank INTEGER, change_pct REAL, price REAL,
        at TEXT, PRIMARY KEY (date, kind, ticker))""",  # kind: live(현재 순위, 매 사이클 갱신) / frozen(마감 1시간 전 고정)
]

DEFAULT_PARAMS = {"drop": -20.0, "vol_mult": 3.0, "decay": 0.5, "cs_late": 110.0, "cs_delta": 10.0, "ask_thin": 0.6, "short_ratio": 55.0,
                  "ask_minutes": 5.0, "wall_ratio": 3.0, "shares_max": 20e6, "best_min": 5, "cand_min": 4}
FIN_WINDOW_DAYS = 7

PATTERN_KEYS = ["drop", "vol", "decay", "buy", "ask_thin", "no_wall"]
DIL_TAGS = {"ATM", "ELOC", "CB", "OFFERING", "WARRANT", "PIPE", "REG_DIRECT"}
EXT_PATTERNS = {
    "PIPE": [re.compile(p, re.S | re.I) for p in (r"private placement", r"unregistered (?:sale|shares|securities)", r"section 4\(a\)\(2\)",
                                                  r"regulation d", r"rule 506", r"restricted securities")],
    "REG_DIRECT": [re.compile(p, re.S | re.I) for p in (r"registered direct offering", r"underwritten (?:public )?offering", r"public offering price")],
    "RESALE_REG": [re.compile(p, re.S | re.I) for p in (r"resale registration statement", r"registration rights agreement", r"register the resale",
                                                         r"resale of the (?:shares|securities)")],
}
REG_FORMS = {"S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-1/A", "F-3", "F-3/A"}
FIN_FORMS = ("8-K", "8-K/A", "6-K")


def ensure_tables(conn=None) -> None:
    if conn is None:
        with closing(db.connect()) as c:
            ensure_tables(c)
        return
    for ddl in DDL:
        conn.execute(ddl)
    conn.commit()


# ---------------------------------------------------------------- 토스 데이터 계산 (순수 함수)
def regular(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """정규장(동부시간 09:30~16:00) 1분봉만."""
    if df is None or df.empty:
        return df
    idx = df.index.tz_convert(ET) if df.index.tz is not None else df.index
    t = idx.hour * 60 + idx.minute
    return df[(t >= 570) & (t < 960)]


def daily_context(daily: list[dict], reg: pd.DataFrame | None) -> dict | None:
    """토스 일봉(최신순)에서 '오늘 봉'을 찾아 전일 종가와 20일 평균 거래량을 구한다.
    오늘 봉 판별: 종가가 정규장 마지막 1분봉 종가와 3% 이내이고 고가/저가가 정규장 범위를 (거의) 포함. 못 찾으면 None(판정 불가)."""
    if not daily or reg is None or len(reg) < 3:
        return None
    last = float(reg["Close"].iloc[-1])
    hi, lo = float(reg["High"].max()), float(reg["Low"].min())
    for i, c in enumerate(daily[:3]):
        try:
            close, h, l = float(c["closePrice"]), float(c["highPrice"]), float(c["lowPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if last > 0 and abs(close / last - 1) <= 0.03 and h >= hi * 0.97 and l <= lo * 1.03:
            hist = daily[i + 1:i + 21]
            if not hist:
                return None
            vols = [float(x["volume"]) for x in hist if x.get("volume") is not None]
            return {"prev_close": float(hist[0]["closePrice"]), "avg_vol20": float(np.mean(vols)) if vols else None,
                    "prev_volume": float(hist[0]["volume"]) if hist[0].get("volume") is not None else None,
                    "n_hist": len(vols), "today_daily_volume": float(c["volume"]) if c.get("volume") is not None else None}
    return None


def volume_stats(reg: pd.DataFrame, avg20: float | None) -> dict:
    vol = reg["Volume"].astype(float)
    total = float(vol.sum())
    roll = vol.rolling("60min").sum()
    peak = float(roll.max())
    peak_end = roll.idxmax()
    typical_hour = avg20 / 6.5 if avg20 else None
    out = {"vol_total": total, "peak60": peak, "last60": float(roll.iloc[-1]), "decay": float(roll.iloc[-1] / peak) if peak > 0 else None,
           "vol_mult": total / avg20 if avg20 else None, "burst_mult": peak / typical_hour if typical_hour else None,
           "mins_since_peak": float((reg.index[-1] - peak_end).total_seconds() / 60)}
    try:  # ✅ 스승님 ①: 종가 체크는 5분봉 — 거래량과 OBV 가 같이 올라야 함(돈 없는 거래량 = 사팔이)
        import setup3
        if "Close" in reg:
            b5 = reg.resample("5min").agg({"Close": "last", "Volume": "sum"}).dropna(subset=["Close"])
            mf = setup3.money_flow(b5)
            out.update({"obv5_ok": mf.get("obv_up", mf["ok"]) if mf["ok"] is not None else None, "obv5_strong": mf["strong"], "obv5_label": mf["label"], "obv5_ratio": mf["obv_ratio"]})  # 장마감 관문은 최소 조건(돈은 들어와 있어야)
    except Exception:  # noqa: BLE001
        pass
    return out


def buy_stats(reg: pd.DataFrame) -> dict:
    """체결강도 추정(1분봉 종가 방향 기반 매수 비중, %): 최근 30분 vs 그 전 60분. 토스 체결에는 매수/매도 구분이 없어 추정치."""
    end = reg.index[-1]
    late = reg[reg.index > end - pd.Timedelta(minutes=30)]
    prior = reg[(reg.index <= end - pd.Timedelta(minutes=30)) & (reg.index > end - pd.Timedelta(minutes=90))]
    return {"buy_late": market.buy_pressure(late), "buy_prior": market.buy_pressure(prior)}


def volume_series(reg: pd.DataFrame, minutes: int = 10) -> list[dict]:
    g = reg["Volume"].astype(float).resample(f"{minutes}min").sum()
    return [{"t": ts.strftime("%H:%M"), "v": float(v)} for ts, v in g.items()]


def ask_stats(book: dict | None, recent_vol_per_min: float | None) -> dict | None:
    asks = (book or {}).get("asks") or []
    bids = (book or {}).get("bids") or []
    if not asks:
        return None
    vols = [v for _, v in asks]
    sh, usd = float(sum(vols)), float(sum(p * v for p, v in asks))
    top_ratio = None
    if len(vols) >= 3:  # 가장 큰 호가 잔량이 나머지 평균의 몇 배인가 (단계가 3개 이상일 때만 의미)
        top = max(vols)
        rest = (sum(vols) - top) / (len(vols) - 1)
        top_ratio = float(top / rest) if rest > 0 else None
    best_ask = min(p for p, _ in asks)
    best_bid = max((p for p, _ in bids), default=None)
    return {"ask_depth_sh": sh, "ask_depth_usd": usd, "n_ask": len(asks), "top_ask_ratio": top_ratio, "best_ask": float(best_ask),
            "best_bid": float(best_bid) if best_bid is not None else None, "bid_depth_usd": float(sum(p * v for p, v in bids)),
            "ask_minutes": float(sh / recent_vol_per_min) if recent_vol_per_min and recent_vol_per_min > 0 else None}


def thinning(samples: list[tuple[datetime, float]]) -> float | None:
    """매도 호가 깊이(달러) 현재 / 15분 이상 이전 샘플의 중앙값. 작을수록 얇아진 것. 샘플이 부족하면 None."""
    if len(samples) < 4:
        return None
    samples = sorted(samples)
    last_ts, cur = samples[-1]
    base = [d for ts, d in samples[:-1] if 15 * 60 <= (last_ts - ts).total_seconds() <= 90 * 60]
    if len(base) < 2:
        return None
    med = float(np.median(base))
    return float(cur / med) if med > 0 else None


def _cs(buy: float, sell: float) -> float | None:
    """체결강도(%) = 매수 체결량 / 매도 체결량 × 100. 매도가 0이면 999 로 제한."""
    if buy + sell <= 0:
        return None
    return min(buy / sell * 100, 999.0) if sell > 0 else 999.0


def buy_ratio_to_cs(r: float | None) -> float | None:
    """분봉 기반 매수 비중(%)을 체결강도 척도로 변환(55% → 122). 웹소켓 데이터가 없을 때만 쓰는 대체값."""
    if r is None:
        return None
    return 999.0 if r >= 100 else r / (100 - r) * 100


def flow_stats(conn, day: str, ticker: str, min_trades: int = 5) -> dict | None:
    """토스 웹소켓 집계(close_flow)에서 체결강도: 수집 시작 후 누적 / 최근 30분 / 그 전 60분. 체결이 min_trades 건 미만인 구간은 None."""
    rows = conn.execute("SELECT minute, buy_sh, sell_sh, n_trades FROM close_flow WHERE date=? AND ticker=? ORDER BY minute", (day, ticker)).fetchall()
    if not rows:
        return None
    df = pd.DataFrame([tuple(r) for r in rows], columns=["minute", "buy", "sell", "n"])
    df["t"] = pd.to_datetime(df["minute"], utc=True)
    end = df["t"].iloc[-1]

    def win(sub):
        return _cs(float(sub["buy"].sum()), float(sub["sell"].sum())) if int(sub["n"].sum()) >= min_trades else None
    return {"cs_cum": win(df), "cs_late": win(df[df["t"] > end - pd.Timedelta(minutes=30)]),
            "cs_prior": win(df[(df["t"] <= end - pd.Timedelta(minutes=30)) & (df["t"] > end - pd.Timedelta(minutes=90))]),
            "flow_first": df["t"].iloc[0].isoformat(), "flow_last": end.isoformat(), "flow_trades": int(df["n"].sum())}


def ws_ask_series(conn, day: str, ticker: str) -> list[tuple[datetime, float]]:
    rows = conn.execute("SELECT minute, ask_usd_avg FROM close_flow WHERE date=? AND ticker=? AND ask_usd_avg IS NOT NULL ORDER BY minute", (day, ticker)).fetchall()
    return [(datetime.fromisoformat(r["minute"]), float(r["ask_usd_avg"])) for r in rows]


# ---------------------------------------------------------------- SEC (토스에 없음)
def scan_ext(text: str, form: str) -> list[str]:
    tags = set(sec.scan_text(text, form))
    head = text[:sec.HEAD_CHARS] if form.startswith("424B") else text
    for tag, pats in EXT_PATTERNS.items():
        if any(p.search(head) for p in pats):
            tags.add(tag)
    tags.add("EXT1")
    return sorted(tags)


def tags_for(client, conn, f: dict) -> list[str]:
    row = conn.execute("SELECT tags FROM close_filing_cache WHERE accession=?", (f["accession"],)).fetchone()
    if row:
        return json.loads(row["tags"])
    tags = scan_ext(client.fetch_text(f["url"]), f["form"])
    conn.execute("INSERT OR REPLACE INTO close_filing_cache (accession,tags,fetched_at) VALUES (?,?,?)", (f["accession"], json.dumps(tags), db.utcnow_iso()))
    conn.commit()
    return tags


def classify_financing(filings: list[dict], tags_of, today: date, window_days: int = FIN_WINDOW_DAYS) -> dict | None:
    """최근 window_days 일 안의 가장 최근 자금조달 이벤트와 '출회 가능 여부'.
    출회 즉시 가능: 공모/등록직접/ATM/전환사채. 출회 제한: 사모(PIPE)·ELOC 중 재판매 등록(S-1/S-3 등) 제출 전 또는 효력(EFFECT) 발생 전."""
    cutoff = (today - timedelta(days=window_days)).isoformat()
    for f in filings:
        if f["filed"] < cutoff or not (f["form"].startswith("424B") or f["form"] in FIN_FORMS):
            continue
        tg = set(tags_of(f))
        if not tg & (DIL_TAGS - {"WARRANT"}) and not f["form"].startswith("424B"):  # 424B(투자설명서 보충)는 서류 종류만으로 증권 발행으로 본다
            continue
        if "ATM" in tg:
            typ, immediate = "ATM", True
        elif "CB" in tg:
            typ, immediate = "전환사채", True
        elif "REG_DIRECT" in tg or f["form"].startswith("424B"):
            typ, immediate = "공모/등록직접", True
        elif "ELOC" in tg:
            typ, immediate = "ELOC", False
        elif "PIPE" in tg:
            typ, immediate = "사모(PIPE)", False
        else:
            typ, immediate = "공모/기타", True  # 유형을 못 가리면 보수적으로 즉시 출회 가능으로 본다
        if immediate:
            sellable, label = "immediate", "즉시 출회 가능"
        else:
            regs = [g for g in filings if g["form"] in REG_FORMS and g["filed"] >= f["filed"]]
            if not regs:
                sellable, label = "restricted", "출회 제한(재판매 등록 전)"
            elif any(g["form"] == "EFFECT" and g["filed"] >= min(r["filed"] for r in regs) for g in filings):
                sellable, label = "free", "출회 가능(등록 효력 발생)"
            else:
                sellable, label = "restricted", "출회 제한(등록 대기)"
        return {"type": typ, "date": f["filed"], "form": f["form"], "url": f["url"], "sellable": sellable, "label": label}
    return None


def sec_context(client, conn, ticker: str, today: date) -> dict:
    cik = client.cik_for(ticker)
    if not cik:
        return {"error": "SEC CIK 없음(ETF/ADR/신규상장 가능성)"}
    filings = sec.recent_filings(client.submissions(cik), cik)
    errors = 0

    def tags_of(f):
        nonlocal errors
        try:
            return tags_for(client, conn, f)
        except Exception as e:  # noqa: BLE001
            errors += 1
            log.warning("%s %s 본문 확인 실패: %s", ticker, f["accession"], e)
            return []
    today_iso = today.isoformat()
    todays = [f for f in filings if f["filed"] == today_iso and (f["form"].startswith("424B") or f["form"] in FIN_FORMS or f["form"] in REG_FORMS)][:6]
    intraday = [{"form": f["form"], "url": f["url"], "tags": [t for t in tags_of(f) if t in DIL_TAGS]} for f in todays]
    cutoff = (today - timedelta(days=FIN_WINDOW_DAYS)).isoformat()
    recent = [f for f in filings if f["filed"] >= cutoff and (f["form"].startswith("424B") or f["form"] in FIN_FORMS or f["form"] in REG_FORMS)][:10]
    warrants = [{"form": f["form"], "date": f["filed"], "url": f["url"]} for f in recent if "WARRANT" in tags_of(f)]
    return {"intraday": intraday, "financing": classify_financing(filings, tags_of, today), "warrants": warrants, "errors": errors}


# ---------------------------------------------------------------- 평가 (대시보드에서 기준값을 바꿔가며 판정)
def _st(ok: bool | None) -> str:
    return "unknown" if ok is None else ("pass" if ok else "fail")


def evaluate(m: dict, params: dict | None = None) -> dict:
    p = {**DEFAULT_PARAMS, **(params or {})}
    items: list[dict] = []

    def add(key, name, status, value, group):
        items.append({"key": key, "name": name, "status": status, "value": value, "group": group})
    f = lambda x, fmt: "확인 불가" if x is None else fmt.format(x)  # noqa: E731

    d = m.get("drop_pct")
    add("drop", f"과대 낙폭 {p['drop']:g}% 이하", _st(None if d is None else d <= p["drop"]), f(d, "{:.1f}% (토스 전일 종가 대비)"), "pattern")
    vm = m.get("vol_mult")
    add("vol", f"거래량 폭발 {p['vol_mult']:g}배 이상", _st(None if vm is None else vm >= p["vol_mult"]), f(vm, "{:.2f}배 (토스 20일 평균 대비)"), "pattern")
    dc = m.get("decay")
    add("decay", f"폭발 후 거래량 감소 (최근 60분 ≤ 피크의 {p['decay']:.0%})", _st(None if dc is None else dc <= p["decay"]),
        f(dc, "최근 60분이 피크의 {:.0%}"), "pattern")
    cl, cp, cc = m.get("cs_late"), m.get("cs_prior"), m.get("cs_cum")
    ok_cs = None if cl is None else (cl >= p["cs_late"] and (cp is None or cl - cp >= p["cs_delta"]))
    cs_txt = "확인 불가" if cl is None else (f"최근 30분 {cl:.0f}% / 그 전 60분 {('-' if cp is None else f'{cp:.0f}%')}" + ("" if cc is None else f" · 수집 후 누적 {cc:.0f}%")
                                          + f" ({m.get('cs_source') or '-'})")
    add("buy", f"체결강도 상승 (최근 30분 ≥ {p['cs_late']:g}% 이고 이전 대비 +{p['cs_delta']:g}%p)", _st(ok_cs), cs_txt, "pattern")
    th = m.get("thin_ratio")
    add("ask_thin", f"매도 호가 얇아짐 (현재 ≤ 이전의 {p['ask_thin']:.0%})", _st(None if th is None else th <= p["ask_thin"]),
        "샘플 부족(마감 전 30~60분 뒤부터 판정)" if th is None else f"이전 중앙값의 {th:.0%} (샘플 {m.get('n_samples', 0)}개)", "pattern")
    am, tr = m.get("ask_minutes"), m.get("top_ask_ratio")
    if am is None:
        wall_ok, wall_txt = None, "확인 불가"
    else:
        wall_ok = am <= p["ask_minutes"] and (tr is None or tr < p["wall_ratio"])
        wall_txt = f"매도잔량 = 최근 거래 {am:.1f}분치" + ("" if tr is None else f", 최대 호가가 나머지 평균의 {tr:.1f}배")
    add("no_wall", f"매도벽 없음 (매도잔량 ≤ 거래 {p['ask_minutes']:g}분치, 최대 호가 < 평균 {p['wall_ratio']:g}배)", _st(wall_ok), wall_txt, "pattern")

    o5 = m.get("obv5_ok")
    add("money5", "돈 들어온 거래량 (5분봉 OBV·거래량 동반 상승 — 스승님 ①)", _st(o5),
        "확인 불가(5분봉 부족)" if o5 is None else (m.get("obv5_label") or "") + ("" if m.get("obv5_ratio") is None else f" · OBV 순유입 {m['obv5_ratio'] * 100:+.0f}%"), "money")
    ds = m.get("dilution_status")
    add("no_atm_cb", "ATM·전환사채 정황 없음 (SEC 키워드)", _st(None if ds in (None, "UNKNOWN") else ds not in ("ATM", "CB")),
        "확인 불가" if ds in (None, "UNKNOWN") else {"ATM": "ATM 정황 있음", "CB": "전환사채 정황 있음"}.get(ds, "미검출"), "dilution")
    intr = m.get("intraday_filings")
    if intr is None:
        add("no_intraday", "장중 신규 희석 공시 없음 (SEC)", "unknown", "확인 불가(SEC 조회 실패)", "dilution")
    else:
        hits = [x for x in intr if x.get("tags")]
        add("no_intraday", "장중 신규 희석 공시 없음 (SEC)", "fail" if hits else "pass",
            f"오늘 공시 {len(intr)}건 중 희석 정황 {len(hits)}건" + ("".join(f" · {x['form']}({','.join(x['tags'])})" for x in hits)), "dilution")
    fin = m.get("financing")
    if fin is None:
        add("fin_restricted", f"최근 {FIN_WINDOW_DAYS}일 자금조달이 '출회 제한형'(사모/ELOC, 재판매 등록 전·대기)", "na", "최근 자금조달 공시 없음", "bonus")
    else:
        add("fin_restricted", f"최근 {FIN_WINDOW_DAYS}일 자금조달이 '출회 제한형'(사모/ELOC, 재판매 등록 전·대기)",
            "pass" if fin["sellable"] == "restricted" else "fail", f"{fin['date']} {fin['type']} → {fin['label']}", "bonus")
    so = m.get("shares_out")
    add("supply", f"공급 제한 (발행주식수 ≤ {p['shares_max'] / 1e6:g}백만 주, 토스)", _st(None if so is None else so <= p["shares_max"]),
        f(None if so is None else so / 1e6, "발행주식수 {:.2f}백만 주"), "bonus")
    wf = m.get("warrant_filings")
    if wf is None:
        add("no_warrant", f"워런트 발행 공시 없음 (SEC, 최근 {FIN_WINDOW_DAYS}일)", "unknown", "확인 불가(SEC 조회 실패)", "dilution")
    else:
        add("no_warrant", f"워런트 발행 공시 없음 (SEC, 최근 {FIN_WINDOW_DAYS}일)", "fail" if wf else "pass",
            "없음" if not wf else f"{len(wf)}건 · " + ", ".join(f"{x['date']} {x['form']}" for x in wf[:3]), "dilution")
    hs = m.get("halts")
    if hs is None:
        add("halt", "하킷·상킷 이력 (업킷 거래정지)", "unknown", "확인 불가(피드 조회 실패 또는 꺼짐)", "info")
    elif not hs:
        add("halt", "하킷·상킷 이력 (업킷 거래정지)", "na", "오늘 거래정지 없음", "info")
    else:
        add("halt", "하킷(하한 정지) 발생 (업킷 거래정지)", "pass" if m.get("halt_down") else "na",
            f"하한(하킷) {m.get('halt_down', 0)}회 · 상한(상킷) {m.get('halt_up', 0)}회 · 기타 {m.get('halt_other', 0)}회" + (" · 현재 정지 중" if m.get("halt_active") else "")
            + " | " + ", ".join(f"{x['time'][6:]} {x['dir'] or x['reason']}" for x in hs[:4]), "info")
    sh = m.get("short")
    if sh is None:
        add("short", "공매도 (FINRA·IBKR)", "unknown", m.get("short_note") or "확인 불가", "info")
    else:
        ratio, parts = sh.get("sv_ratio"), []
        if ratio is not None:
            parts.append(f"{sh.get('sv_date') or '?'} 공매도 거래량 {sh['sv_short']:,.0f}주 ({ratio:.0f}%, 5일 {sh['sv_avg5_ratio']:.0f}%)")
        if sh.get("borrow_fee") is not None:
            parts.append(f"대차 수수료 {sh['borrow_fee']:.1f}%")
        if sh.get("borrow_avail") is not None:
            parts.append("대차 가능: 최신 파일에 없음(바닥 가능성)" if sh.get("borrow_stale") else
                         f"대차 가능 {sh['borrow_avail']:,.0f}주" + (f"(오늘 처음 대비 {sh['borrow_avail_chg_pct']:+.0f}%)" if sh.get("borrow_avail_chg_pct") is not None else ""))
        if sh.get("si_shares") is not None:
            parts.append(f"공매도 잔고 {sh['si_shares']:,.0f}주" + (f"({sh['si_pct_float']:.1f}% float)" if sh.get("si_pct_float") is not None else ""))
        add("short", f"공매도 압력 (직전 거래일 공매도 거래량 비중 ≥ {p['short_ratio']:g}%, FINRA·IBKR)", _st(None if ratio is None else ratio >= p["short_ratio"]),
            " · ".join(parts) or "값 없음", "info")

    pv, vt, dp = m.get("prev_volume"), m.get("vol_total"), m.get("drop_pct")  # 스승님 꿀팁: 전일 대비 거래량 급증 + 하락 = 분산(좋지 않은 신호)
    if pv and vt is not None and dp is not None:
        ratio = vt / pv
        dist = ratio >= p.get("dist_spike", 2.5) and dp < 0
        add("dist", f"분산 신호 없음 (전일 대비 거래량 {p.get('dist_spike', 2.5):g}배 이상 + 하락 = 분산, 장중 기준)", "fail" if dist else "pass",
            f"전일 대비 거래량 {ratio:.1f}배 · 등락 {dp:+.1f}%" + (" — 분산(차익실현) 진행 중" if dist else ""), "info")
    else:
        add("dist", "분산 신호 없음 (전일 대비 거래량 급증 + 하락 = 분산, 장중 기준)", "unknown", "전일 거래량 확인 불가", "info")
    by = {i["key"]: i["status"] for i in items}
    n_pat = sum(1 for k in PATTERN_KEYS if by[k] == "pass")
    if by["drop"] != "pass":
        grade = "낙폭 미달"
    elif by["no_atm_cb"] == "fail" or by["no_intraday"] == "fail":
        grade = "희석 위험"
    elif n_pat >= p["best_min"] and (by["fin_restricted"] == "pass" or by["supply"] == "pass") and by["no_intraday"] == "pass" and by.get("money5") != "fail":
        grade = "BEST"  # 5분봉에 돈이 안 들어왔으면(사팔이) BEST 불가 — 스승님 ①
    elif n_pat >= p["cand_min"] or (n_pat >= p["best_min"] and by["no_intraday"] != "pass"):  # 장중 희석을 확인 못 했으면 BEST 불가(후보까지)
        grade = "후보"
    elif n_pat >= 2:
        grade = "관찰"
    else:
        grade = "미달"
    return {"items": items, "grade": grade, "n_pattern": n_pat, "n_pattern_total": len(PATTERN_KEYS)}


GRADE_ORDER = {"BEST": 0, "후보": 1, "관찰": 2, "미달": 3, "희석 위험": 4, "낙폭 미달": 5}


# ---------------------------------------------------------------- 수집 (스캐너가 정규장 중 사이클마다 호출)
def build_metrics(reg: pd.DataFrame, ctx: dict | None, book: dict | None, samples: list, shares_out: float | None,
                  dilution_status: str | None, sec_ctx: dict | None, price: float, flow: dict | None = None,
                  halt_sum: dict | None = None, short: dict | None = None, short_note: str | None = None) -> dict:
    m: dict = {"price": price, "bars": int(len(reg)), "dilution_status": dilution_status, "shares_out": shares_out,
               "last_bar": reg.index[-1].isoformat(), "prev_close_source": "toss" if ctx else None}
    avg20 = ctx["avg_vol20"] if ctx else None
    m["prev_close"] = ctx["prev_close"] if ctx else None
    m["prev_volume"] = ctx.get("prev_volume") if ctx else None
    m["drop_pct"] = (price / ctx["prev_close"] - 1) * 100 if ctx and ctx["prev_close"] else None
    m["avg_vol20"] = avg20
    m.update(volume_stats(reg, avg20))
    bs = buy_stats(reg)
    if flow and flow.get("cs_late") is not None:  # 토스 웹소켓(체결가↔호가)으로 계산한 체결강도
        m.update({"cs_late": flow["cs_late"], "cs_prior": flow["cs_prior"], "cs_cum": flow["cs_cum"], "cs_source": "토스 웹소켓(체결가↔호가)",
                  "flow_first": flow["flow_first"], "flow_trades": flow["flow_trades"]})
    else:  # 웹소켓 데이터가 부족하면 1분봉 방향 기반 추정으로 대체
        m.update({"cs_late": buy_ratio_to_cs(bs["buy_late"]), "cs_prior": buy_ratio_to_cs(bs["buy_prior"]), "cs_cum": None, "cs_source": "1분봉 추정(웹소켓 데이터 부족)"})
    m["vol_series"] = volume_series(reg)
    end = reg.index[-1]
    recent = reg[reg.index > end - pd.Timedelta(minutes=30)]
    per_min = float(recent["Volume"].sum() / 30) if len(recent) else None
    a = ask_stats(book, per_min)
    if a:
        m.update(a)
    m["thin_ratio"] = thinning(samples)
    m["n_samples"] = len(samples)
    if sec_ctx and "error" not in sec_ctx:
        m["intraday_filings"] = sec_ctx["intraday"]
        m["warrant_filings"] = sec_ctx.get("warrants")
        m["financing"] = sec_ctx["financing"]
        m["sec_errors"] = sec_ctx["errors"]
    else:
        m["intraday_filings"] = None
        m["warrant_filings"] = None
        m["financing"] = None
        m["sec_error"] = (sec_ctx or {}).get("error", "SEC 조회 실패")
    m["halts"] = None if halt_sum is None else halt_sum["halts"]
    if halt_sum is not None:
        m.update({k: halt_sum[k] for k in ("halt_down", "halt_up", "halt_other", "halt_active")})
    m["short"], m["short_note"] = short, short_note
    return m


# ---------------------------------------------------------------- 대상 종목: 토스 급하락 순위 → 마감 1시간 전 고정
EXCLUDED_TYPES = {"ETF", "FOREIGN_ETF", "ETN", "STOCK_WARRANTS", "INFRASTRUCTURE_FUND"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rate(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x * 100 if abs(x) <= 1.5 else x  # 비율(-0.35)로 오면 %로, 이미 %면 그대로


def losers_top(tc, top_n: int = 20) -> tuple[list[dict], int]:
    """토스 급하락 순위(TOP_LOSERS, 1일) 1~top_n위. ETF·ETN·워런트·우선주·비활성은 빼고 (목록, 뺀 개수)."""
    return ranked_top(tc, "TOP_LOSERS", "1d", top_n)


def ranked_top(tc, rank_type: str, duration: str, top_n: int = 20) -> tuple[list[dict], int]:
    """토스 순위 1~top_n위(보통주만). 반환: (목록, 뺀 개수)."""
    items = (tc.rankings(rank_type, "US", duration, max(top_n, 20)) or [])[:top_n]
    rows = []
    for i, it in enumerate(items, 1):
        sym = str(it.get("symbol") or "").strip().upper()
        if not sym:
            continue
        p = it.get("price") or {}
        last, base = _num_or_none(p.get("lastPrice")), _num_or_none(p.get("basePrice"))
        chg = (last / base - 1) * 100 if last and base else _rate(p.get("changeRate"))
        rows.append({"ticker": sym, "rank": i, "change_pct": chg, "price": last})
    n_ex = 0
    if rows:
        try:
            info = {x["symbol"]: x for x in tc.stocks([r["ticker"] for r in rows])}
            bad = {s for s, x in info.items() if x.get("securityType") in EXCLUDED_TYPES or x.get("isCommonShare") is False or x.get("status", "ACTIVE") != "ACTIVE"}
            n_ex = sum(1 for r in rows if r["ticker"] in bad)
            rows = [r for r in rows if r["ticker"] not in bad]
        except Exception as e:  # noqa: BLE001
            log.warning("급하락 순위 종목 유형 확인 실패(필터 없이 사용): %s", e)
    return rows, n_ex


def _num_or_none(v) -> float | None:
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def save_list(conn, day: str, kind: str, rows: list[dict], at: datetime) -> None:
    ensure_tables(conn)
    conn.execute("DELETE FROM close_watchlist WHERE date=? AND kind=?", (day, kind))
    conn.executemany("INSERT INTO close_watchlist (date,kind,ticker,rank,change_pct,price,at) VALUES (?,?,?,?,?,?,?)",
                     [(day, kind, r["ticker"], r["rank"], r.get("change_pct"), r.get("price"), at.isoformat(timespec="seconds")) for r in rows])
    conn.commit()


def load_list(conn, day: str, kind: str) -> list[dict]:
    ensure_tables(conn)
    return [dict(r) for r in conn.execute("SELECT ticker, rank, change_pct, price, at FROM close_watchlist WHERE date=? AND kind=? ORDER BY rank", (day, kind))]


def regular_end_for(day: date) -> datetime:
    """그날 정규장 종료 시각: 스캐너가 토스 장 캘린더에서 저장한 값(조기 폐장 반영), 없으면 동부시간 16:00."""
    m = db.get_meta("us_regular_end")
    if m and m.get("value"):
        try:
            end = datetime.fromisoformat(m["value"])
            if end.astimezone(ET).date() == day:
                return end
        except ValueError:
            pass
    return datetime.combine(day, time(16, 0), ET)


def freeze_due(now: datetime, end: datetime, minutes_before: int) -> bool:
    return now >= end - timedelta(minutes=minutes_before)


def pick_shortlist(passing: list, min_drop: float, max_n: int) -> list[str]:
    cand = sorted((m["day_change_pct"], t) for t, m in passing if m.get("day_change_pct") is not None and m["day_change_pct"] <= min_drop)
    return [t for _, t in cand[:max_n]]


_DAILY: dict = {}  # (거래일, 티커) -> 토스 일봉(하루에 한 번만 받는다)


def load_samples(conn, day: str, ticker: str) -> list[tuple[datetime, float]]:
    rows = conn.execute("SELECT ts, ask_depth_usd FROM close_samples WHERE date=? AND ticker=? AND ask_depth_usd IS NOT NULL ORDER BY ts", (day, ticker)).fetchall()
    return [(datetime.fromisoformat(r["ts"]), float(r["ask_depth_usd"])) for r in rows]


def update(conn, tc, client, tickers: list[str], frames: dict | None = None, now: datetime | None = None,
           halts_list: list | None = None, fintel_client=None, intel_map: dict | None = None) -> int:
    """tickers 각각에 대해 토스 1분봉·일봉·호가와 SEC 공시를 모아 close_state 를 갱신한다. 반환: 갱신 종목 수."""
    import toss
    ensure_tables(conn)
    frames = dict(frames or {})
    missing = [t for t in tickers if t not in frames]
    if missing:
        frames.update(toss.fetch_intraday_many(tc, missing))
    shares: dict[str, float] = {}
    try:
        shares = {x["symbol"]: float(x["sharesOutstanding"]) for x in tc.stocks(tickers) if x.get("sharesOutstanding")}
    except Exception as e:  # noqa: BLE001
        log.warning("토스 발행주식수 조회 실패: %s", e)
    now_utc = now or datetime.now(timezone.utc)
    n = 0
    for t in tickers:
        try:
            reg = regular(frames.get(t))
            if reg is None or len(reg) < 10:
                continue
            day = reg.index[-1].astimezone(ET).date()
            key = (day.isoformat(), t)
            if key not in _DAILY:
                _DAILY[key] = tc.daily_candles(t, 25)
            for k in [k for k in _DAILY if k[0] != day.isoformat()]:
                _DAILY.pop(k, None)
            ctx = daily_context(_DAILY[key], reg)
            price = float(reg["Close"].iloc[-1])
            book = None
            try:
                book = tc.orderbook(t)
            except Exception as e:  # noqa: BLE001
                log.warning("%s 호가 조회 실패: %s", t, e)
            a = ask_stats(book, None)
            if a:  # 샘플은 매 사이클 누적한다 (얇아짐 판정용)
                conn.execute("INSERT INTO close_samples (ts,date,ticker,price,best_ask,best_bid,ask_depth_sh,ask_depth_usd,bid_depth_usd,n_ask,top_ask_ratio) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (now_utc.isoformat(timespec="seconds"), day.isoformat(), t, price, a["best_ask"], a["best_bid"],
                                                                 a["ask_depth_sh"], a["ask_depth_usd"], a["bid_depth_usd"], a["n_ask"], a["top_ask_ratio"]))
                conn.commit()
            samples = load_samples(conn, day.isoformat(), t)
            ws_series = ws_ask_series(conn, day.isoformat(), t)
            if len(ws_series) >= 4:  # 웹소켓 분 단위 시계열이 있으면 5분 간격 REST 샘플보다 우선
                samples = ws_series
            flow = flow_stats(conn, day.isoformat(), t)
            halt_sum = halts.summarize(halts_list, t, day, reg) if halts_list is not None else None
            im = (intel_map or {}).get(t)  # 공통 인텔(intel.py)이 이미 계산한 공매도·SEC 값이 있으면 그대로 쓴다(중복 호출 방지)
            short, short_note = None, "공매도 데이터 미연결"
            if im is not None and "short" in im:
                short, short_note = im.get("short"), im.get("short_note")
            elif fintel_client is not None:
                try:
                    s = fintel_client.summary(t)
                    short = s if any(s.get(k) is not None for k in ("sv_ratio", "borrow_fee", "borrow_avail", "si_shares")) else None
                    short_note = "; ".join(s["errors"]) or None
                except Exception as e:  # noqa: BLE001
                    log.warning("%s 공매도 데이터 조회 실패: %s", t, e)
                    short_note = f"공매도 데이터 조회 실패: {type(e).__name__}"
            if im is not None and im.get("sec") is not None:
                sctx = im["sec"]
            else:
                try:
                    sctx = sec_context(client, conn, t, day)
                except Exception as e:  # noqa: BLE001
                    log.warning("%s SEC 조회 실패: %s", t, e)
                    sctx = {"error": f"SEC 조회 실패: {type(e).__name__}"}
            dil = db.get_dilution(conn, t)
            m = build_metrics(reg, ctx, book, samples, shares.get(t), dil["status"] if dil else None, sctx, price, flow, halt_sum, short, short_note)
            conn.execute("INSERT OR REPLACE INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)",
                         (day.isoformat(), t, json.dumps(m, ensure_ascii=False, default=str), db.utcnow_iso()))
            conn.commit()
            n += 1
        except Exception:  # noqa: BLE001
            log.exception("%s 장마감 체크리스트 갱신 실패", t)
    return n
