import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🔊 시각 맞춘 거래량(todvol) — 곡선·문턱 만들기 · 판정 창(10:00~15:30) · 표시 한 줄 · 시험 기록(시각 보정으로만 70점, 종목·날짜당 첫 번째) ·
28일마다 다시 · 스캐너 한 사이클(알림 끝 🔊 줄 · 시험 기록 · 점수 그대로) · 🏆 출처 · 📌 한눈에."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "Test test@example.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import numpy as np
import pandas as pd
import db, todvol
db.init_db()
ET = todvol.ET
rng = np.random.default_rng(1)

# 1. 곡선·문턱: 보통 날은 고르게, 큰 거래량 날(마감 2.5~5배)은 아침에 몰리게
G = todvol.GRID
def prof(vreg, shape):
    x = np.clip((G - 570) / 390, 0, 1)
    return vreg * (np.sqrt(x) if shape == "front" else x)
rows = [("N%d" % i, "2026-10-%02d" % (i % 28 + 1), 1e5, v, prof(v, "flat")) for i, v in enumerate(rng.uniform(0.5e5, 1.5e5, 400))]
rows += [("H%d" % i, "2026-10-%02d" % (i % 28 + 1), 1e5, v, prof(v, "front")) for i, v in enumerate(rng.uniform(2.5e5, 5e5, 150))]
res = todvol.fit(rows)
assert res and res["n_heavy"] == 150 and res["n_days"] == 550, res
s10 = res["slots"][600]
assert abs(s10["g"] - np.sqrt(30 / 390)) < 1e-9, s10                       # 큰 거래량 날 곡선(√ 모양)
assert s10["thr2"] is not None and s10["thr2"] >= 2 and s10["p2"] >= 0.85, s10
assert min(res["slots"]) == 600 and max(res["slots"]) == 925                # 10:00~15:25 만
assert todvol.fit(rows[:400] + rows[400:450]) is None                        # 큰 거래량 날 100개 미만 → 안 만듦
tab = {s: {"g": r["g"], 1.5: (r["thr15"], r["p15"]), 2.0: (r["thr2"], r["p2"]), 3.0: (r["thr3"], r["p3"])} for s, r in res["slots"].items()}
d0 = date(2026, 10, 28)
at = lambda h, m: datetime(d0.year, d0.month, d0.day, h, m, tzinfo=ET)
vm_hi = 1.2   # 10:02 에 1.2배 = 보정 1.2 ÷ g(≈0.28) ≈ 4.3배
a = todvol.assess(vm_hi, at(10, 2), tab)
assert a and a["tier"] in (2.0, 3.0) and a["adj"] > 4, a
assert todvol.assess(vm_hi, at(9, 50), tab) is None and todvol.assess(vm_hi, at(15, 31), tab) is None and todvol.assess(vm_hi, at(17, 0), tab) is None
assert todvol.assess(0.05, at(10, 2), tab) is None and todvol.assess(None, at(10, 2), tab) is None and todvol.assess(1.2, at(10, 2), {}) is None
assert todvol.assess(3.5, at(14, 0), tab) is None                            # 이미 3배↑ — 알릴 게 없음
assert todvol.alt_points(1.2, {"tier": 2.0}) == 14 and todvol.alt_points(2.5, {"tier": 2.0}) == 14 and todvol.alt_points(1.6, None) == 8 and todvol.alt_points(3.2, {"tier": 2.0}) == 20
ln = todvol.line({"tier": 2.0, "prec": 0.874}, 0.8)
assert ln == "🔊 오늘 거래량 2배↑ 가능성 높음(지금 0.8배 · 과거 같은 시각 맞음 87%)", ln

# 2. 5분봉 → 하루 줄(프리 포함 누적 · 정규장 봉 60개↑ · 20일 평균 함수)
idx = pd.date_range("2026-10-28 04:00", "2026-10-28 19:55", freq="5min", tz=ET)
vol = np.where((idx.hour * 60 + idx.minute >= 570) & (idx.hour * 60 + idx.minute < 960), 1000.0, 100.0)
dr = todvol.day_rows({"AAA": pd.DataFrame({"Close": 1.0, "Volume": vol}, index=idx)}, lambda t, d: 5e4 if d == "2026-10-28" else None)
assert len(dr) == 1 and dr[0][3] == 78 * 1000 and dr[0][2] == 5e4, dr
j930 = int(np.searchsorted(G, 570)); j1000 = int(np.searchsorted(G, 600))
assert dr[0][4][j930] == 66 * 100 and dr[0][4][j1000] == 66 * 100 + 6 * 1000, (dr[0][4][j930], dr[0][4][j1000])   # 프리 66봉 + 정규장 6봉
assert todvol.day_rows({"AAA": pd.DataFrame({"Close": 1.0, "Volume": vol}, index=idx)}, lambda t, d: None) == []

# 3. 아침 작업: 표본 종목 일봉 → 5분봉(가짜) → 표 · 28일 안엔 다시 안 함
T = date.today()
days = [x.date() for x in pd.bdate_range(end=T - timedelta(days=1), periods=80)]
names = [f"S{i:02d}" for i in range(40)]
with closing(db.connect()) as conn:
    conn.executemany("INSERT OR REPLACE INTO daily_prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                     [(t, d.isoformat(), 2, 2, 2, 2, 1e5) for t in names for d in days])
    conn.commit()
assert len(todvol.sample_tickers(db.connect(), T)) == 40
def fake_dl(tk):
    out = {}
    for n, t in enumerate(tk):
        frames = []
        for k, d in enumerate(days[-30:]):
            ix = pd.date_range(f"{d} 09:30", f"{d} 15:55", freq="5min", tz=ET)
            heavy = (n + k) % 3 == 0
            w = np.linspace(3, 1, len(ix)) if heavy else np.ones(len(ix))
            frames.append(pd.DataFrame({"Close": 2.0, "Volume": w / w.sum() * (3e5 if heavy else 1e5)}, index=ix))
        out[t] = pd.concat(frames)
    return out
logs = []
with closing(db.connect()) as conn:
    r = todvol.maybe_build(conn, T, download=fake_dl, out=logs.append)
    assert r and r["ok"] and r["heavy"] >= 100 and r["slots"] == 66, r
    assert tuple(conn.execute("SELECT COUNT(*), MAX(built) FROM tod_volume").fetchone()) == (66, T.isoformat())
    assert todvol.maybe_build(conn, T + timedelta(days=27), download=fake_dl, out=logs.append) is None
    assert todvol.maybe_build(conn, T + timedelta(days=28), download=lambda tk: {}, out=logs.append)["ok"] is False   # 다시 하려다 자료 없음 → 그대로 둠
    assert conn.execute("SELECT COUNT(*) FROM tod_volume").fetchone()[0] == 66
    t2 = todvol.table(conn)
assert "🔊 시각 맞춘 거래량: 표본 40종목" in logs[0] and len(t2) == 66 and t2[600][2.0][0] is not None, (logs, t2.get(600))

# 4. 기록: 지금 상태 + 시험 기록(시각 보정으로만 70점 · 하루 한 번 · 제외·이미 70점은 아님) · 화면용 최근 30분
now = datetime.now(timezone.utc)
day = now.astimezone(ET).date().isoformat()
aa = {"tier": 2.0, "prec": 0.9, "adj": 4.0}
det = lambda vp: {"점수": {"낙폭": 25, "유통주식": 25, "거래량": vp, "매수체결": 15, "희석": 0}}
with closing(db.connect()) as conn:
    todvol.ensure(conn)
    assert todvol.record(conn, "BBB", day, now, 0.85, 1.2, aa, 65.0, det(0), False) is True       # 65 − 0 + 14 = 79
    assert todvol.record(conn, "BBB", day, now, 0.86, 1.3, aa, 65.0, det(0), False) is False      # 같은 날 두 번째
    assert todvol.record(conn, "AAA", day, now, 0.85, 1.2, aa, 80.0, det(0), False) is False      # 이미 70점(알림 감)
    assert todvol.record(conn, "CCC", day, now, 0.85, 1.2, aa, 50.0, det(0), False) is False      # 50 + 14 = 64
    assert todvol.record(conn, "DDD", day, now, 0.85, 1.2, aa, 65.0, None, True) is False         # ATM 제외
    assert todvol.record(conn, "EEE", day, now, 0.85, 1.2, None, 65.0, det(0), False) is False    # 판정 없음
    assert [tuple(r) for r in conn.execute("SELECT ticker, score, alt_score, tier FROM tod_shadow")] == [("BBB", 65.0, 79.0, 2.0)]
    assert {r[0] for r in conn.execute("SELECT ticker FROM tod_now")} == {"AAA", "BBB", "CCC", "DDD"}
    assert todvol.latest(conn, "bbb", now + timedelta(minutes=10))["tier"] == 2.0
    assert todvol.latest(conn, "BBB", now + timedelta(minutes=31)) is None and todvol.latest(conn, "ZZZ") is None
    import scoreboard
    c = scoreboard.collect(conn)
    pt = c[c.source == "pump_tod"]
    assert list(pt.ticker) == ["BBB"] and (pt.target == 30.0).all() and (pt.horizon == 10).all() and "보정 79점(지금 65점)" in pt.note.iloc[0], pt
    conn.execute("DELETE FROM tod_shadow"); conn.execute("DELETE FROM tod_now"); conn.commit()

# 5. 📌 한눈에: 최근 30분 🔊 상태가 있으면 한 줄(주인만)
import glance
with closing(db.connect()) as conn:
    todvol.record(conn, "GLN", day, now, 1.0, 0.9, {"tier": 3.0, "prec": 0.88, "adj": 5}, 40.0, det(0), False)
gl = glance.build("GLN", guest=False)
assert any(x.startswith("🔊 오늘 거래량 3배↑ 가능성 높음(지금 0.9배") for x in gl["ok"]), gl["ok"]
assert not any("🔊" in x for x in glance.build("GLN", guest=True)["ok"])

# 6. 스캐너 한 사이클: 10:30(동부)로 고정 · AAA 는 원래 80점 → 알림 끝에 🔊 줄 · BBB 는 65점 → 알림 없이 시험 기록 · 점수는 그대로
import config, market, scanner, universe, sec
dd = pd.Timestamp.today().normalize()
while dd.weekday() >= 5:   # 주말이면 스캐너가 거래일을 금요일로 잡음 → 가장 가까운 평일로
    dd -= pd.Timedelta(days=1)
didx = pd.bdate_range(end=dd - pd.Timedelta(days=1), periods=45)[-40:]
close = np.linspace(2.0, 1.0, 40)
daily = pd.DataFrame({"Open": close, "High": close * 1.05, "Low": close * 0.95, "Close": close, "Volume": 1e6}, index=didx)
iidx = pd.date_range(dd.tz_localize(ET) + pd.Timedelta(hours=9, minutes=30), periods=60, freq="min")
ic = np.linspace(0.80, 0.85, 60)
intra = pd.DataFrame({"Open": ic, "High": ic * 1.001, "Low": ic * 0.999, "Close": ic, "Volume": 2e4}, index=iidx)   # 누적 120만 = 20일 평균의 1.2배
market.download_daily = lambda tk, period="3mo", chunk=40: {t: daily for t in tk}
market.download_intraday = lambda tk: {t: intra for t in tk}
market.fetch_fundamentals = lambda t: {"name": t, "exchange": "NASDAQ", "float_shares": 8e6, "shares_out": 9e6, "market_cap": 1e7}
universe.get_universe = lambda *a, **k: (["AAA", "BBB"], {"AAA", "BBB"})
scanner.dilution_for = lambda conn, client, t, budget: {"status": "CLEAN" if t == "AAA" else "OFFERING", "flags": {}}
sent = []
scanner.notify.send_telegram = lambda x: sent.append(x) or True
FIX = datetime(dd.year, dd.month, dd.day, 10, 30, tzinfo=ET)
class FixedDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIX.astimezone(tz) if tz else FIX.replace(tzinfo=None)
scanner.datetime = FixedDT
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM tod_volume")
    conn.execute("INSERT INTO tod_volume VALUES (630, 0.3, 1.5, 2.0, 3.0, 0.86, 0.87, 0.88, 1000, 200, ?)", (T.isoformat(),)); conn.commit()
    scanner.run_cycle(conn, sec.SecClient.__new__(sec.SecClient))
    snaps = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT ticker, pump_score, volume_mult FROM daily_snapshots WHERE date=?", (dd.date().isoformat(),))}
    shadow = [tuple(r) for r in conn.execute("SELECT ticker, score, alt_score, tier FROM tod_shadow")]
    nowrows = {r[0]: r[1] for r in conn.execute("SELECT ticker, tier FROM tod_now")}
assert snaps["AAA"][0] == 80.0 and snaps["BBB"][0] == 65.0 and abs(snaps["AAA"][1] - 1.2) < 1e-9, snaps   # 점수는 지금 방식 그대로
assert shadow == [("BBB", 65.0, 85.0, 3.0)], shadow                                                        # 1.2 ÷ 0.3 = 4 ≥ 3 → 3배↑(20점)
assert nowrows == {"AAA": 3.0, "BBB": 3.0, "GLN": 3.0}, nowrows
pump = [x for x in sent if x.startswith("[AAA] 펌핑점수 80")]
assert pump and "\n🔊 오늘 거래량 3배↑ 가능성 높음(지금 1.2배 · 과거 같은 시각 맞음 88%)" in pump[0], sent
assert not any(x.startswith("[BBB] 펌핑점수") for x in sent), sent
print("ALL OK")
