import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""공시 피드 CIK → 티커(2026-10-31): 한 회사에 티커가 여럿(WHLR·WHLRP)이면 집합 순서로 아무거나 골라 WHLR 공시가 전부 WHLRP 로 저장됐음.
SEC 표 순서(회사마다 보통주가 맨 앞) → 우리가 보는 종목 순으로 고정 · 이미 저장된 행(공시 피드·공시 이력·🗓 역분할 시행)을 고쳐 씀."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import db, secfeed, secbackfill, watch
db.init_db()


class FakeClient:
    _map = {"CMCSA": 5, "WHLR": 1, "ABC": 2, "CUBI": 3, "XYZ": 4, "CCZ": 5, "WHLRD": 1, "WHLRP": 1, "ABCW": 2, "CUBB": 3}   # 실제 SEC 표처럼 회사마다 보통주가 먼저
    def cik_for(self, t): return self._map.get(t)


secfeed.core_tickers = lambda ttl=3600: {"WHLRP", "ABCW", "CUBI", "CUBB"}
secfeed.coverage_extra = lambda: {"WHLR", "abc", "XYZ", "CMCSA", "CCZ"}
secfeed._MAP_CACHE.update(at=0, map={}, multi={})
m = secfeed.universe_map(FakeClient())
assert m == {1: "WHLR", 2: "ABC", 3: "CUBI", 4: "XYZ", 5: "CMCSA"}, m        # 우리가 보는 쪽(WHLRP·ABCW·CUBB)보다 SEC 표의 보통주 · 짧은 채권 티커(CCZ)보다 CMCSA
assert secfeed._MAP_CACHE["multi"] == {1: ["WHLRP"], 2: ["ABCW"], 3: ["CUBB"], 5: ["CCZ"]}, secfeed._MAP_CACHE["multi"]

with closing(db.connect()) as conn:
    secfeed.ensure_tables(conn); secbackfill.ensure_tables(conn); watch.ensure_tables(conn)
    ins = "INSERT INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) VALUES (?,?,?,'8-K','c','2026-10-26','x','','','[]',0,'',1,'x')"
    for acc, t, cik in (("w1", "WHLRP", 1), ("w2", "WHLRP", 1), ("w3", "WHLR", 1), ("x1", "XYZ", 4), ("c1", "CUBB", 3)):
        conn.execute(ins, (acc, t, cik))
    conn.commit()
    assert secbackfill.sync_from_feed(conn) == 5                                  # 공시 이력에도 WHLRP 로 들어가 있던 상태
    ev = "INSERT INTO events (ticker, date, kind, title, source, origin, created_at) VALUES (?,?,?,?,'s',?,'x')"
    conn.execute(ev, ("WHLRP", "2026-10-29", "역분할 시행", "역분할 1:6 시행", "secfeed"))
    conn.execute(ev, ("WHLRP", "2026-11-20", "배당", "우선주 배당", "manual"))      # 사람이 적은 다른 일정은 그대로
    conn.commit()
    n = secfeed.relabel(conn, FakeClient())
    assert n == 2 + 1 + 2 + 1 + 1, n                                              # 피드 WHLRP 2 + CUBB 1 · 이력 2 + 1 · 역분할 1
    assert {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM sec_feed WHERE cik=1")} == {"WHLR"}
    assert conn.execute("SELECT COUNT(*) FROM sec_hist WHERE ticker='WHLR'").fetchone()[0] == 3 and conn.execute("SELECT ticker FROM sec_hist WHERE accession='c1'").fetchone()[0] == "CUBI"
    assert conn.execute("SELECT ticker FROM events WHERE kind='역분할 시행'").fetchone()[0] == "WHLR"
    assert conn.execute("SELECT ticker FROM events WHERE kind='배당'").fetchone()[0] == "WHLRP"
    assert conn.execute("SELECT ticker FROM sec_feed WHERE accession='x1'").fetchone()[0] == "XYZ"
    assert secfeed.relabel(conn, FakeClient()) == 0                               # 여러 번 돌려도 같음
print("ALL OK")
