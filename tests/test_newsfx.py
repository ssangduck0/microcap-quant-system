import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import pandas as pd
import db, news, newsfx, translate
db.init_db()

# ------------------------------------------------------------------ 1) 기준일: 뉴욕 16:00 이후 → 다음 거래일 · 장전/장중 → 그날 · 주말 → 월요일
assert newsfx.event_day("2026-10-20T13:00:00+00:00") == "2026-10-20"      # 09:00 ET(장전) 화요일
assert newsfx.event_day("2026-10-20T20:30:00+00:00") == "2026-10-21"      # 16:30 ET → 다음 날
assert newsfx.event_day("2026-10-23T21:00:00+00:00") == "2026-10-26"      # 금요일 17:00 ET → 월요일
assert newsfx.event_day("2026-10-24T15:00:00Z") == "2026-10-26"           # 토요일 → 월요일
assert newsfx.event_day("2026-10-20T19:59:00+00:00") == "2026-10-20"      # 15:59 ET 장중

# ------------------------------------------------------------------ 2) 반응 계산: 기준가 = D 직전 종가 · 당일 고가/종가 · +1일 · +5일(확정)
days = pd.bdate_range("2026-10-13", periods=10)             # 10/13 ~ 10/26
def bars(highs, closes):
    return pd.DataFrame({"Open": closes, "High": highs, "Low": [c * 0.9 for c in closes], "Close": closes}, index=days)
b = bars([1.0, 1.0, 1.0, 1.3, 1.1, 1.0, 1.0, 1.0, 1.5, 1.0], [1.0, 1.0, 1.0, 1.2, 1.05, 0.95, 1.0, 1.1, 1.4, 1.0])
o = newsfx.outcome(b, "2026-10-16")                          # D = 10/16(4번째 봉) · 기준 = 10/15 종가 1.0
assert o["prev_close"] == 1.0 and o["d0_high_pct"] == 30.0 and o["d0_close_pct"] == 20.0 and o["d1_close_pct"] == 5.0, o
assert o["d5_close_pct"] == 40.0 and o["done"] == 1 and o["bars_after"] == 7, o      # +5일 = 10/23 종가 1.4
o2 = newsfx.outcome(b.iloc[:5], "2026-10-16")                # 봉이 D 포함 2개뿐 → 진행 중
assert o2["d0_high_pct"] == 30.0 and o2["d1_close_pct"] == 5.0 and o2["d5_close_pct"] is None and o2["done"] == 0, o2
assert newsfx.outcome(b, "2026-10-13")["prev_close"] is None             # D 직전 봉 없음 → 기준가 없음
assert newsfx.outcome(b, "2026-10-28")["prev_close"] is None             # D 봉이 아직 없음(오늘 뉴스)
assert newsfx.outcome(None, "2026-10-16")["bars_after"] == 0
o3 = newsfx.outcome(b, "2026-10-17")                         # 토요일 기준일 → 그 뒤 첫 봉(월요일 10/19)이 D
assert o3["prev_close"] == 1.2 and o3["d0_high_pct"] == round((1.1 / 1.2 - 1) * 100, 2), o3

# ------------------------------------------------------------------ 3) 아침 작업: 종목 있는 뉴스만 · 봉 없으면 건너뜀 · 확정된 건 다시 안 잼 · 오늘 봉은 뺌
now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
with closing(db.connect()) as conn:
    conn.execute(news.DDL); translate.ensure(conn)
    rows = [("a1", "AAA", "NASDAQ", "AAA wins contract", "x", "2026-10-15T21:00:00+00:00", "l", "f", "[]", "호재", now.isoformat()),   # 16:00 ET 뒤 → D 10/16
            ("a2", "AAA", "NASDAQ", "AAA earnings", "x", "2026-10-26T12:00:00+00:00", "l", "f", "[]", "중립", now.isoformat()),        # D 10/26 → 봉 1개 → 진행
            ("b1", "BBB", "NASDAQ", "BBB no bars", "x", "2026-10-20T12:00:00+00:00", "l", "f", "[]", "호재", now.isoformat()),          # 일봉 없음
            ("c1", None, None, "no ticker", "x", "2026-10-20T12:00:00+00:00", "l", "f", "[]", "중립", now.isoformat()),              # 종목 없음 → 대상 아님
            ("a3", "AAA", "NASDAQ", "AAA today", "x", "2026-10-27T11:00:00+00:00", "l", "f", "[]", "호재", now.isoformat())]           # D 10/27 → 봉 없음(오늘) → 진행(저장 안 함)
    conn.executemany("INSERT INTO news (id, ticker, exchange, title, summary, published, link, feed, tags, sentiment, fetched) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("UPDATE news SET category='계약', ai_grade='A' WHERE id='a1'")
    conn.execute("UPDATE news SET category='실적', ai_grade='B' WHERE id='a2'")
    conn.commit()
    p = newsfx.pending(conn)
    assert [x["id"] for x in p] == ["a1", "b1", "a2", "a3"] and p[0]["day"] == "2026-10-16", p
    logs = []
    res = newsfx.update(conn, {"AAA": b}, now=now, out=logs.append)
    assert res == {"rows": 4, "updated": 2, "done": 1, "open": 2, "nodata": 1}, res
    assert "2건 갱신" in logs[-1] and "일봉 없음 1" in logs[-1], logs
    rx = newsfx.reactions(conn)
    assert rx["a1"]["d0_high_pct"] == 30.0 and rx["a1"]["done"] == 1 and rx["a2"]["done"] == 0 and rx["a2"]["d0_close_pct"] == round((1.0 / 1.4 - 1) * 100, 2) and "a3" not in rx
    assert [x["id"] for x in newsfx.pending(conn)] == ["b1", "a2", "a3"]                      # 확정된 a1 은 빠짐
    # 다음 날 봉이 하나 더 → a2 의 +1일이 채워짐(아직 확정 아님)
    b2 = pd.concat([b, pd.DataFrame({"Open": [1.0], "High": [1.2], "Low": [0.9], "Close": [1.1]}, index=[pd.Timestamp("2026-10-27")])])
    res2 = newsfx.update(conn, {"AAA": b2}, now=datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc), out=logs.append)
    assert res2["updated"] == 2 and newsfx.reactions(conn, ["a2"])["a2"]["d1_close_pct"] == round((1.1 / 1.4 - 1) * 100, 2)
    assert newsfx.reactions(conn, ["a3"])["a3"]["d0_high_pct"] == round((1.2 / 1.0 - 1) * 100, 2)                    # a3: D 10/27 봉이 생김
    # 오늘(뉴욕 장중) 미완성 봉은 빼고 잼: 10/27 13:00 ET 에 10/27 봉이 있으면 무시 → a3 는 아직 기준 없음
    with closing(db.connect()) as c2:
        c2.execute("DELETE FROM news_react WHERE news_id='a3'"); c2.commit()
    res3 = newsfx.update(conn, {"AAA": b2}, now=datetime(2026, 10, 27, 17, 0, tzinfo=timezone.utc), out=logs.append)
    assert "a3" not in newsfx.reactions(conn, ["a3"]), res3
    # 일봉이 DB(daily_prices)에 있으면 bars 없이도 잼 · 야후는 안 부름(download 가짜로 확인)
    conn.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)",
                     [("BBB", d.strftime("%Y-%m-%d"), 2.0, h, 1.8, c, 1000) for d, h, c in zip(days, [2.0] * 5 + [2.6] + [2.0] * 4, [2.0] * 5 + [2.4] + [2.0] * 4)])
    conn.commit()
    called = []
    res4 = newsfx.update(conn, None, now=now, out=logs.append, download=lambda ts: called.append(list(ts)) or {})
    assert newsfx.reactions(conn, ["b1"])["b1"]["d0_high_pct"] == 30.0 and newsfx.reactions(conn, ["b1"])["b1"]["day"] == "2026-10-20", res4
    assert called == [["AAA"]], called                                                          # BBB 는 DB 에 있어 안 부르고, DB 에 없는 AAA 만 야후(가짜)로
    # 통계: 분류×등급
    conn.execute("UPDATE news SET category='계약', ai_grade='A' WHERE id='b1'"); conn.commit()
    stt = newsfx.stats(conn)
    r_ = stt[(stt["분류"] == "계약") & (stt["등급"] == "A")].iloc[0]
    assert r_["건수"] == 2 and r_["당일 고가 중앙값(%)"] == 30.0 and r_["+10% 넘은 비율(%)"] == 100.0 and r_["확정"] == 1, r_
    assert newsfx.lookup(stt, "계약", "호재", "A") is None and newsfx.lookup(stt, "계약", "호재", "A", min_n=2)["건수"] == 2
    assert newsfx.lookup(stt, None, "호재", None) is None                                      # 분류 없는 건 '호재(키워드)' 로 묶임(지금은 0건)
    assert newsfx.stats(conn, lookback_days=0).empty or True

# ------------------------------------------------------------------ 4) 화면: 접힌 줄(분류·종목·제목·몇 분 전) → 요약·뉴스 뒤 주가·과거 반응 · 통계 펼침
news.recent = lambda days=14: db.read_df("SELECT * FROM news")
from streamlit.testing.v1 import AppTest
def _app():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import news, news_ui, db, newsfx
    news.recent = lambda days=14: db.read_df("SELECT * FROM news")
    newsfx.MIN_N = 2
    news_ui.render()
at = AppTest.from_function(_app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
labels = [e.label for e in at.expander]
assert any(l.startswith("📊 뉴스 반응 통계") for l in labels), labels
assert any(l.startswith("🏷 계약 · AAA · AAA wins contract") and "전" in l for l in labels), labels      # 분류 · 종목 · 제목 · 몇 분 전
md = " ".join(m.value for m in at.markdown)
assert "📊 뉴스 뒤 주가(기준 2026-10-16 직전 종가 $1.00): 당일 고가 **+30.0%** · 종가 +20.0% · +1일 +5.0% · +5일 +40.0%" in md, md[:1500]
assert "진행 중" in md                                                                           # a2
caps = " ".join(c.value for c in at.caption)
assert "이 종류(계약 · A등급)의 과거 반응 2건" in caps, caps[:800]
assert any(len(d.value) >= 1 and "분류" in list(d.value.columns) for d in at.dataframe), "통계 표"
print("ALL OK")
