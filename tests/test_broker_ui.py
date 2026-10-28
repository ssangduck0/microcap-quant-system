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
assert any("dry-run 결과" in c.value and "아직 없음" in c.value for c in at.caption)                                 # 기록이 없을 땐 안내 글만(2026-10-29 아침)
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
btn("live_check").click().run(); assert not at.exception
with closing(db.connect()) as conn:
    assert [r[0] for r in conn.execute("SELECT kind FROM live_requests ORDER BY id")] == ["probe", "check"]
# 한도 저장: 기본값과 다른 것만 overrides 에
at.number_input(key="live_LIVE_MAX_OPEN").set_value(2)                      # 폼 안 위젯은 run() 없이 값만 두고 제출 버튼으로
[b for b in at.button if b.label == "한도 저장"][0].click().run(); assert not at.exception
ov = config.overrides(); assert ov.get("LIVE_MAX_OPEN") == 2 and "LIVE_MAX_PRICE" not in ov and config.LIVE_MAX_OPEN == 2, ov
# 킬 스위치 → 요청 + 즉시 끔
btn("live_kill").click().run(); assert not at.exception
with closing(db.connect()) as conn:
    kinds = [r[0] for r in conn.execute("SELECT kind FROM live_requests ORDER BY id")]
assert kinds == ["probe", "check", "kill"] and config.LIVE_TRADING is False and config.overrides().get("LIVE_TRADING") is None, (kinds, config.overrides())   # 기본값(꺼짐)과 같으면 저장 안 함
# 킬 메모가 있으면 해제 버튼
db.set_meta("live:kill", "2026-10-29 테스트"); at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
assert any(b.key == "live_unkill" for b in at.button) and not any(b.key == "live_kill" for b in at.button)
[b for b in at.button if b.key == "live_unkill"][0].click().run(); assert not broker.killed()
# 보유 선택 팔기 · 전부 팔기(2026-10-29): 체크한 것만 요청, 전부 버튼은 모두
with closing(db.connect()) as conn:
    conn.executemany("INSERT OR REPLACE INTO live_positions (ticker, strategy, qty, avg_px, tp_px, sl_px, cond_id, opened_at, buy_coid) VALUES (?,?,?,?,?,?,?,?,?)",
                     [("AAA", "piggy", 1, 0.5, 0.7, 0.45, "C1", "2026-10-28T16:00:00+00:00", "k1"), ("BBB", "piggy", 1, 1.0, 1.3, 0.9, "C2", "2026-10-28T16:00:00+00:00", "k2")]); conn.commit()
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
assert [b for b in at.button if b.key == "live_sell_sel"][0].disabled and not any(b.key.startswith("live_sell_AAA") for b in at.button)
at.checkbox(key="live_pick_BBB").check().run(); assert not [b for b in at.button if b.key == "live_sell_sel"][0].disabled
[b for b in at.button if b.key == "live_sell_sel"][0].click().run(); assert not at.exception
with closing(db.connect()) as conn:
    assert [tuple(r) for r in conn.execute("SELECT kind, ticker FROM live_requests WHERE id>3 ORDER BY id")] == [("sell", "BBB")]
[b for b in at.button if b.key == "live_sell_all"][0].click().run(); assert not at.exception
with closing(db.connect()) as conn:
    assert [tuple(r) for r in conn.execute("SELECT kind, ticker FROM live_requests WHERE id>3 ORDER BY id")] == [("sell", "BBB"), ("sell", "AAA"), ("sell", "BBB")]
    conn.execute("DELETE FROM live_positions"); conn.commit()
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
# 끄기
at.text_input(key="live_confirm").set_value(broker_ui.CONFIRM).run(); [b for b in at.button if b.key == "live_on2"][0].click().run()
assert config.LIVE_TRADING is True; [b for b in at.button if b.key == "live_off"][0].click().run(); assert config.LIVE_TRADING is False and config.overrides().get("LIVE_TRADING") is None
# dry-run 결과(그때 1주 샀다면, 2026-10-29 아침): 기록이 생기면 요약 4칸 + 한글 열 표
import pandas as pd
from datetime import datetime, timezone
with closing(db.connect()) as conn:
    assert broker.mirror_buy(conn, None, "piggy", "DR1", 0.5, tp_px=0.7, sl_px=0.45, now=datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc))["mode"] == "dry"
    bars = {"DR1": pd.DataFrame({"Open": [0.5, 0.55], "High": [0.6, 0.75], "Low": [0.48, 0.5], "Close": [0.55, 0.7]}, index=pd.to_datetime(["2026-11-02", "2026-11-03"]))}
    r = broker.simulate_dry(conn, bars, now=datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc), out=lambda *_: None); assert r["closed"] == 1, r
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert any("그때 1주 샀다면" in m.value for m in at.markdown) and any(m.label == "익절 비율" and m.value == "100%" for m in at.metric), [(m.label, m.value) for m in at.metric]
assert any("매수가(지정가)" in list(d.value.columns) for d in at.dataframe)
print("ALL OK")
