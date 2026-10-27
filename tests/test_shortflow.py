import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, shortflow as sf
db.init_db()
idx = pd.bdate_range(end="2026-10-14", periods=62)[-60:]
def mk(o, c, vol, hi=None, lo=None):
    o, c, v = (np.asarray(x, float) for x in (o, c, vol))
    h = np.maximum(o, c) * 1.01 if hi is None else np.asarray(hi, float); l = np.minimum(o, c) * 0.99 if lo is None else np.asarray(lo, float)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)
# 바닥 반복: 0.50 근처에서 3번 +15% 반등 후 최근 15일은 거래량 줄며 0.50~0.53 횡보
base = []
for k in range(3):
    base += list(np.linspace(0.58, 0.50, 7)) + list(np.linspace(0.50, 0.58, 7))
base += [0.52, 0.51, 0.52, 0.51, 0.50, 0.51, 0.52, 0.51, 0.52, 0.51, 0.52, 0.51, 0.51, 0.52, 0.51, 0.52, 0.51, 0.51]
c = np.array(base[:60]); o = np.r_[c[0], c[:-1]]; vol = np.r_[np.full(42, 500000.), np.full(18, 200000.)]
B = mk(o, c, vol)
r = sf.analyze(B); print(r["stage"], {k: r[k] for k in ("cycles", "vol_ratio", "range10_pct", "cover_run")})
assert r["base_ok"] and r["cycles"] >= 2 and r["stage"] == "② 바닥 반복 확인 — 진입 검토"
assert sf.analyze(B, {"min_cycles": 5})["stage"] == "① 바닥 횡보 관찰 중"                         # 반복이 부족하면 관찰 단계
# 수익확정 커버: 마지막 4일 얇은 양봉(+1~2%), 거래량 평범
c2 = c.copy(); o2 = o.copy()
for k, (oo, cc) in enumerate([(0.510, 0.518), (0.518, 0.527), (0.527, 0.535), (0.535, 0.544)]):
    o2[56 + k], c2[56 + k] = oo, cc
r2 = sf.analyze(mk(o2, c2, vol)); print(r2["stage"], r2["cover_run"])
assert r2["cover_run"] >= 4 and r2["stage"] == "③ 수익확정 커버형 양봉 — 눌림 대비"
v3 = vol.copy(); v3[-1] = 5_000_000                                                                  # 같은 양봉이라도 거래량이 폭발하면 커버형이 아님(압박성 매수일 수 있음)
assert sf.analyze(mk(o2, c2, v3))["cover_run"] == 0
# 들어올림: 장중 값(스캐너)으로 +25%, 거래량 6배
r4 = sf.analyze(B, live={"day_change_pct": 25.0, "volume_mult": 6.0}); assert r4["stage"] == "④ 들어올림 — 청산 검토" and "(장중)" in r4["items"][-1]["현재 값"]
assert sf.analyze(B, live={"day_change_pct": 25.0, "volume_mult": 1.0})["stage"] != "④ 들어올림 — 청산 검토"   # 거래량 없는 상승은 아님
# 상승 추세 종목은 해당 없음
up = np.linspace(0.5, 1.0, 60); assert sf.analyze(mk(np.r_[0.5, up[:-1]], up, np.full(60, 300000.)))["stage"] == "–"
assert sf.analyze(B.tail(20)) is None and sf.analyze(None) is None
# 보조 신호
h = sf.analyze(B, short={"borrow_avail_chg_pct": 40.0, "sv_ratio": 30.0, "sv_avg5_ratio": 50.0})["hints"]; print(h)
assert "빌린 주식 반환" in h[0] and "감소" in h[1]
assert sf.analyze(B, short={"borrow_avail_chg_pct": 40.0, "borrow_stale": True})["hints"] == []          # 오래된 IBKR 값은 쓰지 않음
# 신호 기록(하루 한 번) · 결과
with closing(db.connect()) as conn:
    assert sf.record(conn, "AAA", "2026-10-10", sf.STAGES[1], 0.50) and not sf.record(conn, "AAA", "2026-10-10", sf.STAGES[1], 0.51)
assert len(sf.events()) == 1
fut = mk(np.full(60, 0.5), np.r_[np.full(55, 0.5), [0.47, 0.46, 0.52, 0.60, 0.55]], np.full(60, 1e5), hi=np.r_[np.full(55, 0.505), [0.48, 0.47, 0.53, 0.62, 0.56]], lo=np.r_[np.full(55, 0.495), [0.45, 0.44, 0.50, 0.58, 0.54]])
oc = sf.outcome(fut, idx[54].strftime("%Y-%m-%d"), 0.50); print(oc)
assert oc["days"] == 5 and abs(oc["max_up"] - 24.0) < 1e-6 and abs(oc["max_down"] + 12.0) < 1e-6 and abs(oc["next_close"] + 6.0) < 1e-6 and abs(oc["close_n"] - 10.0) < 1e-6
assert sf.outcome(fut, "2026-10-14", 0.5) == {"days": 0} and sf.outcome(None, "x", 1) == {}
print("ALL OK")
