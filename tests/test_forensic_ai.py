import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, config, aipick, forensic, forensic_ai
db.init_db()
T = date.today()
d = lambda n: (T - timedelta(days=n)).isoformat()

class FakeSec:
    def __init__(self): self.fetched = []
    def cik_for(self, t): return None if t == "SYAB" else 1234
    def submissions(self, cik):
        rows = [("0001-26-000001", "8-K", d(5), "1.01,3.02,9.01"), ("0001-26-000002", "8-K", d(6), "7.01"), ("0001-26-000003", "424B5", d(7), ""),
                ("0001-26-000004", "S-3", d(40), ""), ("0001-26-000005", "10-Q", d(20), ""), ("0001-26-000006", "10-K", d(200), ""),
                ("0001-26-000007", "DEF 14A", d(30), ""), ("0001-24-000008", "10-K", d(700), "")]
        return {"name": "Alpha Bio Inc", "filings": {"recent": {"accessionNumber": [r[0] for r in rows], "form": [r[1] for r in rows], "filingDate": [r[2] for r in rows],
                                                               "items": [r[3] for r in rows], "primaryDocument": [f"doc{i}.htm" for i in range(len(rows))]}}}
    def companyfacts(self, cik):
        return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": d(75), "val": 17597071, "form": "10-Q", "filed": d(74)},
                                                                                              {"end": d(75), "val": 17597071, "form": "10-Q", "filed": d(74)}]}},
                                  "EntityPublicFloat": {"units": {"USD": [{"end": d(300), "val": 8800000, "form": "10-K", "filed": d(210)}]}}},
                          "us-gaap": {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                              {"start": d(300), "end": d(120), "val": -4995000, "form": "10-Q", "filed": d(74)},
                              {"start": d(300), "end": d(210), "val": -2100000, "form": "10-Q", "filed": d(160)}]}},
                                      "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": d(120), "val": 794000, "form": "10-Q", "filed": d(74)}]}}}}}
    def fetch_text(self, url, limit=600000):
        self.fetched.append(url)
        filler = "lorem ipsum " * 3000
        return ("COVER PAGE " + filler + " There is substantial doubt about our ability to continue as a going concern. " + filler
                + " The warrants have an exercise price of $0.50 per share. " + filler + " Cash and cash equivalents of $1.2 million. " + filler)

sec_ = FakeSec()
with closing(db.connect()) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS insider_tx (accession TEXT, seq INTEGER, ticker TEXT, owner TEXT, title TEXT, date TEXT, code TEXT, shares REAL, price REAL, value REAL, after_shares REAL, url TEXT)")
    conn.execute("INSERT INTO insider_tx (accession, seq, ticker, owner, title, date, code, shares, price, value) VALUES ('a',1,'ABIO','CEO Kim','CEO',?, 'P', 10000, 0.6, 6000)", (d(10),))
    import pandas as pd, numpy as np
    idx = pd.bdate_range(start=pd.Timestamp(T) - pd.Timedelta(days=120), periods=70)
    c = np.linspace(0.5, 0.8, 70)
    db.upsert_daily_prices(conn, "ABIO", pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": np.full(70, 1e5)}, index=idx))
    conn.commit()

# 원문 발췌: 18개월 안 · 핵심 단어 주변만 · 8-K 는 자금조달 항목만 · 내부자·시장 데이터 포함
g = forensic_ai.gather(sec_, "ABIO", T)
titles = [p[0] for p in g["parts"]]
assert titles[0].startswith("최근 공시 목록") and any(t.startswith("10-K ·") for t in titles) and any(t.startswith("10-Q") for t in titles)
assert any(t.startswith("424B5") for t in titles) and any(t.startswith("S-3") for t in titles) and any(t.startswith("DEF 14A") for t in titles)
assert sum(t.startswith("8-K") for t in titles) == 1                                              # 7.01(IR 자료) 8-K 는 뺌
assert not any(d(700) in t for t in titles)                                                      # 18개월 넘은 10-K 는 안 봄
xb = dict(g["parts"])[[t for t in titles if t.startswith("SEC XBRL")][0]]
assert titles[1].startswith("SEC XBRL") and "non-affiliate float" in xb and "8,800,000" in xb and "-4,995,000" in xb and "-2,100,000" in xb
assert xb.count("17,597,071") == 1                                                               # 같은 기준일 중복은 한 번만
k10 = dict(g["parts"])[[t for t in titles if t.startswith("10-K ·")][0]]
assert "going concern" in k10 and "exercise price of $0.50" in k10 and len(k10) < 30000          # 핵심 단어 주변만(원문 15만 자)
assert any("Form 4" in t for t in titles) and any("시장 데이터" in t for t in titles)
p = forensic_ai.build_prompt("ABIO", g, T)
assert "Alpha Bio Inc" in p and "CIK 1234" in p
sp = forensic_ai.system_prompt()
assert "고정 규율" in sp and "베이비 쉐프" in sp and "§6" in sp or "공매도" in sp

# 분석 → 저장 · 대기열 제거 · 실패 기록 정리
forensic.queue_add(["SYAB", "ABIO", "NIVF"])
forensic._set_error("NINF", "옛 실패(티커 오타)")                                               # 대기열에 없는 종목의 오래된 실패
REPORT = (f"# ABIO 덕구 SEC 포렌식 희석 스캔 (as-of {T.isoformat()})\n## 1. 무슨 회사인지 요약\n바이오.\n## 2. 💰 현재 런웨이 / 월 소모량\n🔴 런웨이 3개월 미만 (10-Q " + d(20) + ")\n"
          + ("내용 " * 300) + "\n## 3. 유통 가능 주식 수\n추가 확인 필요\n## 4. 완전희석 브리지\n추가 확인 필요\n## 5. 내부자\n표\n"
          "## 10. 적색경보\n🔴 going concern · 🟠 워런트 $0.50\n## 11. 대기 중인 호재\n- 없음\n"
          '<!-- DILUTION_JSON {"basic": 17597071, "fd": "177,000,000", "fd_ratio": null, "baby_shelf": "적용", "runway_months": 2.1, "toxic": false, "atm_eloc": null} -->')
calls = []
class R:
    status_code = 200
    def json(self): return {"content": [{"type": "text", "text": REPORT}], "usage": {"input_tokens": 25000, "output_tokens": 4000}}
def post(url, headers=None, json=None, timeout=None):
    calls.append(json); return R()
res = forensic_ai.run(limit=2, client=sec_, post=post, out=lambda *_: None)
assert "NINF" not in forensic.errors()                                                           # 오래된 실패 기록 정리
assert res["n"] == 1 and "SYAB" in forensic.errors() and "CIK" in forensic.errors()["SYAB"]["why"]  # CIK 없는 티커는 실패 기록
assert forensic.queue_list() == ["SYAB", "NIVF"]                                                 # 성공한 ABIO 만 빠짐
assert calls[0]["model"] == "claude-sonnet-5-5" and calls[0]["max_tokens"] == 32000 and "덕구" in calls[0]["system"]
assert calls[0]["output_config"] == {"effort": "medium"} and "thinking" not in calls[0]                 # Sonnet 5.5: 생각은 켠 채 깊이만 낮춤
rep = forensic.reports("ABIO")
assert len(rep) == 1 and "서버 자동" in str(rep.iloc[0].to_dict())
assert aipick.spent_usd() > 0
# 🧾 완전희석 배수 저장(보고서 화면에선 기계용 줄 제거) → ✅ 3대 조건 ③ 판정이 '희석 있음'으로
assert "DILUTION_JSON" not in str(rep.iloc[0].to_dict())
import setup3, secbackfill
with closing(db.connect()) as conn:
    for ddl in secbackfill.DDL:
        conn.execute(ddl)
    conn.commit()
    m = forensic_ai.metrics_at(conn, "ABIO")
    assert m and abs(m["fd_ratio"] - 177000000 / 17597071) < 1e-6 and m["baby_shelf"] == "적용" and m["toxic"] == 0 and m["atm_eloc"] is None
    dl = setup3.dilution_absent("ABIO", conn)
    assert dl["ok"] is False and "완전희석 10.1배" in dl["label"] and "대기 물량" in dl["label"], dl
    assert setup3.dilution_absent("ABIO", conn, as_of=d(30))["ok"] is True                        # 보고서 전 날짜엔 모름(컨닝 없음)
    assert setup3.tier(15, True, dl["ok"]) is None                                                # 검증 순위에서도 빠짐
    b_ = aipick.brief(conn, {"ticker": "ABIO", "src": "순위", "pick": None, "rank": None})
    assert b_["fd_ratio"] == round(177000000 / 17597071, 2)
assert forensic_ai.parse_metrics("no json") is None and forensic_ai.parse_metrics("<!-- DILUTION_JSON {bad} -->") is None

# 실패한 종목은 이틀 동안 다시 시도하지 않음 → 다음 실행은 NIVF 만
res2 = forensic_ai.run(limit=2, client=sec_, post=post, out=lambda *_: None)
assert res2["n"] == 1 and forensic.queue_list() == ["SYAB"] and len(calls) == 2
# 예산 부족이면 멈춤
forensic.queue_add(["ZZZZ"])
config.AI_MONTHLY_BUDGET_KRW = aipick.spent_usd() * aipick.FX + 10
res3 = forensic_ai.run(limit=3, client=sec_, post=post, out=lambda *_: None)
assert res3["n"] == 0 and "예산" in res3["msg"] and len(calls) == 2
config.AI_MONTHLY_BUDGET_KRW = 50000.0

# 짧은 답(거절·요약만): 실패 기록에 답 앞부분 · 답은 파일로 남김
class RS(R):
    def json(self): return {"content": [{"type": "text", "text": "자료가 부족해 분석할 수 없습니다."}], "usage": {"input_tokens": 100, "output_tokens": 20}}
r4 = forensic_ai.analyze("ABIO", client=sec_, post=lambda *a, **k: RS(), out=lambda *_: None)
assert not r4["ok"] and "자료가 부족해" in forensic.errors()["ABIO"]["why"] and "섹션 제목 0개" in r4["msg"]
assert (forensic.root_dir() / "ai_raw" / f"ABIO_{T:%Y%m%d}.md").read_text(encoding="utf-8").startswith("자료가 부족해")
# 생각에 한도를 다 써서 글이 빈 답 → 이유가 실패 메시지에(요금은 기록)
class RT(R):
    def json(self): return {"content": [{"type": "thinking", "thinking": ""}], "stop_reason": "max_tokens",
                            "usage": {"input_tokens": 38000, "output_tokens": 9000, "output_tokens_details": {"thinking_tokens": 8999}}}
before = aipick.spent_usd()
r6 = forensic_ai.run(tickers=["ABIO"], client=sec_, post=lambda *a, **k: RT(), out=lambda *_: None)
assert r6["n"] == 0 and "max_tokens" in r6["msg"] and "생각" in r6["msg"] and aipick.spent_usd() > before

# 핵심 공시가 하나도 없으면 Claude 를 부르지 않음
class NoCore(FakeSec):
    def submissions(self, cik):
        return {"name": "Otc Co", "filings": {"recent": {"accessionNumber": ["x1", "x2"], "form": ["SC 13G", "3"], "filingDate": [d(10), d(20)], "items": ["", ""],
                                                       "primaryDocument": ["a.htm", "b.htm"]}}}
n0 = len(calls)
r5 = forensic_ai.analyze("OTCX", client=NoCore(), post=post, out=lambda *_: None)
assert not r5["ok"] and "핵심 공시" in r5["msg"] and "SC 13G" in r5["msg"] and len(calls) == n0

# AI PICK 용 요약: 적색경보·런웨이 · 오래된 보고서는 안 씀
with closing(db.connect()) as conn:
    fz = forensic_ai.latest_brief(conn, "ABIO")
    assert fz and "🔴" in fz and "적색경보" in fz and "런웨이" in fz
    assert forensic_ai.latest_brief(conn, "NONE") is None
    b = aipick.brief(conn, {"ticker": "ABIO", "src": "순위", "pick": None, "rank": None})
    assert "forensic" in b
assert config.AI_MONTHLY_BUDGET_KRW == 50000.0 and "FORENSIC_PER_RUN" in config.SETTINGS
print("ALL OK")
