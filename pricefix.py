"""🩹 병합(역분할) 뒤 저장 일봉의 기준 섞임 수리 (2026-10-30).

왜: `daily_prices` 는 야후 일봉을 그때그때 덮어쓴 것이라 병합이 지나면
  (a) 아침 갱신 대상(case_progress done)이 아닌 종목은 병합 전 봉이 옛 기준 그대로 남아 병합일에 ×비율 점프가 생기고(스캐너는 최근 3봉만 씀),
  (b) 갱신 대상이라도 6개월 창 밖의 옛 봉은 옛 기준으로 남는다.
  운영 복사본(10/30 02:19) 조사: 병합일 경계 점프 16건·33종목(AXG 10/26 ×199 · ENLV ×14.8 · BTOC ×16 · DKI ×16.7 …).
  `daily_prices` 를 읽는 모듈이 17개(presim·screener·sigmodel·timemachine·aipick·autopsy…)라 가짜 급등·급락을 그대로 본다.
어떻게: 병합 종목의 2년 일봉을 야후에서 다시 받아 통째로 덮어쓴다(INSERT OR REPLACE — 지우지 않음, 야후에 없으면 그대로 둠).
  아침 작업: 처음 한 번은 2년 안 병합 종목 전부(meta `pricefix_2y_done`), 그 뒤로는 최근 10일 안 병합 종목 + 경계 점프가 보이는 종목만.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import db

RECENT_DAYS = 10
LOOKBACK_DAYS = 730
META_KEY = "pricefix_2y_done"


def split_tickers(conn, lookback_days: int = LOOKBACK_DAYS, today: date | None = None) -> list[str]:
    since = ((today or date.today()) - timedelta(days=lookback_days)).isoformat()
    try:
        return sorted({r[0] for r in conn.execute("SELECT ticker FROM rs_events WHERE ratio > 0 AND ratio < 1 AND date >= ?", (since,))})
    except Exception:  # noqa: BLE001  (표가 없는 새 DB)
        return []


def recent_split_tickers(conn, days: int = RECENT_DAYS, today: date | None = None) -> list[str]:
    return split_tickers(conn, days, today)


def boundary_tickers(conn, lookback_days: int = LOOKBACK_DAYS, today: date | None = None) -> list[str]:
    """병합일 직전 종가 → 직후 종가가 √(1/비율) 넘게 튀면 병합 전 봉이 미환산(환산된 자료는 그런 점프가 없다)."""
    since = ((today or date.today()) - timedelta(days=lookback_days)).isoformat()
    out = set()
    try:
        ev = conn.execute("SELECT ticker, date, ratio FROM rs_events WHERE ratio > 0 AND ratio < 1 AND date >= ?", (since,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    for t, d, r in ev:
        before = conn.execute("SELECT close FROM daily_prices WHERE ticker=? AND date<? AND close>0 ORDER BY date DESC LIMIT 1", (t, d)).fetchone()
        after = conn.execute("SELECT close FROM daily_prices WHERE ticker=? AND date>=? AND close>0 ORDER BY date LIMIT 1", (t, d)).fetchone()
        if before and after and after[0] / before[0] > math.sqrt(1.0 / float(r)):
            out.add(t)
    return sorted(out)


def repair(conn, tickers: list[str], download=None, period: str = "2y", chunk: int = 50) -> dict:
    """야후 2년 일봉으로 다시 쓴다. 자료가 짧으면(20봉 미만) 건드리지 않음."""
    import cases
    import market
    dl = download or (lambda ts: market.download_daily(ts, period=period, chunk=chunk))
    n_t = n_rows = 0
    changed: list[str] = []
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        data = dl(part) or {}
        for t in part:
            df = cases.drop_incomplete_last_bar(data.get(t))
            if df is None or len(df) < 20:
                continue
            if _differs(conn, t, df):
                changed.append(t)
            n_rows += db.retry_locked(db.upsert_daily_prices, conn, t, df)
            n_t += 1
    dropped = _drop_presim(conn, changed)
    return {"tickers": n_t, "rows": n_rows, "changed": changed, "presim_dropped": dropped}


def _differs(conn, t: str, df, tol: float = 0.02) -> bool:
    """저장된 종가와 새 종가가 같은 날짜에서 2% 넘게 다른 날이 있으면 True(= 옛 기준 봉이 있었음)."""
    import pandas as pd
    old = dict(conn.execute("SELECT date, close FROM daily_prices WHERE ticker=? AND close > 0", (t,)).fetchall())
    if not old:
        return False
    for ts, c in df["Close"].dropna().items():
        o = old.get(pd.Timestamp(ts).strftime("%Y-%m-%d"))
        if o and c and abs(float(c) / float(o) - 1) > tol:
            return True
    return False


def _drop_presim(conn, tickers: list[str]) -> int:
    """일봉이 바뀐 종목의 🎲 사건(presim_ep)을 지움 → 같은 아침 presim.build_episodes 가 고친 일봉으로 다시 만듦(표 전체 재작성 없이)."""
    if not tickers:
        return 0
    try:
        q = ",".join("?" * len(tickers))
        def _d():
            cur = conn.execute(f"DELETE FROM presim_ep WHERE ticker IN ({q})", tickers)
            conn.commit()
            return max(0, cur.rowcount or 0)
        return db.retry_locked(_d)
    except Exception:  # noqa: BLE001  (presim 표가 아직 없는 DB)
        return 0


def morning(conn, out=print, download=None, today: date | None = None) -> dict:
    today = today or date.today()
    first = db.get_meta(META_KEY) is None
    tickers = split_tickers(conn, today=today) if first else sorted(set(recent_split_tickers(conn, today=today)) | set(boundary_tickers(conn, today=today)))
    res = repair(conn, tickers, download=download) if tickers else {"tickers": 0, "rows": 0, "changed": [], "presim_dropped": 0}
    left = boundary_tickers(conn, today=today)
    if first:
        db.set_meta(META_KEY, today.isoformat())
    out(f"병합 환산 수리: 대상 {len(tickers)}종목 → {res['tickers']}종목 {res['rows']:,}봉 다시 씀 · 실제로 바뀐 종목 {len(res.get('changed', []))}개(🎲 사건 {res.get('presim_dropped', 0):,}건 다시 만들 예정)"
        + (" (처음 한 번: 2년 안 병합 종목 전부)" if first else "")
        + (f" · 아직 경계 점프 남음 {len(left)}종목({', '.join(left[:8])})" if left else ""))
    return {**res, "first": first, "asked": len(tickers), "left": left}
