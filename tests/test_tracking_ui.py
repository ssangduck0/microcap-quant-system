import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db
db.init_db()
D = "2026-10-08"
et = lambda s: pd.Timestamp(s, tz="America/New_York").tz_convert("UTC").isoformat()
def snap(t, d, last_seen, **kw):
    r = {"date":d,"ticker":t,"exchange":"NASDAQ","first_seen":et(d+" 09:35"),"last_seen":last_seen,"price":1.0,"high_20d":2.0,"low_20d":0.9,"drawdown_pct":-40.0,
         "day_change_pct":-15.0,"volume_mult":3.0,"buy_pressure":55.0,"float_shares":8e6,"atr14":0.1,"entry_ref":0.9,"stop_ref":0.8,"target_ref":1.2,
         "quant_score":50.0,"quant_detail":"{}","pump_score":40.0,"pump_detail":'{"checks":[]}',"dilution_status":"CLEAN","excluded":0}
    r.update(kw); return r
# 마감 무렵(15:45 ET)까지 유지된 종목 10개: 다음날 고가가 +10% 이상인 것 4개 -> 성공률 40%
nh = [25, 12, 10, 18, 3, 5, -2, 7, 9.9, 0]
with closing(db.connect()) as conn:
    for i, h in enumerate(nh):
        t = f"HLD{i}"
        db.upsert_snapshot(conn, snap(t, D, et(D+" 15:45"), win_score=40.0 + i*5, dilution_status="ATM" if i == 1 else "CLEAN", excluded=1 if i == 1 else 0))
        conn.execute("INSERT INTO tracked_outcomes (date,ticker,entry_close,next_open_pct,next_high_pct,next_low_pct,next_close_pct,fwd_5d,max_up_5d,max_down_5d,bars_after,complete,status,updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (D, t, 1.0, 1.0, h, -5.0, h - 6, 2.0, h + 3, -8.0, 6, 0, "ok", db.utcnow_iso()))
    for i in range(5):    # 장 초반(11:00 ET)에만 잡혔다 사라진 종목 5개 -> 기본 필터에서 제외
        t = f"EARLY{i}"
        db.upsert_snapshot(conn, snap(t, D, et(D+" 11:00")))
        conn.execute("INSERT INTO tracked_outcomes (date,ticker,entry_close,next_high_pct,next_close_pct,bars_after,complete,status,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (D, t, 1.0, 30.0, 20.0, 6, 0, "ok", db.utcnow_iso()))
    db.upsert_snapshot(conn, snap("TODAY1", "2026-10-12", et("2026-10-12 15:50")))     # 결과 아직 없음
    conn.commit()

from streamlit.testing.v1 import AppTest
def track_sr(at):  # 📒 발견 종목 추적 화면의 '성공률'(다른 화면에도 같은 이름이 있어서 '발견 종목-일' 지표부터 찾음)
    ms = list(at.metric); i = [m.label for m in ms].index("발견 종목-일")
    return [m for m in ms[i:i + 8] if m.label == "성공률"][0]
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=90).run()
print("exc:", [e.value for e in at.exception])
_ms = list(at.metric); _i = [m.label for m in _ms].index("발견 종목-일")                 # 📒 발견 종목 추적 화면의 지표부터
mm = {m.label: m.value for m in _ms[_i:_i + 8]}; print({k: v for k, v in mm.items() if k.startswith(("발견","결과 확","성공"))})
assert mm["발견 종목-일"] == "11" and mm["결과 확인"] == "10"           # 마감까지 유지 10 + 결과 대기 1(TODAY1)
assert mm["성공 (≥ +10%)"] == "4"
sr = [m for m in _ms[_i:_i + 8] if m.label == "성공률"][0]; print("성공률:", sr.value, sr.delta)
assert sr.value == "40.0%"                                                 # 발견 10개 중 4개가 +10% -> 40%
assert "vs 조건 없이 전체" in sr.delta
# 마감 무렵 필터 해제 -> 초반에만 잡힌 5개(모두 성공)가 포함되어 성공률 상승
at.checkbox(key="trk_held").set_value(False).run()
_ms = list(at.metric); _i = [m.label for m in _ms].index("발견 종목-일"); sr = [m for m in _ms[_i:_i + 8] if m.label == "성공률"][0]; print("held off:", sr.value)
assert sr.value == f"{9/15*100:.1f}%"
# 성공 기준 변경(+20%): 고가 기준 25 하나 + 초반 5개
at.checkbox(key="trk_held").set_value(True).run()
at.slider(key="trk_target").set_value(20).run()
assert track_sr(at).value == "10.0%"
at.slider(key="trk_target").set_value(10).run()
# ATM 제외 -> ATM 1개(HLD1, 성공) 제외: 9개 중 3개
at.checkbox(key="trk_atm").set_value(True).run()
assert track_sr(at).value == f"{3/9*100:.1f}%"
at.checkbox(key="trk_atm").set_value(False).run()
# 하루 상위 3개(승률 점수 높은 순: HLD9, HLD8, HLD7 -> 고가 0, 9.9, 7 -> 성공 0)
at.number_input(key="trk_topn").set_value(3).run()
assert track_sr(at).value == "0.0%", track_sr(at).value
at.number_input(key="trk_topn").set_value(0).run()
# 승률 점수 ≥ 70 (HLD6..9) -> 성공 0/4
at.slider(key="trk_ws").set_value(70).run()
assert track_sr(at).value == "0.0%"
at.slider(key="trk_ws").set_value(0).run()
# 다른 기준: 다음날 종가 +5% / 5일 내 최고가
for b in ("다음날 종가", "5일 내 최고가"):
    at.selectbox(key="trk_basis").set_value(b).run(); assert not at.exception, [e.value for e in at.exception]
    print(b, track_sr(at).value)
# 5일 내 최고가: 도달(≥10)이면 확정 성공, 미도달은 bars_after(6) >= 5 라 확정 실패 -> max_up = h+3: 25+3,12+3,10+3,18+3,.. 7+3=10 도 성공
assert track_sr(at).value == f"{sum(1 for h in nh if h + 3 >= 10)/10*100:.1f}%"
print("tables:", [d.value.shape for d in at.dataframe][-3:], "| download:", len(at.get("download_button")))
print("ALL OK")
