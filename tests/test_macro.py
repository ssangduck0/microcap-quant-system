import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from datetime import date
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import pandas as pd
import db, macro
db.init_db()
vix = pd.DataFrame({"Close": [15.0, 16.2, 22.5]}, index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"]))
v = macro.fetch_vix(lambda: vix); assert v["value"] == 22.5 and abs(v["chg"] - 6.3) < 1e-9 and v["level"] == "경계"
class R:
    def __init__(s, j=None, t=""): s._j, s.text = j, t
    def json(s): return s._j
f = macro.fetch_fng(lambda u: R({"fear_and_greed": {"score": 27.4, "rating": "fear", "previous_close": 31.0, "previous_1_week": 45.0, "timestamp": "2026-10-19T20:00:00"}}))
assert {k: v for k, v in f.items() if k != "hist"} == {"score": 27.4, "prev": 31.0, "week": 45.0, "rating": "공포", "at": "2026-10-19T20:00"} and f["hist"] == []
data = [{"year": "2026", "period": f"M{m:02d}", "value": str(140 + m * 0.1), "footnotes": [{"code": "P"}] if m == 9 else [{}]} for m in range(1, 10)]
data += [{"year": "2025", "period": f"M{m:02d}", "value": str(138 + m * 0.1), "footnotes": [{}]} for m in range(1, 13)] + [{"year": "2025", "period": "M13", "value": "1"}]
i = macro.fetch_imp(lambda u: R({"Results": {"series": [{"data": data}]}})); print(i)
assert i["month"] == "2026-09" and abs(i["mom"] - (140.9 / 140.8 - 1) * 100) < 1e-9 and abs(i["yoy"] - (140.9 / 138.9 - 1) * 100) < 1e-9 and i["prelim"]
html = "<tr><td>September 2026</td><td>Oct. 16, 2026</td></tr><tr><td>October 2026</td><td>Nov. 13, 2026</td></tr><tr><td>Sept. 9, 2026</td></tr>"
assert macro.parse_schedule(html, date(2026, 10, 19)) == "2026-11-13" and macro.parse_schedule("none", date(2026, 10, 19)) is None
calls = []
def boom(): raise ConnectionError("CNN blocked")
d = macro.refresh(fetchers={"vix": lambda: (calls.append(1), {"value": 20.0})[1], "fng": boom, "imp": lambda: {"mom": 0.3}, "imp_next": lambda: {"date": "2026-11-13"}})
assert d["vix"]["value"] == 20.0 and d["fng"]["_err"].startswith("ConnectionError") and d["imp"]["mom"] == 0.3
macro.refresh(fetchers={"vix": lambda: (calls.append(1), {"value": 21.0})[1], "fng": boom, "imp": lambda: {"mom": 0.3}, "imp_next": lambda: {"date": "x"}})
assert len(calls) == 1 and macro.get()["vix"]["value"] == 20.0                                          # 15분 안에는 다시 안 받음
macro.set_manual("2026-11-13", 0.2); assert macro.manual() == {"next_date": "2026-11-13", "forecast": 0.2}
print("ALL OK")
# 화면: 맨 위 시장 지표 줄 · 링크 · 관리 모드 입력
from contextlib import closing
from datetime import timedelta
import halts; halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
nd = (date.today() + timedelta(days=5)).isoformat()
macro.refresh(force=True, fetchers={"vix": lambda: {"value": 22.5, "chg": 6.3, "level": "경계", "date": "2026-10-19"}, "fng": lambda: {"score": 27.4, "rating": "공포", "prev": 31.0, "week": 45.0},
                                   "imp": lambda: {"month": "2026-09", "mom": 0.4, "yoy": 1.4, "prelim": True}, "imp_next": lambda: {"date": nd}})
macro.set_manual(None, 0.2)
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ["QUANT_TEST_PAGE"] = "home"
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "VIX 변동성" in html and "22.50" in html and "27 · 공포" in html and "전월비 +0.4%" in html and "예상 +0.2% 대비 상회" in html and "(잠정)" in html and "D-5" in html
assert "fear-and-greed" in html and "bls.gov/mxp" in html and "investing.com" in html                     # 데이터 출처 링크
os.environ["QUANT_TEST_PAGE"] = "admin"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
at.text_input(key="mc_date").set_value("2026-11-13"); at.text_input(key="mc_fc").set_value("-0.1"); [b for b in at.button if b.key == "mc_save"][0].click().run()
assert macro.manual() == {"next_date": "2026-11-13", "forecast": -0.1}
at.text_input(key="mc_fc").set_value("abc"); [b for b in at.button if b.key == "mc_save"][0].click().run(); assert any("숫자로" in e.value for e in at.error)
os.environ.pop("QUANT_TEST_PAGE"); print("UI OK")
# 차트용 이력
import pandas as pd
v = macro.fetch_vix(lambda: pd.DataFrame({"Close": [15.0, 16.0, 17.0]}, index=pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"])))
assert v["hist"] == [["2026-10-16", 15.0], ["2026-10-19", 16.0], ["2026-10-20", 17.0]]
f = macro.fetch_fng(lambda u: R({"fear_and_greed": {"score": 28, "rating": "fear"}, "fear_and_greed_historical": {"data": [{"x": 1760000000000, "y": 40.0}, {"x": 1760086400000, "y": 28.0}]}}))
assert len(f["hist"]) == 2 and f["hist"][1][1] == 28.0
i = macro.fetch_imp(lambda u: R({"Results": {"series": [{"data": data}]}})); assert len(i["hist"]) == 20 and i["hist"][-1][0] == "2026-09"
macro.refresh(force=True, fetchers={"vix": lambda: v, "fng": lambda: f, "imp": lambda: i, "imp_next": lambda: {"date": nd}})
os.environ["QUANT_TEST_PAGE"] = "home"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
def count_charts(n):
    k = 1 if getattr(n, "type", "") == "vega_lite_chart" else 0
    ch = getattr(n, "children", None)
    return k + (sum(count_charts(x) for x in ch.values()) if isinstance(ch, dict) else 0)
assert count_charts(at._tree) >= 3
os.environ.pop("QUANT_TEST_PAGE"); print("CHART OK")
