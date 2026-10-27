import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"; os.environ["DASH_PASSWORD"] = "ownerpass123"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import db, halts, access, notify
db.init_db(); halts.fetch = lambda *a, **k: []
sent = []; notify.send_telegram = lambda m: sent.append(m) or True
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
# 기기 정보 · 한 기기 전용
IPH = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1", "Cf-Connecting-Ip": "211.1.2.3", "Cf-Ipcountry": "KR"}
AND = {"User-Agent": "Mozilla/5.0 (Linux; Android 15) SamsungBrowser/27.0 Chrome/130", "CF-Connecting-IP": "1.2.3.4", "CF-IPCountry": "US"}
ci = access.client_info(IPH); assert ci["device"] == "아이폰 · 사파리" and ci["ip"] == "211.1.2.3" and ci["country"] == "KR"
assert access.client_info({})["ip"].startswith("로컬")
t1 = access.create("민수", 24, True)
assert access.record_visit(t1, ci)["allowed"] and access.record_visit(t1, ci) == {"allowed": True, "new_device": False, "name": "민수"}
r = access.record_visit(t1, access.client_info(AND)); assert r["allowed"] is False                           # 다른 기기 → 막힘
t2 = access.create("지수", 24, False)
access.record_visit(t2, ci); r = access.record_visit(t2, access.client_info(AND)); assert r["allowed"] and r["new_device"]   # 제한 없음 → 허용하되 새 기기 표시
v = access.visits(); assert len(v) == 5 and v["blocked"].sum() == 1 and v["new_device"].sum() == 2   # 차단된 시도도 새 기기
# 비밀번호 잠금
for i in range(9): assert access.pw_fail() is False
assert access.pw_fail() is True and access.pw_locked() > 14
import requests as _rq
def _fake_get(u, timeout=6, **kw):
    class R: status_code = 200
    return R()
_rq.get = _fake_get                                                                                 # 방문객 주소가 살아 있다고 가정
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run(); assert any("잠시 잠겼어요" in e.value for e in at.error) and not at.text_input
db.set_meta("pw_lock_until", "")
# 방문객 전용 서버: 링크 없이 → 비밀번호 창 없이 안내만, 링크로 → 열람
os.environ["QUANT_GUEST_ONLY"] = "1"
at = AppTest.from_file(APP, default_timeout=180).run(); assert any("방문객 링크로만" in w.value for w in at.warning) and not [x for x in at.text_input if x.key == "_pw_in"]
t3 = access.create("스터디", 24, False)
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = t3; at.run(); (lambda b: b and b[0].click().run())([x for x in at.button if x.key == "_guest_agree"]); assert not at.exception, [e.value for e in at.exception]
assert any("방문객 모드" in i.value for i in at.info) and any("👥 방문객 접속" in m and "스터디" in m for m in sent)
os.environ.pop("QUANT_GUEST_ONLY")
# 관리 모드: 방문객 전용 주소 · 접속 기록
os.environ.pop("DASH_PASSWORD"); os.environ["QUANT_TEST_PAGE"] = "admin"
db.set_meta("guest_tunnel_url", "https://guest-only.trycloudflare.com")
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
[b for b in at.button if b.key == "gu_make"][0].click().run()
assert any(c.value.startswith("https://guest-only.trycloudflare.com/?guest=") for c in at.code)
log = [d.value for d in at.dataframe if "기기·브라우저" in d.value.columns][0]; assert "🚫 차단(다른 기기)" in set(log["표시"]) and "⚠️ 새 기기" in set(log["표시"])
assert any("링크가 퍼졌을 수 있어요" in e.value and "2건" in e.value for e in at.error)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
