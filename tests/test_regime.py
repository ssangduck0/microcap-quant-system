import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🚦 소형주 장세 신호등: FRED CSV 파싱 · 재료 → 점수(🟢/🟡/🔴) · 재료 일부 없어도 계산 · 저장·TTL · 홈 화면 표시(가짜 자료, 인터넷 없음)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np
import pandas as pd
import db, regime, halts
db.init_db(); halts.fetch = lambda *a, **k: []
from contextlib import closing
_now = db.utcnow_iso()
with closing(db.connect()) as conn:   # 홈이 그려지려면 스냅샷 한 줄은 있어야
    db.upsert_snapshot(conn, {"date": pd.Timestamp.today().strftime("%Y-%m-%d"), "ticker": "RGM", "exchange": "NASDAQ", "first_seen": _now, "last_seen": _now, "price": 1.0, "high_20d": 2.0,
        "low_20d": 0.9, "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0,
        "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()


class R:
    def __init__(self, text): self.text = text


def fred(vals, start="2026-01-01"):
    idx = pd.bdate_range(start, periods=len(vals))
    return "observation_date,X\n" + "\n".join(f"{d:%Y-%m-%d},{'.' if v is None else v}" for d, v in zip(idx, vals))


s = regime.fetch_fred("DGS2", http_get=lambda u: R(fred([3.5, None, 3.6])))
assert list(s.round(2)) == [3.5, 3.6] and s.index[-1].strftime("%Y-%m-%d") == "2026-01-05"


def series(vals, start="2025-11-01"):
    return pd.Series(np.array(vals, float), index=pd.bdate_range(start, periods=len(vals)))


# 🟢: VIX 14 · 콘탱고 · 스프레드 잔잔 · SPY 200일선 위 · 나스닥 20일선 위
good = {"vix": series([15] * 10 + [14]), "vix9d": series([13]), "vix3m": series([17]), "hy": series([3.0] * 30), "dgs2": series([3.6] * 10), "dgs10": series([4.2] * 10),
        "spy": series(list(np.linspace(500, 600, 220))), "ixic": series(list(np.linspace(17000, 19000, 60)))}
g = regime.evaluate(good)
assert g["light"] == "green" and g["points"] == 0 and g["reasons"] == [] and len(g["ok"]) >= 4 and g["n_inputs"] == 8, g
# 🔴: VIX 22(하루 +20%) · 백워데이션 · 스프레드 5일 +0.5 · 2년물↓ + SPY↓ · SPY 200일선 아래 · 나스닥 20일선 아래·기울기↓
bad = {"vix": series([18] * 10 + [22]), "vix9d": series([24]), "vix3m": series([21]), "hy": series([3.0] * 25 + [3.1, 3.2, 3.3, 3.4, 3.5]),
       "dgs2": series([3.8] * 5 + [3.7, 3.65, 3.6, 3.6, 3.55]), "dgs10": series([4.2] * 10),
       "spy": series(list(np.linspace(500, 600, 200)) + list(np.linspace(600, 520, 20))), "ixic": series(list(np.linspace(19000, 17000, 60)))}
b = regime.evaluate(bad)
assert b["light"] == "red" and b["points"] >= 7, b
assert any("백워데이션" in r for r in b["reasons"]) and any("하이일드" in r for r in b["reasons"]) and any("200일선 아래" in r for r in b["reasons"]) and any("채권" in r for r in b["reasons"])
# 🟡: VIX 19 만 + 나머지 좋음 → 1점 … 거기에 SPY 200일선 아래(+2) → 3점 노랑
mid = {**good, "vix": series([18] * 10 + [19]), "spy": series(list(np.linspace(600, 500, 220)))}
y = regime.evaluate(mid); assert y["light"] == "yellow" and y["points"] == 3, y
# 재료 일부 없음
part = regime.evaluate({"vix": series([25]), "spy": None, "hy": None}); assert part["light"] == "yellow" and part["points"] == 2 and part["n_inputs"] == 1
# FRED 없을 때 HYG/IEF 대체: 비율이 5일에 −1.5% → 스프레드 확대 +1
px_ = regime.evaluate({"hyg_ief": series([0.85] * 25 + [0.85, 0.845, 0.84, 0.838, 0.837])}); assert px_["points"] == 1 and any("HYG/IEF" in r for r in px_["reasons"]), px_
assert regime.evaluate({"hyg_ief": series([0.85] * 30)})["points"] == 0
# DBnomics JSON 파싱
class J:
    def __init__(self, d): self._d = d
    def json(self): return self._d
sd = regime.fetch_dbnomics("FED/H15/RIFLGFCY02_N.B", http_get=lambda u: J({"series": {"docs": [{"period": ["2026-01-02", "2026-01-05", "2026-01-06"], "value": [3.5, "NA", 3.6]}]}}))
assert list(sd.round(2)) == [3.5, 3.6]
# FRED 가 시간 초과면 금리는 DBnomics 로
def http_mix(u):
    if "fred.stlouisfed" in u:
        raise TimeoutError("blocked")
    return J({"series": {"docs": [{"period": [f"2026-01-{d:02d}" for d in range(1, 11)], "value": [3.6] * 10}]}})
xx = regime.fetch(download=lambda: {}, http_get=http_mix); assert xx["hy"] is None and xx["dgs2"] is not None and len(xx["dgs2"]) == 10 and xx["dgs10"] is not None
assert regime.evaluate({})["n_inputs"] == 0
# 저장·TTL: 가짜 야후·FRED
frames = {"^VIX": pd.DataFrame({"Close": good["vix"]}), "^VIX9D": pd.DataFrame({"Close": good["vix9d"]}), "^VIX3M": pd.DataFrame({"Close": good["vix3m"]}),
          "SPY": pd.DataFrame({"Close": good["spy"]}), "^IXIC": pd.DataFrame({"Close": good["ixic"]})}
calls = []
def http(u):
    calls.append(u); return R(fred([3.0] * 30))
r1 = regime.refresh(force=True, download=lambda: frames, http_get=http)
assert r1["light"] == "green" and r1["_err"] is None and len(calls) == 3 and regime.get()["label"].startswith("🟢")
r2 = regime.refresh(download=lambda: (_ for _ in ()).throw(RuntimeError("no")), http_get=http); assert r2["light"] == "green" and len(calls) == 3   # TTL 안이면 안 받음
r3 = regime.refresh(force=True, download=lambda: {}, http_get=lambda u: (_ for _ in ()).throw(RuntimeError("down")))
assert r3["_err"] and r3.get("light") == "green"                                                                                   # 실패하면 예전 값 유지 + 오류 표시
# 홈 화면: 신호등 줄
from streamlit.testing.v1 import AppTest
regime.refresh(force=True, download=lambda: frames, http_get=http)
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "소형주 장세" in html and "🟢" in html, html[:500]
os.environ["QUANT_TEST_PAGE"] = "rank"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
assert any("🚦" in m.value for m in at.markdown)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
