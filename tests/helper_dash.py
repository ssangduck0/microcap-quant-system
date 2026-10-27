import os, sys, json
DB = sys.argv[1]
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"] = DB
sys.path.insert(0, "/mnt/user-data/outputs/quant_system")
from contextlib import closing
import db
with closing(db.connect()) as conn:
    ev = [{"accession":"0001-01","form":"424B5","filed":"2026-09-12","url":"https://www.sec.gov/x","tags":["ATM","WARRANT"]}]
    fl = {"ATM":True,"ELOC":False,"CB":False,"WARRANT":True,"SHELF_S3":True,"PARTIAL_CHECK":False}
    db.save_dilution(conn, {"ticker":"AAA","cik":1,"status":"ATM","flags":fl,"evidence":ev})
    conn.execute("UPDATE daily_snapshots SET dilution_status='ATM', excluded=1, pump_score=0 WHERE ticker='AAA'")
    conn.execute("UPDATE daily_snapshots SET dilution_status='UNKNOWN' WHERE ticker='CCC'")
    db.save_dilution(conn, {"ticker":"CCC","cik":None,"status":"UNKNOWN","flags":{},"evidence":[],"error":"CIK 없음"})
    db.save_filing(conn, "AAA", 1, {"accession":"0001-01","form":"424B5","filed":"2026-09-12","items":"","url":"https://www.sec.gov/x"}, ["ATM","WARRANT"])
    conn.commit()
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("/mnt/user-data/outputs/quant_system/dashboard.py", default_timeout=60).run()
print("exceptions:", [e.value for e in at.exception])
print("tabs:", [t.label for t in at.tabs])
print("metrics:", [(m.label, m.value) for m in at.metric][:6])
print("dataframes:", len(at.dataframe))
# 전체 기간으로 바꿔서 다시 (데이터가 과거 날짜로 옮겨졌으므로)
at.sidebar.selectbox[0].set_value("전체").run()
print("exceptions:", [e.value for e in at.exception], "dataframes:", len(at.dataframe))
at.selectbox[1].set_value("AAA").run() if len(at.selectbox) > 1 else None
print("exceptions:", [e.value for e in at.exception])
print([m.value for m in at.error][:2], [m.value for m in at.warning][:2])
