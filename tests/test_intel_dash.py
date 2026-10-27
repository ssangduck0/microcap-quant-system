import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, intel, closewatch as cw, halts, scanner, market, universe, sec, tossws
db.init_db(); cw.ensure_tables(); intel.ensure_table()
ETZ = ZoneInfo("America/New_York")
# ---------- 1) 실시간 구독: 우선순위 순서로 50개 자름(알파벳순 아님) ----------
col = tossws.FlowCollector(lambda: "tok")
syms = [f"Z{i:02d}" for i in range(60)] + ["AAA"]                      # AAA 는 61번째(우선순위 최하) → 빠져야 함
col.set_symbols(syms); assert "AAA" not in col._symbols and "Z00" in col._symbols and len(col._symbols) == 50
col.set_symbols(["AAA"] + syms); assert "AAA" in col._symbols and "Z49" not in col._symbols
print("subscription priority OK")
# ---------- 2) 스캐너: 정규장이 아니어도 저장한 모든 종목의 공통 인텔 계산, 실시간 구독은 모든 세션 ----------
ridx = pd.date_range("2026-10-12 09:30", "2026-10-12 15:59", freq="min", tz=ETZ)
c = np.linspace(9.0, 7.9, len(ridx)); frame = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 500.0}, index=ridx)
idx = pd.bdate_range(end=pd.Timestamp("2026-10-09"), periods=47)[-45:][-40:]
daily_y = pd.DataFrame({"Open": 10., "High": 10.5, "Low": 9.5, "Close": 10., "Volume": 1e6}, index=idx)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: daily_y for t in tk}
market.download_intraday = lambda tk: {t: frame for t in tk}
market.fetch_fundamentals = lambda t: {"name": t, "exchange": "NASDAQ", "float_shares": 8e6, "shares_out": 9e6, "market_cap": 1e7}
universe.get_universe = lambda *a, **k: (["IA", "IB"], {"IA", "IB"})
class FS(sec.SecClient):
    def __init__(s): pass
    def cik_for(s, t): return 7
    def submissions(s, c): return {"filings": {"recent": {"accessionNumber": [], "primaryDocument": [], "form": [], "filingDate": [], "items": []}}}
class Col:
    connected = False
    def __init__(s): s.sets = []
    def set_symbols(s, x): s.sets.append(list(x))
scanner.notify.send_telegram = lambda x: True
halts.fetch = lambda *a, **k: []
scanner.is_regular_session = lambda now=None: False
cc = Col()
with closing(db.connect()) as conn:
    scanner.run_cycle(conn, FS(), None, cc, None)
    rows = {r["ticker"]: json.loads(r["data"]) for r in conn.execute("SELECT ticker, data FROM ticker_intel")}
    print(sorted(rows), cc.sets)
    assert set(rows) == {"IA", "IB"} and cc.sets and set(cc.sets[-1]) == {"IA", "IB"}                 # 장외에도 계산·구독
    assert rows["IA"]["halt"] == {"halts": [], "halt_up": 0, "halt_down": 0, "halt_other": 0, "halt_active": False, "src": halts.last_source}
    assert rows["IA"]["short_note"] == intel.NO_FINTEL and rows["IA"]["sec"]["intraday"] == []
    assert conn.execute("SELECT COUNT(*) FROM close_state").fetchone()[0] == 0                          # 장마감 체크리스트는 정규장에만
print("scanner OK")
# ---------- 3) 대시보드: 스냅샷 표의 요약 열, 종목 상세·리포트의 상세 섹션 ----------
with closing(db.connect()) as conn:
    snap_date = conn.execute("SELECT MAX(date) FROM daily_snapshots").fetchone()[0]
    data = {"day": snap_date, "cs": {"late": 135.0, "prior": 90.0, "cum": 110.0, "source": "토스 실시간(체결가↔호가)", "trades": 1234},
            "halt": {"halts": [{"time": "10-12 11:00:00", "code": "LUDP", "reason": "변동성 정지(LULD)", "threshold": 7.0, "price_before": 8.6, "dir": "하한", "resume": "11:05:00", "carry": False}],
                     "halt_up": 0, "halt_down": 1, "halt_other": 0, "halt_active": False, "src": "upcuit"},
            "sec": {"intraday": [{"form": "424B5", "url": "https://sec.gov/a", "tags": ["OFFERING"]}], "errors": 0,
                    "financing": {"type": "사모(PIPE)", "label": "출회 제한(재판매 등록 전)", "date": "2026-10-09", "form": "8-K", "url": "https://sec.gov/b", "sellable": "restricted"},
                    "warrants": [{"form": "8-K", "date": "2026-10-09", "url": "https://sec.gov/b"}]},
            "sec_at": "2026-10-12T19:00:00+00:00", "short": {"sv_date": "2026-10-09", "sv_ratio": 72.0, "sv_avg5_ratio": 55.0, "borrow_fee": 33.3, "borrow_avail": 5000.0}, "short_note": None}
    intel.save(conn, snap_date, "IA", data)
from streamlit.testing.v1 import AppTest
import streamlit as st
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
st.cache_data.clear()
at = AppTest.from_file(APP, default_timeout=90).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
snap = [d.value for d in at.dataframe if "체결강도(%)" in d.value.columns and "퀀트점수" in d.value.columns][0]
r = snap[snap["티커"] == "IA"].iloc[0]; print(r[intel_cols := ["체결강도(%)", "체강 출처", "거래정지", "공매도(전일%)", "대차수수료(%)", "장중 희석", "자금조달(7일)", "워런트(7일)"]].to_dict())
assert r["체결강도(%)"] == 135.0 and r["체강 출처"] == "실시간" and r["거래정지"] == "하킷 1 · 상킷 0" and r["공매도(전일%)"] == 72.0 and r["장중 희석"] == "❌ 1건"
assert r["자금조달(7일)"] == "사모(PIPE) · 출회 제한(재판매 등록 전)" and r["워런트(7일)"] == "⚠️ 1건"
cols = list(snap.columns); assert cols.index("가격 흐름(2시간)") == cols.index("희석상태") + 1 and cols.index("체결강도(%)") == cols.index("희석상태") + 3   # 희석상태 뒤: 미니 차트 2개, 체결강도
assert snap[snap["티커"] == "IB"].iloc[0]["체강 출처"] in ("추정", "")                                       # 실시간 없는 종목은 추정/빈칸
md = " ".join(m.value for m in at.markdown)
titles = [m.value for m in at.markdown if "📡" in m.value]
assert any("📡 IB 체결강도" in x for x in titles) and any("📡 IA 체결강도" in x for x in titles)          # 종목 상세(표 첫 종목 IB) + 종목 리포트(IA) 모두 같은 섹션
assert any("sec.gov/b" in i.value and "출회 제한" in i.value for i in at.info)                              # 출회 제한형 자금조달은 파란 정보 상자 + 근거 링크
assert any(m.label == "최근 30분" and m.value == "135%" for m in at.metric) and any(m.label == "하킷 / 상킷" and m.value == "1 / 0" for m in at.metric)
assert any("장중 희석: 오늘 공시 1건 중 희석 정황 1건" in e.value for e in at.error)
assert any("📡 체결강도" in e.label for e in at.expander)                                                     # 종목 리포트 탭에도 같은 섹션
# 지금 조회 버튼: 토스 없이 intel.on_demand 호출
called = []
intel.on_demand = lambda conn, client, t, fc=None, hl=None, today=None: called.append(t) or data
btn = [b for b in at.button if b.label == "🔄 지금 조회"][0]; btn.click().run()
assert called and not at.exception
print("ALL OK")
