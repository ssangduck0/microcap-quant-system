import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, tosslink as tl, watch, piggy, halts
db.init_db(); halts.fetch = lambda *a, **k: []
assert tl.extract_code({"symbol": "RUBI", "productCode": "us20220803004"}) == "US20220803004"
assert tl.extract_code({"symbol": "XXII", "weirdField": "NAS0240124005", "name": "22nd Century"}) == "NAS0240124005"   # 필드 이름이 달라도 값 모양으로
assert tl.extract_code({"symbol": "AAA", "isin": "US0378331005", "name": "x"}) is None and tl.extract_code({"isin": "US0378331005", "c": "US20100311002"}) == "US20100311002"   # ISIN(12자리)은 코드로 착각하지 않음
assert tl.from_url("https://tossinvest.com/stocks/US20100311002/order?x=1") == "US20100311002" and tl.from_url("https://example.com") is None
assert tl.url("abcd", {}) == "https://tossinvest.com/stocks/ABCD/order"
class TC:
    def __init__(s): s.calls = []
    def stocks(s, syms): s.calls.append(list(syms)); return [{"symbol": x, "stockCode": "US2022080300" + str(i)} for i, x in enumerate(syms) if x != "NONE"]
tc = TC(); assert tl.refresh(tc, ["RUBI", "XXII", "NONE", "RUBI"]) == 2 and tc.calls == [["RUBI", "XXII", "NONE"]]
assert tl.refresh(tc, ["RUBI", "XXII"]) == 0 and len(tc.calls) == 1                                                   # 이미 있는 종목은 다시 묻지 않음
assert tl.url("rubi") == "https://tossinvest.com/stocks/US20220803000/order"
print("module OK")
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    for t in ("RUBI", "HODO"):
        db.upsert_snapshot(conn, {"date": "2026-10-14", "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.3, "high_20d": 0.6, "low_20d": 0.25,
            "drawdown_pct": -40.0, "day_change_pct": -25.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
watch.add("RUBI", "관심"); piggy.add("HODO", "기타")
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
tables = [d.value for d in at.dataframe if "토스" in d.value.columns]
snap = [x for x in tables if "퀀트점수" in x.columns][0].set_index("티커")
assert snap.loc["RUBI", "토스"] == "https://tossinvest.com/stocks/US20220803000/order" and snap.loc["HODO", "토스"] == "https://tossinvest.com/stocks/HODO/order"
assert any("출회 가능(M주)" in x.columns for x in tables) and any("박스 위치(%)" in x.columns for x in tables)    # 워치리스트·저금통에도
lb = [b for b in at.get("link_button") if b.label == "📲 토스증권에서 열기"]; assert len(lb) >= 3                     # 📊·⭐·🐷 상세
# 코드 모르는 종목: 주소 붙여넣기로 저장
at.session_state["snap_table_pick"] = "HODO"; at.run()
at.text_input(key="snap_tossurl_HODO").set_value("https://tossinvest.com/stocks/NAS0231005001/order").run(); assert not at.exception
assert tl.codes()["HODO"] == "NAS0231005001"
print("ALL OK")
