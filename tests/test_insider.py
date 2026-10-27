import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from datetime import date
import db, insider
db.init_db()
D = date.today().isoformat()
X = f"""<?xml version="1.0"?><ownershipDocument><issuer><issuerCik>0001</issuerCik><issuerTradingSymbol>MDCX</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>Bokhari Raza</rptOwnerName></reportingOwnerId><reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>{D}</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>10000</value></transactionShares><transactionPricePerShare><value>3.25</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>150000</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>{D}</value></transactionDate><transactionCoding><transactionCode>A</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>5000</value></transactionShares><transactionPricePerShare><value>0</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
tx = insider.parse_form4(X); print(tx)
assert tx[0]["code"] == "P" and tx[0]["shares"] == 10000 and tx[0]["price"] == 3.25 and tx[0]["title"] == "이사 · CEO" and tx[0]["after"] == 150000 and tx[1]["code"] == "A"
assert insider.parse_form4("bad") == []
ATOM = f"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>4 - Medicus Pharma Ltd. (0001997296) (Issuer)</title><link href="https://www.sec.gov/Archives/edgar/data/1997296/000199729626000010/0001997296-26-000010-index.htm"/><id>urn:tag:sec.gov,2008:accession-number=0001997296-26-000010</id></entry>
<entry><title>4 - Bokhari Raza (0002000001) (Reporting)</title><link href="u"/><id>urn:tag:sec.gov,2008:accession-number=0001997296-26-000010</id></entry>
<entry><title>4 - Other Co (0000000009) (Issuer)</title><link href="u2"/><id>urn:tag:sec.gov,2008:accession-number=0000000009-26-1</id></entry></feed>"""
class FC:
    def _get(s, url, **kw):
        class R: pass
        r = R()
        r.text = ATOM if "getcurrent" in url else (X if url.endswith("form4.xml") else '<a href="/Archives/edgar/data/1997296/x/xslF345X05/form4.xml">h</a><a href="/Archives/edgar/data/1997296/x/form4.xml">r</a>')
        return r
c = FC()
assert insider.poll(c, {1997296: "MDCX"}) == 1 and insider.poll(c, {1997296: "MDCX"}) == 0          # 발행회사 기준 · 중복 없음
assert insider.enrich(c) == 1
b = insider.buys(30); assert list(b["ticker"]) == ["MDCX"] and b.iloc[0]["value"] == 32500.0         # 보상 지급(A)은 빠지고 매수(P)만
s = insider.summary_by_ticker(b).iloc[0]; assert s["총매수액"] == 32500.0 and abs(s["평단"] - 3.25) < 1e-9 and s["직책"] == "이사 · CEO"
print("ALL OK")
import multisignal; assert "내부자 매수" in multisignal.collect().get("MDCX", [])
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ["QUANT_TEST_PAGE"] = "insider"
import halts; halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
from contextlib import closing
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": D, "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -40.0,
        "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
        "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert any("스캐너 대상이 아닌 1종목 숨김" in c.value for c in at.caption)   # '초소형주만'(기본 켜짐): 스캐너가 본 적 없는 MDCX 는 숨김
at.toggle(key="in_small").set_value(False).run(); assert not at.exception                      # 끄면 전부
card = [m.value for m in at.markdown if 'class="qk-tk"' in m.value][0]; assert "MDCX" in card and "총 &#36;32,500" in card and "Bokhari Raza" in card and "이사 · CEO" in card
os.environ.pop("QUANT_TEST_PAGE"); print("UI OK")
