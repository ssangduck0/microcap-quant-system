import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, piggy, market, halts
db.init_db(); piggy.ensure_tables(); halts.fetch = lambda *a, **k: []
db.set_meta("usdkrw", "1342.0")
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=122)[-120:]; t = np.arange(120)
def frame(c, s=0.02): c = np.asarray(c, float); return pd.DataFrame({"Open": c, "High": c * (1 + s), "Low": c * (1 - s), "Close": c, "Volume": 200000.0}, index=idx)
PX = {"LOWZ": frame(np.r_[0.575 + 0.07 * np.sin(t[:119] / 3.0), 0.51]), "HIGHZ": frame(np.r_[0.575 + 0.07 * np.sin(t[:119] / 3.0), 0.64]),
      "BRK": frame(np.r_[0.575 + 0.07 * np.sin(t[:110] / 3.0), np.full(10, 0.40)]), "ATMX": frame(0.575 + 0.07 * np.sin(t / 3.0)), "DOWN": frame(np.linspace(0.9, 0.4, 120)),
      "PRICY": frame(np.full(120, 5.0))}
market.download_daily = lambda tk, period="3mo", chunk=200: {x: (PX[x].tail(5) if period == "5d" else PX[x]) for x in tk if x in PX}
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": idx[-1].strftime("%Y-%m-%d"), "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0,
        "low_20d": 0.9, "drawdown_pct": -40.0, "day_change_pct": -15.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0,
        "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    for tk in PX: conn.execute("INSERT OR REPLACE INTO case_progress (ticker, status) VALUES (?, 'done')", (tk,))
    db.save_dilution(conn, {"ticker": "ATMX", "cik": 1, "status": "ATM", "flags": {}, "evidence": []})
    conn.commit()
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception and "🐷 저금통" in [x.label for x in at.tabs]
assert any("저금통이 비어 있습니다" in i.value for i in at.info) and any("아직 분석 결과가 없습니다" in i.value for i in at.info)
# 후보 찾기 실행 → 필터
[b for b in at.button if b.key == "ps_run"][0].click().run(); assert not at.exception
scr = [d.value for d in at.dataframe if "안정성" in d.value.columns and "반등" in d.value.columns][0]; print(scr[["티커", "안정성", "박스 위치(%)", "희석"]].to_string(index=False))
assert set(scr["티커"]) == {"LOWZ", "HIGHZ"}                                             # 이탈(BRK)·하락(DOWN)·희석(ATMX)·고가(PRICY) 제외
at.checkbox(key="ps_nd").set_value(False).run(); assert "ATMX" in set([d.value for d in at.dataframe if "반등" in d.value.columns][0]["티커"])
at.checkbox(key="ps_nd").set_value(True).run(); at.checkbox(key="ps_low").set_value(True).run()
assert list([d.value for d in at.dataframe if "반등" in d.value.columns][0]["티커"]) == ["LOWZ"]   # 저점 구간만
# 후보 상세(첫 행 LOWZ) → 카테고리 고르고 담기
[b for b in at.button if b.key == "ps_add_LOWZ"][0].click().run(); assert piggy.tickers() == ["LOWZ"] and not at.exception
piggy.add("HIGHZ", "바이오·헬스"); piggy.add("BRK", "기타")
st.cache_data.clear(); at = AppTest.from_file(APP, default_timeout=120).run(); assert not at.exception
lst = [d.value for d in at.dataframe if "상태" in d.value.columns and "박스 위치(%)" in d.value.columns][0]; print(lst[["카테고리", "티커", "상태", "현재가(원)", "수량(주)", "박스"]].to_string(index=False))
z = dict(zip(lst["티커"], lst["상태"])); assert z == {"LOWZ": "🟢 저점 구간", "HIGHZ": "🔴 고점 구간", "BRK": "⚠️ 박스 이탈"}
low = lst.set_index("티커").loc["LOWZ"]; assert low["수량(주)"] == int(1_000_000 / (0.51 * 1342.0)) and low["박스"] == "자동"
mt = {m.label: m.value for m in at.metric}; assert mt["담은 종목"] == "3개" and mt["🟢 저점 구간"] == "1" and mt["⚠️ 박스 이탈"] == "1"
# 상세: BRK 선택 → 이탈 경고, 박스 직접 입력 저장
at.session_state["pg_table_pick"] = "BRK"; at.run()
assert any("박스 아래로 이탈" in w.value for w in at.warning)
at.number_input(key="pg_lo_BRK").set_value(0.35); at.number_input(key="pg_hi_BRK").set_value(0.45); [b for b in at.button if b.key == "pg_save_BRK"][0].click().run()
row = piggy.items().set_index("ticker").loc["BRK"]; assert row["box_low"] == 0.35 and row["box_high"] == 0.45
st.cache_data.clear(); at = AppTest.from_file(APP, default_timeout=120).run()
lst = [d.value for d in at.dataframe if "상태" in d.value.columns and "박스 위치(%)" in d.value.columns][0]; b = lst.set_index("티커").loc["BRK"]
assert b["박스"] == "직접" and b["상태"] == "⏸ 중간"                                         # 새 박스 기준으로 다시 판정
# 카테고리 필터
at.radio(key="pg_cat").set_value("바이오·헬스").run(); assert list([d.value for d in at.dataframe if "상태" in d.value.columns and "박스 위치(%)" in d.value.columns][0]["티커"]) == ["HIGHZ"]
# 매매 기록 저장 → 통계
tr = pd.DataFrame([{"id": None, "date": "2026-10-10", "ticker": "LOWZ", "buy": 0.50, "sell": 0.60, "qty": 1000, "fee_pct": 0.0, "note": ""}])
piggy.save_trades(tr); at.run(); assert {m.label: m.value for m in at.metric}["승률"] == "100%"
# 스캐너 알림 연결: 저금통 종목 가격이 저점 구간이면 텔레그램 호출
import scanner, notify
sent = []; notify.send_telegram = lambda m: sent.append(m) or True
msgs = piggy.alerts({"LOWZ": 0.51}, today="2026-10-20"); assert msgs and "LOWZ" in msgs[0]
print("ALL OK")
