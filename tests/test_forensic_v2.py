"""📰 Claude 공시분석 v2(B단계 2026-10-28) + C단계 외국 발행사: 6-K 첨부 읽기 · 규칙 지표 프롬프트 · SUMMARY_JSON 저장 · 자동 대기열 · 시나리오 추적 · 📰 탭 화면.
가짜 SEC·가짜 Claude — 인터넷 없이."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, config, aipick, forensic, forensic_ai, clock, secfeed, mover
db.init_db()
T = date.today(); d = lambda n: (T - timedelta(days=n)).isoformat()

PRESS = "PRESS RELEASE: Brainstorm announces $10 million registered direct offering at $2.50 per share with warrants exercisable at $3.00. " * 40
class FakeSec:
    """외국 발행사(FPI): 20-F · F-1 · 6-K 여러 건. 6-K 주 문서는 표지뿐(짧음) → 첨부(EX-99)에 내용."""
    def __init__(self): self.fetched = []; self.sub_n = 0
    def cik_for(self, t): return None if t == "NOCIK" else 1234
    def submissions(self, cik):
        self.sub_n += 1
        rows = [("0001-26-000001", "6-K", d(3), ""), ("0001-26-000002", "6-K", d(10), ""), ("0001-26-000003", "6-K", d(30), ""), ("0001-26-000004", "6-K", d(60), ""),
                ("0001-26-000005", "20-F", d(120), ""), ("0001-26-000006", "F-1", d(200), ""), ("0001-26-000007", "6-K", d(400), "")]
        return {"name": "Brainstorm Cell Therapeutics", "fiscalYearEnd": "1231", "category": "Non-accelerated filer",
                "filings": {"recent": {"accessionNumber": [r[0] for r in rows], "form": [r[1] for r in rows], "filingDate": [r[2] for r in rows],
                                       "items": [r[3] for r in rows], "primaryDocument": [f"doc{i}.htm" for i in range(len(rows))]}}}
    def companyfacts(self, cik): return {"facts": {}}
    def fetch_text(self, url, limit=600000):
        self.fetched.append(url)
        if "ex99" in url: return PRESS
        if url.endswith("doc0.htm"): return "FORM 6-K REPORT OF FOREIGN PRIVATE ISSUER cover page only. " * 8          # 짧은 표지(6000자 미만)
        return "lorem ipsum " * 2000 + " cash and cash equivalents of $3.3 million. going concern. warrant exercise price $3.00 " + "lorem " * 2000
    def _get(self, url):
        class R: text = ('<a href="/Archives/edgar/data/1234/000126000001/doc0.htm">doc0.htm</a> <a href="/Archives/edgar/data/1234/000126000001/ex99-1.htm">ex99-1.htm</a>'
                         ' <a href="/Archives/edgar/data/1234/000126000001/0001-26-000001-index.htm">idx</a>')
        return R()

sec_ = FakeSec()
idx = pd.bdate_range(end=pd.Timestamp(T), periods=80)
c = np.full(80, 2.0); h = c * 1.02; l = c * 0.98; v = np.full(80, 1e5)
h[70], c[70] = 5.05, 2.12   # PR 급등일(고가 +150% → 종가 +6%)
with closing(db.connect()) as conn:
    db.upsert_daily_prices(conn, "BRAI", pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx))
    secfeed.ensure_tables(conn)
    conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, filed, tags, sentiment) VALUES ('p1','BRAI',1234,'6-K',?,'[\"계약\"]','강한 호재')", (idx[70].date().isoformat(),))
    conn.execute("CREATE TABLE IF NOT EXISTS short_interest (ticker TEXT, date TEXT, si_pct REAL)"); conn.execute("CREATE TABLE IF NOT EXISTS ibkr_borrow (symbol TEXT PRIMARY KEY, fee REAL)")
    conn.execute("INSERT INTO short_interest VALUES ('BRAI', ?, 0.57)", (d(1),)); conn.execute("INSERT INTO ibkr_borrow VALUES ('BRAI', 565)")
    conn.commit()

# ---- C단계: 외국 발행사는 6-K 3건 · 첨부(보도자료)까지 · 20-F · F-1
g = forensic_ai.gather(sec_, "BRAI", T)
titles = [p[0] for p in g["parts"]]; print(titles)
assert sum(t.startswith("6-K") for t in titles) == 3 and any(t.startswith("20-F") for t in titles) and any(t.startswith("F-1") for t in titles)
k6 = dict(g["parts"])[next(t for t in titles if "0001-26-000001" in t)]
assert "registered direct offering at $2.50" in k6 and any("ex99" in u for u in sec_.fetched)                      # 짧은 6-K → 첨부 EX-99 를 읽음
assert not any("0001-26-000007" in t for t in titles)                                                                # 18개월 넘은 6-K 는 안 봄
# ---- A단계: 우리 규칙 계산이 프롬프트에
rt = dict(g["parts"])[next(t for t in titles if "우리 규칙 계산" in t)]; print(rt)
assert "PR·급등일 반응" in rt and "+152%" in rt and "하락 원인(규칙): 현물 매도 추정" in rt and "다음 정기 보고: 20-F" in rt and "가격대 50일 이동평균" in rt
sp = forensic_ai.system_prompt(); assert "SUMMARY_JSON" in sp and "한 장 요약" in sp and "DILUTION_JSON" in sp and "베이비 쉐프" in sp
with closing(db.connect()) as conn:
    assert clock.report_due_cached(conn, "BRAI", None)["next_form"] == "20-F"                                       # gather 가 보고 기한을 캐시에 남김

# ---- B단계: 분석 → SUMMARY_JSON 저장 · 보고서 화면에선 기계용 줄 제거
SUMMARY = {"one_liner": "12월부터 돌아오는 빚 — 현금 3.3M 로 2.9M 상환 뒤 사모 불가피", "clock": {"status": "급함", "cash_usd": 3300000, "monthly_burn_usd": 1100000, "runway_months": 3.0, "cash_need_by": (T + timedelta(days=60)).isoformat(), "why": "6-K " + d(3)},
           "structure": {"who_holds": "사모 투자자(2026-09 PIPE) 60% · 내부자 8%", "insider_pct": 8, "note": "등록 효력 뒤 락업 없음"},
           "payments": [{"date": (T + timedelta(days=40)).isoformat(), "amount_usd": 1500000, "what": "전환사채 원금", "source": "6-K " + d(10)},
                        {"date": (T + timedelta(days=70)).isoformat(), "amount_usd": "900,000", "what": "라이선스료", "source": "20-F"},
                        {"date": (T + timedelta(days=100)).isoformat(), "amount_usd": 500000, "what": "이자", "source": "6-K"}],
           "funding": {"likely": "사모(PIPE)", "atm_ok_from": (T + timedelta(days=30)).isoformat(), "atm_capacity_usd": 5000000, "warrants_cash_usd": 0, "convertibles_usd": 1500000, "why": "베이비 쉐프 한도 소진"},
           "overhang_calendar": [{"date": (T + timedelta(days=20)).isoformat(), "what": "등록 효력(사모 주식)", "shares_m": 4.0, "note": ""}],
           "levels": [{"price": 2.5, "label": "사모 발행가", "why": "9월 PIPE"}, {"price": 3.0, "label": "워런트 행사가", "why": ""}, {"price": "bad", "label": "x"}],
           "scenarios": {"attack": {"trigger": "임상 데이터 + 사모 해소", "target": 4.0, "note": "PR 고점 재도전"}, "base": {"trigger": "횡보", "target": 2.0}, "fail": {"trigger": "사모 출회", "target": 1.2, "note": "직전 저점"}},
           "pattern": "호재 당일 고점 → 3일 뒤 상승분 90% 반납", "sell_vs_short": "현물 매도", "next_deadline": {"date": (T + timedelta(days=40)).isoformat(), "what": "전환사채 상환"}}
REPORT = (f"# BRAI 덕구 SEC 포렌식 희석 스캔 (as-of {T.isoformat()})\n## 1. 무슨 회사인지 요약\n바이오.\n## 2. 💰 현재 런웨이 / 월 소모량\n🔴 3개월\n" + ("내용 " * 300)
          + "\n## 3. 유통 가능 주식 수\n-\n## 4. 완전희석 브리지\n-\n## 5. 내부자\n-\n## 10. 적색경보\n-\n## 11. 대기 중인 호재\n-\n"
          '<!-- DILUTION_JSON {"basic": 10000000, "fd": 20000000, "fd_ratio": null, "baby_shelf": "적용", "runway_months": 3.0, "toxic": false, "atm_eloc": true} -->\n'
          "<!-- SUMMARY_JSON " + json.dumps(SUMMARY, ensure_ascii=False) + " -->")
calls = []
class R:
    status_code = 200
    def json(self): return {"content": [{"type": "text", "text": REPORT}], "usage": {"input_tokens": 20000, "output_tokens": 5000}}
def post(url, headers=None, json=None, timeout=None):
    calls.append(json); return R()
forensic.queue_add(["BRAI"])
res = forensic_ai.analyze("BRAI", client=sec_, post=post, out=lambda *_: None); print(res["msg"])
assert res["ok"] and "📰 한 장 요약" in res["msg"] and "SUMMARY_JSON" in calls[0]["system"] and "우리 규칙 계산" in calls[0]["messages"][0]["content"]
rep = forensic.reports("BRAI"); body = str(rep.iloc[0].to_dict())
assert len(rep) == 1 and "SUMMARY_JSON" not in body and "DILUTION_JSON" not in body and forensic.queue_list() == []
with closing(db.connect()) as conn:
    s = forensic_ai.summary_latest(conn, "BRAI"); print(s["one_liner"], s["clock"], s["total_committed_usd"])
    assert s["as_of"] == T.isoformat() and s["clock"]["status"] == "급함" and s["clock"]["cash_usd"] == 3.3e6 and s["clock"]["runway_months"] == 3.0
    assert len(s["payments"]) == 3 and s["payments"][1]["amount_usd"] == 900000 and s["total_committed_usd"] == 2.9e6                  # 합계는 지급 목록에서 · "900,000" 문자열도 숫자로
    assert [x["price"] for x in s["levels"]] == [2.5, 3.0] and s["scenarios"]["attack"]["target"] == 4.0 and s["scenarios"]["fail"]["target"] == 1.2
    assert s["funding"]["likely"] == "사모(PIPE)" and s["funding"]["convertibles_usd"] == 1.5e6 and s["sell_vs_short"] == "현물 매도"
    assert forensic_ai.summary_latest(conn, "BRAI", as_of=d(1)) is None                                                                   # 컨닝 없음
    m = forensic_ai.metrics_at(conn, "BRAI"); assert m and m["fd_ratio"] == 2.0 and m["atm_eloc"] == 1                                    # 예전 수치 저장도 그대로
    # 📰 시나리오 추적(D-light): 오늘 요약은 '진행 중' · 20일 전 요약(공격 목표 1.2)인데 그 뒤 고가 1.5 → 도달 · 실패 목표에 닿으면 실패
    sc = forensic_ai.scenario_check(conn); assert len(sc) == 1 and sc.iloc[0]["판정"] == "진행 중" and sc.iloc[0]["기준가($)"] == 2.0
    forensic_ai.save_summary("OLDT", d(20), {"scenarios": {"attack": {"target": 1.2}, "fail": {"target": 0.5}}, "one_liner": "옛 요약"})
    forensic_ai.save_summary("BADT", d(20), {"scenarios": {"attack": {"target": 9.0}, "fail": {"target": 0.5}}, "one_liner": "나쁜 요약"})
    co = np.full(80, 1.0); ho = co * 1.02; ho[-10:] = 1.5; lo = co * 0.98
    db.upsert_daily_prices(conn, "OLDT", pd.DataFrame({"Open": co, "High": ho, "Low": lo, "Close": co, "Volume": v}, index=idx))
    lb = co * 0.98; lb[-3:] = 0.4
    db.upsert_daily_prices(conn, "BADT", pd.DataFrame({"Open": co, "High": co * 1.02, "Low": lb, "Close": co, "Volume": v}, index=idx)); conn.commit()
    sc = forensic_ai.scenario_check(conn).set_index("종목"); print(sc[["판정", "그 뒤 고가($)", "그 뒤 저가($)"]])
    assert sc.loc["OLDT", "판정"] == "🚀 공격 목표 도달" and sc.loc["BADT", "판정"] == "💀 실패 시나리오" and sc.loc["BRAI", "판정"] == "진행 중"
    # 📰 자동 대기열: 급상승 상위(BRAI 는 요약 있음 → 제외 · FAILT 는 최근 실패 → 제외) + 가상매매 보유 + 저금통 · 토스 거래 가능만 · 하루 limit
    mover.ensure(conn)
    for i, tk in enumerate(["BRAI", "NEWT", "FAILT", "NOTR", "OLDT"], 1):
        conn.execute("INSERT INTO toss_rank (date, kind, rank, ticker, price, change_pct, session, at) VALUES (?,?,?,?,1,50,'reg',?)", (T.isoformat(), "up", i, tk, db.utcnow_iso()))
    conn.commit()
    db.set_meta("forensic_ai_fail:FAILT", T.isoformat())
    import papertrade, piggy, tradable
    papertrade.open_tickers = lambda: ["PTO"]; piggy.tickers = lambda: ["PIG"]
    tradable.active = lambda conn=None, ttl=600: {"BRAI", "NEWT", "FAILT", "PTO", "PIG", "OLDT", "BADT"}
    new = forensic_ai.auto_enqueue(conn, out=lambda *_: None, limit=4); print(new)
    assert new == ["NEWT", "PTO", "PIG"] and set(forensic.queue_list()) == {"NEWT", "PTO", "PIG"}                                        # OLDT 는 30일 안 요약 있음 · NOTR 거래 불가
    assert forensic_ai.auto_enqueue(conn, out=lambda *_: None) == []                                                                       # 이미 대기열
    assert forensic_ai.auto_enqueue(conn, out=lambda *_: None, max_age=5) == ["OLDT"]                                                     # 요약이 오래되면 다시
assert forensic_ai.parse_summary("<!-- SUMMARY_JSON {bad} -->") is None and forensic_ai.parse_summary("none") is None and forensic_ai.parse_summary("<!-- SUMMARY_JSON [1] -->") is None
ps = forensic_ai.parse_summary('x <!-- DILUTION_JSON {"basic": 1} -->\n<!-- SUMMARY_JSON {"one_liner": "a", "scenarios": {"attack": {"target": "4.5"}}, "payments": "no"} -->')
assert ps["one_liner"] == "a" and ps["scenarios"]["attack"]["target"] == 4.5 and ps["payments"] == [] and ps["total_committed_usd"] is None and ps["clock"] == {"cash_usd": None, "monthly_burn_usd": None, "runway_months": None}
assert forensic_ai.full_text(sec_, {"form": "10-K", "url": "https://x/doc5.htm", "accession": "0001-26-000005"}, 1234).startswith("lorem")   # 긴 서류는 그대로

# ---- 📰 탭 화면(🏢 종목) — 한 장 요약 카드 · 규칙 카드 · 2 진입 판단의 사다리 보강
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "BRAI", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 2.0, "high_20d": 5.05, "low_20d": 1.9,
        "drawdown_pct": -60.0, "day_change_pct": -5.0, "volume_mult": 6.0, "buy_pressure": 55.0, "float_shares": 9e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "OFFERING", "excluded": 0})
    db.save_fundamentals(conn, "BRAI", {"name": "Brainstorm", "exchange": "NASDAQ", "float_shares": 9e6, "shares_out": 12e6, "market_cap": 24e6})
    conn.commit()
os.environ["QUANT_TEST_PAGE"] = "lookup"
import watch_ui
df = pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)
watch_ui.prices = lambda tk: {"BRAI": df}
at = AppTest.from_file(APP, default_timeout=180); at.session_state["lookup_ticker"] = "BRAI"; at.run(); assert not at.exception, [e.value for e in at.exception]
assert [x.label for x in at.tabs][0] == "📰 한 장 요약"
html = "\n".join(m.value for m in at.markdown); succ = "\n".join(m.value for m in at.success)
assert "12월부터 돌아오는 빚" in succ and "⏰ 시계 — 급함" in html and "런웨이 3.0개월" in html and "🏗 구조" in html and "사모 투자자(2026-09 PIPE)" in html
assert "💸 갚아야 할 돈" in html and "$2.90M" in html and "🏦 조달 예상" in html and "ATM 가능 시점" in html and "사모 20% 할인 가정: &#36;1.6000에 1.81M주 = 유통주식의 20%" in html   # 2.9M ÷ 1.6 · 카드 안 $ 는 esc 가 &#36; 로
assert "🚀 공격 시나리오 목표" in html and "💀 실패 시나리오 목표" in html and "사모 발행가" in html and "★ 현재가" in html and "📅 물량 달력" in html
assert "📉 하락 원인(규칙) — 현물 매도 추정" in html and "⏰ 다음 정기 보고" in html and "20-F 기한" in html and "📣 PR 소화력" in html and "+152%" in html
assert "50일 이동평균" in html and "PR 고점 · 공급벽" in html                                                                              # 2 진입 판단 사다리 보강
os.environ.pop("QUANT_TEST_PAGE")
print("ALL OK")
