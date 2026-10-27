import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import pandas as pd
import db, halts, watch, pick30, pressure, fundscan, rsplit, accum
db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
T = date.today(); now = db.utcnow_iso()
def snap(t, px, hi, dil="CLEAN"):
    with closing(db.connect()) as conn:
        db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": px, "high_20d": hi, "low_20d": px * .9,
            "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 50e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": dil, "excluded": 0})
for t, px, hi, dil in (("PASS", 0.6, 0.8, "CLEAN"), ("ATMX", 0.6, 0.8, "ATM"), ("FAR", 0.3, 0.35, "CLEAN"), ("NOSPL", 0.6, 0.8, "CLEAN"), ("HIT", 0.6, 1.2, "CLEAN")):
    snap(t, px, hi, dil)
with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('PASS', ?, 0.1, 1.0)", ((T - timedelta(days=100)).isoformat(),)); conn.execute("INSERT INTO rs_events VALUES ('HIT', ?, 0.1, 1.0)", ((T - timedelta(days=100)).isoformat(),))
    conn.execute(accum.DDL); conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (T.isoformat(), "NEWX", "주간", 6.0, "{}")); conn.commit()
watch.add_event("PASS", (T + timedelta(days=10)).isoformat(), "상장유지 기한", "$1 회복 기한")
watch.add_event("PASS", (T + timedelta(days=3)).isoformat(), "주총", "특별 주총")                       # 주총은 상승 요인 아님 → 임박에서 제외
real_cand, real_eval = pressure.candidates, pressure.evaluate
pressure.candidates = lambda conn: ["PASS", "ATMX", "FAR", "NOSPL", "HIT"]
def fake_eval(t, conn, a, b):
    r = real_eval(t, conn, a, b); r["score"] = 6.0; return r
pressure.evaluate = fake_eval
s = pick30.scan()
fails = {r["ticker"]: r["fail"] for r in s["fail"]}; print(fails, [(r["ticker"], r["status"], r["imm_days"], r["imm_kind"]) for r in s["pass"]], s["funnel"])
assert [r["ticker"] for r in s["pass"]] == ["PASS"] and s["pass"][0]["status"] == "유력" and s["pass"][0]["imm_days"] == 10 and s["pass"][0]["target_name"] == "$1 상장 유지"
assert fails == {"ATMX": "하방 희석 없음", "FAR": "목표가 도달 범위 안", "NOSPL": "다른 해결 방법 없음", "HIT": "목표가 최근 미도달"}
assert s["registered"] == 5 and s["funnel"]["하방 희석 없음"] == 1 and s["funnel"]["목표가 있음"] == 0 and list(s["funnel"])[0] == "목표가 있음" and s["unregistered"] == ["NEWX"]
rows = [{"ticker": "A", "status": "대기", "imm_days": 5, "pressure": 3}, {"ticker": "B", "status": "유력", "imm_days": 20, "pressure": 9}, {"ticker": "C", "status": "가능", "imm_days": None, "pressure": 5}]
assert [r["ticker"] for r in pick30.sort(rows, "유력·임박 순")] == ["B", "C", "A"] and [r["ticker"] for r in pick30.sort(rows, "임박 순")] == ["A", "B", "C"] and [r["ticker"] for r in pick30.sort(rows, "압박 순")] == ["B", "C", "A"]
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "pick"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "하방 희석 없음 −1" in html and "등록 5 → <b>1종목 통과</b>" in html and "qk-pick-grid" in html and '<div class="l1">' in html and "PASS" in html and "유력" in html
at.toggle(key="pk_txt").set_value(True).run(); assert any("1. PASS 유력 +67%" in c.value and "$1 상장 유지" in c.value for c in at.code)
assert any("탈락 조건" in d.value.columns for d in at.dataframe)
labels = {l.label for l in at.get("page_link")}; assert {"선별", "종목", "관리", "오늘"} <= labels                    # 📱 아래 고정 메뉴
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
