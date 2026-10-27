import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, config, toss, closewatch as cw, scanner, market, universe, sec, intel
db.init_db(); cw.ensure_tables()
ET = ZoneInfo("America/New_York"); KST = ZoneInfo("Asia/Seoul")
# ---------- 1) 장 캘린더 → 정규장 종료(조기 폐장 포함) ----------
cal = {"today": {"regularMarket": {"startTime": "2026-11-27T23:30:00+09:00", "endTime": "2026-11-28T03:00:00+09:00"}}}   # 블랙프라이데이 13:00 ET 조기 폐장
assert toss.regular_end(cal, datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)) == datetime(2026, 11, 28, 3, 0, tzinfo=KST)        # 진행 중
assert toss.regular_end(cal, datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)) == datetime(2026, 11, 28, 3, 0, tzinfo=KST)        # 시작 전(예정)
assert toss.regular_end(cal, datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc)) is None and toss.regular_end({}) is None
db.set_meta("us_regular_end", datetime(2026, 11, 28, 3, 0, tzinfo=KST).isoformat())
assert cw.regular_end_for(date(2026, 11, 27)).astimezone(ET).strftime("%H:%M") == "13:00"                                         # 조기 폐장 반영
assert cw.regular_end_for(date(2026, 10, 14)) == datetime(2026, 10, 14, 16, 0, tzinfo=ET)                                           # 다른 날 → 기본 16:00
end = datetime(2026, 10, 14, 16, 0, tzinfo=ET)
assert not cw.freeze_due(datetime(2026, 10, 14, 14, 59, tzinfo=ET), end, 60) and cw.freeze_due(datetime(2026, 10, 14, 15, 0, tzinfo=ET), end, 60)
print("calendar/freeze OK")
# ---------- 2) 급하락 순위 파싱 ----------
def R(i, sym, last, base=None, rate=None):
    p = {"lastPrice": str(last)}
    if base: p["basePrice"] = str(base)
    if rate is not None: p["changeRate"] = str(rate)
    return {"symbol": sym, "price": p}
RANK = [R(i, f"T{i:02d}", 1.0, 2.0) for i in range(1, 26)]
RANK[2] = R(3, "ETFX", 5.0, 10.0); RANK[4] = R(5, "WRNTW", 0.1, 0.3); RANK[6] = R(7, "RATE", 3.0, rate="-0.42"); RANK[7] = R(8, "PCT", 3.0, rate="-38.5")
class TC:
    def __init__(s, ranking): s.ranking, s.calls = ranking, 0
    def rankings(s, t, c, d, n): s.calls += 1; assert t == "TOP_LOSERS" and d == "1d"; return list(s.ranking)[:n]
    def stocks(s, syms): return [{"symbol": x, "securityType": "ETF" if x == "ETFX" else ("STOCK_WARRANTS" if x.endswith("W") else "STOCK"), "isCommonShare": True} for x in syms]
rows, n_ex = cw.losers_top(TC(RANK), 20); print([r["ticker"] for r in rows][:8], n_ex)
assert n_ex == 2 and len(rows) == 18 and rows[0] == {"ticker": "T01", "rank": 1, "change_pct": -50.0, "price": 1.0}
by = {r["ticker"]: r for r in rows}; assert "ETFX" not in by and "WRNTW" not in by and by["T20"]["rank"] == 20 and "T21" not in by          # 순위 1~20 안에서만, 원래 순위 유지
assert abs(by["RATE"]["change_pct"] + 42.0) < 1e-9 and by["PCT"]["change_pct"] == -38.5                                                         # 비율·% 둘 다 처리
print("ranking OK")
# ---------- 3) 스캐너 흐름: 고정 전 → 고정 → 고정 유지 ----------
ridx = pd.date_range("2026-10-14 09:30", "2026-10-14 14:30", freq="min", tz=ET)
c = np.linspace(2.0, 1.0, len(ridx)); frame = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 500.0}, index=ridx)
idx = pd.bdate_range(end=pd.Timestamp("2026-10-13"), periods=42)[-40:]
daily_y = pd.DataFrame({"Open": 2., "High": 2.1, "Low": 1.9, "Close": 2., "Volume": 1e6}, index=idx)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: daily_y for t in tk}
market.download_intraday = lambda tk: {t: frame for t in tk}
market.fetch_fundamentals = lambda t: {"name": t, "exchange": "NASDAQ", "float_shares": 8e6, "shares_out": 9e6, "market_cap": 1e7}
universe.get_universe = lambda *a, **k: (["T01", "ZZZ"], {"T01", "ZZZ"})
class STC(TC):
    def exchange_rate(s): return 1400.0
    def us_calendar(s): return {}
    def intraday_frame(s, sym, max_pages=6): return frame
    def daily_candles(s, sym, count=25): return []
    def orderbook(s, sym): return {"asks": [], "bids": []}
class FS(sec.SecClient):
    def __init__(s): pass
    def cik_for(s, t): return 7
    def submissions(s, c): return {"filings": {"recent": {"accessionNumber": [], "primaryDocument": [], "form": [], "filingDate": [], "items": []}}}
class Col:
    connected = False
    def __init__(s): s.sets = []
    def set_symbols(s, x): s.sets.append(list(x))
scanner.notify.send_telegram = lambda x: True
import halts; halts.fetch = lambda *a, **k: []
scanner.is_regular_session = lambda now=None: True
db.set_meta("us_regular_end", datetime(2026, 10, 14, 16, 0, tzinfo=ET).isoformat())
tc, col = STC(RANK), Col()
D = "2026-10-14"
with closing(db.connect()) as conn:
    cw._now = lambda: datetime(2026, 10, 14, 14, 30, tzinfo=ET).astimezone(timezone.utc)      # 마감 90분 전: 고정 전
    scanner.run_cycle(conn, FS(), tc, col, None)
    assert len(cw.load_list(conn, D, "live")) == 18 and cw.load_list(conn, D, "frozen") == []
    assert conn.execute("SELECT COUNT(*) FROM close_state").fetchone()[0] == 0                   # 고정 전에는 체크리스트 기록 없음
    assert col.sets[-1][:3] == ["T01", "T02", "T04"]                                             # 현재 순위 종목이 실시간 구독 맨 앞
    cw._now = lambda: datetime(2026, 10, 14, 15, 2, tzinfo=ET).astimezone(timezone.utc)       # 마감 58분 전: 고정
    scanner.run_cycle(conn, FS(), tc, col, None)
    fz = cw.load_list(conn, D, "frozen"); assert [x["ticker"] for x in fz][:3] == ["T01", "T02", "T04"] and len(fz) == 18
    got = {r["ticker"] for r in conn.execute("SELECT ticker FROM close_state WHERE date=?", (D,))}
    print("checklist tickers:", len(got), sorted(got)[:5]); assert got and got <= {x["ticker"] for x in fz} and "ZZZ" not in got   # 고정 종목만
    # 이후 순위가 바뀌어도 대상은 고정 유지, 현재 순위만 갱신
    tc.ranking = [R(1, "NEW1", 1.0, 3.0)] + RANK[1:]
    cw._now = lambda: datetime(2026, 10, 14, 15, 30, tzinfo=ET).astimezone(timezone.utc)
    scanner.run_cycle(conn, FS(), tc, col, None)
    assert [x["ticker"] for x in cw.load_list(conn, D, "frozen")][0] == "T01" and cw.load_list(conn, D, "live")[0]["ticker"] == "NEW1"
    assert "NEW1" not in {r["ticker"] for r in conn.execute("SELECT ticker FROM close_state WHERE date=?", (D,))}
    assert col.sets[-1][0] == "T01"                                                              # 고정 후에는 고정 종목이 구독 맨 앞
print("scanner flow OK")
# ---------- 4) 화면: 고정 안내와 표 좁히기 / 고정 전 미리보기 ----------
from streamlit.testing.v1 import AppTest
import streamlit as st
with closing(db.connect()) as conn:   # 고정 목록 밖 종목의 기록(예전 방식)이 남아 있어도 표에는 안 나와야 함
    conn.execute("INSERT OR REPLACE INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)", (D, "OUTSIDER", json.dumps({"drop_pct": -50.0}), db.utcnow_iso())); conn.commit()
st.cache_data.clear()
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
assert any("대상 고정" in i.value and "급하락 순위 1~20위" in i.value and "18종목" in i.value for i in at.info)
at.checkbox(key="cw_hide").set_value(False).run()
boards = [d.value for d in at.dataframe if "패턴" in d.value.columns and "등급" in d.value.columns]
assert boards and "OUTSIDER" not in set(boards[0]["티커"]) and set(boards[0]["티커"]) <= {x["ticker"] for x in fz}
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM close_watchlist WHERE kind='frozen'"); conn.commit()
st.cache_data.clear()
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=120).run(); assert not at.exception
assert any("아직 대상 고정 전" in w.value for w in at.warning)
prev = [d.value for d in at.dataframe if "순위" in d.value.columns and "등락(%)" in d.value.columns]; assert prev and prev[0].iloc[0]["티커"] == "NEW1"
assert not [d for d in at.dataframe if "패턴" in d.value.columns and "등급" in d.value.columns]                                   # 고정 전에는 체크리스트 표 없음
print("ALL OK")
