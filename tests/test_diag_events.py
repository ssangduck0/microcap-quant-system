import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, io, contextlib, json, random
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db; db.init_db()
import eventlab, papertrade, diag_events
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    diag_events.main()
assert "아직 라벨된 사건이 없어" in buf.getvalue(), buf.getvalue()          # 빈 DB 에서도 끝까지
random.seed(1)
with closing(db.connect()) as conn:
    eventlab.ensure_tables(conn)
    for i in range(80):
        a = f"a{i}"; sent = "호재" if i % 2 else "악재"; typ = ["계약·수주", "공모·사모(희석)", "실적 발표"][i % 3]
        conn.execute("INSERT INTO ev_docs (accession, ticker, form, items, filed, title, types, sentiment, ok) VALUES (?,?,?,?,?,?,?,?,1)",
                     (a, f"T{i % 9}", "8-K", "8.01", f"2026-0{1 + i % 9}-1{i % 9}", "t", json.dumps([typ], ensure_ascii=False), sent))
        conn.execute("INSERT INTO ev_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (a, f"T{i % 9}", f"2026-0{1 + i % 9}-1{i % 9}", "장중" if i % 4 else "장후",
                     random.choice([0.5, 2.0, 7.0]), 1.0, random.uniform(-20, 30), random.uniform(0, 40), random.uniform(-30, 0), random.uniform(-20, 20), 2.0, 0.5, random.uniform(-10, 10)))
    conn.execute(papertrade.DDL)
    conn.commit()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    diag_events.main()
out = buf.getvalue()
for need in ("[1] 수집: 공시 80건", "[2] 사건 종류별", "계약·수주", "[3] 호재·악재", "[4] 가격대 $1 미만", "[5b]", "절사평균", "[6] 가중치 제안", "RANK_W_NEWS", "[7] 가상매매: 전체 0건", "끝."):
    assert need in out, (need, out[-1500:])
# 절사평균: 극단값 하나가 평균을 끌어올려도 절사평균·중앙값은 그대로
import pandas as pd
x = pd.Series([1.0] * 19 + [1000.0])
assert x.mean() > 50 and abs(eventlab.trimmed(x) - 1.0) < 1e-9 and x.median() == 1.0
print("ALL OK")
