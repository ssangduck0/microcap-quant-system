"""SQLite 저장소. CSV 대신 쓰는 이유: 종목·날짜 단위로 upsert 되어 중복이 쌓이지 않고, 10년치도 빠르게 조회됩니다."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pandas as pd

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT PRIMARY KEY, name TEXT, exchange TEXT,
    float_shares REAL, shares_out REAL, market_cap REAL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS dilution (
    ticker TEXT PRIMARY KEY, cik INTEGER, status TEXT NOT NULL,
    flags TEXT, evidence TEXT, error TEXT, checked_at TEXT
);
CREATE TABLE IF NOT EXISTS filing_cache (
    accession TEXT PRIMARY KEY, ticker TEXT, cik INTEGER, form TEXT, filed TEXT,
    items TEXT, url TEXT, tags TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker TEXT NOT NULL, date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS daily_snapshots (
    date TEXT NOT NULL, ticker TEXT NOT NULL, exchange TEXT,
    first_seen TEXT, last_seen TEXT,
    price REAL, high_20d REAL, low_20d REAL, drawdown_pct REAL, day_change_pct REAL, pre_dd_pct REAL, avg_dollar_vol REAL,
    gap_pct REAL, close_loc REAL, range_pct REAL, prior_range_pct REAL, mkt_down_frac REAL,
    volume_mult REAL, buy_pressure REAL, float_shares REAL, atr14 REAL,
    entry_ref REAL, stop_ref REAL, target_ref REAL,
    quant_score REAL, quant_detail TEXT,
    pump_score REAL, pump_detail TEXT,
    dilution_status TEXT, excluded INTEGER DEFAULT 0,
    win_p REAL, win_score REAL, win_model TEXT,
    PRIMARY KEY (date, ticker)
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, date TEXT, ticker TEXT,
    price REAL, drawdown_pct REAL, quant_score REAL, pump_score REAL,
    dilution_status TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS case_events (
    ticker TEXT NOT NULL, date TEXT NOT NULL,
    prev_close REAL, close REAL, drop_pct REAL, gap_pct REAL, intraday_rebound_pct REAL,
    avg_dollar_vol REAL, vol_mult REAL, pre_dd_pct REAL,
    next_open_pct REAL, next_high_pct REAL, next_low_pct REAL, next_close_pct REAL,
    fwd_3d REAL, fwd_5d REAL, fwd_10d REAL, max_up_5d REAL, max_down_5d REAL, max_up_3d REAL, max_down_3d REAL,
    bars_after INTEGER, last_bar_date TEXT,
    range_pct REAL, close_loc REAL, prior_range_pct REAL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_case_date ON case_events (date);
CREATE TABLE IF NOT EXISTS case_progress (
    ticker TEXT PRIMARY KEY, status TEXT NOT NULL, n_events INTEGER DEFAULT 0, n_bars INTEGER,
    first_date TEXT, last_date TEXT, is_delisted INTEGER DEFAULT 0, msg TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tracked_outcomes (
    date TEXT NOT NULL, ticker TEXT NOT NULL, entry_close REAL,
    next_open_pct REAL, next_high_pct REAL, next_low_pct REAL, next_close_pct REAL,
    fwd_3d REAL, fwd_5d REAL, fwd_10d REAL, max_up_5d REAL, max_down_5d REAL,
    bars_after INTEGER, complete INTEGER DEFAULT 0, status TEXT, updated_at TEXT,
    PRIMARY KEY (date, ticker)
);
CREATE TABLE IF NOT EXISTS models (name TEXT PRIMARY KEY, payload TEXT, fitted_at TEXT);
CREATE TABLE IF NOT EXISTS reports (ticker TEXT PRIMARY KEY, payload TEXT, generated_at TEXT);
CREATE TABLE IF NOT EXISTS notes (ticker TEXT PRIMARY KEY, note TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals (ticker, id);
CREATE INDEX IF NOT EXISTS idx_snap_ticker ON daily_snapshots (ticker, date);
"""

SNAPSHOT_COLS = [
    "date", "ticker", "exchange", "first_seen", "last_seen", "price", "high_20d", "low_20d",
    "drawdown_pct", "day_change_pct", "pre_dd_pct", "avg_dollar_vol",
    "gap_pct", "close_loc", "range_pct", "prior_range_pct", "mkt_down_frac", "volume_mult", "buy_pressure", "float_shares", "atr14",
    "entry_ref", "stop_ref", "target_ref", "quant_score", "quant_detail",
    "pump_score", "pump_detail", "dilution_status", "excluded", "win_p", "win_score", "win_model",
]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_fresh(iso: str | None, hours: float) -> bool:
    if not iso:
        return False
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - t < timedelta(hours=hours)


def connect() -> sqlite3.Connection:
    # 2026-10-28: 예전엔 연결마다 PRAGMA journal_mode=WAL 을 실행했는데, 서버에서 재 보니 그 한 줄이 연결 비용의 96%(0.04ms → 0.98ms)였다.
    # WAL 은 DB 파일에 한 번 설정하면 계속 유지되므로 init_db() 에서 한 번만 켠다(🏁 순위 계산처럼 연결을 1만 번 여는 곳이 두 배 빨라짐).
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


MIGRATIONS = {"daily_snapshots": [("day_change_pct", "REAL"), ("pre_dd_pct", "REAL"), ("avg_dollar_vol", "REAL"),
                                  ("gap_pct", "REAL"), ("close_loc", "REAL"), ("range_pct", "REAL"), ("prior_range_pct", "REAL"),
                                  ("mkt_down_frac", "REAL"), ("win_p", "REAL"), ("win_score", "REAL"), ("win_model", "TEXT")],
              "case_events": [("range_pct", "REAL"), ("close_loc", "REAL"), ("prior_range_pct", "REAL"), ("max_up_3d", "REAL"), ("max_down_3d", "REAL")]}  # 기존 DB 에 뒤늦게 추가된 컬럼


def init_db() -> None:
    with closing(connect()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")   # 파일에 한 번 켜 두면 모든 연결이 WAL(읽기·쓰기 동시) — connect() 는 더 이상 매번 안 함(2026-10-28)
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        conn.commit()


def read_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with closing(connect()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


# ---------- fundamentals ----------
def get_fundamentals(conn, ticker):
    row = conn.execute("SELECT * FROM fundamentals WHERE ticker=?", (ticker,)).fetchone()
    return dict(row) if row else None


def save_fundamentals(conn, ticker, f: dict) -> None:
    conn.execute(
        """INSERT INTO fundamentals (ticker,name,exchange,float_shares,shares_out,market_cap,updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, exchange=excluded.exchange,
             float_shares=excluded.float_shares, shares_out=excluded.shares_out,
             market_cap=excluded.market_cap, updated_at=excluded.updated_at""",
        (ticker, f.get("name"), f.get("exchange"), f.get("float_shares"), f.get("shares_out"),
         f.get("market_cap"), utcnow_iso()),
    )
    conn.commit()


# ---------- dilution ----------
def get_dilution(conn, ticker):
    row = conn.execute("SELECT * FROM dilution WHERE ticker=?", (ticker,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["flags"] = json.loads(d["flags"] or "{}")
    d["evidence"] = json.loads(d["evidence"] or "[]")
    return d


def save_dilution(conn, res: dict) -> None:
    try:  # 2026-10-27: 희석 상태 이력(저금통 ⑦ '희석 구조 변하지 않았을 것')
        conn.execute("CREATE TABLE IF NOT EXISTS dilution_hist (ticker TEXT NOT NULL, date TEXT NOT NULL, status TEXT, PRIMARY KEY (ticker, date))")
        conn.execute("INSERT OR REPLACE INTO dilution_hist VALUES (?,?,?)", (res["ticker"], utcnow_iso()[:10], res["status"]))
    except Exception:  # noqa: BLE001
        pass
    conn.execute(
        """INSERT INTO dilution (ticker,cik,status,flags,evidence,error,checked_at) VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET cik=excluded.cik, status=excluded.status, flags=excluded.flags,
             evidence=excluded.evidence, error=excluded.error, checked_at=excluded.checked_at""",
        (res["ticker"], res.get("cik"), res["status"], json.dumps(res.get("flags", {}), ensure_ascii=False),
         json.dumps(res.get("evidence", []), ensure_ascii=False), res.get("error"), utcnow_iso()),
    )
    conn.commit()


# ---------- filing cache ----------
def get_filing(conn, accession):
    row = conn.execute("SELECT * FROM filing_cache WHERE accession=?", (accession,)).fetchone()
    return dict(row) if row else None


def save_filing(conn, ticker, cik, f: dict, tags: list[str]) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO filing_cache (accession,ticker,cik,form,filed,items,url,tags,fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (f["accession"], ticker, cik, f["form"], f["filed"], f.get("items", ""), f["url"],
         json.dumps(tags), utcnow_iso()),
    )
    conn.commit()


# ---------- prices ----------
def upsert_daily_prices(conn, ticker: str, df: pd.DataFrame) -> int:
    rows = []
    for idx, r in df.iterrows():
        if pd.isna(r.get("Close")):
            continue
        rows.append((ticker, pd.Timestamp(idx).strftime("%Y-%m-%d"),
                     _f(r.get("Open")), _f(r.get("High")), _f(r.get("Low")), _f(r.get("Close")), _f(r.get("Volume"))))
    conn.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def upsert_recent_bars(conn, daily: dict, n: int = 3) -> int:
    """전 종목 최근 n일 일봉을 한 번에 저장(2026-10-27). 스캐너는 후보 종목만 저장해서 나머지 종목의 '어제 거래량'이 장중 값으로 남았고,
    🕶 다크풀 비중(장외 ÷ 전체)이 100% 로 몰리는 원인이었음. 한 트랜잭션으로 수천 행이라 1초 안쪽."""
    rows = []
    for t, df in (daily or {}).items():
        if df is None or getattr(df, "empty", True):
            continue
        for idx, r in df.tail(n).iterrows():
            if pd.isna(r.get("Close")):
                continue
            rows.append((t, pd.Timestamp(idx).strftime("%Y-%m-%d"), _f(r.get("Open")), _f(r.get("High")), _f(r.get("Low")), _f(r.get("Close")), _f(r.get("Volume"))))
    if rows:
        conn.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
    return len(rows)


def _f(x):
    return None if x is None or pd.isna(x) else float(x)


# ---------- snapshots / signals ----------
def get_snapshot(conn, date: str, ticker: str):
    row = conn.execute("SELECT * FROM daily_snapshots WHERE date=? AND ticker=?", (date, ticker)).fetchone()
    return dict(row) if row else None


def upsert_snapshot(conn, row: dict) -> None:
    cols = SNAPSHOT_COLS
    placeholders = ",".join("?" for _ in cols)
    keep = {"win_p", "win_score", "win_model"}  # 정규장 밖 스캔은 점수를 비워서 보내므로, 직전 정규장 점수를 지우지 않는다
    updates = ",".join((f"{c}=COALESCE(excluded.{c},{c})" if c in keep else f"{c}=excluded.{c}")
                       for c in cols if c not in ("date", "ticker", "first_seen"))
    conn.execute(
        f"INSERT INTO daily_snapshots ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(date,ticker) DO UPDATE SET {updates}",
        tuple(row.get(c) for c in cols),
    )
    conn.commit()


def last_signal(conn, ticker: str):
    row = conn.execute("SELECT * FROM signals WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
    return dict(row) if row else None


def insert_signal(conn, s: dict) -> None:
    conn.execute(
        """INSERT INTO signals (ts,date,ticker,price,drawdown_pct,quant_score,pump_score,dilution_status,reason)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (utcnow_iso(), s["date"], s["ticker"], s["price"], s["drawdown_pct"], s["quant_score"],
         s["pump_score"], s["dilution_status"], s["reason"]),
    )
    conn.commit()


# ---------- reports / notes ----------
def get_report(ticker: str, conn=None):
    """conn 을 주면 그 연결로(순위 계산이 종목마다 부름 — 연결을 새로 안 열기, 2026-10-28)."""
    if conn is None:
        with closing(connect()) as c:
            return get_report(ticker, c)
    row = conn.execute("SELECT payload FROM reports WHERE ticker=?", (ticker,)).fetchone()
    return json.loads(row["payload"]) if row else None


def save_report(ticker: str, payload: dict) -> None:
    with closing(connect()) as conn:
        conn.execute("INSERT OR REPLACE INTO reports (ticker,payload,generated_at) VALUES (?,?,?)",
                     (ticker, json.dumps(payload, ensure_ascii=False), utcnow_iso()))
        conn.commit()


def get_note(ticker: str) -> str:
    with closing(connect()) as conn:
        row = conn.execute("SELECT note FROM notes WHERE ticker=?", (ticker,)).fetchone()
    return row["note"] if row else ""


def save_note(ticker: str, note: str) -> None:
    with closing(connect()) as conn:
        conn.execute("INSERT OR REPLACE INTO notes (ticker,note,updated_at) VALUES (?,?,?)", (ticker, note, utcnow_iso()))
        conn.commit()


# ---------- meta (환율, 미국장 세션 등 스캐너가 기록하고 대시보드가 읽는 값) ----------
def set_meta(key: str, value: str) -> None:
    with closing(connect()) as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key,value,updated_at) VALUES (?,?,?)", (key, value, utcnow_iso()))
        conn.commit()


def get_meta(key: str):
    with closing(connect()) as conn:
        row = conn.execute("SELECT value, updated_at FROM meta WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


# ---------- models ----------
def get_model(name: str):
    with closing(connect()) as conn:
        row = conn.execute("SELECT payload FROM models WHERE name=?", (name,)).fetchone()
    return json.loads(row["payload"]) if row else None


def list_models() -> list[dict]:
    with closing(connect()) as conn:
        return [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM models ORDER BY name")]


def save_model(name: str, payload: dict) -> None:
    with closing(connect()) as conn:
        conn.execute("INSERT OR REPLACE INTO models (name,payload,fitted_at) VALUES (?,?,?)",
                     (name, json.dumps(payload, ensure_ascii=False), utcnow_iso()))
        conn.commit()
