import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
os.environ["TOSS_CLIENT_ID"]="tsck_test"; os.environ["TOSS_CLIENT_SECRET"]="s_secret_value"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, toss, universe, market, scanner, sec
config.BASE_DIR = Path(tmp)
db.init_db()

class Resp:
    def __init__(s, status=200, body=None, headers=None): s.status_code=status; s._b=body if body is not None else {}; s.headers=headers or {}; s.text=json.dumps(s._b)
    def json(s): return s._b
class Sess:
    """routes: (method, path) -> callable(params/data) -> Resp"""
    def __init__(s): s.posts=[]; s.gets=[]; s.routes={}; s.token_n=0; s.valid_token=None
    def post(s, url, data=None, timeout=0):
        s.posts.append(data); h = s.routes.get(("POST", "/oauth2/token"))
        if h: return h(data)
        s.token_n += 1; s.valid_token = f"tok{s.token_n}"
        return Resp(200, {"access_token": s.valid_token, "token_type":"Bearer", "expires_in": 86400})
    def get(s, url, params=None, headers=None, timeout=0):
        path = "/" + url.split("://",1)[1].split("/",1)[1]
        s.gets.append((path, params, headers))
        return s.routes[("GET", path)](params, headers)
class Clock:
    def __init__(s): s.t=1000.0; s.slept=[]
    def now(s): return s.t
    def sleep(s, x): s.slept.append(x); s.t += x
def mk(sess, clk): return toss.TossClient("tsck_test","s_secret_value","https://openapi.tossinvest.com",session=sess,sleep=clk.sleep,clock=clk.now)

# 1) 토큰 캐시 + 헤더
sess, clk = Sess(), Clock()
def ok_price(params, headers):
    assert headers["Authorization"] == f"Bearer {sess.valid_token}"
    return Resp(200, {"result":[{"symbol":s,"timestamp":"t","lastPrice":"1.25","currency":"USD"} for s in params["symbols"].split(",")]})
sess.routes[("GET","/api/v1/prices")] = ok_price
tc = mk(sess, clk)
for _ in range(3): tc.prices(["AAA"])
assert len(sess.posts)==1, len(sess.posts)
assert "s_secret" not in repr(tc)
print("token cache OK")

# 2) prices 묶음 분할(250 -> 2회) + float 변환
sess.gets.clear(); res = tc.prices([f"T{i}" for i in range(250)])
assert len(sess.gets)==2 and len(res)==250 and res["T0"]["price"]==1.25
# 3) 401 만료 -> 재발급 1회 후 성공
sess2, clk2 = Sess(), Clock(); calls={"n":0}
def flaky(params, headers):
    calls["n"]+=1
    if calls["n"]==1: return Resp(401, {"error":{"requestId":"r1","code":"expired-token","message":"expired"}})
    return Resp(200, {"result":[{"symbol":"A","timestamp":"t","lastPrice":"2","currency":"USD"}]})
sess2.routes[("GET","/api/v1/prices")]=flaky; tc2=mk(sess2,clk2)
assert tc2.prices(["A"])["A"]["price"]==2.0 and len(sess2.posts)==2
# 4) 429 Retry-After
sess3, clk3 = Sess(), Clock(); c3={"n":0}
def lim(params, headers):
    c3["n"]+=1
    return Resp(429, {"error":{"code":"rate-limit-exceeded","message":"x"}}, {"Retry-After":"3"}) if c3["n"]==1 else Resp(200, {"result":[]})
sess3.routes[("GET","/api/v1/prices")]=lim; tc3=mk(sess3,clk3); tc3.prices(["A"])
assert any(abs(x-3)<1e-6 for x in clk3.slept), clk3.slept
# 5) 오류 매핑
sess4, clk4 = Sess(), Clock()
sess4.routes[("GET","/api/v1/candles")] = lambda p,h: Resp(404, {"error":{"requestId":"rq","code":"stock-not-found","message":"없음"}})
tc4=mk(sess4,clk4)
try: tc4.candles("ZZZ"); raise SystemExit("no error")
except toss.TossError as e: assert e.code=="stock-not-found" and e.status==404 and "rq" in str(e)
# 6) 인증 403 -> 이후 5분간 호출 차단(실패 폭주 방지)
sess5, clk5 = Sess(), Clock()
sess5.routes[("POST","/oauth2/token")] = lambda d: Resp(403, {"error":"access_denied","error_description":"IP address not allowed"})
tc5 = mk(sess5, clk5)
for i in range(5):
    try: tc5.exchange_rate(); raise SystemExit("no error")
    except toss.TossError as e:
        if i==0: assert e.status==403 and "허용 IP" in str(e)
        else: assert e.code=="auth-blocked"
assert len(sess5.posts)==1, len(sess5.posts)
clk5.t += 301
try: tc5.exchange_rate()
except toss.TossError as e: assert e.code!="auth-blocked"
assert len(sess5.posts)==2
print("auth/err/429 OK")

# 7) 속도 제한: MARKET_DATA 10회 호출 간격
sess6, clk6 = Sess(), Clock(); sess6.routes[("GET","/api/v1/prices")] = lambda p,h: Resp(200,{"result":[]})
tc6=mk(sess6,clk6); t0=clk6.now()
for _ in range(10): tc6.prices(["A"])
assert clk6.now()-t0 >= 9*(1/12)-1e-6, clk6.now()-t0
print("rate limit OK")

# 8) 1분봉 페이지네이션 + 중복 제거 + 오늘(ET 04:00~) 필터
ET="America/New_York"
start_prev = pd.Timestamp("2026-10-09 16:00", tz=ET)
bars=[]; ts = start_prev
while ts <= pd.Timestamp("2026-10-12 11:00", tz=ET):
    if ts.hour>=20 and ts.date()==pd.Timestamp("2026-10-09").date() or ts.date()==pd.Timestamp("2026-10-12").date() and ts.hour>=4 or (ts.date()==pd.Timestamp("2026-10-09").date() and ts.hour<20):
        bars.append(ts)
    ts += pd.Timedelta(minutes=1)
    if ts.date()==pd.Timestamp("2026-10-09").date() and ts.hour>=20: ts = pd.Timestamp("2026-10-12 04:00", tz=ET)
bars = sorted(set(bars), reverse=True)
today_n = len([b for b in bars if b.date()==pd.Timestamp("2026-10-12").date()])
fmt = lambda b: b.tz_convert("Asia/Seoul").isoformat()
def candles(params, headers):
    assert params["interval"]=="1m" and params["symbol"]=="AAA" and params["count"]==200
    sel = bars if "before" not in params else [b for b in bars if b <= pd.Timestamp(params["before"])]
    page = sel[:200]
    nxt = fmt(page[-1]) if len(sel)>200 else None
    return Resp(200, {"result":{"candles":[{"timestamp":fmt(b),"openPrice":"1.0","highPrice":"1.1","lowPrice":"0.9","closePrice":"1.05","volume":"100","currency":"USD"} for b in page],"nextBefore":nxt}})
sess7, clk7 = Sess(), Clock(); sess7.routes[("GET","/api/v1/candles")]=candles; tc7=mk(sess7,clk7)
df = tc7.intraday_frame("AAA")
print("intraday rows", len(df), "today expected", today_n, "pages", len(sess7.gets))
assert len(df)==today_n and df.index.is_monotonic_increasing and not df.index.duplicated().any()
assert str(df.index.tz)==ET and df.index.min() >= pd.Timestamp("2026-10-12 04:00", tz=ET)
assert list(df.columns)==["Open","High","Low","Close","Volume"] and df["Volume"].sum()==100*today_n
m = market.compute_metrics(pd.DataFrame({"Open":[1.0]*30,"High":[1.2]*30,"Low":[0.9]*30,"Close":[1.0]*30,"Volume":[1e5]*30}, index=pd.bdate_range(end="2026-10-09", periods=32)[-30:]), df)
assert m["trade_date"]=="2026-10-12", m["trade_date"]
# 9) 세션 판정
cal = {"today":{"date":"2026-03-25","dayMarket":{"startTime":"2026-03-25T09:00:00+09:00","endTime":"2026-03-25T16:50:00+09:00"},
  "preMarket":{"startTime":"2026-03-25T17:00:00+09:00","endTime":"2026-03-25T22:30:00+09:00"},
  "regularMarket":{"startTime":"2026-03-25T22:30:00+09:00","endTime":"2026-03-26T05:00:00+09:00"},
  "afterMarket":{"startTime":"2026-03-26T05:00:00+09:00","endTime":"2026-03-26T07:00:00+09:00"}}}
k = lambda s: datetime.fromisoformat(s)
assert toss.us_session(cal, k("2026-03-25T18:00:00+09:00"))=="프리마켓"
assert toss.us_session(cal, k("2026-03-26T02:00:00+09:00"))=="정규장"
assert toss.us_session(cal, k("2026-03-26T06:00:00+09:00"))=="애프터마켓"
assert toss.us_session(cal, k("2026-03-26T08:00:00+09:00"))=="장 마감/휴장"
# 10) 병렬 분봉: 한 종목 실패해도 나머지 성공
class FakeTC:
    def intraday_frame(s, sym):
        if sym=="BAD": raise toss.TossError(404,"stock-not-found","x")
        return df
got = toss.fetch_intraday_many(FakeTC(), ["A","BAD","B"]); assert set(got)=={"A","B"}
print("intraday/session OK")

# 11) 유니버스: 토스 종목 목록 + 랭킹 + 폴백
import itertools
syms = ["".join(p) for p in itertools.product("ABCDE", repeat=4)]   # 625개
stocks = [{"symbol":s,"securityType":"STOCK","isCommonShare":True} for s in syms]
stocks += [{"symbol":"QQQQ","securityType":"ETF","isCommonShare":True},{"symbol":"WARR","securityType":"STOCK_WARRANTS","isCommonShare":True},
           {"symbol":"PREF","securityType":"STOCK","isCommonShare":False},{"symbol":"BRK.B","securityType":"STOCK","isCommonShare":True}]
class UTC:
    def __init__(s, fail=False): s.fail=fail
    def stocks_all(s, market, status="ACTIVE"):
        if s.fail: raise toss.TossError(403,"ip-not-allowed","x")
        return stocks
    def stocks(s, syms): return [{"symbol":x,"securityType":"ETF" if x=="ETFX" else "STOCK","isCommonShare":True,"status":"ACTIVE"} for x in syms]
    def rankings(s, t, c, d, n):
        if t=="MARKET_TRADING_VOLUME": raise toss.TossError(500,"internal-error","x")
        return [{"symbol":"ETFX","price":{"lastPrice":"5","changeRate":"-0.4"}},{"symbol":"LOSR","price":{"lastPrice":"1.5","changeRate":"-0.3"}},{"symbol":"BIGC","price":{"lastPrice":"250","changeRate":"-0.1"}},{"symbol":"PNY","price":{"lastPrice":"0.01"}}]
listed = universe.load_listed_toss(UTC(), False)
assert len(listed)==625 and "QQQQ" not in listed and "WARR" not in listed and "PREF" not in listed and "BRK.B" not in listed
r = universe.from_toss_rankings(UTC()); assert r=={"LOSR"}, r      # 가격대 밖 + 실패한 랭킹 허용
manual = os.path.join(tmp, "manual_tickers.txt"); open(manual,"w").write("MANU\n"); config.MANUAL_TICKERS_FILE = Path(manual)
config.SCAN_UNIVERSE="nasdaq"
allt, prio = universe.get_universe(UTC())
assert prio=={"MANU","LOSR"} and "LOSR" in allt and len(allt)==627 and "AAAA" in allt
# 토스 실패 -> nasdaqtrader 목록(캐시/다운로드) 폴백
universe.load_listed = lambda include_amex=False: ["FALL"+"A"]*1 + syms[:10]
for f in Path(tmp).glob("universe_cache_toss*"): f.unlink()
allt2, prio2 = universe.get_universe(UTC(fail=True))
assert "FALLA" in allt2 and "MANU" in prio2
print("universe OK")

# 12) 스캐너 통합: 환율/세션 기록, 토스 분봉 + yfinance 보충
idx = pd.bdate_range(end=pd.Timestamp.today().normalize()-pd.Timedelta(days=1), periods=45)[-40:]
close = np.linspace(2.0,1.0,40)
daily = pd.DataFrame({"Open":close,"High":close*1.05,"Low":close*0.95,"Close":close,"Volume":np.full(40,2e6)}, index=idx)
tdate = pd.Timestamp.today().normalize().tz_localize(ET)
def intra_frame(p):
    ii = pd.date_range(tdate+pd.Timedelta(hours=4), periods=60, freq="min"); ic=np.linspace(1.0,0.8,60)
    return pd.DataFrame({"Open":ic,"High":ic*1.002,"Low":ic*0.998,"Close":ic,"Volume":np.full(60,3e4)}, index=ii)
SHARES = {"BIGC": 1e10, "MANU": 1e10}
class STC:
    def stocks(s, syms): return [{"symbol":x,"sharesOutstanding":str(SHARES.get(x, 9e6))} for x in syms]
    def exchange_rate(s): return 1412.5
    def us_calendar(s): return cal
    def intraday_frame(s, sym):
        if sym=="YFONLY": return None
        return intra_frame(0)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: daily for t in tk}
yf_asked=[]
market.download_intraday = lambda tk: (yf_asked.extend(tk) or {t: intra_frame(0) for t in tk})
market.fetch_fundamentals = lambda t: {"name":t,"exchange":"NASDAQ","float_shares":8e6,"shares_out":9e6,"market_cap":1e7}
universe.get_universe = lambda *a, **k: (["TOSA","TOSB","YFONLY"], {"TOSA","TOSB","YFONLY"})
class FS(sec.SecClient):
    def __init__(s): pass
    def cik_for(s,t): return 1
    def submissions(s,c): return {"filings":{"recent":{"accessionNumber":[],"primaryDocument":[],"form":[],"filingDate":[],"items":[]}}}
scanner.notify.send_telegram = lambda x: True
config.SEC_USER_AGENT="T t@e.com"
with closing(db.connect()) as conn:
    n = scanner.run_cycle(conn, FS(), STC())
print("saved", n, "yfinance asked", yf_asked)
assert n==3 and sorted(yf_asked)==["TOSA","TOSB","YFONLY"]   # 거래량 기준 출처로 yfinance 를 전부 조회
assert db.get_meta("usdkrw")["value"]=="1412.5000" and db.get_meta("us_session")["value"]
# 토스 없이도 동작(기존 경로)
yf_asked.clear()
with closing(db.connect()) as conn: n2 = scanner.run_cycle(conn, FS(), None)
assert n2==3 and sorted(yf_asked)==["TOSA","TOSB","YFONLY"]
print("scanner integration OK")

# 13) 거래량 출처: 토스 분봉(합 1.8M)과 yfinance 분봉(합 3.0M)이 다를 때 배수는 분모와 같은 yfinance 기준이어야 함
def yf_frame(vol):
    f = intra_frame(0); f["Volume"] = vol; return f
def vm(ticker):
    with closing(db.connect()) as c:
        r = c.execute("SELECT volume_mult FROM daily_snapshots WHERE ticker=? ORDER BY date DESC", (ticker,)).fetchone()
    return r[0] if r else "missing"
for t in ("TOSA","TOSB","YFONLY"):
    with closing(db.connect()) as c: c.execute("DELETE FROM daily_snapshots WHERE ticker=?", (t,)); c.commit()
market.download_intraday = lambda tk: {t: yf_frame(5e4) for t in tk if t != "NOYF"}   # yfinance 합 = 5e4*60 = 3.0M, 분모 2.0M -> 1.5배
universe.get_universe = lambda *a, **k: (["TOSA","NOYF","YFONLY"], {"TOSA","NOYF","YFONLY"})
class STC2(STC):
    pass
config.VOLUME_SOURCE = "yahoo"
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), STC2())
print("yahoo mode:", vm("TOSA"), vm("YFONLY"), vm("NOYF"))
assert abs(vm("TOSA")-1.5) < 0.01 and abs(vm("YFONLY")-1.5) < 0.01     # 토스 봉이 있어도 거래량은 yfinance 기준
assert vm("NOYF") is None                                              # 토스 봉만 있고 기준 거래량 없음 -> 틀린 값 대신 확인 불가
config.VOLUME_SOURCE = "toss"
for t in ("TOSA","NOYF","YFONLY"):
    with closing(db.connect()) as c: c.execute("DELETE FROM daily_snapshots WHERE ticker=?", (t,)); c.commit()
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), STC2())
print("toss mode:", vm("TOSA"), vm("NOYF"))
assert abs(vm("TOSA")-0.9) < 0.01 and abs(vm("NOYF")-0.9) < 0.01      # 토스 분봉 합 1.8M / 2.0M
config.VOLUME_SOURCE = "yahoo"
print("volume source OK")

# 14) 시총 필터: 초소형주 아닌 종목 제외(수동 목록은 유지), 끄기, UNKNOWN 사유 로그
import logging
logs = []
class H(logging.Handler):
    def emit(s, r): logs.append(r.getMessage())
logging.getLogger("scanner").addHandler(H()); logging.getLogger("scanner").setLevel(logging.INFO)
config.VOLUME_SOURCE = "yahoo"
universe.get_universe = lambda *a, **k: (["TOSA","BIGC","MANU"], {"TOSA","BIGC","MANU"})
def present(*ts):
    with closing(db.connect()) as c: return {t for t in ts if c.execute("SELECT 1 FROM daily_snapshots WHERE ticker=?", (t,)).fetchone()}
with closing(db.connect()) as c: c.execute("DELETE FROM daily_snapshots"); c.commit()
config.MAX_MARKET_CAP_USD = 300_000_000
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), STC())
assert present("TOSA","BIGC","MANU") == {"TOSA","MANU"}, present("TOSA","BIGC","MANU")
assert any("1단계 시총 필터" in l for l in logs), logs          # 대형주는 후보 선정 전(1단계)에 제거됨
# 2단계 안전망: 1단계 조회가 실패해도(발행주식수 없음) 실시간 가격 기준으로 다시 걸러야 함
class FlakyTC(STC):
    n = 0
    def stocks(s, syms):
        FlakyTC.n += 1
        if FlakyTC.n == 1: raise toss.TossError(500, "internal-error", "x")
        return STC.stocks(s, syms)
with closing(db.connect()) as c: c.execute("DELETE FROM daily_snapshots"); c.commit()
logs.clear()
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), FlakyTC())
assert present("TOSA","BIGC","MANU") == {"TOSA","MANU"}
assert any("시총 필터(>$300M)로 제외" in l and "BIGC" in l for l in logs), logs
with closing(db.connect()) as c: c.execute("DELETE FROM daily_snapshots"); c.commit()
config.MAX_MARKET_CAP_USD = 0
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), STC())
assert present("TOSA","BIGC","MANU") == {"TOSA","BIGC","MANU"}
config.MAX_MARKET_CAP_USD = 300_000_000
class FS0(FS):
    def cik_for(s, t): return None
with closing(db.connect()) as c: c.execute("DELETE FROM daily_snapshots"); c.execute("DELETE FROM dilution"); c.commit()
logs.clear()
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS0(), STC())
assert any("희석=UNKNOWN (SEC CIK 없음" in l for l in logs), logs[:5]
print("market cap filter OK")
print("ALL OK"); print(os.environ["QUANT_DB"])
