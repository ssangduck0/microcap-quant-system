"""🌙 세션별 고점 기록 — 초소형주 급등은 프리·애프터·데이마켓에서 자주 터지는데 일봉 고가는 정규장만 담는다.
스캐너가 받는 1분봉(yfinance 프리·애프터 포함 · 토스)에서 세션별 최고가·최저가를 매 사이클 계산해 '더 높은(낮은) 값으로만' 갱신 저장한다.
세션(미국 동부시간): 데이마켓·야간 20:00~04:00(다음 거래일로 셈) · 프리 04:00~09:30 · 정규 09:30~16:00 · 애프터 16:00~20:00.
🕰 타임머신은 이 기록이 있는 날이면 '하루 최고가 = 네 세션 중 최고'로 급등을 판정한다(없는 과거는 정규장 일봉만).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

DDL = """CREATE TABLE IF NOT EXISTS ext_hilo (date TEXT NOT NULL, ticker TEXT NOT NULL, night_high REAL, pre_high REAL, reg_high REAL, post_high REAL,
         day_low REAL, updated TEXT, PRIMARY KEY (date, ticker))"""
SESS = ("night", "pre", "reg", "post")
LOW_COLS = tuple(f"{x}_low" for x in SESS)   # 2026-10-27 추가: 🧪 가상매매가 세션 순서대로 '익절·손절 중 먼저 닿은 쪽'을 가리려면 세션별 최저가도 필요
SESSION_END_ET = {"night": (4, 0), "pre": (9, 30), "reg": (16, 0), "post": (20, 0)}   # 세션 끝(동부시간)


def ensure(conn) -> None:
    conn.execute(DDL)
    have = {r[1] for r in conn.execute("PRAGMA table_info(ext_hilo)")}
    for c in LOW_COLS:
        if c not in have:
            conn.execute(f"ALTER TABLE ext_hilo ADD COLUMN {c} REAL")


def _next_bday(d: date) -> date:
    x = d + timedelta(days=1)
    while x.weekday() >= 5:
        x += timedelta(days=1)
    return x


def sessions(df: pd.DataFrame) -> dict[str, dict]:
    """1분봉 → {거래일: {night_high, pre_high, reg_high, post_high, day_low}} (동부시간 기준)."""
    if df is None or df.empty or "High" not in df:
        return {}
    d = df.dropna(subset=["High"])
    idx = pd.DatetimeIndex(d.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    et = idx.tz_convert("America/New_York")
    mins = et.hour * 60 + et.minute
    out: dict[str, dict] = {}
    for (ts, m), hi, lo in zip(zip(et, mins), d["High"].astype(float), d.get("Low", d["High"]).astype(float)):
        day = ts.date()
        if m >= 20 * 60:                       # 20:00 이후 = 다음 거래일의 데이마켓·야간
            day, s = _next_bday(day), "night"
        elif m < 4 * 60:
            s = "night"
        elif m < 9 * 60 + 30:
            s = "pre"
        elif m < 16 * 60:
            s = "reg"
        else:
            s = "post"
        while day.weekday() >= 5:
            day = _next_bday(day)
        r = out.setdefault(day.isoformat(), {f"{x}_high": None for x in SESS} | {"day_low": None} | {f"{x}_low": None for x in SESS})
        k, kl = f"{s}_high", f"{s}_low"
        r[k] = hi if r[k] is None else max(r[k], hi)
        r[kl] = lo if r[kl] is None else min(r[kl], lo)
        r["day_low"] = lo if r["day_low"] is None else min(r["day_low"], lo)
    return out


def record(conn, frames: dict) -> int:
    """스캐너 1분봉 묶음 → 세션별 고점 저장(기존보다 높을 때만 · 최저는 낮을 때만)."""
    import db
    ensure(conn)
    now, n = db.utcnow_iso(), 0
    for t, df in (frames or {}).items():
        for day, r in sessions(df).items():
            conn.execute("""INSERT INTO ext_hilo (date, ticker, night_high, pre_high, reg_high, post_high, day_low, updated, night_low, pre_low, reg_low, post_low)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(date, ticker) DO UPDATE SET
                              night_high = MAX(COALESCE(night_high, excluded.night_high), COALESCE(excluded.night_high, night_high)),
                              pre_high = MAX(COALESCE(pre_high, excluded.pre_high), COALESCE(excluded.pre_high, pre_high)),
                              reg_high = MAX(COALESCE(reg_high, excluded.reg_high), COALESCE(excluded.reg_high, reg_high)),
                              post_high = MAX(COALESCE(post_high, excluded.post_high), COALESCE(excluded.post_high, post_high)),
                              day_low = MIN(COALESCE(day_low, excluded.day_low), COALESCE(excluded.day_low, day_low)),
                              night_low = MIN(COALESCE(night_low, excluded.night_low), COALESCE(excluded.night_low, night_low)),
                              pre_low = MIN(COALESCE(pre_low, excluded.pre_low), COALESCE(excluded.pre_low, pre_low)),
                              reg_low = MIN(COALESCE(reg_low, excluded.reg_low), COALESCE(excluded.reg_low, reg_low)),
                              post_low = MIN(COALESCE(post_low, excluded.post_low), COALESCE(excluded.post_low, post_low)),
                              updated = excluded.updated""",
                         (day, t, r["night_high"], r["pre_high"], r["reg_high"], r["post_high"], r["day_low"], now,
                          r["night_low"], r["pre_low"], r["reg_low"], r["post_low"]))
            n += 1
    conn.commit()
    return n


def rows_for(conn, tickers, since: str) -> dict[str, dict[str, dict]]:
    """{ticker: {date: {night_high, …, post_low}}} — 🧪 가상매매 보완 판정용(세션 순서대로 익절·손절 확인)."""
    tk = set(tickers)
    if not tk:
        return {}
    try:
        ensure(conn)
        cur = conn.execute("SELECT * FROM ext_hilo WHERE date >= ?", (since,))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        d = dict(zip(cols, r))
        if d["ticker"] in tk:
            out.setdefault(d["ticker"], {})[d["date"]] = d
    return out


def day_highs(conn, tickers, since: str) -> dict[str, dict[str, float]]:
    """{ticker: {date: 네 세션 최고가}} — 타임머신용."""
    try:
        rows = conn.execute("SELECT ticker, date, MAX(COALESCE(night_high,0), COALESCE(pre_high,0), COALESCE(reg_high,0), COALESCE(post_high,0)) FROM ext_hilo WHERE date >= ?",
                            (since,)).fetchall()
    except Exception:  # noqa: BLE001
        return {}
    tk = set(tickers)
    out: dict[str, dict[str, float]] = {}
    for t, d, h in rows:
        if t in tk and h and h > 0:
            out.setdefault(t, {})[d] = float(h)
    return out


def backfill(days: int = 60, limit: int | None = None, download=None, out=print) -> int:
    """최근 days 일(yfinance 5분봉 최대 60일)의 프리·애프터 포함 분봉으로 세션별 고점 채우기.
    대상: 일봉 저장소에서 최근 days 일 사이 가격 $20 미만이었던 종목(타임머신 대상). 받은 종목은 기록해 두고 다시 받지 않음."""
    import json
    from contextlib import closing
    import db
    since = (date.today() - timedelta(days=days + 5)).isoformat()
    with closing(db.connect()) as conn:
        ensure(conn)
        tick = [r[0] for r in conn.execute("SELECT ticker FROM daily_prices WHERE date >= ? GROUP BY ticker HAVING MIN(close) < 20", (since,))]
    m = db.get_meta("exthilo_backfill_done")
    try:
        done = set(json.loads(m["value"])) if m and m.get("value") else set()
    except (TypeError, ValueError):
        done = set()
    todo = [t for t in tick if t not in done]
    if limit:
        todo = todo[:limit]
    if not todo:
        out("시간외 고점 채우기: 더 받을 종목 없음")
        return 0
    if download is None:
        import market
        download = lambda ts: market._download(ts, chunk_size=50, period=f"{min(days, 60)}d", interval="5m", prepost=True)  # noqa: E731
    n = 0
    for i in range(0, len(todo), 50):
        part = todo[i:i + 50]
        frames = download(part) or {}
        with closing(db.connect()) as conn:
            n += record(conn, frames)
        done |= set(part)
        db.set_meta("exthilo_backfill_done", json.dumps(sorted(done)))
        out(f"시간외 고점 채우기: {min(i + 50, len(todo))}/{len(todo)}종목 · 저장 {n}일치")
    return n


if __name__ == "__main__":
    import sys
    import quiet  # noqa: F401
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    import config
    config.apply_overrides()
    backfill(days=int(sys.argv[1]) if len(sys.argv) > 1 else 60)
