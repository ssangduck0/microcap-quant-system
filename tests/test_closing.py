import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db
db.init_db()
now = db.utcnow_iso()
NAMES = ["낙폭 -20% 이하","유통주식 2천만 이하","거래량 2배 이상","매수체결 55% 이상","ATM 미검출","CB 미검출","희석 상태 확인됨"]
def checks(n_ok): return json.dumps({"checks": [[k, i < n_ok] for i, k in enumerate(NAMES)]}, ensure_ascii=False)
def snap(t, **kw):
    r = {"date":"2026-10-12","ticker":t,"exchange":"NASDAQ","first_seen":now,"last_seen":now,"price":1.0,"high_20d":2.0,"low_20d":0.9,"drawdown_pct":-40.0,
         "day_change_pct":-15.0,"volume_mult":3.0,"gap_pct":-2.0,"close_loc":0.3,"buy_pressure":55.0,"float_shares":8e6,"atr14":0.1,"entry_ref":0.95,"stop_ref":0.85,
         "target_ref":1.15,"quant_score":50.0,"quant_detail":"{}","pump_score":40.0,"pump_detail":checks(5),"dilution_status":"CLEAN","excluded":0}
    r.update(kw); return r
rows = [snap("HIGH", win_score=90.0, win_p=0.5, pump_detail=checks(6)),
        snap("MID", win_score=60.0, win_p=0.3, pump_detail=checks(4), float_shares=50e6),
        snap("LOW", win_score=20.0, win_p=0.1, pump_detail=checks(2), day_change_pct=-5.0),
        snap("NOSC", pump_score=95.0, pump_detail=checks(7), day_change_pct=-4.0),          # 승률 점수 없음(정규장 스캔 전)
        snap("ATM1", dilution_status="ATM", excluded=1, pump_score=0.0, pump_detail=checks(3), drawdown_pct=-70.0),
        snap("ATM2", dilution_status="ATM", excluded=1, pump_score=0.0, pump_detail=checks(3))]
with closing(db.connect()) as conn:
    for r in rows: db.upsert_snapshot(conn, r)
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
def board(at):
    return [d.value for d in at.dataframe if "충족" in d.value.columns and "승률 점수" in d.value.columns][0]
def run(session):
    import streamlit as st
    st.cache_data.clear()          # us_session() 은 30초 캐시되므로 값을 바꿀 때마다 비운다
    db.set_meta("us_session", session)
    return AppTest.from_file(APP, default_timeout=90).run()

at = run("프리마켓")
print("exc:", [e.value for e in at.exception])
assert not at.exception
assert any("프리마켓" in w.value and "정규장 마감 30분 전" in w.value for w in at.warning)          # 정규장이 아니면 경고
t = board(at); print(t[["티커","승률 점수","충족","낙폭≤-20%","거래량≥2배","ATM 없음","희석 확인"]].to_string(index=False))
assert list(t["티커"]) == ["HIGH", "MID", "LOW", "NOSC"]                                           # 승률 점수 순, 점수 없는 종목은 뒤
ITEM_COLS = ["낙폭≤-20%", "유통≤2천만", "거래량≥2배", "매수≥55%", "ATM 없음", "CB 없음", "희석 확인"]
assert all(c in t.columns for c in ITEM_COLS) and "체크" not in t.columns                              # 항목마다 열이 따로 있고, 아이콘 한 줄 열은 없다
assert t.iloc[0]["충족"] == "6/7" and list(t.iloc[0][ITEM_COLS]) == ["✅"] * 6 + ["❌"]                  # HIGH: 마지막 항목(희석 확인)만 미충족
assert list(t.iloc[1][ITEM_COLS]) == ["✅"] * 4 + ["❌"] * 3 and list(t.iloc[3][ITEM_COLS]) == ["✅"] * 7
assert set(t[ITEM_COLS].stack().unique()) == {"✅", "❌"}
assert [m.value for m in at.metric if m.label == "ATM 정황으로 제외"] == ["2 개"]
assert [m.value for m in at.metric if m.label == "승률 점수 있는 종목"] == ["3 개"]
assert not any("ATM" in x for x in t["티커"])                                                       # ATM 종목은 표에 없음
# 정규장이면 경고 대신 안내
at = run("정규장"); assert not at.exception and not any("프리마켓" in w.value for w in at.warning) and any("정규장" in s.value for s in at.success)
# 필터: 승률 점수 ≥ 50 / 오늘 등락 -10% 이하 / 유통주식 ≤ 20M / 충족 ≥ 5
at.slider(key="cl_ws").set_value(50).run(); assert list(board(at)["티커"]) == ["HIGH", "MID"]
at.slider(key="cl_ws").set_value(0).run()
at.checkbox(key="cl_crash").set_value(True).run(); assert list(board(at)["티커"]) == ["HIGH", "MID"]       # LOW(-5%), NOSC(-4%) 제외
at.checkbox(key="cl_crash").set_value(False).run()
at.number_input(key="cl_float").set_value(20.0).run(); assert "MID" not in list(board(at)["티커"])
at.number_input(key="cl_float").set_value(0.0).run()
at.slider(key="cl_chk").set_value(5).run(); assert list(board(at)["티커"]) == ["HIGH", "NOSC"]              # 6/7, 7/7 만
at.slider(key="cl_chk").set_value(0).run()
# 정렬 기준 변경
at.selectbox(key="cl_sort").set_value("펌핑점수(참고)").run(); assert list(board(at)["티커"])[0] == "NOSC"
at.selectbox(key="cl_sort").set_value("낙폭(깊은 순)").run(); assert not at.exception
at.slider(key="cl_ws").set_value(0).run(); at.selectbox(key="cl_sort").set_value("승률 점수").run()
# 상세: 기본 선택은 첫 행(HIGH) -> 미충족 1개와 그 항목이 경고에 명시
assert at.selectbox(key="cl_pick").value == "HIGH"
w = [x.value for x in at.warning if "미충족" in x.value]; print("warning:", w)
assert w and "HIGH" in w[0] and "미충족 1개" in w[0] and "희석 상태 확인됨" in w[0]
det = [d.value for d in at.dataframe if "항목(기준)" in d.value.columns][0]
print(det.to_string(index=False))
assert list(det["항목(기준)"]) == NAMES and list(det["결과"]).count("❌ 미충족") == 1 and det.iloc[0]["결과"] == "✅ 충족"
assert det.iloc[0]["현재 값"] == "-40.0% (20일 고점 대비)" and det.iloc[2]["현재 값"] == "3.00배 (20일 평균 대비)" and det.iloc[1]["현재 값"] == "8.00백만 주"
# MID 선택 -> 미충족 3개, 값 확인 / NOSC 선택 -> 모두 충족
at.selectbox(key="cl_pick").set_value("MID").run()
w = [x.value for x in at.warning if "미충족" in x.value]; print("MID:", w)
assert w and "MID" in w[0] and "미충족 3개" in w[0] and "ATM 미검출" in w[0] and "CB 미검출" in w[0] and "희석 상태 확인됨" in w[0]
det = [d.value for d in at.dataframe if "항목(기준)" in d.value.columns][0]
assert det.iloc[1]["현재 값"] == "50.00백만 주" and det.iloc[1]["결과"] == "✅ 충족"      # 표시된 값과 저장된 판정은 스캐너가 같은 시점에 만든 것(테스트 데이터는 판정만 임의 지정)
at.selectbox(key="cl_pick").set_value("NOSC").run()
assert any("모두 충족" in x.value for x in at.success) and not [x for x in at.warning if "미충족" in x.value]
assert not at.exception
at.slider(key="cl_ws").set_value(100).run(); assert any("조건에 맞는 종목이 없습니다" in i.value for i in at.info)
print("ALL OK")
