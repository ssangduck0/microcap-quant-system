import sys; sys.path.insert(0, __import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd, live, ui_kit, report_dialog
ny = "America/New_York"
idx = pd.date_range("2026-10-20 09:30", "2026-10-20 15:59", freq="1min", tz=ny).append(pd.date_range("2026-10-21 09:30", "2026-10-21 16:30", freq="1min", tz=ny))
c = np.r_[np.full(390, 0.09), np.linspace(0.09, 0.1542, 390), np.linspace(0.158, 0.186, 31)]
m1 = pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1e4}, index=idx)
live.fetch = lambda t: live.analyze(m1, None, 1e6)
ui_kit.inject()
report_dialog.render("SHFS", focus="live")
