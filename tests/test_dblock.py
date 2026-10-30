"""DB 잠금(2026-10-30 아침 '잠김' 사고) — retry_locked · 공매도 잔고/수집기가 인터넷에서 받는 동안 잠금을 쥐지 않음 ·
presim 전체 재작성이 먼저 지우지 않음(실패해도 옛 표 유지, 성공하면 옛 행 정리) · 병합 수리가 바뀐 종목의 presim 사건만 지움."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, threading, time, sqlite3
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import config, db

db.init_db()


def can_write_now() -> bool:
    """다른 프로그램 흉내: 0.2초만 기다려 쓰기 잠금을 잡아 본다."""
    c = sqlite3.connect(config.DB_PATH, timeout=0.2)
    try:
        c.execute("BEGIN IMMEDIATE"); c.execute("ROLLBACK"); return True
    except sqlite3.OperationalError:
        return False
    finally:
        c.close()


# ---- 1) retry_locked: 잠김이면 기다렸다 성공 · 다른 오류는 바로
holder = sqlite3.connect(config.DB_PATH, timeout=1, check_same_thread=False); holder.execute("BEGIN IMMEDIATE")
assert not can_write_now()
threading.Timer(0.6, holder.rollback).start()
db.TIMEOUT = 0.1
calls = {"n": 0}
def _w():
    calls["n"] += 1
    with closing(db.connect()) as c:
        c.execute("INSERT OR REPLACE INTO meta (key, value, updated_at) VALUES ('lk','1','x')"); c.commit()
db.retry_locked(_w, tries=6, wait=0.2)
assert calls["n"] >= 2 and db.get_meta("lk")["value"] == "1", calls
holder.close(); db.TIMEOUT = 30.0
bad = {"n": 0}
def _bad():
    bad["n"] += 1; raise sqlite3.OperationalError("no such table: zzz")
try:
    db.retry_locked(_bad, wait=0.01); raise SystemExit("should raise")
except sqlite3.OperationalError:
    assert bad["n"] == 1

# ---- 2) 공매도 잔고: 받는(get_info) 동안 다른 프로그램이 쓸 수 있어야 함(종목마다 확정)
import shortint
seen = []
def getter(t):
    seen.append(can_write_now())
    return {"sharesShort": 1_000_000, "sharesShortPriorMonth": 900_000, "shortPercentOfFloat": 0.2, "shortRatio": 3.0, "dateShortInterest": 1760000000, "floatShares": 5_000_000}
assert shortint.refresh(["AAA", "BBB", "CCC"], getter=getter, out=lambda *_: None) == 3
assert seen == [True, True, True], seen     # 예전 코드: 2번째·3번째 다운로드 때 False(첫 INSERT 부터 끝까지 잠금)

# ---- 3) 수집기: SEC 문서를 받는 동안 잠금을 쥐지 않음(모아서 한 번에 씀)
import eventlab as ev, secbackfill
with closing(db.connect()) as conn:
    secbackfill.ensure_tables(conn)
    for k in range(3):
        conn.execute("INSERT INTO sec_hist VALUES (?,?,?,?,?)", (f"0001-26-00000{k}", "ABCD", "8-K", (date.today() - timedelta(days=k + 1)).isoformat(), "8.01"))
    conn.commit()
IDX = """<div class="infoHead">Accepted</div><div class="info">2026-03-10 16:05:12</div>
<table class="tableFile"><tr><td>1</td><td>8-K</td><td><a href="/Archives/edgar/data/7/x/main.htm">main.htm</a></td><td>8-K</td></tr></table>"""
fetch_free = []
class FC:
    def cik_for(s, t): return 7
    def _get(s, u):
        class R: text = IDX
        return R()
    def fetch_text(s, u, limit=0):
        fetch_free.append(can_write_now()); return "Abcd Bio announces update\nSome lead text."
assert ev.collect(FC(), out=lambda *_: None) == 3
assert fetch_free and all(fetch_free), fetch_free   # 예전 코드: 2번째 문서부터 False
with closing(db.connect()) as conn:
    assert conn.execute("SELECT COUNT(*) FROM ev_docs").fetchone()[0] == 3

# ---- 4) presim 전체 재작성: 먼저 지우지 않음 · 실패하면 옛 표 그대로 · 성공하면 옛 행만 정리하고 버전 표시
import presim
days = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=1), periods=320)
r = np.random.default_rng(3)
c = 2.0 * np.cumprod(1 + r.normal(0, 0.03, len(days)))
bars = {"AAA": pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": 2e5}, index=days)}
with closing(db.connect()) as conn:
    presim.ensure(conn)
    blob = np.zeros(40, dtype=np.float32).tobytes()
    conn.execute("INSERT INTO presim_ep (ticker, date, px, flags, onset, n, hi, lo, cl) VALUES ('OLDX','2025-01-02',1.0,1,1,40,?,?,?)", (blob, blob, blob))
    conn.commit()
    db.set_meta("presim_ep_ver", "1")
    real = presim._write_ep
    presim._write_ep = lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error"))
    try:
        presim.build_episodes(conn, bars=bars, out=lambda *_: None, today=days[-1].date()); raise SystemExit("should raise")
    except sqlite3.OperationalError:
        pass
    presim._write_ep = real
    assert conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker='OLDX'").fetchone()[0] == 1 and db.get_meta("presim_ep_ver")["value"] == "1"   # 옛 표 그대로
    res = presim.build_episodes(conn, bars=bars, out=lambda *_: None, today=days[-1].date())
    assert res["pruned"] == 1 and conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker='OLDX'").fetchone()[0] == 0, res
    assert conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker='AAA'").fetchone()[0] > 0 and db.get_meta("presim_ep_ver")["value"] == presim.EP_VERSION
    n_aaa = conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker='AAA'").fetchone()[0]

    # ---- 5) 병합 수리: 일봉이 실제로 바뀐 종목만 presim 사건을 지움 → 다음 build 가 다시 만듦
    import pricefix, rsplit
    rsplit.ensure_tables(conn)
    conn.execute("INSERT INTO rs_events VALUES ('AAA', ?, 0.1, 1.0)", ((date.today() - timedelta(days=30)).isoformat(),))
    conn.execute("INSERT INTO rs_events VALUES ('SAME', ?, 0.5, 1.0)", ((date.today() - timedelta(days=30)).isoformat(),))
    db.upsert_daily_prices(conn, "AAA", bars["AAA"] / 10)                                      # 저장본 = 옛 기준(÷10)
    db.upsert_daily_prices(conn, "SAME", bars["AAA"])
    conn.execute("INSERT INTO presim_ep (ticker, date, px, flags, onset, n, hi, lo, cl) VALUES ('SAME','2025-01-02',1.0,1,1,40,?,?,?)", (blob, blob, blob)); conn.commit()
    rr = pricefix.repair(conn, ["AAA", "SAME"], download=lambda ts: {t: bars["AAA"] for t in ts})
    assert rr["changed"] == ["AAA"] and rr["presim_dropped"] == n_aaa, rr
    assert conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker='AAA'").fetchone()[0] == 0 and conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker='SAME'").fetchone()[0] == 1
    res2 = presim.build_episodes(conn, bars=bars, out=lambda *_: None, today=days[-1].date())
    assert conn.execute("SELECT COUNT(*) FROM presim_ep WHERE ticker='AAA'").fetchone()[0] == n_aaa, res2   # 같은 아침에 다시 만들어짐
print("ALL OK")
