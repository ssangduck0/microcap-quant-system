import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""토스 데이터 정책 A안(2026-10-30): 방문객 화면의 당일 현재가(토스 1분봉) → 전일 종가(야후 일봉 확정 봉). guestpx 도우미 · 종목 헤더(glance) · PICK 격자."""
import os, sys, tempfile
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import db, guestpx
db.init_db()
ET = ZoneInfo("America/New_York")
et_now = datetime.now(ET)
days = [(et_now - timedelta(days=k)).strftime("%Y-%m-%d") for k in (3, 2, 1, 0)]   # 3일 전 … 오늘(ET)
with closing(db.connect()) as conn:
    conn.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)",
                     [("AAA", d, c, c * 1.1, c * 0.9, c, 1000.0) for d, c in zip(days, (1.0, 1.1, 1.2, 1.3))] + [("BBB", days[-2], 2.0, 2.2, 1.8, 2.0, 500.0)])
    db.upsert_snapshot(conn, {"date": days[-1], "ticker": "AAA", "exchange": "NASDAQ", "first_seen": db.utcnow_iso(), "last_seen": db.utcnow_iso(), "price": 9.9, "high_20d": 2.0, "low_20d": 0.9,
                              "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
                              "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()

# 1) prev_close: 장중(10:00 ET)엔 오늘 봉 제외 → 어제 종가 1.2 · 등락 = 1.2/1.1 ; 마감 뒤(17:00)엔 오늘 봉 1.3 · 봉 1개면 등락 None · 없는 종목은 빠짐
live = guestpx.prev_close(["AAA", "BBB", "NOPE"], now=et_now.replace(hour=10, minute=0))
assert live["AAA"]["close"] == 1.2 and live["AAA"]["date"] == days[-2] and abs(live["AAA"]["chg"] - (1.2 / 1.1 - 1) * 100) < 1e-9, live
assert live["BBB"]["close"] == 2.0 and live["BBB"]["chg"] is None and "NOPE" not in live
done = guestpx.prev_close(["AAA"], now=et_now.replace(hour=17, minute=0))
assert done["AAA"]["close"] == 1.3 and done["AAA"]["date"] == days[-1] and abs(done["AAA"]["chg"] - (1.3 / 1.2 - 1) * 100) < 1e-9, done
assert guestpx.prev_close([]) == {} and guestpx.one("nope") is None
cur = guestpx.one("AAA")   # 지금 시각 기준(캐시) — 둘 중 하나
assert cur and cur["close"] in (1.2, 1.3) and guestpx.one("aaa") == cur
guestpx.clear()

# 2) 종목 헤더: 방문객이면 price = 전일 종가(스냅샷 9.9 아님) · 라벨 '전일 종가' · 주인은 스냅샷 그대로
import glance
g_guest, g_owner = glance.build("AAA", guest=True), glance.build("AAA", guest=False)
assert g_guest["price"] == cur["close"] and g_guest["price_label"] == "전일 종가", (g_guest["price"], g_guest["price_label"])
assert g_owner["price"] == 9.9 and g_owner["price_label"] == "현재가"
import company
c_guest = company.build("AAA")   # 화면 밖(방문객 아님) → 현재가
assert any(x["label"] == "★ 현재가" for x in c_guest["ladder"])
lad = company.ladder("AAA", 1.2, None, [], None, now_label="★ 전일 종가")
assert lad[0]["label"] == "★ 전일 종가" and lad[0]["kind"] == "now"

# 3) PICK 격자: 방문객이면 목표 대비 % 를 전일 종가로 다시 계산 · 주인은 받은 pct 그대로 · 자료 없으면 '-'
from streamlit.testing.v1 import AppTest


def _app(guest, rows):
    import os, sys
    sys.path.insert(0, os.environ["QS_ROOT"])
    import streamlit as st
    if guest:
        st.session_state["_guest"] = {"token": "t", "name": "손님", "left_min": 60}
    import pick30_ui
    st.markdown(pick30_ui.grid(rows), unsafe_allow_html=True)


rows = [{"ticker": "AAA", "status": "유력", "weak": 0, "pct": 999.0, "imm_days": None, "target": 2.4, "target_name": "x", "price": 9.9},
        {"ticker": "NOPE", "status": "대기", "weak": 0, "pct": 50.0, "imm_days": 10, "target": 3.0, "target_name": "y", "price": 2.0}]
o = AppTest.from_function(_app, kwargs={"guest": False, "rows": rows}, default_timeout=60).run()
assert not o.exception and any("+999%" in m.value and "+50%" in m.value for m in o.markdown), [m.value[:200] for m in o.markdown]
g = AppTest.from_function(_app, kwargs={"guest": True, "rows": rows}, default_timeout=60).run()
assert not g.exception, [e.value for e in g.exception]
exp = f"+{(2.4 / cur['close'] - 1) * 100:.0f}%"
html = " ".join(m.value for m in g.markdown)
assert exp in html and "+999%" not in html and "+50%" not in html and " · -" in html, (exp, html[:400])
print("ALL OK")
