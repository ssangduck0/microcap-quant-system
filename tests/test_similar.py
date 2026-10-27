import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, sqlite3
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, market, similar, cases

nan = np.nan
def ev_row(t, d, drop, vol, close, nh, no=3.0, nc=5.0, f5=8.0, md=-10.0):
    return dict(ticker=t, date=d, close=close, drop_pct=drop, vol_mult=vol, next_open_pct=no, next_high_pct=nh, next_low_pct=-2.0,
                next_close_pct=nc, fwd_5d=f5, max_down_5d=md)
ev = pd.DataFrame([ev_row("A","2024-01-01",-20,5,1.0,15), ev_row("B","2024-02-01",-22,6,1.2,5), ev_row("C","2024-03-01",-35,5,1.0,30),
                   ev_row("D","2024-04-01",-21,20,5.0,12), ev_row("E","2024-05-01",-19,nan,1.0,nan,nan,nan,nan,nan),
                   ev_row("F","2026-10-12",-20,5,1.0,40)])

# select / stats
s = similar.select(ev, -20, 5, 5.0, 2.0, before="2026-10-12"); assert list(s.ticker)==["A","B"]
st = similar.stats(s, 10); assert st["n"]==2 and st["known"]==2 and abs(st["success"]-50)<1e-9 and st["next_open"]==3.0
s2 = similar.select(ev, -20, 5, 5.0, None, before="2026-10-12"); assert sorted(s2.ticker)==["A","B","D","E"]
st2 = similar.stats(s2, 10); assert st2["known"]==3 and abs(st2["success"]-200/3)<1e-9
assert sorted(similar.select(ev, -20, 5, None, None, 1.1, 2.0, before="2026-10-12").ticker)==["A","B","E"]
assert "F" in set(similar.select(ev, -20, 5).ticker)                               # before 가 없으면 포함
assert similar.stats(ev.iloc[0:0], 10)["success"] is None and similar.stats(ev.iloc[0:0], 10)["n"]==0
nr = similar.nearest(s2, -20, 5.0); assert list(nr.ticker)[:2]==["A","B"] and nr.iloc[0]["distance"]==0
assert abs(nr.iloc[1]["distance"]-np.sqrt(0.16+np.log2(6/5)**2))<1e-9 and np.isnan(nr.iloc[-1]["distance"])   # 거래량 없는 사건은 맨 뒤
# 6개 열 외 컬럼 변경에도 안전
print("select/stats/nearest OK")

# annotate
snaps = pd.DataFrame({"date":["2026-10-12"]*5, "day_change_pct":[-20, -3, nan, -20, -20], "volume_mult":[5.0, 5.0, 5.0, None, nan]})
a = similar.annotate(snaps, ev, 10)
assert a.loc[0,"sim_n"]==2 and abs(a.loc[0,"sim_success"]-50)<1e-9            # 거래량 조건 적용, 같은 날 사건(F) 제외
assert np.isnan(a.loc[1,"sim_n"]) and np.isnan(a.loc[2,"sim_n"])               # -10% 보다 덜 빠졌거나 등락률 없음 -> 계산 안 함
assert a.loc[3,"sim_n"]==4 and abs(a.loc[3,"sim_success"]-200/3)<1e-9           # 거래량 정보 없으면 등락률만으로 매칭
assert a.loc[4,"sim_n"]==4
assert similar.annotate(snaps, ev.iloc[0:0], 10)["sim_n"].isna().all()
assert "sim_n" in similar.annotate(snaps.drop(columns=["day_change_pct"]), ev, 10)
print("annotate OK")

# compute_metrics: 전일 종가·오늘 등락률
idx = pd.bdate_range(end=pd.Timestamp("2026-10-09"), periods=42)[-40:]
daily = pd.DataFrame({"Open":10.,"High":10.5,"Low":9.5,"Close":np.linspace(10,8,40),"Volume":1e6}, index=idx)
iidx = pd.date_range("2026-10-12 04:00", periods=60, freq="min", tz="America/New_York")
ic = np.linspace(7.5, 7.2, 60)
intra = pd.DataFrame({"Open":ic,"High":ic,"Low":ic,"Close":ic,"Volume":1e4}, index=iidx)
m = market.compute_metrics(daily, intra)
assert abs(m["prev_close"]-8.0)<1e-9 and abs(m["day_change_pct"]-(7.2/8.0-1)*100)<1e-9
# 일봉에 오늘 봉(부분)이 섞여 있어도 전일 종가는 직전 거래일 종가
daily2 = pd.concat([daily, pd.DataFrame({"Open":7.4,"High":7.6,"Low":7.1,"Close":7.2,"Volume":3e5}, index=[pd.Timestamp("2026-10-12")])])
m2 = market.compute_metrics(daily2, intra); assert abs(m2["prev_close"]-8.0)<1e-9
assert market.compute_metrics(daily.iloc[0:0], None) is None
# 정규장 봉으로 시가 갭/변동폭/종가 위치/직전 변동폭 계산 (프리마켓 봉은 제외)
pre_idx = pd.date_range("2026-10-12 04:00", periods=330, freq="min", tz="America/New_York")      # 04:00~09:29 프리마켓 + 09:30~ 정규장
oc = np.r_[np.full(330 - 60 + 0, 9.0)[:0], np.linspace(9.0, 9.0, 270), np.linspace(7.6, 7.2, 60)]
reg_open = pd.date_range("2026-10-12 09:30", periods=60, freq="min", tz="America/New_York")
full = pd.date_range("2026-10-12 04:00", periods=330 + 60, freq="min", tz="America/New_York")
full = full[(full < "2026-10-12 09:30") | (full >= "2026-10-12 09:30")][:390 + 0]
cl = np.r_[np.full(330, 9.9), np.linspace(7.6, 7.2, 60)]            # 프리마켓은 9.9(갭 계산에 섞이면 안 됨), 정규장은 7.6 -> 7.2
ix = pd.date_range("2026-10-12 04:00", periods=390, freq="min", tz="America/New_York")
reg_n = int(((ix.hour * 60 + ix.minute) >= 570).sum())
df_i = pd.DataFrame({"Open": cl, "High": cl * 1.01, "Low": cl * 0.99, "Close": cl, "Volume": 1e4}, index=ix)
m3 = market.compute_metrics(daily, df_i)
rg = df_i[(ix.hour * 60 + ix.minute) >= 570]
assert abs(m3["gap_pct"] - (rg["Open"].iloc[0] / 8.0 - 1) * 100) < 1e-9            # 정규장 첫 봉 시가 vs 전일 종가 (프리마켓 9.9 아님)
assert abs(m3["range_pct"] - (rg["High"].max() / rg["Low"].min() - 1) * 100) < 1e-9
loc = (7.2 - rg["Low"].min()) / (rg["High"].max() - rg["Low"].min()); assert abs(m3["close_loc"] - loc) < 1e-9 and 0 <= m3["close_loc"] <= 0.2
exp_prng = float((((daily["High"] - daily["Low"]) / daily["Close"]) * 100).tail(20).mean()); assert abs(m3["prior_range_pct"] - exp_prng) < 1e-9
assert market.compute_metrics(daily, intra)["gap_pct"] is None                    # 정규장 봉이 3개 미만이면(프리마켓만) 계산하지 않음
assert market.compute_metrics(daily, None)["close_loc"] is None
print("metrics OK")

# 시장 급락 종목 비율
import scanner
bars = [("2026-10-12", -12.0)] * 60 + [("2026-10-12", -3.0)] * 540 + [("2026-10-09", -50.0)] * 20 + [("2026-10-12", None)] * 10
assert abs(scanner.market_down_frac(bars) - 60/610) < 1e-12                       # 가장 많은 종목이 공유한 날짜 기준, 변동 없는 종목은 분모에 포함
assert scanner.market_down_frac(bars[:100]) is None and scanner.market_down_frac([]) is None
print("market frac OK")

# DB 마이그레이션: 컬럼이 없는 예전 DB
old = os.path.join(tmp, "old.db"); c = sqlite3.connect(old)
c.execute("CREATE TABLE daily_snapshots (date TEXT NOT NULL, ticker TEXT NOT NULL, exchange TEXT, first_seen TEXT, last_seen TEXT, price REAL, high_20d REAL, low_20d REAL, drawdown_pct REAL, volume_mult REAL, buy_pressure REAL, float_shares REAL, atr14 REAL, entry_ref REAL, stop_ref REAL, target_ref REAL, quant_score REAL, quant_detail TEXT, pump_score REAL, pump_detail TEXT, dilution_status TEXT, excluded INTEGER DEFAULT 0, PRIMARY KEY (date, ticker))")
c.execute("INSERT INTO daily_snapshots (date,ticker,price) VALUES ('2026-10-01','OLD',1.5)"); c.commit(); c.close()
config.DB_PATH = __import__("pathlib").Path(old); db.init_db(); db.init_db()      # 두 번 실행해도 안전
with closing(db.connect()) as conn:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_snapshots)")}
    assert "day_change_pct" in cols and conn.execute("SELECT price FROM daily_snapshots WHERE ticker='OLD'").fetchone()[0]==1.5
    db.upsert_snapshot(conn, {"date":"2026-10-12","ticker":"NEW","price":1.0,"day_change_pct":-12.5,"excluded":0})
    assert conn.execute("SELECT day_change_pct FROM daily_snapshots WHERE ticker='NEW'").fetchone()[0]==-12.5
print("migration OK")

# 대시보드 화면 확인용 DB 준비
config.DB_PATH = __import__("pathlib").Path(os.environ["QUANT_DB"]); db.init_db()
with closing(db.connect()) as conn:
    cases.save_events(conn, [{**{k: None for k in cases.EVENT_COLS}, "ticker": r.ticker, "date": r.date, "close": r.close, "drop_pct": r.drop_pct, "vol_mult": r.vol_mult,
                              "next_open_pct": r.next_open_pct, "next_high_pct": r.next_high_pct, "next_low_pct": r.next_low_pct,
                              "next_close_pct": r.next_close_pct, "fwd_5d": r.fwd_5d, "max_down_5d": r.max_down_5d} for r in ev.itertuples()])
    for t, chg, vm in (("AAA", -20.0, 5.0), ("BBB", -3.0, 2.0), ("CCC", None, None)):
        db.upsert_snapshot(conn, {"date":"2026-10-12","ticker":t,"exchange":"NASDAQ","first_seen":db.utcnow_iso(),"last_seen":db.utcnow_iso(),
            "price":1.1,"high_20d":2.0,"low_20d":1.0,"drawdown_pct":-45.0,"day_change_pct":chg,"volume_mult":vm,"buy_pressure":55.0,"float_shares":8e6,
            "atr14":0.1,"entry_ref":1.0,"stop_ref":0.9,"target_ref":1.3,"quant_score":50.0,"quant_detail":"{}","pump_score":40.0,"pump_detail":'{"checks":[]}',
            "dilution_status":"CLEAN","excluded":0})
print("ALL OK"); print(os.environ["QUANT_DB"])
