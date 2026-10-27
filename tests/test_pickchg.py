import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, pick30
db.init_db()
T = date.today()


def row(t, status, pct, imm, weak=False):
    return {"ticker": t, "status": status, "weak": weak, "target_name": "$1 상장유지", "pct": pct, "imm_days": imm, "pressure": 5.0, "price": 0.5}


day1 = {"pass": [row("AAA", "가능", 50, 10), row("BBB", "대기", 80, 100), row("CCC", "대기", 40, 200)]}
day2 = {"pass": [row("BBB", "유력", 70, 3), row("AAA", "가능", 45, 9), row("DDD", "대기", 60, 50)]}
with closing(db.connect()) as conn:
    assert pick30.snapshot(conn, day1, today=T - timedelta(days=1)) == 3
    assert pick30.snapshot(conn, day1, today=T - timedelta(days=1)) == 0                      # 하루 한 번(이미 있으면 그대로)
    assert pick30.snapshot(conn, day2, today=T) == 3
    ch = pick30.changes(conn)
    assert ch["dates"] == [T.isoformat(), (T - timedelta(days=1)).isoformat()]
    r = {x["ticker"]: x for x in ch["rows"]}
    assert r["BBB"]["rank"] == 1 and r["BBB"]["move"] == 1 and r["BBB"]["status_change"] == "대기 → 유력" and r["BBB"]["status_up"] is True
    assert r["AAA"]["move"] == -1 and r["AAA"]["status_change"] is None and r["AAA"]["pct_prev"] == 50
    assert r["DDD"]["new"] is True and [g["ticker"] for g in ch["gone"]] == ["CCC"]
    assert [h["rank"] for h in pick30.history(conn, "BBB")] == [1, 2]

# 화면: 📊 PICK 변동(이 화면만 따로 띄워 검사)
from streamlit.testing.v1 import AppTest
def _app():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import pick30_ui
    pick30_ui._scan = lambda: {"pass": []}
    pick30_ui.render_changes()
at = AppTest.from_function(_app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
tb = [d.value for d in at.dataframe if "변동" in d.value.columns][0]
assert list(tb["티커"])[:1] == ["BBB"] and "▲1" in list(tb["변동"]) and "🆕" in list(tb["변동"]), tb
assert any("빠진 종목" in c.value and "CCC" in c.value for c in at.caption)
print("ALL OK")
