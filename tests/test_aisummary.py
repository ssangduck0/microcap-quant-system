import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import db, aisummary as ai, forensic, config, halts
os.environ["ANTHROPIC_API_KEY"] = "test-key"   # config 오프라인 모드가 import 때 진짜 키를 비우므로 가짜 키는 그 뒤에(가짜 http_post 로만 호출)
db.init_db(); halts.fetch = lambda *a, **k: []; db.set_meta("usdkrw", "1350")
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "NIVF", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.279, "high_20d": 0.5, "low_20d": 0.25,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "ATM", "excluded": 0})
db.save_report("NIVF", {"ticker": "NIVF", "generated_at": now, "errors": {}, "runway": {"runway_months": 1.5, "cash": 0.5e6, "monthly_burn": 0.33e6, "cash_asof": "2026-06-30"},
                        "company": {}, "financing": {"events": []}, "timeline": []})
f = ai.facts("NIVF"); print(list(f))
assert f["런웨이(종목 리포트·XBRL)"]["runway_months"] == 1.5 and f["스캐너"]["희석판정"] == "ATM" and f["회사 압박"]["점수"] >= 3
calls = []
class R:
    def __init__(s, j, code=200): s._j, s.status_code, s.text = j, code, json.dumps(j)
    def json(s): return s._j
SUM = {"판정": "회피 — ATM 열림", "매수 동기": "상장유지 (추정)", "해소하려는 문제": "$1", "압박 목적": "조달", "가격 사다리": ["$1.00"], "출회 주체": "ATM", "주의사항": ["희석"],
       "한줄요약": "압박은 크지만 ATM 이 열려 있음", "확인필요": ["ATM 잔여 한도"]}
CHK = {"항목": [{"이름": "런웨이", "A": "1.5개월", "B": "2개월", "판정": "일치", "메모": ""}, {"이름": "ATM·ELOC", "A": "열림", "B": "잔여 없음", "판정": "다름", "메모": "원문 확인"}],
       "일치율": 70, "종합": "대체로 일치", "원문확인": ["ATM 잔여"]}
def post(url, headers, body):
    calls.append((url, headers, body))
    assert headers["x-api-key"] == "test-key" and headers["anthropic-version"] and body["model"] == ai.model() and body["messages"][0]["role"] == "user"
    out = CHK if "검증자" in body["system"] else SUM
    return R({"content": [{"type": "text", "text": "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"}], "usage": {"input_tokens": 3000, "output_tokens": 800}})
s = ai.summarize("NIVF", http_post=post); print(round(s["_cost_krw"], 1))
assert s["판정"].startswith("회피") and abs(s["_cost_krw"] - (3000 * 2 + 800 * 10) / 1e6 * 1350) < 1e-6 and len(calls) == 1
assert ai.summarize("NIVF", http_post=post)["판정"].startswith("회피") and len(calls) == 1                      # 같은 날은 저장본(호출 안 함)
assert "사실" in ai.SYSTEM and "추정" in ai.SYSTEM and '"티커": "NIVF"' in calls[0][2]["messages"][0]["content"]
try:
    ai.cross_check("NIVF", http_post=post); raise SystemExit("should fail without forensic")
except RuntimeError as e:
    assert "덕구 스캔 보고서가 없습니다" in str(e)
forensic.add("NIVF", "## NIVF 덕구 스캔\n런웨이 2개월 · ATM 잔여 한도 없음")
c = ai.cross_check("NIVF", http_post=post); assert c["일치율"] == 70 and [x["이름"] for x in ai.conflicts(c)] == ["ATM·ELOC"] and "덕구 스캔" in calls[-1][2]["messages"][0]["content"] and "시스템 데이터" in calls[-1][2]["messages"][0]["content"]
assert abs(ai.month_spend_usd() - 2 * (3000 * 2 + 800 * 10) / 1e6) < 1e-9
config.AI_MONTHLY_BUDGET_KRW = 10                                                                          # 예산 초과 → 호출 안 함
try:
    ai.summarize("NIVF", force=True, http_post=post); raise SystemExit("should block")
except RuntimeError as e:
    assert "예산이 부족" in str(e)
config.AI_MONTHLY_BUDGET_KRW = 10000
assert ai._json("not json at all")["확인필요"]                                                              # 형식이 깨져도 보여 줌
# 화면(종목 검색)
os.environ["QUANT_TEST_PAGE"] = "lookup"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180)
at.session_state["lookup_ticker"] = "NIVF"; at.run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown); assert "일치율 70%" in html and "압박은 크지만 ATM 이 열려 있음" in html and "해소하려는 문제" in html
assert any("어긋난 항목" in e.value and "ATM·ELOC" in e.value for e in at.error)
tbl = [d.value for d in at.dataframe if "덕구 스캔(공시 원문)" in d.value.columns][0]; assert list(tbl["판정"]) == ["✅ 일치", "⚠️ 다름"] and "우리 시스템 데이터" in tbl.columns
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
