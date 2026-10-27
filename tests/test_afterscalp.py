import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, afterscalp as af
db.init_db()
ET = ZoneInfo("America/New_York"); day = datetime(2026, 10, 15, tzinfo=ET)
A0, NOW = day.replace(hour=16), day.replace(hour=18, minute=30)
def build(prices, vol=100000.0, flat_mask=None, drop_mask=None):
    idx = pd.date_range(day.replace(hour=4), NOW, freq="min", tz=ET)[:len(prices)]
    c = np.asarray(prices, float); h, l = c * 1.003, c * 0.997; v = np.full(len(c), vol)
    if flat_mask is not None: h[flat_mask], l[flat_mask] = c[flat_mask], c[flat_mask]
    df = pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)
    if drop_mask is not None: df = df[~drop_mask]
    return df
n = len(pd.date_range(day.replace(hour=4), NOW, freq="min"))
t_after = int((A0 - day.replace(hour=4)).total_seconds() // 60)                 # 16:00 위치
base = np.full(n, 1.00)
base[t_after:t_after + 30] = np.linspace(1.00, 1.30, 30)                         # 16:00~16:30 급등 +30%
base[t_after + 30:t_after + 90] = np.linspace(1.30, 1.08, 60)                    # 16:30~17:30 눌림
base[t_after + 90:] = 1.08 + 0.002 * np.sin(np.arange(n - t_after - 90))         # 17:30~ 이동평균선 근처 횡보
GOOD = build(base)
r = af.analyze(GOOD, A0, NOW, fx=1342.0); print(r["stage"], {k: round(r[k], 3) if isinstance(r[k], float) else r[k] for k in ("value_krw", "candle_ratio", "max_gap", "spike_pct", "dist_ma50", "dist_ma200")})
assert r["stage"] == af.STAGE_IN and r["ok"] == {"value": True, "candle": True, "spike": True, "ma": True} and r["max_gap"] == 0
assert abs(r["plan"]["target"] / r["price"] - 1.05) < 1e-9 and abs(r["plan"]["stop"] / r["price"] - 0.95) < 1e-9
# 'ㅡ' 많은 종목: 애프터 최근 60분 중 절반이 고가=저가 → 캔들 불합격
fm = np.zeros(n, bool); fm[-60::2] = True
r2 = af.analyze(build(base, flat_mask=fm), A0, NOW, fx=1342.0); assert not r2["ok"]["candle"] and r2["flat"] >= 30 and r2["stage"] == "–"
# 거래가 띄엄띄엄(분봉 자체가 없는 분) → 공백으로 불합격
dm = np.zeros(n, bool); dm[-60:] = [i % 5 != 0 for i in range(60)]
r3 = af.analyze(build(base, drop_mask=dm), A0, NOW, fx=1342.0); assert r3["max_gap"] >= 4 and not r3["ok"]["candle"]
# 거래대금 부족(분당 100주)
assert not af.analyze(build(base, vol=100.0), A0, NOW, fx=1342.0)["ok"]["value"]
# 아직 고점 근처(눌림 전) → 관찰
hi = base.copy(); hi[t_after + 30:] = 1.29 + 0.002 * np.sin(np.arange(n - t_after - 30))
r4 = af.analyze(build(hi), A0, NOW, fx=1342.0); assert r4["stage"] == af.STAGE_WATCH and not r4["ok"]["ma"]
# 급등 없음
assert af.analyze(build(np.full(n, 1.0)), A0, NOW, fx=1342.0)["stage"] == "–"
assert af.analyze(GOOD, NOW - timedelta(minutes=1), NOW, fx=1342.0) is None and af.analyze(None, A0, NOW, 1342.0) is None   # 애프터 시작 직후는 판정 보류
# 결과: 신호(18:30, 1.08) 뒤 +5% 먼저 / -5% 먼저 / 마감 전 가격
dl = af.deadline_of(day.replace(hour=20)); assert dl == day.replace(hour=19, minute=50)
fut_idx = pd.date_range(NOW + timedelta(minutes=1), day.replace(hour=20), freq="min", tz=ET)
def fut(path): c = np.interp(np.arange(len(fut_idx)), np.linspace(0, len(fut_idx) - 1, len(path)), path); return pd.DataFrame({"Open": c, "High": c * 1.001, "Low": c * 0.999, "Close": c, "Volume": 1e5}, index=fut_idx)
oc = af.outcome(fut([1.08, 1.14, 1.02]), NOW, 1.08, dl); print(oc)
assert oc["first_hit"] == "목표 +5%" and oc["max_up"] > 5 and -5 < oc["max_down"] < 0   # 최저점(1.02)은 매도 마감(19:50) 뒤라 결과에 안 들어감
assert af.outcome(fut([1.08, 1.02, 1.20]), NOW, 1.08, dl)["first_hit"] == "손절 -5%"
oc3 = af.outcome(fut([1.08, 1.10, 1.09]), NOW, 1.08, dl); assert oc3["first_hit"] is None and abs(oc3["exit_price"] - fut([1.08, 1.10, 1.09]).loc[:dl, "Close"].iloc[-1]) < 1e-9
# 저장
with closing(db.connect()) as conn:
    assert af.record_signal(conn, "2026-10-15", "GOODX", NOW, 1.08) and not af.record_signal(conn, "2026-10-15", "GOODX", NOW, 1.09)
    af.update_outcome(conn, "2026-10-15", "GOODX", oc); af.save_state(conn, "2026-10-15", "GOODX", {**r, "chart": af.chart_series(GOOD)})
s = af.signals().iloc[0]; assert s["first_hit"] == "목표 +5%" and s["price"] == 1.08
st_ = af.states("2026-10-15")[0][2]; assert st_["stage"] == af.STAGE_IN and len(st_["chart"]["close"]) == 240 and st_["chart"]["ma200"][-1] is not None
print("ALL OK")
