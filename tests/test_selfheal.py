import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db
db.init_db()
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date":"2026-10-08","ticker":"AAA","exchange":"NASDAQ","first_seen":now,"last_seen":now,"price":1.0,"high_20d":2.0,"low_20d":0.9,
        "drawdown_pct":-40.0,"day_change_pct":-15.0,"volume_mult":3.0,"buy_pressure":55.0,"float_shares":8e6,"atr14":0.1,"quant_score":50.0,"quant_detail":"{}",
        "pump_score":40.0,"pump_detail":'{"checks":[]}',"dilution_status":"CLEAN","excluded":0})
    conn.execute("DROP TABLE tracked_outcomes"); conn.commit()
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='tracked_outcomes'").fetchone()
db.init_db = lambda: None          # 이전 버전 db.py 처럼 새 테이블을 만들어 주지 않는 상황을 흉내
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=90).run()
print("exc:", [e.value[:80] for e in at.exception])
assert not at.exception
with closing(db.connect()) as conn:
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='tracked_outcomes'").fetchone()      # 스스로 생성됨
print("info:", [i.value[:50] for i in at.info if "결과가 아직" in i.value])
import tracker
with closing(db.connect()) as conn:
    conn.execute("DROP TABLE tracked_outcomes"); conn.commit()
    lines=[]; tracker.status(conn, out=lines.append); print(lines)       # status 도 테이블이 없어도 동작
print("ALL OK")
