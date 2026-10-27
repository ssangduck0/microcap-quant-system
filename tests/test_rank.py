import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, halts, accum, regsho, watch, rank
db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
today = date.today(); now = db.utcnow_iso()
def A(score, strong, level): return json.dumps({"score": score, "level": level, "n_absorb": 3, "n_strong": strong, "top_day": "10/16", "top_vr": 9.0, "top_chg": 12.0, "news": [], "dilution": [],
                                                 "absorb_days": ["10/15", "10/16"], "price": 1.0, "parts": {}, "r30": 10, "cum": 10}, ensure_ascii=False)
with closing(db.connect()) as conn:
    conn.execute(accum.DDL)
    conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (today.isoformat(), "BNAI", "일간", 7.0, A(7.0, 1, "강한 매집 의심")))
    conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (today.isoformat(), "BNAI", "주간", 8.0, A(8.0, 1, "강한 매집 의심")))
    conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (today.isoformat(), "BRNX", "주간", 8.0, A(8.0, 0, "매집 의심")))
    for t, dil in (("BNAI", "CLEAN"), ("BRNX", "ATM")):
        db.upsert_snapshot(conn, {"date": today.isoformat(), "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
            "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": dil, "excluded": 0})
    regsho.ensure_tables(conn)
    for i in range(11):
        d = (today - timedelta(days=i)).isoformat()
        conn.execute("INSERT INTO regsho_files VALUES (?,'ok',1,0)", (d,)); conn.execute("INSERT INTO regsho_list VALUES (?,'BNAI','B')", (d,))
    conn.commit()
watch.add_event("BNAI", (today + timedelta(days=2)).isoformat(), "주총", "특별 주총")
df = rank.compute().set_index("ticker"); print(df[["rank", "score", "strength", "when", "when_why", "risk"]].to_string())
assert df.loc["BNAI", "rank"] < df.loc["BRNX", "rank"] and df.loc["BNAI", "when"] == "⏱ 3일 이내" and df.loc["BRNX", "when"] == "⏱ 수주"
assert any("13일 강제 상환까지 2일" in x for x in df.loc["BNAI", "when_why"]) and any("D-2 주총" in x for x in df.loc["BNAI", "when_why"]) and "ATM·ELOC 열림" in df.loc["BRNX", "risk"]
os.environ["QUANT_TEST_PAGE"] = "rank"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
at.slider(key="rk_min").set_value(0).run()
cards = [m.value for m in at.markdown if 'class="qk-rank"' in m.value]; assert "BNAI" in cards[0] and "⏱ 3일 이내" in cards[0] and "BRNX" in cards[1]
at.radio(key="rk_when").set_value("⏱ 3일 이내").run(); assert len([m for m in at.markdown if 'class="qk-rank"' in m.value]) == 1
os.environ["QUANT_TEST_PAGE"] = "accum"
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
at.radio(key="ac_per").set_value("주간").run(); at.radio(key="ac_sort").set_value("종합 순위순").run()
cards = [m.value for m in at.markdown if 'class="qk-tk"' in m.value]; assert "BNAI" in cards[0] and "🏁 종합 1위" in cards[0]
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
