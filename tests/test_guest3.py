import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import db, halts, access
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
assert "투자 권유가 아닙니다" in access.notice() and "무단 공유" in access.notice()
css = access.watermark_css("민수 · 10/19 14:05 · 무단 배포 금지"); assert "pointer-events:none" in css and "data:image/svg+xml" in css and "%EB%AF%BC%EC%88%98" in css   # '민수' 인코딩
assert access.short_ip("2001:4430:d07f:5070:7531:5ae1:947:7") == "2001:4430:…" and access.short_ip("211.1.2.3") == "211.1.2.3"
tok = access.create("민수", 24, False)
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = tok; at.run(); assert not at.exception
assert any("열람 전용" in w.value and "투자 권유가 아닙니다" in w.value for w in at.warning) and not at.get("page_link") and not at.dataframe   # 동의 전엔 아무것도 안 보임
[b for b in at.button if b.key == "_guest_agree"][0].click().run(); assert not at.exception
assert at.get("page_link") and any("qk-wm" in m.value for m in at.markdown) and any("방문객 모드" in i.value for i in at.info)
v = access.visits(); assert v.iloc[0]["agreed_at"]                                                    # 동의 시각 기록
access.set_notice("새 경고 문구 — 공유 금지")
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = tok; at.run(); assert any("새 경고 문구" in w.value for w in at.warning)
os.environ["QUANT_TEST_PAGE"] = "admin"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
log = [d.value for d in at.dataframe if "경고 동의" in d.value.columns][0]; assert (log["경고 동의"] != "—").any()
at.text_area(key="gu_notice").set_value("관리자가 바꾼 문구"); [b for b in at.button if b.key == "gu_notice_save"][0].click().run(); assert access.notice() == "관리자가 바꾼 문구"
[b for b in at.button if b.key == "gu_notice_reset"][0].click().run(); assert access.notice() == access.DEFAULT_NOTICE.strip()
assert not any("qk-wm" in m.value for m in at.markdown)                                              # 주인 화면엔 워터마크 없음
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
