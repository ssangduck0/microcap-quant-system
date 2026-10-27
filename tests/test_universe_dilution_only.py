import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, universe, market, scanner, sec
config.INTEL_SEC_MAX_PER_CYCLE = 0   # 공통 인텔 SEC 확인을 끄고 희석 판정 한도만 검증
db.init_db()

# 1) 상장 목록 파싱
LISTED = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
ABCDW|ABCD Acquisition Corp - Warrants|S|N|N|100|N|N
ABCDU|ABCD Acquisition Corp - Units|S|N|N|100|N|N
QQQ|Invesco QQQ Trust|G|N|N|100|Y|N
ZZZZT|Test Co|G|Y|N|100|N|N
SMOL|Small Corp - Common Stock|S|N|D|100|N|N
RGHT|Foo Corp - Rights|S|N|N|100|N|N
BRK.B|Berkshire|Q|N|N|100|N|N
File Creation Time: 1012202623:00|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
AMEXA|Amex Micro - Common Stock|A|AMEXA|N|100|N|AMEXA
NYSEA|Big Corp|N|NYSEA|N|100|N|NYSEA
File Creation Time: 1012202623:00|||||||
"""
class R:
    def __init__(s,t): s.text=t
    def raise_for_status(s): pass
orig = universe.requests.get
universe.requests.get = lambda url, **kw: R(LISTED if "nasdaqlisted" in url else OTHER)
assert universe._fetch_listed(False) == ["AAPL","SMOL"], universe._fetch_listed(False)
assert universe._fetch_listed(True) == ["AAPL","AMEXA","SMOL"]
universe.requests.get = orig
print("parse OK")

# 2) 2단계 사이클: 합성 종목 400개
rng = np.random.default_rng(1)
idx = pd.bdate_range(end=pd.Timestamp.today().normalize()-pd.Timedelta(days=1), periods=50)[-42:]
def frame(kind):
    n=len(idx)
    if kind=="drop":      close=np.linspace(2.0,1.0,n)           # -50% 낙폭
    elif kind=="flat":    close=np.full(n,1.0)                    # 낙폭 없음
    elif kind=="penny":   close=np.linspace(0.04,0.02,n)          # 가격 필터 탈락
    elif kind=="big":     close=np.linspace(80,40,n)              # 가격 상한 탈락
    elif kind=="dead":    close=np.linspace(2.0,1.0,n)
    vol = rng.integers(2e6,3e6,n).astype(float)
    if kind=="dead": vol = np.full(n, 10.0)                       # 거래대금 탈락
    v = vol.copy(); 
    return pd.DataFrame({"Open":close,"High":close*1.03,"Low":close*0.97,"Close":close,"Volume":v}, index=idx)
tick = {}
for i in range(300): tick[f"D{i:03d}"[:5].replace("D","DR")] = "drop"   # 길이 맞추기용 이름
names = [f"T{i:04d}" for i in range(400)]
kinds = {}
for i,t in enumerate(names):
    kinds[t] = "drop" if i<250 else "flat" if i<300 else "penny" if i<330 else "big" if i<360 else "dead"
# drop 종목에 거래량 급증 차등: 뒤쪽 번호일수록 오늘 거래량 큼
frames = {}
for i,t in enumerate(names):
    f = frame(kinds[t])
    if kinds[t]=="drop": f.iloc[-1, f.columns.get_loc("Volume")] *= (1 + i/10)
    frames[t]=f
# 우선종목은 필터 탈락 유형(flat)이어도 포함돼야 함
priority = {"T0260"}
market.download_daily = lambda tk, period="3mo", chunk=40: {t: frames[t] for t in tk if t in frames}
inspected = []
def fake_intra(tk):
    inspected.extend(tk)
    out={}
    for t in tk:
        n=60; ic=np.linspace(1.0,0.8,n)+rng.normal(0,0.002,n)
        iidx=pd.date_range(pd.Timestamp.today().normalize().tz_localize("America/New_York")+pd.Timedelta(hours=4),periods=n,freq="min")
        out[t]=pd.DataFrame({"Open":ic,"High":ic*1.002,"Low":ic*0.998,"Close":ic,"Volume":rng.integers(1e4,5e4,n)},index=iidx)
    return out
market.download_intraday = fake_intra
fund_calls=[]
def fake_fund(t): fund_calls.append(t); return {"name":t,"exchange":"NASDAQ","float_shares":8e6,"shares_out":9e6,"market_cap":1e7}
market.fetch_fundamentals = fake_fund
universe.get_universe = lambda *a, **k: (names, priority)
sec_calls=[]
class Fake(sec.SecClient):
    def __init__(s): pass
    def cik_for(s,t): return 1
    def submissions(s,c): sec_calls.append(1); return {"filings":{"recent":{"accessionNumber":[],"primaryDocument":[],"form":[],"filingDate":[],"items":[]}}}
scanner.notify.send_telegram = lambda x: True
with closing(db.connect()) as conn:
    n = scanner.run_cycle(conn, Fake())
    print("cycle1 saved", n, "intraday requested", len(inspected), "sec calls", len(sec_calls), "fund calls", len(fund_calls))
    assert len(inspected) == config.MAX_CANDIDATES + 1            # 상위 100 + 우선종목 1
    assert "T0260" in inspected                                   # 우선종목 포함
    assert not any(t in inspected for t in names[300:360])        # 가격 필터 탈락 종목 제외
    assert not any(t in inspected for t in names[360:])           # 거래대금 탈락 제외
    top = sorted(inspected)
    assert "T0249" in inspected and "T0000" not in inspected      # 거래량 급증 순으로 선택
    assert len(sec_calls) <= config.MAX_SEC_CHECKS_PER_CYCLE   # 희석 판정 한도 + 공통 인텔 장중 공시 확인 한도(따로 제한)
    assert len(fund_calls) <= config.MAX_NEW_FUNDAMENTALS_PER_CYCLE
    # 우선종목은 1단계 필터를 건너뛰고 가장 먼저 정밀 분석(SEC 한도도 먼저 사용)된다
    assert conn.execute("SELECT COUNT(*) FROM daily_snapshots WHERE ticker='T0260'").fetchone()[0]==1
    assert n == config.MAX_SEC_CHECKS_PER_CYCLE                    # 이번 사이클 검사된 15개만 저장
    # SEC 검사 안 된 종목이 '희석 없음'으로 저장되지 않았는지
    assert conn.execute("SELECT COUNT(*) FROM daily_snapshots s LEFT JOIN dilution d USING(ticker) WHERE d.ticker IS NULL").fetchone()[0]==0
    # 사이클을 거듭하면 나머지가 처리됨
    for _ in range(7): scanner.run_cycle(conn, Fake())
    tot = conn.execute("SELECT COUNT(*) FROM daily_snapshots").fetchone()[0]
    print("after 8 cycles snapshots", tot)
    assert tot >= 100
print("ALL OK")
