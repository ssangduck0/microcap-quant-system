import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys
import tempfile
DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.mkdtemp(), "q.db"); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=DB; os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
import db, report, sec
db.init_db()
with closing(db.connect()) as conn:
    conn.execute("""INSERT OR REPLACE INTO daily_snapshots (date,ticker,exchange,first_seen,last_seen,price,high_20d,low_20d,drawdown_pct,volume_mult,buy_pressure,float_shares,atr14,entry_ref,stop_ref,target_ref,quant_score,quant_detail,pump_score,pump_detail,dilution_status,excluded)
      VALUES ('2026-10-12','MNDR','NASDAQ',datetime('now'),datetime('now'),0.85,1.5,0.8,-43,13,60,560000,0.1,0.8,0.7,1.0,60,'{}',50,'{"checks":[]}','ATM',0)""")
    conn.commit()
# 저장된 리포트가 있어야 1~6 섹션이 그려짐(예전엔 리포트가 든 DB를 인자로 넘겼음) → 최소 리포트를 직접 넣음
db.save_report("MNDR", {"ticker": "MNDR", "generated_at": db.utcnow_iso(), "errors": {}, "cik": 1,
    "company": {"name": "M Corp", "exchange": "NASDAQ", "price": 0.85, "market_cap": 5e6, "shares_out": 6e6, "float_shares": 5.6e5},
    "runway": {"runway_months": 3.0, "cash": 1.5e6, "monthly_burn": 0.5e6, "cash_asof": "2026-06-30"},
    "financing": {"events": []}, "insiders": {"rows": [], "days": 180, "summary": {}}, "timeline": []})
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=60).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
print("tabs:", [t.label for t in at.tabs])
md = [m.value for m in at.markdown]
for needle in ["### 1. 회사","### 2. 희석 · 조달","### 3. 런웨이","### 4. 내부자 거래 (Form 4)","### 5. 내 메모","### 6. 타임라인"]:
    assert any(needle in m for m in md), needle
print("metrics:", [(m.label, m.value) for m in at.metric if m.label in ("종가","시가총액","유통주식","현금","런웨이","월 소모량(영업CF)")])
print("warnings/errors:", [w.value[:70] for w in at.warning][:3], [e.value[:70] for e in at.error][:3])
print("dataframes:", len(at.dataframe))
# 메모 저장
at.text_area(key="note_MNDR").set_value("테스트 메모").run()
assert db.get_note("MNDR") and "테스트 메모" in str(db.get_note("MNDR")) and not at.exception, db.get_note("MNDR")
# 리포트 없는 종목 + 생성 버튼 경로(네트워크는 가짜로)
class FakeClient: 
    def __init__(s, ua): pass
sec.SecClient = FakeClient
called=[]
def fake_build(client, conn, ticker, today=None):
    called.append(ticker); return {"ticker":ticker,"generated_at":db.utcnow_iso(),"errors":{"sec":"테스트 실패 사유"},"cik":None,"company":{"name":"X Corp","exchange":"NASDAQ"},"timeline":[]}
report.build_report = fake_build
at.text_input(key="rep_extra").set_value("ZZZZ").run()
print("no-report info:", [i.value[:50] for i in at.info if "ZZZZ" in i.value])
[b for b in at.button if "리포트 생성" in b.label][0].click().run()
assert called == ["ZZZZ"] and not at.exception, (called, [e.value for e in at.exception])
print("after build warnings:", [w.value[:60] for w in at.warning])
print("UI OK")
