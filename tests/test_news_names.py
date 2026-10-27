import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db; db.init_db()
import news, themes
from datetime import datetime, timezone
assert news._norm("Amber International Holding Ltd") == "amber international"
assert news._norm("The Coca-Cola Company") == "coca cola" and news._norm("AT&T Inc.") == "at and t"
with closing(db.connect()) as conn:
    for d in themes.DDL:
        conn.execute(d)
    for t, n in [("AMBR", "Amber International Holding Ltd"), ("GLB", "Global Inc"), ("ZAPP", "Zapp"), ("NVTS", "Navitas Semiconductor Corp"),
                 ("NAVI", "Navitas Corp"), ("ABEO", "Abeona Therapeutics Inc."), ("HLTH", "Health Systems Group")]:
        conn.execute("INSERT INTO ticker_meta (ticker, name) VALUES (?,?)", (t, n))
    conn.commit()
    idx = news.name_index(conn)
assert "global" not in idx and "zapp" not in idx and "health systems" not in idx, idx   # 흔한 단어·짧은 한 단어·흔한 단어만인 이름 제외
assert idx["navitas semiconductor"][0] == "NVTS" and "abeona therapeutics" in idx
M = lambda t, s="": (news.match_name(t, s, idx) or (None,))[0]  # noqa: E731
assert M("Amber International Holding Limited Announces Results") == "AMBR"
assert M("Navitas Semiconductor Unveils New GaN Chip") == "NVTS"                # 더 긴 이름 우선(Navitas Corp 아님)
assert M("Partnership with Abeona Therapeutics expands", "") == "ABEO"          # 두 단어 이상은 중간에 있어도
assert M("Global markets rally") is None and M("Health Systems are changing") is None
assert M("New study", "Today Amber International announced a contract") == "AMBR"  # 요약 앞부분
# 한 단어 이름(7자 이상, 흔하지 않음)은 제목이 그 이름으로 시작할 때만
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO ticker_meta (ticker, name) VALUES ('ODYS','Odyssefy Inc')"); conn.commit()
    idx = news.name_index(conn)
assert news.match_name("Odyssefy Reports Q3", "", idx)[0] == "ODYS" and news.match_name("Investors cheer Odyssefy", "", idx) is None

# ingest: 표기가 있으면 표기 우선, 없으면 이름 연결 + 태그 · 이미 쌓인 글도 다시 연결
now = datetime.now(timezone.utc).isoformat()
items = [{"id": "1", "title": "Amber International Holding Limited Announces Results", "summary": "x", "published": now, "link": "l1"},
         {"id": "2", "title": "Navitas Semiconductor (NASDAQ: NVTS) wins award", "summary": "", "published": now, "link": "l2"},
         {"id": "3", "title": "Private startup raises seed", "summary": "", "published": now, "link": "l3"}]
assert news.ingest(items, "f") == 3
with closing(db.connect()) as conn:
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM news")}
assert rows["1"]["ticker"] == "AMBR" and "🔗이름 연결" in json.loads(rows["1"]["tags"])
assert rows["2"]["ticker"] == "NVTS" and "🔗이름 연결" not in json.loads(rows["2"]["tags"]) and rows["3"]["ticker"] is None
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO news (id, title, summary, published, tags) VALUES ('9','Abeona Therapeutics to Present','', ?, '[]')", (now,))
    assert news.relink(conn) == 1
    assert conn.execute("SELECT ticker FROM news WHERE id='9'").fetchone()[0] == "ABEO"
print("ALL OK")
