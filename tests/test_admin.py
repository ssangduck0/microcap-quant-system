import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
import db, config, halts
db.init_db(); halts.fetch = lambda *a, **k: []
base_top = config.CLOSE_WATCH_TOP_N
config.save_overrides({"CLOSE_WATCH_TOP_N": 999, "AFTER_ALERTS": "0", "NOT_A_SETTING": 1})
assert config.CLOSE_WATCH_TOP_N == 50 and config.AFTER_ALERTS is False and "NOT_A_SETTING" not in config.overrides()   # 범위 제한·형 변환·허용 목록
config.save_overrides({}); assert config.CLOSE_WATCH_TOP_N == base_top and config.AFTER_ALERTS is True
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-16", "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
open(os.path.join(tmp, "scanner.log"), "w", encoding="utf-8").write("line1\n공시 알림: 새 공시 3건\n")
config.MANUAL_TICKERS_FILE = os.path.join(tmp, "manual_tickers.txt")
os.environ["QUANT_TEST_PAGE"] = "admin"
import notify; sent = []; notify.send_telegram = lambda m: sent.append(m) or True
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
at.toggle(key="adm_AFTER_ALERTS").set_value(False); at.number_input(key="adm_CLOSE_WATCH_TOP_N").set_value(30)
[b for b in at.button if b.key == "adm_save"][0].click().run(); assert not at.exception
assert config.overrides() == {"AFTER_ALERTS": False, "CLOSE_WATCH_TOP_N": 30}                    # 기본값과 다른 것만 저장
at.text_area(key="adm_manual").set_value("aaa\n# 주석\n bbb \n"); [b for b in at.button if b.key == "adm_manual_save"][0].click().run()
assert open(config.MANUAL_TICKERS_FILE).read() == "AAA\nBBB\n"
[b for b in at.button if b.key == "adm_tg"][0].click().run(); assert sent and "테스트" in sent[0]
assert any("공시 알림: 새 공시 3건" in c.value for c in at.code)
assert any("아침 작업 경고·실패" in (e.label or "") for e in at.expander) and "아침 작업" in at.radio(key="adm_log").options   # 2026-10-30 filelog 경고 상자 · 로그 보기 목록
at.radio(key="adm_log").set_value("아침 작업").run(); assert not at.exception and any("파일이 없습니다" in c.value for c in at.caption)   # 임시 DB 폴더엔 cases.log 없음
[b for b in at.button if b.key == "adm_reset"][0].click().run(); assert config.overrides() == {}
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
