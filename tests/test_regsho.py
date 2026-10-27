import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, regsho as rg
db.init_db()
F = "Symbol|Security Name|Market Category|Reg SHO Threshold Flag|Rule 3210|Filler\nHODO|House of Doge Inc. Common Stock|S|Y|N|\nAAA|A Corp|S|Y|N|\nFile Creation Time: 1015202620:01|||||\n"
assert rg.parse(F) == {"HODO": "House of Doge Inc. Common Stock", "AAA": "A Corp"}
now = datetime(2026, 10, 15, 21, 0, tzinfo=ZoneInfo("America/New_York"))       # 목요일 21시 → 오늘 파일 포함
days = {"20261015": "HODO|H|S|Y|N|\nAAA|A|S|Y|N|", "20261014": "HODO|H|S|Y|N|", "20261013": "HODO|H|S|Y|N|\nAAA|A|S|Y|N|", "20261012": "", "20261009": "HODO|H|S|Y|N|"}
calls = []
def get(u):
    calls.append(u); k = u.rsplit("th", 1)[1][:8]
    return (200, "Symbol|Security Name|x|y|z|\n" + days[k] + "\nFile Creation Time: x||||") if days.get(k) else (404, "")
with closing(db.connect()) as conn:
    got = rg.refresh(conn, http_get=get, now=now.astimezone(timezone.utc), days=5); assert got == 4 and len(calls) == 5
    st = rg.streaks(conn); print(st)
    assert st == {"HODO": 4, "AAA": 1}                                          # 휴장(10/12 없음)은 건너뛰고 연속: HODO 15·14·13·09, AAA 15만(14일 빠짐)
    n = len(calls); rg.refresh(conn, http_get=get, now=now.astimezone(timezone.utc), days=5); assert len(calls) == n   # 받은 날·1시간 안의 미게시는 다시 안 받음
    assert rg.latest_date(conn) == "2026-10-15" and rg.label(4) == "📛 4일째" and rg.label(None) == ""
assert rg.candidates(datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")), 1)[0].isoformat() == "2026-10-14"   # 20시 전엔 오늘 파일 없음
print("ALL OK")
