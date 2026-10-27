import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ["QUANT_TEST_PAGE"] = "alerts"
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from datetime import date, datetime, timezone
import db, halts, secfeed, watch, forensic, regsho, rsplit
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso(); today = date.today().isoformat(); upd = datetime.now(timezone.utc).isoformat()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": today, "ticker": "OMEX", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    secfeed.ensure_tables(conn)
    rows = [("a1", "OMEX", "8-K", "Odyssey Marine", "5.03,8.01", ["정관 변경", "주식 병합"], -2, "악재"), ("a2", "EARN", "8-K", "Ellington Credit", "8.01", ["자사주매입"], 2, "호재"),
            ("a3", "SCNI", "424B5", "Scinai", "", ["희석 위험"], -2, "악재"), ("a4", "SCNI", "8-K", "Scinai", "3.02", ["희석 위험"], -2, "악재"), ("a5", "SCNI", "6-K", "Scinai", "", [], 0, "중립")]
    for acc, t, fm, co, it, tags, sc, se in rows:
        conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                     (acc, t, 1, fm, co, today, upd, it, f"https://sec.gov/{acc}", json.dumps(tags, ensure_ascii=False), sc, se, now))
    regsho.ensure_tables(conn); conn.execute("INSERT INTO regsho_files VALUES (?,'ok',1,0)", (today,)); conn.execute("INSERT INTO regsho_list VALUES (?,'SCNI','S')", (today,))
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('OMEX', ?, 0.04, 1.0)", (today,)); conn.commit()
watch.add("OMEX", "관심")
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
cards = [m.value for m in at.markdown if 'class="qk-tk"' in m.value]; print(len(cards))
assert len(cards) == 5 and any("공시 알림 <b" in m.value and ">5</b>건" in m.value for m in at.markdown)
om = [c for c in cards if "OMEX" in c][0]; assert "악재" in om and "주식 병합" in om and "90일 이내 병합" in om and "관심" in om and "정관 변경(병합·수권 등)" in om
sc = [c for c in cards if "SCNI" in c]; assert all("⚠ 반복 공시" in c and "Reg SHO 1일째" in c for c in sc)
at.radio(key="al_f").set_value("호재").run(); assert [ "EARN" in m.value for m in at.markdown if 'class="qk-tk"' in m.value] == [True]
at.radio(key="al_f").set_value("희석 위험").run(); assert len([m for m in at.markdown if 'class="qk-tk"' in m.value]) == 2
at.radio(key="al_f").set_value("전체").run(); at.text_input(key="al_q").set_value("#병합").run(); assert len([m for m in at.markdown if 'class="qk-tk"' in m.value]) == 1
at.text_input(key="al_q").set_value("#관심").run(); assert len([m for m in at.markdown if 'class="qk-tk"' in m.value]) == 1
at.text_input(key="al_q").set_value("scinai").run(); assert len([m for m in at.markdown if 'class="qk-tk"' in m.value]) == 3
[b for b in at.button if b.key == "al_q_a3"][0].click().run(); assert "SCNI" in forensic.queue_list()
[b for b in at.button if b.key == "al_rep_a3"][0].click().run(); assert not at.exception, [e.value for e in at.exception]          # 리포트 팝업 열기
os.environ.pop("QUANT_TEST_PAGE")
print("ALL OK")
