import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🛰 1단계 빠른 모드(stage1fast): 동부 20시 기준 · 시세→오늘 봉 · 병합 의심 · 모드별 흐름(full/shadow/fast/되돌림) · 대상 다시 받기 · 비교·매일 점검 멈춤."""
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timezone, timedelta
tmp = tempfile.mkdtemp()
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, market, stage1fast as sf, scanner
db.init_db()
U = timezone.utc

# ---- 동부 20시 기준(마감값이 굳은 시각) ----
tue10 = datetime(2026, 11, 3, 15, 0, tzinfo=U)                     # 화 10:00 ET(EST)
assert sf.last_settle(tue10).isoformat().startswith("2026-11-02T20:00")         # 월 20시
assert sf.last_settle(datetime(2026, 11, 2, 3, 0, tzinfo=U)).isoformat().startswith("2026-10-30T20:00")   # 일요일 밤 → 금 20시
assert sf.last_settle(datetime(2026, 11, 4, 2, 0, tzinfo=U)).isoformat().startswith("2026-11-03T20:00")   # 화 21시 ET
c = sf.Cache()
assert c.due(tue10)                                                 # 비어 있으면 받기
c.frames, c.fetched_at = {"X": pd.DataFrame()}, datetime(2026, 11, 3, 2, 0, tzinfo=U)   # 월 21시 ET 에 받음
assert not c.due(tue10) and c.due(datetime(2026, 11, 4, 1, 30, tzinfo=U))         # 화 장중은 그대로 · 화 20:30 ET 엔 다시
assert str(c.settled_day()) == "2026-11-02"
print("settle OK")

# ---- 가짜 자료: 월(11/2)까지 지난 일봉 40개 + 화(11/3) 오늘 봉 ----
idx = pd.bdate_range(end="2026-11-02", periods=40)
TUE = pd.Timestamp("2026-11-03")
TS_TUE = int(datetime(2026, 11, 3, 18, 0, tzinfo=U).timestamp())
TS_MON = int(datetime(2026, 11, 2, 21, 0, tzinfo=U).timestamp())
NAMES = [f"T{i:02d}" for i in range(30)]
PREV, BAR, FULL = {}, {}, {}
rng = np.random.default_rng(1)
for i, t in enumerate(NAMES):
    cl = np.linspace(3.0, 1.0 + i * 0.02, 40)
    PREV[t] = pd.DataFrame({"Open": cl, "High": cl * 1.04, "Low": cl * 0.96, "Close": cl, "Adj Close": cl, "Volume": np.full(40, 1e6)}, index=idx)
    px = float(cl[-1]) * (0.97 + i * 0.002)
    BAR[t] = {"Open": float(cl[-1]), "High": px * 1.03, "Low": px * 0.95, "Close": px, "Volume": 1e6 * (2 + i * 0.5)}
    FULL[t] = pd.concat([PREV[t], pd.DataFrame([{**BAR[t], "Adj Close": px}], index=pd.DatetimeIndex([TUE]))])


def quote(t, ts=TS_TUE, prev=None, **kw):
    b = BAR[t]
    x = {"symbol": t, "regularMarketPrice": b["Close"], "regularMarketVolume": b["Volume"], "regularMarketDayHigh": b["High"],
         "regularMarketDayLow": b["Low"], "regularMarketOpen": b["Open"], "regularMarketTime": ts,
         "regularMarketPreviousClose": float(PREV[t]["Close"].iloc[-1]) if prev is None else prev}
    x.update(kw)
    return x


Q = {t: quote(t) for t in NAMES}

# ---- 시세 → 오늘 봉 ----
day, bar = sf.quote_bar(Q["T05"])
assert day == TUE and bar == {k: BAR["T05"][k] for k in bar}
assert sf.quote_bar({"regularMarketPrice": None}) is None and sf.quote_bar({"regularMarketPrice": 1.0}) is None
d2, b2 = sf.quote_bar({"regularMarketPrice": 2.0, "regularMarketTime": TS_TUE})     # 고가·저가·거래량이 없으면 현재가·0
assert b2 == {"Open": 2.0, "High": 2.0, "Low": 2.0, "Close": 2.0, "Volume": 0.0}
print("quote_bar OK")

# ---- build: 지난 일봉 + 시세 = 지금 방식(야후 일봉)과 같은 1단계 값 ----
cache = sf.Cache()
cache.set(PREV, datetime(2026, 11, 3, 2, 0, tzinfo=U))
out, need, mis, fq = sf.build(NAMES, Q, cache)
assert not need and not mis and fq == set(NAMES) and set(out) == set(NAMES)
for t in NAMES:
    a, b = market.quick_screen(out[t]), market.quick_screen(FULL[t])
    assert a["last_date"] == b["last_date"] == "2026-11-03"
    for k in ("price", "drawdown_pct", "avg_dollar_vol", "vol_mult", "day_chg_pct"):
        assert abs(a[k] - b[k]) < 1e-9, (t, k, a[k], b[k])
# 장 시작 전·주말: 시세가 어제(월) 값 → 마감값으로 굳은 저장 일봉 그대로
o2, n2, _, f2 = sf.build(["T01"], {"T01": quote("T01", ts=TS_MON)}, cache)
assert o2["T01"] is cache.frames["T01"] and not n2 and not f2
# 병합 의심(전일 종가 ×10) · 시세 없음 → 야후 일봉 · 새 종목은 한 번 받아 보고 없으면 dead
q3 = {"T02": quote("T02", prev=float(PREV["T02"]["Close"].iloc[-1]) * 10), "NEW": quote("T03", symbol="NEW")}
o3, n3, m3, _ = sf.build(["T02", "T04", "NEW", "DEAD"], q3, cache)
assert m3 == ["T02"] and n3 == ["T02", "T04", "NEW"] and not o3
cache.dead.add("NEW")
assert sf.build(["NEW"], q3, cache)[1] == []
# 장중 재시작으로 저장 일봉 끝이 오늘(부분) 봉 → 시세 값으로 바꿔 끼움
part = FULL["T06"].copy(); part.iloc[-1, part.columns.get_loc("Close")] *= 0.5          # 오전에 받은 화요일 부분 봉
mid = sf.Cache(); mid.set({"T06": part}, datetime(2026, 11, 3, 16, 0, tzinfo=U))
o4, _, _, f4 = sf.build(["T06"], Q, mid)
assert len(o4["T06"]) == 41 and o4["T06"]["Close"].iloc[-1] == BAR["T06"]["Close"] and f4 == {"T06"}
print("build OK")

# ---- 모드별 흐름 ----
calls = []
def dl(tk):
    calls.append(list(tk))
    return {t: FULL[t] for t in tk if t in FULL}
now = datetime(2026, 11, 3, 16, 0, tzinfo=U)
config.STAGE1_MODE = "full"
d, s1 = sf.daily_for(NAMES, now, dl, lambda tk: Q)
assert s1["used"] == "full" and calls == [NAMES] and s1["quotes"] is None
# fast: 처음(메모리 비어 있음) → 전체 받아 메모리 · 다음 사이클 → 일괄 시세 + 야후 일봉 필요한 종목만
config.STAGE1_MODE = "fast"; sf.CACHE = sf.Cache(); calls.clear()
mon21 = datetime(2026, 11, 3, 2, 0, tzinfo=U)
d, s1 = sf.daily_for(NAMES, mon21, lambda tk: (calls.append(list(tk)), {t: PREV[t] for t in tk})[1], lambda tk: Q)
assert s1["used"] == "refresh" and s1["kind"] is None and len(sf.CACHE.frames) == 30 and sf.CACHE.fetched_at == mon21
calls.clear()
q5 = dict(Q); q5["T07"] = quote("T07", prev=float(PREV["T07"]["Close"].iloc[-1]) / 20)   # T07 오늘 병합(1:20)처럼
d, s1 = sf.daily_for(NAMES + ["ZZZ"], now, dl, lambda tk: q5)
assert s1["used"] == "fast" and calls == [["T07"]] and s1["need"] == 1 and s1["mismatch"] == 1, (calls, s1)
assert set(d) == set(NAMES) and d["T07"] is FULL["T07"] and "T07" not in s1["from_quote"] and len(s1["from_quote"]) == 29
assert sf.CACHE.frames["T07"].index[-1] == TUE                   # 받은 일봉으로 메모리도 갱신
# 대상 다시 받기: 시세로 만든 종목만
calls.clear()
n_r = sf.refresh(d, ["T01", "T07", "T09"], s1, download=dl)
assert n_r == 2 and calls == [["T01", "T09"]] and d["T01"] is FULL["T01"] and s1["refresh"] == 2
# 되돌림: 일괄 시세가 적으면 지금 방식
calls.clear()
d, s1 = sf.daily_for(NAMES, now, dl, lambda tk: {})
assert s1["used"] == "fallback" and calls == [NAMES]
# shadow: 지금 방식으로 돌리고 빠른 모드 일봉은 비교용으로
config.STAGE1_MODE = "shadow"; calls.clear()
d, s1 = sf.daily_for(NAMES, now, dl, lambda tk: Q)
assert s1["used"] == "full" and s1["kind"] == "shadow" and calls == [NAMES] and set(s1["fast"]) == set(NAMES)
# 매일 점검: 메모리가 오래됨(화 20시 지남) → 어제 받은 일봉 + 시세 vs 방금 받은 일봉 비교 후 메모리 갱신
config.STAGE1_MODE = "fast"; calls.clear()
tue21 = datetime(2026, 11, 4, 2, 0, tzinfo=U)
d, s1 = sf.daily_for(NAMES, tue21, dl, lambda tk: Q)
assert s1["used"] == "refresh" and s1["kind"] == "daily" and s1["fast"] is not None and sf.CACHE.fetched_at == tue21
print("modes OK")

# ---- 비교 · 기록 · 매일 점검 실패 시 멈춤 ----
cmp = scanner.stage1_compare(FULL, s1["fast"], set(), {}, set())
assert cmp["pass_overlap"] == 100.0 and cmp["pick_overlap"] == 100.0 and cmp["pass_full"] == cmp["pass_fast"] > 0, cmp
bad_fast = {t: FULL[t].assign(Volume=lambda x: x["Volume"][::-1].values) for t in NAMES[:10]}
cmp2 = scanner.stage1_compare(FULL, bad_fast, set(), {}, set())
assert cmp2["pass_overlap"] < 95 and sf.check_failed(cmp2) and not sf.check_failed(cmp)
sent = []
sf.record({**s1, "fast": None}, cmp2, now=tue21, send=sent.append)
assert sent and "점검 실패" in sent[0] and sf.blocked(tue21 + timedelta(hours=3))
assert sf.mode_now(tue21 + timedelta(hours=3)) == "shadow"           # 다음 점검까지 지금 방식(+ 비교)
assert not sf.blocked(datetime(2026, 11, 5, 1, 2, tzinfo=U)) and sf.mode_now(datetime(2026, 11, 5, 1, 2, tzinfo=U)) == "fast"   # 수 20:02 ET 뒤 해제
config.STAGE1_MODE = "shadow"; sent.clear()
sf.record({**s1, "fast": None}, cmp2, now=tue21, send=sent.append)
assert not sent                                                    # shadow 는 기록만(알림·멈춤 없음)
with closing(db.connect()) as conn:
    rows = conn.execute("SELECT used, kind, pass_overlap FROM stage1_runs").fetchall()
assert len(rows) == 2 and rows[0][1] == "daily" and rows[0][2] == cmp2["pass_overlap"]
print("record OK")

# ---- scanner.stage1 통합: fast 결과 = full 결과, 기록 남음 ----
db.set_meta("stage1_block", json.dumps({"until": "2000-01-01T00:00:00+00:00"}))
real_now = datetime.now(U)
settled = sf.last_settle(real_now).date()
pidx = pd.bdate_range(end=pd.Timestamp(settled), periods=40)
tday = pd.Timestamp(settled) + pd.offsets.BDay(1)
ts_t = int(pd.Timestamp(tday).tz_localize("America/New_York").replace(hour=13).timestamp())
P2 = {t: f.iloc[:40].set_axis(pidx) for t, f in FULL.items()}
F2 = {t: pd.concat([P2[t], pd.DataFrame([BAR[t]], index=pd.DatetimeIndex([tday]))]) for t in NAMES}
Q2 = {t: {**quote(t, ts=ts_t), "regularMarketPreviousClose": float(P2[t]["Close"].iloc[-1])} for t in NAMES}
market.download_daily = lambda tk, period="2mo", chunk=40: {t: F2[t] for t in tk if t in F2}
market.bulk_quotes = lambda tk, **k: {t: Q2[t] for t in tk if t in Q2}
config.MAX_CANDIDATES = 12
config.STAGE1_MODE = "full"
p_full, d_full, _, mkt_full = scanner.stage1(NAMES, set(), None, set())
config.STAGE1_MODE = "fast"
sf.CACHE = sf.Cache(); sf.CACHE.set(P2, real_now)
p_fast, d_fast, _, mkt_fast = scanner.stage1(NAMES, set(), None, set())
assert p_fast == p_full and mkt_fast == mkt_full and len(p_full) == 12, (p_fast, p_full)
assert all(d_fast[t] is F2[t] for t in p_fast)                     # 정밀 분석 대상은 야후 일봉으로 다시 받음
assert all(d_fast[t].index[-1] == tday for t in NAMES)             # 나머지(하류 기능용)도 오늘 봉까지
config.STAGE1_MODE = "shadow"
scanner.stage1(NAMES, set(), None, set())
with closing(db.connect()) as conn:
    last = conn.execute("SELECT mode, used, kind, pass_overlap, pick_overlap, refresh FROM stage1_runs ORDER BY rowid DESC LIMIT 3").fetchall()
assert last[0][:5] == ("shadow", "full", "shadow", 100.0, 100.0), last
assert last[1][1] == "fast" and last[1][5] == 12 and last[2][1] == "full", last
print("stage1 integration OK")

# ---- 관리 모드 · 🩺 운영 현황 숫자 ----
assert config.SETTINGS["STAGE1_MODE"][0] is str and config.STAGE1_MODE_CHOICES[0] == "shadow"
import jobs
with closing(db.connect()) as conn:
    h = jobs.health(conn)
assert "1단계 빠른 모드 %" in h and "1단계 비교 겹침 %(최저)" in h, h
print("ALL OK")
