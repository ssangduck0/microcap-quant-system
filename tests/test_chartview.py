import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""📐 차트 관점 엔진: 기준봉·채널·되돌림 · 매물대 · 지지 반복 · 이평(일봉/60분/5분) · 파라볼릭 · 볼린저 · 다이버전스 · 캔들 · 신호 · 기록 · 아침 작업(가짜 자료)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import numpy as np
import pandas as pd
import db, chartview as cv
db.init_db()
rng = np.random.default_rng(7)


def daily(closes, vols=None, start="2026-04-01", opens=None, highs=None, lows=None):
    idx = pd.bdate_range(start, periods=len(closes))
    c = np.array(closes, dtype=float)
    o = np.array(opens, dtype=float) if opens is not None else np.r_[c[0], c[:-1]]
    h = np.array(highs, dtype=float) if highs is not None else np.maximum(o, c) * 1.02
    l = np.array(lows, dtype=float) if lows is not None else np.minimum(o, c) * 0.98
    v = np.array(vols, dtype=float) if vols is not None else np.full(len(c), 1e6)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


# ---- 1) 급등 마디: 100일 $1 근처 횡보 → 기준봉(거래 10배, +80%) → 3일 더 올라 머리 $3 → 무릎~허리 사이로 눌림
flat = list(1.0 + rng.normal(0, 0.01, 100))
c = flat + [1.8, 2.4, 2.8, 3.0] + [2.6, 2.3, 2.05, 1.95, 1.9]          # 발 1.0 · 머리 3.0 → 허리 2.0 · 무릎 1.5 → 지금 1.9(무릎~허리)
v = [1e6] * 100 + [1.2e7, 8e6, 6e6, 5e6] + [3e6, 2.5e6, 2e6, 1.5e6, 1.2e6]
o = np.r_[c[0], c[:-1]]; o[100] = 1.0
h = np.maximum(o, c) * 1.01; h[100] = 1.85; h[103] = 3.05
l = np.minimum(o, c) * 0.99
d1 = daily(c, v, opens=o, highs=h, lows=l)
b = cv.base_candle(d1)
assert b and b["date"] == d1.index[100].strftime("%Y-%m-%d") and abs(b["head"] - 3.05) < 1e-9 and abs(b["foot"] - 1.0) < 0.02 and b["vol_x"] > 9, b
L = cv.channel_levels(b)
assert abs(L["허리"] - (b["foot"] + 0.5 * (3.05 - b["foot"]))) < 1e-9 and L["보라돌이"] > L["머리"] > L["어깨"] > L["허리"] > L["무릎"] > L["발"]
r = cv.retrace_state(d1, b)
assert r["zone"] == "무릎~허리" and r["above_life"] and not r["above_waist"] and r["stage"] == 1 and r["type"].startswith("C"), r   # 1.9/3.05 = −38%
# 60분봉: 250봉, 마지막 8봉이 200선 위 → '돌파 지지' · 5분봉: 이평 수렴(평평)
h60 = daily(list(np.linspace(1.3, 1.15, 242) + rng.normal(0, 0.003, 242)) + [1.9, 1.92, 1.91, 1.93, 1.9, 1.92, 1.91, 1.9], start="2026-01-01")   # 200선 아래서 흐르다 8봉 전 돌파
m5 = daily(list(1.9 + rng.normal(0, 0.002, 300)), start="2026-09-01")
a = cv.analyze(d1, h60, m5, float_shares=5e6)
codes = {s["code"] for s in a["signals"]}
assert "pullback" in codes and "h60_200" in codes and "retrace1" in codes and "life_break" not in codes, codes
assert a["ma_60"]["break200"] and a["ma_60"]["break200"] <= 10 and a["ma_5"]["converged"] and a["turnover"] is not None
assert any(k["name"] == "허리(50%)" and k["status"] == "bad" for k in a["checks"]) and any(k["name"] == "기준봉·생명선" and k["status"] == "good" for k in a["checks"])
assert "무릎~허리" in a["verdict"] and cv.chip(a)[1] == "orange" and "허리" in cv.chip(a)[0]
prof = a["prof"]; assert prof and prof["sup"] and prof["sup"] < 1.3 and (prof["res"] is None or prof["res"] > a["px"]) and a["profile"]["kind"].isin(["진함", "보통", "공백"]).all(), prof   # 100일 쌓인 $1 매물이 아래 지지
assert abs(a["support"]["level"] - L["무릎"]) < 1e-9 and a["support"]["touches"] == 0, a["support"]   # 가장 가까운 아래 자리 = 무릎, 아직 안 건드림
# 생명선 이탈: 종가가 기준봉 시작가(1.0) 아래
d_break = d1.copy(); d_break.iloc[-1, d_break.columns.get_loc("Close")] = 0.95
a2 = cv.analyze(d_break)
assert {s["code"] for s in a2["signals"]} >= {"life_break"} and cv.chip(a2)[1] == "red" and "이탈" in cv.chip(a2)[0]
# 허리 이탈(어제 허리 위 → 오늘 아래)
d_w = daily(flat + [1.8, 2.4, 2.8, 3.0, 2.6, 2.3, 2.1, 1.95], v[:108], opens=np.r_[o[:107], 2.1], highs=np.r_[h[:107], 2.12], lows=np.r_[l[:107], 1.9])
a3 = cv.analyze(d_w); assert "waist_break" in {s["code"] for s in a3["signals"]}, a3["signals"]

# ---- 2) 기준봉 없음(완만한 횡보) → None 채널, 체크리스트는 '기준봉 없음'
d_flat = daily(list(2 + rng.normal(0, 0.02, 80)))
a4 = cv.analyze(d_flat)
assert a4["base"] is None and a4["levels"] is None and any(k["name"] == "기준봉" and k["status"] == "none" for k in a4["checks"]) and cv.chip(a4) is None

# ---- 3) 일봉 5/20 골든크로스(어제 교차) · 고점 'ㅗ' 캔들 · ANO 연속 하락 뒤 전환
up = list(np.linspace(2.0, 1.6, 30)) + list(np.linspace(1.6, 2.2, 8))      # 내리다 8일 올림 → 5가 20을 최근에 돌파
d_gc = daily(up); md = cv.ma_daily(d_gc)
assert md["gc_days"] is not None and md["gc_days"] <= 5, md
cc = list(2 + rng.normal(0, 0.01, 40)) + [2.05]
hh = np.maximum(np.r_[cc[0], cc[:-1]], cc) * 1.005; hh[-1] = 2.6          # 마지막 봉: 몸통 작고 윗꼬리 김(20일 고점)
d_top = daily(cc, highs=hh)
cd = cv.candles(d_top); assert cd["top"] and not cd["hammer"], cd
assert "top_candle" in {s["code"] for s in cv.analyze(d_top)["signals"]}
base_c = list(3 + rng.normal(0, 0.005, 40))
turn_c = base_c + [2.9, 2.8, 2.7, 2.6, 2.85]                              # 4일 연속 하락(시가 = 전일 종가 보다 살짝 낮게) 뒤 전일 시가(2.7) 돌파
op = np.r_[turn_c[0], turn_c[:-1]]; op[-5:-1] = [x * 0.995 for x in np.r_[base_c[-1], 2.9, 2.8, 2.7]]
d_turn = daily(turn_c, opens=op)
cd2 = cv.candles(d_turn); assert cd2["down_run"] == 4 and cd2["turn"], cd2
assert "turn3" in {s["code"] for s in cv.analyze(d_turn)["signals"]}
d_wait = daily(turn_c[:-1], opens=op[:-1]); assert cv.candles(d_wait)["turn_waiting"]

# ---- 4) 파라볼릭: 상승 추세면 점이 아래 · 하락 뒤 횡보면 '몇 봉 뒤 접촉' 이 나온다 · 볼린저 수축
d_up = daily(list(np.linspace(1, 2, 60)))
s_up = cv.sar_state(d_up); assert s_up["pos"] == "below"
d_dn = daily(list(np.linspace(2, 1, 40)) + [1.0] * 5)
s_dn = cv.sar_state(d_dn); assert s_dn["pos"] == "above" and s_dn["eta"] is not None and 1 <= s_dn["eta"] <= 30, s_dn
bb = cv.bollinger(daily(list(2 + rng.normal(0, 0.05, 100)) + list(2 + rng.normal(0, 0.002, 25))))
assert bb and bb["squeeze"] and bb["pctile"] <= 20, bb

# ---- 5) 다이버전스: 주가 −15% · 거래량 줄고 · MACD 오름
px = list(np.linspace(3, 2.4, 20)) + list(np.linspace(2.4, 2.55, 15)) + list(np.linspace(2.55, 2.4, 15))
vv = [3e6] * 35 + [1e6] * 15
dv = cv.divergence(daily(px, vv)); assert dv is not None and dv["vol_ratio"] < 1
# ---- 6) 매물대·지지 터치
prof2 = cv.volume_profile(daily([1.0] * 60 + [1.5] * 10, [5e6] * 60 + [1e6] * 10), bins=10)
assert prof2 is not None and prof2.iloc[0]["kind"] == "진함" and prof2["share"].sum() > 99.9
assert cv.touch_count(daily([1.05] * 8, lows=[0.98, 1.03, 0.98, 1.03, 0.98, 1.03, 0.98, 1.03]), 0.98) == 4   # 같은 자리 저가를 4번 따로 건드림
assert cv.touch_count(daily([1.0] * 10), None) == 0

# ---- 7) 기록 · 조회 · 아침 작업(가짜 자료)
with closing(db.connect()) as conn:
    cv.ensure(conn)
    n = cv.record(conn, "2026-10-27", "aaa", a["signals"], a["px"]); assert n == len(a["signals"])
    assert cv.record(conn, "2026-10-27", "AAA", a["signals"], a["px"]) == 0        # 같은 날 중복 없음
    conn.commit()
    df = cv.recent(conn, days=3650); assert set(df["ticker"]) == {"AAA"} and "name" in df
    res = cv.scan(conn, {"BBB": d1, "CCC": d_flat}, ["BBB", "CCC"], day="2026-10-27", h60={"BBB": h60}, m5={"BBB": m5})
    assert [x["ticker"] for x in res] == ["BBB"] and len(cv.recent(conn, days=3650)) > n
    conn.execute("INSERT OR REPLACE INTO daily_snapshots (date, ticker, win_score) VALUES ('2026-10-27', 'BBB', 80)"); conn.commit()
    cands = cv.candidates(conn); assert "BBB" in cands
# ---- 8) 스캐너 실시간 경고: 5분 5·20 꺾임 → 처음 한 번만 텔레그램(가짜 send) · 🏆 성과 공표 소스 · 타임머신 깃발
m5_down = daily(list(np.linspace(2.1, 1.7, 300)), start="2026-09-01")      # 5분봉이 줄곧 내려 5·20 둘 다 꺾임
sent = []
with closing(db.connect()) as conn:
    msgs = cv.live_check(conn, {"BBB": d1}, {"BBB": m5_down}, ["BBB"], send=sent.append, day="2026-10-28")
    assert msgs and any("5분봉 5·20 모두 꺾임" in m for m in msgs) and sent == msgs, msgs
    assert cv.live_check(conn, {"BBB": d1}, {"BBB": m5_down}, ["BBB"], send=sent.append, day="2026-10-28") == []    # 같은 날 두 번 안 보냄
    import config; config.CHART_ALERTS = False
    assert cv.live_check(conn, {"BBB": d1}, {"BBB": m5_down}, ["BBB"], send=sent.append, day="2026-10-29") == []    # 꺼져 있으면 기록만
    assert conn.execute("SELECT COUNT(*) FROM chart_signals WHERE date='2026-10-29' AND kind='m5_break'").fetchone()[0] == 1
    config.CHART_ALERTS = True
    import scoreboard as sb
    df_sb = sb.collect(conn)
    srcs = set(df_sb[df_sb["ticker"] == "BBB"]["source"]); assert {"chart_pullback", "chart_h60"} <= srcs, srcs
    assert float(df_sb[(df_sb["ticker"] == "BBB") & (df_sb["source"] == "chart_pullback")]["entry"].iloc[0]) > 0
o_arr, h_arr, l_arr, c_arr, v_arr = (d1[k].to_numpy() for k in ("Open", "High", "Low", "Close", "Volume"))
gc3, pb = cv.tm_flags(o_arr, h_arr, l_arr, c_arr, v_arr)
assert pb[-1] and pb[-2] and not pb[100] and not pb[103], np.where(pb)[0]          # 머리 뒤 무릎~허리 눌림(마지막 이틀) · 기준봉·머리 날은 아님
assert gc3[103] or gc3[102] or gc3[104]                                               # 급등 중 5/20 골크
assert not cv.tm_flags(o_arr[:10], h_arr[:10], l_arr[:10], c_arr[:10], v_arr[:10])[0].any()
logs = []
out = cv.morning(out=logs.append, fetch=lambda ticks: ({t: d1 for t in ticks}, {t: h60 for t in ticks}, {t: m5 for t in ticks}))
assert out["n"] >= 1 and any("신호" in x for x in logs), logs
print("ALL OK")
