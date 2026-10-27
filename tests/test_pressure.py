import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, halts, pressure, watch, secbackfill, rsplit
db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
now = db.utcnow_iso(); today = date.today()
with closing(db.connect()) as conn:
    for t, px, fs, dil in (("NIVF", 0.279, 3e6, "ATM"), ("MDCX", 3.25, 5e6, "CLEAN"), ("SAFE", 5.0, 100e6, "CLEAN")):
        db.upsert_snapshot(conn, {"date": today.isoformat(), "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": px, "high_20d": px * 2, "low_20d": px * 0.9,
            "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": fs, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": dil, "excluded": 0})
    secbackfill.ensure_tables(conn)
    for i, f in enumerate(("424B5", "S-1", "424B4")):
        conn.execute("INSERT INTO sec_hist VALUES (?,?,?,?,'')", (f"x{i}", "NIVF", f, (today - timedelta(days=30 * (i + 1))).isoformat()))
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('NIVF', ?, 0.25, 1.0)", ((today - timedelta(days=6)).isoformat(),)); conn.commit()
watch.add_event("NIVF", (today + timedelta(days=6)).isoformat(), "상장유지 기한", "회복 기한")
db.save_report("NIVF", {"ticker": "NIVF", "generated_at": now, "errors": {}, "runway": {"runway_months": 1.5, "cash": 0.5e6, "monthly_burn": 0.33e6, "cash_asof": "2026-06-30"},
                        "company": {"delisting_notices": [{"filed": (today - timedelta(days=100)).isoformat(), "url": "u"}]}, "financing": {"events": [], "summary": {}}, "timeline": []})
db.save_report("SAFE", {"ticker": "SAFE", "generated_at": now, "errors": {}, "runway": {"runway_months": 40.0}, "company": {}, "financing": {"events": []}, "timeline": []})
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=42)[-40:]
lo = pd.DataFrame({"Close": np.r_[np.full(30, 0.3), np.full(10, 0.279)]}, index=idx)
with closing(db.connect()) as conn:
    r = pressure.evaluate("NIVF", conn, None, lo); print(r["score"], r["parts"], r["targets"], r["warn"], r["stance"])
    assert r["parts"] == {"런웨이": 3, "$1 상장유지": 3, "baby shelf": 1, "역분할": 1, "상습 희석": 1} and r["score"] == 9 and r["stance"] == "회피" and r["atm_open"]
    assert abs(r["targets"][0][2] - (1 / 0.279 - 1) * 100) < 1e-6 and r["targets"][1][0] == "baby shelf 탈출" and abs(r["targets"][1][1] - 25.0) < 1e-9
    assert any("상습 희석" in w for w in r["warn"]) and any("D-6" in p[1] for p in r["press"] if p[0] == "상장 유지")
    m = pressure.evaluate("MDCX", conn, None, None); assert m["parts"] == {"baby shelf": 1} and not m["has_report"] and m["stance"] == "대기"
    s = pressure.evaluate("SAFE", conn, None, None); assert s["score"] == 0.0
    sc = pressure.scan(conn, {"NIVF": lo}); assert [x["ticker"] for x in sc] == ["NIVF", "MDCX"]                  # 압박 0점(SAFE)은 빠짐
os.environ["QUANT_TEST_PAGE"] = "pressure"
import watch_ui; watch_ui.prices = lambda tk: {"NIVF": lo}
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown); print(html.count('class="qk-rank"'))
assert "NIVF" in html and "압박 9" in html and "ATM·ELOC 열림" in html and "구조 회피" in html and "baby shelf 탈출" in html and "&#36;1 상장 유지" in html
at.checkbox(key="pr_atm").set_value(True).run(); assert "NIVF" not in "\n".join(m.value for m in at.markdown if 'class="qk-rank"' in m.value)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
