import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, intel, closewatch as cw, halts
db.init_db(); cw.ensure_tables()
ETZ = ZoneInfo("America/New_York")
idx = pd.date_range("2026-10-12 09:30", "2026-10-12 15:59", freq="min", tz=ETZ); n = len(idx)
close = np.r_[np.linspace(9.0, 7.5, n - 30), np.linspace(7.52, 7.9, 30)]
frame = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1000.0}, index=idx)
class FakeSec:
    def __init__(s): s.subs = 0
    def cik_for(s, t): return 7
    def submissions(s, c):
        s.subs += 1
        return {"filings": {"recent": {"accessionNumber": ["0001-01", "0001-02"], "primaryDocument": ["a.htm", "b.htm"], "form": ["424B5", "8-K"],
                                       "filingDate": ["2026-10-12", "2026-10-09"], "items": ["", "3.02"]}}}
    def fetch_text(s, url): return "registered direct offering of shares and warrants to purchase common stock" if "000101" in url else "private placement section 4(a)(2) warrants to purchase"
class FakeFintel:
    def __init__(s): s.calls = []
    def summary(s, t): s.calls.append(t); return {"sv_date": "2026-10-09", "sv_ratio": 70.0, "sv_avg5_ratio": 50.0, "sv_short": 7.0, "borrow_fee": 25.0, "errors": []}
HL = [{"symbol": "AAA", "name": "A", "market": "NASDAQ", "code": "LUDP", "threshold": 7.0, "status": "resumed", "halt": datetime(2026, 10, 12, 11, 0, tzinfo=ETZ),
       "resume": datetime(2026, 10, 12, 11, 5, tzinfo=ETZ), "title": None}]
halts.last_source = "upcuit"
t0 = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
fs, ff = FakeSec(), FakeFintel()
intel._SEC_AT.clear(); intel._FIN_AT.clear()
with closing(db.connect()) as conn:
    out = intel.compute(conn, fs, ["AAA", "BBB", "AAA"], frames={"AAA": frame}, halts_list=HL, fintel_client=ff, sec_budget=1, fintel_budget=1, now=t0)
    assert list(out) == ["AAA", "BBB"]                                                            # 중복 제거, 순서 유지
    a = out["AAA"]; print(json.dumps({k: a[k] for k in ("cs", "halt")}, ensure_ascii=False, default=str)[:400])
    assert a["day"] == "2026-10-12" and a["cs"]["source"].startswith("1분봉 추정") and a["cs"]["late"] == 999.0             # 실시간 없으면 1분봉 추정(마지막 30분 전부 상승)
    assert a["halt"]["halt_down"] == 1 and a["halt"]["src"] == "upcuit"                                                       # 7.0 < 직전가 → 하킷
    assert a["sec"]["financing"]["type"] == "공모/등록직접" and a["sec"]["intraday"][0]["form"] == "424B5" and len(a["sec"]["warrants"]) == 2
    assert a["short"]["sv_ratio"] == 70.0 and a["short_note"] is None
    b = out["BBB"]; assert b["sec"] is None and b["short"] is None and b["cs"] is None and b["day"] == "2026-10-12"           # 한도(SEC 1, Fintel 1) 초과 → 확인 전
    assert fs.subs == 1 and ff.calls == ["AAA"]
    # 다음 사이클(5분 뒤): 주기(SEC 10분·Fintel 20분) 전이라 AAA 는 직전 값 유지, BBB 는 이제 확인
    out2 = intel.compute(conn, fs, ["AAA", "BBB"], frames={"AAA": frame}, halts_list=HL, fintel_client=ff, sec_budget=5, fintel_budget=5, now=t0 + timedelta(minutes=5))
    assert fs.subs == 2 and ff.calls == ["AAA", "BBB"] and out2["AAA"]["sec"] == a["sec"] and out2["AAA"]["short"] == a["short"] and out2["BBB"]["sec"] is not None
    # 11분 뒤: AAA SEC 재확인(10분 경과), Fintel 은 아직(20분)
    intel.compute(conn, fs, ["AAA"], frames={"AAA": frame}, halts_list=HL, fintel_client=ff, now=t0 + timedelta(minutes=11))
    assert fs.subs == 3 and ff.calls == ["AAA", "BBB"]
    # 실시간 집계(close_flow)가 있으면 그게 우선
    for i in range(40):
        conn.execute("INSERT OR REPLACE INTO close_flow (minute,ticker,date,buy_sh,sell_sh,mid_sh,n_trades,ask_usd_avg,ask_usd_last,n_books) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ((datetime(2026, 10, 12, 19, 20, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat(), "AAA", "2026-10-12", 60.0, 40.0, 0.0, 3, 1000.0, 1000.0, 2))
    conn.commit()
    out3 = intel.compute(conn, fs, ["AAA"], frames={"AAA": frame}, halts_list=None, fintel_client=None, now=t0 + timedelta(minutes=12))
    c3 = out3["AAA"]; assert c3["cs"]["source"].startswith("토스 실시간") and abs(c3["cs"]["late"] - 150.0) < 1e-6 and abs(c3["cs"]["cum"] - 150.0) < 1e-6
    assert c3["halt"]["halt_down"] == 1 and c3["short"] is None and c3["short_note"] == intel.NO_FINTEL                       # 피드 실패 시 직전 거래정지 유지, Fintel 미연동 문구
    # 요약 문구(표 한 줄)
    sc = intel.summary_cells(out2["AAA"]); print(sc)
    assert sc["체강 출처"] == "추정" and sc["거래정지"].startswith("하킷 1 · 상킷 0") and sc["공매도(전일%)"] == 70.0 and sc["장중 희석"] == "❌ 1건"
    assert sc["자금조달(7일)"].startswith("공모/등록직접") and sc["워런트(7일)"] == "⚠️ 2건"
    assert intel.summary_cells(None)["장중 희석"] == "확인 전" and intel.summary_cells({"sec": {"error": "x"}, "halt": None})["장중 희석"] == "확인 불가"
    assert intel.summary_cells(c3)["체강 출처"] == "실시간"
    # 장마감 체크리스트는 공통 인텔의 SEC·Fintel 값을 그대로 사용 → 추가 호출 없음
    class TC:
        def stocks(s, sy): return []
        def daily_candles(s, sym, count=25): return []
        def orderbook(s, sym): return {"asks": [], "bids": []}
    n_subs = fs.subs; ff2 = FakeFintel(); cw._DAILY.clear()
    cw.update(conn, TC(), fs, ["AAA"], frames={"AAA": frame}, halts_list=HL, fintel_client=ff2, intel_map={"AAA": out2["AAA"]}, now=t0)
    m = json.loads(conn.execute("SELECT metrics FROM close_state WHERE ticker='AAA'").fetchone()["metrics"])
    assert fs.subs == n_subs and ff2.calls == [] and m["financing"]["type"] == "공모/등록직접" and m["short"]["sv_ratio"] == 70.0
    # on_demand(대시보드 버튼): 토스 없이 SEC·거래정지·Fintel 갱신, 체결강도는 유지
    od = intel.on_demand(conn, fs, "AAA", FakeFintel(), HL, today=datetime(2026, 10, 12).date())
    assert od["cs"] == c3["cs"] and od["sec"]["financing"] and od["short"]["sv_ratio"] == 70.0 and intel.latest(conn, "AAA")[0] == "2026-10-12"
print("ALL OK")
