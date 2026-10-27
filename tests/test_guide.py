import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import db, halts, access, guide_content as gc
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
assert len(gc.SECTIONS) == 37 and all(s["body"] for s in gc.SECTIONS)
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "guide"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
tabs = [t.label for t in at.tabs]; print(tabs)
assert tabs == ["🚀 시작하기", "🗺 화면별 사용법", "📚 용어 사전", "❓ 자주 묻는 질문", "🛠 주인 전용"]
assert any("처음이라면 이 순서로" in e.label for e in at.expander) and any("\\$1 상장유지" in m.value for m in at.markdown)   # '$' 안전 처리
at.text_input(key="gd_q").set_value("baby shelf").run(); assert not at.exception
hits = [e.label for e in at.expander]; print(hits); assert len(hits) >= 2 and all("baby" in (e.label + "".join(m.value for m in e.markdown)).lower() for e in at.expander)
# 방문객: 주인 전용 탭·관리 화면 설명 없음
tok = access.create("민수", 24, False)
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = tok; at.run(); [b for b in at.button if b.key == "_guest_agree"][0].click().run()
assert not at.exception, [e.value for e in at.exception]
tabs = [t.label for t in at.tabs]; assert "🛠 주인 전용" not in tabs and not any("워치리스트 · 🗓 일정" in e.label for e in at.expander)
assert any("📖 가이드북" in i.value for i in at.info)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
