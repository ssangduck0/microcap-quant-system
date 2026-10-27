"""C단계(2026-10-28) 커버리지: 공시 피드 대상 넓히기(토스 전 종목·급등락 7일·가상매매) · 스캐너 급등락 종목 기본자료 채우기(한도 안에서)."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import db, secfeed, mover, tradable, papertrade, scanner
db.init_db()
T = date.today(); d = lambda n: (T - timedelta(days=n)).isoformat()

with closing(db.connect()) as conn:
    mover.ensure(conn)
    for i, (tk, day) in enumerate([("UPX", d(0)), ("UP2", d(0)), ("OLD9", d(9)), ("DNX", d(0))], 1):
        conn.execute("INSERT INTO toss_rank (date, kind, rank, ticker, price, change_pct, session, at) VALUES (?,?,?,?,1,50,'reg',?)",
                     (day, "down" if tk == "DNX" else "up", i, tk, db.utcnow_iso()))
    conn.commit()
tradable.active = lambda conn=None, ttl=600: {"BRAI", "abc"}
papertrade.open_tickers = lambda: ["PTX"]
ex = secfeed.coverage_extra(); print(sorted(ex))
assert {"BRAI", "ABC", "PTX", "UPX", "UP2", "DNX"} <= ex and "OLD9" not in ex                          # 7일 넘은 순위는 제외 · 대문자

class FakeClient:
    _map = {"BRAI": 111, "ABC": 222, "PTX": 333, "UPX": 444}
    def cik_for(self, t): return self._map.get(t)
secfeed._MAP_CACHE.update(at=0, map={})
m = secfeed.universe_map(FakeClient()); print(m)
assert m[111] == "BRAI" and m[444] == "UPX" and 333 in m                                                # 피드 대상에 토스 전 종목·급등락·가상매매가 들어감

# 스캐너: 급등락 상위 종목 기본자료 채우기 — 한도(fund 2 · sec 1)가 다 떨어지면 멈춤
calls = []
def fake_fund(conn, t, budget):
    calls.append(("f", t)); budget["fund"] -= 1
    return {"updated_at": "now", "shares_out": 1e6}
def fake_dil(conn, client, t, budget):
    calls.append(("d", t)); budget["sec"] -= 1
    return {"checked_at": "now", "status": "CLEAN"}
scanner.get_fundamentals = fake_fund; scanner.dilution_for = fake_dil
with closing(db.connect()) as conn:
    n = scanner.mover_fill(conn, object(), None, budget={"fund": 2, "sec": 1}); print(n, calls)
    assert n == 4 and [c for c in calls] == [("f", "UPX"), ("d", "UPX"), ("f", "UP2"), ("d", "UP2")]      # DNX 는 한도 소진으로 다음 사이클
    calls.clear()
    assert scanner.mover_fill(conn, None, None, budget={"fund": 9, "sec": 9}) == 3 and [c[0] for c in calls] == ["f", "f", "f"]   # client 없으면 희석은 건너뜀
    def boom(conn, t, budget): raise RuntimeError("x")
    scanner.get_fundamentals = boom
    assert scanner.mover_fill(conn, None, None, budget={"fund": 9, "sec": 9}) == 0                       # 실패해도 스캐너는 계속
print("ALL OK")
