import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, piggy, watch, market, halts, shortflow as sf, notes_ui
db.init_db(); piggy.ensure_tables(); halts.fetch = lambda *a, **k: []; db.set_meta("usdkrw", "1342.0")
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=122)[-120:]
base = []
for k in range(7):                                       # 반등 반복 7번(98거래일) → 최근 60거래일 안에 2번 이상 포함
    base += list(np.linspace(0.58, 0.50, 7)) + list(np.linspace(0.50, 0.58, 7))
base += [0.52, 0.51] * 11
c = np.array(base[:120]); o = np.r_[c[0], c[:-1]]; vol = np.r_[np.full(100, 500000.), np.full(20, 200000.)]
def mk(o, c, v): return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99, "Close": c, "Volume": v}, index=idx)
BASE = mk(o, c, vol)
c2, o2 = c.copy(), o.copy()
for k, (oo, cc) in enumerate([(0.510, 0.518), (0.518, 0.527), (0.527, 0.535), (0.535, 0.544)]): o2[116 + k], c2[116 + k] = oo, cc
COVER = mk(o2, c2, vol)
up = np.linspace(0.5, 1.0, 120); UP = mk(np.r_[0.5, up[:-1]], up, np.full(120, 3e5))
PX = {"BASEX": BASE, "COVERX": COVER, "UPX": UP}
market.download_daily = lambda tk, period="3mo", chunk=200: {x: PX[x] for x in tk if x in PX}
now = db.utcnow_iso(); D = idx[-1].strftime("%Y-%m-%d")
with closing(db.connect()) as conn:
    for t in ("BASEX", "COVERX", "UPX"):
        db.upsert_snapshot(conn, {"date": D, "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": float(PX[t]["Close"].iloc[-1]), "high_20d": 2.0,
            "low_20d": 0.4, "drawdown_pct": -40.0, "day_change_pct": 0.5, "volume_mult": 1.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0,
            "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    sf.record(conn, "BASEX", idx[100].strftime("%Y-%m-%d"), sf.STAGES[2], 0.52)
piggy.add("BASEX", "기타"); piggy.add("COVERX", "기타"); watch.add("UPX", "관심")
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
assert sf.TIP_TITLE in notes_ui.list_titles() and "주우우욱 들어올릴때" in notes_ui.get(sf.TIP_TITLE)          # 꿀팁 원문이 노트에 보관
pl = [d.value for d in at.dataframe if "공매도 흐름" in d.value.columns and "박스 위치(%)" in d.value.columns][0]
sfmap = dict(zip(pl["티커"], pl["공매도 흐름"])); print(sfmap)
assert sfmap["BASEX"] == "② 바닥 반복 확인 — 진입 검토" and sfmap["COVERX"] == "③ 수익확정 커버형 양봉 — 눌림 대비"
wl = [d.value for d in at.dataframe if "공매도 흐름" in d.value.columns and "출회 가능(M주)" in d.value.columns][0]; assert dict(zip(wl["티커"], wl["공매도 흐름"]))["UPX"] == "–"
assert any("공매도 흐름 (스승님 꿀팁)" in m.value for m in at.markdown) and any(sf.TIP_TITLE in e.label for e in at.expander)
tabs = [d.value for d in at.dataframe if "단계" in d.value.columns and "티커" in d.value.columns and len(d.value.columns) == 2]
assert tabs and list(tabs[0]["티커"])[:2] == ["COVERX", "BASEX"]                                              # 단계 순서(④→③→②→①)
ev = [d.value for d in at.dataframe if "5일 최고(%)" in d.value.columns][0]; print(ev.to_string(index=False))
assert ev.iloc[0]["티커"] == "BASEX" and ev.iloc[0]["확인 일수"] == 5
at.slider(key="sf_cycles").set_value(6).run(); assert not at.exception
pl = [d.value for d in at.dataframe if "공매도 흐름" in d.value.columns and "박스 위치(%)" in d.value.columns][0]
assert dict(zip(pl["티커"], pl["공매도 흐름"]))["BASEX"] == "① 바닥 횡보 관찰 중"                                # 기준값을 바꾸면 다시 판정
# 스캐너 경로: 기록 + 알림 한 번
import scanner, notify, config
sent = []; notify.send_telegram = lambda m: sent.append(m) or True
with closing(db.connect()) as conn:
    r = sf.analyze(COVER); assert sf.record(conn, "COVERX", "2026-10-20", r["stage"], r["price"]) and not sf.record(conn, "COVERX", "2026-10-20", r["stage"], r["price"])
print("ALL OK")
