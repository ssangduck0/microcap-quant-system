import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import json, db, listing, watch, shares, pressure
db.init_db(); watch.ensure_tables()
T = ("Item 3.01 Notice of Delisting. On September 25, 2026, HUB Cyber Security Ltd. received a letter from the Listing Qualifications Department of The Nasdaq Stock Market "
     "notifying the Company that its Market Value of Listed Securities (MVLS) was below the $35 million minimum requirement. The Company has until March 22, 2027 to regain compliance.")
p = listing.parse(T, "2026-09-25"); print(p)
assert p["kinds"][0] == "상장증권 시가총액 기준" and p["threshold"] == "$35M" and p["deadline"] == "2027-03-22" and not p["deadline_est"]
b = listing.parse("The Company received notice that its closing bid price was below $1.00 for 30 consecutive business days.", "2026-10-01")
assert b["kinds"] == ["주가 $1 기준"] and b["deadline"] == "2027-03-30" and b["deadline_est"]                # 기한 문구 없으면 +180일 추정
assert listing.parse("Item 8.01 Other events.", "2026-10-01") is None
# 본문 전체가 아니라 Item 3.01 구간만 본다: 뒤에 붙는 상용구(Form 10-K 참조·감사위원회·연례 주총)는 통지 종류로 잡히면 안 된다
B = ("FORM 8-K. Item 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; Transfer of Listing. On October 1, 2026, the Company received a letter from "
     "The Nasdaq Stock Market LLC notifying the Company that the closing bid price of its common stock was below $1.00 for 30 consecutive business days (Listing Rule 5550(a)(2)). "
     "The Company has until March 30, 2027 to regain compliance. Item 9.01 Financial Statements and Exhibits. Forward-Looking Statements: factors are described in the Company's "
     "Annual Report on Form 10-K and Quarterly Reports on Form 10-Q and its ability to timely file periodic reports. The audit committee and independent directors reviewed this report. "
     "The Company expects to hold its annual meeting of stockholders in June 2027. SIGNATURES Pursuant to the requirements of the Securities Exchange Act.")
q = listing.parse(B, "2026-10-01")
assert q["kinds"] == ["주가 $1 기준"] and q["deadline"] == "2027-03-30" and not q["deadline_est"], q
assert listing.parse("Risks are described in our Annual Report on Form 10-K. The audit committee met.", "2026-10-01") is None          # 통지 없는 글
f = listing.parse("The Company failed to timely file its Form 10-Q and received a notice from Nasdaq under Rule 5250(c)(1).", "2026-10-01")
assert f["kinds"] == ["정기보고서 지연"]                                                                                                # 진짜 지연 통지는 잡힘
assert listing.parse("Item 3.01. The Company received a notice from Nasdaq regarding its stockholders' equity requirement. The Company previously received a bid price notice.", "2026-10-01")["kinds"][0] == "자기자본 기준"  # 먼저 나온 기준이 주 통지
# 소문자 본문(서버 fetch_text)에서도 기한 날짜가 읽혀야 한다(안 그러면 전부 +180일 추정)
lo = listing.parse(B.lower(), "2026-10-01"); assert lo["deadline"] == "2027-03-30" and not lo["deadline_est"] and lo["kinds"] == ["주가 $1 기준"], lo
# 공시 목록에서 본문 8-K 고르기: iXBRL 본문(/ix?doc=)이 첨부보다 뒤에 있어도 본문을 고른다
IDX = ('<table><tr><td>1</td><td>EX-10.1</td><td><a href="/Archives/edgar/data/1/000/ex101.htm">ex101.htm</a></td><td>EX-10.1</td></tr>'
       '<tr><td>2</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/000/form8k.htm">form8k.htm</a></td><td>8-K</td></tr></table>')
assert listing.main_doc(IDX) == "/Archives/edgar/data/1/000/form8k.htm"
assert listing.main_doc('<a href="/Archives/edgar/data/1/000/only.htm">x</a>') == "/Archives/edgar/data/1/000/only.htm" and listing.main_doc("<p>none</p>") is None
# '기준 회복 완료' 8-K 는 통지가 아니고, 회복 못 해 새 통지를 받은 건 통지
assert listing.parse("Item 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; Transfer of Listing. By letter dated September 2, 2026, Nasdaq notified the Company that the closing bid price had been at $1.00 or greater for 10 consecutive business days and accordingly the Company has regained compliance with Listing Rule 5550(a)(2).", "2026-09-03") is None
nn = listing.parse("Item 3.01. As of September 15, 2026 the Company had not regained compliance with the minimum bid price requirement. On September 15, 2026 the Company received a new letter from Nasdaq that its common stock will be subject to delisting unless it requests a hearing before the Hearings Panel by September 22, 2026.", "2026-09-18")
assert nn and nn["kinds"][0] == "주가 $1 기준" and nn["deadline"] == "2026-09-22", nn
# 주주 승인 규정(5635) 위반 통지
assert listing.parse("Item 3.01. On September 10, 2026 the Company received a notification letter from Nasdaq indicating that the Company is not in compliance with Nasdaq Listing Rule 5635(d), which requires prior shareholder approval.", "2026-09-15")["kinds"] == ["주주 승인 규정 위반"]
# '불이행 시 청문 신청 가능' 가정 문구는 상장폐지 종류가 아니고, 실제 결정은 잡히되 주 통지는 기준 쪽
h = listing.parse("Item 3.01. If the Company does not regain compliance, Nasdaq will provide written notification that its securities are subject to delisting, at which time the Company may appeal to a Hearings Panel. "
                  "The letter stated that the market value of listed securities was below the $35 million minimum requirement.", "2026-10-01")
assert h["kinds"] == ["상장증권 시가총액 기준"] and h["threshold"] == "$35M", h
h2 = listing.parse("Item 3.01. On October 2, 2026 the Company received a Staff Determination letter from Nasdaq to delist its securities because its stockholders' equity requirement was not met. The Company intends to request a hearing.", "2026-10-02")
assert h2["kinds"] == ["자기자본 기준", "상장폐지 결정·청문"] and h2["threshold"] == "$2.5M", h2
fut = (date.today() + timedelta(days=40)).isoformat()
listing.save("HUBC", "acc1", date.today().isoformat(), "u", {**p, "deadline": fut})
assert any(e.kind == "상장유지 기한" and e.date == fut for e in watch.events_df(["HUBC"]).itertuples())
# void(통지 아님) 표시된 건은 latest 에서 빠진다
listing.save("VOIDX", "v1", date.today().isoformat(), "u", {**p, "deadline": fut})
assert listing.latest("VOIDX")
with closing(db.connect()) as conn:
    conn.execute("UPDATE listing_notices SET void=1 WHERE accession='v1'"); conn.commit()
assert listing.latest("VOIDX") is None and listing.latest("HUBC")
# 3.01 구간이 '다른 항목 참조' 한 줄뿐이면 본문의 통지 문장을 본다(ONFO)
X = ("Item 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; Transfer of Listing. To the extent required by Item 3.01 of Form 8-K, the information contained in Item 8.01 is incorporated herein. "
     "Item 8.01 Other Events. On October 6, 2026, the Company received a letter from Nasdaq notifying the Company that its stockholders' equity of $1.2 million was below the $2.5 million minimum requirement. The Company has until November 20, 2026 to submit a plan.")
x = listing.parse(X, "2026-10-07"); assert x["kinds"] == ["자기자본 기준"] and x["deadline"] == "2026-11-20", x
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "HUBC", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.33, "high_20d": 1.9, "low_20d": 0.3,
        "drawdown_pct": -80.0, "day_change_pct": -5.0, "volume_mult": 4.6, "buy_pressure": 55.0, "float_shares": 9e9, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.execute(shares.DDL); conn.execute("INSERT INTO shares_info VALUES ('HUBC', ?, ?)", (json.dumps({"adjusted": 2.1e6, "asof": "2026-08-12", "splits_after": [{"date": "2026-09-15", "ratio": 0.04}], "warn": True}), now)); conn.commit()
    r = pressure.evaluate("HUBC", conn, None, None); print(r["parts"], r["targets"])
assert "상장유지(상장증권 시가총액)" in r["parts"] and r["parts"]["상장유지(상장증권 시가총액)"] == 3 and r["shares"] == 2.1e6 and "SEC 표지" in r["shares_tag"]
mv = [x for x in r["targets"] if x[0] == "시가총액 기준 회복"][0]; assert abs(mv[1] - 35e6 / 2.1e6) < 1e-9                     # $16.67 필요
assert any("상장증권 시가총액 기준 미달 통지" in p[1] and "D-40" in p[1] for p in r["press"])
print("ALL OK")
