"""⏰ clock.py(A단계 2026-10-28): PR 소화력 · 하락 원인 · 보고 기한 · 사모 계산 · 사다리 보강 — 인터넷 없이(가짜 SEC)."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, clock, secfeed, exthilo
db.init_db()
T = date.today(); d = lambda n: (T - timedelta(days=n)).isoformat()

# 일봉 80일: 평소 1.00 · 40번째 급등일(공시 없음, 고가 1.3 → 종가 1.1) · 60번째 6-K 호재(고가 1.6 → 종가 1.4, 반납 33%)
# · 70번째 6-K 강한 호재(일봉 고가 1.5 지만 프리장 1.9 → 종가 1.05, 반납 94%) · 75번째 6-K 호재인데 반응 없음(고가 1.02)
idx = pd.bdate_range(end=pd.Timestamp(T), periods=80)
o = np.full(80, 1.0); h = np.full(80, 1.02); l = np.full(80, 0.98); c = np.full(80, 1.0); v = np.full(80, 1e5)
I1, I2, I3, I4 = 40, 60, 70, 75
h[I1], c[I1], v[I1] = 1.3, 1.1, 3e6
h[I2], c[I2], v[I2] = 1.6, 1.4, 5e6
h[I3], c[I3], v[I3] = 1.5, 1.05, 4e6
D = lambda i: idx[i].date().isoformat()
with closing(db.connect()) as conn:
    db.upsert_daily_prices(conn, "BRAI", pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx))
    secfeed.ensure_tables(conn)
    for acc, i, sent in (("a2", I2, "호재"), ("a3", I3, "강한 호재"), ("a4", I4, "호재"), ("a5", I1, "악재")):   # 악재는 PR 로 안 센다(급등일로만)
        conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, filed, tags, sentiment) VALUES (?,?,1,'6-K',?,?,?)", (acc, "BRAI", D(i), '["계약", "매출"]', sent))
    conn.execute(exthilo.DDL)
    conn.execute("INSERT INTO ext_hilo (date, ticker, night_high, pre_high, reg_high, post_high) VALUES (?,?,?,?,?,?)", (D(I3), "BRAI", None, 1.9, 1.5, None))
    conn.commit()

    pr = clock.pr_reactions(conn, "BRAI")
    print(pr["note"]); print([(r["date"], r["why"], round(r["hi_pct"]), round(r["close_pct"]), None if r["fade"] is None else round(r["fade"], 3)) for r in pr["rows"]])
    assert pr["n"] == 4 and [r["date"] for r in pr["rows"]] == [D(I4), D(I3), D(I2), D(I1)]                      # 최신순 · 다음날은 중복으로 안 셈
    r4, r3, r2, r1 = pr["rows"]
    assert "반응 없음" in r4["why"] and r4["hi_pct"] < 5
    assert r3["why"].startswith("공시 6-K 강한 호재") and abs(r3["high"] - 1.9) < 1e-9 and abs(r3["hi_pct"] - 90) < 1e-6 and abs(r3["fade"] - (1.9 - 1.05) / 0.9) < 1e-6   # 프리장 고점 반영
    assert "계약" in r3["why"] and abs(r2["fade"] - (1.6 - 1.4) / 0.6) < 1e-6 and abs(r2["close_pct"] - 40) < 1e-6
    assert r1["why"].startswith("급등일") and abs(r1["fade"] - (1.3 - 1.1) / 0.3) < 1e-6
    assert pr["trend"] == "약해짐" and "약해짐" in pr["note"] and "반납 94%" in pr["note"] or "반응 없음" in pr["note"]   # 최근 두 번: 94% 반납 > 33% 반납
    assert clock.pr_reactions(conn, "NONE")["n"] == 0 and clock.pr_reactions(conn, "NONE")["trend"] is None
    old = clock.pr_reactions(conn, "BRAI", as_of=D(I2))                                                           # 컨닝 없음: 그날까지만
    assert old["n"] == 2 and old["rows"][0]["date"] == D(I2)
    # 장 마감 뒤 공시(그날 반응 없음) → 다음날 급등은 '전날 공시' 로 한 번만
    conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, filed, tags, sentiment) VALUES ('a6','AFTR',1,'8-K',?,'[]','호재')", (D(50),))
    h2 = np.full(80, 1.02); c2 = np.full(80, 1.0); h2[51], c2[51] = 1.25, 1.2                                                  # 평소 평탄 · 공시 다음날만 급등
    db.upsert_daily_prices(conn, "AFTR", pd.DataFrame({"Open": o, "High": h2, "Low": l, "Close": c2, "Volume": v}, index=idx)); conn.commit()
    pa = clock.pr_reactions(conn, "AFTR"); print([(r["date"], r["why"]) for r in pa["rows"]])
    assert pa["n"] == 2 and pa["rows"][0]["why"].startswith("전날 공시 8-K") and "반응 없음" in pa["rows"][1]["why"]

    # 📉 하락 원인
    assert clock.drop_cause(conn, "NONE")["verdict"] == "자료 없음"
    conn.execute("CREATE TABLE IF NOT EXISTS short_interest (ticker TEXT, date TEXT, si_pct REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS ibkr_borrow (symbol TEXT PRIMARY KEY, fee REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS cx_short_volume (ticker TEXT, date TEXT, short_pct REAL)")
    conn.execute("INSERT INTO short_interest (ticker, date, si_pct) VALUES ('BRAI', ?, 0.57), ('BRAI', ?, 3.0), ('HISI', ?, 20.0), ('MEH', ?, 3.0)", (d(1), d(20), d(1), d(1)))
    conn.execute("INSERT INTO ibkr_borrow VALUES ('BRAI', 565), ('MEH', 10)")
    conn.execute("INSERT INTO cx_short_volume VALUES ('SVH', ?, 65.0)", (d(1),))
    conn.commit()
    dc = clock.drop_cause(conn, "BRAI"); print(dc)
    assert dc["verdict"] == "현물 매도 추정" and dc["si_pct"] == 0.57 and dc["fee"] == 565 and "공매 잔고 0.6%" in dc["why"] and "대차비용 565%" in dc["why"]   # 최신 잔고(0.57) 사용
    assert clock.drop_cause(conn, "HISI")["verdict"] == "공매 눌림 가능" and clock.drop_cause(conn, "SVH")["verdict"] == "공매 눌림 가능"
    assert clock.drop_cause(conn, "MEH")["verdict"] == "보류"

    # ⏰ 보고 기한 — 외국 발행사(20-F): 회계연도 말 + 4개월, NT +15일
    sub_fpi = {"fiscalYearEnd": "1231", "category": "", "filings": {"recent": {"form": ["6-K", "20-F", "6-K"], "filingDate": ["2026-10-01", "2026-04-20", "2026-03-01"]}}}
    r = clock.report_due(sub_fpi, today=date(2026, 10, 28)); print(r)
    assert r["fpi"] and r["next_form"] == "20-F" and r["period_end"] == "2026-12-31" and r["due"] == "2027-04-30" and r["nt_due"] == clock._bday(date(2027, 5, 15)).isoformat()
    assert r["dday"] == (date(2027, 4, 30) - date(2026, 10, 28)).days and r["last_annual"] == "2026-04-20"
    sub_early = {"fiscalYearEnd": "1231", "filings": {"recent": {"form": ["6-K", "20-F"], "filingDate": ["2026-02-01", "2025-04-25"]}}}
    r = clock.report_due(sub_early, today=date(2026, 3, 1))                                                      # 작년 20-F 를 아직 안 냈음 → 올해 4/30
    assert r["period_end"] == "2025-12-31" and r["due"] == "2026-04-30" and r["dday"] == 60
    # 미국 발행사(10-K/10-Q): 비가속 90일 · 분기 45일(NT +5) — 2026-10-28 기준 다음은 3분기 10-Q
    sub_us = {"fiscalYearEnd": "1231", "category": "Non-accelerated filer", "filings": {"recent": {"form": ["10-Q", "8-K", "10-K"], "filingDate": ["2026-08-10", "2026-05-01", "2026-03-25"]}}}
    r = clock.report_due(sub_us, today=date(2026, 10, 28)); print(r)
    assert not r["fpi"] and r["next_form"] == "10-Q" and r["period_end"] == "2026-09-30" and r["due"] == "2026-11-16" and r["nt_due"] == "2026-11-23"   # 11/14 토 → 월요일
    sub_la = {"fiscalYearEnd": "0630", "category": "Large accelerated filer", "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-08-25"]}}}
    r = clock.report_due(sub_la, today=date(2026, 10, 28)); assert r["next_form"] == "10-Q" and r["due"] == "2026-11-09"                # 9/30 + 40일
    r = clock.report_due({"fiscalYearEnd": "0630", "category": "Accelerated filer", "filings": {"recent": {"form": ["10-Q"], "filingDate": ["2026-05-10"]}}}, today=date(2026, 7, 15))
    assert r["next_form"] == "10-K" and r["period_end"] == "2026-06-30" and r["due"] == clock._bday(date(2026, 9, 13)).isoformat()     # 6/30 + 75일
    assert clock.report_due({"fiscalYearEnd": "", "filings": {}}) is None and clock.report_due({}) is None

    class FakeSec:
        def __init__(self): self.n = 0
        def cik_for(self, t): return 99 if t == "BRAI" else None
        def submissions(self, cik): self.n += 1; return sub_fpi
    fs = FakeSec()
    r = clock.report_due_cached(conn, "BRAI", fs); assert r["next_form"] == "20-F" and fs.n == 1
    r2 = clock.report_due_cached(conn, "BRAI", fs); assert r2["due"] == r["due"] and r2["fpi"] is True and "dday" in r2 and fs.n == 1     # 캐시(3일)
    assert clock.report_due_cached(conn, "BRAI", None)["due"] == r["due"] and clock.report_due_cached(conn, "ZZZ", None) is None
    assert clock.report_due_cached(conn, "ZZZ", fs) is None
    assert clock.refresh_due(conn, fs, ["BRAI", "ZZZ", "brai"], out=lambda *_: None) == 1

    # 🧮 사모 계산 · 사다리 보강
    s = clock.pipe_sim(2.0, 10e6, 5e6, 20e6); print(s)
    assert abs(s["price"] - 1.6) < 1e-9 and abs(s["shares"] - 6.25e6) < 1 and abs(s["pct_float"] - 125) < 1e-6 and abs(s["pct_out"] - 31.25) < 1e-6
    assert clock.pipe_sim(None, 1e6, 1, 1) is None and clock.pipe_sim(2.0, None, 1, 1) is None and clock.pipe_sim(2.0, 1e6, None, None)["pct_float"] is None
    df = pd.DataFrame({"Close": c, "High": h, "Low": l}, index=idx)
    lv = clock.extra_levels(conn, "BRAI", 1.0, df, amount_usd=5e6, float_shares=10e6, shares_out=12e6)
    labels = [x["label"] for x in lv]; print([(x["label"], round(x["price"], 3), None if x["pct"] is None else round(x["pct"])) for x in lv])
    assert labels[0] == "50일 이동평균" and any("PR 고점" in s_ for s_ in labels) and "PR 직전 종가" in labels and "사모 20% 할인가(가정)" in labels
    pk = next(x for x in lv if "PR 고점" in x["label"]); assert abs(pk["price"] - 1.9) < 1e-9 and abs(pk["pct"] - 90) < 1e-6 and "+90%" in pk["note"]   # 가장 최근 큰 PR(프리장 1.9)
    pp = next(x for x in lv if x["kind"] == "pipe"); assert abs(pp["price"] - 0.8) < 1e-9 and "6.25M주" in pp["note"] and "62%" in pp["note"]
    assert clock.extra_levels(conn, "NONE", None) == []

    rb = clock.rule_block(conn, "BRAI", 1.0, df, client=fs)
    txt = clock.rule_text(rb); print(txt)
    assert "PR·급등일 반응" in txt and "고점을 지키는 힘: 약해짐" in txt and "하락 원인(규칙): 현물 매도 추정" in txt and "다음 정기 보고: 20-F 기한 2027-04-30" in txt and "가격대 50일 이동평균" in txt
    assert clock.rule_text({}) == "" and isinstance(clock.due_targets(conn), list)
print("ALL OK")
