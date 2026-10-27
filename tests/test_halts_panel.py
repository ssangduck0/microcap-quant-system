import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, halts, closewatch as cw
db.init_db(); cw.ensure_tables()
ET = ZoneInfo("America/New_York"); now = datetime.now(ET)
HS = [
 {"symbol": "LUDA", "name": "Luld A", "market": "NASDAQ", "code": "LUDP", "title": None, "threshold": 2.5, "status": "halted", "halt": now - timedelta(minutes=2), "resume": None, "quote_resume": None},
 {"symbol": "LONG", "name": "Long", "market": "NASDAQ", "code": "LUDP", "title": None, "threshold": 1.0, "status": "halted", "halt": now - timedelta(minutes=9), "resume": None, "quote_resume": None},
 {"symbol": "NEWS", "name": "News", "market": "NYSE", "code": "T1", "title": "Halt - News Pending", "threshold": None, "status": "quote_resumed", "halt": now - timedelta(minutes=30), "resume": None, "quote_resume": now},
 {"symbol": "DONE", "name": "Done", "market": "NASDAQ", "code": "LUDP", "title": None, "threshold": 3.0, "status": "resumed", "halt": now - timedelta(minutes=60), "resume": now - timedelta(minutes=55), "quote_resume": None},
 {"symbol": "OLDY", "name": "Old", "market": "NASDAQ", "code": "T12", "title": "Additional Information Requested", "threshold": None, "status": "halted", "halt": now - timedelta(days=1), "resume": None, "quote_resume": None},
 {"symbol": "NOTIME", "name": "x", "market": "NASDAQ", "code": "T1", "title": None, "threshold": None, "status": "halted", "halt": None, "resume": None, "quote_resume": None}]
calls = {"n": 0, "fail": False}
def fake_fetch(ttl=30.0, **k):
    calls["n"] += 1
    if calls["fail"]: raise RuntimeError("both down")
    halts.last_source = "upcuit"; return HS
halts.fetch = fake_fetch
from streamlit.testing.v1 import AppTest
import streamlit as st
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
def panel(at): return [d.value for d in at.dataframe if "진행" in d.value.columns and "사유" in d.value.columns][0]
# 1) 스냅샷이 하나도 없으면 대시보드가 일찍 멈추므로, 최소 스냅샷 1개 + 체크리스트 기록 없음(장외) 상태에서 현황판이 보여야 함
nowiso = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-13", "ticker": "LUDA", "exchange": "NASDAQ", "first_seen": nowiso, "last_seen": nowiso, "price": 2.4, "high_20d": 5, "low_20d": 2,
        "drawdown_pct": -50.0, "day_change_pct": -30.0, "volume_mult": 3.0, "buy_pressure": 50.0, "float_shares": 5e6, "atr14": 0.2, "quant_score": 40.0, "quant_detail": "{}",
        "pump_score": 30.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
st.cache_data.clear()
at = AppTest.from_file(APP, default_timeout=90).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
t = panel(at); print(t[["상태", "티커", "사유", "진행", "스캐너", "체크리스트", "이월"]].to_string(index=False))
assert list(t["티커"]) == ["LUDA", "LONG", "NEWS", "DONE", "OLDY"]                                  # 최신 정지 먼저, 시각 없는 항목 제외
r = {x["티커"]: x for x in t.to_dict("records")}
assert r["LUDA"]["상태"] == "🔴 정지 중" and "예상 재개" in r["LUDA"]["진행"] and "초 남음" in r["LUDA"]["진행"]          # LULD 5분 규칙 카운트다운
assert "5분 넘음" in r["LONG"]["진행"] and r["NEWS"]["상태"] == "🟡 호가만 재개" and r["NEWS"]["사유"] == "T1 뉴스 대기"
assert r["DONE"]["상태"] == "🟢 재개" and r["DONE"]["진행"] == "" and r["DONE"]["재개(ET)"] != "" and r["OLDY"]["이월"] == "전날" and "추가 정보 요청" in r["OLDY"]["사유"]
assert r["LUDA"]["스캐너"] == "✅" and r["LONG"]["스캐너"] == "" and r["LUDA"]["체크리스트"] == ""
mt = {m.label: m.value for m in at.metric}; print({k: mt[k] for k in ("전체", "지금 정지 중", "LULD(상킷·하킷)", "스캐너 발견 종목")})
assert mt["전체"] == "5 건" and mt["지금 정지 중"] == "4 건" and mt["LULD(상킷·하킷)"] == "3 건" and mt["스캐너 발견 종목"] == "1 건"
assert any("아직 기록이 없습니다" in i.value for i in at.info)                                         # 체크리스트는 비어도 현황판은 보임
assert any("업킷 API" in c.value for c in at.caption)
# 2) 필터
at.checkbox(key="halt_active").set_value(True).run(); assert "DONE" not in list(panel(at)["티커"])
at.checkbox(key="halt_luld").set_value(True).run(); assert list(panel(at)["티커"]) == ["LUDA", "LONG"]
at.checkbox(key="halt_seen").set_value(True).run(); assert list(panel(at)["티커"]) == ["LUDA"]
for k in ("halt_active", "halt_luld", "halt_seen"): at.checkbox(key=k).set_value(False).run()
at.text_input(key="halt_q").set_value("ne").run(); assert list(panel(at)["티커"]) == ["NEWS", "DONE"]   # 부분 일치(NE 포함)
at.text_input(key="halt_q").set_value("new").run(); assert list(panel(at)["티커"]) == ["NEWS"]
at.text_input(key="halt_q").set_value("").run()
# 3) 체크리스트 종목이면 스캐너가 계산한 방향(하한/상한)이 붙음
hk = HS[0]["halt"].strftime("%m-%d %H:%M:%S")
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)", ("2026-10-13", "LUDA",
        json.dumps({"drop_pct": -30.0, "halts": [{"time": hk, "dir": "하한", "code": "LUDP"}]}), nowiso)); conn.commit()
st.cache_data.clear()
at = AppTest.from_file(APP, default_timeout=90).run(); assert not at.exception
r = {x["티커"]: x for x in panel(at).to_dict("records")}; assert r["LUDA"]["방향"] == "하한" and r["LUDA"]["체크리스트"] == "✅" and r["LONG"]["방향"] == ""
# 4) 새로고침 버튼은 다시 받아 옴
n0 = calls["n"]; [b for b in at.button if b.label == "🔄 새로고침"][0].click().run(); assert calls["n"] > n0 and not at.exception
# 5) 업킷·나스닥 모두 실패하면 경고만 보이고 나머지 화면은 정상
calls["fail"] = True; st.cache_data.clear()
at = AppTest.from_file(APP, default_timeout=90).run(); assert not at.exception
assert any("받지 못했습니다" in w.value for w in at.warning) and not [d for d in at.dataframe if "진행" in d.value.columns]
print("ALL OK")
