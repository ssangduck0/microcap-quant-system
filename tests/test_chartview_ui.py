import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""📐 스승 관점 화면: 📈 차트 탭 안 구역(신호 칩 · 한 줄 판독 · 채널 차트 · 매물대 · 체크리스트 표) · 최근 신호 표 · 🏢 종목 헤더 칩(가짜 일봉·분봉, 인터넷 없음)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import numpy as np
import pandas as pd
import db, chartview as cv
db.init_db()
rng = np.random.default_rng(3)


def daily(closes, vols=None, start="2026-04-01", opens=None, highs=None):
    idx = pd.bdate_range(start, periods=len(closes)); c = np.array(closes, float)
    o = np.array(opens, float) if opens is not None else np.r_[c[0], c[:-1]]
    h = np.array(highs, float) if highs is not None else np.maximum(o, c) * 1.02
    return pd.DataFrame({"Open": o, "High": h, "Low": np.minimum(o, c) * 0.98, "Close": c, "Volume": np.array(vols, float) if vols is not None else 1e6}, index=idx)


flat = list(1.0 + rng.normal(0, 0.01, 100))
c = flat + [1.8, 2.4, 2.8, 3.0, 2.6, 2.3, 2.05, 1.95, 1.9]
v = [1e6] * 100 + [1.2e7, 8e6, 6e6, 5e6, 3e6, 2.5e6, 2e6, 1.5e6, 1.2e6]
o = np.r_[c[0], c[:-1]]; o[100] = 1.0
h = np.maximum(o, c) * 1.01; h[100] = 1.85; h[103] = 3.05
d1 = daily(c, v, opens=o, highs=h)
h60 = daily(list(np.linspace(1.3, 1.15, 242) + rng.normal(0, 0.003, 242)) + [1.9, 1.92, 1.91, 1.93, 1.9, 1.92, 1.91, 1.9], start="2026-01-01")
m5 = daily(list(1.9 + rng.normal(0, 0.002, 300)), start="2026-09-01")
cv.fetch_intraday = lambda ticks, want60=True, want5=True: ({t: h60 for t in ticks}, {t: m5 for t in ticks})
import watch_ui; watch_ui.prices = lambda tk: {t: d1 for t in tk}
import market; market.download_daily = lambda tickers, period="6mo", chunk=50: {t: d1 for t in tickers}
now_iso = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-27", "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now_iso, "last_seen": now_iso, "price": 1.9, "high_20d": 3.0, "low_20d": 0.9,
        "drawdown_pct": -38.0, "day_change_pct": -2.0, "volume_mult": 1.2, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.05, "quant_score": 70.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0, "win_score": 80.0})
    cv.ensure(conn)
    a0 = cv.analyze(d1, h60, m5)
    cv.record(conn, "2026-10-27", "AAA", a0["signals"], a0["px"]); conn.commit()
# 헤더 칩(일봉만)
import chartview_ui
chip = chartview_ui.header_chip("AAA", d1); assert "📐" in chip and "허리" in chip, chip
assert chartview_ui.header_chip("AAA", None) == "" and chartview_ui.header_chip("AAA", d1.head(10)) == ""
tb = chartview_ui.checklist_table(a0); assert {"누구", "항목", "상태", "내용"} <= set(tb.columns) and (tb["누구"] == "ANO").any() and (tb["누구"] == "키쟈").any()
assert "📐 급등 후 눌림 타점" in chartview_ui.signal_chips(a0)
# 📈 차트 화면
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "chart"
at = AppTest.from_file(APP, default_timeout=240).run(); assert not at.exception, [e.value for e in at.exception]
dfs = [d.value for d in at.dataframe]
assert any("항목" in d.columns and "상태" in d.columns for d in dfs), [list(d.columns) for d in dfs]          # 체크리스트 표
assert any("신호" in d.columns and (d["티커"] == "AAA").any() for d in dfs), [list(d.columns) for d in dfs]   # 최근 신호 표
caps = "\n".join(x.value for x in at.caption)
assert "📐 기준봉" in caps and "체크리스트 ✅" in caps and "60분봉" in caps, caps
html = "\n".join(m.value for m in at.markdown); assert "📐 급등 후 눌림 타점" in html and "60분봉 200선 돌파 지지" in html
assert any(e.label.startswith("📐 스승 관점") for e in at.expander)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
