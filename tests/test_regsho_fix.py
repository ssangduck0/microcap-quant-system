import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, regsho as rg
db.init_db()
HTML = "<html><script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':</script>|x|y</html>"
assert rg.parse(HTML) == {}                                                                        # 봇 확인 웹페이지는 버림
assert rg.parse("Symbol|Security Name|C|F|R|\nHODO|House|S|Y|N|\n<SCRIPT>(FUNCTION(W,D)|a|b|\nFile Creation Time: x||||") == {"HODO": "House"}
with closing(db.connect()) as conn:
    rg.ensure_tables(conn)
    conn.execute("INSERT INTO regsho_files VALUES ('2026-10-20','ok',1,0)"); conn.execute("INSERT INTO regsho_list VALUES ('2026-10-20','<SCRIPT>(FUNCTION(W,D,S,L,I){W[L]=W[L]','x')")
    conn.execute("INSERT INTO regsho_files VALUES ('2026-10-19','ok',2,0)"); conn.execute("INSERT INTO regsho_list VALUES ('2026-10-19','HODO','H')"); conn.commit()
    assert rg.cleanup(conn) == 1 and rg.dates(conn) == ["2026-10-19"]                             # 잘못된 날은 다시 받도록 지움
print("ALL OK")
