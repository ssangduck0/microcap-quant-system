import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, runway, report, pick30, fundscan
db.init_db()
T = date.today(); now_iso = db.utcnow_iso()
ago = lambda n: (T - timedelta(days=n)).isoformat()  # noqa: E731

# --- 최근 12개월(TTM): 계절성 회사가 한 분기 마이너스로 '현금 소진'이 되지 않게
def facts(fy, ytd, prior, cash=5e6):
    y0 = T.year - 1
    return {"facts": {"us-gaap": {
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": f"{T.year}-07-31", "val": cash, "form": "10-Q"}]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            {"start": f"{y0 - 1}-02-01", "end": f"{y0}-01-31", "val": fy, "filed": f"{y0}-04-01"},          # 연간
            {"start": f"{y0}-02-01", "end": f"{y0}-07-31", "val": prior, "filed": f"{y0}-09-01"},           # 작년 상반기
            {"start": f"{T.year}-02-01", "end": f"{T.year}-07-31", "val": ytd, "filed": f"{T.year}-09-01"}]}}}}}
seasonal = report.runway_from_facts(facts(12e6, -4e6, -5e6))      # 연간 +12, 올해 상반기 −4, 작년 상반기 −5 → TTM +13
assert seasonal["ocf_ttm"] == 13e6 and seasonal["monthly_burn"] == 0.0 and "최근 12개월" in seasonal["burn_basis"] and seasonal["v"] == 4, seasonal
assert seasonal["ocf"] == -4e6                                     # 예전 방식이었다면 월 0.67M 소진으로 잡혔을 값
burner = report.runway_from_facts(facts(-12e6, -8e6, -6e6))       # TTM −14 → 월 약 1.17M
assert abs(burner["monthly_burn"] - 14e6 / 12) < 1 and abs(burner["runway_months"] - 5e6 / (14e6 / 12)) < 1e-6, burner
no_prior = report.runway_from_facts({"facts": {"us-gaap": {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
    {"start": f"{T.year}-01-01", "end": f"{T.year}-06-30", "val": -6e6}]}}}}})
assert abs(no_prior["monthly_burn"] - 6e6 / ((date(T.year, 6, 30) - date(T.year, 1, 1)).days / 30.44)) < 1 and no_prior["burn_basis"] == "최근 보고 기간"   # 연간 없으면 예전 방식

# --- 단기 투자(국채·MMF): 같은 기준일 값만 현금에 더함(바이오 소형주 런웨이 과소 추정 방지)
cfi = {"facts": {"us-gaap": {
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": ago(60), "val": 2e6}]}},
    "ShortTermInvestments": {"units": {"USD": [{"end": ago(60), "val": 8e6}, {"end": ago(150), "val": 20e6}]}},
    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"start": ago(150), "end": ago(60), "val": -3e6}]}}}}}
ri = report.runway_from_facts(cfi)
assert ri["cash"] == 10e6 and ri["cash_only"] == 2e6 and ri["investments"] == 8e6 and 9.5 < ri["runway_months"] < 10.5, ri   # 현금만이면 약 2개월로 잘못 잡힘
assert "investments" not in report.runway_from_facts({"facts": {"us-gaap": {"CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": ago(60), "val": 2e6}]}},
    "ShortTermInvestments": {"units": {"USD": [{"end": ago(150), "val": 9e6}]}}}}})                                              # 기준일 다르면 안 더함

# --- SEC companyfacts → 현금·월 소모량
cf = {"facts": {"us-gaap": {
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": ago(400), "val": 9e6}, {"end": ago(60), "val": 6e6, "accn": "a1", "form": "10-Q"}]}},
    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"start": ago(150), "end": ago(60), "val": -3e6}]}}}}}
rw = report.runway_from_facts(cf)
assert rw["cash"] == 6e6 and rw["cash_asof"] == ago(60) and abs(rw["monthly_burn"] - 1e6) < 5e4, rw
assert report.runway_from_facts({"facts": {}}) == {"currency": None, "v": 4}   # 자료 없어도 예외 없이 빈 칸(버전만)

with closing(db.connect()) as conn:
    fundscan.ensure_tables(conn)
    runway.save(conn, "AAA", rw)                                                          # 6M, 월 1M, 60일 전 → 지금 약 4M · 약 4개월
    runway.save(conn, "BBB", {"cash": 1e6, "cash_asof": ago(90), "monthly_burn": 1e6})   # 소진 추정
    runway.save(conn, "CCC", {"cash": 5e6, "cash_asof": ago(60), "monthly_burn": 0.0})   # 흑자
    runway.save(conn, "DDD", {"cash": 1e6, "cash_asof": ago(400), "monthly_burn": 1e6})  # 오래된 재무
    runway.save(conn, "EEE", {"error": "x"})                                              # 자료 없음
    conn.execute("INSERT INTO fs_deals (accession, ticker, filed, form, kind, proceeds) VALUES ('x1','BBB',?,'424B4','공모',5e6)", (ago(10),))
    conn.commit()

    a = runway.now("AAA", conn); assert a["source"] == "SEC 재무" and 3.5 < a["runway_now"] < 4.5 and not a["exhausted"] and not a["stale"], a
    assert runway.label(a).startswith("런웨이 4.0개월") or runway.label(a).startswith("런웨이 3.9개월") or runway.label(a).startswith("런웨이 4.1개월"), runway.label(a)
    b = runway.now("BBB", conn); assert b["raised_after"] == 5e6 and b["runway_now"] > 2, b          # 그 뒤 조달 5M 반영
    b0 = runway.now("BBB", conn, deals=[]); assert b0["exhausted"] and b0["runway_now"] == 0 and "추정 현금 소진" in runway.label(b0), b0
    c = runway.now("CCC", conn); assert c["profitable"] and c["runway_now"] is None and "흑자" in runway.label(c), c
    d = runway.now("DDD", conn); assert d["stale"] and "오래됨" in runway.label(d), d
    runway.save(conn, "FFF", {"cash": 1e6, "cash_asof": ago(300), "monthly_burn": 1e5, "cash_source": {"form": "20-F"}}); conn.commit()
    f_ = runway.now("FFF", conn); assert f_["stale"] and runway.label(f_).startswith("해외 기업 연차 재무"), runway.label(f_)
    assert runway.now("EEE", conn) is None and runway.now("ZZZ", conn) is None and runway.label(None) == "런웨이 미확인"

    # 종목 리포트가 30일 안이면 리포트 우선
    db.save_report("AAA", {"ticker": "AAA", "runway": {"cash": 2e6, "cash_asof": ago(30), "monthly_burn": 1e6, "runway_months": 2.0}})
    assert runway.now("AAA", conn)["source"] == "SEC 재무"        # 예전 계산 방식 리포트(v 없음)보다 새 저장소 우선
    db.save_report("AAA", {"ticker": "AAA", "runway": {"cash": 2e6, "cash_asof": ago(30), "monthly_burn": 1e6, "runway_months": 2.0, "v": 4}})
    assert runway.now("AAA", conn)["source"] == "종목 리포트"

    # --- PICK: 펀드스캔 딜이 없어도 런웨이 저장소로 판정(예전엔 '런웨이 미확인')
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "BBB", "exchange": "NASDAQ", "first_seen": now_iso, "last_seen": now_iso, "price": 0.5, "high_20d": 0.55,
        "low_20d": 0.4, "drawdown_pct": -20.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 50.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0,
        "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
    tgt = {"targets": [("baby shelf 탈출", 0.9, "")], "score": 3}
    runway.save(conn, "BBB", {"cash": 1e6, "cash_asof": ago(30), "monthly_burn": 1e6}); conn.commit()   # 그 뒤 조달 5M → 약 5개월
    r = pick30.evaluate("BBB", conn, tgt, None)
    assert r["has_runway"] and r["runway"] is not None and r["imm_kind"] == "현금 바닥", r
    runway.save(conn, "BBB", {"cash": 9e6, "cash_asof": ago(30), "monthly_burn": 3e6}); conn.commit()   # 약 2개월(바닥 약 60일 뒤) → 런웨이 3개월↓ 라 가능
    conn.execute("DELETE FROM fs_deals WHERE ticker='BBB'"); conn.commit()
    r = pick30.evaluate("BBB", conn, tgt, None)
    assert r["status"] == "가능" and r["imm_days"] > 45 and r["why"].startswith("런웨이 2.0개월(3개월 이하)"), r
    runway.save(conn, "BBB", {"cash": 1e6, "cash_asof": ago(400), "monthly_burn": 1e6}); conn.commit()  # 오래된 재무 → 판정에 안 씀
    r = pick30.evaluate("BBB", conn, tgt, None)
    assert r["status"] == "대기" and r["imm_days"] is None and "오래됨" in r["why"] and r["has_runway"], r
    assert pick30.why_stats([r])["오래된 재무(200일↑)"] == 1

# --- 채우기: 없는 것만, 앞쪽 우선, 자료 없는 회사도 기록
class FakeClient:
    calls = []
    def cik_for(self, t): return 123
    def companyfacts(self, cik):
        FakeClient.calls.append(cik)
        return cf
res = runway.refresh(FakeClient(), ["NEW1", "AAA", "new1", "NEW2", "NEW3"], limit=2, out=lambda *_: None)
assert res["fetched"] == 2 and res["left"] == 1 and len(FakeClient.calls) == 2, res   # AAA 는 최근 받음/리포트 → 건너뜀, 대소문자 중복 제거
with closing(db.connect()) as conn:
    assert runway.now("NEW1", conn)["source"] == "SEC 재무"
res = runway.refresh(FakeClient(), ["NEW1", "NEW2", "NEW3"], limit=5, out=lambda *_: None)
assert res["fetched"] == 1, res                                                          # 2주 안에 받은 건 다시 안 받음
# 점검 명령: 흑자·오래된 재무(런웨이 숫자 없음)가 섞여도 끝까지(예전엔 정렬 중 오류)
import io, contextlib, diag_pick
_orig = pick30.scan
pick30.scan = lambda: {"registered": 2, "pass": [r], "fail": [{**r, "ticker": "CCC", "runway": None, "runway_info": c, "fail": "목표가 있음"}],
                       "funnel": {"목표가 있음": 1}, "why": pick30.why_stats([r]), "unregistered": []}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    diag_pick.main()
pick30.scan = _orig
assert "흑자(소모 없음) 1" in buf.getvalue() and "끝." in buf.getvalue(), buf.getvalue()[-600:]
print("ALL OK")
