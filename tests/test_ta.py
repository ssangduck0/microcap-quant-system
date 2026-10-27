import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import sys; sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd, ta
idx = pd.bdate_range("2026-01-01", periods=160)
c = np.r_[np.linspace(10, 5, 120), np.linspace(5, 5.6, 40)]                                       # 긴 하락 뒤 반등
df = pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": 1e6}, index=idx)
x = ta.compute(df)
r = ta.rsi(pd.Series([1.0] * 20 + [2.0] * 5)); assert r.iloc[-1] == 100.0                           # 오르기만 하면 100
assert abs(x["RSI"].iloc[110] - 0) < 30 and x["RSI"].iloc[-1] > 50                                  # 하락 구간 과매도 → 반등
assert {"MA5", "MA20", "MA60", "macd", "signal", "span_a", "span_b", "cloud_thick_pct"} <= set(x.columns)
up = pd.Series(np.r_[np.linspace(10, 5, 100), np.linspace(5, 7, 6)], index=pd.bdate_range("2026-01-01", periods=106))
m = ta.macd(up); d = m["macd"] - m["signal"]; assert (d.iloc[-1] > 0) and (d.iloc[-10] < 0)          # 반등에 골든크로스
s = ta.signals(ta.compute(pd.DataFrame({"Open": up, "High": up * 1.01, "Low": up * 0.99, "Close": up, "Volume": 1e6})), {"cross_days": 7})   # 6일 전 교차
names = [i[0] for i in s["items"]]; print(names, s["values"])
assert any(n.startswith("MACD 골든크로스") for n in names) and any(n.startswith("일목") for n in names) and s["values"]["cloud_thick_pct"] is not None
low = pd.Series(np.r_[np.linspace(10, 5, 60), [4.8, 4.7, 4.75, 4.9, 5.1]], index=pd.bdate_range("2026-01-01", periods=65))
s2 = ta.signals(ta.compute(pd.DataFrame({"Open": low, "High": low * 1.01, "Low": low * 0.99, "Close": low, "Volume": 1e6})), {"rsi_low": 35})
assert any(n == "RSI 바닥 반등" for n, _, _ in s2["items"]), s2["items"]
print("ALL OK")
