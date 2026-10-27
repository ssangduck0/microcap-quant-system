"""⚡ 지금 분석 — 1분봉(장전·정규장·애프터 포함)으로 현재가·전일 종가 대비·정규장 마감·구간 변동폭·구간 내 위치·52주 위치와 신호 요약(급등·고점 이탈·지지 확인·거래량·변동성 주의).

세션(동부 시각): 장전 04:00~09:30 · 정규장 09:30~16:00 · 애프터 16:00~20:00. '구간'은 지금 세션(정규장 중이면 정규장, 애프터 중이면 애프터).
"""
from __future__ import annotations

import pandas as pd


def session_of(ts: pd.Timestamp) -> str:
    hm = ts.hour * 100 + ts.minute
    return "장전" if 400 <= hm < 930 else ("정규장" if 930 <= hm < 1600 else ("애프터" if 1600 <= hm < 2000 else "장외"))


def analyze(m1: pd.DataFrame, daily: pd.DataFrame | None = None, shares: float | None = None) -> dict | None:
    """m1: 1분봉(동부 시각 인덱스, 여러 날 가능) · daily: 1년 일봉(52주) · shares: 주식 수(시총용)."""
    m1 = m1.dropna(subset=["Close"])
    if m1.empty:
        return None
    idx = m1.index.tz_convert("America/New_York") if m1.index.tz is not None else m1.index
    m1 = m1.set_axis(idx)
    days = sorted({d for d in idx.date})
    last_ts = idx[-1]
    sess = session_of(last_ts)
    today = m1[idx.date == last_ts.date()]
    reg_today = today[[session_of(t) == "정규장" for t in today.index]]
    prev_days = [d for d in days if d < last_ts.date()]
    prev_close = None
    for d in reversed(prev_days):
        pr = m1[(idx.date == d)]
        pr = pr[[session_of(t) == "정규장" for t in pr.index]]
        if not pr.empty:
            prev_close = float(pr["Close"].iloc[-1])
            break
    if prev_close is None and daily is not None and len(daily) >= 2:
        prev_close = float(daily["Close"].dropna().iloc[-2])
    reg_close = float(reg_today["Close"].iloc[-1]) if (sess == "애프터" and not reg_today.empty) else None
    window = today[[session_of(t) == sess for t in today.index]] if sess != "장외" else today.tail(120)
    price = float(m1["Close"].iloc[-1])
    lo, hi = float(window["Low"].min()), float(window["High"].max())
    base_for_session = reg_close if sess == "애프터" else prev_close
    out = {"session": sess, "time": last_ts.strftime("%H:%M"), "price": price, "prev_close": prev_close, "reg_close": reg_close,
           "chg_prev": None if not prev_close else (price / prev_close - 1) * 100, "chg_session": None if not base_for_session else (price / base_for_session - 1) * 100,
           "reg_chg": None if not (reg_close and prev_close) else (reg_close / prev_close - 1) * 100, "lo": lo, "hi": hi,
           "range_pct": (hi / lo - 1) * 100 if lo else None, "pos": None if hi == lo else (price - lo) / (hi - lo) * 100, "window": window, "signals": []}
    if daily is not None and not daily.dropna(subset=["Close"]).empty:
        d = daily.dropna(subset=["Close"]).tail(252)
        h52, l52 = float(d["High"].max()), float(d["Low"].min())
        out.update({"hi52": h52, "lo52": l52, "pos52": None if h52 == l52 else (price - l52) / (h52 - l52) * 100, "from_hi52": (price / h52 - 1) * 100})
    mcap = None if not shares else price * shares
    out["mcap"] = mcap
    sig = out["signals"]
    if (out["reg_chg"] or 0) >= 20 or (out["chg_session"] or 0) >= 15 or (out["chg_prev"] or 0) >= 30:
        sig.append(("급등", ("" if out["reg_chg"] is None else f"정규장 {out['reg_chg']:+.2f}%, ") + (f"{sess} {out['chg_session']:+.2f}%" if out["chg_session"] is not None else ""), "red"))
    if hi and price < hi * 0.97:
        sig.append(("고점 이탈", f"구간 고가 {hi:.4f} 대비 {(price / hi - 1) * 100:+.2f}%", "blue"))
    tail = window.tail(15)
    if len(tail) >= 8:
        base = float(tail["Low"].iloc[:-3].min())
        flat = float(tail["Close"].iloc[:-3].max()) / base - 1 <= 0.04 if base else False
        if flat and price >= base * 1.02:
            sig.append(("지지 확인", f"{base:.4f} 부근 횡보 후 {price:.4f} 반등", "green"))
    if "Volume" in window and len(window):
        v = float(window["Volume"].iloc[-1])
        sig.append(("거래량", f"최근 1분봉 {v / 1e3:,.2f}K" + ("" if len(window) < 20 else f" (구간 평균의 {v / max(window['Volume'].mean(), 1):.1f}배)"), "orange"))
    if (mcap is not None and mcap < 5e6) or (out["range_pct"] or 0) >= 20:
        sig.append(("변동성 주의", ("" if mcap is None else f"시총 약 {mcap / 1e4:,.1f}만 달러, ") + f"변동폭 {out['range_pct']:.1f}%", "orange"))
    return out


def fetch(t: str) -> dict | None:
    """야후 1분봉(5일, 장전·애프터 포함) + 1년 일봉 + 주식 수(📐) → analyze."""
    import yfinance as yf

    import shares as sh
    m1 = yf.download(t, period="5d", interval="1m", prepost=True, progress=False, auto_adjust=False)
    d1 = yf.download(t, period="1y", interval="1d", progress=False, auto_adjust=False)
    for df in (m1, d1):
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    n, _ = sh.best(t)
    return analyze(m1, d1, n)
