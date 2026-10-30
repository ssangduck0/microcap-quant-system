"""📈 급상승/급하락 100 (2026-10-27 B단계) — 스캐너가 사이클마다 토스 순위(TOP_GAINERS·TOP_LOSERS, 1일)를 100위까지 저장(ETF·워런트 제외).

래빗스탁 '급상승/급하락 랭킹'처럼 세션(프리·정규·애프터·데이마켓) 상관없이 지금 순위를 보여 주고, 종목마다 희석 배지(ATM·ELOC·전환사채)·산업·시가총액·최근 7일 뉴스·공시 수를 붙인다.
스캐너가 꺼져 있으면(PC) 아침 일봉 등락(daily_move)으로 대신 보여 준다. 토스 API 는 서버 스캐너만 부른다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import db

ET = ZoneInfo("America/New_York")
DDL = """CREATE TABLE IF NOT EXISTS toss_rank (date TEXT NOT NULL, kind TEXT NOT NULL, rank INTEGER NOT NULL, ticker TEXT, price REAL, change_pct REAL,
         session TEXT, at TEXT, PRIMARY KEY (date, kind, rank))"""
KINDS = {"up": "TOP_GAINERS", "down": "TOP_LOSERS"}
TOP_N = 100


def ensure(conn) -> None:
    conn.execute(DDL)


def save(conn, day: str, kind: str, rows: list[dict], at: datetime, session: str | None) -> int:
    """그날 그 종류의 순위를 통째로 바꿔 넣는다(사이클마다 최신 스냅샷)."""
    ensure(conn)
    conn.execute("DELETE FROM toss_rank WHERE date=? AND kind=?", (day, kind))
    conn.executemany("INSERT OR REPLACE INTO toss_rank (date, kind, rank, ticker, price, change_pct, session, at) VALUES (?,?,?,?,?,?,?,?)",
                     [(day, kind, int(r["rank"]), r["ticker"], r.get("price"), r.get("change_pct"), session, at.isoformat()) for r in rows])
    conn.execute("DELETE FROM toss_rank WHERE date < ?", ((date.fromisoformat(day) - timedelta(days=10)).isoformat(),))
    conn.commit()
    return len(rows)


def capture(conn, tc, now: datetime | None = None, session: str | None = None, top_n: int = TOP_N) -> dict[str, int]:
    """스캐너: 토스 급상승·급하락 1일 순위 100위까지 저장. 반환 {kind: 건수}."""
    import closewatch
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(ET).date().isoformat()
    if session is None:
        session = (db.get_meta("us_session") or {}).get("value")
    out = {}
    for kind, rt in KINDS.items():
        rows, _ex = closewatch.ranked_top(tc, rt, "1d", top_n)
        out[kind] = save(conn, day, kind, rows, now, session)
    return out


def latest(conn, kind: str) -> tuple[dict, list[dict]]:
    """(메타{date, at, session, source}, 순위 행들). 스캐너 기록이 없으면 daily_move 로 대신."""
    ensure(conn)
    r = conn.execute("SELECT date, MAX(at) at, session FROM toss_rank WHERE kind=? GROUP BY date ORDER BY date DESC LIMIT 1", (kind,)).fetchone()
    if r:
        rows = [dict(x) for x in conn.execute("SELECT rank, ticker, price, change_pct FROM toss_rank WHERE date=? AND kind=? ORDER BY rank", (r["date"], kind))]
        return {"date": r["date"], "at": r["at"], "session": r["session"], "source": "토스 순위(스캐너)"}, rows
    try:
        d = conn.execute("SELECT MAX(date) FROM daily_move").fetchone()[0]
        if not d:
            return {}, []
        order = "DESC" if kind == "up" else "ASC"
        rows = [{"rank": i, "ticker": x[0], "price": x[1], "change_pct": x[2]} for i, x in enumerate(
            conn.execute(f"SELECT ticker, price, chg FROM daily_move WHERE date=? AND chg IS NOT NULL ORDER BY chg {order} LIMIT ?", (d, TOP_N)), 1)]
        return {"date": d, "at": None, "session": None, "source": "아침 일봉 등락(daily_move) — 스캐너 순위 기록 없음"}, rows
    except Exception:  # noqa: BLE001
        return {}, []


def enrich(conn, rows: list[dict], days: int = 7) -> pd.DataFrame:
    """순위 행 + 이름·산업·시가총액·희석 배지·최근 7일 뉴스/공시 수."""
    if not rows:
        return pd.DataFrame()
    tk = [r["ticker"] for r in rows]
    q = ",".join("?" * len(tk))
    since = (date.today() - timedelta(days=days)).isoformat()

    def table(sql, params=()):
        try:
            return {r[0]: r[1:] for r in conn.execute(sql, params)}
        except Exception:  # noqa: BLE001
            return {}
    meta = table(f"SELECT ticker, name, sic_desc FROM ticker_meta WHERE ticker IN ({q})", tk)
    fund = table(f"SELECT ticker, market_cap, shares_out FROM fundamentals WHERE ticker IN ({q})", tk)
    dil = table(f"SELECT ticker, status FROM dilution WHERE ticker IN ({q})", tk)
    news = table(f"SELECT ticker, COUNT(*) FROM news WHERE ticker IN ({q}) AND published >= ? GROUP BY ticker", (*tk, since))
    feed = table(f"SELECT ticker, COUNT(*) FROM sec_feed WHERE ticker IN ({q}) AND filed >= ? GROUP BY ticker", (*tk, since))
    badge = {"ATM": "ATM", "ELOC": "ELOC", "CB": "TOXIC(전환사채)", "OFFERING": "공모·사모", "CLEAN": "", "UNKNOWN": ""}
    out = []
    for r in rows:
        t = r["ticker"]
        mc = (fund.get(t) or (None, None))[0]
        if not mc and r.get("price") and (fund.get(t) or (None, None))[1]:
            mc = r["price"] * fund[t][1]
        out.append({"순위": r["rank"], "티커": t, "이름": (meta.get(t) or ("", ""))[0] or "", "현재가": r.get("price"), "등락률(%)": r.get("change_pct"),
                    "시가총액($M)": None if not mc else mc / 1e6, "희석": badge.get((dil.get(t) or ("UNKNOWN",))[0] or "UNKNOWN", ""),
                    "산업": (meta.get(t) or ("", ""))[1] or "", f"뉴스 {days}일": (news.get(t) or (0,))[0], f"공시 {days}일": (feed.get(t) or (0,))[0]})
    return pd.DataFrame(out)
