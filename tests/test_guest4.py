import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import db, halts, access, requests
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
db.set_meta("guest_tunnel_url", "https://dale-lender-blog-farmer.trycloudflare.com")
def dead(u, timeout=6, **kw): raise requests.exceptions.ConnectionError("NXDOMAIN")
requests.get = dead
os.environ["QUANT_TEST_PAGE"] = "admin"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert any("응답하지 않아요" in e.value for e in at.error) and [b for b in at.button if b.key == "gu_make"][0].disabled       # 죽은 주소로는 못 만듦
tok = access.create("민수", 24, False)
def alive(u, timeout=6, **kw):
    class R: status_code = 200
    return R()
requests.get = alive
db.set_meta("guest_tunnel_url", "https://new-address.trycloudflare.com")                               # 터널이 새 주소로
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception
assert not [b for b in at.button if b.key == "gu_make"][0].disabled
assert any(c.value == f"https://new-address.trycloudflare.com/?guest={tok}" for c in at.code)          # 같은 토큰을 새 주소로 다시 보기
import tunnel
db.set_meta("guest_tunnel_url", "https://old.trycloudflare.com"); tunnel.KEY = "guest_tunnel_url"
tunnel.password_ok = lambda: (True, ""); tunnel.find_cloudflared = lambda: None
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
