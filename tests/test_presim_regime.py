"""🎲 presim 보강 C(장세 조건부 · C안 2026-10-30) — 과거 장세 재생(컨닝 없음 · FRED 하루 늦게) · 장세 기록(실시간 우선, 나머지 재생) ·
판정 두 개(2년 전체 / 오늘과 같은 장세 날만) · 대표 판정(관리 모드 스위치, 더 조심스러운 쪽) · 기록 칸 · 🏆 성과 공표 출처 · 배지."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import numpy as np
import pandas as pd
import config, db, presim, presim_ui, regime, scoreboard

db.init_db()

# ---------------------------------------------------------------- 1) 과거 장세 재생: 컨닝 없음 · FRED 는 전날까지
idx = pd.bdate_range("2024-01-01", "2025-12-31")
D = idx[400]
flat = lambda v: pd.Series(float(v), index=idx)   # noqa: E731
x = {"vix": flat(15), "vix9d": flat(14), "vix3m": flat(16), "spy": pd.Series(np.linspace(400, 600, len(idx)), index=idx),
     "ixic": pd.Series(np.linspace(14000, 20000, len(idx)), index=idx), "hyg_ief": flat(0.8), "dgs2": flat(4.0), "dgs10": flat(4.3),
     "hy": flat(3.0)}
x["vix"].loc[D] = 35.0                                        # D 하루 공포
x["hy"].loc[D:] = 6.0                                         # D 에 하이일드 급등(FRED → 다음 날부터 보여야)
rp = regime.replay(x, [idx[399].date(), D.date(), idx[401].date()])
d0, d1, d2 = (str(idx[399].date()), str(D.date()), str(idx[401].date()))
assert rp[d0]["light"] == "green" and rp[d0]["points"] == 0, rp[d0]
assert rp[d1]["points"] >= 4 and rp[d1]["light"] == "red" and rp[d1]["vix"] == 35.0, rp[d1]   # VIX ≥30 +3 · 하루 +15% +1 · (하이일드는 아직 안 보임)
assert rp[d2]["points"] == 2 and rp[d2]["light"] == "yellow", rp[d2]                         # 다음 날: VIX 정상 · 하이일드 ≥5% +1 · 5일 +0.3pp +1
x2 = {k: v.copy() for k, v in x.items()}
x2["vix"].loc[idx[401]:] = 80.0; x2["spy"].loc[idx[401]:] = 1.0                               # 미래를 바꿔도
assert regime.replay(x2, [D.date()])[d1] == rp[d1]                                             # 그날 장세는 그대로(컨닝 없음)
tz = {k: v.tz_localize("America/New_York") if k in ("vix", "spy") else v for k, v in x.items()}  # 야후식 시간대 붙은 인덱스도
assert regime.replay(tz, [D.date()])[d1]["light"] == "red"
assert regime.replay({}, [D.date()]) == {}                                                      # 자료 없으면 건너뜀

# ---------------------------------------------------------------- 2) 가짜 사건 표: '픽' 신호는 🔴 장세에서만 강하고 🟢 에선 기준과 같음
H = presim.H
def path(win: bool) -> tuple[bytes, bytes, bytes]:
    hi = np.full(H, 1.0, np.float32); lo = np.full(H, -1.0, np.float32); cl = np.zeros(H, np.float32)
    if win:
        hi[2] = 31.0                                          # 3일째 +31% → 목표 +30% 먼저
    else:
        lo[1] = -11.0                                         # 2일째 −11% → 손절 −10% 먼저
    return hi.tobytes(), lo.tobytes(), cl.tobytes()

days = pd.bdate_range("2025-01-02", periods=200)
green, red = [d.strftime("%Y-%m-%d") for d in days[:100]], [d.strftime("%Y-%m-%d") for d in days[100:]]
rows, n_t = [], 0
for lt, dl in (("green", green), ("red", red)):
    for i, d in enumerate(dl):
        win = (i % 4 == 0) if lt == "green" else (i % 5 < 3)  # 픽: 🟢 25% · 🔴 60% 이 목표 먼저
        rows.append((f"K{n_t:04d}", d, 1.0, presim.F["pick"], 0, H, *path(win))); n_t += 1
        for j in range(2):                                    # 기준: 두 장세 모두 25%
            rows.append((f"B{n_t:04d}", d, 1.0, presim.F["base"], 0, H, *path((i * 2 + j) % 4 == 0))); n_t += 1
with closing(db.connect()) as conn:
    presim.ensure(conn)
    conn.executemany("INSERT INTO presim_ep (ticker, date, px, flags, onset, n, hi, lo, cl) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("CREATE TABLE IF NOT EXISTS regime_hist (date TEXT PRIMARY KEY, light TEXT, points INTEGER, at TEXT)")
    conn.executemany("INSERT INTO regime_hist VALUES (?,?,?,?)", [(d, "red", 5, "x") for d in red])   # 🔴 날짜는 실시간 기록이 있음
    conn.commit()

    # ---- 장세 기록: 실시간 기록(🔴 100일) + 나머지는 재생(가짜 재료 → 🟢)
    gx = {k: flat(v) for k, v in (("vix", 14), ("vix9d", 13), ("vix3m", 15), ("hyg_ief", 0.8), ("dgs2", 4.0), ("dgs10", 4.3), ("hy", 3.0))}
    gx["spy"] = pd.Series(np.linspace(400, 600, len(idx)), index=idx); gx["ixic"] = pd.Series(np.linspace(14000, 20000, len(idx)), index=idx)
    calls = []
    res = presim.ensure_regimes(conn, out=lambda *_: None, loader=lambda: calls.append(1) or gx)
    assert res == {"need": 200, "live": 100, "replay": 100} and calls == [1], res
    assert presim.ensure_regimes(conn, out=lambda *_: None, loader=lambda: calls.append(1) or gx)["need"] == 0 and calls == [1]   # 두 번째는 할 일 없음
    rmap = presim.regime_map(conn)
    assert {rmap[d] for d in green} == {"green"} and {rmap[d] for d in red} == {"red"}
    assert dict(conn.execute("SELECT src, COUNT(*) FROM presim_regime GROUP BY src").fetchall()) == {"live": 100, "replay": 100}

    # ---- 판정 두 개
    r_ = np.random.default_rng(1)
    bd = pd.bdate_range(end=days[-1], periods=260)
    c = 2.0 * np.cumprod(1 + r_.normal(0, 0.02, len(bd)))
    df = pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": 300_000.0}, index=bd)
    e = float(df["Close"].iloc[-1])
    kw = dict(entry=e, sl=e * 0.9, tp=e * 1.3, horizon=40, n_sim=500, seed=3)
    g = presim.run_one(conn, "ZZZ", df, "pick", regime_light="green", **kw)
    assert g["ok"] and g["key"] == "pick" and g["verdict"] == "🟢", (g.get("key"), g.get("verdict"), g.get("edge"))
    assert abs(g["layer1"]["ev_pct"] - 7.0) < 0.01 and abs(g["base"]["ev_pct"] - 0.0) < 0.01                     # 전체: 픽 +7% · 기준 0%
    assert g["regime"] == "green" and g["verdict_reg"] == "🪙" and abs(g["reg"]["ev"]) < 0.01 and g["reg"]["n_eff"] == 100   # 🟢 날만: 우위 0 → 동전
    assert set(g["by_light"]) == {"green", "yellow", "red"} and g["by_light"]["yellow"]["n"] == 0 and abs(g["by_light"]["red"]["ev"] - 14.0) < 0.01
    assert g["verdict_main"] == "🪙"                                                                                # 기본(장세 반영) = 더 조심스러운 쪽
    assert presim.combine("🟢", "🪙", on=False) == "🟢" and presim.combine("🟢", "🔴", on=True) == "🔴" and presim.combine("🔴", "🟢", on=True) == "🔴"
    assert presim.combine("🪙", "❔", on=True) == "🪙" and presim.combine("❔", "🟢", on=True) == "❔"
    rd = presim.run_one(conn, "ZZZ", df, "pick", regime_light="red", save=False, **kw)
    assert rd["verdict_reg"] == "🟢" and rd["verdict_main"] == "🟢" and rd["edge_reg"] > rd["edge"]            # 🔴 날만: 더 강함 → 둘 다 🟢
    ye = presim.run_one(conn, "ZZZ", df, "pick", regime_light="yellow", save=False, **kw)
    assert ye["verdict_reg"] == "❔" and ye["verdict_main"] == "🟢"                                              # 🟡 사건 없음 → 2년 전체 판정
    no = presim.run_one(conn, "ZZZ", df, "pick", regime_light="", save=False, **kw)
    assert no["verdict_reg"] == "❔" and no["verdict_main"] == "🟢"
    old_min = presim.EFF_MIN; presim.EFF_MIN = 150.0                                                            # 장세 표본 100 < 150 → ❔
    assert presim.run_one(conn, "ZZZ", df, "pick", regime_light="green", save=False, **kw)["verdict_reg"] == "❔"
    presim.EFF_MIN = old_min

    # ---- 기록 칸 · 대표 판정 · 배지
    row = dict(conn.execute("SELECT * FROM presim_log WHERE ticker='ZZZ'").fetchone())
    assert row["verdict"] == "🟢" and row["verdict_reg"] == "🪙" and row["regime"] == "green" and row["n_eff_reg"] == 100 and abs(row["ev_reg"]) < 0.01
    config.PRESIM_REGIME_VERDICT = True
    assert presim.main_verdict(row) == "🪙" and presim_ui.badge_text(row).startswith("🪙 익절")
    config.PRESIM_REGIME_VERDICT = False
    assert presim.main_verdict(row) == "🟢" and presim_ui.badge_text(row).startswith("🟢 익절")               # 스위치를 끄면 예전과 같음
    config.PRESIM_REGIME_VERDICT = True
    assert presim.main_verdict({"verdict": "🟢", "verdict_reg": None}) == "🟢"                                  # 10/30 이전 기록(칸 없음) = 2년 전체
    chip = presim_ui.badge_chip("ZZZ", {"ZZZ": row})
    assert "2년 전체 🟢" in chip and "날만 🪙" in chip and "qk-orange" in chip, chip[:200]
    cap = presim_ui._regime_caption(g)
    assert "판정 두 개" in cap and "2년 전체 🟢" in cap and "🟢 장세 날만 🪙" in cap and "대표 🪙" in cap, cap
    assert "장세 기록 없음" in presim_ui._regime_caption(no)
    assert "PRESIM_REGIME_VERDICT" in config.SETTINGS and config.SETTINGS["PRESIM_REGIME_VERDICT"][0] is bool

    # ---- 🏆 성과 공표: 2년 전체(presim_g) 와 장세 반영(presim_rc) 이 같이 잡힘
    sb = scoreboard.collect(conn)
    srcs = set(sb["source"]) if "source" in sb.columns else set(sb.iloc[:, 0])
    assert {"presim_g", "presim_rc"} <= srcs, srcs
    assert {"presim_rg", "presim_rc", "presim_rr"} <= set(scoreboard.SOURCES) if hasattr(scoreboard, "SOURCES") else True
print("ALL OK")
