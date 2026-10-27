import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, json, tempfile
from datetime import date, timedelta
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
os.environ["SEC_USER_AGENT"] = "Test test@example.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, sec, market, scoring, scanner, analytics, universe

db.init_db()

# 1. scan_text
atm = sec.html_to_text("<html><ix:header>junk at the market</ix:header><body>Prospectus Supplement. We entered into a Sales Agreement with ABC Securities, as sales agent, for an at-the-market offering.</body></html>")
assert "junk" not in atm
assert "ATM" in sec.scan_text(atm, "424B5"), sec.scan_text(atm, "424B5")
generic = "x " * 20000 + "at the market convertible notes"
assert sec.scan_text(generic, "424B5") == [], sec.scan_text(generic, "424B5")   # 본문 깊은 곳 일반문구는 무시
assert "CB" in sec.scan_text(generic, "8-K")
eloc = sec.html_to_text("<p>Equity Purchase Agreement ... Put Notice ... pre-funded warrants ... substantial doubt</p>")
print("eloc tags", sec.scan_text(eloc, "8-K"))
assert {"ELOC","WARRANT","GOING_CONCERN"} <= set(sec.scan_text(eloc, "8-K"))

# 2. assess with fake client
today = date.today()
def f(i, form, days, items=""):
    d = (today - timedelta(days=days)).isoformat()
    return form, d, items, f"0001-{i:02d}"
class Fake(sec.SecClient):
    def __init__(self, filings, texts, fail=False):
        self.filings, self.texts, self.fail = filings, texts, fail
    def cik_for(self, t): return None if t=="NOCIK" else 123
    def submissions(self, cik):
        if self.fail: raise RuntimeError("boom")
        r = {"accessionNumber":[], "primaryDocument":[], "form":[], "filingDate":[], "items":[]}
        for form, d, items, acc in self.filings:
            r["accessionNumber"].append(acc); r["primaryDocument"].append("a.htm"); r["form"].append(form)
            r["filingDate"].append(d); r["items"].append(items)
        return {"filings":{"recent":r}}
    def fetch_text(self, url):
        if "FAIL" in self.texts.get(url.split("/")[-2], ""): raise RuntimeError("fetch")
        return sec.html_to_text(self.texts.get(url.split("/")[-2], ""))
with closing(db.connect()) as conn:
    filings = [f(1,"424B5",30), f(2,"8-K",10,"1.01,9.01"), f(3,"8-K",5,"5.02"), f(4,"S-3",200)]
    texts = {"000101": "ATM sales agreement at-the-market offering", "000102": "nothing here"}
    c = Fake(filings, texts)
    r = sec.assess(c, conn, "AAA")
    print("AAA", r["status"], r["flags"]["ATM"], r["flags"]["SHELF_S3"], len(r["evidence"]))
    assert r["status"]=="ATM" and r["flags"]["SHELF_S3"]
    # 5.02 8-K 는 후보에서 제외되어야 함
    assert len(sec.select_candidates(sec.recent_filings(c.submissions(1),1), today))==2
    # clean
    r = sec.assess(Fake([f(2,"8-K",10,"1.01")], {"000102":"supply agreement for widgets"}), conn, "BBB")
    assert r["status"]=="CLEAN", r
    # fetch fail -> UNKNOWN (not CLEAN)
    r = sec.assess(Fake([f(5,"424B5",10)], {"000105":"FAIL"}), conn, "CCC")
    assert r["status"]=="UNKNOWN" and r["flags"]["PARTIAL_CHECK"], r
    # fetch fail but hit elsewhere -> hit wins
    r = sec.assess(Fake([f(5,"424B5",10), f(6,"8-K",9,"1.01")], {"000105":"FAIL","000106":"convertible note financing"}), conn, "DDD")
    assert r["status"]=="CB", r
    # submissions failure / no CIK
    assert sec.assess(Fake([],{},fail=True), conn, "EEE")["status"]=="UNKNOWN"
    assert sec.assess(Fake([],{}), conn, "NOCIK")["status"]=="UNKNOWN"
    # old ATM (>730d) ignored; 424B4 recent -> OFFERING
    r = sec.assess(Fake([f(7,"424B4",20)], {"000107":"final prospectus"}), conn, "FFF")
    assert r["status"]=="OFFERING", r
    # cache: second call must not refetch
    class NoFetch(Fake):
        def fetch_text(self, url): raise AssertionError("refetched")
    r = sec.assess(NoFetch(filings, texts), conn, "AAA"); assert r["status"]=="ATM"
print("sec OK")

# 3. market.compute_metrics
idx = pd.bdate_range(end=pd.Timestamp.today().normalize()-pd.Timedelta(days=1), periods=45)[-40:]
assert len(idx)==40, len(idx)
rng = np.random.default_rng(0)
close = np.linspace(2.0, 1.0, 40)
daily = pd.DataFrame({"Open":close,"High":close*1.05,"Low":close*0.95,"Close":close,"Volume":rng.integers(1e6,2e6,40)}, index=idx)
iidx = pd.date_range(pd.Timestamp.today().normalize().tz_localize("America/New_York")+pd.Timedelta(hours=4), periods=60, freq="min")
ic = np.linspace(1.0, 0.8, 60) + rng.normal(0,0.002,60)
intra = pd.DataFrame({"Open":ic,"High":ic*1.002,"Low":ic*0.998,"Close":ic,"Volume":rng.integers(1e4,5e4,60)}, index=iidx)
m = market.compute_metrics(daily, intra)
print({k: (round(v,3) if isinstance(v,float) else v) for k,v in m.items()})
assert m["drawdown_pct"] < -12 and 0 <= m["buy_pressure"] <= 100 and m["atr14"] > 0
m2 = market.compute_metrics(daily, None); assert m2["price"]==close[-1]
# batch splitter
multi = pd.concat({"AAA": daily, "BBB": daily}, axis=1)
assert set(market._split(multi, ["AAA","BBB","ZZZ"])) == {"AAA","BBB"}

# 4. scoring
q, qd = scoring.quant_score(m, 8e6, "CLEAN", {}); p, pd_, ex = scoring.pump_checklist(m, 8e6, "CLEAN", {})
print("q", q, qd, "p", p, ex)
assert 0 <= q <= 100 and not ex
assert scoring.pump_checklist(m, 8e6, "ATM", {})[2] is True
assert scoring.quant_score(m, 8e6, "ATM", {})[0] < q
e, s, t = scoring.reference_levels(1.0, 0.1); assert s < e < t
assert scoring.baby_shelf(10e6, 2.0)["is_baby_shelf"] and not scoring.baby_shelf(100e6, 2.0)["is_baby_shelf"]

# 5. scanner.run_cycle with patched IO
names = ["AAA","BBB","CCC","ZZZ"]
market.download_daily = lambda tk, period="3mo", chunk=40: {t: daily for t in tk if t!="ZZZ"}
market.download_intraday = lambda tk: {t: intra for t in tk}
market.fetch_fundamentals = lambda t: {"name": t, "exchange": "NASDAQ", "float_shares": 8e6, "shares_out": 9e6, "market_cap": 1e7}
universe.get_universe = lambda *a, **k: (names, set(names))
sent = []
scanner.notify.send_telegram = lambda x: sent.append(x) or True
client = Fake([f(2,"8-K",10,"1.01")], {"000102":"supply agreement"})
with closing(db.connect()) as conn:
    n1 = scanner.run_cycle(conn, client)
    n2 = scanner.run_cycle(conn, client)    # 같은 날 두 번째 사이클: 중복 행이 생기면 안 됨
    cnt = conn.execute("SELECT COUNT(*) FROM daily_snapshots").fetchone()[0]
    sig = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    print("saved", n1, n2, "snapshots", cnt, "signals", sig, "alerts", len(sent))
    assert n1==3 and cnt==3 and sig==3, (cnt, sig)
    assert conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0] == 3*40

# 6. analytics: 신호일 다음 거래일 가격이 있도록 스냅샷 날짜를 과거로 이동
with closing(db.connect()) as conn:
    d0 = idx[-10].strftime("%Y-%m-%d")
    conn.execute("UPDATE daily_snapshots SET date=? ", (d0,)); conn.commit()
fr = analytics.forward_returns(); print(fr.head(3).to_string())
assert fr["fwd_5d"].notna().all()
print(analytics.summarize(fr, "dilution_status").iloc[:, :6].to_string())
print("ALL OK")
print(os.environ["QUANT_DB"])
