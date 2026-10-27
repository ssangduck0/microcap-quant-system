import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, datetime, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, pumpsetup as ps, watch, piggy, market, halts, notes_ui, sec
db.init_db(); halts.fetch = lambda *a, **k: []; db.set_meta("usdkrw", "1342.0")
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=122)[-120:]
c = np.r_[np.full(80, 1.0), np.linspace(1.0, 2.5, 40)]
PX = {"EWPL": pd.DataFrame({"Open": c, "High": c * 1.05, "Low": c * 0.97, "Close": c, "Volume": 1e6}, index=idx)}
market.download_daily = lambda tk, period="3mo", chunk=200: {x: PX[x] for x in tk if x in PX}
DOCS = {"0001": "proposal to approve a share consolidation and that the authorized share capital of the Company be increased",
        "0002": "an exempted company incorporated in the Cayman Islands offering units, each consisting of one ordinary share and one warrant to purchase. H.C. Wainwright placement agent"}
class FS(sec.SecClient):
    def __init__(s, *a, **k): pass
    def cik_for(s, t): return 5
    def submissions(s, c):
        F = [("0001", "6-K", idx[70].strftime("%Y-%m-%d")), ("0002", "F-1", idx[75].strftime("%Y-%m-%d"))]
        rec = {"accessionNumber": [x[0] for x in F], "primaryDocument": ["d.htm"] * 2, "form": [x[1] for x in F], "filingDate": [x[2] for x in F], "items": ["", ""]}
        return {"stateOfIncorporation": "E9", "stateOfIncorporationDescription": "Cayman Islands", "filings": {"recent": rec}}
    def fetch_text(s, url, limit=600000): return DOCS.get(url.split("/")[-2], "")
sec.SecClient = FS
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": idx[-1].strftime("%Y-%m-%d"), "ticker": "EWPL", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 2.5, "high_20d": 2.6,
        "low_20d": 1.0, "drawdown_pct": -5.0, "day_change_pct": 3.0, "volume_mult": 1.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.1, "quant_score": 50.0,
        "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    # 첫 분석이 80번째 날(가격 1.0)이었다고 가정 → 이후 20일 최고 = (idx[100] 고가)/1.0
    r0 = ps.analyze(FS(), conn, "EWPL", today=idx[80].date(), shares_out=3e6)
    r0["analyzed"] = idx[80].strftime("%Y-%m-%d"); ps.save(conn, "EWPL", r0, price=1.0)
watch.add("EWPL", "관심")
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception and "🕵️ 세력·셋업" in [x.label for x in at.tabs]
assert all(t in notes_ui.list_titles() for t in ps.TIPS)                                            # 꿀팁 원문 4개가 노트로
assert sum("포모를 못 견디면" in i.value for i in at.info) >= 3                                       # 세력·셋업 탭, 🎯 체크리스트, 📒 매매 기록
radar = [d.value for d in at.dataframe if "+신호" in d.value.columns][0]; r = radar.set_index("티커").loc["EWPL"]; print(radar.to_string(index=False))
assert r["+신호"] >= 5 and r["설립지"] == "케이맨 제도" and r["조달 상대방"] == "H.C. Wainwright" and r["판정"] == "강한 셋업"
exp = (PX["EWPL"]["High"].iloc[81:101].max() / 1.0 - 1) * 100; assert r["이후 결과"] == f"{exp:+.0f}%" and str(r["경과(거래일)"]) == "20", (r["이후 결과"], exp)  # 표에는 글자로('None' 대신 '아직 없음')
assert [d.value for d in at.dataframe if "이후 20일 최고 중앙값(%)" in d.value.columns]                 # 검증 표
wl = [d.value for d in at.dataframe if "셋업" in d.value.columns and "출회 가능(M주)" in d.value.columns][0]
assert wl.set_index("티커").loc["EWPL", "셋업"].startswith("강한 셋업")
assert any("🕵️ EWPL 세력·셋업" in m.value for m in at.markdown) and any(s.value.startswith("**강한 셋업**") for s in at.success)
assert any("극펌핑 종목의 공통점" in e.label for e in at.expander)
# 탭에서 새로 분석(가짜 SEC) → 결과 갱신
at.text_input(key="ps_in").set_value("EWPL"); [b for b in at.button if b.key == "ps_go"][0].click().run(); assert not at.exception
with closing(db.connect()) as conn:
    assert ps.cached(conn, "EWPL")[1]["verdict"] == "강한 셋업" and conn.execute("SELECT price FROM setup_first WHERE ticker='EWPL'").fetchone()["price"] == 1.0   # 첫 분석 가격 유지
print("ALL OK")
