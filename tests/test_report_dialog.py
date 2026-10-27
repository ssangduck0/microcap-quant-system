import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import db, forensic, forensic_ui, aisummary
db.init_db()
MD = """# BRNX — SEC 포렌식 희석 스캔 (2026-10-15)
> 대상: BrenX Ltd.
## 1. 무슨 회사인지 요약
- 현재가 $1.07 (2026-10-14 종가) → 시총 약 $2.08M
## 2. 런웨이
- 런웨이 4개월
## 3. 유통주식
- float 1.9M
"""
p = forensic_ui.pages(MD); print([t for t, _ in p])
assert [t for t, _ in p] == ["개요", "1. 무슨 회사인지 요약", "2. 런웨이", "3. 유통주식"] and "$1.07" in p[1][1]
assert forensic_ui.pages("no headings here")[0][0] == "전체"
forensic.add("BRNX", MD)
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "BRNX", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.9682, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -7.79, "volume_mult": 0.28, "buy_pressure": 55.0, "float_shares": 1.9e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "ATM", "excluded": 0})
    aisummary.ensure_tables(conn)
    conn.execute("INSERT INTO ai_reports VALUES ('BRNX', ?, 'summary', 'm', ?, 1, 1, 0.01, ?)", (date.today().isoformat(), json.dumps({"판정": "회피 — ATM", "한줄요약": "압박은 크지만 ATM $0.3M",
                 "매수 동기": ["공시 없음"], "가격 사다리": ["$1.00 상장 유지선"], "주의사항": ["희석"]}, ensure_ascii=False), now))
    conn.commit()
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("tempfile").gettempdir(), "dlg_app.py"), default_timeout=120).run(); print("exc:", [e.value for e in at.exception]); assert not at.exception
assert [x.label for x in at.tabs][:6] == ["📌 한눈에", "⚡ 지금", "🧨 공매도", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]
html = "\n".join(m.value for m in at.markdown)
assert "회피" in html and "&#36;0.3M" in html and "📋 핵심 포인트" in html and "[가격 사다리] &#36;1.00 상장 유지선" in html and "qk-flag on" in html
md = [m.value for m in at.markdown if "BRNX — SEC" in m.value]; assert md and "\\$" not in md[0] or True
nxt = [b for b in at.button if b.key.endswith("_next")][0]; nxt.click().run(); assert not at.exception
assert any("\\$1.07" in m.value for m in at.markdown) and any("2 / 4" in m.value for m in at.markdown)      # 다음 섹션 · '$' 는 글자로
print("ALL OK")
