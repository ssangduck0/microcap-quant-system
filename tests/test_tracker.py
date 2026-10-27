import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, market, cases, tracker
db.init_db()
ET = ZoneInfo("America/New_York")
approx = lambda a, b, tol=1e-9: a is not None and abs(a-b) < tol

def base_df(idx):
    O=[10.]*30+[9.0, 9.35, 9.5, 9.0, 9.2, 9.4, 9.5, 9.7, 9.8, 9.9]
    H=[10.2]*30+[9.1, 9.8, 9.6, 9.3, 9.5, 9.9, 9.6*1.01, 9.7*1.01, 9.8*1.01, 9.9*1.01]
    L=[9.8]*30+[8.2, 9.0, 8.9, 8.8, 9.1, 9.3, 9.6*.99, 9.7*.99, 9.8*.99, 9.9*.99]
    C=[10.]*30+[8.5, 9.5, 9.0, 9.2, 9.4, 9.6, 9.6, 9.7, 9.8, 9.9]
    return pd.DataFrame({"Open":O,"High":H,"Low":L,"Close":C,"Volume":1e6}, index=idx)

# ---------- outcome_for 수치 검증 ----------
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=42)[-40:]
df = base_df(idx); d30 = idx[30].strftime("%Y-%m-%d")
r = tracker.outcome_for(df, d30)
exp = {"entry_close":8.5, "next_open_pct":(9.35/8.5-1)*100, "next_high_pct":(9.8/8.5-1)*100, "next_low_pct":(9.0/8.5-1)*100,
       "next_close_pct":(9.5/8.5-1)*100, "fwd_3d":(9.2/8.5-1)*100, "fwd_5d":(9.6/8.5-1)*100, "max_up_5d":(9.9/8.5-1)*100, "max_down_5d":(8.8/8.5-1)*100}
for k, v in exp.items(): assert approx(r[k], v, 1e-9), (k, r[k], v)
assert r["fwd_10d"] is None and r["bars_after"]==9 and r["complete"]==0 and r["status"]=="ok"
# 같은 정의의 과거 사건 계산(cases.find_events)과 일치해야 함
ev = cases.find_events("X", df)[0]
for k_ev, k_tr in (("next_open_pct","next_open_pct"),("next_high_pct","next_high_pct"),("next_close_pct","next_close_pct"),("fwd_5d","fwd_5d"),("max_up_5d","max_up_5d")):
    assert approx(ev[k_ev], r[k_tr], 1e-9), (k_ev, ev[k_ev], r[k_tr])
# 아직 며칠 안 지난 경우: 지금까지 구간으로 계산, 5일 창 미완성
r2 = tracker.outcome_for(df.head(33), d30)
assert r2["bars_after"]==2 and r2["fwd_3d"] is None and approx(r2["max_up_5d"], (9.8/8.5-1)*100) and r2["next_open_pct"] is not None and r2["complete"]==0
r3 = tracker.outcome_for(df.head(31), d30)                                  # 진입일이 마지막 봉
assert r3["bars_after"]==0 and r3["next_open_pct"] is None and r3["max_up_5d"] is None and r3["entry_close"]==8.5
assert tracker.outcome_for(df, "2000-01-03") is None                          # 그 날짜 봉이 없음
dfx = pd.concat([df, pd.DataFrame({"Open":9.9,"High":10.0,"Low":9.8,"Close":9.9,"Volume":1e6}, index=pd.bdate_range(start=idx[-1]+pd.Timedelta(days=1), periods=3))])
assert tracker.outcome_for(dfx, d30)["complete"]==1 and tracker.outcome_for(dfx, d30)["fwd_10d"] is not None
dz = df.copy(); dz.iloc[30, dz.columns.get_loc("Close")] = 0.0
assert tracker.outcome_for(dz, d30) is None                                    # 종가가 0 이하면 진입가 불가
print("outcome_for OK")

# ---------- update: 스냅샷 -> 결과 채우기 ----------
now_ = db.utcnow_iso()
def snap(t, d, **kw):
    r = {"date":d,"ticker":t,"exchange":"NASDAQ","first_seen":now_,"last_seen":now_,"price":8.5,"high_20d":10.2,"low_20d":8.2,"drawdown_pct":-17.0,"day_change_pct":-15.0,
         "volume_mult":3.0,"buy_pressure":55.0,"float_shares":8e6,"atr14":0.3,"quant_score":50.0,"quant_detail":"{}","pump_score":40.0,"pump_detail":'{"checks":[]}',
         "dilution_status":"CLEAN","excluded":0}
    r.update(kw); return r
old_date = (date.today() - timedelta(days=30)).isoformat()
with closing(db.connect()) as conn:
    for t, d in (("AAA", d30), ("BBB", d30), ("GONE", old_date), ("NEW", idx[-1].strftime("%Y-%m-%d"))):
        db.upsert_snapshot(conn, snap(t, d))
dl_calls = []
def dl(tk, period="3mo", chunk=40):
    dl_calls.append(list(tk)); return {t: df for t in tk if t in ("AAA","BBB","NEW")}      # GONE 은 데이터 없음
market.download_daily = dl
after_close = datetime.combine(idx[-1].date(), time(17, 0), tzinfo=ET)
before_close = datetime.combine(idx[-1].date(), time(11, 0), tzinfo=ET)
lines = []
with closing(db.connect()) as conn:
    res = tracker.update(conn, out=lines.append, now=before_close)         # 장 마감 전: 오늘 봉은 제외
    rows = {(r["ticker"]): dict(r) for r in conn.execute("SELECT * FROM tracked_outcomes")}
    print("before close:", sorted(rows), res)
    assert set(rows) == {"AAA","BBB","GONE"} and "NEW" not in rows                      # NEW(오늘 발견)는 아직 대기
    assert rows["AAA"]["complete"]==0 and approx(rows["AAA"]["next_high_pct"], (9.8/8.5-1)*100)
    assert rows["GONE"]["status"]=="no_data" and rows["GONE"]["complete"]==1            # 오래됐는데 가격 없음 -> 재시도 중단
    assert any("대기" in l for l in lines)
    # 장 마감 후: 오늘 봉이 확정되어 NEW 도 채워짐(다음날 결과는 아직 없음)
    dl_calls.clear(); res = tracker.update(conn, out=lines.append, now=after_close)
    assert "GONE" not in dl_calls[0]                                                      # 완료/중단된 기록은 다시 받지 않음
    new = conn.execute("SELECT * FROM tracked_outcomes WHERE ticker='NEW'").fetchone()
    assert new is not None and new["entry_close"] == 9.9 and new["next_high_pct"] is None
    # 며칠 뒤: 더 많은 봉이 생기면 AAA 가 완료로 바뀜
    market.download_daily = lambda tk, period="3mo", chunk=40: {t: dfx for t in tk if t in ("AAA","BBB","NEW")}
    tracker.update(conn, out=lines.append, now=after_close)
    a = conn.execute("SELECT * FROM tracked_outcomes WHERE ticker='AAA'").fetchone()
    assert a["complete"]==1 and a["fwd_10d"] is not None
    dl_calls.clear(); market.download_daily = lambda tk, period="3mo", chunk=40: (dl_calls.append(list(tk)) or {})
    tracker.update(conn, out=lines.append, now=after_close)
    assert "AAA" not in (dl_calls[0] if dl_calls else [])                                 # 완료된 건 재조회 없음
    # 새 기록이 없으면 안내만
    conn.execute("DELETE FROM daily_snapshots"); conn.commit(); lines.clear()
    assert tracker.update(conn, out=lines.append)["rows"]==0 and "없습니다" in lines[0]
    lines.clear(); tracker.status(conn, out=lines.append); print(lines)
# cases.update 마지막에 자동 실행되는지
called = []
tracker_update_orig = tracker.update
tracker.update = lambda conn, out=print, **kw: called.append(1) or {}
with closing(db.connect()) as conn:
    market.download_daily = lambda tk, period="3mo", chunk=40: {}
    cases.update(conn, [], [], days=60, chunk=10, pause=0, out=lambda *_: None)
assert called == [1]
tracker.update = tracker_update_orig
print("update OK")
print("ALL OK")
