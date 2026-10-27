import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from datetime import datetime, timedelta, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db
db.init_db()
import scanner
src = open(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), encoding="utf-8").read()
ns = {}
code = src[src.index("def scanner_status("):src.index("SCANNER_OK, SCANNER_NOTE")]
exec("import json\nfrom datetime import datetime, timedelta, timezone\nfrom zoneinfo import ZoneInfo\n" + code, ns)
st_ = ns["scanner_status"]
now = datetime(2026, 10, 26, 0, 20, tzinfo=timezone.utc)
b = lambda phase, ago, nxt=None: json.dumps({"at": (now - timedelta(minutes=ago)).isoformat(), "phase": phase, "next": None if nxt is None else (now + timedelta(minutes=nxt)).isoformat()})
assert st_(3, None, now) == (True, "")                                   # 결과 저장이 10분 안
assert st_(18, b("정밀 분석 중", 8), now) == (True, "정밀 분석 중 · 8분째")    # 회차가 길어도 일하는 중이면 동작 중
assert st_(60, b("쉬는 중", 20, nxt=30), now)[0] and "다음" in st_(60, b("쉬는 중", 20, nxt=30), now)[1]
assert st_(90, b("쉬는 중", 80, nxt=-30), now) == (False, "")           # 다음 회차 시각이 한참 지났으면 멈춤
assert st_(90, b("일봉 받는 중", 60), now) == (False, "")                 # 45분 넘게 같은 단계면 멈춤
assert st_(30, None, now) == (False, "")
# 스캐너가 실제로 신호를 남김
scanner.beat("일봉 받는 중")
m = json.loads(db.get_meta("scanner_beat")["value"]); assert m["phase"] == "일봉 받는 중" and m["next"] is None
scanner.beat("쉬는 중", next_in=600)
m = json.loads(db.get_meta("scanner_beat")["value"]); assert m["phase"] == "쉬는 중" and m["next"] > m["at"]
print("ALL OK")
