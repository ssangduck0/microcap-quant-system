import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import pandas as pd
import db, secbackfill as sb
db.init_db()
with closing(db.connect()) as conn:
    for t, d, nh, nc in (("AAA", "2020-03-10", 30.0, 5.0), ("AAA", "2023-06-01", 2.0, -8.0), ("BBB", "2022-01-05", 50.0, 20.0), ("OLD", "2019-01-01", 1.0, 1.0)):
        conn.execute("INSERT INTO case_events (ticker, date, next_high_pct, next_close_pct) VALUES (?,?,?,?)", (t, d, nh, nc))
    conn.commit()
calls = []
class FS:
    def cik_for(s, t): return None if t == "OLD" else {"AAA": 1, "BBB": 2}[t]
    def submissions(s, cik):
        if cik == 1:
            rec = {"accessionNumber": ["a1", "a2"], "form": ["424B5", "8-K"], "filingDate": ["2023-05-30", "2023-05-31"], "items": ["", "1.01"]}
            return {"filings": {"recent": rec, "files": [{"name": "CIK0000000001-submissions-001.json", "filingFrom": "2015-01-01", "filingTo": "2021-12-31"},
                                                          {"name": "CIK0000000001-submissions-000.json", "filingFrom": "2005-01-01", "filingTo": "2010-12-31"}]}}
        return {"filings": {"recent": {"accessionNumber": ["b1"], "form": ["10-Q"], "filingDate": ["2021-11-10"], "items": [""]}}}
    def _get(s, url):
        calls.append(url)
        class R:
            def json(self_): return {"accessionNumber": ["a0", "a00"], "form": ["8-K", "S-1"], "filingDate": ["2020-01-15", "2015-05-01"], "items": ["3.01,5.03", ""]}
        return R()
r = sb.build(FS(), years=10, out=lambda *_: None); print(r, calls)
assert r["tickers"] == 3 and len(calls) == 1 and calls[0].endswith("-001.json")                # 10년 범위 밖(2005~2010) 파일은 받지 않음
assert sb.build(FS(), years=10, out=lambda *_: None)["tickers"] == 0                             # 이어받기: 완료 종목은 건너뜀
s = sb.status(); assert s["done"] == 2 and s["no_cik"] == 1 and s["filings"] >= 4
ev = db.read_df("SELECT ticker, date, next_high_pct, next_close_pct FROM case_events")
hist = db.read_df("SELECT ticker, form, filed, items FROM sec_hist")
fl = sb.event_flags(ev, hist); ev = ev.join(fl); print(ev.to_string(index=False))
a20 = ev[(ev.ticker == "AAA") & (ev.date == "2020-03-10")].iloc[0]; a23 = ev[(ev.ticker == "AAA") & (ev.date == "2023-06-01")].iloc[0]
assert a20["notice"] and a20["charter"] and not a20["offering"] and a20["quiet"]                 # 3.01·5.03(2020-01-15)은 90일·180일 안, 급락일 근처 공시는 없음
assert a23["offering"] and a23["news"] and not a23["quiet"] and not a23["notice"]               # 424B5(-2일)·8-K(-1일)
assert ev[ev.ticker == "BBB"].iloc[0]["quiet"] and pd.isna(ev[ev.ticker == "OLD"].iloc[0]["offering"])   # CIK 없는 종목은 판정 불가
# sync_from_feed(2026-10-30): 스캐너 피드 → 공시 이력. 종목 없는 행은 빼고, 두 번째는 0건
import secfeed as _sf
from contextlib import closing as _cl
with _cl(db.connect()) as _c:
    _c.execute(_sf.DDL)
    _c.executemany("INSERT OR REPLACE INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [("0009-01", "aaa", 1, "8-K", "A", "2026-10-28", "2026-10-28T12:00:00", "1.01,3.02", "u", "[]", 0, "중립", 1, "x"),
                    ("0009-02", "BBB", 2, "424B5", "B", None, "2026-10-29T12:00:00", None, "u", "[]", 0, "중립", 1, "x"),
                    ("0009-03", None, 3, "8-K", "C", "2026-10-29", "2026-10-29T12:00:00", "", "u", "[]", 0, "중립", 1, "x")])
    _c.commit()
    assert sb.sync_from_feed(_c) == 2
    _rows = {r[0]: tuple(r) for r in _c.execute("SELECT accession, ticker, form, filed, items FROM sec_hist WHERE accession LIKE '0009-%'")}
    assert _rows["0009-01"] == ("0009-01", "AAA", "8-K", "2026-10-28", "1.01,3.02") and _rows["0009-02"] == ("0009-02", "BBB", "424B5", "2026-10-29", "") and "0009-03" not in _rows, _rows
    assert sb.sync_from_feed(_c) == 0
print("ALL OK")
