import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, pumpsetup as ps, shortdata
db.init_db()
DOCS = {
 "0001": "NOTICE OF EXTRAORDINARY GENERAL MEETING. Proposal 1: to approve a share consolidation of the Company's issued ordinary shares. Proposal 2: to approve that the authorized share capital of the Company be increased.",
 "0002": "PROSPECTUS. The Company is an exempted company incorporated in the Cayman Islands. We are offering units, each consisting of one ordinary share and one warrant to purchase one ordinary share. H.C. Wainwright & Co. is acting as placement agent.",
 "0003": "Current report. Item 4.02 Non-reliance on previously issued financial statements.",
 "0004": "Securities purchase agreement with Yorkville Advisors for an equity purchase agreement up to $10 million.",
}
F = [("0001", "6-K", "2026-09-20", ""), ("0002", "F-1", "2026-09-01", ""), ("0003", "8-K", "2026-10-01", "4.02"), ("0005", "10-Q", "2026-08-10", "")]
class FS:
    def __init__(s, incs=("E9", "Cayman Islands"), extra=()): s.inc, s.F, s.fetched = incs, list(F) + list(extra), []
    def cik_for(s, t): return None if t == "NOCIK" else 5
    def submissions(s, c):
        rec = {"accessionNumber": [x[0] for x in s.F], "primaryDocument": ["d.htm"] * len(s.F), "form": [x[1] for x in s.F], "filingDate": [x[2] for x in s.F], "items": [x[3] for x in s.F]}
        return {"stateOfIncorporation": s.inc[0], "stateOfIncorporationDescription": s.inc[1], "filings": {"recent": rec}}
    def fetch_text(s, url, limit=600000):
        s.fetched.append(url); return DOCS.get(url.split("/")[-2], "nothing relevant here")
today = date(2026, 10, 15)
with closing(db.connect()) as conn:
    fs = FS()
    r = ps.analyze(fs, conn, "EWPL", today=today, shares_out=3e6, dark={"dark_pct": 62.0, "days": 5}, short={"borrow_avail": 400000.0, "borrow_fee": 3.0})
    sig = {s["신호"]: s["결과"] for s in r["signals"]}; print(r["verdict"], r["plus"], r["minus"], r["counterparties"]); print(json.dumps(sig, ensure_ascii=False, indent=0)[:900])
    assert sig["병합 안건 + 수권주식 증액이 함께(자본 재구성 = 대규모 희석 예고)"] and sig["수권주식(수권자본) 증액 안건·승인"] and sig["병합(역분할) 안건·승인"]
    assert sig["주식 수가 적은데 병합 안건(가장 확실한 증거)"] and sig["설립지 케이맨 제도·영국령 버진아일랜드"] and sig["F-1(S-1) 등록서류가 보통주+워런트 구조"]
    assert sig["조달 상대방 1곳(세력 1집단 추정)"] and r["counterparties"] == ["H.C. Wainwright"] and sig["흔적: 대차 넉넉 + 다크풀(장외) 비중 50% 이상"]
    assert sig["최근 90일 8-K 악재(물량 떠넘기기 주의)"] and r["negatives"][0]["name"] == "재무제표 신뢰 불가(정정)" and not sig["ATM·ELOC(시장가 희석) — 피할 것"]
    assert r["plus"] == 8 and r["minus"] == 1 and r["verdict"] == "주의 — 악재·상대방 혼재"                     # 악재가 있으면 셋업이 강해도 '주의'
    n = len(fs.fetched); ps.analyze(fs, conn, "EWPL", today=today); assert len(fs.fetched) == n                # 공시 본문은 캐시(다시 안 읽음)
    # 두 번째 조달 상대방(ELOC 투자자) 추가 → 상대방 2곳 + ELOC → 피함
    fs2 = FS(extra=[("0004", "8-K", "2026-09-25", "1.01")])
    r2 = ps.analyze(fs2, conn, "EWPL", today=today)
    s2 = {s["신호"]: s["결과"] for s in r2["signals"]}; assert s2["조달 상대방 2곳 이상(이해관계 혼재)"] and s2["ATM·ELOC(시장가 희석) — 피할 것"] and r2["verdict"].startswith("피함")
    # 설립지 코드가 없으면 본문(F-1 표지)으로 보조 판정 / 미국 회사는 아님
    r3 = ps.analyze(FS(incs=("", "")), conn, "EWPL", today=today); assert r3["incorporation"] == "Cayman Islands"
    r4 = ps.analyze(FS(incs=("DE", "Delaware")), conn, "EWPL", today=today); assert r4["incorporation"] == "Cayman Islands"   # 문서에 케이맨 설립 문장이 있으면 그걸 씀
    assert ps.analyze(FS(), conn, "NOCIK")["error"].startswith("SEC CIK 없음")
    # 흔적: 대차 정보 없으면 판정 불가(None), 다크풀 낮으면 False
    r5 = ps.analyze(fs, conn, "EWPL", today=today, dark={"dark_pct": 30.0, "days": 5}, short={"borrow_avail": 400000.0})
    assert {s["신호"]: s["결과"] for s in r5["signals"]}["흔적: 대차 넉넉 + 다크풀(장외) 비중 50% 이상"] is False
    assert {s["신호"]: s["결과"] for s in ps.analyze(fs, conn, "EWPL", today=today)["signals"]}["흔적: 대차 넉넉 + 다크풀(장외) 비중 50% 이상"] is None
    # 다크풀 비율: FINRA 장외 거래량 ÷ Yahoo 전체 거래량
    shortdata.ensure_tables(conn)
    for d, tot in (("2026-10-13", 600.0), ("2026-10-14", 500.0)):
        conn.execute("INSERT INTO finra_shvol (date, symbol, short, exempt, total) VALUES (?,?,?,?,?)", (d, "EWPL", 100.0, 0.0, tot))
    conn.commit()
    df = pd.DataFrame({"Volume": [1000.0, 1000.0]}, index=pd.to_datetime(["2026-10-13", "2026-10-14"]))
    ds = ps.dark_stats(conn, "EWPL", df); assert ds == {"dark_pct": 55.0, "days": 2}
    assert ps.dark_stats(conn, "EWPL", None) is None
    # 저장·첫 분석 기록
    ps.save(conn, "EWPL", r, price=1.5); ps.save(conn, "EWPL", r2, price=2.0)
    assert ps.cached(conn, "EWPL")[1]["verdict"].startswith("피함") and conn.execute("SELECT price FROM setup_first WHERE ticker='EWPL'").fetchone()["price"] == 1.5   # 첫 분석 가격은 유지
print("ALL OK")
