import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🕶 다크풀: 비중 계산(장외 ÷ 전체, 100 자름) · 20일 평균·괴리도·전일비·연속상승·급등 · 상위 표(잡음 제외) · 매집 동반 칩 · 화면(AppTest) · 종목 카드."""
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import pandas as pd
import db, darkpool as dp, shortdata, halts
db.init_db(); halts.fetch = lambda *a, **k: []
days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-10-23", periods=24)]
with closing(db.connect()) as conn:
    shortdata.ensure_tables(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS accum (date TEXT, ticker TEXT, period TEXT, score REAL, data TEXT, PRIMARY KEY (date, ticker, period))")
    for i, d in enumerate(days):
        # AAA: 평소 40% → 마지막 4일 55·60·70·90 (연속상승 + 급등) · BBB: 늘 30% · CCC: 장외 2만 주(잡음 제외) · DDD: 일봉 없음(비중 계산 불가)
        pa = [0.40] * 20 + [0.55, 0.60, 0.70, 0.90]
        conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (d, "AAA", 500_000 * pa[i] * 0.5, 0, 1_000_000 * pa[i]))
        conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (d, "BBB", 100_000, 0, 300_000))
        conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (d, "CCC", 10_000, 0, 20_000))
        conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (d, "DDD", 900_000, 0, 900_000))
        for t in ("AAA", "BBB", "CCC"):
            db.upsert_daily_prices(conn, t, pd.DataFrame({"Open": [1.0], "High": [1.1], "Low": [0.9], "Close": [1.0], "Volume": [1_000_000 if t != "CCC" else 20_000]}, index=pd.to_datetime([d])))
    conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (days[-1], "AAA", "일간", 5.0, "{}"))
    import themes; themes.ensure_tables(conn)
    for t in ("AAA", "BBB", "CCC"):   # 우리 종목 목록에 있는 것만 상위 표(ETF 는 장외 100만 주↑일 때만)
        conn.execute("INSERT OR REPLACE INTO ticker_meta (ticker, name, sic, sic_desc, themes, updated) VALUES (?,?,?,?,?,?)", (t, t, 0, "", "[]", "x"))
    conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (days[-1], "ETFX", 150_000, 0, 150_000))
    db.upsert_daily_prices(conn, "ETFX", pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [150_000]}, index=pd.to_datetime([days[-1]])))
    conn.commit()
    s = dp.series(conn, "aaa")
    assert len(s) == 24 and abs(s["dp_pct"].iloc[-1] - 90.0) < 1e-9 and abs(s["short_pct"].iloc[-1] - 25.0) < 1e-9, s.tail(2)
    st_ = dp.summary(conn, "AAA")
    assert st_["date"] == days[-1] and abs(st_["dp_pct"] - 90) < 1e-9 and st_["rising"] and st_["spike"] and abs(st_["prev_diff"] - 20) < 1e-9
    assert 40 < st_["avg20"] < 50 and st_["gap"] > 40 and len(st_["trend"]) == 5, st_                     # 평균은 마지막 날을 뺀 20일
    assert dp.summary(conn, "DDD") == {} and dp.series(conn, "NONE").empty                                  # 일봉 없으면 비중 없음
    day, top = dp.top(conn, n=30)
    assert day == days[-1] and list(top["ticker"]) == ["AAA", "BBB"] and top.iloc[0]["flags"] == ["급등", "연속상승", "매집의심"] and top.iloc[1]["flags"] == []   # CCC 는 10만 주 미만 · ETFX 는 목록 밖 15만 주 제외
    assert abs(top.iloc[1]["dp_pct"] - 30) < 1e-9 and abs(top.iloc[1]["gap"]) < 1e-9 and len(top.iloc[0]["trend"]) == 5
    fm = dp.flag_map(conn); assert set(fm) == {"AAA"} and fm["AAA"].startswith("DP 90%") and "+" in fm["AAA"]
    # 장외 > 전체×1.05 인 날은 일봉이 아직 장중 값(미완성) → 그날은 비중 없음(앞날 값으로), 1.05 안쪽은 100 으로 자름
    conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", ("2026-10-26", "BBB", 0, 0, 2_000_000))
    db.upsert_daily_prices(conn, "BBB", pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1_000_000]}, index=pd.to_datetime(["2026-10-26"])))
    conn.commit()
    assert dp.summary(conn, "BBB")["date"] == days[-1] and abs(dp.summary(conn, "BBB")["dp_pct"] - 30) < 1e-9
    db.upsert_daily_prices(conn, "BBB", pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1_950_000]}, index=pd.to_datetime(["2026-10-26"])))
    conn.commit()
    assert dp.summary(conn, "BBB")["dp_pct"] == 100.0 and dp.summary(conn, "BBB")["date"] == "2026-10-26"
    conn.execute("DELETE FROM finra_shvol WHERE date='2026-10-26'"); conn.commit()
# 감시 대상 밖·미완성 의심 종목 일봉 다시 받기: DDD(일봉 없음)와 2M/1M 인 BBB → 가짜 다운로드로 채움
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", ("2026-10-26", "BBB", 0, 0, 2_000_000))
    db.upsert_daily_prices(conn, "BBB", pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1_000_000]}, index=pd.to_datetime(["2026-10-26"])))
    conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", ("2026-10-26", "DDD", 900_000, 0, 900_000))
    conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", ("2026-10-26", "AAA", 400_000, 0, 500_000))
    db.upsert_daily_prices(conn, "AAA", pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1_000_000]}, index=pd.to_datetime(["2026-10-26"])))
    conn.commit()
    assert dp.stale_symbols(conn) == ["BBB", "DDD"], dp.stale_symbols(conn)      # 장중 값 의심(BBB) 먼저, 일봉 없음(DDD) 다음
calls = []
def fake_dl(tk):
    calls.append(list(tk))
    return {t: pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [4_000_000]}, index=pd.to_datetime(["2026-10-26"])) for t in tk}
assert dp.refresh_volumes(download=fake_dl, out=lambda *_: None) == 2 and calls == [["BBB", "DDD"]]
with closing(db.connect()) as conn:
    assert dp.stale_symbols(conn) == [] and abs(dp.summary(conn, "DDD")["dp_pct"] - 22.5) < 1e-9 and dp.summary(conn, "BBB")["dp_pct"] == 50.0
    conn.execute("DELETE FROM finra_shvol WHERE date='2026-10-26'"); conn.execute("DELETE FROM daily_prices WHERE date='2026-10-26'"); conn.commit()
# 화면
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-16", "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "darkpool"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
tb = [d.value for d in at.dataframe if "DP%" in d.value.columns][0]
assert list(tb["티커"]) == ["AAA", "BBB"] and tb.iloc[0]["신호"] == "급등 · 연속상승 · 매집의심" and tb.iloc[0]["5일 추이"] == "40 → 55 → 60 → 70 → 90"
at.radio(key="dp_flt").set_value("연속상승").run(); assert not at.exception
assert list([d.value for d in at.dataframe if "DP%" in d.value.columns][0]["티커"]) == ["AAA"]
# 종목 카드(🏢 종목 화면 펼침에 쓰는 함수)
CARD = """
import os, sys; sys.path.insert(0, os.environ["QS_ROOT"])
import streamlit as st, darkpool_ui
darkpool_ui.card("AAA", key="t")
darkpool_ui.card("NONE", key="t2")
"""
at2 = AppTest.from_string(CARD, default_timeout=60).run(); assert not at2.exception, [e.value for e in at2.exception]
html = "\n".join(m.value for m in at2.markdown)
assert "90.0%" in html and "급등" in html and any("다크풀 기록이 없어요" in c.value for c in at2.caption) and [b for b in at2.button if b.key.startswith("cp_btn_")]
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
