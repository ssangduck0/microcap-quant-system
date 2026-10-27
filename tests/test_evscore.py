import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json, random
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import pandas as pd
import db, evscore, secfeed, watch, halts
db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
random.seed(7)
T = date.today()

# --- 가짜 사건 3년치: '계약·수주 / $1 미만 / 장전' 은 진짜로 잘 오르고(70%), '공모·사모 / $5 이상 / 장후' 는 못함(20%), 나머지 40%.
#     키워드(sentiment)는 일부러 엉터리로 섞어 '지금 규칙'이 약하게
rows = []
for i in range(9000):
    d0 = T - timedelta(days=random.randint(1, 1095))
    r = random.random()
    if r < 0.15:
        ty, px, tm, p = "계약·수주", 0.6, "장전", 0.70
    elif r < 0.30:
        ty, px, tm, p = "공모·사모(희석)", 8.0, "장후", 0.20
    else:
        ty, px, tm, p = random.choice(["기타", "실적 발표", "FDA·임상"]), random.choice([0.5, 2.0, 7.0]), random.choice(["장전", "장중", "장후"]), 0.40
    rows.append({"type": ty, "price": px, "timing": tm, "day0": d0.isoformat(), "abn5": (5.0 if random.random() < p else -5.0),
                 "sentiment": random.choice(["호재", "악재", "중립", "중립"])})
df = pd.DataFrame(rows)
tb = evscore.build_table(df)
assert 0.38 < tb["p0"] < 0.46 and tb["n"] == 9000
good, bad = evscore.score(tb, "계약·수주", 0.6, "장전"), evscore.score(tb, "공모·사모(희석)", 8.0, "장후")
assert good > 15 and bad < -15, (good, bad)
assert evscore.score(tb, "없는 종류", 1.0, "장전") == 0.0 and evscore.score({}, "x", 1, "장전") == 0.0
assert abs(evscore.score(tb, "계약·수주", 0.6, "장중")) < good           # 같은 종류·가격대지만 칸이 없으면 상위(종류×가격대) 값
# 표본 적은 칸은 기준선 쪽으로: 5건짜리 100% 칸이 기준선+60%p 가 되지 않음
small = pd.concat([df, pd.DataFrame([{"type": "희귀", "price": 2.0, "timing": "장전", "day0": T.isoformat(), "abn5": 5.0, "sentiment": "중립"}] * 5)])
assert evscore.score(evscore.build_table(small), "희귀", 2.0, "장전") < 5

v = evscore.validate(df)
assert v["ok"] and v["new"]["spread"] > v["old"]["spread"] and v["new"]["rho"] > v["old"]["rho"], v
assert not evscore.validate(df.head(500))["ok"]                          # 자료 부족이면 안 씀

# --- 공시 알림 한 건 → 종류·시점
assert evscore.feed_timing("2026-10-23T08:15:00-04:00") == "장전" and evscore.feed_timing("2026-10-23T10:00:00-04:00") == "장중"
assert evscore.feed_timing("2026-10-23T16:05:12-04:00") == "장후" and evscore.feed_timing(None) == "장후"
assert evscore.feed_type("3.02", "[]") == "공모·사모(희석)" and evscore.feed_type('["1.01"]', "") == "계약·수주"
# 공시 알림의 한글 태그로도 분류(예전엔 거의 다 '기타' → 희석 공시가 좋은 점수를 받던 버그)
assert evscore.feed_type(None, '["ATM/ELOC"]', "6-K") == "공모·사모(희석)" and evscore.feed_type("", ["상장유지", "사명 변경"], "8-K") == "상장유지 통지"
assert evscore.feed_type("1.01", ["희석 위험"], "8-K") == "공모·사모(희석)"                       # 희석이 계약보다 앞섬
assert evscore.feed_type("", ["사명 변경"], "8-K") == "기타"
assert evscore.feed_type("", ["희석 위험"], "424B5") is None and evscore.feed_type("", [], "S-1") is None   # 8-K·6-K 만 점수
# 가격을 모르면 종류 전체 값
assert evscore.score(tb, "계약·수주", None, "장전") != 0.0 and evscore.info(tb, "계약·수주", None, "장전")["level"] == "종류 전체(가격 미상)"

# --- 순위: 검증 통과한 점수표가 있으면 새 점수, 없거나 끄면 예전 규칙
db.set_meta("evscore", json.dumps({"built": "x", "validation": {"ok": True}, "table": tb}, ensure_ascii=False))
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    secfeed.ensure_tables(conn)
    for t, px in (("GOOD", 0.6), ("BAD", 8.0)):
        db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": px, "high_20d": 2.0, "low_20d": 0.4,
            "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.execute("INSERT INTO sec_feed (accession, ticker, form, company, filed, updated, items, tags, sentiment, score) VALUES ('g1','GOOD','8-K','Good Co',?,?,'1.01','[]','중립',0)",
                 (T.isoformat(), f"{T.isoformat()}T08:10:00-04:00"))
    conn.execute("INSERT INTO sec_feed (accession, ticker, form, company, filed, updated, items, tags, sentiment, score) VALUES ('b1','BAD','8-K','Bad Co',?,?,'3.02','[]','중립',0)",
                 (T.isoformat(), f"{T.isoformat()}T17:30:00-04:00"))
    conn.commit()
    rec = evscore.recent(conn, tb, {"GOOD": 0.6, "BAD": 8.0})
assert rec["GOOD"][0][0] > 15 and "계약·수주·$1 미만·장전" == rec["GOOD"][0][1] and rec["BAD"][0][0] < -15
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO sec_feed (accession, ticker, form, company, filed, updated, items, tags, sentiment, score) VALUES ('p1','GOOD','424B5','Good Co',?,?,'','[\"희석 위험\"]','악재',-2)",
                 (T.isoformat(), f"{T.isoformat()}T09:00:00-04:00"))
    conn.commit()
import rank, config
r = rank.compute().set_index("ticker")
assert not any("과거 성과 좋음" in x for x in r.loc["GOOD", "why"]), r.loc["GOOD", "why"]   # 같은 기간에 희석 투자설명서(악재)가 있으면 가산 안 함
assert "최근 3일 악재 공시" in r.loc["GOOD", "risk"], r.loc["GOOD", "risk"]                  # 8-K 가 아닌 악재는 예전 규칙으로 감점
assert any("과거 성과 나쁨" in x for x in r.loc["BAD", "risk"]), r.loc["BAD", "risk"]
config.RANK_NEWS_EVIDENCE = False                                                              # 관리 모드에서 끄면 예전 규칙
r2 = rank.compute().set_index("ticker")
assert "GOOD" not in r2.index or not any("과거 성과" in x for x in r2.loc["GOOD", "why"])
config.RANK_NEWS_EVIDENCE = True
db.set_meta("evscore", json.dumps({"built": "x", "validation": {"ok": False}, "table": tb}, ensure_ascii=False))
assert evscore.active() is None                                                               # 검증 실패면 안 씀
# --- 공시 알림 화면: 공시마다 '📊 과거 ±%p' 칩
i = evscore.for_feed_row(tb, {"items": "1.01", "tags": [], "updated": f"{T.isoformat()}T08:10:00-04:00"}, 0.6)
assert i["pp"] > 15 and i["level"] == "칸" and i["key"] == "계약·수주|$1 미만|장전" and evscore.chip_color(i["pp"]) == "green" and evscore.chip_color(-5) == "red"
from streamlit.testing.v1 import AppTest
os.environ["QUANT_TEST_PAGE"] = "alerts"
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]
md = " ".join(m.value for m in at.markdown)
assert "📊 과거 +" in md and "📊 과거 -" in md, md[:1500]
assert "· 참고" in md, md[:600]                                                     # 검증 미통과(위에서 ok=False) → 회색 '참고' 칩
os.environ.pop("QUANT_TEST_PAGE", None)
print("ALL OK")
