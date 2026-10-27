"""발견 종목 추적(페이퍼 트레이딩 기록): 스캐너가 발견해 저장한 종목(daily_snapshots)이 그 뒤 실제로 어떻게 움직였는지 자동으로 채운다.

  python tracker.py update     # 결과 채우기 (매일 `python cases.py update` 끝에 자동으로 실행됨)
  python tracker.py status     # 추적 현황

진입가 = 발견한 날(미국 거래일)의 정규장 종가 (일봉 기준: '장 마감 무렵에 산다'의 대리값. 체결가·수수료·호가 공백은 반영되지 않음)
기록하는 결과(진입가 대비 %):
  next_open/high/low/close_pct : 다음 거래일 시가·고가·저가·종가
  fwd_3d/5d/10d               : N거래일 뒤 종가
  max_up_5d / max_down_5d     : 이후 5거래일 중(지금까지 확보된 구간) 최고가 / 최저가
'성공' 기준(예: 다음날 고가 +10%)은 저장하지 않고 대시보드에서 바꿔가며 계산합니다.
결과는 장 마감 후 일봉이 확정돼야 채워집니다(마감 전에는 오늘 봉을 쓰지 않음). 10거래일이 지나면 완료로 표시하고 더 이상 갱신하지 않습니다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from contextlib import closing
from datetime import date, timedelta

import numpy as np
import pandas as pd

import cases
import db
import market

log = logging.getLogger("tracker")

# db.py 의 SCHEMA 와 같은 정의. db.py 가 이전 버전이어도 이 모듈이 스스로 테이블을 만들 수 있도록 여기에도 둔다.
TABLE_DDL = """CREATE TABLE IF NOT EXISTS tracked_outcomes (
    date TEXT NOT NULL, ticker TEXT NOT NULL, entry_close REAL,
    next_open_pct REAL, next_high_pct REAL, next_low_pct REAL, next_close_pct REAL,
    fwd_3d REAL, fwd_5d REAL, fwd_10d REAL, max_up_5d REAL, max_down_5d REAL,
    bars_after INTEGER, complete INTEGER DEFAULT 0, status TEXT, updated_at TEXT,
    PRIMARY KEY (date, ticker)
)"""


CLOSE_DDL = TABLE_DDL.replace("tracked_outcomes", "close_outcomes")  # 장마감 체크리스트(고정 종목)의 결과 — 같은 형식


def ensure_close_table(conn=None) -> None:
    if conn is None:
        with closing(db.connect()) as c:
            ensure_close_table(c)
        return
    conn.execute(CLOSE_DDL)
    conn.commit()


def ensure_table(conn=None) -> None:
    if conn is not None:
        conn.execute(TABLE_DDL)
        conn.commit()
        return
    with closing(db.connect()) as c:
        ensure_table(c)
OUT_COLS = ["entry_close", "next_open_pct", "next_high_pct", "next_low_pct", "next_close_pct", "fwd_3d", "fwd_5d", "fwd_10d",
            "max_up_5d", "max_down_5d", "bars_after", "complete", "status"]


def _pct(a: float, b: float) -> float | None:
    return None if not b or np.isnan(a) or np.isnan(b) else float((a / b - 1) * 100)


def outcome_for(df: pd.DataFrame, date_str: str) -> dict | None:
    """df: 일봉(Open/High/Low/Close). date_str 의 정규장 종가를 진입가로 그 뒤 결과를 계산. 그 날짜의 봉이 없으면 None."""
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    d = d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Open", "High", "Low", "Close"])
    try:
        i = d.index.get_loc(pd.Timestamp(date_str))
    except KeyError:
        return None
    o, h, l, c = (d[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n = len(d)
    if not c[i] > 0:
        return None
    r = {"entry_close": float(c[i]), "bars_after": int(n - 1 - i), "complete": int(n - 1 - i >= 10), "status": "ok",
         "next_open_pct": None, "next_high_pct": None, "next_low_pct": None, "next_close_pct": None,
         "fwd_3d": None, "fwd_5d": None, "fwd_10d": None, "max_up_5d": None, "max_down_5d": None}
    if i + 1 < n:
        r.update(next_open_pct=_pct(o[i + 1], c[i]), next_high_pct=_pct(h[i + 1], c[i]),
                 next_low_pct=_pct(l[i + 1], c[i]), next_close_pct=_pct(c[i + 1], c[i]))
        w = slice(i + 1, min(i + 6, n))  # 아직 5거래일이 안 지났으면 지금까지의 구간
        r["max_up_5d"] = _pct(float(h[w].max()), c[i])
        r["max_down_5d"] = _pct(float(l[w].min()), c[i])
    for k in (3, 5, 10):
        if i + k < n:
            r[f"fwd_{k}d"] = _pct(c[i + k], c[i])
    return r


def _fill(conn, rows, table: str, label: str, chunk: int, out, now) -> tuple[int, int]:
    """rows(date, ticker)의 결과를 일봉으로 계산해 table 에 저장. 반환: (갱신, 대기)."""
    tickers = sorted({r["ticker"] for r in rows})
    out(f"{label}: 기록 {len(rows):,}건 · 종목 {len(tickers):,}개 가격 확인")
    data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk):
        data.update(market.download_daily(tickers[i:i + chunk], period="3mo", chunk=chunk))
    n_upd = n_pending = 0
    for r in rows:
        df = cases.drop_incomplete_last_bar(data.get(r["ticker"]), now)
        res = outcome_for(df, r["date"]) if df is not None and not df.empty else None
        if res is None:
            if (date.today() - date.fromisoformat(r["date"])).days > 14:   # 끝내 가격을 못 구한 기록은 더 이상 재시도하지 않음
                res = {"status": "no_data", "complete": 1}
            else:
                n_pending += 1
                continue
        vals = [res.get(c) for c in OUT_COLS]
        conn.execute(f"INSERT OR REPLACE INTO {table} (date,ticker,{','.join(OUT_COLS)},updated_at) VALUES (?,?,{','.join('?' * len(OUT_COLS))},?)",
                     (r["date"], r["ticker"], *vals, db.utcnow_iso()))
        n_upd += 1
    conn.commit()
    out(f"  결과 갱신 {n_upd:,}건 · 대기(장 마감 전이거나 가격 대기) {n_pending:,}건")
    return n_upd, n_pending


def update_close(conn, lookback_days: int = 90, chunk: int = 100, out=print, now=None) -> dict:
    """장마감 체크리스트에 고정된 종목(close_watchlist frozen)의 다음날·5일 결과."""
    import closewatch
    closewatch.ensure_tables(conn)
    ensure_close_table(conn)
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute("""SELECT w.date, w.ticker FROM close_watchlist w
                           LEFT JOIN close_outcomes o ON o.date=w.date AND o.ticker=w.ticker
                           WHERE w.kind='frozen' AND w.date >= ? AND (o.ticker IS NULL OR o.complete = 0)""", (cutoff,)).fetchall()
    if not rows:
        out("장마감 체크리스트: 추적할 새 기록이 없습니다.")
        return {"rows": 0, "updated": 0}
    n_upd, n_pending = _fill(conn, rows, "close_outcomes", "장마감 체크리스트 결과", chunk, out, now)
    return {"rows": len(rows), "updated": n_upd, "pending": n_pending}


def update(conn, lookback_days: int = 45, chunk: int = 100, out=print, now=None) -> dict:
    ensure_table(conn)
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute("""SELECT s.date, s.ticker FROM daily_snapshots s
                           LEFT JOIN tracked_outcomes o ON o.date=s.date AND o.ticker=s.ticker
                           WHERE s.date >= ? AND (o.ticker IS NULL OR o.complete = 0)""", (cutoff,)).fetchall()
    res = {"rows": 0, "updated": 0}
    if not rows:
        out("추적할 새 기록이 없습니다.")
    else:
        n_upd, n_pending = _fill(conn, rows, "tracked_outcomes", "발견 종목 추적", chunk, out, now)
        res = {"rows": len(rows), "updated": n_upd, "pending": n_pending}
    try:  # 장마감 체크리스트 결과도 같이(매일 아침 cases.py update 끝에서 자동)
        res["close"] = update_close(conn, chunk=chunk, out=out, now=now)
    except Exception as e:  # noqa: BLE001
        log.warning("장마감 체크리스트 결과 갱신 실패: %s", e)
    return res


def status(conn, out=print) -> None:
    ensure_table(conn)
    ensure_close_table(conn)
    n_snap = conn.execute("SELECT COUNT(*) FROM daily_snapshots").fetchone()[0]
    r = conn.execute("SELECT COUNT(*), SUM(complete), SUM(next_high_pct IS NOT NULL), MIN(date), MAX(date) FROM tracked_outcomes").fetchone()
    out(f"발견 기록 {n_snap:,}건 · 추적됨 {r[0]:,}건(완료 {r[1] or 0:,}, 다음날 결과 확인 {r[2] or 0:,}) · 기간 {r[3]} ~ {r[4]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="발견 종목 추적")
    ap.add_argument("cmd", choices=["update", "status"])
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    db.init_db()
    with closing(db.connect()) as conn:
        update(conn) if args.cmd == "update" else None
        status(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
