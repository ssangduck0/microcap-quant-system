import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, watch, sec
db.init_db(); watch.ensure_tables()
approx = lambda a, b, tol=1e-9: a is not None and abs(a - b) < tol
# ---------- 1) 공시 문장 추출 ----------
T8K = ("On October 9, 2026, the Company entered into a securities purchase agreement pursuant to which it agreed to sell 2,500,000 shares of its common stock "
       "at a purchase price of $1.20 per share, together with warrants to purchase up to 2,500,000 shares of common stock at an exercise price of $1.45 per share. "
       "The Company also issued pre-funded warrants to purchase up to 1,000,000 shares. The warrants will expire on October 9, 2031. "
       "Each of the directors agreed to a lock-up of 90 days. The convertible promissory note has a conversion price of $0.85 per share. "
       "The Company received a letter stating it has until April 6, 2027 to regain compliance with the minimum bid price requirement.")
over, evs = watch.extract(T8K, "8-K", "2026-10-09", "https://sec.gov/x")
k = {(o["kind"], o["qty_m"], o["price"]) for o in over}; print(sorted(k, key=str))
assert ("워런트", 2.5, 1.45) in k and ("선지급 워런트", 1.0, 0.0001) in k and ("전환사채", None, 0.85) in k and ("공모 주식", 2.5, 1.2) in k
assert not any(o["kind"] == "워런트" and o["qty_m"] == 1.0 for o in over)                         # 선지급 워런트를 일반 워런트로 중복 인식하지 않음
assert all(o["source"] == "https://sec.gov/x" and o["snippet"] for o in over)
ek = {(e["kind"], e["date"]) for e in evs}; print(sorted(ek))
assert ("워런트 만기", "2031-10-09") in ek and ("상장유지 기한", "2027-04-06") in ek and ("락업 해제(추정)", "2027-01-07") in ek
TATM = "We have entered into an at-the-market sales agreement under which we may sell shares having an aggregate offering price of up to $25.5 million from time to time."
o2, _ = watch.extract(TATM, "8-K", "2026-10-01", "u"); assert o2 and o2[0]["kind"] == "ATM" and o2[0]["note"] == "한도 $25.5M" and o2[0]["qty_m"] is None
TPX = ("The annual meeting of stockholders will be held on Thursday, December 4, 2026 at 10:00 a.m. The reverse stock split will become effective at 12:01 a.m. "
       "Eastern Time on Nov. 3, 2026. A special meeting of shareholders is scheduled for, on Sept. 15, 2026.")
_, e3 = watch.extract(TPX, "DEF 14A", "2026-10-01", "u"); ek3 = {(e["kind"], e["date"]) for e in e3}; print(ek3)
assert ("주총", "2026-12-04") in ek3 and ("역분할 시행", "2026-11-03") in ek3 and ("임시주총", "2026-09-15") in ek3
assert watch.parse_date("Sept. 5, 2026") == date(2026, 9, 5) and watch.parse_date("Foo 1, 2026") is None
o4, _ = watch.extract("warrants to purchase 500 shares at an exercise price of $1.00", "8-K", "2026-10-01", "u"); assert o4 == []   # 너무 작은 수량은 제외(오탐 방지)
print("extract OK")
# ---------- 2) 물량 요약 ----------
rows = [{"kind": "워런트", "qty_m": 2.5, "price": 1.45, "status": "활성"}, {"kind": "선지급 워런트", "qty_m": 1.0, "price": 0.0001, "status": "활성"},
        {"kind": "워런트", "qty_m": 3.0, "price": 4.0, "status": "활성"}, {"kind": "ATM", "qty_m": None, "price": None, "status": "활성", "note": "한도 $25.5M"},
        {"kind": "사모(PIPE)", "qty_m": 5.0, "price": 1.0, "status": "잠김"}, {"kind": "워런트", "qty_m": 9.0, "price": 0.5, "status": "소멸"},
        {"kind": "전환사채", "qty_m": None, "price": 0.85, "status": "확인 필요"}]
s = watch.overhang_summary(rows, 1.30); print(s)
assert approx(s["below_m"], 1.0) and approx(s["above_m"], 5.5) and s["next_price"] == 1.45 and approx(s["next_dist_pct"], (1.45 / 1.30 - 1) * 100)
assert s["no_price"] == ["ATM (한도 $25.5M)"] and s["locked_m"] == 5.0 and s["pending"] == 1 and s["n_active"] == 4
s2 = watch.overhang_summary(rows, 5.0); assert approx(s2["below_m"], 6.5) and s2["above_m"] == 0 and s2["next_price"] is None
assert watch.overhang_summary(rows, None)["below_m"] is None
print("overhang OK")
# ---------- 3) $1 연속 일수 ----------
df = pd.DataFrame({"Close": [0.8, 0.9, 1.0, 1.1, 1.05]}); assert watch.dollar_streak(df) == {"above": 3, "below": 0}
df2 = pd.DataFrame({"Close": [1.2, 0.95, 0.9]}); assert watch.dollar_streak(df2) == {"above": 0, "below": 2}
assert watch.dollar_streak(None) == {"above": None, "below": None}
assert watch.trading_days_between(date(2026, 10, 9), date(2026, 10, 14)) == 3 and watch.trading_days_between(date(2026, 10, 14), date(2026, 10, 14)) == 0
print("streak OK")
# ---------- 4) 워치리스트·장부·일정 저장 ----------
watch.add("aaa", "관심", 1.10, "메모1"); watch.add("BBB", "블랙"); watch.add("CCC", "보유", 2.0)
assert watch.lists_map() == {"AAA": "관심", "BBB": "블랙", "CCC": "보유"} and set(watch.scanner_priority()) == {"AAA", "CCC"}
watch.add("AAA", "보유"); a = watch.all_items().set_index("ticker").loc["AAA"]; assert a["list"] == "보유" and a["added_price"] == 1.10 and a["note"] == "메모1"   # 다시 추가해도 추가가·메모 유지
watch.update("AAA", note="새 메모"); assert watch.all_items().set_index("ticker").loc["AAA", "note"] == "새 메모"
assert list(watch.all_items()["ticker"]) == ["AAA", "CCC", "BBB"]                                   # 보유 → 관심 → 그레이 → 블랙
watch.remove("CCC"); assert "CCC" not in watch.lists_map()
assert watch.add_overhang("AAA", "워런트", 2.5, 1.45, source="u", origin="자동 후보") and not watch.add_overhang("AAA", "워런트", 2.5, 1.45, source="u", origin="자동 후보")   # 같은 자동 후보 중복 없음
watch.add_overhang("AAA", "ATM", None, None, note="한도 $25M")
ed = watch.overhang_rows("AAA"); ed.loc[ed["kind"] == "워런트", "status"] = "잠김"
ed = pd.concat([ed[ed["kind"] == "워런트"], pd.DataFrame([{"id": None, "kind": "전환사채", "qty_m": 4.0, "price": 0.8, "expiry": "", "status": "활성", "note": "새 행"}])], ignore_index=True)
watch.save_overhang_edits("AAA", ed)                                                                  # ATM 행 삭제, 워런트 상태 변경, 새 행 추가
r = watch.overhang_rows("AAA"); print(r[["kind", "qty_m", "price", "status", "origin"]].to_string(index=False))
assert set(r["kind"]) == {"워런트", "전환사채"} and r.set_index("kind").loc["워런트", "status"] == "잠김" and r.set_index("kind").loc["전환사채", "origin"] == "수동"
assert watch.add_event("AAA", "2026-10-20", "주총", "주총") and not watch.add_event("AAA", "2026-10-20", "주총", "주총")
watch.add_event("BBB", "2026-11-01", "기타", "x"); assert list(watch.events_df(["AAA"])["kind"]) == ["주총"] and len(watch.events_df(start="2026-10-25")) == 1
assert watch.events_df([]).empty
eid = int(watch.events_df(["AAA"]).iloc[0]["id"]); watch.delete_event(eid); assert watch.events_df(["AAA"]).empty
print("store OK")
# ---------- 5) 공시 스캔(가짜 SEC) ----------
class FakeSec:
    def __init__(s): s.fetched = []
    def cik_for(s, t): return None if t == "NOCIK" else 9
    def submissions(s, c):
        F = [("0001", "8-K", "2026-10-09", "1.01,3.02"), ("0002", "EFFECT", "2026-10-08", ""), ("0003", "424B5", "2026-10-07", ""), ("0004", "8-K", "2026-10-05", "3.01"),
             ("0005", "10-Q", "2026-08-10", ""), ("0006", "10-Q", "2026-05-10", ""), ("0007", "8-K", "2024-01-01", "")]
        rec = {"accessionNumber": [x[0] for x in F], "primaryDocument": ["d.htm"] * len(F), "form": [x[1] for x in F], "filingDate": [x[2] for x in F], "items": [x[3] for x in F]}
        return {"filings": {"recent": rec}}
    def fetch_text(s, url, limit=600_000):
        s.fetched.append(url)
        return T8K if "/0001/" in url or "0001" in url.split("/")[-2] else "quarterly report"
fs = FakeSec()
res = watch.scan_ticker(fs, "AAA", today=date(2026, 10, 14)); print(res)
assert res["docs"] == 4 and res["errors"] == 0 and res["new_overhang"] >= 4                                   # 8-K, 424B5, 8-K(3.01), 최근 10-Q 1건(오래된 10-Q·2년 전 공시 제외)
ev = watch.events_df(["AAA"]); kinds = set(ev["kind"]); print(sorted(kinds))
assert {"희석 임박", "발행", "상장유지 미달", "워런트 만기", "상장유지 기한", "락업 해제(추정)"} <= kinds
cand = watch.overhang_rows("AAA"); assert (cand["status"] == "확인 필요").sum() >= 4 and (cand["origin"] == "자동 후보").all() == False
n_before = len(watch.overhang_rows("AAA")); watch.scan_ticker(fs, "AAA", today=date(2026, 10, 14)); assert len(watch.overhang_rows("AAA")) == n_before   # 재스캔해도 중복 없음
assert watch.scan_ticker(fs, "NOCIK")["error"].startswith("SEC CIK 없음")
print("scan OK")
# ---------- 6) 랭크 ----------
snaps = pd.DataFrame([
    {"date": "2026-10-12", "ticker": "AAA", "win_score": 80, "quant_score": 50, "day_change_pct": -30, "drawdown_pct": -50, "price": 1.0, "dilution_status": "CLEAN"},
    {"date": "2026-10-13", "ticker": "AAA", "win_score": 60, "quant_score": 40, "day_change_pct": -12, "drawdown_pct": -55, "price": 0.9, "dilution_status": "CLEAN"},
    {"date": "2026-10-13", "ticker": "BBB", "win_score": 90, "quant_score": 70, "day_change_pct": -40, "drawdown_pct": -60, "price": 2.0, "dilution_status": "ATM"},
    {"date": "2026-10-09", "ticker": "OLD", "win_score": 99, "quant_score": 99, "day_change_pct": -50, "drawdown_pct": -70, "price": 3.0, "dilution_status": "CLEAN"}])
tracked = pd.DataFrame([{"date": "2026-10-12", "ticker": "AAA", "next_high_pct": 15.0, "next_close_pct": 3.0}])
r2 = watch.rank(snaps, tracked, 2); print(r2.to_string(index=False))
assert list(r2["ticker"]) == ["AAA", "BBB"] and r2.iloc[0]["발견일수"] == 2 and r2.iloc[0]["최고승률"] == 80 and r2.iloc[0]["최근가"] == 0.9 and r2.iloc[0]["다음날최고"] == 15.0
r1 = watch.rank(snaps, tracked, 1); assert list(r1["ticker"]) == ["BBB", "AAA"]                               # 일간: 최신 날짜만, 승률 점수 순
assert watch.rank(snaps.iloc[0:0], None, 5).empty
print("ALL OK")
