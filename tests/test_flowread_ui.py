import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, flowread as fr, closewatch as cw, watch, piggy, market, halts, notes_ui
db.init_db(); cw.ensure_tables(); halts.fetch = lambda *a, **k: []; db.set_meta("usdkrw", "1342.0")
# 체크리스트 평가: 전일 대비 거래량 2.95배 + 하락 → 분산(참고 항목, 등급에는 영향 없음)
base = {"drop_pct": -8.05, "vol_total": 13052497.0, "prev_volume": 4429653.0}
ev = cw.evaluate(base); it = {i["key"]: i for i in ev["items"]}
assert it["dist"]["status"] == "fail" and it["dist"]["group"] == "info" and "2.9배" in it["dist"]["value"]
assert cw.evaluate({**base, "vol_total": 5e6})["items"][[i["key"] for i in ev["items"]].index("dist")]["status"] == "pass"
assert {i["key"]: i["status"] for i in cw.evaluate({"drop_pct": -20.0})["items"]}["dist"] == "unknown"
assert cw.evaluate(base)["grade"] == cw.evaluate({**base, "vol_total": 5e6})["grade"]                            # 등급 불변
# daily_context 가 전일 거래량을 돌려줌
ridx = pd.date_range("2026-10-12 09:30", "2026-10-12 15:59", freq="min", tz="America/New_York")
reg = pd.DataFrame({"Open": 7.9, "High": 8.0, "Low": 7.8, "Close": 7.9, "Volume": 100.0}, index=ridx)
cand = lambda o, h, l, c, v: {"openPrice": str(o), "highPrice": str(h), "lowPrice": str(l), "closePrice": str(c), "volume": str(v), "timestamp": "x"}
ctx = cw.daily_context([cand(7.9, 8.1, 7.7, 7.92, 3e6), cand(10, 10.5, 9.8, 10.0, 1.2e6)] + [cand(10, 10.3, 9.7, 10, 1e6)] * 20, reg)
assert ctx["prev_volume"] == 1.2e6
print("checklist OK")
# 화면
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=62)[-60:]
def mk(c, v, o=None):
    c, v = np.asarray(c, float), np.asarray(v, float); o = np.r_[c[0], c[:-1]] if o is None else np.asarray(o, float)
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.02, "Low": np.minimum(o, c) * 0.98, "Close": c, "Volume": v}, index=idx)
DIST = mk(np.r_[np.full(58, 0.30), 0.275, 0.253], np.r_[np.full(58, 4e6), 4429653, 13052497])          # 마지막 날 분산
SHAKE = mk(np.r_[np.full(58, 2.2), 2.17, 2.461], np.r_[np.full(58, 7e6), 7835865, 53207826])           # 마지막 날 털기
PX = {"DISTX": DIST, "SHAKEX": SHAKE}
market.download_daily = lambda tk, period="3mo", chunk=200: {x: PX[x] for x in tk if x in PX}
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    for t in PX:
        db.upsert_snapshot(conn, {"date": idx[-1].strftime("%Y-%m-%d"), "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": float(PX[t]["Close"].iloc[-1]),
            "high_20d": 3.0, "low_20d": 0.2, "drawdown_pct": -10.0, "day_change_pct": -8.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1,
            "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "ATM" if t == "DISTX" else "CLEAN", "excluded": 0})
        db.save_dilution(conn, {"ticker": t, "cik": 1, "status": "ATM" if t == "DISTX" else "CLEAN", "flags": {}, "evidence": []})
    fr.record(conn, "DISTX", idx[50].strftime("%Y-%m-%d"), fr.KINDS["dist"], 0.30)
watch.add("DISTX", "관심"); piggy.add("SHAKEX", "기타")
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
assert fr.TIP_TITLE in notes_ui.list_titles()
wl = [d.value for d in at.dataframe if "분산·털기" in d.value.columns and "출회 가능(M주)" in d.value.columns][0]
pg = [d.value for d in at.dataframe if "분산·털기" in d.value.columns and "박스 위치(%)" in d.value.columns][0]
print(dict(zip(wl["티커"], wl["분산·털기"])), dict(zip(pg["티커"], pg["분산·털기"])))
assert dict(zip(wl["티커"], wl["분산·털기"]))["DISTX"] == "🔻 분산 — 내릴 쪽" and dict(zip(pg["티커"], pg["분산·털기"]))["SHAKEX"] == "🔺 털기 — 다음날 상승 마감 확인 필요"
md = [m.value for m in at.markdown]; assert any("📈 DISTX 더 오를까 더 내릴까" in x for x in md) and any("📈 SHAKEX 더 오를까 더 내릴까" in x for x in md)
assert any("최근 판정: **🔻 분산" in e.value for e in at.error)
risk = [d.value for d in at.dataframe if "확인 항목" in d.value.columns]
dx = [r for r in risk if (r["값"] == "ATM").any()]; assert dx and dx[0].set_index("확인 항목").loc["희석 리스크: ATM·ELOC·전환사채", "결과"] == "❌ 문제"
sec_tbl = [d.value for d in at.dataframe if "판정" in d.value.columns and "5일 뒤 종가(%)" in d.value.columns][0]; assert sec_tbl.iloc[0]["티커"] == "DISTX"
assert any("📈 분산·털기" in x.label for x in at.tabs)
at.slider(key="fr_spike").set_value(8.0).run(); assert not at.exception
wl = [d.value for d in at.dataframe if "분산·털기" in d.value.columns and "출회 가능(M주)" in d.value.columns][0]; assert dict(zip(wl["티커"], wl["분산·털기"]))["DISTX"] == "–"   # 기준을 올리면 해당 없음
print("ALL OK")
