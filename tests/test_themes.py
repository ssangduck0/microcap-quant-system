import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
import pandas as pd
import db, themes as th
db.init_db()
assert th.assign("Medicus Pharma Ltd.", 2834) == ["바이오·제약"]
assert th.assign("Intchains Group Limited", 3674, ["The Company launched an AI chip for bitcoin mining and data center use"]) == ["반도체·전자부품", "AI", "크립토·디지털자산", "데이터센터·HPC"]
assert th.assign("Odyssey Marine Exploration", 1000) == ["광물·자원"] and th.assign("Nothing Co", None) == []
assert th.assign("X Gold Corp", 1040) == ["금·귀금속"] and th.assign("Chem Co", 2810) == ["화학·소재"]                 # 가장 좁은 업종 범위 하나만
class FC:
    def cik_for(s, t): return {"MDCX": 1, "ICG": 2}.get(t)
    def submissions(s, cik): return {1: {"name": "Medicus Pharma Ltd.", "sic": "2834", "sicDescription": "Pharmaceutical Preparations"},
                                      2: {"name": "Intchains AI Group", "sic": "3674", "sicDescription": "Semiconductors"}}[cik]
assert th.build(FC(), ["MDCX", "ICG", "NOPE"], out=lambda *_: None) == 3 and th.build(FC(), ["MDCX"], out=lambda *_: None) == 0   # 있는 종목은 건너뜀
tb = th.table().set_index("ticker"); assert tb.loc["ICG", "themes"] == ["반도체·전자부품", "AI"] and tb.loc["NOPE", "themes"] == []
th.set_manual("NOPE", ["드론"]); assert th.table().set_index("ticker").loc["NOPE", "themes"] == ["드론"]           # 직접 지정 우선
th.set_manual("NOPE", []); assert th.table().set_index("ticker").loc["NOPE", "themes"] == []
with closing(db.connect()) as conn:
    th.save_moves(conn, "2026-10-16", [("MDCX", 3.25, 25.0, 6.0, 30.0), ("ICG", 1.33, 2.0, 1.2, 5.0), ("NOPE", 1.0, 0.0, 1.0, 0.0)])
h = th.hot(th.table(), th.moves()).set_index("테마"); print(h.to_string())
assert h.loc["바이오·제약", "움직임"] == 1 and h.loc["AI", "움직임"] == 0 and h.index[0] == "바이오·제약"
assert "AI" in th.all_themes() and "퀀텀" in th.all_themes()
print("ALL OK")
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ["QUANT_TEST_PAGE"] = "themes"
import halts; halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-16", "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown); assert "바이오·제약" in html and "1종목" in html and "MDCX" in html and "오늘 +25.0%" in html
at.text_input(key="th_edit_t").set_value("ICG").run(); at.multiselect(key="th_edit_s_ICG").set_value(["AI"]); at.text_input(key="th_edit_new").set_value("짱작주")
[b for b in at.button if b.key == "th_edit_save"][0].click().run(); assert th.table().set_index("ticker").loc["ICG", "themes"] == ["AI", "짱작주"]
os.environ.pop("QUANT_TEST_PAGE"); print("UI OK")
