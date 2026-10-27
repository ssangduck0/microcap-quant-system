import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, fundscan as fs, shares, rsplit
db.init_db()
COVER = ("PROSPECTUS SUPPLEMENT. Smith Micro Software, Inc. We are offering 1,500,000 shares of our common stock and pre-funded warrants to purchase up to 300,000 shares "
         "together with Series A warrants to purchase up to 1,800,000 shares of common stock at an exercise price of $0.95 per share and Series B warrants to purchase up to 900,000 shares "
         "of common stock at an exercise price of $1.10 per share. The combined public offering price is $0.80 per share. We expect gross proceeds of approximately $1.44 million. "
         "H.C. Wainwright & Co. is acting as our exclusive placement agent.")
d = fs.parse_deal(COVER, "424B4"); print(d)
assert d["proceeds"] == 1.44e6 and d["unit_price"] == 0.80 and d["shares"] == 1_500_000 and d["pfw"] == 300_000 and d["agent"] == "H.C. Wainwright" and not d["resale"]
assert [(w["name"], w["qty"], w["price"]) for w in d["warrants"]] == [("Series A", 1_800_000, 0.95), ("Series B", 900_000, 1.10)]
assert fs.kind_of("424B3") == "재판매 등록" and fs.kind_of("8-K", "1.01,3.02") == "사모·PIPE 계약" and fs.is_deal("8-K", "3.02") and not fs.is_deal("10-Q", "")
# C단계: 등록서류도 딜 · 행사가 표현 확대 · AI 보조 후보 판정
assert fs.is_deal("S-3", "") and fs.is_deal("F-1/A", "") and fs.kind_of("S-1") == "증권 등록(S-1/F-1)" and fs.kind_of("F-3") == "선반 등록(S-3/F-3)"
C2 = ("We are offering 2,000,000 units, each consisting of one share and one warrant. The combined offering price per share and accompanying warrant is $1.25. "
      "The warrants to purchase up to 2,000,000 shares of common stock are exercisable immediately at an exercise price of $1.50 per share and expire five years from issuance.")
d2 = fs.parse_deal(C2, "424B4"); assert d2["unit_price"] == 1.25 and d2["warrants"] == [{"name": "Warrants", "qty": 2000000.0, "price": 1.5}], d2
C3 = "Series C warrants to purchase up to 5,500,000 shares of common stock. The exercise price per share of the Series C warrants will be $0.42. Purchase price of $0.40 per unit."
d3 = fs.parse_deal(C3, "8-K"); assert d3["warrants"][0]["price"] == 0.42 and d3["unit_price"] == 0.40, d3
assert fs._needs_ai("424B5", {"warrants": [], "unit_price": None}, "x" * 2000) and not fs._needs_ai("424B5", d2, "x" * 2000) and not fs._needs_ai("424B5", {"warrants": [], "unit_price": None}, "short")
CF = {"facts": {"us-gaap": {"ClassOfWarrantOrRightOutstanding": {"units": {"shares": [{"end": "2026-06-30", "val": 2_000_000, "filed": "2026-08-12"}]}},
                            "ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights1": {"units": {"USD/shares": [{"end": "2026-06-30", "val": 1.2, "filed": "2026-08-12"}]}}},
                "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-05-10", "val": 4_000_000, "filed": "2026-05-14", "accn": "a"},
                                                                                    {"end": "2026-08-12", "val": 5_800_000, "filed": "2026-08-14", "accn": "b"}]}}}}}
x = fs.xbrl(CF); assert x["warrants"]["val"] == 2e6 and x["wavg_price"]["val"] == 1.2 and x["shares_hist"] == [("2026-05-10", 4e6), ("2026-08-12", 5.8e6)]
T = date.today(); D = lambda n: (T - timedelta(days=n)).isoformat(); now = db.utcnow_iso()
with closing(db.connect()) as conn:
    fs.ensure_tables(conn)
    fs.save_deal(conn, "SMSI", "d1", "2026-06-15", "424B4", "", "u", d)
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "SMSI", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.75, "high_20d": 1.0, "low_20d": 0.7,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 9e9, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.execute("INSERT INTO fs_xbrl VALUES ('SMSI', ?, ?)", (json.dumps(x), now))
    conn.execute(shares.DDL); conn.execute("INSERT INTO shares_info VALUES ('SMSI', ?, ?)", (json.dumps({"adjusted": 5.8e6, "asof": "2026-08-12", "splits_after": [], "warn": False}), now))
    conn.commit()
db.save_report("SMSI", {"ticker": "SMSI", "generated_at": now, "errors": {}, "runway": {"runway_months": 3.6, "cash": 3.6e6, "monthly_burn": 1.0e6, "cash_asof": D(30)},
                        "company": {"splits": []}, "financing": {"events": []}, "timeline": []})
a = fs.analyze("SMSI"); print({k: a[k] for k in ("runway_now", "min_ex", "need", "money_in", "overhang", "dil_pct", "score", "label", "pressure", "grade", "cond")})
assert abs(a["runway_now"] - (3.6e6 - 1e6 * (30 / 30.4)) / 1e6) < 1e-6 and a["min_ex"] == 0.95 and abs(a["need"] - (0.95 / 0.75 - 1) * 100) < 1e-9
assert a["money_in"] == 1.8e6 * 0.95 + 0.9e6 * 1.10 and a["overhang"] == 1.8e6 + 0.9e6 + 3e5 and a["cond"] and a["label"] == "양면 신호" and a["score"] == 30 + 40   # 대기 물량 51.7% → 양면 and a["grade"] == "A"
assert a["share_change"]["before"] == 4e6 and a["share_change"]["increase"] == 1.8e6 and a["share_change"]["explained"] == 1.5e6 and abs(a["share_change"]["unknown"] - 3e5) < 1
assert "워런트 행사로" in a["sentence"] and "구조적으로" in a["sentence"]
# 병합 환산: 딜 뒤 1:5 병합 → 수량 ÷5 · 가격 ×5
with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('SMSI', '2026-07-01', 0.2, 1.0)"); conn.commit()
b = fs.analyze("SMSI"); assert abs(b["min_ex"] - 0.95 * 5) < 1e-9 and abs(b["warrants"][0]["qty"] - 1.8e6 * 0.2) < 1e-6 and b["adj_note"] and b["rs"]
assert [r["ticker"] for r in fs.scan()] == ["SMSI"]
# run(): 공시 해석 · 재무 갱신(가짜 SEC)
with closing(db.connect()) as conn:
    import secbackfill; secbackfill.ensure_tables(conn); conn.execute("INSERT INTO sec_hist VALUES ('d2','ABCD','424B5',?,'')", (D(10),)); conn.commit()
class FC:
    def cik_for(s, t): return 7
    def _get(s, url):
        class R: text = '<a href="/Archives/edgar/data/7/x/abcd424b5.htm">d</a>'
        return R()
    def fetch_text(s, url, limit=0): return COVER
    def companyfacts(s, cik): return CF
r = fs.run(FC(), out=lambda *_: None, ai_cap=0); assert r["deals"] == 1 and r["xbrl"] == 1 and r["ai"] == 0   # SMSI 재무는 7일 안이라 건너뜀 · AI 보조는 끔
with closing(db.connect()) as conn: assert conn.execute("SELECT kind FROM fs_deals WHERE accession='d2'").fetchone()[0] == "공모"
print("ALL OK")
