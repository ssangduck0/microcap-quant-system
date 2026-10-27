import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import sys; sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd, live
ny = "America/New_York"
prev = pd.date_range("2026-10-20 09:30", "2026-10-20 15:59", freq="1min", tz=ny)
reg = pd.date_range("2026-10-21 09:30", "2026-10-21 15:59", freq="1min", tz=ny)
aft = pd.date_range("2026-10-21 16:00", "2026-10-21 16:59", freq="1min", tz=ny)
pc = np.full(len(prev), 0.0899)
rc = np.linspace(0.09, 0.1542, len(reg))
ac = np.r_[np.linspace(0.158, 0.20, 25), np.linspace(0.20, 0.18, 20), np.full(10, 0.18), [0.181, 0.183, 0.186, 0.186, 0.186]][:len(aft)]
idx = prev.append(reg).append(aft)
c = np.r_[pc, rc, ac]
m1 = pd.DataFrame({"Open": c, "High": c * 1.001, "Low": c * 0.999, "Close": c, "Volume": 1e4}, index=idx); m1.iloc[-1, 4] = 136440
d1 = pd.DataFrame({"High": [46.8, 1.0, 0.2], "Low": [0.5, 0.08, 0.08], "Close": [40, 0.09, 0.0899]}, index=pd.to_datetime(["2025-11-01", "2026-10-19", "2026-10-20"]))
a = live.analyze(m1, d1, 1.03e6); print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in a.items() if k not in ("window", "signals")}); print(a["signals"])
assert a["session"] == "애프터" and abs(a["prev_close"] - 0.0899) < 1e-9 and abs(a["reg_close"] - 0.1542) < 1e-9 and abs(a["chg_prev"] - (0.186 / 0.0899 - 1) * 100) < 1e-6
assert abs(a["reg_chg"] - (0.1542 / 0.0899 - 1) * 100) < 1e-6 and abs(a["chg_session"] - (0.186 / 0.1542 - 1) * 100) < 1e-6 and 50 < a["pos"] < 80 and a["from_hi52"] < -99
names = [s[0] for s in a["signals"]]; assert names[:3] == ["급등", "고점 이탈", "지지 확인"] and "거래량" in names and "변동성 주의" in names
assert "136.44K" in dict((s[0], s[1]) for s in a["signals"])["거래량"]
print("ALL OK")

from streamlit.testing.v1 import AppTest
import os, tempfile
os.environ["QUANT_DB"] = os.path.join(tempfile.mkdtemp(), "q.db")
import db; db.init_db()
at = AppTest.from_file(__import__("os").path.join(__import__("tempfile").gettempdir(), "live_app.py"), default_timeout=120).run(); assert not at.exception, [e.value for e in at.exception]
assert [x.label for x in at.tabs][0] == "⚡ 지금"
html = "\n".join(m.value for m in at.markdown); assert "SHFS 분석 결과" in html and "애프터" in html and "차트 구간 내 위치" in html and "신호 요약" in html and "급등" in html
print("LIVE UI OK")
