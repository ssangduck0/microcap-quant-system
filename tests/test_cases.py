import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, market, cases, analytics
db.init_db()
approx = lambda a, b, tol=1e-6: a is not None and abs(a-b) < tol
ORIG_DROP = cases.drop_incomplete_last_bar
cases.drop_incomplete_last_bar = lambda df, now=None: df

# ---------- 1) find_events 수치 검증 ----------
def base_df(n_total=40, idx=None):
    idx = idx if idx is not None else pd.bdate_range(end="2026-10-09", periods=n_total)
    O=[10.]*30; H=[10.2]*30; L=[9.8]*30; C=[10.]*30; V=[1e6]*30
    O+= [9.0, 9.35, 9.5, 9.0, 9.2, 9.4, 9.5, 9.7, 9.8, 9.9]
    H+= [9.1, 9.8, 9.6, 9.3, 9.5, 9.9, 9.6*1.01, 9.7*1.01, 9.8*1.01, 9.9*1.01]
    L+= [8.2, 9.0, 8.9, 8.8, 9.1, 9.3, 9.6*.99, 9.7*.99, 9.8*.99, 9.9*.99]
    C+= [8.5, 9.5, 9.0, 9.2, 9.4, 9.6, 9.6, 9.7, 9.8, 9.9]
    V+= [5e6]+[1.5e6]*9
    return pd.DataFrame({"Open":O,"High":H,"Low":L,"Close":C,"Volume":V}, index=idx)
df = base_df()
ev = cases.find_events("AAA", df)
assert len(ev)==1, ev
e = ev[0]
exp = {"drop_pct":-15.0, "gap_pct":-10.0, "intraday_rebound_pct":(8.5/8.2-1)*100, "vol_mult":5.0, "avg_dollar_vol":1e7,
       "pre_dd_pct":(10/10.2-1)*100, "next_open_pct":(9.35/8.5-1)*100, "next_high_pct":(9.8/8.5-1)*100,
       "next_low_pct":(9.0/8.5-1)*100, "next_close_pct":(9.5/8.5-1)*100, "fwd_3d":(9.2/8.5-1)*100, "fwd_5d":(9.6/8.5-1)*100,
       "max_up_5d":(9.9/8.5-1)*100, "max_down_5d":(8.8/8.5-1)*100, "max_up_3d":(9.8/8.5-1)*100, "max_down_3d":(8.8/8.5-1)*100}   # 3일 안 최고·최저(2026-10-29)
for k, v in exp.items(): assert approx(e[k], v, 1e-6), (k, e[k], v)
assert e["fwd_10d"] is None and e["bars_after"]==9 and e["date"]==df.index[30].strftime("%Y-%m-%d") and e["last_bar_date"]=="2026-10-09"
# 경계/예외
d2 = base_df(); d2.iloc[30, d2.columns.get_loc("Close")] = 9.05   # -9.5% -> 사건 아님
assert cases.find_events("X", d2)==[]
d3 = base_df(); d3.iloc[30, d3.columns.get_loc("Close")] = 0.0001; d3.iloc[30, d3.columns.get_loc("Low")] = 0.0001   # 데이터 오류성 -99.99%
assert cases.find_events("X", d3)==[]
assert cases.find_events("X", df, since="2026-10-01")==[] and len(cases.find_events("X", df, since="2020-01-01"))==1
d4 = base_df(); d4.iloc[5, d4.columns.get_loc("Close")] = 8.0     # 앞쪽(문맥 부족) 사건
e4 = [x for x in cases.find_events("X", d4) if x["date"]==d4.index[5].strftime("%Y-%m-%d")][0]
assert e4["vol_mult"] is None and e4["avg_dollar_vol"] is None and e4["next_open_pct"] is not None
assert cases.find_events("X", df.head(8))==[]
# 시간대/중복 인덱스 입력도 안전
d5 = base_df(); d5.index = d5.index.tz_localize("America/New_York"); assert len(cases.find_events("X", d5))==1
assert approx(e["range_pct"], (9.1/8.2-1)*100) and approx(e["close_loc"], (8.5-8.2)/(9.1-8.2)) and approx(e["prior_range_pct"], 4.0)   # 변동폭, 종가 위치, 직전 20일 평균 변동폭
assert e4["prior_range_pct"] is None            # 문맥 부족 사건
dflat = base_df(); dflat.iloc[30, dflat.columns.get_loc("High")] = 8.5; dflat.iloc[30, dflat.columns.get_loc("Low")] = 8.5
assert cases.find_events("X", dflat)[0]["close_loc"] is None        # 고가=저가면 종가 위치 정의 불가
print("find_events OK")

# ---------- 2) build: 진행/이어하기/오류/상장폐지 ----------
calls = []
mode = {"fail_second": True}
def fake_dl(tk, period="3mo", chunk=40):
    calls.append(list(tk))
    if mode["fail_second"] and "DDD" in tk: return {}            # 묶음 전체 실패(일시 오류)
    out = {}
    for t in tk:
        if t=="AAA": out[t]=base_df()
        elif t=="BBB": out[t]=base_df().assign(Close=10.0, Open=10.0, High=10.1, Low=9.9)   # 사건 없음
        elif t=="CCC": continue                                  # 데이터 없음(상폐)
        else: out[t]=base_df()
    return out
market.download_daily = fake_dl
lines = []
with closing(db.connect()) as conn:
    st1 = cases.build(conn, ["AAA","BBB","CCC"], ["DDD","EEE","FFF"], years=10, chunk=3, pause=0, out=lines.append)
    prog = {r["ticker"]: (r["status"], r["is_delisted"]) for r in conn.execute("SELECT * FROM case_progress")}
    print(prog); print("\n".join(lines))
    assert prog["AAA"]==("done",0) and prog["BBB"]==("done",0) and prog["CCC"]==("no_data",0)
    assert prog["DDD"]==("error",1) and prog["EEE"]==("error",1) and prog["FFF"]==("error",1)
    assert st1["ok"]==2 and st1["no_data"]==1 and st1["error"]==3 and st1["events"]==1
    assert any("[6/6]" in l and "오류 3" in l and "남은 시간" in l for l in lines)
    # 재실행: 완료/데이터없음은 건너뛰고 오류만 재시도
    calls.clear(); mode["fail_second"]=False; lines.clear()
    st2 = cases.build(conn, ["AAA","BBB","CCC"], ["DDD","EEE","FFF"], chunk=3, pause=0, out=lines.append)
    assert calls==[["DDD","EEE","FFF"]], calls
    assert st2["ok"]==3 and st2["error"]==0 and conn.execute("SELECT COUNT(*) FROM case_events").fetchone()[0]==4
    assert conn.execute("SELECT is_delisted FROM case_progress WHERE ticker='EEE'").fetchone()[0]==1
    # rebuild 는 전부 다시 + 중복 저장 없음(PK)
    calls.clear(); cases.build(conn, ["AAA","BBB","CCC"], ["DDD","EEE","FFF"], chunk=3, pause=0, rebuild=True, out=lines.append)
    assert len(calls)==2 and conn.execute("SELECT COUNT(*) FROM case_events").fetchone()[0]==4
    # Ctrl+C: 지금까지 커밋하고 이어하기 가능
    conn.execute("DELETE FROM case_progress"); conn.execute("DELETE FROM case_events"); conn.commit()
    n={"c":0}
    def kb(tk, period="3mo", chunk=40):
        n["c"]+=1
        if n["c"]==2: raise KeyboardInterrupt
        return fake_dl(tk, period, chunk)
    market.download_daily = kb; lines.clear()
    cases.build(conn, ["AAA","BBB","CCC"], ["DDD","EEE","FFF"], chunk=3, pause=0, out=lines.append)
    assert any("이어서 진행" in l for l in lines)
    assert conn.execute("SELECT COUNT(*) FROM case_progress").fetchone()[0]==3          # 첫 묶음은 저장됨
    market.download_daily = fake_dl; calls.clear()
    cases.build(conn, ["AAA","BBB","CCC"], ["DDD","EEE","FFF"], chunk=3, pause=0, out=lines.append)
    assert calls==[["DDD","EEE","FFF"]]
print("build OK")

# ---------- 3) update: 최근 사건 추가 + 이전 사건 결과 보완 + 신규 종목 ----------
full_idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=50)[-48:]
a_old = base_df(idx=full_idx[:40]); a_new = base_df(idx=full_idx[:40])
extra = pd.DataFrame({"Open":[9.9]*8,"High":[10.0]*8,"Low":[9.8]*8,"Close":[9.9]*8,"Volume":[1e6]*8}, index=full_idx[40:])
extra.iloc[6, extra.columns.get_loc("Close")] = 8.6; extra.iloc[6, extra.columns.get_loc("Low")] = 8.5   # 새 사건(-13.1%)
a_ext = pd.concat([a_new, extra])
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM case_progress"); conn.execute("DELETE FROM case_events"); conn.commit()
    market.download_daily = lambda tk, period="3mo", chunk=40: {t: a_old for t in tk}
    cases.build(conn, ["AAA"], [], chunk=3, pause=0, out=lambda *_: None)
    before = conn.execute("SELECT fwd_10d, bars_after FROM case_events WHERE ticker='AAA'").fetchone()
    assert before[0] is None and before[1]==9
    market.download_daily = lambda tk, period="3mo", chunk=40: {t: (a_ext if t=="AAA" else base_df(idx=full_idx[:40])) for t in tk}
    res = cases.update(conn, ["AAA","NEWW"], [], days=90, chunk=10, pause=0, out=lambda *_: None)
    rows = conn.execute("SELECT date, fwd_10d, bars_after FROM case_events WHERE ticker='AAA' ORDER BY date").fetchall()
    print([tuple(r) for r in rows], res)
    assert len(rows)==2 and rows[0]["fwd_10d"] is not None and rows[0]["bars_after"]==17      # 이전 사건 결과 보완
    assert rows[1]["bars_after"]==1 and abs(conn.execute("SELECT drop_pct FROM case_events WHERE ticker='AAA' ORDER BY date DESC").fetchone()[0] - (8.6/9.9-1)*100) < 1e-6
    assert res["new_tickers"]==1 and conn.execute("SELECT status FROM case_progress WHERE ticker='NEWW'").fetchone()[0]=="done"
    lines=[]; cases.status(conn, out=lines.append); print(lines); assert "사건" in lines[1]
print("update OK")

# ---------- 4) 요약 통계 ----------
with closing(db.connect()) as conn:
    cs = pd.read_sql_query("SELECT * FROM case_events", conn)
s = analytics.case_summary(cs, 10); assert s.iloc[0]["사건 수"]==len(cs)
sb = analytics.case_summary(cs, 10, "drop_pct", [-101,-50,-30,-20,-10.0001], ["≤-50%","-50~-30%","-30~-20%","-20~-10%"]); assert len(sb)>=1
col = [c for c in s.columns if c.startswith("성공률")][0]
known = cs["next_high_pct"].dropna(); assert approx(s.iloc[0][col], (known>=10).mean()*100)
print("summary OK")

# ---------- 5) 장 마감 전 임시 일봉 처리 ----------
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
idxd = pd.bdate_range(end="2026-10-12", periods=42)[-40:]           # 마지막 봉 = 2026-10-12(월)
dd = base_df(idx=idxd)
mid  = datetime(2026,10,12,13,0,tzinfo=ET)                   # 미국 장중(한국시간 새벽 2시)
done = datetime(2026,10,12,16,30,tzinfo=ET)                  # 마감 후
nextday = datetime(2026,10,13,9,0,tzinfo=ET)
assert len(ORIG_DROP(dd, mid))==39 and ORIG_DROP(dd, mid).index[-1]==idxd[-2]
assert len(ORIG_DROP(dd, done))==40 and len(ORIG_DROP(dd, nextday))==40
assert len(ORIG_DROP(dd, datetime(2026,10,12,4,0,tzinfo=ET)))==39     # 프리마켓에도 오늘 봉은 미확정
assert ORIG_DROP(None, mid) is None and ORIG_DROP(dd.iloc[0:0], mid).empty
dtz = dd.copy(); dtz.index = dtz.index.tz_localize("America/New_York"); assert len(ORIG_DROP(dtz, mid))==39
# 임시 봉이 '다음날 결과'로 쓰이지 않는지: 사건=bar 38(2026-10-09 금), 다음날=마지막 봉(10-12)
d6 = base_df(idx=idxd); 
for col, v in (("Close",8.5),("Low",8.2)): d6.iloc[38, d6.columns.get_loc(col)] = v
d6.iloc[39, d6.columns.get_loc("Close")] = 9.0
e_full = [x for x in cases.find_events("X", d6) if x["date"]=="2026-10-09"][0]
assert e_full["next_close_pct"] is not None
e_cut = [x for x in cases.find_events("X", ORIG_DROP(d6, mid)) if x["date"]=="2026-10-09"][0]
assert e_cut["next_close_pct"] is None and e_cut["bars_after"]==0
# 장중에 build 하면 임시 일봉 사건이 저장되지 않고, 마감 후 update 가 확정값으로 채움(+더 이상 사건이 아닌 행은 삭제)
d7 = base_df(idx=idxd); d7.iloc[39, d7.columns.get_loc("Close")] = 8.0; d7.iloc[39, d7.columns.get_loc("Low")] = 7.9   # 임시 -19% (10-12)
market.download_daily = lambda tk, period="3mo", chunk=40: {t: d7 for t in tk}
cases.drop_incomplete_last_bar = lambda df, now=None: ORIG_DROP(df, mid)
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM case_progress"); conn.execute("DELETE FROM case_events"); conn.commit()
    cases.build(conn, ["TMP"], [], chunk=3, pause=0, out=lambda *_: None)
    got = [r[0] for r in conn.execute("SELECT date FROM case_events WHERE ticker='TMP'")]
    assert "2026-10-12" not in got and "2026-09-04" in [x for x in got] or "2026-10-12" not in got     # 임시 사건 없음
    # (가짜) 이전 버전이 저장해 둔 임시 사건 행이 남아 있는 상황
    conn.execute("INSERT OR REPLACE INTO case_events (ticker,date,drop_pct,close) VALUES ('TMP','2026-10-12',-19.0,8.0)"); conn.commit()
    # 마감 후 확정값: 10-12 종가가 회복되어 더 이상 사건이 아님
    d8 = d7.copy(); d8.iloc[39, d8.columns.get_loc("Close")] = 9.9; d8.iloc[39, d8.columns.get_loc("Low")] = 9.0
    market.download_daily = lambda tk, period="3mo", chunk=40: {t: d8 for t in tk}
    cases.drop_incomplete_last_bar = lambda df, now=None: ORIG_DROP(df, done)
    cases.update(conn, [], [], days=3650, chunk=10, pause=0, out=lambda *_: None)
    got = [r[0] for r in conn.execute("SELECT date FROM case_events WHERE ticker='TMP'")]
    assert "2026-10-12" not in got, got            # 낡은 임시 사건 행이 삭제됨
    # 데이터가 부족한 응답은 기존 기록을 지우지 않음
    market.download_daily = lambda tk, period="3mo", chunk=40: {t: d8.head(20) for t in tk}
    before = conn.execute("SELECT COUNT(*) FROM case_events WHERE ticker='TMP'").fetchone()[0]
    cases.update(conn, [], [], days=3650, chunk=10, pause=0, out=lambda *_: None)
    assert conn.execute("SELECT COUNT(*) FROM case_events WHERE ticker='TMP'").fetchone()[0]==before
cases.drop_incomplete_last_bar = lambda df, now=None: df
print("incomplete bar OK")
print("ALL OK"); print(os.environ["QUANT_DB"])
