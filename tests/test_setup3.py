import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, setup3 as s3, secbackfill
db.init_db()
T = date.today()


def bars(close, vol, start="2025-01-02"):
    idx = pd.bdate_range(start=start, periods=len(close))
    c = np.asarray(close, float)
    return pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": np.asarray(vol, float)}, index=idx)


# --- ① 돈 들어온 거래량(OBV)
up = bars(np.r_[np.full(30, 1.0), np.linspace(1.0, 1.3, 10)], np.r_[np.full(30, 1e5), np.full(10, 3e5)])
m = s3.money_flow(up); assert m["ok"] and m["strong"] and "강한 유입" in m["label"], m
saf = bars(np.r_[np.full(30, 1.0), [1.0, 1.05] * 5], np.r_[np.full(30, 1e5), np.tile([3e5, 1e5], 5)])   # 오를 땐 적게, 내릴 땐 많이 → 거래량만 늘고 OBV 하락
m2 = s3.money_flow(saf); assert m2["ok"] is False and "사팔이" in m2["label"], m2
assert s3.money_flow(bars([1, 2, 3], [1, 1, 1]))["ok"] is None and s3.money_flow(None)["label"] == "봉 부족"

# --- ② 지지선 · 과매도
base = []
for k in range(4):   # 1.0 근처에서 4번 바닥 → 반등
    base += list(np.linspace(1.3, 1.0, 12)) + list(np.linspace(1.0, 1.3, 12))
base += list(np.linspace(1.3, 1.04, 10))
sp = s3.support_or_oversold(bars(base, np.full(len(base), 1e5)))
assert sp["support"] is not None and sp["touches"] >= 3 and "지지선" in sp["label"], sp
assert sp["ok"] == sp["oversold"]                                                           # ② 판정은 과매도(지지선은 참고)
dn = s3.support_or_oversold(bars(np.linspace(2.0, 0.5, 60), np.full(60, 1e5)))
assert dn["ok"] and dn["oversold"] and "과매도" in dn["label"], dn
flat = s3.support_or_oversold(bars(np.linspace(1.0, 2.0, 60), np.full(60, 1e5)))
assert flat["ok"] is False, flat

# --- ③ 희석 부재: 기준일 '전에' 접수된 것만(컨닝 방지)
with closing(db.connect()) as conn:
    for d_ in secbackfill.DDL:
        conn.execute(d_)
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('a1','DIL','424B5',?, '')", ((T - timedelta(days=40)).isoformat(),))
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('a2','PIPE','8-K',?, '1.01,3.02')", ((T - timedelta(days=10)).isoformat(),))
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('a3','OK','8-K',?, '7.01')", ((T - timedelta(days=10)).isoformat(),))
    conn.commit()
    assert s3.dilution_absent("DIL", conn)["ok"] is False and s3.dilution_absent("PIPE", conn)["ok"] is False and s3.dilution_absent("OK", conn)["ok"] is True
    assert s3.dilution_absent("DIL", conn, as_of=(T - timedelta(days=41)).isoformat())["ok"] is True       # 공시 전날 기준 → 아직 모름
    assert s3.dilution_absent("DIL", conn, as_of=(T - timedelta(days=40)).isoformat())["ok"] is True       # 접수 당일도 제외(시각 모름)
    assert s3.dilution_absent("DIL", conn, as_of=(T - timedelta(days=39)).isoformat())["ok"] is False
    ev = s3.evaluate("OK", up, conn)
    assert ev["money"]["ok"] and ev["dilution"]["ok"] and ev["n_ok"] >= 2

# --- 🕰 타임머신: 미래 봉을 바꿔도 그날 판정은 그대로(컨닝 없음) · 결과는 미래로
import timemachine as tm
c = np.r_[np.full(120, 1.0) + np.sin(np.arange(120) / 3) * 0.05, np.linspace(1.0, 1.5, 30)]
v = np.r_[np.full(120, 2e5), np.full(30, 6e5)]
d1 = bars(c, v, start="2025-01-02")
d2 = d1.copy(); d2.iloc[-15:, d2.columns.get_loc("High")] *= 3; d2.iloc[-15:, d2.columns.get_loc("Close")] *= 3; d2.iloc[-15:, d2.columns.get_loc("Volume")] *= 10
s, e = d1.index[40].strftime("%Y-%m-%d"), d1.index[-1].strftime("%Y-%m-%d")
r1 = pd.DataFrame(tm.ticker_rows("X", d1, [], s, e, step=1)).set_index("date")
r2 = pd.DataFrame(tm.ticker_rows("X", d2, [], s, e, step=1)).set_index("date")
cut = d1.index[-16].strftime("%Y-%m-%d")                                                   # 바꾼 구간 전날까지의 판정
keep = [x for x in r1.index if x <= cut]
assert (r1.loc[keep, ["money", "strong", "sup", "dil"]] == r2.loc[keep, ["money", "strong", "sup", "dil"]]).all().all()   # 조건은 같음
assert (r2.loc[cut, "max_up"] > r1.loc[cut, "max_up"])                                      # 결과(미래)는 바뀜
dday = d1.index[100].strftime("%Y-%m-%d")
rd = pd.DataFrame(tm.ticker_rows("X", d1, [(d1.index[90]).strftime("%Y-%m-%d")], s, e, step=1)).set_index("date")
assert rd.loc[dday, "dil"] == False and rd.loc[d1.index[90].strftime("%Y-%m-%d"), "dil"] == True   # 공시일 당일 판정엔 그 공시를 모름
# '+30% 먼저': −20% 에 먼저 닿으면 실패 · 같은 날 둘 다면 보수적으로 실패 · 공시 이력 없으면 ③ 은 '모름'(False)
cc2 = np.r_[np.full(100, 1.0) + np.sin(np.arange(100) / 3) * 0.05]
up_first = bars(np.r_[cc2, [1.1, 1.35, 1.0, 0.7]], np.full(104, 2e5))
dn_first = bars(np.r_[cc2, [0.75, 1.4, 1.4, 1.4]], np.full(104, 2e5))
k = up_first.index[99].strftime("%Y-%m-%d")
ra = {x["date"]: x for x in tm.ticker_rows("U", up_first, [], k, k, step=1)}
rb = {x["date"]: x for x in tm.ticker_rows("D", dn_first, [], k, k, step=1)}
assert ra[k]["first"] is True and rb[k]["first"] is False and rb[k]["max_up"] >= 30 and rb[k]["min_dn"] <= -20, (ra[k], rb[k])
rc = {x["date"]: x for x in tm.ticker_rows("N", up_first, [], k, k, step=1, covered=False)}
assert rc[k]["dil"] is False and rc[k]["covered"] is False
# 병합 단위가 섞인 날: 가격 1/64 · 거래량 64배(금액 그대로) → 그 앞뒤는 판정 안 함 · 진짜 폭락(금액도 크게 변함)은 그대로
cs = (np.r_[np.full(150, 64.0) + np.sin(np.arange(150) / 3), np.full(60, 1.0) + np.sin(np.arange(60) / 3) / 64]) / 10   # 가격 상한($20) 아래로
vs_ = np.r_[np.full(150, 1e5), np.full(60, 64e5)]   # 거래대금 하한($5만) 위로
assert tm.split_artifacts(cs, vs_) == [150]
crash = np.r_[np.full(30, 1.0), np.full(10, 0.15)]; cv = np.r_[np.full(30, 1e5), np.full(10, 5e7)]
assert tm.split_artifacts(crash, cv) == []                                                  # 진짜 폭락(금액 75배)은 병합 아님
ra2 = tm.ticker_rows("S", bars(cs, vs_), [], "2000-01-01", "2100-01-01", step=1)
assert ra2 and all(not (110 <= list(bars(cs, vs_).index.strftime("%Y-%m-%d")).index(x["date"]) < 290) for x in ra2)
sm = tm.summarize(r1.reset_index())
assert "+30% 먼저(−20% 전)(%)" in sm["combos"][0] and sm["base_first"] is not None and sm["covered_pct"] == 100.0
assert any(x["조합"] == "🧲 매집형(가격↓·OBV↑)" for x in sm["combos"])
assert sm["n"] > 0 and sm["combos"][0]["조합"] == "전체(기준)" and any(x["조합"].startswith("✅ 3대 조건 모두") for x in sm["combos"])
assert any(x["조합"] == "💰 강한 유입+③" for x in sm["combos"]) and sm["horizons"] and {h["기간(거래일)"] for h in sm["horizons"]} <= {5, 10, 20, 40}
assert "기대값(%)" in sm["combos"][0] and sm["base_ev"] is not None
# 기대값 규칙: +30% 먼저면 +30, −20% 먼저면 −20, 둘 다 아니면 기간 끝 종가
assert ra[k]["exit10"] == 30.0 and rb[k]["exit10"] == -20.0
flat2 = bars(np.r_[cc2, np.full(12, 1.05)], np.full(112, 2e5))
rf = {x["date"]: x for x in tm.ticker_rows("F", flat2, [], k, k, step=1)}
assert abs(rf[k]["exit10"] - (1.05 / flat2["Close"].iloc[99] - 1) * 100) < 1e-6 and rf[k]["first10"] is False

# run: daily_prices + sec_hist → meta 저장
# 일봉이 부족하면 0건 대신 안내(예전 결과를 덮지 않음) · fill_history 로 채운 뒤 계산
r0 = tm.run(years=1.0, out=lambda *_: None)
assert r0.get("hint") and "--fill" in r0["hint"] and tm.load_result() is None
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO case_progress (ticker, status) VALUES ('AAA','done')") if conn.execute("SELECT name FROM sqlite_master WHERE name='case_progress'").fetchone() else None
    conn.commit()
_fx = {}
for t, df in (("AAA", d1), ("BBB", d2)):
    df2 = df.copy(); df2.index = pd.bdate_range(end=pd.offsets.BDay().rollback(pd.Timestamp(T - timedelta(days=30))), periods=len(df2)); _fx[t] = df2  # 끝이 주말이면 직전 영업일(개수 어긋남 방지)
n_f = tm.fill_history(years=1.0, download=lambda ts: {t: _fx[t] for t in ts if t in _fx}, out=lambda *_: None)
assert n_f >= 1, n_f
assert tm.fill_history(years=1.0, download=lambda ts: {t: _fx[t] for t in ts if t in _fx}, out=lambda *_: None) == 0   # 이미 시도한 종목은 다시 안 받음
res = tm.run(years=1.0, out=lambda *_: None)
rp = tm.replay("AAA", years=1.0)                                                            # 🕰 종목 하나 되돌려 보기
assert not rp.empty and {"up10", "strong", "supl", "ovs", "dil", "rsi", "sup_lv"} <= set(rp.columns)
assert tm.replay("NOPE").empty
assert res["n_tickers"] >= 1 and res["n"] > 0 and tm.load_result()["combos"], res.get("n")

# --- 🎯 장마감 체크리스트: 5분봉 OBV · 돈이 안 들어왔으면 BEST 불가
import closewatch as cw
mi = pd.date_range("2026-10-23 13:30", periods=360, freq="min", tz="UTC")
cc = np.r_[np.linspace(1.0, 0.8, 300), np.tile([0.80, 0.79], 30)]
reg = pd.DataFrame({"Close": cc, "Volume": np.r_[np.full(300, 1e4), np.tile([1e3, 5e4], 30)]}, index=mi)
vs = cw.volume_stats(reg, 1e6)
assert "obv5_ok" in vs and vs["obv5_ok"] is False, vs.get("obv5_label")
mm = {"drop_pct": -30, "vol_mult": 5, "decay": 0.3, "cs_late": 130, "cs_prior": 100, "thin_ratio": 0.4, "ask_minutes": 1, "top_ask_ratio": 1,
      "dilution_status": "CLEAN", "intraday_filings": [], "financing": {"sellable": "restricted", "date": "x", "type": "x", "label": "x"}, "shares_out": 1e6, "warrant_filings": []}
g_ok = cw.evaluate({**mm, "obv5_ok": True, "obv5_label": "💰"})["grade"]
g_bad = cw.evaluate({**mm, "obv5_ok": False, "obv5_label": "⚠️ 사팔이"})
assert g_ok == "BEST" and g_bad["grade"] != "BEST" and any(i["key"] == "money5" and i["status"] == "fail" for i in g_bad["items"]), (g_ok, g_bad["grade"])

# --- 🏆 성과 공표: 3대 조건 기록 → 출처로 집계
with closing(db.connect()) as conn:
    rows = [{"ticker": "OK", "all": True, "price": 1.2, "money": {"strong": True, "label": "💰 강한 유입"}, "support": {"label": "🧱 지지선"}},
            {"ticker": "NO", "all": False, "price": 1.0, "money": {"strong": False, "label": "x"}, "support": {"label": "x"}}]
    assert s3.record(conn, rows) == 1 and s3.record(conn, rows) == 0                  # 같은 종목 20일에 한 번
    import scoreboard as sb
    col = sb.collect(conn)
    assert (col["source"] == "setup3").sum() == 1 and "강한 유입" in col[col["source"] == "setup3"].iloc[0]["note"]

# --- 화면: ✅ 3대 조건(지금 후보 · 타임머신)
import watch_ui
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "OK", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.3, "high_20d": 1.3, "low_20d": 1.0,
        "drawdown_pct": -1.0, "day_change_pct": 3.0, "volume_mult": 3.0, "buy_pressure": 60.0, "float_shares": 1e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
watch_ui.prices = lambda tks: {"OK": up}
from streamlit.testing.v1 import AppTest
os.environ["QUANT_TEST_PAGE"] = "setup3"
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180)
at.query_params["v"] = "full"; at.run()
assert not at.exception, [e.value for e in at.exception]
assert any("3대 조건" in m.value for m in at.markdown) and at.dataframe, "지금 후보 표"
assert [b for b in at.button if b.key == "s3_go_tm"]                                             # 타임머신은 🏆 검증으로 옮김(버튼만 남음)
os.environ["QUANT_TEST_PAGE"] = "score"
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180)
at.query_params["v"] = "full"; at.run(); assert not at.exception, [e.value for e in at.exception]
at.button_group(key="tab_score").set_value("🕰 타임머신").run()
assert not at.exception and any(any(str(x).startswith("✅ 3대 조건 모두") for x in d.value.get("조합", [])) for d in at.dataframe), "타임머신 표"
os.environ.pop("QUANT_TEST_PAGE", None)
print("ALL OK")
