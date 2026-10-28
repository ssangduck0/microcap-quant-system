"""🔬 docs/studies/study_shares_change.py(⑥ 규칙 검증) 의 핵심 계산 — 가짜 표지·가짜 주가로: 직전 분기 쌍 고르기 · 사이 분할 반영 · 제출일 이후 진입(컨닝 금지) · 당시 실제 주가 · 오류 제외."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import importlib.util, os
import numpy as np
import pandas as pd
p = os.path.join(os.environ["QS_ROOT"], "docs", "studies", "study_shares_change.py")
spec = importlib.util.spec_from_file_location("study", p); st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)

idx = pd.bdate_range("2025-01-01", periods=400)
close = pd.Series(1.0, index=idx)
close.iloc[200:] = 2.0                                   # 2025-10-09(200번째 거래일)부터 2배
close.iloc[260:] = 0.5                                   # 260번째 거래일부터 0.5
sp = pd.Series(0.0, index=idx); sp.iloc[150] = 0.1       # 두 표지 사이 1:10 병합(야후 비율 = 새/옛)
sp.iloc[300] = 0.2                                       # 진입 뒤 1:5 병합 → 당시 실제 주가 = 종가 × 0.2
px = {"AAA": pd.DataFrame({"Close": close, "Volume": 1000, "Stock Splits": sp}),
      "BBB": pd.DataFrame({"Close": close, "Volume": 1000, "Stock Splits": 0.0}),
      "GLT": pd.DataFrame({"Close": pd.Series(1.0, index=idx), "Volume": 1, "Stock Splits": 0.0})}
d_asof0, d_asof1 = idx[100].date().isoformat(), idx[190].date().isoformat()   # 간격 126일(75~200 안)
filed1 = idx[199].date().isoformat()                                           # 제출일 = 199번째 → 진입은 199번째 종가(1.0), 200번째부터 2배는 진입 뒤
hist = pd.DataFrame([
    {"ticker": "AAA", "asof": d_asof0, "filed": idx[105].date().isoformat(), "form": "10-Q", "shares": 10_000_000},
    {"ticker": "AAA", "asof": d_asof1, "filed": filed1, "form": "10-Q", "shares": 1_500_000},   # 1:10 병합 뒤 150만 = 옛 100만 기준 +50%
    {"ticker": "BBB", "asof": d_asof0, "filed": idx[105].date().isoformat(), "form": "10-Q", "shares": 1_000_000},
    {"ticker": "BBB", "asof": d_asof1, "filed": filed1, "form": "10-Q", "shares": 300_000},     # 분할 기록 없이 -70% → 역분할 누락 의심 제외
    {"ticker": "BBB", "asof": "2024-01-05", "filed": "2024-01-10", "form": "10-Q", "shares": 1_000_000},                         # 다음 표지와 간격 > 200일 → 쌍 안 됨
    {"ticker": "GLT", "asof": d_asof0, "filed": None, "form": "10-Q", "shares": 1_000_000},
    {"ticker": "GLT", "asof": d_asof1, "filed": None, "form": "10-Q", "shares": 1_000_000},     # filed 없음 → asof+5일 진입
])
df = st.build_pairs(hist, px); print(df.to_string())
assert list(df["ticker"]) == ["AAA", "GLT"] and df.attrs["dropped"]["rs_missing"] == 1 and df.attrs["dropped"]["glitch"] == 0
a = df[df.ticker == "AAA"].iloc[0]
assert abs(a["pct"] - 50.0) < 1e-9 and a["splits"] == 1 and str(a["entry"]) == idx[199].date().isoformat() and a["c0"] == 1.0
assert abs(a["r20"] - 100.0) < 1e-9 and abs(a["r60"] - 100.0) < 1e-9 and abs(a["max60"] - 100.0) < 1e-9 and abs(a["min60"] - 100.0) < 1e-9   # 진입(199) 뒤 20·60거래일은 2배 구간
assert abs(a["c0_raw"] - 0.2) < 1e-9                                                                                                 # 진입 뒤 1:5 병합 반영한 당시 가격
assert st.bucket(a["pct"]) == "20~50%" and st.bucket(0) == "≤0%" and st.bucket(10) == "0~10%" and st.bucket(10.1) == "10~20%" and st.bucket(500) == ">100%"
g = df[df.ticker == "GLT"].iloc[0]; assert str(g["entry"]) >= (pd.Timestamp(d_asof1) + pd.Timedelta(days=5)).date().isoformat() and g["pct"] == 0.0
tb = st.table_by_bucket(df); assert tb.loc["20~50%", "n"] == 1 and abs(tb.loc["20~50%", "med60"] - 100.0) < 1e-9 and tb.loc["20~50%", "spike30"] == 100.0 and tb.loc["≤0%", "flat"] == 100.0
tt = st.table_by_threshold(df, ths=(20,)); assert list(tt["n"]) == [1, 1] and abs(st.tmean(pd.Series([0, 1, 2, 3, 100.0]), cut=0.2) - 2.0) < 1e-9
# 야후 오류(60일에 50배↑) 제외
px["GLT"].loc[idx[200:], "Close"] = 100.0        # 진입(≈193번째) 뒤 60거래일 안에 100배 → 오류로 제외
df2 = st.build_pairs(hist, px); assert "GLT" not in set(df2["ticker"]) and df2.attrs["dropped"]["glitch"] == 1
print("ALL OK")
