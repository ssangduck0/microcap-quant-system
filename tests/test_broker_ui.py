"""💵 관리 모드 '실매매' 구역(broker_ui, 2026-10-29): 두 단계 스위치(문구 없이는 안 켜짐) · 끄기 · 1주 왕복 요청 · 킬 요청 · 한도 저장(기본값과 다른 것만) · 킬 해제."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"; os.environ["QUANT_TEST_PAGE"] = "admin"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import config, db, broker, broker_ui
db.init_db()
with closing(db.connect()) as conn:
    broker.ensure(conn)
    now = db.utcnow_iso()
    db.upsert_snapshot(conn, {"date": "2026-10-28", "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -40.0,
                              "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}',
                              "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert any("💵 실매매" in e.label for e in at.expander)
btn = lambda k: [b for b in at.button if b.key == k][0]
assert btn("live_on2").disabled and btn("live_off").disabled and "LIVE_TRADING" not in config.overrides()           # 꺼진 상태: 2단계 버튼 잠김
at.text_input(key="live_confirm").set_value("아무거나").run(); assert btn("live_on2").disabled                       # 문구가 다르면 잠김
at.text_input(key="live_confirm").set_value(broker_ui.CONFIRM).run(); assert not btn("live_on2").disabled
btn("live_on2").click().run(); assert not at.exception and config.overrides().get("LIVE_TRADING") is True and config.LIVE_TRADING is True
assert btn("live_on2").disabled and not btn("live_off").disabled
# 1주 왕복 요청 → 요청 표
at.text_input(key="live_probe_t").set_value("aapl").run(); btn("live_probe").click().run(); assert not at.exception
with closing(db.connect()) as conn:
    req = [dict(r) for r in conn.execute("SELECT kind, ticker, done_at FROM live_requests ORDER BY id")]
assert req == [{"kind": "probe", "ticker": "AAPL", "done_at": None}], req
# 한도 저장: 기본값과 다른 것만 overrides 에
at.number_input(key="live_LIVE_MAX_OPEN").set_value(2)                      # 폼 안 위젯은 run() 없이 값만 두고 제출 버튼으로
[b for b in at.button if b.label == "한도 저장"][0].click().run(); assert not at.exception
ov = config.overrides(); assert ov.get("LIVE_MAX_OPEN") == 2 and "LIVE_MAX_PRICE" not in ov and config.LIVE_MAX_OPEN == 2, ov
# 킬 스위치 → 요청 + 즉시 끔
btn("live_kill").click().run(); assert not at.exception
with closing(db.connect()) as conn:
    kinds = [r[0] for r in conn.execute("SELECT kind FROM live_requests ORDER BY id")]
assert kinds == ["probe", "kill"] and config.LIVE_TRADING is False and config.overrides().get("LIVE_TRADING") is None, (kinds, config.overrides())   # 기본값(꺼짐)과 같으면 저장 안 함
# 킬 메모가 있으면 해제 버튼
db.set_meta("live:kill", "2026-10-29 테스트"); at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
assert any(b.key == "live_unkill" for b in at.button) and not any(b.key == "live_kill" for b in at.button)
[b for b in at.button if b.key == "live_unkill"][0].click().run(); assert not broker.killed()
# 끄기
at.text_input(key="live_confirm").set_value(broker_ui.CONFIRM).run(); [b for b in at.button if b.key == "live_on2"][0].click().run()
assert config.LIVE_TRADING is True; [b for b in at.button if b.key == "live_off"][0].click().run(); assert config.LIVE_TRADING is False and config.overrides().get("LIVE_TRADING") is None
print("ALL OK")
