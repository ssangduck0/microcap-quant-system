import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, datetime, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, regsho, shortflow, forensic, watch
db.init_db()
now = db.utcnow_iso(); today = date.today().isoformat()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": today, "ticker": "BLNK", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "ATM", "excluded": 0})
    regsho.ensure_tables(conn)
    for d in ("2026-10-10", "2026-10-13", "2026-10-14", "2026-10-15", today):
        conn.execute("INSERT OR IGNORE INTO regsho_files VALUES (?,'ok',1,0)", (d,)); conn.execute("INSERT OR IGNORE INTO regsho_list VALUES (?,'BLNK','B')", (d,))
    shortflow.record(conn, "BLNK", today, shortflow.STAGES[2], 1.0); conn.commit()
db.save_report("BLNK", {"ticker": "BLNK", "generated_at": now, "errors": {}, "runway": {"runway_months": 60.3, "cash": 34e6, "monthly_burn": 0.56e6, "cash_asof": "2026-06-30"},
                        "financing": {"events": [{"date": today}, {"date": "2020-01-01"}], "summary": {}}, "company": {}, "timeline": []})
r = {"accession": "x1", "ticker": "BLNK", "company": "Blink Charging Co.", "form": "8-K", "items": "8.01,9.01", "tags": ["파트너십·계약", "자사주매입"], "score": 3, "sentiment": "호재",
     "url": "https://sec.gov/x", "updated": datetime.now(timezone.utc).isoformat(), "lead": "On October 16, 2026, Blink Charging announced a distribution.", "repeat": False}
json.dump(r, open(__import__("os").path.join(__import__("tempfile").gettempdir(), "rep_r.json"), "w"))
import alerts_ui
p = alerts_ui.report_parts(r); print({k: v for k, v in p.items() if k != "fin"}); print(p["fin"])
assert p["flags"][0] == ("ATM", True) and p["flags"][2][1] is False and p["fin"][2] == ("런웨이", "60.3개월") and p["fin"][3] == ("최근 1년 자금조달", "1회")
assert any("Reg SHO 5일째" in x for x in p["up"]) and any("멀티 시그널" in x for x in p["up"]) and any("유통 주식 8.0백만" in x for x in p["up"]) and any("런웨이 60개월" in x for x in p["up"])
assert any("희석 정황 ATM" in x for x in p["risk"]) and 0 <= p["strength"] <= 100 and p["key"][0].startswith("8-K 기타 중요 사항")
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("tempfile").gettempdir(), "rep_app.py"), default_timeout=120).run(); print("exc:", [e.value for e in at.exception]); assert not at.exception
html = "\n".join(m.value for m in at.markdown)
assert "qk-verdict" in html and "호재" in html and "qk-flag on" in html and "60.3개월" in html and "> On October 16, 2026" in html and "📋 핵심 포인트" in html
forensic.add("BLNK", "## BLNK 덕구 요약\n한글 보고서 본문")                               # 덕구 저장본이 있으면 그걸 먼저
at = AppTest.from_file(__import__("os").path.join(__import__("tempfile").gettempdir(), "rep_app.py"), default_timeout=120).run(); assert "BLNK 덕구 요약" in "\n".join(m.value for m in at.markdown)
[b for b in at.button if b.key == "rep_q_x1"][0].click().run(); assert "BLNK" in forensic.queue_list()
print("ALL OK")
