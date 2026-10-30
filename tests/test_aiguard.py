"""🤖⚠️ aiguard — Anthropic 계정 문제(충전 잔액·키) 감지: 분류 · 기록 + 하루 한 번 텔레그램 · 성공하면 저절로 지움 · call_claude/aisummary 연결 · 관리 모드 빨간 경고."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import db, aiguard

db.init_db()
CREDIT = '{"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}}'
assert aiguard.classify(400, CREDIT) == "Anthropic 계정 충전 잔액 부족"
assert aiguard.classify(401, '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}').startswith("Anthropic API 키 오류")
assert aiguard.classify(400, '{"error":{"type":"invalid_request_error","message":"max_tokens: too large"}}') is None   # 요청 오류는 사용자 계정 문제 아님
assert aiguard.classify(529, "overloaded_error") is None and aiguard.classify(None, None) is None

sent = []
assert aiguard.note(400, CREDIT, send=sent.append) == "Anthropic 계정 충전 잔액 부족" and len(sent) == 1 and "충전" in sent[0] and sent[0].startswith("🤖")
assert aiguard.note(400, CREDIT, send=sent.append) and len(sent) == 1                 # 같은 날 두 번째는 텔레그램 안 보냄
pb = aiguard.problem(); assert pb and pb["reason"] == "Anthropic 계정 충전 잔액 부족", pb
aiguard.ok(); assert aiguard.problem() is None
assert aiguard.note(400, "bad request", send=sent.append) is None and aiguard.problem() is None and len(sent) == 1

# call_claude: 400(충전 부족) → 기록 · 성공 → 지움
import aipick, notify
notify.send_telegram = lambda m: sent.append(m) or True
db.set_meta(aiguard.ALERT_KEY, "")
class R:
    def __init__(s, code, text, js=None): s.status_code, s.text, s._j = code, text, js
    def json(s): return s._j
os.environ["ANTHROPIC_API_KEY"] = "test-key"
try:
    aipick.call_claude("hi", "claude-haiku-5-5", post=lambda *a, **k: R(400, CREDIT)); raise SystemExit("should raise")
except RuntimeError as e:
    assert "HTTP 400" in str(e)
assert aiguard.problem() and len(sent) == 2
txt, tin, tout = aipick.call_claude("hi", "claude-haiku-5-5", post=lambda *a, **k: R(200, "", {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 3, "output_tokens": 2}}))
assert txt == "ok" and aiguard.problem() is None

# aisummary.call 도 같은 판단
import aisummary
aisummary.budget_left_krw = lambda: 1e9
try:
    aisummary.call("sys", "user", http_post=lambda url, headers, body: R(400, CREDIT)); raise SystemExit("should raise")
except RuntimeError as e:
    assert "API 오류 400" in str(e)
assert aiguard.problem()

# 관리 모드: 빨간 경고(빈 DB 면 화면이 '스캔 기록 없음' 에서 멈추므로 스냅샷 한 줄 — test_admin 과 같게)
from contextlib import closing
import halts
halts.fetch = lambda *a, **k: []
os.environ["SEC_USER_AGENT"] = "T t@e.com"
_now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-16", "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": _now, "last_seen": _now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
os.environ["DASH_PASSWORD"] = ""; os.environ["QUANT_TEST_PAGE"] = "admin"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(os.path.join(os.environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]
assert any("충전 잔액 부족" in e.value for e in at.error), [e.value[:60] for e in at.error]
aiguard.ok()
at2 = AppTest.from_file(os.path.join(os.environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run()
assert not any("충전 잔액 부족" in e.value for e in at2.error)
os.environ.pop("QUANT_TEST_PAGE")
print("ALL OK")
