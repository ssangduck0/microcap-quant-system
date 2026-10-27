import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, eventlab as ev
db.init_db()
idx = pd.bdate_range(end=date.today() - timedelta(days=1), periods=120)
px = pd.DataFrame({"Open": 1.0, "High": 1.1, "Low": 0.9, "Close": np.linspace(1, 2, len(idx)), "Volume": 1e6}, index=idx)
filed = idx[60].strftime("%Y-%m-%d")
with closing(db.connect()) as conn:
    ev.ensure_tables(conn)
    # 주가 없는 종목 3개(DEAD*)가 먼저 들어가 있고, 그 뒤에 살아 있는 종목 2개
    for i, t in enumerate(["DEAD1", "DEAD2", "DEAD3", "LIVE1", "LIVE2"]):
        conn.execute("INSERT INTO ev_docs (accession, ticker, form, items, filed, accepted, title, types, sentiment, ok) VALUES (?,?,?,?,?,?,?,?,?,1)",
                     (f"a{i}", t, "8-K", "8.01", filed, f"{filed} 08:00:00", "t", '["기타"]', "중립"))
    conn.commit()
dl = lambda ts: {t: (None if t.startswith("DEAD") else px) for t in ts}  # noqa: E731
n1 = ev.label(limit_tickers=3, download=dl, out=lambda *_: None)
n2 = ev.label(limit_tickers=3, download=dl, out=lambda *_: None)
with closing(db.connect()) as conn:
    done = {r[0] for r in conn.execute("SELECT ticker FROM ev_labels")}
    st = dict(conn.execute("SELECT ticker, status FROM ev_label_try").fetchall())
assert done == {"LIVE1", "LIVE2"}, (n1, n2, done, st)          # 예전엔 DEAD1~3 만 계속 시도해서 LIVE 가 영원히 안 됨
assert st["DEAD1"] == "no_data" and st["LIVE1"] == "ok", st
# 주가 없던 종목은 14일 동안 건너뜀
calls = []
ev.label(limit_tickers=10, download=lambda ts: calls.extend(ts) or {t: None for t in ts}, out=lambda *_: None)
assert not any(t.startswith("DEAD") for t in calls), calls
print("ALL OK")
