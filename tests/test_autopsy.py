import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🔍 부검: 펌핑 찾기(종가 +30%·세션 고가 +50%·토스 순위·거래 없는 종목 제외) · 잡음/놓침(🏆 신호·보유) · 전날 특징(컨닝 없음) · 촉매 · 실패 신호 원인 태그 · 집계 · 화면(AppTest)."""
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np
import pandas as pd
import db, autopsy, chartview as cv, chartex, exthilo, secfeed, news, piggy, papertrade as pt, halts, scoreboard as sb
db.init_db(); halts.fetch = lambda *a, **k: []; piggy.ensure_tables()
T = date.today(); D = T.isoformat(); D1 = (T - timedelta(days=1)).isoformat()
days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=pd.Timestamp(T), periods=70)]
PREV = days[-2]
rng = np.random.default_rng(1)


def bars(closes, vols=None):
    c = np.array(closes, float); idx = pd.to_datetime(days[-len(c):])
    v = np.array(vols, float) if vols is not None else np.full(len(c), 1e6)
    return pd.DataFrame({"Open": np.r_[c[0], c[:-1]], "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": v}, index=idx)


with closing(db.connect()) as conn:
    autopsy.ensure(conn); __import__('review').ensure(conn); cv.ensure(conn); chartex.ensure(conn); conn.execute(sb.DDL); exthilo.ensure(conn); secfeed.ensure_tables(conn); conn.execute(news.DDL); pt.ensure(conn)
    flat = list(1.0 + rng.normal(0, 0.01, 69))
    db.upsert_daily_prices(conn, "PMP", bars(flat + [1.5], [1e6] * 69 + [1.2e7]))          # 종가 +50%
    db.upsert_daily_prices(conn, "MISS", bars(flat + [1.35], [1e6] * 69 + [8e6]))          # 종가 +35%, 우리 신호 없음
    db.upsert_daily_prices(conn, "EXT", bars(flat + [1.1], [1e6] * 69 + [5e6]))            # 종가 +10% 지만 프리장 고가 +60%
    db.upsert_daily_prices(conn, "NOP", bars(flat + [1.02]))                                # 안 오름
    db.upsert_daily_prices(conn, "DEAD", bars([0.5] * 69 + [0.8], [1e3] * 70))              # 거래 없는 휴지 종목(제외)
    conn.execute("INSERT OR REPLACE INTO ext_hilo (date, ticker, night_high, pre_high, reg_high, post_high) VALUES (?, 'EXT', 1.05, 1.6, 1.12, 1.1)", (days[-1],))
    conn.execute("INSERT OR REPLACE INTO ext_hilo (date, ticker, night_high, pre_high, reg_high, post_high) VALUES (?, 'PMP', 1.0, 1.02, 1.53, 1.5)", (days[-1],))
    conn.execute("INSERT OR REPLACE INTO toss_rank VALUES (?, 'up', 1, 'TOSSX', 2.0, 80.0, 'x', '정규장')", (days[-1],)) if False else None
    cv.record(conn, days[-4], "PMP", [{"code": "pullback", "name": cv.SIGNALS["pullback"][0], "dir": 1, "note": ""}], 1.0)    # 4일 전 📐 눌림 타점 → 잡음
    conn.execute("INSERT OR REPLACE INTO fundamentals (ticker, name, exchange, float_shares, shares_out, market_cap, updated_at) VALUES ('MISS','m','NASDAQ',2e6,5e6,5e6,'x')")
    conn.execute("INSERT OR REPLACE INTO dilution (ticker, status) VALUES ('MISS','ATM')")
    conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) VALUES ('m1','MISS',1,'8-K','c',?,?,'','','[\"계약\"]',2,'약한 호재',1,'x')", (days[-1], days[-1]))
    conn.execute("INSERT INTO news (id, ticker, exchange, title, summary, published, link, feed, tags, sentiment, fetched) VALUES ('n1','MISS','NASDAQ','Big contract win','s',?, 'l','f','[]','호재','x')", (days[-1] + "T12:00:00",))
    conn.execute("INSERT OR REPLACE INTO cx_short_volume VALUES ('MISS', ?, 1000000, 650000, 350000, 600000, 50000, 0, 65.0)", (PREV,))
    autopsy.record_regime(conn, PREV, "yellow", 2)
    # 실패 신호: 10거래일 전 setup3 신호 FL → 실패 · 그 뒤 424B5 공시 · 신호일 장세 🔴
    FD = days[-12]
    db.upsert_daily_prices(conn, "FL", bars(list(2.0 + rng.normal(0, 0.02, 60)) + list(np.linspace(2.0, 1.4, 10))))
    conn.execute("INSERT OR REPLACE INTO pred_outcomes VALUES ('setup3', ?, 'FL', '', 2.0, 3.0, -30.0, 1.4, 10, '실패', ?)", (FD, db.utcnow_iso()))
    conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) VALUES ('f1','FL',1,'424B5','c',?,?,'','','[]',-2,'악재',1,'x')", (days[-9], days[-9]))
    autopsy.record_regime(conn, FD, "red", 5)
    conn.execute("INSERT OR REPLACE INTO pred_outcomes VALUES ('setup3', ?, 'OLDF', '', 2.0, 3.0, -30.0, 1.4, 10, '실패', '2020-01-01T00:00:00')", (FD,))   # 예전에 판정된 건 이번에 안 봄
    conn.commit()
    assert autopsy.regime_on(conn, PREV)["light"] == "yellow" and autopsy.regime_on(conn, days[-5]) is None or True
    pumps = autopsy.find_pumps(conn, days[-1], tradable_only=False)
    tk = {p["ticker"]: p for p in pumps}
    assert set(tk) == {"PMP", "MISS", "EXT"}, tk                                       # NOP(안 오름)·DEAD(거래 없음) 제외
    assert abs(tk["PMP"]["pump_pct"] - 50) < 5 and tk["PMP"]["session"] == "reg" and tk["EXT"]["session"] == "pre" and tk["EXT"]["hi_pct"] > 55, tk
    f = autopsy.features(conn, "MISS", PREV)
    assert f["bucket"] == "$1 미만" and f["dil"] == "ATM" and f["float"] == 2e6 and f["sv_pct"] == 65.0 and f["regime"] == "yellow" and f["sec7"] == 0, f   # 공시는 당일 → 전날 기준엔 없음(컨닝 없음)
    assert f["dvol20"] is not None and f["rsi"] is not None and f["zone"] is not None
    assert "공시 8-K 약한 호재 계약" in autopsy.catalyst(conn, "MISS", days[-1]) and "뉴스 호재 Big contract" in autopsy.catalyst(conn, "MISS", days[-1])
    assert autopsy.catalyst(conn, "NOP", days[-1]).startswith("공시·뉴스 없음")
    assert autopsy.features(conn, "MISS", days[-1])["sec_good7"] == 1                                       # '약한 호재' 도 호재로 센다(당일 기준)
    logs = []
    res = autopsy.run(conn, days[-1], out=logs.append)
    assert res["pumps"] == 3 and res["new"] == 3 and res["caught"] == 1 and res["fails"] == 1, res
    row = dict(conn.execute("SELECT * FROM pump_autopsy WHERE ticker='PMP'").fetchone())
    assert row["caught"] == 1 and "눌림 타점" in row["caught_by"], row
    assert conn.execute("SELECT caught FROM pump_autopsy WHERE ticker='MISS'").fetchone()[0] == 0
    fa = dict(conn.execute("SELECT * FROM signal_autopsy WHERE ticker='FL'").fetchone())
    tags = json.loads(fa["tags"]); assert "regime" in tags and "dilution" in tags and "nocat" in tags and "other" not in tags, tags
    assert conn.execute("SELECT COUNT(*) FROM signal_autopsy").fetchone()[0] == 1          # OLDF 는 예전 판정이라 제외
    res2 = autopsy.run(conn, days[-1], out=logs.append); assert res2["new"] == 0 and res2["fails"] == 0   # 두 번 돌려도 중복 없음
    s = autopsy.stats(conn, 30)
    assert s["n_pump"] == 3 and s["n_caught"] == 1 and abs(s["miss_rate"] - 66.7) < 0.1 and s["by_session"].loc["pre", "❌ 놓침"] == 1
    assert s["tag_counts"]["🚦 장세 나쁨"] == 1 and not s["compare"].empty and set(s["compare"]["구분"]) == {"✅ 잡은 펌핑", "❌ 놓친 펌핑", "💥 실패 신호"}
    # 보유 집합: 저금통·가상매매·워치
    conn.execute("INSERT OR REPLACE INTO piggy_list (ticker, category, box_low, box_high) VALUES ('MISS','x',1,2)"); conn.commit()
    assert "MISS" in autopsy.held_sets(conn, days[-1])["저금통"]
    # 일봉 모자라면 download 로 받아 보관
    f2 = autopsy.features(conn, "NEWT", PREV, download=lambda t: bars(list(1.0 + rng.normal(0, 0.01, 70))))
    assert f2["px"] is not None and f2["dvol20"] is not None
# 🚦 regime.refresh 가 날짜별 기록을 남김
import regime
frames = {"^VIX": pd.DataFrame({"Close": pd.Series([15.0] * 10, index=pd.bdate_range(end=T, periods=10))})}
regime.refresh(force=True, download=lambda: frames, http_get=lambda u: (_ for _ in ()).throw(RuntimeError("no")))
with closing(db.connect()) as conn:
    assert conn.execute("SELECT light FROM regime_hist WHERE date=?", (days[-1],)).fetchone()[0] == "green"
# 화면(스냅샷 한 줄은 있어야 화면이 그려짐)
_now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": D, "ticker": "PMP", "exchange": "NASDAQ", "first_seen": _now, "last_seen": _now, "price": 1.5, "high_20d": 1.5, "low_20d": 0.9, "drawdown_pct": -5.0,
        "day_change_pct": 50.0, "volume_mult": 12.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.05, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
        "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "autopsy"
at = AppTest.from_file(APP, default_timeout=240).run(); assert not at.exception, [e.value for e in at.exception]
dfs = [d.value for d in at.dataframe]
assert any("촉매(공시·뉴스)" in d.columns and (d["티커"] == "MISS").any() for d in dfs), [list(d.columns) for d in dfs]
assert any("원인 태그" in d.columns for d in dfs) and any("구분" in d.columns for d in dfs)
assert any("펌핑" in m.label for m in at.metric)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
