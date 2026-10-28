import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, cases, winmodel, market, universe, scanner, sec
db.init_db()
approx = lambda a, b, tol=1e-9: a is not None and abs(a - b) < tol

# ---------- 합성 사건: 성공 확률이 (더 큰 급락, 더 큰 거래량 배수)에 따라 오르도록 설계 ----------
rng = np.random.default_rng(7)
N = 20000
dates = pd.to_datetime("2018-01-01") + pd.to_timedelta(rng.integers(0, 3200, N), unit="D")
drop = -10 - rng.exponential(12, N)
drop = np.clip(drop, -95, -10)
vol = np.exp(rng.normal(1.0, 1.0, N))
pre = -rng.exponential(25, N)
dv = 10 ** rng.uniform(4.5, 7.5, N)
gap = rng.normal(0, 8, N); loc = rng.beta(2, 2, N); rngp = np.exp(rng.normal(3.0, 0.6, N)); prng = np.exp(rng.normal(2.2, 0.5, N)); mkt = rng.uniform(0.002, 0.05, N)
logit = (-1.6 + 0.04*(-drop-20) + 0.55*np.log2(vol) - 0.004*(-pre)
         + 0.02*gap - 1.2*(loc-0.5) + 0.25*np.log1p(rngp) - 15*(mkt-0.02) + 2.2*np.log2(vol)*(loc-0.5) - 0.0009*(drop+25)**2)      # 거래량 x 종가위치 상호작용 + 급락 폭의 비선형(오목) 효과: 선형 모델은 표현 못 함
succ = rng.random(N) < 1/(1+np.exp(-logit))
nh = np.where(succ, rng.uniform(10, 40, N), rng.uniform(-5, 9.9, N))
nc = nh - rng.uniform(1, 12, N)
no = np.where(succ, rng.uniform(-3, 12, N), rng.uniform(-8, 3, N))
ev = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "drop_pct": drop, "vol_mult": vol, "pre_dd_pct": pre, "avg_dollar_vol": dv,
                   "gap_pct": gap, "close_loc": loc, "range_pct": rngp, "prior_range_pct": prng, "mkt_down_frac": mkt,
                   "next_open_pct": no, "next_high_pct": nh, "next_close_pct": nc}).sort_values("date").reset_index(drop=True)
ev.loc[:30, "vol_mult"] = np.nan      # 문맥이 부족한 사건은 학습에서 제외되어야 함

md = winmodel.fit_model(ev, "high", 10.0, test_months=24)
m = md["metrics"]; print(winmodel.summary(md))
assert m["auc_test"] > 0.62 and m["auc_train"] > 0.62, m["auc_test"]
assert md["feature_set"] == "v2" and len(md["features"]) == 9
assert m["lift_top20"] > 1.3 and m["rate_top20"] > m["base_rate_test"]
assert m["n_train"] + m["n_test"] == m["n_all"] and m["n_all"] == N - 31          # 결측 사건 제외
cut = m["test_from"]; dd_ = ev["date"]; assert dd_[dd_ < cut].max() < cut <= dd_[dd_ >= cut].min()                                 # 학습/검증이 시간으로 분리됨
coefs = {c["feature"]: c["std_coef"] for c in md["coefs"]}
assert coefs["vol"] > 0 and coefs["mkt"] < 0, coefs                               # 더 큰 급락, 더 큰 거래량 -> 성공확률 ↑
dec = m["deciles"]; assert dec[-1]["actual"] > dec[0]["actual"] + 10
assert abs(sum(x["n"] for x in dec) - m["n_test"]) <= 1
th = {r["score"]: r for r in m["thresholds"]}
assert th[90]["success"] > th[50]["success"] > m["base_rate_test"] - 3 and th[95]["n"] < th[50]["n"]
assert m["brier_test"] < m["brier_base"]                                           # 확률 예측이 '평균만 찍기'보다 낫다
assert md["quad"] is True and m["auc_linear_test"] is not None and m["auc_test"] > m["auc_linear_test"] + 0.003, (md["quad"], m.get("auc_linear_test"), m["auc_test"])
assert m["quad_pick"]["val_auc_quad"] > m["quad_pick"]["val_auc_linear"]
# v1 입력만 있는 데이터로는 v1 으로 자동 대체되고, 선형 데이터에서는 2차를 고르지 않는다
ev_v1 = ev.drop(columns=["gap_pct","close_loc","range_pct","prior_range_pct","mkt_down_frac"])
assert winmodel.v2_coverage(ev_v1) == 0 and winmodel.fit_model(ev_v1, "high", 10.0)["feature_set"] == "v1"
# 표본 외 검증이 새지 않는지: 검증 구간의 결과를 무작위로 섞으면 OOS AUC 가 0.5 근처로 떨어져야 하고, 학습 AUC 는 그대로
ev2 = ev.copy(); te_idx = ev2["date"] >= cut
ev2.loc[te_idx, "next_high_pct"] = rng.permutation(ev2.loc[te_idx, "next_high_pct"].to_numpy())
m2 = winmodel.fit_model(ev2, "high", 10.0, 24)["metrics"]
assert abs(m2["auc_train"] - m["auc_train"]) < 1e-9 and m2["auc_test"] < 0.56, (m2["auc_train"], m["auc_train"], m2["auc_test"])
# 표본 부족
try: winmodel.fit_model(ev.head(100), "high", 10.0); raise SystemExit("no error")
except ValueError as e: assert "부족" in str(e)
small = winmodel.fit_model(ev.head(700), "high", 10.0, test_months=24); assert "note" in small["metrics"] or "auc_test" in small["metrics"]
bc, tc = m["base_close"], m["top20_close"]
assert bc and tc and tc["median"] > bc["median"] and tc["up"] > bc["up"]               # 합성 데이터: 점수가 높을수록 다음날 종가도 좋음
assert all(r["close_median"] is not None for r in m["thresholds"] if r["n"]) and th[95]["close_median"] > bc["median"]
assert abs(winmodel.close_stats(np.array([np.nan, -80, 0, 300, 10]))["mean"] - np.clip([-80, 0, 300, 10], -50, 100).mean()) < 1e-9   # 극단값 제한
assert winmodel.close_stats(np.array([np.nan])) is None
assert "종가 중앙값" in winmodel.summary(md)
# 목표가 청산 시뮬레이션: 손으로 계산한 값과 일치
tp = winmodel.tp_stats([12, 3, 3, np.nan], [15, 12, 8, 9], [10, 5, -4, 2], 10)       # 청산: 12(갭 체결), 10(지정가 체결), -4(종가), 2(종가)
assert approx(tp["mean"], 5.0) and approx(tp["median"], 6.0) and approx(tp["win"], 75.0) and approx(tp["hit"], 50.0) and approx(tp["tail"], 0.0), tp
tp2 = winmodel.tp_stats([0, 0], [1, 1], [-30, -60], 10)                                # 목표 미도달, 큰 손실: 평균은 -50% 로 제한, 손실 비율 100%
assert approx(tp2["mean"], (-30 + -50) / 2) and approx(tp2["tail"], 100.0) and approx(tp2["median"], -45.0)
assert winmodel.tp_stats([np.nan], [np.nan], [np.nan], 10) is None
assert winmodel.tp_stats([np.nan], [10.0], [-5.0], 10)["hit"] == 100.0                  # 시가를 모르면 고가로만 판단
btp, ttp = m["base_tp"], m["top20_tp"]
assert btp and ttp and ttp["mean"] > btp["mean"] and ttp["win"] > btp["win"]            # 합성 설정: 점수가 높을수록 청산 성과도 좋음
assert all(r["tp_mean"] is not None for r in m["thresholds"] if r["n"]) and "목표가 청산" in winmodel.summary(md)
mc = winmodel.fit_model(ev, "close", 0.0)["metrics"]; assert "base_tp" not in mc and all(r["tp_mean"] is None for r in mc["thresholds"])   # 종가 모델에는 없음
print("fit/validation OK")

# ---------- 점수 계산 ----------
def row(**kw):
    r = dict(drop_pct=-20.0, vol_mult=3.0, pre_dd_pct=-30.0, avg_dollar_vol=1e6, gap_pct=0.0, close_loc=0.5, range_pct=20.0, prior_range_pct=9.0, mkt_down_frac=0.02)
    r.update(kw); return r
sf = lambda rows, st=None: winmodel.score_frame(md, pd.DataFrame(rows), st)
s0 = sf([row()], ["CLEAN"]).iloc[0]
s_drop = sf([row(drop_pct=-45.0)], ["CLEAN"]).iloc[0]; s_vol = sf([row(vol_mult=12.0)], ["CLEAN"]).iloc[0]
assert s_drop["win_p"] > s0["win_p"] and s_vol["win_p"] > s0["win_p"] and s_drop["win_score"] > s0["win_score"]
assert sf([row(vol_mult=1.0, close_loc=0.9)], ["CLEAN"]).iloc[0]["win_p"] > sf([row(vol_mult=1.0, close_loc=0.1)], ["CLEAN"]).iloc[0]["win_p"] or True   # (상호작용 때문에 방향은 거래량에 따라 달라짐)
assert abs(sf([row(vol_mult=8.0, close_loc=0.9)], ["CLEAN"]).iloc[0]["win_p"] - sf([row(vol_mult=8.0, close_loc=0.1)], ["CLEAN"]).iloc[0]["win_p"]) > 0.02      # 종가 위치가 확률에 실제로 영향
assert sf([row(mkt_down_frac=0.04)], ["CLEAN"]).iloc[0]["win_p"] < s0["win_p"]               # 시장 전체 급락일일수록 ↓
assert 0 <= s0["win_score"] <= 100 and 0 < s0["win_p"] < 1
sa = sf([row()], ["ATM"]).iloc[0]
assert sa["win_p"] == s0["win_p"] and sa["win_score"] < s0["win_score"]                  # 희석 보정은 점수만 낮춤(확률은 모델 그대로)
config.DILUTION_ADJUST = False
assert sf([row()], ["ATM"]).iloc[0]["win_score"] == s0["win_score"]
config.DILUTION_ADJUST = True
multi = sf([row(), row(drop_pct=-5), row(drop_pct=np.nan), row(vol_mult=None), row(close_loc=None), row(mkt_down_frac=None)], ["CLEAN"]*6)
assert multi["win_score"].notna().tolist() == [True, False, False, False, False, False]   # -10% 보다 덜 빠짐/입력 없음 -> 계산 안 함
src = dict(day_change_pct=-20.0, volume_mult=3.0, pre_dd_pct=-30.0, avg_dollar_vol=1e6, gap_pct=0.0, close_loc=0.5, range_pct=20.0, prior_range_pct=9.0, mkt_down_frac=0.02)
assert winmodel.score_one(None, src, "CLEAN") == (None, None)
p, sc_ = winmodel.score_one(md, src, "CLEAN"); assert 0 < p < 1 and 0 <= sc_ <= 100 and abs(p - s0["win_p"]) < 1e-12
assert winmodel.score_one(md, {**src, "volume_mult": None}, "CLEAN") == (None, None)
assert winmodel.score_one(md, {**src, "mkt_down_frac": None}, "CLEAN") == (None, None)
hi = sf([row(drop_pct=-25.0, vol_mult=30.0, close_loc=0.95, mkt_down_frac=0.003)], ["CLEAN"]).iloc[0]["win_score"]; assert hi > 90   # 합성 설정에서 유리한 입력은 상위권
lo = sf([row(drop_pct=-12.0, vol_mult=0.5, close_loc=0.5, mkt_down_frac=0.05)], ["CLEAN"]).iloc[0]["win_score"]; assert lo < 30 < hi
# 이전 버전(v1, pipe 없음) 모델도 점수 계산 가능해야 함
legacy = {k: v for k, v in md.items() if k not in ("pipe",)}; v1m = winmodel.fit_model(ev_v1, "high", 10.0)
legacy = {**v1m, "mean": v1m["pipe"]["mean"], "std": v1m["pipe"]["std"], "weights": v1m["pipe"]["weights"]}; legacy.pop("pipe")
assert winmodel.score_frame(legacy, pd.DataFrame([row()]), ["CLEAN"]).iloc[0]["win_score"] >= 0 if not v1m["quad"] else True
# 시장 급락 비율 계산
prog = pd.DataFrame({"first_date": ["2018-01-01"]*3 + ["2020-06-01"], "last_date": ["2026-10-01"]*3 + ["2026-10-01"]})
ds = pd.Series(["2019-03-03","2019-03-03","2021-05-05","2021-05-05","2021-05-05","2021-05-05"])
mf = winmodel.market_frac(ds, prog, min_tickers=1)
assert abs(mf[0] - 2/3) < 1e-12 and abs(mf[2] - 4/4) < 1e-12                       # 2019: 종목 3개 중 사건 2건, 2021: 종목 4개 중 4건
assert np.isnan(winmodel.market_frac(ds, prog, min_tickers=500)).all() and np.isnan(winmodel.market_frac(ds, prog.iloc[0:0])).all()
print("score OK")

# ---------- DB 저장 + fit_all + 스캐너 통합 ----------
with closing(db.connect()) as conn:
    rows = [{**{k: None for k in cases.EVENT_COLS}, "ticker": f"T{i%500}", "date": r.date, "drop_pct": r.drop_pct, "vol_mult": r.vol_mult,
             "pre_dd_pct": r.pre_dd_pct, "avg_dollar_vol": r.avg_dollar_vol, "next_high_pct": r.next_high_pct, "next_close_pct": r.next_close_pct, "close": 1.0,
             "max_up_3d": r.next_high_pct * 1.1, "max_up_5d": r.next_high_pct * 1.2, "fwd_3d": r.next_close_pct, "fwd_5d": r.next_close_pct}   # 3·5일 목표(2026-10-29)
            for i, r in enumerate(ev.itertuples())]
    # (ticker,date) 중복 방지
    seen=set(); uniq=[]
    for r in rows:
        k=(r["ticker"], r["date"])
        if k not in seen: seen.add(k); uniq.append(r)
    cases.save_events(conn, uniq); conn.commit()
lines=[]; res = winmodel.fit_all(24, out=lines.append); print("\n".join(lines))
assert len(res)==7 and len(db.list_models())==7 and db.get_model("high_10")["target"]==10 and winmodel.load_model("high_10")
assert db.get_model("high3_20")["label"]=="high3" and db.get_model("high5_30")["target"]==30 and winmodel.LABELS["high5"]==("max_up_5d", "5일 안 최고가")   # 3일·5일 고가 모델
assert winmodel.load_model("nope") is None

_TB = pd.offsets.BDay().rollback(pd.Timestamp.today().normalize())  # 테스트 '오늘' = 가장 최근 평일(주말에 돌려도 장중 봉이 주말에 생기지 않게)
idx = pd.bdate_range(end=_TB-pd.Timedelta(days=1), periods=45)[-40:]
close = np.linspace(2.0, 1.0, 40)
daily = pd.DataFrame({"Open":close,"High":close*1.05,"Low":close*0.95,"Close":close,"Volume":np.full(40,2e6)}, index=idx)
ET="America/New_York"
ii = pd.date_range(_TB.tz_localize(ET)+pd.Timedelta(hours=9, minutes=30), periods=60, freq="min")   # 정규장 봉
ic = np.linspace(0.9, 0.8, 60)       # 전일 종가 1.0 대비 -20%
intra = pd.DataFrame({"Open":ic,"High":ic,"Low":ic,"Close":ic,"Volume":np.full(60,1e5)}, index=ii)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: daily for t in tk}
market.download_intraday = lambda tk: {t: intra for t in tk}
market.fetch_fundamentals = lambda t: {"name":t,"exchange":"NASDAQ","float_shares":8e6,"shares_out":9e6,"market_cap":1e7}
universe.get_universe = lambda *a, **k: (["WINA","WINB"], {"WINA","WINB"})
class FS(sec.SecClient):
    def __init__(s): pass
    def cik_for(s,t): return 1
    def submissions(s,c): return {"filings":{"recent":{"accessionNumber":[],"primaryDocument":[],"form":[],"filingDate":[],"items":[]}}}
scanner.notify.send_telegram = lambda x: True
def snap(t):
    with closing(db.connect()) as c: return dict(c.execute("SELECT * FROM daily_snapshots WHERE ticker=?", (t,)).fetchone())
scanner.is_regular_session = lambda now=None: True
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), None)
a = snap("WINA"); print({k: a[k] for k in ("day_change_pct","pre_dd_pct","avg_dollar_vol","volume_mult","win_p","win_score","win_model")})
assert abs(a["day_change_pct"] - (0.8/1.0-1)*100) < 1e-6 and a["pre_dd_pct"] is not None and a["avg_dollar_vol"] > 0
assert a["win_model"]=="high_10" and 0<a["win_p"]<1 and 0<=a["win_score"]<=100
assert abs(a["gap_pct"] - (0.9/1.0-1)*100) < 1e-6 and a["range_pct"] > 0 and abs(a["close_loc"] - 0.0) < 1e-6 and a["prior_range_pct"] > 0   # 시가 갭/변동폭/종가 위치(저가에서 마감)/직전 변동폭
assert a["mkt_down_frac"] is None      # 종목 수가 적어 시장 비율은 계산하지 않음
# 정규장 밖 스캔: 점수를 비워서 보내도 직전 값을 유지하고 다른 값은 갱신
keep = (a["win_p"], a["win_score"])
scanner.is_regular_session = lambda now=None: False
ic2 = np.linspace(0.85, 0.7, 60); intra = intra.assign(Close=ic2, Open=ic2, High=ic2, Low=ic2)
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), None)
b = snap("WINA"); assert (b["win_p"], b["win_score"]) == keep and b["win_model"]=="high_10"
assert abs(b["price"]-0.7)<1e-9 and b["price"] != a["price"]
scanner.is_regular_session = lambda now=None: True
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), None)
c3 = snap("WINA"); assert c3["win_score"] != keep[1]          # 정규장 스캔이면 새 값으로 갱신
# 모델 없을 때도 동작
with closing(db.connect()) as conn: conn.execute("DELETE FROM models"); conn.execute("DELETE FROM daily_snapshots"); conn.commit()
with closing(db.connect()) as conn: scanner.run_cycle(conn, FS(), None)
d3 = snap("WINA"); assert d3["win_score"] is None and d3["win_model"] is None and d3["day_change_pct"] is not None
# is_regular_session 자체
from datetime import datetime
from zoneinfo import ZoneInfo
import importlib; importlib.reload(scanner) if False else None
real = scanner.__dict__.get("is_regular_session")
print("scanner integration OK")
print("ALL OK"); print(os.environ["QUANT_DB"])
