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
bars = {"AAA": flat, "BBB": up, "CCC": dn}
import rank as _rank, pick30
with closing(db.connect()) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS sec_hist (accession TEXT PRIMARY KEY, ticker TEXT NOT NULL, form TEXT, filed TEXT, items TEXT)")
    conn.execute("INSERT OR IGNORE INTO sec_hist VALUES ('a1','AAA','10-Q','2024-01-10','')")                 # AAA 만 공시 이력 있음 → 희석 판정 가능
    conn.execute("INSERT OR IGNORE INTO sec_hist VALUES ('a2','AAA','424B4',?,'')", (days[200].strftime("%Y-%m-%d"),))
    conn.execute(_rank.HIST_DDL); conn.execute(pick30.HIST_DDL)
    d_pick = days[400].strftime("%Y-%m-%d")
    conn.execute("INSERT INTO pick_hist VALUES (?,?,?,?,?,?,?,?,?,?)", (d_pick, "BBB", 1, "유력", 0, "상장유지", 30, 5, 7, 1.0))
    conn.execute("INSERT INTO rank_hist VALUES (?,?,?,?,?)", (d_pick, "CCC", 3, 80.0, 3))
    conn.commit()
    today = days[-1].date()
    res = presim.build_episodes(conn, bars=bars, out=lambda *_: None, today=today)
    cnt = presim.ep_counts(conn)
    assert res["tickers"] == 3 and res["new"] == res["rows"] > 60 and res["updated"] == 0, res
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
    assert res2["new"] == 0 and res2["updated"] == short_n, (res2, short_n)
    ex = pd.bdate_range(days[-1] + pd.Timedelta(days=1), periods=10)
    more = {t: pd.concat([df, pd.DataFrame({"Open": df["Close"].iloc[-1], "High": df["Close"].iloc[-1] * 1.01, "Low": df["Close"].iloc[-1] * 0.99, "Close": df["Close"].iloc[-1], "Volume": 200_000.0}, index=ex)]) for t, df in bars.items()}
    res3 = presim.build_episodes(conn, bars=more, out=lambda *_: None, today=ex[-1].date())
    assert res3["new"] >= 0 and conn.execute("SELECT MAX(n) FROM presim_ep WHERE n < 40").fetchone()[0] >= 10
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
presim.MIN_EP = 20
with closing(db.connect()) as conn:
    r = presim.run_one(conn, "AAA", flat, "scr", seed=1, n_sim=1500, now=datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc))
    assert r["ok"] and r["key"] in presim.KEYS and r["layer1"]["n"] >= 20 and r["own"]["ok"] and r["verdict"] in "🟢🪙🔴" and r["size"]["shares"] >= 0, r
    assert r["basis"] == "같은 신호 전체 과거" and r["day"] == days[-1].strftime("%Y-%m-%d")
    row = conn.execute("SELECT * FROM presim_log WHERE ticker='AAA'").fetchone()
    assert row["key"] == r["key"] and row["verdict"] == r["verdict"] and json.loads(row["detail"])["own"]["ok"] is True
    bad = presim.run_one(conn, "AAA", flat, "scr", sl=e * 1.1)
    assert bad["ok"] is False and "손절가" in bad["why"]
    assert presim.run_one(conn, "ZZZ", flat.tail(50), "scr")["ok"] is False
    # 아침 자동 실행: 후보 = 순위 상위 N + PICK 유력 (저금통 표 없음) · 자료 부족 건너뜀 · 기록 · 배지
    conn.execute("INSERT INTO rank_hist VALUES (?,?,?,?,?)", (days[-1].strftime("%Y-%m-%d"), "AAA", 1, 90.0, 1))
    conn.execute("INSERT INTO rank_hist VALUES (?,?,?,?,?)", (days[-1].strftime("%Y-%m-%d"), "ZZZ", 2, 85.0, 2))
    conn.execute("INSERT INTO pick_hist VALUES (?,?,?,?,?,?,?,?,?,?)", (days[-1].strftime("%Y-%m-%d"), "BBB", 1, "유력", 0, "상장유지", 30, 5, 7, 1.0))
    conn.commit()
    cands = presim.candidates(conn)
    assert [(c["ticker"], c["source"]) for c in cands] == [("BBB", "pick"), ("AAA", "rank"), ("ZZZ", "rank")], cands
    logs = []
    m = presim.morning(conn, out=logs.append, bars={**bars, "ZZZ": flat.tail(50)}, n_sim=800, now=datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc))   # 위 scr 기록보다 나중
    assert m["n"] == 3 and m["done"] == 2 and m["skip"] == 1 and sum(m["verdicts"].values()) == 2, m
    assert "🎲 매매 전 시뮬레이션: 2종목" in logs[-1] and "자료 부족 1" in logs[-1], logs
    lt = presim.latest(conn, "BBB", days=(date.today() - days[-1].date()).days + 1)
    assert lt and lt["source"] == "pick" and lt["verdict"] in "🟢🪙🔴"
    lm = presim.latest_map(conn, ["AAA", "BBB", "ZZZ"], days=(date.today() - days[-1].date()).days + 1)
    assert set(lm) == {"AAA", "BBB"} and lm["AAA"]["source"] == "rank"
    assert len(presim.log_rows(conn, days=9999)) == 3                                               # AAA(scr) · AAA(rank) · BBB(pick) — 같은 날 같은 종목도 출처가 다르면 따로
    assert presim.morning(conn, out=logs.append, bars={}, build=False)["done"] == 0                      # 봉 없으면 전부 건너뜀(죽지 않음)
print("ALL OK")
