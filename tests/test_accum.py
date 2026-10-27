import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, accum
db.init_db()
idx = pd.bdate_range(end="2026-10-14", periods=62)[-60:]
c = np.full(60, 1.00); v = np.full(60, 1e5)
c[-25:-5] = np.linspace(1.0, 1.05, 20)
c[55] = c[54]
for k, (ch, vr) in enumerate([(0.02, 3), (0.01, 3.5), (0.0, 4), (0.143, 30)]):            # 마지막 4일: 흡수일 4번, 마지막 날 강한 매집(+14.3%)
    i = 56 + k; c[i] = c[i - 1] * (1 + ch); v[i] = 1e5 * vr
df = pd.DataFrame({"Close": c, "Volume": v}, index=idx)
r = accum.analyze(df, filings=[("2026-07-01", "S-1")], regsho_days=None)
w, dd = r["주간"], r["일간"]; print(w["parts"], w["score"], w["top_day"], round(w["top_vr"], 1), round(w["top_chg"], 1))
assert w["n_absorb"] == 4 and w["n_strong"] == 1 and w["level"] == "강한 매집 의심" and w["top_vr"] >= 5 and abs(w["top_chg"] - 14.3) < 0.01 and w["top_day"] == "10/14"
assert w["parts"]["이유 미확인"] == 1.0 and w["parts"]["희석 서류 없음"] == 1.0                     # 7월 S-1 은 45일 밖
assert dd["n_absorb"] == 1 and "월간" in r and r["월간"]["n_absorb"] >= 4
r2 = accum.analyze(df, filings=[("2026-10-13", "8-K"), ("2026-10-01", "424B5")], regsho_days=7)
assert r2["주간"]["parts"]["이유 미확인"] == 0 and r2["주간"]["parts"]["희석 서류 없음"] == 0 and r2["주간"]["parts"]["Reg SHO"] == 0.5
flat = pd.DataFrame({"Close": np.full(60, 1.0), "Volume": np.full(60, 1e5)}, index=idx); assert accum.analyze(flat) == {}
assert accum.analyze(df.tail(10)) is None
import market
market.download_daily = lambda tk, period="3mo", chunk=200: {t: df for t in tk if t == "KMRK"}
assert accum.run(["KMRK", "NONE"], out=lambda *_: None) == 1
lw = accum.latest("주간"); assert list(lw["ticker"]) == ["KMRK"] and lw.iloc[0]["data"]["level"] == "강한 매집 의심"
print("ALL OK")
