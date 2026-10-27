import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from pathlib import Path
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, market, universe, scanner, sec
db.init_db()
config.BASE_DIR = Path(tmp); manual = Path(tmp)/"manual_tickers.txt"; manual.write_text("MANBIG\n"); config.MANUAL_TICKERS_FILE = manual
config.MAX_MARKET_CAP_USD = 300_000_000; config.MAX_CANDIDATES = 100

idx = pd.bdate_range(end=pd.Timestamp.today().normalize()-pd.Timedelta(days=1), periods=45)[-40:]
def frame(spike):
    c = np.linspace(2.0, 1.0, 40); v = np.full(40, 2e6); v[-1] = 2e6*spike
    return pd.DataFrame({"Open":c,"High":c*1.05,"Low":c*0.95,"Close":c,"Volume":v}, index=idx)
big = [f"BIG{i:03d}" for i in range(120)]; small = [f"SML{i:03d}" for i in range(80)]
frames = {t: frame(30+i) for i,t in enumerate(big)}                       # 대형주: 거래량 급증이 훨씬 큼
frames.update({t: frame(3+i*0.01) for i,t in enumerate(small)})
frames["MANBIG"] = frame(2); frames["RKBIG"] = frame(2)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: frames[t] for t in tk if t in frames}
calls = []
class TC:
    def stocks(s, syms):
        calls.append(len(syms))
        return [{"symbol":x,"sharesOutstanding": str(1e10 if x.startswith(("BIG","MANBIG","RKBIG")) else 9e6)} for x in syms]
names = big + small + ["MANBIG","RKBIG"]
priority = {"MANBIG","RKBIG"}      # MANBIG=수동 목록, RKBIG=랭킹에서 올라온 대형주

picked, daily, shares, mkt = scanner.stage1(names, priority, TC(), {"MANBIG"})
print("picked", len(picked), "stocks() batch sizes", calls)
assert set(small) <= set(picked), "초소형주가 대형주에 밀려 빠짐"
assert not any(t.startswith("BIG") for t in picked) and "RKBIG" not in picked      # 대형주는 후보 선정 전에 제거
assert "MANBIG" in picked                                                          # 수동 목록은 대형주여도 유지
assert len(picked) == 81 and all(t in shares for t in small)
assert sum(calls) <= len(big)+len(small)+2   # 실제 TossClient.stocks 가 200개씩 나눠 호출

# 필터 끄면 예전 동작(거래량 급증 상위 100개를 대형주가 독차지)
config.MAX_MARKET_CAP_USD = 0
p2, _, _, _ = scanner.stage1(names, priority, TC(), {"MANBIG"})
assert len([t for t in p2 if t.startswith("BIG")]) == 100 and not set(small) & set(p2)
config.MAX_MARKET_CAP_USD = 300_000_000

# 토스 조회 실패 시: 필터 없이 진행(중단하지 않음)
class BadTC:
    def stocks(s, syms): raise RuntimeError("boom")
p3, _, sh3, _ = scanner.stage1(names, priority, BadTC(), {"MANBIG"})
assert sh3 == {} and len(p3) == 102     # prio 2 + others 상위 100
print("stage1 OK")

# run_cycle 통합: 2단계 안전망은 이미 받은 발행주식수를 재사용(재조회 없음)
calls.clear()
idx2 = pd.date_range(pd.Timestamp.today().normalize().tz_localize("America/New_York")+pd.Timedelta(hours=4), periods=60, freq="min")
def intra(): 
    ic=np.linspace(1.0,0.8,60); return pd.DataFrame({"Open":ic,"High":ic*1.002,"Low":ic*0.998,"Close":ic,"Volume":np.full(60,3e4)}, index=idx2)
market.download_intraday = lambda tk: {t: intra() for t in tk}
market.fetch_fundamentals = lambda t: {"name":t,"exchange":"NASDAQ","float_shares":8e6,"shares_out":9e6,"market_cap":1e7}
universe.get_universe = lambda *a, **k: (names, priority)
class FS(sec.SecClient):
    def __init__(s): pass
    def cik_for(s,t): return 1
    def submissions(s,c): return {"filings":{"recent":{"accessionNumber":[],"primaryDocument":[],"form":[],"filingDate":[],"items":[]}}}
class FTC(TC):
    def exchange_rate(s): return 1400.0
    def us_calendar(s): return {}
    def intraday_frame(s, sym): return intra()
scanner.notify.send_telegram = lambda x: True
with closing(db.connect()) as conn:
    n = scanner.run_cycle(conn, FS(), FTC())
    rows = {r[0] for r in conn.execute("SELECT ticker FROM daily_snapshots")}
print("saved", n, "stocks() calls", calls)
assert n == config.MAX_SEC_CHECKS_PER_CYCLE and all(t.startswith(("SML","MANBIG")) for t in rows), rows
assert calls[0] == 202 and calls.count(202) == 1, calls   # 1단계에서 한 번에 조회하고, 2단계 시총 안전망은 이미 받은 발행주식수를 재사용(재조회 없음)
assert len(calls) <= 2, calls                              # 추가 호출은 장마감 체크리스트의 후보 종목 발행주식수 조회 1회뿐
with closing(db.connect()) as c:
    vals = [r[0] for r in c.execute("SELECT day_change_pct FROM daily_snapshots")]
assert vals and all(v is not None for v in vals), vals            # 스캐너가 오늘 등락률(전일 종가 대비)을 저장
print("day_change saved OK")
print("ALL OK")
