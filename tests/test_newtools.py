import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, config, aipick, secdigest, newtools, secfeed
db.init_db()
T = date.today(); d = lambda n: (T - timedelta(days=n)).isoformat()
with closing(db.connect()) as conn:
    for ddl in ([secfeed.DDL] if isinstance(secfeed.DDL, str) else list(secfeed.DDL)):
        conn.execute(ddl)
    conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, date TEXT, kind TEXT, title TEXT, source TEXT, origin TEXT, created_at TEXT)")
    rows = [("a1", "AAA", "8-K", d(1), "http://x/a1"), ("a2", "BBB", "SC 13D", d(2), "http://x/a2"), ("a3", "CCC", "10-Q", d(1), "http://x/a3"),
            ("a4", "DDD", "424B5", d(1), "http://x/a4"), ("a5", "EEE", "8-K", d(30), "http://x/a5")]
    for a, t, fm, fl, u in rows:
        conn.execute("INSERT INTO sec_feed (accession, ticker, form, company, filed, updated, url) VALUES (?,?,?,?,?,?,?)", (a, t, fm, t + " Inc", fl, fl + "T12:00:00", u))
    conn.commit()
    p = secdigest.pending(conn)
    assert [x["accession"] for x in p] == ["a1", "a4", "a2"] or sorted(x["accession"] for x in p) == ["a1", "a2", "a4"], p   # 10-Q·7일 지난 것 제외
class C:
    def fetch_text(self, url, limit=0):
        return "Item 5.03 ... The 1-for-10 reverse stock split will become effective on " + d(-5) + " ... " + "x " * 3000
calls = []
class R:
    status_code = 200
    def json(self):
        items = [{"accession": "a1", "summary_ko": "AAA가 1대10 역분할을 시행해요.", "category": "병합", "grade": "A", "rs": {"date": d(-5), "ratio": "1:10"}, "holder": None},
                 {"accession": "a2", "summary_ko": "XYZ 펀드가 BBB 지분 9.9%를 신고했어요.", "category": "대량보유", "grade": "B", "rs": None,
                  "holder": {"name": "XYZ Capital", "pct": "9.9%", "type": "경영개입형"}},
                 {"accession": "a4", "summary_ko": "DDD 공모 가격 확정.", "category": "엉뚱한분류", "grade": "Z", "rs": None, "holder": None}]
        return {"content": [{"type": "text", "text": json.dumps({"items": items}, ensure_ascii=False)}], "usage": {"input_tokens": 3000, "output_tokens": 600}}
def post(url, headers=None, json=None, timeout=None):
    calls.append(json); return R()
assert secdigest.run(client=C(), post=post, out=lambda *_: None) == 3
assert calls[0]["model"] == "claude-haiku-5-5" and calls[0]["thinking"] == {"type": "disabled"} and "13D" in calls[0]["system"]
with closing(db.connect()) as conn:
    dg = secdigest.digests(conn, ["a1", "a2", "a4"])
    assert dg["a1"]["grade"] == "A" and dg["a4"]["category"] == "기타" and dg["a4"]["grade"] == "C"           # 이상한 값은 안전하게
    ev = [tuple(x) for x in conn.execute("SELECT ticker, date, kind, title FROM events").fetchall()]
    assert ev == [("AAA", d(-5), "역분할 시행", "역분할 1:10 시행")], ev                                        # 🔁 병합 예정으로
    h = secdigest.holders(conn)
    assert len(h) == 1 and h.iloc[0]["holder"] == "XYZ Capital" and h.iloc[0]["pct"] == 9.9 and h.iloc[0]["type"] == "경영개입형"
assert secdigest.run(client=C(), post=post, out=lambda *_: None) == 0 and len(calls) == 1                     # 다시 요약 안 함
config.SEC_DIGEST = False; assert secdigest.run(client=C(), post=post, out=lambda *_: None) == 0; config.SEC_DIGEST = True

# 🌀 폭풍의 눈 — 화면은 없고 🕰 타임머신 시험 조건으로만(아래)
idx = pd.bdate_range(start=pd.Timestamp(T) - pd.Timedelta(days=320), periods=200)
c1 = np.r_[np.linspace(3.0, 1.0, 199), [1.02]]; v1 = np.r_[np.full(150, 2e5), np.full(30, 1e6), np.full(19, 3e5), [3e4]]

# 🏦 대량 보유 화면(폭풍의 눈·다크풀 화면은 없음)
from streamlit.testing.v1 import AppTest
assert not hasattr(newtools, "render_gem") and not hasattr(newtools, "render_darkpool")
for fn in ("render_holders",):
    src = f"import sys, os\nsys.path.insert(0, os.environ['QS_ROOT'])\nimport newtools\nnewtools.{fn}()\n"
    at = AppTest.from_string(src, default_timeout=120).run()
    assert not at.exception, (fn, [e.value for e in at.exception])
    txt = " ".join(m.value for m in at.markdown) + " ".join(df_.value.to_string() for df_ in at.dataframe)
    assert "XYZ Capital" in txt, (fn, txt[:300])

# 🕰 타임머신 조합
import timemachine as tm
rws = tm.ticker_rows("GEMX", pd.DataFrame({"Open": c1, "High": c1 * 1.01, "Low": c1 * 0.99, "Close": c1, "Volume": v1}, index=idx), [], idx[0].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d"), step=1)
assert rws and all("vac" in x and "low52" in x for x in rws) and any(n == "🌀 폭풍의 눈+③" for n, _ in tm.COMBOS)
print("ALL OK")
