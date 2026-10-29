"""과거 SEC 공시 목록 백필 — 과거 사례 DB(10년 급락 사건)에 '그때 어떤 공시가 있었는지'를 붙인다.

python secbackfill.py build [--years 10]   종목별 공시 목록(서류 종류·날짜·8-K 항목)을 받아 sec_hist 에 저장(이어받기 가능)
python secbackfill.py status               진행 상황

본문은 읽지 않고 서류 종류·날짜·항목만 받아 빠르다(종목당 1~3회 요청, SEC 초당 10회 제한 안에서).
SEC 는 최근 1,000건을 'recent' 로 주고 그 이전은 별도 파일(files)로 나눠 주므로 10년 범위에 걸치는 파일까지 받는다.
※ 상장폐지·티커 변경 종목은 CIK 를 못 찾을 수 있다(생존편향은 가격 DB 와 같음).
"""
from __future__ import annotations

import argparse
import logging
import sys
from contextlib import closing
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config
import db
import sec

log = logging.getLogger("secbackfill")
DDL = ["CREATE TABLE IF NOT EXISTS sec_hist (accession TEXT PRIMARY KEY, ticker TEXT NOT NULL, form TEXT, filed TEXT, items TEXT)",
       "CREATE INDEX IF NOT EXISTS idx_sec_hist ON sec_hist (ticker, filed)",
       "CREATE TABLE IF NOT EXISTS sec_hist_progress (ticker TEXT PRIMARY KEY, status TEXT, n INTEGER, at TEXT)"]
OFFER = ("424B", "S-1", "F-1", "S-3", "F-3", "EFFECT")
FLAGS = {  # 이름: (설명, 창(일): 시작·끝, 판정)
    "offering": ("공모·등록 서류(424B·S-1/F-1·S-3/F-3·EFFECT) 급락일 -5~+1일", -5, 1),
    "notice": ("상장유지 미달 통지(8-K 3.01) 급락일 전 90일", -90, 0),
    "charter": ("정관 변경(8-K 5.03 — 역분할·수권주식 증가 등) 급락일 전 180일", -180, 0),
    "news": ("8-K·6-K(뉴스성 공시) 급락일 -1~0일", -1, 0),
    "quiet": ("공시 공백(급락일 -10~+1일에 아무 공시 없음)", -10, 1),
}


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def sync_from_feed(conn) -> int:
    """스캐너 실시간 공시 피드(sec_feed)를 공시 이력(sec_hist)에 합침(INSERT OR IGNORE) — 백필은 1회성이라 그 뒤 공시는 피드로만 들어옴.
    2026-10-30 발견: sec_hist 가 10/15 에서 멈춰 수집기(eventlab)·presim/타임머신 희석 깃발·📚 공시 플래그가 그 뒤 공시를 못 봤음. 아침 작업 맨 앞에서 매일."""
    ensure_tables(conn)
    try:
        cur = conn.execute("INSERT OR IGNORE INTO sec_hist (accession, ticker, form, filed, items) "
                           "SELECT accession, UPPER(ticker), form, COALESCE(filed, substr(updated, 1, 10)), COALESCE(items, '') FROM sec_feed "
                           "WHERE accession IS NOT NULL AND ticker IS NOT NULL AND ticker <> ''")
    except Exception:  # noqa: BLE001 — sec_feed 표가 없는 DB(PC 초기)
        return 0
    conn.commit()
    return max(0, cur.rowcount or 0)


def _rows(block: dict, ticker: str) -> list[tuple]:
    n = len(block.get("accessionNumber", []))
    items = block.get("items") or [""] * n
    return [(block["accessionNumber"][i], ticker, block["form"][i], block["filingDate"][i], items[i] or "") for i in range(n)]


def backfill_one(client, conn, ticker: str, cutoff: str) -> int:
    cik = client.cik_for(ticker)
    if not cik:
        conn.execute("INSERT OR REPLACE INTO sec_hist_progress (ticker, status, n, at) VALUES (?,?,?,?)", (ticker, "no_cik", 0, db.utcnow_iso()))
        conn.commit()
        return 0
    sub = client.submissions(cik)
    rows = _rows(sub.get("filings", {}).get("recent", {}), ticker)
    for f in sub.get("filings", {}).get("files", []) or []:  # 오래된 공시 파일: 10년 범위에 걸치는 것만
        if (f.get("filingTo") or "9999") >= cutoff:
            rows += _rows(client._get(f"https://data.sec.gov/submissions/{f['name']}").json(), ticker)
    rows = [r for r in rows if r[3] >= cutoff]
    conn.executemany("INSERT OR IGNORE INTO sec_hist (accession, ticker, form, filed, items) VALUES (?,?,?,?,?)", rows)
    conn.execute("INSERT OR REPLACE INTO sec_hist_progress (ticker, status, n, at) VALUES (?,?,?,?)", (ticker, "done", len(rows), db.utcnow_iso()))
    conn.commit()
    return len(rows)


def build(client, years: int = 10, out=print, tickers: list[str] | None = None) -> dict:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        tickers = tickers or [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM case_events ORDER BY ticker")]
        done = {r[0] for r in conn.execute("SELECT ticker FROM sec_hist_progress WHERE status IN ('done','no_cik')")}
        todo = [t for t in tickers if t not in done]
        cutoff = (date.today() - timedelta(days=int(years * 365.25) + 30)).isoformat()
        out(f"과거 공시 백필: 대상 {len(tickers):,}종목 · 이미 완료 {len(tickers) - len(todo):,} · 남은 {len(todo):,} (기준일 {cutoff} 이후)")
        n_rows = n_fail = 0
        for i, t in enumerate(todo, 1):
            try:
                n_rows += backfill_one(client, conn, t, cutoff)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                log.warning("%s 공시 목록 실패: %s", t, e)
            if i % 100 == 0 or i == len(todo):
                out(f"  {i:,}/{len(todo):,} · 공시 {n_rows:,}건 · 실패 {n_fail}")
    return {"tickers": len(todo), "rows": n_rows, "failed": n_fail}


def status() -> dict:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        r = conn.execute("SELECT COUNT(*) AS n, SUM(status='done') AS done, SUM(status='no_cik') AS nocik FROM sec_hist_progress").fetchone()
        filings = conn.execute("SELECT COUNT(*) FROM sec_hist").fetchone()[0]
        total = conn.execute("SELECT COUNT(DISTINCT ticker) FROM case_events").fetchone()[0] if conn.execute(
            "SELECT name FROM sqlite_master WHERE name='case_events'").fetchone() else 0
    return {"total": total, "done": r["done"] or 0, "no_cik": r["nocik"] or 0, "filings": filings}


def event_flags(ev: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    """사건(ticker, date)마다 FLAGS 판정. 백필이 안 된 종목은 NaN(판정 불가).
    2026-10-28: 결과는 그대로 두고 빠르게 — 서류 종류 판정을 공시 전체에 한 번만(벡터) 하고, 종목별로는 정렬된 날짜 배열 조각만 자른다.
    (예전엔 종목마다 groupby 조각에 str.startswith/contains 를 다시 돌리고 out.loc 에 한 칸씩 써서 서버에서 21초 걸림 → 과거 사례 화면이 매번 25초)"""
    out = pd.DataFrame(index=ev.index, columns=list(FLAGS), dtype=object)
    if ev.empty or hist.empty:
        return out
    form = hist["form"].astype(str)
    items = hist["items"].fillna("").astype(str)
    is8k = form.str.startswith("8-K").values
    masks = {"offering": form.str.startswith(OFFER).values,
             "notice": is8k & items.str.contains(r"\b3\.01\b").values,
             "charter": is8k & items.str.contains(r"\b5\.03\b").values,
             "news": form.str.startswith(("8-K", "6-K")).values,
             "quiet": np.ones(len(hist), dtype=bool)}
    tk = hist["ticker"].astype(str).values
    d = pd.to_datetime(hist["filed"]).values.astype("datetime64[D]")
    order = np.lexsort((d, tk))                       # 종목 → 날짜 순(종목 안에서 날짜 정렬 = 예전의 np.sort 와 같음)
    tk, d = tk[order], d[order]
    masks = {k: v[order] for k, v in masks.items()}
    uniq, starts = np.unique(tk, return_index=True)
    ends = np.append(starts[1:], len(tk))
    span = {t: (s, e) for t, s, e in zip(uniq, starts, ends)}
    res = {k: np.full(len(ev), np.nan, dtype=object) for k in FLAGS}
    ev_days = pd.to_datetime(ev["date"]).values.astype("datetime64[D]")
    pos = pd.Series(np.arange(len(ev)), index=ev.index)
    for t, idx in ev.groupby("ticker").groups.items():
        if t not in span:
            continue
        s, e = span[t]
        rows = pos[idx].values
        days = ev_days[rows]
        for name, (_, a, b) in FLAGS.items():
            arr = d[s:e][masks[name][s:e]]
            lo = np.searchsorted(arr, days + np.timedelta64(a, "D"), side="left")
            hi = np.searchsorted(arr, days + np.timedelta64(b, "D"), side="right")
            has = (hi - lo) > 0
            res[name][rows] = (~has) if name == "quiet" else has
    for name in FLAGS:
        out[name] = res[name]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="과거 SEC 공시 목록 백필")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--years", type=int, default=10)
    sub.add_parser("status")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.init_db()
    if a.cmd == "status":
        s = status()
        print(f"과거 사례 종목 {s['total']:,} · 완료 {s['done']:,} · CIK 없음 {s['no_cik']:,} · 공시 {s['filings']:,}건")
        return 0
    if "@" not in config.SEC_USER_AGENT:
        print("SEC_USER_AGENT 가 .env 에 없습니다.")
        return 2
    r = build(sec.SecClient(config.SEC_USER_AGENT), a.years)
    print(f"끝: {r['tickers']:,}종목 · 공시 {r['rows']:,}건 · 실패 {r['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
