import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timedelta, timezone
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, closewatch as cw, sec, scanner, market, universe
db.init_db()
ET = "America/New_York"

# 급락일 정규장 합성 데이터 (전일 종가 10.0 -> 7.9 마감, 10:00~11:00 거래량 폭발 후 감소, 마지막 30분 반등)
ridx = pd.date_range("2026-10-12 09:30", "2026-10-12 15:59", freq="min", tz=ET); n = len(ridx)
close = np.r_[np.linspace(9.0, 7.5, 150), np.linspace(7.5, 7.4, n - 180), np.linspace(7.52, 7.9, 30)]
vol = np.r_[np.full(30, 1000.), np.full(60, 10000.), np.full(n - 90, 500.)]
pre = pd.date_range("2026-10-12 04:00", "2026-10-12 09:29", freq="min", tz=ET)
full_idx = pre.append(ridx)
frame = pd.DataFrame({"Open": np.r_[np.full(len(pre), 9.0), 9.0, close[:-1]], "High": np.r_[np.full(len(pre), 9.0), close * 1.01], "Low": np.r_[np.full(len(pre), 9.0), close * 0.99],
                      "Close": np.r_[np.full(len(pre), 9.0), close], "Volume": np.r_[np.full(len(pre), 100.), vol]}, index=full_idx)
def candle(o, h, l, c, v): return {"openPrice": str(o), "highPrice": str(h), "lowPrice": str(l), "closePrice": str(c), "volume": str(v), "timestamp": "x"}
DAILY = [candle(9.0, 9.1, 7.4, 7.92, 3e6), candle(10.0, 10.5, 9.8, 10.0, 1.5e6)] + [candle(10, 10.3, 9.7, 10.0, 1e6) for _ in range(20)]

class FakeTC:
    def __init__(s): s.calls = {"orderbook": 0, "daily": 0, "frame": 0}; s.ask_scale = 1.0
    def intraday_frame(s, sym): s.calls["frame"] += 1; return None if sym == "NOFRAME" else frame
    def daily_candles(s, sym, count=25): s.calls["daily"] += 1; return DAILY
    def orderbook(s, sym):
        s.calls["orderbook"] += 1
        if sym == "BADBOOK": raise RuntimeError("boom")
        return {"timestamp": "t", "asks": [(7.91 + 0.01 * i, 1000.0 * s.ask_scale) for i in range(3)], "bids": [(7.90, 500.0)]}
    def stocks(s, syms): return [{"symbol": x, "sharesOutstanding": "9000000"} for x in syms]
class FakeSec:
    def cik_for(s, t): return None if t == "NOSEC" else 7
    def submissions(s, cik):
        rec = {"accessionNumber": ["0001-01"], "primaryDocument": ["a.htm"], "form": ["8-K"], "filingDate": ["2026-10-09"], "items": ["3.02"]}
        return {"filings": {"recent": rec}}
    def fetch_text(s, url): return "securities purchase agreement private placement section 4(a)(2) restricted securities"
cw._DAILY.clear()
tc, fs = FakeTC(), FakeSec()
with closing(db.connect()) as conn:
    db.save_dilution(conn, {"ticker": "AAA", "cik": 7, "status": "CLEAN", "flags": {}, "evidence": []})
    t0 = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
    # 5분 간격으로 6번 갱신: 처음 3번은 매도 호가가 두껍고, 이후 얇아짐
    for i in range(6):
        tc.ask_scale = 1.0 if i < 4 else 0.3
        k = cw.update(conn, tc, fs, ["AAA", "NOFRAME", "BADBOOK", "NOSEC"], frames={"AAA": frame, "BADBOOK": frame, "NOSEC": frame}, now=t0 + timedelta(minutes=5 * i))
        if i == 0: assert k == 3, k                               # NOFRAME 은 프레임이 없어 건너뜀(그래도 토스에서 받아 보려 시도)
    rows = {r["ticker"]: json.loads(r["metrics"]) for r in conn.execute("SELECT ticker, metrics FROM close_state")}
    print(sorted(rows))
    assert set(rows) == {"AAA", "BADBOOK", "NOSEC"}
    m = rows["AAA"]
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items() if k not in ("vol_series", "intraday_filings", "financing")})
    assert abs(m["prev_close"] - 10.0) < 1e-9 and abs(m["drop_pct"] - (7.9 / 10.0 - 1) * 100) < 1e-6 and m["prev_close_source"] == "toss"      # 토스 일봉에서 전일 종가
    avg20 = (1.5e6 + 19 * 1e6) / 20      # 이전 20개 일봉: 150만 1개 + 100만 19개
    assert abs(m["avg_vol20"] - avg20) < 1e-6 and abs(m["vol_mult"] - vol.sum() / avg20) < 1e-9 and m["decay"] < 0.1 and m["cs_late"] == 999.0 and m["cs_source"].startswith("1분봉")      # 토스 20일 평균과 비교. 웹소켓 데이터가 없으면 분봉 추정으로 대체
    assert m["shares_out"] == 9e6 and m["dilution_status"] == "CLEAN" and len(m["vol_series"]) >= 39
    assert m["n_samples"] == 6 and m["thin_ratio"] is not None and abs(m["thin_ratio"] - 0.3) < 1e-6                                                   # 호가 샘플 6개, 마지막 값이 이전 중앙값의 30%
    fin = m["financing"]; assert fin["type"] == "사모(PIPE)" and fin["sellable"] == "restricted" and "재판매 등록 전" in fin["label"]                   # 사모 + 등록서류 없음 = 출회 제한
    assert m["intraday_filings"] == []                                                                                                                  # 오늘(10-12) 공시 없음
    assert abs(m["ask_minutes"] - 3 * 300.0 / (vol[-30:].sum() / 30)) < 1e-6
    # 호가 실패해도 나머지는 기록, SEC 없는 종목은 SEC 항목만 확인 불가
    assert rows["BADBOOK"].get("ask_minutes") is None and rows["BADBOOK"]["n_samples"] == 0 and rows["BADBOOK"]["thin_ratio"] is None
    assert rows["NOSEC"]["intraday_filings"] is None and "sec_error" in rows["NOSEC"] and rows["NOSEC"]["drop_pct"] is not None
    # 일봉은 종목당 하루 한 번만 받는다(AAA, BADBOOK, NOSEC = 3번)
    assert tc.calls["daily"] == 3, tc.calls
    ev = cw.evaluate(m); by = {i["key"]: i["status"] for i in ev["items"]}; print(ev["grade"], by)
    assert ev["grade"] == "BEST" and by["fin_restricted"] == "pass" and by["ask_thin"] == "pass" and by["short"] == "unknown"
    ev2 = cw.evaluate(rows["NOSEC"]); assert {i["key"]: i["status"] for i in ev2["items"]}["no_intraday"] == "unknown"
    # 같은 날 다시 갱신하면 같은 (날짜,티커) 행을 덮어씀
    cw.update(conn, tc, fs, ["AAA"], frames={"AAA": frame}, now=t0 + timedelta(minutes=40))
    assert conn.execute("SELECT COUNT(*) FROM close_state WHERE ticker='AAA'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM close_samples WHERE ticker='AAA'").fetchone()[0] == 7
# ---- 웹소켓 집계가 있으면 체결강도·호가 추이에 우선 사용, 거래정지/Fintel 연동
from zoneinfo import ZoneInfo
from datetime import datetime as DT
import halts as H
base_t = DT(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
with closing(db.connect()) as conn:
    for i in range(100):
        buy, sell = (30.0, 70.0) if i < 70 else (80.0, 20.0)
        conn.execute("INSERT OR REPLACE INTO close_flow (minute,ticker,date,buy_sh,sell_sh,mid_sh,n_trades,ask_usd_avg,ask_usd_last,n_books) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ((base_t + timedelta(minutes=i)).isoformat(), "AAA", "2026-10-12", buy, sell, 0.0, 4, 2000.0 if i < 70 else 500.0, 500.0, 5))
    conn.commit()
    ETZ = ZoneInfo("America/New_York")
    hl = [{"symbol": "AAA", "name": "A", "market": "NASDAQ", "code": "LUDP", "halt": DT(2026, 10, 12, 10, 15, 30, tzinfo=ETZ), "threshold": 7.5, "resume": DT(2026, 10, 12, 10, 20, 30, tzinfo=ETZ)},
          {"symbol": "AAA", "name": "A", "market": "NASDAQ", "code": "LUDP", "halt": DT(2026, 10, 12, 9, 40, 0, tzinfo=ETZ), "threshold": 9.9, "resume": DT(2026, 10, 12, 9, 45, 0, tzinfo=ETZ)},
          {"symbol": "AAA", "name": "A", "market": "NASDAQ", "code": "T1", "halt": DT(2026, 10, 12, 14, 0, 0, tzinfo=ETZ), "threshold": None, "resume": None},
          {"symbol": "ZZZ", "name": "Z", "market": "NASDAQ", "code": "LUDP", "halt": DT(2026, 10, 12, 11, 0, 0, tzinfo=ETZ), "threshold": 1.0, "resume": None}]
    class FakeFintel:
        def summary(self, t): return {"sv_date": "2026-10-09", "sv_short": 800.0, "sv_total": 1000.0, "sv_ratio": 80.0, "sv_avg5_ratio": 60.0, "borrow_fee": 30.0, "errors": []}
    cw.update(conn, tc, fs, ["AAA", "NOSEC"], frames={"AAA": frame, "NOSEC": frame}, now=t0 + timedelta(minutes=60), halts_list=hl, fintel_client=FakeFintel())
    rows = {r["ticker"]: json.loads(r["metrics"]) for r in conn.execute("SELECT ticker, metrics FROM close_state")}
    m = rows["AAA"]; print({k: m.get(k) for k in ("cs_late", "cs_prior", "cs_cum", "cs_source", "thin_ratio", "n_samples", "halt_down", "halt_up", "halt_other", "halt_active")})
    assert m["cs_source"].startswith("토스 웹소켓") and abs(m["cs_late"] - 80 / 20 * 100) < 1e-6 and abs(m["cs_prior"] - 30 / 70 * 100) < 1e-6        # 마지막 30분 400%, 그 전 60분 43%
    assert m["n_samples"] == 100 and abs(m["thin_ratio"] - 500 / 2000) < 1e-6                                                                       # 호가 깊이 샘플은 웹소켓 분 단위 시계열 사용(최근 500 / 이전 2000)
    assert m["halt_down"] == 1 and m["halt_up"] == 1 and m["halt_other"] == 1 and m["halt_active"] is True and len(m["halts"]) == 3                 # 7.5 < 직전가 → 하한, 9.9 > 직전가 → 상한, T1 → 기타(재개 없음)
    assert [h["dir"] for h in m["halts"]] == ["상한", "하한", None] and m["halts"][1]["price_before"] > 8.0 and m["halts"][2]["resume"] is None
    assert m["short"]["sv_ratio"] == 80.0 and m["short_note"] is None and "warrant_filings" in m
    assert rows["NOSEC"]["halts"] == [] and rows["NOSEC"]["halt_down"] == 0                                                                           # 정지 이력이 없는 종목은 빈 목록(확인은 됨)
    ev = cw.evaluate(m); by = {i["key"]: i["status"] for i in ev["items"]}; print(ev["grade"], by)
    assert by["buy"] == "pass" and by["halt"] == "pass" and by["short"] == "pass" and by["no_warrant"] in ("pass", "unknown")
    # 피드/Fintel 이 없으면 확인 불가로 남음
    cw.update(conn, tc, fs, ["AAA"], frames={"AAA": frame}, now=t0 + timedelta(minutes=70))
    m2 = json.loads(conn.execute("SELECT metrics FROM close_state WHERE ticker='AAA'").fetchone()["metrics"])
    assert m2["halts"] is None and m2["short"] is None and "공매도 데이터 미연결" in m2["short_note"]
    s2 = {i["key"]: i["status"] for i in cw.evaluate(m2)["items"]}; assert s2["halt"] == "unknown" and s2["short"] == "unknown"
print("update OK")

# ---------- 스캐너 통합: 정규장 + 토스 사용 시 close_state 가 생기고, 장외/토스 없음이면 건드리지 않음 ----------
idx = pd.bdate_range(end=pd.Timestamp("2026-10-09"), periods=47)[-45:][-40:]
daily_y = pd.DataFrame({"Open": 10., "High": 10.5, "Low": 9.5, "Close": 10., "Volume": 1e6}, index=idx)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: daily_y for t in tk}
market.download_intraday = lambda tk: {t: frame for t in tk}
market.fetch_fundamentals = lambda t: {"name": t, "exchange": "NASDAQ", "float_shares": 8e6, "shares_out": 9e6, "market_cap": 1e7}
universe.get_universe = lambda *a, **k: (["CWAA"], {"CWAA"})
class STC(FakeTC):
    def exchange_rate(s): return 1400.0
    def us_calendar(s): return {}
    def rankings(s, t, c, d, n): return [{"symbol": "CWAA", "price": {"lastPrice": "7.9", "basePrice": "10"}}]   # 토스 급하락 1위
class FS2(sec.SecClient):
    def __init__(s): pass
    def cik_for(s, t): return 7
    def submissions(s, c):
        return {"filings": {"recent": {"accessionNumber": [], "primaryDocument": [], "form": [], "filingDate": [], "items": []}}}
scanner.notify.send_telegram = lambda x: True
cw._DAILY.clear()
with closing(db.connect()) as conn:
    scanner.is_regular_session = lambda now=None: False
    scanner.run_cycle(conn, FS2(), STC())
    assert conn.execute("SELECT COUNT(*) FROM close_state WHERE ticker='CWAA'").fetchone()[0] == 0             # 정규장이 아니면 기록하지 않음
    scanner.is_regular_session = lambda now=None: True
    scanner.run_cycle(conn, FS2(), None)
    assert conn.execute("SELECT COUNT(*) FROM close_state WHERE ticker='CWAA'").fetchone()[0] == 0             # 토스 없으면 기록하지 않음
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    db.set_meta("us_regular_end", _dt(2026, 10, 12, 16, 0, tzinfo=_Z("America/New_York")).isoformat())
    cw._now = lambda: _dt(2026, 10, 12, 14, 0, tzinfo=_Z("America/New_York"))         # 마감 2시간 전: 순위만 기록, 체크리스트 기록 없음
    scanner.run_cycle(conn, FS2(), STC())
    assert conn.execute("SELECT COUNT(*) FROM close_state WHERE ticker='CWAA'").fetchone()[0] == 0
    cw._now = lambda: _dt(2026, 10, 12, 15, 5, tzinfo=_Z("America/New_York"))         # 마감 1시간 전 지남: 급하락 순위로 고정 후 기록
    scanner.run_cycle(conn, FS2(), STC())
    r = conn.execute("SELECT metrics FROM close_state WHERE ticker='CWAA'").fetchone()
    assert r is not None and json.loads(r["metrics"])["drop_pct"] < -20
print("scanner hook OK")
print("ALL OK"); print(os.environ["QUANT_DB"])
