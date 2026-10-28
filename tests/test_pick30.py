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
for t, px, hi, dil in (("PASS", 0.6, 0.8, "CLEAN"), ("ATMX", 0.6, 0.8, "ATM"), ("FAR", 0.3, 0.35, "CLEAN"), ("NOSPL", 0.6, 0.8, "CLEAN"), ("HIT", 0.6, 1.2, "CLEAN"), ("DIL6", 0.6, 0.8, "CLEAN")):
    snap(t, px, hi, dil)
with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('PASS', ?, 0.1, 1.0)", ((T - timedelta(days=100)).isoformat(),)); conn.execute("INSERT INTO rs_events VALUES ('DIL6', ?, 0.1, 1.0)", ((T - timedelta(days=100)).isoformat(),)); conn.execute("INSERT INTO rs_events VALUES ('HIT', ?, 0.1, 1.0)", ((T - timedelta(days=100)).isoformat(),))
    conn.execute(accum.DDL); conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (T.isoformat(), "NEWX", "주간", 6.0, "{}")); conn.commit()
watch.add_event("PASS", (T + timedelta(days=10)).isoformat(), "상장유지 기한", "$1 회복 기한")
watch.add_event("PASS", (T + timedelta(days=3)).isoformat(), "주총", "특별 주총")                       # 주총은 상승 요인 아님 → 임박에서 제외
real_cand, real_eval = pressure.candidates, pressure.evaluate
pressure.candidates = lambda conn: ["PASS", "ATMX", "FAR", "NOSPL", "HIT", "DIL6"]
import shares as _sh6
with closing(db.connect()) as conn:   # 🔬 ⑥(2026-10-28): DIL6 는 PASS 와 같은데 직전 분기 주식수 +50% → '하방 희석 없음' 탈락
    conn.execute(_sh6.HIST_DDL)
    # 두 표지 모두 1:10 병합(T-100) 뒤로 두어 분할 반영이 끼지 않게(T-95 → T-5, 간격 90일)
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", [("DIL6", (T - timedelta(days=95)).isoformat(), "f", "10-Q", 1_000_000), ("DIL6", (T - timedelta(days=5)).isoformat(), "f", "10-Q", 1_500_000),
                                                                             ("PASS", (T - timedelta(days=95)).isoformat(), "f", "10-Q", 1_000_000), ("PASS", (T - timedelta(days=5)).isoformat(), "f", "10-Q", 1_150_000)])
    conn.commit()
def fake_eval(t, conn, a, b):
    r = real_eval(t, conn, a, b); r["score"] = 6.0; return r
pressure.evaluate = fake_eval
with closing(db.connect()) as conn:   # ⚠️ 10~20% 는 통과하되 이유에 표시 · ❌ 는 share_chg 에 값
    e6 = pick30.evaluate("PASS", conn, fake_eval("PASS", conn, None, None), None); assert e6["fail"] is None and e6["share_cls"] == "warn" and "⚠️ 주식수 +15%(분기)" in e6["why"], e6
    d6 = pick30.evaluate("DIL6", conn, fake_eval("DIL6", conn, None, None), None); assert d6["fail"] == "하방 희석 없음" and d6["share_cls"] == "bad" and d6["share_chg"].startswith("+50% ("), d6
    conn.execute("DELETE FROM shares_hist WHERE ticker='PASS'"); conn.commit()   # 아래 화면 검사는 PASS 를 평범하게
s = pick30.scan()
fails = {r["ticker"]: r["fail"] for r in s["fail"]}; print(fails, [(r["ticker"], r["status"], r["imm_days"], r["imm_kind"]) for r in s["pass"]], s["funnel"])
assert [r["ticker"] for r in s["pass"]] == ["PASS"] and s["pass"][0]["status"] == "유력" and s["pass"][0]["imm_days"] == 10 and s["pass"][0]["target_name"] == "$1 상장 유지"
assert fails == {"ATMX": "하방 희석 없음", "FAR": "목표가 도달 범위 안", "NOSPL": "다른 해결 방법 없음", "HIT": "목표가 최근 미도달", "DIL6": "하방 희석 없음"}
assert s["registered"] == 6 and s["funnel"]["하방 희석 없음"] == 2 and s["funnel"]["목표가 있음"] == 0 and list(s["funnel"])[0] == "목표가 있음" and s["unregistered"] == ["NEWX"]
rows = [{"ticker": "A", "status": "대기", "imm_days": 5, "pressure": 3}, {"ticker": "B", "status": "유력", "imm_days": 20, "pressure": 9}, {"ticker": "C", "status": "가능", "imm_days": None, "pressure": 5}]
assert [r["ticker"] for r in pick30.sort(rows, "유력·임박 순")] == ["B", "C", "A"] and [r["ticker"] for r in pick30.sort(rows, "임박 순")] == ["A", "B", "C"] and [r["ticker"] for r in pick30.sort(rows, "압박 순")] == ["B", "C", "A"]
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "pick"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "하방 희석 없음 −2" in html and "등록 6 → <b>1종목 통과</b>" in html and "qk-pick-grid" in html and '<div class="l1">' in html and "PASS" in html and "유력" in html
at.toggle(key="pk_txt").set_value(True).run(); assert any("1. PASS 유력 +67%" in c.value and "$1 상장 유지" in c.value for c in at.code)
assert any("탈락 조건" in d.value.columns for d in at.dataframe)
_ft = [d.value for d in at.dataframe if "탈락 조건" in d.value.columns][0]; assert "주식수(분기)" in _ft.columns and _ft.set_index("티커").loc["DIL6", "주식수(분기)"].startswith("+50%")
labels = {l.label for l in at.get("page_link")}; assert {"선별", "종목", "관리", "오늘"} <= labels                    # 📱 아래 고정 메뉴
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
