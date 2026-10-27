import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""📈 급상승/급하락: 토스 순위 저장(가짜 클라이언트) · 최신 조회 · 희석 배지·산업·뉴스/공시 수 붙이기 · 스캐너 기록 없으면 daily_move 대체 · 화면(AppTest)."""
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import datetime, timezone
import pandas as pd
import db, mover, halts, themes, secfeed, news
db.init_db(); halts.fetch = lambda *a, **k: []


class FakeTC:
    def rankings(self, rank_type, country, duration, count):
        base = [{"symbol": "UPA", "price": {"lastPrice": "2.0", "basePrice": "1.0"}}, {"symbol": "ETFX", "price": {"lastPrice": "3", "basePrice": "2"}},
                {"symbol": "UPB", "price": {"lastPrice": "1.5", "basePrice": "1.0"}}]
        return base if rank_type == "TOP_GAINERS" else [{"symbol": "DNA", "price": {"lastPrice": "0.5", "basePrice": "1.0"}}]

    def stocks(self, symbols):
        return [{"symbol": s, "securityType": "ETF" if s == "ETFX" else "STOCK", "isCommonShare": True, "status": "ACTIVE"} for s in symbols]


with closing(db.connect()) as conn:
    themes.ensure_tables(conn); secfeed.ensure_tables(conn); conn.execute(news.DDL)
    conn.execute("INSERT OR REPLACE INTO ticker_meta (ticker, name, sic, sic_desc, themes, updated) VALUES ('UPA','Up A Inc',7373,'Services-Computer','[]','x')")
    conn.execute("INSERT OR REPLACE INTO fundamentals (ticker, name, exchange, float_shares, shares_out, market_cap, updated_at) VALUES ('UPA','Up A','NASDAQ',1e6,5e6,NULL,'x')")
    conn.execute("INSERT OR REPLACE INTO dilution (ticker, status) VALUES ('UPA','ATM')") if "status" in [r[1] for r in conn.execute("PRAGMA table_info(dilution)")] else None
    conn.execute("INSERT INTO news (id, ticker, exchange, title, summary, published, link, feed, tags, sentiment, fetched) VALUES ('n1','UPA','NASDAQ','t','s',?, 'l','f','[]','호재','x')",
                 (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),))
    conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) VALUES ('a1','UPA',1,'8-K','c',?, 'u','','','[]',0,'중립',0,'x')",
                 (datetime.now(timezone.utc).strftime("%Y-%m-%d"),))
    conn.commit()
    # 스캐너 기록이 없으면 daily_move 로 대신
    themes.save_moves(conn, "2026-10-24", [("MVA", 1.0, 12.5, 2.0, 1.0, 100.0), ("MVB", 1.0, -8.0, 1.0, 1.0, 50.0)])
    conn.commit()
    meta, rows = mover.latest(conn, "up"); assert meta["source"].startswith("아침 일봉") and rows[0]["ticker"] == "MVA" and rows[0]["change_pct"] == 12.5
    meta, rows = mover.latest(conn, "down"); assert rows[0]["ticker"] == "MVB"
    # 스캐너: 토스 순위 저장(ETF 제외) → 최신 조회
    now = datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc)
    n = mover.capture(conn, FakeTC(), now=now, session="정규장")
    assert n == {"up": 2, "down": 1}, n
    meta, rows = mover.latest(conn, "up")
    assert meta["date"] == "2026-10-27" and meta["session"] == "정규장" and meta["source"].startswith("토스") and [r["ticker"] for r in rows] == ["UPA", "UPB"]
    assert abs(rows[0]["change_pct"] - 100.0) < 1e-9 and rows[0]["rank"] == 1 and rows[1]["rank"] == 3        # 순위 번호는 토스 원래 순위(ETF 자리 비움)
    tb = mover.enrich(conn, rows)
    r0 = tb.iloc[0]
    assert r0["이름"] == "Up A Inc" and r0["산업"] == "Services-Computer" and r0["희석"] == "ATM" and r0["뉴스 7일"] == 1 and r0["공시 7일"] == 1
    assert abs(r0["시가총액($M)"] - 10.0) < 1e-9 and tb.iloc[1]["희석"] == "" and tb.iloc[1]["이름"] == ""   # 시총 없으면 현재가 × 발행 주식
    mover.capture(conn, FakeTC(), now=now, session="정규장")                                                 # 다시 저장해도 중복 없음
    assert conn.execute("SELECT COUNT(*) FROM toss_rank").fetchone()[0] == 3
# 화면
now_iso = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-16", "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now_iso, "last_seen": now_iso, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "movers"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
tb = [d.value for d in at.dataframe if "등락률(%)" in d.value.columns][0]
assert list(tb["티커"]) == ["UPA", "UPB"] and tb.iloc[0]["희석"] == "ATM" and any("토스 순위" in c.value and "정규장" in c.value for c in at.caption)
at.toggle(key="mv_clean").set_value(True).run(); assert not at.exception
assert list([d.value for d in at.dataframe if "등락률(%)" in d.value.columns][0]["티커"]) == ["UPB"]
at.toggle(key="mv_clean").set_value(False).run(); at.radio(key="mv_kind").set_value("📉 급하락").run(); assert not at.exception
assert list([d.value for d in at.dataframe if "등락률(%)" in d.value.columns][0]["티커"]) == ["DNA"]
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
