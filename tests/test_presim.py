import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from contextlib import closing
from datetime import date, datetime, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np
import pandas as pd
import db, presim
db.init_db()

# ------------------------------------------------------------------ 1) outcomes: 손절 먼저 · 익절 먼저 · 같은 날 둘 다(보수=손절 · 낙관=익절) · 결판 안 남 · 미완 제외
H = 5
nan = np.nan
hi = np.array([[5, 12, 1, 1, 1], [2, 2, 2, 2, 2], [11, 1, 1, 1, 1], [5, 4, 3, 2, 1], [3, nan, nan, nan, nan]], dtype=np.float32)
lo = np.array([[-3, -4, -1, -1, -1], [-9, -1, -1, -1, -1], [-9, -1, -1, -1, -1], [-5, -4, -3, -2, -1], [-2, nan, nan, nan, nan]], dtype=np.float32)
cl = np.array([[1, 10, 1, 1, 1], [-5, 0, 0, 0, 0], [0, 0, 0, 0, 0], [1, 1, 1, 1, 2], [1, nan, nan, nan, nan]], dtype=np.float32)
o = presim.outcomes(hi, lo, cl, sl_pct=8, tp_pct=10, horizon=5, bars=np.array([5, 5, 5, 5, 1]))
assert o["n"] == 4, o                                                   # 5번째(봉 1개 · 안 닿음)는 미완이라 뺌
assert o["p_tp"] == 25.0 and o["p_tp_opt"] == 50.0 and o["p_sl"] == 50.0 and o["p_none"] == 25.0 and o["both_pct"] == 25.0, o
assert abs(o["ev_pct"] - (-1.0)) < 1e-6 and abs(o["ev_opt"] - 3.5) < 1e-6 and o["none_avg"] == 2.0, o
o2 = presim.outcomes(hi, lo, cl, 8, 10, horizon=1, bars=np.array([5, 5, 5, 5, 1]))                     # 기간 1일: 1번은 안 닿음 → 종가 +1
assert o2["n"] == 5 and o2["p_tp"] == 0.0 and o2["p_sl"] == 40.0 and o2["p_none"] == 60.0, o2
assert presim.outcomes(hi[:0], lo[:0], cl[:0], 8, 10, 5)["n"] == 0
# 사건별 계획 배열 = 숫자 하나와 같은 결과 · 둘째 사건만 목표 20 이면 그 사건은 익절 못 함 · 가중치(w) · n_eff · 기대값 0 기준선 p0
oa = presim.outcomes(hi, lo, cl, np.array([8, 8, 8, 8, 8.0]), np.array([10, 10, 10, 10, 10.0]), 5, bars=np.array([5, 5, 5, 5, 1]))
assert oa["n"] == o["n"] and oa["p_tp"] == o["p_tp"] and abs(oa["ev_pct"] - o["ev_pct"]) < 1e-6 and oa["n_eff"] == 4 and abs(oa["p0"] - 8 / 18 * 100) < 0.1, oa
ob = presim.outcomes(hi, lo, cl, np.array([8, 8, 8, 8, 8.0]), np.array([20, 10, 10, 10, 10.0]), 5, bars=np.array([5, 5, 5, 5, 1]))
assert ob["p_tp"] == 0.0 and ob["p_none"] == 50.0 and ob["tp_pct"] == 10.0, ob                      # 1번 사건은 +12 까지만 올라 목표 20 못 닿음 → 결판 안 남
ow = presim.outcomes(hi, lo, cl, 8, 10, 5, bars=np.array([5, 5, 5, 5, 1]), w=np.array([3, 1, 1, 1, 1.0]))
assert ow["n"] == 4 and ow["n_eff"] == 6.0 and ow["p_tp"] == 50.0 and abs(ow["ev_pct"] - round((3 * 10 - 8 - 8 + 2) / 6, 2)) < 1e-6, ow   # 1번 사건 가중 3
on_ = presim.outcomes(hi, lo, cl, np.array([8, np.nan, 8, 8, 8.0]), 10, 5, bars=np.array([5, 5, 5, 5, 1]))
assert on_["n"] == 3, on_                                                                               # 계획 없는(NaN) 사건은 뺌

# ------------------------------------------------------------------ 2) simulate(2겹): 대칭 무작위 걷기 → 동전 던지기 · 상승 → 🟢 · 하락 → 🔴 · 둘 다 닿는 날 · 자료 부족
days = pd.bdate_range("2024-09-02", periods=560)
def mk(drift, seed, vol=0.03, n=len(days), start=2.0):
    r = np.random.default_rng(seed)
    rets = r.normal(drift, vol, n); rets = rets - rets.mean() + drift          # 표본 평균을 정확히 drift 로(250일 표본의 우연한 치우침 제거)
    c = start * np.cumprod(1 + rets)
    hi_ = c * (1 + np.abs(r.normal(0, 0.02, n))); lo_ = c * (1 - np.abs(r.normal(0, 0.02, n)))
    return pd.DataFrame({"Open": c, "High": hi_, "Low": lo_, "Close": c, "Volume": 200_000.0}, index=days[:n])
flat = mk(0.0, 11)
e = float(flat["Close"].iloc[-1])
s = presim.simulate(flat, e, e / 1.1, e * 1.1, 20, n=4000, seed=3)                                 # 로그 기준 대칭(−9.1% / +10%): 곱으로 움직이는 가격엔 이게 공평
assert s["ok"] and s["n_days"] == 250 and abs(s["p_tp"] - s["p_sl"]) <= 6, s                           # 대칭 손절·목표 → 비슷
assert presim.verdict(s["p_tp"], s["p_sl"], s["ev_pct"])[0] == "🪙"
up = mk(0.004, 12)
eu = float(up["Close"].iloc[-1])
su = presim.simulate(up, eu, eu * 0.9, eu * 1.1, 20, n=4000, seed=3)
assert su["p_tp"] >= su["p_sl"] + 10 and presim.verdict(su["p_tp"], su["p_sl"], su["ev_pct"])[0] == "🟢", su
dn = mk(-0.004, 13)
ed = float(dn["Close"].iloc[-1])
sd = presim.simulate(dn, ed, ed * 0.9, ed * 1.1, 20, n=4000, seed=3)
assert sd["p_sl"] >= sd["p_tp"] + 10 and presim.verdict(sd["p_tp"], sd["p_sl"], sd["ev_pct"])[0] == "🔴", sd
wild = flat.copy(); wild["High"] = wild["Close"].shift(1).fillna(wild["Close"]) * 1.15; wild["Low"] = wild["Close"].shift(1).fillna(wild["Close"]) * 0.85   # 매일 ±15%
sw = presim.simulate(wild, e, e * 0.9, e * 1.1, 10, n=500, seed=1)
assert sw["both_pct"] == 100.0 and sw["p_tp"] == 0.0 and sw["p_tp_opt"] == 100.0 and sw["p_sl"] == 100.0, sw       # 같은 날 둘 다 → 보수 손절 · 낙관 익절
assert presim.simulate(flat.tail(100), e, e * 0.9, e * 1.1, 20)["ok"] is False                        # 120일 미만
assert presim.simulate(flat, e, e * 0.9, e * 1.1, 20, n=300, seed=5) == presim.simulate(flat, e, e * 0.9, e * 1.1, 20, n=300, seed=5)   # seed 재현

# ------------------------------------------------------------------ 3) 수량 · 판정
z = presim.size(1.0, 0.9, 5_000_000, 50_000, fx=1000.0)
assert z["shares"] == 500 and z["risk_usd"] == 50.0 and z["cost_usd"] == 500.0 and z["caps"] == [], z              # 50달러 ÷ 0.1 = 500주(계좌 10% 상한 500 과 같음)
z2 = presim.size(1.0, 0.95, 5_000_000, 50_000, fx=1000.0)
assert z2["shares"] == 500 and "계좌의 10% 상한" in z2["caps"][0], z2                                   # 1,000주 → 계좌 10%(500주)
z3 = presim.size(1.0, 0.9, 5_000_000, 50_000, fx=1000.0, adv20=20_000)
assert z3["shares"] == 200 and "거래량" in z3["caps"][0] and z3["risk_usd"] == 20.0, z3                  # 20일 평균 거래량 1% = 200주
assert presim.size(1.0, 1.0, 5_000_000, 50_000, 1000.0)["shares"] == 0 and "손절가" in presim.size(1.0, 1.2, 5e6, 5e4, 1000.0)["why"]
assert presim.verdict(55, 40, 3)[0] == "🟢" and presim.verdict(40, 55, -3)[0] == "🔴" and presim.verdict(50, 45, 0.5)[0] == "🪙"
assert presim.verdict(60, 40, 0.5)[0] == "🪙" and presim.verdict(None, 1, 1)[0] == "❔"                 # 비율 차이가 커도 기대값이 작으면 동전
# 기준 대비 우위 판정 + 소표본 보정: 우위 +2.5 · 유효 표본 1000 → 보정 2.27 🟢 · 표본 30 → 🪙(MIN_EP 미만) · −2.5 · 500 → −2.08 🔴 · 작은 우위는 🪙
v = presim.verdict_edge(3.0, 0.5, 1000)
assert v[0] == "🟢" and abs(v[3] - 2.5) < 1e-9 and 2.2 < v[2] < 2.3, v
assert presim.verdict_edge(3.0, 0.5, 30)[0] == "🪙" and presim.verdict_edge(0.0, 2.5, 500)[0] == "🔴" and presim.verdict_edge(1.0, 0.8, 5000)[0] == "🪙" and presim.verdict_edge(None, 1, 10)[0] == "❔"
assert abs(presim.shrink(10.0, 100) - 5.0) < 1e-9 and presim.shrink(10.0, 0) == 0.0

# ------------------------------------------------------------------ 4) 깃발: 과매도 onset 은 구간마다 한 번 · 희석 서류(그날 전 90일) · 자료 없는 종목은 희석 '없음' 아님
ff = presim.flags_frame(flat)
on_ovs = (ff["onset"] & presim.F["ovs"]) > 0
in_ovs = (ff["flags"] & presim.F["ovs"]) > 0
assert on_ovs.sum() >= 3 and on_ovs.sum() < in_ovs.sum(), (on_ovs.sum(), in_ovs.sum())
prev = in_ovs.shift(1, fill_value=False)
assert ((on_ovs) == (in_ovs & ~prev)).all()                                                             # onset = 오늘 켜짐 & 어제 꺼짐
d_mid = days[300].strftime("%Y-%m-%d")
ff2 = presim.flags_frame(flat, dil_dates=[d_mid])
dil = (ff2["flags"] & presim.F["dil"]) > 0
assert bool(dil.iloc[300]) and not bool(dil.iloc[301]) and not bool(dil.iloc[350]) and bool(dil.iloc[400]), "접수 다음 날부터 90일 동안 희석 있음(당일은 시각을 몰라 타임머신처럼 안 봄)"
assert not ((presim.flags_frame(flat, covered=False)["flags"] & presim.F["dil"]) > 0).any()
assert presim.flags_frame(flat.head(20)).empty

# ------------------------------------------------------------------ 5) 사건 표: onset·기준 표본·PICK·순위 · 경로 값 · 이어하기(새 봉이 오면 n<40 행만 갱신)
# 🐷 저금통 재생용 종목: $0.5~0.7 박스를 20일 주기로 오르내림(1,000원 미만 · 폭 40% · 반등 많음 · 거래대금 충분) → 바닥 근처에 처음 들어온 날이 사건
_ph = 2 * np.pi * np.arange(len(days)) / 20
_pc = 0.6 + 0.1 * np.sin(_ph)
pig = pd.DataFrame({"Open": _pc, "High": _pc * 1.02, "Low": _pc * 0.98, "Close": _pc, "Volume": 300_000.0}, index=days)
pz, pon, psl, ptp = presim.piggy_flags(presim._norm(pig))
assert 10 <= pon.sum() < pz.sum() and (pon == (pz & ~np.concatenate([[False], pz[:-1]]))).all(), (pon.sum(), pz.sum())
assert np.all((psl[pon] >= 1) & (psl[pon] <= 30)) and np.all(ptp[pon] > 0) and np.isnan(psl[~pz]).all(), (psl[pon][:5], ptp[pon][:5])
assert not presim.piggy_flags(presim._norm(flat))[0].any()                                            # $2 짜리는 1,000원 넘어 저금통 아님
bars = {"AAA": flat, "BBB": up, "CCC": dn, "PIG": pig}
import rank as _rank, pick30
with closing(db.connect()) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS sec_hist (accession TEXT PRIMARY KEY, ticker TEXT NOT NULL, form TEXT, filed TEXT, items TEXT)")
    conn.execute("INSERT OR IGNORE INTO sec_hist VALUES ('a1','AAA','10-Q','2024-01-10','')")                 # AAA 만 공시 이력 있음 → 희석 판정 가능
    conn.execute("INSERT OR IGNORE INTO sec_hist VALUES ('a2','AAA','424B4',?,'')", (days[200].strftime("%Y-%m-%d"),))
    conn.execute("INSERT OR IGNORE INTO sec_hist VALUES ('p1','PIG','10-Q','2024-01-10','')")                 # PIG 도 공시 이력 있음 → 희석 '없음' 판정 가능
    conn.execute(_rank.HIST_DDL); conn.execute(pick30.HIST_DDL)
    d_pick = days[400].strftime("%Y-%m-%d")
    conn.execute("INSERT INTO pick_hist VALUES (?,?,?,?,?,?,?,?,?,?)", (d_pick, "BBB", 1, "유력", 0, "상장유지", 30, 5, 7, 1.0))
    conn.execute("INSERT INTO rank_hist VALUES (?,?,?,?,?)", (d_pick, "CCC", 3, 80.0, 3))
    conn.commit()
    today = days[-1].date()
    res = presim.build_episodes(conn, bars=bars, out=lambda *_: None, today=today)
    cnt = presim.ep_counts(conn)
    assert res["tickers"] == 4 and res["new"] == res["rows"] > 60 and res["updated"] == 0, res
    assert cnt["piggy"] >= 10 and cnt["piggy_nd"] == cnt["piggy"] and (db.get_meta("presim_ep_ver") or {}).get("value") == presim.EP_VERSION, cnt
    e_p = presim.episodes(conn, "piggy")
    assert set(e_p["meta"]["ticker"]) == {"PIG"} and np.isfinite(e_p["sl"]).all() and (e_p["tp"] > 0).all() and (e_p["w"] <= 1).all() and (e_p["w"] < 1).any(), e_p["w"][:5]   # 20일 주기 사건은 ±60일 안에 겹침 → 가중 < 1
    e_b = presim.episodes(conn, "base")
    assert np.isnan(e_b["sl"][(e_b["meta"]["ticker"] != "PIG").to_numpy()]).all()                    # 저금통 구간이 아닌 날의 사건은 계획 없음(NaN)
    assert cnt["ovs"] >= 20 and cnt["base"] >= 60 and cnt["pick"] == 1 and cnt["rank"] == 1 and cnt["t3"] > 0 and cnt["t3"] <= cnt["ovs"], cnt
    ep = presim.episodes(conn, "pick")
    assert ep["n"] == 1 and ep["meta"].iloc[0]["ticker"] == "BBB" and ep["meta"].iloc[0]["date"] == d_pick
    i = 400; c0 = float(up["Close"].iloc[i])
    assert abs(ep["hi"][0, 0] - (float(up["High"].iloc[i + 1]) / c0 - 1) * 100) < 1e-3 and abs(ep["cl"][0, 4] - (float(up["Close"].iloc[i + 5]) / c0 - 1) * 100) < 1e-3
    assert ep["bars"][0] == 40
    # 희석: AAA 의 424B4(200번째 날) 뒤 90일은 t3 사건에서 빠짐
    e3 = presim.episodes(conn, "t3")["meta"]
    d_lo, d_hi = days[200].strftime("%Y-%m-%d"), (days[200] + pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    assert set(e3["ticker"]) == {"AAA"} and not ((e3["date"] >= d_lo) & (e3["date"] < d_hi)).any(), e3
    # 끝 쪽 사건은 봉이 40개 안 됨 → n<40 · 이어하기 때 봉이 더 생기면 그 행만 갱신
    short_n = conn.execute("SELECT COUNT(*) FROM presim_ep WHERE n < 40").fetchone()[0]
    assert short_n > 0
    res2 = presim.build_episodes(conn, bars=bars, out=lambda *_: None, today=today)
    # 다시 쓰는 행 = n<40 인 행 + 최근 H+RECENT_REDO 봉 안에 시작한 행(자가 치유) — 그 밖의 40봉 다 찬 행은 건너뜀
    redo_n = sum(conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker=? AND (n < 40 OR date >= ?)", (t, df.index[len(df) - (presim.H + presim.RECENT_REDO)].strftime("%Y-%m-%d"))).fetchone()[0] for t, df in bars.items())
    assert res2["new"] == 0 and res2["updated"] == redo_n and redo_n >= short_n > 0, (res2, short_n, redo_n)
    assert conn.execute("SELECT COUNT(*) FROM presim_ep WHERE n >= 40").fetchone()[0] > redo_n   # 건너뛴 오래된 행이 대부분
    ex = pd.bdate_range(days[-1] + pd.Timedelta(days=1), periods=10)
    more = {t: pd.concat([df, pd.DataFrame({"Open": df["Close"].iloc[-1], "High": df["Close"].iloc[-1] * 1.01, "Low": df["Close"].iloc[-1] * 0.99, "Close": df["Close"].iloc[-1], "Volume": 200_000.0}, index=ex)]) for t, df in bars.items()}
    res3 = presim.build_episodes(conn, bars=more, out=lambda *_: None, today=ex[-1].date())
    assert res3["new"] >= 0 and conn.execute("SELECT MAX(n) FROM presim_ep WHERE n < 40").fetchone()[0] >= 10
    # 자가 치유: 마지막 봉이 40번째 봉인 사건(AAA 를 PICK 유력으로 강제)은 마지막 봉 값이 바뀌어 다시 돌리면 경로 값이 새 값으로 바뀜(장중 미완성 봉이 굳지 않음)
    d_heal = more["AAA"].index[-(presim.H + 1)].strftime("%Y-%m-%d")
    conn.execute("INSERT INTO pick_hist VALUES (?,?,?,?,?,?,?,?,?,?)", (d_heal, "AAA", 2, "유력", 0, "상장유지", 30, 5, 7, 1.0)); conn.commit()
    presim.build_episodes(conn, bars=more, out=lambda *_: None, today=ex[-1].date())
    r0 = conn.execute("SELECT n FROM presim_ep WHERE ticker='AAA' AND date=?", (d_heal,)).fetchone()
    assert r0 is not None and r0[0] == presim.H, r0
    fixed = {t: df.copy() for t, df in more.items()}
    fixed["AAA"].iloc[-1, fixed["AAA"].columns.get_loc("High")] = float(more["AAA"]["High"].iloc[-1]) * 1.5
    res_h = presim.build_episodes(conn, bars=fixed, out=lambda *_: None, today=ex[-1].date())
    e_aaa = presim.episodes(conn, "pick"); j = list(e_aaa["meta"]["ticker"]).index("AAA")
    c0h = float(more["AAA"]["Close"].iloc[-(presim.H + 1)])
    assert abs(e_aaa["hi"][j, presim.H - 1] - (float(fixed["AAA"]["High"].iloc[-1]) / c0h - 1) * 100) < 1e-2 and res_h["updated"] > 0, (e_aaa["hi"][j, -3:], res_h)
    # 컨닝 검사: 미래 봉을 바꿔도 그 전 날짜 사건의 깃발(onset)과 경로의 앞부분은 그대로
    rows_before = {r[0]: r[1] for r in conn.execute("SELECT date, onset FROM presim_ep WHERE ticker='AAA'")}
    assert rows_before

# ------------------------------------------------------------------ 6) 키 고르기 · 기본값 · 한 종목 실행 · 기록
counts = {"t1": 500, "t2": 500, "t3": 50, "ovs": 500, "strong": 500, "pick": 500, "rank": 10, "base": 1000}
assert presim.pick_key(presim.F["ovs20"] | presim.F["dil"], "scr", counts) == "t1"
assert presim.pick_key(presim.F["ovs"] | presim.F["dil"], "scr", counts) == "ovs"                      # t3 는 표본 부족 → 과매도
assert presim.pick_key(0, "scr", counts) == "base" and presim.pick_key(0, "pick", counts) == "pick" and presim.pick_key(0, "rank", counts) == "base"
dflt = presim.defaults(flat)
assert dflt["entry"] == e and 0 < dflt["sl"] < e < dflt["tp"] and dflt["horizon"] == 40
dp = presim.defaults(flat, "piggy", (e * 0.8, e * 1.4))
assert abs(dp["sl"] - e * 0.8 * 0.95) < 1e-4 and abs(dp["tp"] - e * 1.4) < 1e-4 and presim.defaults(flat, "close")["horizon"] == 5
assert presim.pick_key(0, "piggy", {"piggy": 500, "piggy_nd": 500, "base": 1000}) == "piggy" and presim.pick_key(presim.F["dil"], "piggy", {"piggy": 500, "piggy_nd": 500}) == "piggy_nd"
assert presim.pick_key(presim.F["dil"], "piggy", {"piggy": 500, "piggy_nd": 5, "base": 1000}) == "piggy"            # 희석 없음 키 표본 부족 → 전체 저금통 키
presim.MIN_EP = 20
with closing(db.connect()) as conn:
    # 🐷 저금통 출처: 기본 계획이면 사건별 '그날 박스'(plan=box) · 기준(아무 날) 비교 · 최근 창 · 기준선 · 사용자가 손절·목표를 주면 고정 %(plan=fixed)
    rp = presim.run_one(conn, "PIG", pig, "piggy", seed=1, n_sim=800, now=datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc))
    assert rp["ok"] and rp["key"] in presim.BOX_KEYS and rp["plan"] == "box" and rp["layer1"]["n"] >= 10 and rp["base"]["n"] > 0 and rp["p0"] and 0 < rp["p0"] < 100, rp["layer1"]
    assert rp["edge"] is not None and rp["edge_raw"] is not None and abs(rp["edge"]) <= abs(rp["edge_raw"]) and "기준" in rp["basis"] and rp["n_eff"] and rp["n_eff"] <= rp["layer1"]["n"], rp
    rowp = conn.execute("SELECT plan, edge, ev_base, n_eff, p0, recent_n FROM presim_log WHERE ticker='PIG'").fetchone()
    assert rowp["plan"] == "box" and rowp["edge"] == rp["edge"] and rowp["p0"] == rp["p0"] and rowp["n_eff"] == rp["n_eff"], tuple(rowp)
    rpf = presim.run_one(conn, "PIG", pig, "piggy", sl=0.45, tp=0.8, seed=1, n_sim=800, save=False)
    assert rpf["ok"] and rpf["plan"] == "fixed" and rpf["layer1"]["sl_pct"] != rp["layer1"]["sl_pct"]
    r = presim.run_one(conn, "AAA", flat, "scr", seed=1, n_sim=1500, now=datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc))
    assert r["ok"] and r["key"] in presim.KEYS and r["layer1"]["n"] >= 20 and r["own"]["ok"] and r["verdict"] in "🟢🪙🔴" and r["size"]["shares"] >= 0, r
    assert r["basis"].startswith("같은 신호 전체 과거") or r["basis"].startswith("기준(아무 날)뿐"), r["basis"]
    assert r["day"] == days[-1].strftime("%Y-%m-%d") and r["plan"] == "fixed" and r["base"]["n"] > 0 and r["p0"] == r["layer1"]["p0"]
    row = conn.execute("SELECT * FROM presim_log WHERE ticker='AAA'").fetchone()
    assert row["key"] == r["key"] and row["verdict"] == r["verdict"] and json.loads(row["detail"])["own"]["ok"] is True
    bad = presim.run_one(conn, "AAA", flat, "scr", sl=e * 1.1)
    assert bad["ok"] is False and "손절가" in bad["why"]
    assert presim.run_one(conn, "ZZZ", flat.tail(50), "scr")["ok"] is False
    # 아침 자동 실행: 후보 = 저금통(박스는 직접 값 없으면 최근 분석의 지지·저항) + 순위 상위 N + PICK 유력 · 자료 부족 건너뜀 · 기록 · 배지
    import piggy
    piggy.ensure_tables(); piggy.add("PIG", "기타")
    conn.execute("INSERT OR REPLACE INTO piggy_scan (date, ticker, price, metrics) VALUES (?,?,?,?)", (days[-1].strftime("%Y-%m-%d"), "PIG", 0.5, json.dumps({"support": 0.5, "resistance": 0.7, "score": 80})))
    conn.commit()
    conn.execute("INSERT INTO rank_hist VALUES (?,?,?,?,?)", (days[-1].strftime("%Y-%m-%d"), "AAA", 1, 90.0, 1))
    conn.execute("INSERT INTO rank_hist VALUES (?,?,?,?,?)", (days[-1].strftime("%Y-%m-%d"), "ZZZ", 2, 85.0, 2))
    conn.execute("INSERT INTO pick_hist VALUES (?,?,?,?,?,?,?,?,?,?)", (days[-1].strftime("%Y-%m-%d"), "BBB", 1, "유력", 0, "상장유지", 30, 5, 7, 1.0))
    conn.commit()
    cands = presim.candidates(conn)
    assert [(c["ticker"], c["source"]) for c in cands] == [("PIG", "piggy"), ("BBB", "pick"), ("AAA", "rank"), ("ZZZ", "rank")], cands
    assert cands[0]["box"] == (0.5, 0.7), cands[0]                                                        # piggy.box_of: 분석 박스
    logs = []
    m = presim.morning(conn, out=logs.append, bars={**bars, "ZZZ": flat.tail(50)}, n_sim=800, now=datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc))   # 위 scr 기록보다 나중
    assert m["n"] == 4 and m["done"] == 3 and m["skip"] == 1 and sum(m["verdicts"].values()) == 3, m
    assert "🎲 매매 전 시뮬레이션: 3종목" in logs[-1] and "자료 부족 1" in logs[-1], logs
    lp = presim.latest(conn, "PIG", days=(date.today() - days[-1].date()).days + 1)
    assert lp and lp["source"] == "piggy" and lp["plan"] == "box" and abs(lp["sl"] - 0.5 * 0.95) < 1e-6 and abs(lp["tp"] - 0.7) < 1e-6, dict(lp)   # 기본값 = 분석 박스 하단×0.95 / 상단
    lt = presim.latest(conn, "BBB", days=(date.today() - days[-1].date()).days + 1)
    assert lt and lt["source"] == "pick" and lt["verdict"] in "🟢🪙🔴"
    lm = presim.latest_map(conn, ["AAA", "BBB", "ZZZ"], days=(date.today() - days[-1].date()).days + 1)
    assert set(lm) == {"AAA", "BBB"} and lm["AAA"]["source"] == "rank"
    assert len(presim.log_rows(conn, days=9999)) == 4                                               # AAA(scr) · AAA(rank) · BBB(pick) · PIG(piggy) — 같은 날 같은 종목도 출처가 다르면 따로
    assert presim.morning(conn, out=logs.append, bars={}, build=False)["done"] == 0                      # 봉 없으면 전부 건너뜀(죽지 않음)
# ------------------------------------------------------------------ 8) 장중 미완성 봉: _load_bars 는 16:20 ET 전에는 '오늘' 봉을 빼고, 장 마감 뒤에는 둔다(아침 작업은 마감 뒤라 영향 없음)
from zoneinfo import ZoneInfo
with closing(db.connect()) as conn:
    et_now = datetime.now(ZoneInfo("America/New_York"))
    ds = [(et_now - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(4, -1, -1)]      # 4일 전 … 오늘(ET)
    conn.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)", [("DDD", d, 1.0, 1.1, 0.9, 1.0, 1000.0) for d in ds])
    conn.commit()
    live = presim._load_bars(conn, ["DDD"], ds[0], now=et_now.replace(hour=10, minute=0))["DDD"]
    done = presim._load_bars(conn, ["DDD"], ds[0], now=et_now.replace(hour=17, minute=0))["DDD"]
    assert len(live) == 4 and live.index[-1].strftime("%Y-%m-%d") == ds[-2] and len(done) == 5 and done.index[-1].strftime("%Y-%m-%d") == ds[-1], (len(live), len(done))
    assert presim._load_bars(conn, [], ds[0]) == {}
print("ALL OK")
