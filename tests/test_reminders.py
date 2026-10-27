import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, reminders, eventlab
db.init_db()
with closing(db.connect()) as conn:
    eventlab.ensure_tables(conn)
    for i in range(100):  # 공시 100건 중 90건 라벨 → 남은 10%(아직 준비 안 됨)
        conn.execute("INSERT INTO ev_docs (accession, ticker, ok) VALUES (?, 'A', 1)", (f"a{i}",))
        if i < 90:
            conn.execute("INSERT INTO ev_labels (accession, ticker) VALUES (?, 'A')", (f"a{i}",))
    conn.commit()
sent = []
send = lambda m: sent.append(m) or True  # noqa: E731
assert reminders.check(today=date(2026, 11, 1), send=send, out=lambda *_: None) == [] and not sent       # 가장 이른 날 전
assert reminders.check(today=date(2026, 11, 16), send=send, out=lambda *_: None) == [] and not sent      # 날은 됐지만 라벨 남은 10%
with closing(db.connect()) as conn:
    for i in range(90, 97):
        conn.execute("INSERT INTO ev_labels (accession, ticker) VALUES (?, 'A')", (f"a{i}",))
    conn.commit()
assert reminders.check(today=date(2026, 11, 16), send=send, out=lambda *_: None) == ["evscore_hybrid"]   # 남은 3% → 보냄
assert len(sent) == 1 and "두 방식 합치기" in sent[0] and "남은 비율 3.0%" in sent[0], sent
assert reminders.check(today=date(2026, 11, 17), send=send, out=lambda *_: None) == [] and len(sent) == 1  # 한 번만
# 텔레그램 실패면 기록 안 하고 다음 날 다시 · 늦어도 되는 날이 지나면 준비 안 돼도 보냄
db.set_meta("reminder:evscore_hybrid", "")
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM ev_labels WHERE accession IN ('a90','a91','a92','a93','a94','a95','a96')"); conn.commit()
assert reminders.check(today=date(2026, 11, 23), send=lambda m: False, out=lambda *_: None) == []
assert reminders.check(today=date(2026, 11, 23), send=send, out=lambda *_: None) == ["evscore_hybrid"]
with closing(db.connect()) as conn:
    st = reminders.status(conn, date(2026, 11, 23))[0]
assert st["sent"] == "2026-11-23" and st["earliest"] == "2026-11-15"
print("ALL OK")
