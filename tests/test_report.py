import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from datetime import date, timedelta
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, sec, market, report
db.init_db()
today = date.today()
d = lambda n: (today - timedelta(days=n)).isoformat()

FORM4 = """<?xml version="1.0"?><ownershipDocument>
<reportingOwner><reportingOwnerId><rptOwnerName>Teoh Pui Pui</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>true</isOfficer><officerTitle>Co-CEO</officerTitle><isTenPercentOwner>0</isTenPercentOwner></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable>
<nonDerivativeTransaction><transactionDate><value>2026-09-05</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>2950</value></transactionShares><transactionPricePerShare><value>3.96</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>231741</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>2026-09-06</value></transactionDate>
<transactionCoding><transactionCode>A</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>100000</value></transactionShares><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>"""
rows = parse = report.parse_form4(FORM4)
assert len(rows)==2 and rows[0]["code"]=="P" and rows[0]["shares"]==2950 and rows[0]["price"]==3.96
assert "Co-CEO" in rows[0]["role"] and "이사" in rows[0]["role"] and rows[1]["price"] is None
print("form4 parse OK")

COMPANYFACTS = {"facts": {"us-gaap": {
  "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
      {"end":"2025-12-31","val":3480000,"accn":"0001-25-1","form":"10-K"},
      {"end":"2026-06-30","val":2100000,"accn":"0001-26-2","form":"10-Q"}]}},
  "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
      {"start":"2025-01-01","end":"2025-12-31","val":-4360000,"accn":"0001-25-1","form":"10-K"},
      {"start":"2026-01-01","end":"2026-06-30","val":-1800000,"accn":"0001-26-2","form":"10-Q"},
      {"start":"2026-04-01","end":"2026-06-30","val":-900000,"accn":"0001-26-2","form":"10-Q"}]}}}}}
class Fake(sec.SecClient):
    def __init__(s, texts=None): s.texts = texts or {}; s.fetched=[]
    def cik_for(s,t): return None if t=="NOCIK" else 123
    def submissions(s,cik):
        rec = {"accessionNumber":[], "primaryDocument":[], "form":[], "filingDate":[], "items":[]}
        for acc, doc, form, dt, items in [
            ("0001-01","a.htm","424B5",d(30),""), ("0001-02","b.htm","8-K",d(60),"1.01,9.01"),
            ("0001-03","c.htm","8-K",d(200),"3.01"), ("0001-04","d.htm","S-3",d(100),""),
            ("0001-05","xslF345X05/f4.xml","4",d(40),""), ("0001-06","e.htm","8-K",d(400),"3.02")]:
            rec["accessionNumber"].append(acc); rec["primaryDocument"].append(doc); rec["form"].append(form)
            rec["filingDate"].append(dt); rec["items"].append(items)
        return {"filings":{"recent":rec}}
    def companyfacts(s,cik): return COMPANYFACTS
    def fetch_text(s,url):
        s.fetched.append(url)
        key = url.split("/")[-2]
        return sec.html_to_text(s.texts.get(key, "nothing"))
    def fetch_raw(s,url,limit=0):
        s.fetched.append(url)
        assert "xsl" not in url, url          # Form 4 는 xsl 폴더 밖 원본 XML 이어야 함
        return FORM4

idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=522)[-520:]
rng = np.random.default_rng(3)
close = np.linspace(5.0, 0.9, len(idx))
vol = rng.integers(1e5, 2e5, len(idx)).astype(float)
vol[-30] = 4e6      # 거래량 폭발일(5배 이상)
df = pd.DataFrame({"Open":close,"High":close*1.04,"Low":close*0.96,"Close":close,"Volume":vol}, index=idx)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: df for t in tk}
market.fetch_fundamentals = lambda t: {"name":"Mobile Health","exchange":"NASDAQ","float_shares":560000,"shares_out":2.3e6,"market_cap":3.5e6}
market.fetch_splits = lambda t: [{"date":"2026-06-29","ratio":1/6,"text":"1:6 역분할"},{"date":"2025-09-25","ratio":0.2,"text":"1:5 역분할"}]

c = Fake({"000101": "prospectus supplement at-the-market offering sales agent", "000102": "convertible note financing"})
with closing(db.connect()) as conn:
    rep = report.build_report(c, conn, "MNDR", today)
print("errors:", rep["errors"])
assert not rep["errors"], rep["errors"]
co = rep["company"]; assert co["float_ratio"] < 30 and len(co["splits"])==2 and len(co["delisting_notices"])==1
assert co["volume_spikes"], "거래량 폭발일 미검출"
fin = rep["financing"]; kinds = [tuple(e["tags"]) for e in fin["events"]]
print("financing:", kinds, fin["summary"])
assert ("ATM",) in kinds and ("CB",) in kinds and ("REGISTRATION",) in kinds
assert fin["summary"]["count"]==2 and "median_gap_days" in fin["summary"]
atm = [e for e in fin["events"] if e["tags"]==["ATM"]][0]; assert "pre20_pct" in atm and "after5_pct" in atm
rw = rep["runway"]; print("runway:", rw)
assert rw["cash"]==2100000 and rw["cash_asof"]=="2026-06-30"
assert abs(rw["monthly_burn"]-900000/ (90/30.44) ) < 1 or abs(rw["monthly_burn"]-1800000/6) < 20000   # 최신 종료일, 긴 기간 우선
assert rw["runway_months"] > 0
ins = rep["insiders"]; assert ins["summary"]["open_market_buys"]==1 and ins["errors"]==0
types = {t["type"] for t in rep["timeline"]}; print("timeline types", types)
assert {"분할","상장유지","거래량","조달","내부자"} <= types
# NOCIK: SEC 섹션만 실패하고 회사 섹션은 생성
with closing(db.connect()) as conn:
    r2 = report.build_report(Fake(), conn, "NOCIK", today)
assert "sec" in r2["errors"] and r2["company"] is not None and "runway" not in r2
# 런웨이 데이터 없음 -> 에러 격리
class NoFacts(Fake):
    def companyfacts(s,cik): return {"facts":{}}
with closing(db.connect()) as conn:
    r3 = report.build_report(NoFacts(), conn, "MNDR", today)
assert "runway" in r3["errors"] and r3["financing"] is not None
db.save_report("MNDR", rep); assert db.get_report("MNDR")["ticker"]=="MNDR"
db.save_note("MNDR","메모1"); assert db.get_note("MNDR")=="메모1"
print("REPORT OK")
print(os.environ["QUANT_DB"])
