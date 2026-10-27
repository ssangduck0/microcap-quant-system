"""🕶 다크풀(장외) 거래 비중 (2026-10-27 B단계) — 래빗스탁 '다크풀 분석기'와 같은 계산.

DP 비중(%) = FINRA 일별 장외 거래량(finra_shvol.total — TRF 보고분, 래빗스탁의 'DP 거래량'과 같은 값) ÷ 그날 전체 거래량(daily_prices.volume, 야후 일봉) × 100.
장외·일봉 집계 시점 차이로 100% 를 넘을 수 있어 100 으로 자른다. 20일 평균과의 괴리도(%p)·전일비·5일 추이·연속 상승을 함께 본다.
신호: 급등 = 괴리도 ≥ 25%p · 연속상승 = 최근 4일 비중이 계속 오름 · 매집의심 = 🧲 매집 의심(일간) 합계 ≥ 4.
새 수집기는 없다(FINRA·일봉은 이미 매일 받음). 비용 0.
"""
from __future__ import annotations

from contextlib import closing

import pandas as pd

import db

AVG_DAYS = 20
TREND_DAYS = 5
SPIKE_PP = 25.0       # 급등: 20일 평균 대비 +25%p 이상
SIGNAL_DP = 50.0      # 'DP 동반' 표시 기준: 비중 50% 이상이면서 평균보다 10%p 이상
SIGNAL_GAP = 10.0
MIN_DP_VOL = 100_000  # 상위 표: 장외 거래량 10만 주 미만은 제외(잡음)
BIG_DP_VOL = 1_000_000  # 우리 종목 목록(ticker_meta) 밖이면 장외 100만 주 이상만(소형 ETF·펀드 제외)


MAX_RATIO = 1.05   # 장외 거래량이 전체 거래량보다 5% 넘게 많을 수는 없다 → 그날 일봉이 아직 장중 값(미완성)이라는 뜻이라 비중을 매기지 않음


def _pct(dp, vol) -> float | None:
    if not vol or vol <= 0 or dp is None:
        return None
    if dp > vol * MAX_RATIO:
        return None
    return float(min(100.0, dp / vol * 100))


def dates(conn, n: int = AVG_DAYS + TREND_DAYS) -> list[str]:
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT date FROM finra_shvol ORDER BY date DESC LIMIT ?", (n,))][::-1]
    except Exception:  # noqa: BLE001
        return []


def series(conn, t: str, n: int = AVG_DAYS + TREND_DAYS) -> pd.DataFrame:
    """종목 하나의 날짜별 장외 거래량·전체 거래량·DP 비중·공매도 비중(장외 안)."""
    t = t.upper()
    try:
        rows = conn.execute("""SELECT f.date, f.total AS dp_vol, f.short AS short_vol, p.volume AS vol FROM finra_shvol f
                               LEFT JOIN daily_prices p ON p.ticker = f.symbol AND p.date = f.date
                               WHERE f.symbol = ? ORDER BY f.date DESC LIMIT ?""", (t, n)).fetchall()
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows]).iloc[::-1].reset_index(drop=True) if rows else pd.DataFrame()
    if df.empty:
        return df
    df["dp_pct"] = [_pct(a, b) for a, b in zip(df["dp_vol"], df["vol"])]
    df["short_pct"] = [None if not a else float(min(100.0, (s or 0) / a * 100)) for s, a in zip(df["short_vol"], df["dp_vol"])]
    return df


def _stats(s: pd.DataFrame) -> dict:
    """series() 결과 → 최신 비중·20일 평균·괴리도·전일비·5일 추이·연속상승."""
    v = s.dropna(subset=["dp_pct"])
    if v.empty:
        return {}
    last = v.iloc[-1]
    hist = v["dp_pct"].iloc[:-1].tail(AVG_DAYS)
    avg = float(hist.mean()) if len(hist) else None
    prev = float(v["dp_pct"].iloc[-2]) if len(v) >= 2 else None
    trend = v.tail(TREND_DAYS)
    pcts = list(trend["dp_pct"].astype(float))
    rising = len(pcts) >= 4 and all(b > a for a, b in zip(pcts[-4:], pcts[-3:]))
    return {"date": last["date"], "dp_pct": float(last["dp_pct"]), "avg20": avg, "gap": None if avg is None else float(last["dp_pct"]) - avg,
            "prev_diff": None if prev is None else float(last["dp_pct"]) - prev, "dp_vol": float(last["dp_vol"] or 0), "vol": float(last["vol"] or 0),
            "short_pct": None if pd.isna(last.get("short_pct")) else float(last["short_pct"]),
            "trend": [(d, float(p)) for d, p in zip(trend["date"], trend["dp_pct"])], "rising": bool(rising),
            "spike": avg is not None and float(last["dp_pct"]) - avg >= SPIKE_PP}


def summary(conn, t: str) -> dict:
    return _stats(series(conn, t))


def _accum_scores(conn) -> dict[str, float]:
    try:
        d = conn.execute("SELECT MAX(date) FROM accum WHERE period='일간'").fetchone()[0]
        if not d:
            return {}
        return {r[0]: float(r[1]) for r in conn.execute("SELECT ticker, score FROM accum WHERE date=? AND period='일간'", (d,))}
    except Exception:  # noqa: BLE001
        return {}


def top(conn, day: str | None = None, n: int = 30, min_dp_vol: float = MIN_DP_VOL) -> tuple[str | None, pd.DataFrame]:
    """장외 비중 상위 n (최신 FINRA 날짜). 열: ticker dp_pct avg20 gap prev_diff dp_vol vol trend rising spike accum flags."""
    ds = dates(conn, AVG_DAYS + TREND_DAYS)
    if not ds:
        return None, pd.DataFrame()
    day = day or ds[-1]
    try:
        rows = conn.execute("""SELECT f.symbol AS ticker, f.total AS dp_vol, f.short AS short_vol, p.volume AS vol FROM finra_shvol f
                               JOIN daily_prices p ON p.ticker = f.symbol AND p.date = f.date
                               WHERE f.date = ? AND p.volume > 0 AND f.total >= ?""", (day, min_dp_vol)).fetchall()
    except Exception:  # noqa: BLE001
        return day, pd.DataFrame()
    base = pd.DataFrame([dict(r) for r in rows])
    if base.empty:
        return day, base
    base["dp_pct"] = [_pct(a, b) for a, b in zip(base["dp_vol"], base["vol"])]
    import tradable
    act = tradable.active(conn)
    if act:   # P1: 토스에서 살 수 있는 보통주만(ETF·상폐·미지원 제외) — LQTI·AGGH 같은 것이 섞이던 문제
        base = base[base["ticker"].isin(act)]
    else:     # 목록이 아직 없으면(PC) 예전 규칙: 우리 종목(ticker_meta) 또는 장외 100만 주↑
        try:
            ours = {r[0] for r in conn.execute("SELECT ticker FROM ticker_meta")}
        except Exception:  # noqa: BLE001
            ours = set()
        if ours:
            base = base[[t in ours or dv >= BIG_DP_VOL for t, dv in zip(base["ticker"], base["dp_vol"])]]
    base = base.dropna(subset=["dp_pct"]).sort_values("dp_pct", ascending=False).head(n * 3)
    tickers = list(base["ticker"])
    hist = pd.DataFrame()
    if tickers:
        q = ",".join("?" * len(tickers))
        hist = pd.DataFrame([dict(r) for r in conn.execute(f"""SELECT f.symbol AS ticker, f.date, f.total AS dp_vol, p.volume AS vol FROM finra_shvol f
                               LEFT JOIN daily_prices p ON p.ticker = f.symbol AND p.date = f.date
                               WHERE f.symbol IN ({q}) AND f.date >= ? AND f.date <= ? ORDER BY f.date""", (*tickers, ds[0], day)).fetchall()])
    acc = _accum_scores(conn)
    out = []
    for r in base.to_dict("records"):
        h = hist[hist["ticker"] == r["ticker"]] if not hist.empty else pd.DataFrame()
        if not h.empty:
            h = h.assign(dp_pct=[_pct(a, b) for a, b in zip(h["dp_vol"], h["vol"])], short_vol=None)
            st_ = _stats(h)
        else:
            st_ = {"dp_pct": r["dp_pct"], "avg20": None, "gap": None, "prev_diff": None, "trend": [(day, r["dp_pct"])], "rising": False, "spike": False}
        flags = []
        if st_.get("spike"):
            flags.append("급등")
        if st_.get("rising"):
            flags.append("연속상승")
        if acc.get(r["ticker"], 0) >= 4:
            flags.append("매집의심")
        out.append({"ticker": r["ticker"], "dp_pct": r["dp_pct"], "avg20": st_.get("avg20"), "gap": st_.get("gap"), "prev_diff": st_.get("prev_diff"),
                    "dp_vol": float(r["dp_vol"]), "vol": float(r["vol"]), "short_pct": None if not r["dp_vol"] else float(min(100.0, (r["short_vol"] or 0) / r["dp_vol"] * 100)),
                    "trend": st_.get("trend") or [], "rising": bool(st_.get("rising")), "spike": bool(st_.get("spike")), "accum": acc.get(r["ticker"]), "flags": flags})
    df = pd.DataFrame(out).sort_values("dp_pct", ascending=False).head(n).reset_index(drop=True)
    return day, df


def stale_symbols(conn, day: str | None = None, min_dp_vol: float = MIN_DP_VOL, ratio: float = 0.9) -> list[str]:
    """최신 FINRA 날짜에 장외 거래량은 있는데 그날 일봉이 없거나(스캐너 감시 대상 밖: NYSE·AMEX 등) 장외 ÷ 전체 > 0.9 로 미완성이 의심되는 종목."""
    ds = dates(conn, 1)
    if not ds:
        return []
    day = day or ds[-1]
    try:
        rows = conn.execute("""SELECT f.symbol, f.total, p.volume FROM finra_shvol f LEFT JOIN daily_prices p ON p.ticker = f.symbol AND p.date = f.date
                               WHERE f.date = ? AND f.total >= ?""", (day, min_dp_vol)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    sus = sorted(s for s, dp, vol in rows if vol and (dp or 0) > vol * ratio)      # 일봉은 있는데 장외가 더 많음 = 장중 값으로 멈춤(먼저)
    missing = sorted(s for s, dp, vol in rows if not vol)                            # 일봉 자체가 없음(감시 대상 밖) — FINRA 전체 1.2만 종목 중 장외 10만 주↑
    return sus + missing


def refresh_volumes(download=None, out=print, limit: int = 2000) -> int:   # 3,500 은 야후 응답이 느려 10분 넘게 걸림 → 의심 종목 먼저 2,000
    """아침 작업: 의심 종목의 최근 5일 일봉을 다시 받아 저장(한 묶음 · 비용 0). 반환 저장한 종목 수."""
    import market
    download = download or (lambda tk: market.download_daily(tk, period="5d"))
    with closing(db.connect()) as conn:
        syms = stale_symbols(conn)[:limit]
        if not syms:
            out("다크풀: 다시 받을 일봉 없음")
            return 0
        try:
            data = download(syms)
        except Exception as e:  # noqa: BLE001
            out(f"다크풀: 일봉 다시 받기 실패({e})")
            return 0
        n = 0
        for t, df in (data or {}).items():
            if df is not None and not getattr(df, "empty", True):
                db.upsert_daily_prices(conn, t, df.tail(5))
                n += 1
    out(f"다크풀: 감시 대상 밖·미완성 의심 {len(syms)}종목 중 {n}종목 일봉 다시 받음")
    return n


def flag_map(conn=None) -> dict[str, str]:
    """🧲 매집 의심 화면용 'DP 동반' 칩: 비중 ≥ 50% 이고 20일 평균보다 10%p 이상 높은 종목 → 'DP 62% (+14p)'."""
    def _run(c):
        day, df = top(c, n=200, min_dp_vol=MIN_DP_VOL)
        if df.empty:
            return {}
        return {r["ticker"]: f"DP {r['dp_pct']:.0f}%" + ("" if r["gap"] is None else f" ({r['gap']:+.0f}p)")
                for r in df.to_dict("records") if r["dp_pct"] >= SIGNAL_DP and (r["gap"] or 0) >= SIGNAL_GAP}
    if conn is not None:
        return _run(conn)
    with closing(db.connect()) as c:
        return _run(c)
