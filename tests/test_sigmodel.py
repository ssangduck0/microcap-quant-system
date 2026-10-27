import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🧠 신호 승률 모델: 특징(컨닝 없음) · 정답 · 학습(심은 패턴을 AUC 로 찾아내는지) · 저장/불러오기 · 신호에 확률 붙이기 · 🏆 표 열 · 🔍 부검 탭 모델 보고서(가짜 자료)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np
import pandas as pd
import db, sigmodel as sm, chartview as cv, scoreboard as sb, halts
db.init_db(); halts.fetch = lambda *a, **k: []
rng = np.random.default_rng(11)
N_DAYS = 430
idx = pd.bdate_range(end=pd.Timestamp(date.today()), periods=N_DAYS)


def synth(seed: int) -> pd.DataFrame:
    """무작위 걸음 + 심은 패턴: 거래량 6배 터진 날(+12%) 뒤 10일 안에 60% 확률로 +45% 랠리 · 그 외엔 3% 확률."""
    r = np.random.default_rng(seed)
    c = np.empty(N_DAYS); v = np.full(N_DAYS, 1e6)
    c[0] = 2.0
    pump_left, pump_mult = 0, 1.0
    for i in range(1, N_DAYS):
        ret = r.normal(0, 0.03)
        spike = r.random() < 0.03
        if spike:
            ret += 0.12; v[i] = 6e6
            if r.random() < 0.6:
                pump_left, pump_mult = r.integers(2, 8), 1.45
        elif r.random() < 0.003:
            pump_left, pump_mult = 3, 1.45
        if pump_left > 0:
            pump_left -= 1
            if pump_left == 0:
                ret += np.log(pump_mult); pump_mult = 1.0
        c[i] = max(0.05, c[i - 1] * np.exp(ret))
        v[i] *= np.exp(r.normal(0, 0.3))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.03, "Low": np.minimum(o, c) * 0.97, "Close": c, "Volume": v}, index=idx)


frames = {f"T{i:02d}": synth(100 + i) for i in range(40)}
# 1) 특징·정답
F = sm.daily_features(frames["T00"])
assert set(sm.FEATURES) <= set(F.columns) and {"y30", "y10", "ok", "date"} <= set(F.columns) and len(F) == N_DAYS
assert F["y30"].iloc[-sm.H_BIG:].isna().all() and F["y30"].iloc[:-sm.H_BIG].notna().all()          # 미래가 없는 마지막 10일은 정답 없음
assert F["ok"].iloc[:sm.MIN_HIST].sum() == 0 and F["ok"].iloc[sm.MIN_HIST:].any()
assert F["zone"].isin([0, 1, 2, 3, 4]).all() and F["stage"].between(0, 4).all() and (F["base_days"] <= 99).all()
# 정답 손계산: 평평하다가 i+3 일 고가가 +50% → y30=1, y10=1 / 아무 일 없으면 0
flat = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1e6}, index=idx[:100])
flat.iloc[83, flat.columns.get_loc("High")] = 1.5
Ff = sm.daily_features(flat); assert Ff["y30"].iloc[80] == 1 and Ff["y10"].iloc[80] == 1 and Ff["y30"].iloc[60] == 0 and Ff["y10"].iloc[77] == 0   # 83-77=6 > 5일
# 컨닝 없음: 미래 봉을 바꿔도 i 일의 특징은 그대로
full = frames["T01"]; cut = full.iloc[:301]
row_full, row_cut = sm.daily_features(full).iloc[300][sm.FEATURES].astype(float), sm.daily_features(cut).iloc[300][sm.FEATURES].astype(float)
assert np.allclose(row_full.fillna(-9), row_cut.fillna(-9), atol=1e-9), (row_full - row_cut).abs().sort_values().tail(3)
asof = idx[300].strftime("%Y-%m-%d")
fa = sm.features_asof(full, asof); assert fa is not None and fa["date"] == asof and np.allclose(fa[sm.FEATURES].astype(float).fillna(-9), row_cut.fillna(-9))
assert sm.features_asof(full.iloc[:30], asof) is None
# 희석 공시 90일 창
Fd = sm.daily_features(frames["T02"], dil_dates=[idx[200].strftime("%Y-%m-%d")], covered=True)
assert Fd["dil_bad"].iloc[200] == 1 and Fd["dil_bad"].iloc[199] == 0 and Fd["dil_bad"].iloc[260] == 1 and Fd["dil_bad"].iloc[330] == 0 and (Fd["dil_unknown"] == 0).all()
assert (sm.daily_features(frames["T02"], covered=False)["dil_unknown"] == 1).all()
# 2) 학습: 심은 패턴(거래량 배수·1일 등락)을 찾아내는지 — 표본 외 AUC
with closing(db.connect()) as conn:
    for t, df in frames.items():
        db.upsert_daily_prices(conn, t, df)
    conn.commit()
    X = sm.build_dataset(conn, years=1.5, out=lambda *a: None, step=1)
    assert len(X) > 3000 and X["ticker"].nunique() == 40 and X["y30"].notna().all(), len(X)
    m = sm.fit(X)
    t30 = m["targets"]["p30"]
    assert t30["auc_test"] > 0.55 and t30["auc_train"] > 0.55 and len(t30["deciles"]) == 10 and t30["lift_top"] > 1.3, (t30["auc_test"], t30["lift_top"])   # 심은 패턴은 터진 날 하루만 보여 AUC 는 낮게 나옴 · 상위 10% 적중이 기준의 1.3배↑가 핵심
    assert {w["key"] for w in t30["weights"]} == set(sm.FEATURES) and all("특징" in w for w in t30["weights"])   # 가중치 표(순위는 제곱항·상관 때문에 고정 아님)
    assert m["targets"]["p10"]["auc_test"] is not None and m["n_train"] > m["n_test"] > 100 and "AUC" in sm.summary(m)
    sm.save(m); assert sm.load()["fitted_at"] == m["fitted_at"]
    assert sm.maybe_refit(conn, out=lambda *a: None) is None                                          # 방금 학습 → 다시 안 함
    try:
        sm.fit(X.head(300)); assert False
    except ValueError:
        pass
    # 3) 신호에 확률 붙이기: 📐 눌림 타점(오늘) + 과거 셋업 신호 — 과거 신호는 days 창 밖이라 안 붙음
    cv.ensure(conn); conn.execute(sb.DDL)
    today = idx[-1].strftime("%Y-%m-%d"); old = idx[-200].strftime("%Y-%m-%d")
    conn.execute("INSERT OR IGNORE INTO chart_signals VALUES (?,?,?,?,?,?)", (today, "T03", "pullback", float(frames["T03"]["Close"].iloc[-1]), "", "x"))
    conn.execute("INSERT OR IGNORE INTO chart_signals VALUES (?,?,?,?,?,?)", (old, "T04", "gc520", 1.0, "", "x"))
    conn.execute("CREATE TABLE IF NOT EXISTS setup3_signals (date TEXT, ticker TEXT, price REAL, strong INTEGER, note TEXT, PRIMARY KEY (date, ticker))")
    conn.execute("INSERT OR IGNORE INTO setup3_signals VALUES (?, 'NEWT', 1.0, 1, '')", (today,))                         # 일봉 없는 종목 → download 로
    conn.commit()
    calls = []
    def dl(t):
        calls.append(t); return synth(999)
    n = sm.score_signals(conn, days=3, out=lambda *a: None, download=dl)
    rows = {r[0]: r for r in conn.execute("SELECT ticker, source, p30, p10 FROM sig_prob")}
    assert n == 2 and set(rows) == {"T03", "NEWT"} and "T04" not in rows and calls == ["NEWT"], (n, rows, calls)
    assert 0 < rows["T03"][2] < 1 and 0 < rows["T03"][3] < 1 and rows["T03"][1] == "chart_pullback"
    assert sm.score_signals(conn, days=3, out=lambda *a: None, download=dl) == 0 and len(calls) == 1          # 두 번 안 붙임
    tb = sb.table(conn); assert "p30" in tb.columns and float(tb[tb["ticker"] == "T03"]["p30"].iloc[0]) == rows["T03"][2]
    pr = sm.probs(conn); assert len(pr) == 2
    _now = db.utcnow_iso()
    db.upsert_snapshot(conn, {"date": today, "ticker": "T03", "exchange": "NASDAQ", "first_seen": _now, "last_seen": _now, "price": 1.5, "high_20d": 1.5, "low_20d": 0.9, "drawdown_pct": -5.0,
        "day_change_pct": 5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.05, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
        "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
# 4) 화면: 🏆 성과 공표 표에 AI 확률 열 · 🔍 부검 탭 모델 보고서
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "score"
at = AppTest.from_file(APP, default_timeout=240).run(); assert not at.exception, [e.value for e in at.exception]
dfs = [d.value for d in at.dataframe]
sbt = [d for d in dfs if "AI 확률(%)" in d.columns]
assert sbt and any((d["티커"] == "T03").any() for d in sbt), [list(d.columns) for d in dfs]
v = [d for d in sbt if (d["티커"] == "T03").any()][0]; v = v[v["티커"] == "T03"]["AI 확률(%)"].iloc[0]; assert 0 <= float(v) <= 100
os.environ["QUANT_TEST_PAGE"] = "autopsy"
at = AppTest.from_file(APP, default_timeout=240).run(); assert not at.exception, [e.value for e in at.exception]
dfs = [d.value for d in at.dataframe]
assert any("특징" in d.columns and "가중치" in d.columns for d in dfs) and any("분위" in d.columns and "실제 적중(%)" in d.columns for d in dfs), [list(d.columns) for d in dfs]
assert any("신호 승률 모델" in m.value for m in at.markdown) and any("AUC" in m.label or "AUC" in str(m.value) for m in at.metric)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
