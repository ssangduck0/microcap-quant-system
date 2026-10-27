import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, pricevault as pv
db.init_db()
T = date.today()
Y = T - timedelta(days=1)


def frame(n=60, end=None, start_px=1.0, step=0.0):
    idx = pd.bdate_range(end=pd.Timestamp(end or Y), periods=n)
    c = start_px + step * np.arange(len(idx))
    return pd.DataFrame({"Open": c, "High": c * 1.05, "Low": c * 0.95, "Close": c, "Adj Close": c, "Volume": 1e6}, index=idx)


# ------------------------------------------------------------------ 1) 저장 · 병합 단위 맞추기
with closing(db.connect()) as conn:
    pv.ensure(conn)
    old = frame(60, end=Y - timedelta(days=40), start_px=0.5)          # 예전에 받은 것(0.5달러대)
    assert pv.save_bars(conn, "SPL", old)["saved"] == len(old)
    same = frame(60, end=Y, start_px=0.5)                               # 겹치는 날 같은 가격 → 단위 그대로
    same.loc[same.index.isin(old.index), "Close"] = old.loc[old.index.isin(same.index), "Close"].values
    r = pv.save_bars(conn, "SPL", same)
    assert r["factor"] == 1.0
    # 1:10 병합 뒤 yfinance 가 최근 3개월을 10배로 다시 조정해서 줌 → 예전 보관분(겹치지 않는 앞부분)도 10배로 맞춤
    first_old = conn.execute("SELECT close FROM px_vault WHERE ticker='SPL' ORDER BY date LIMIT 1").fetchone()[0]
    adj = same.iloc[-40:].copy() * 1
    for col in ("Open", "High", "Low", "Close"):
        adj[col] = adj[col] * 10
    r = pv.save_bars(conn, "SPL", adj)
    assert abs(r["factor"] - 10) < 1e-9, r
    assert abs(conn.execute("SELECT close FROM px_vault WHERE ticker='SPL' ORDER BY date LIMIT 1").fetchone()[0] - first_old * 10) < 1e-9
    assert conn.execute("SELECT COUNT(*) FROM px_adjust WHERE ticker='SPL'").fetchone()[0] == 1
    # 하루짜리 데이터 오류(한 날만 다름)는 단위 변화로 보지 않음
    noisy = same.iloc[-40:].copy()
    noisy["Close"] = noisy["Close"] * 10
    noisy.iloc[5, noisy.columns.get_loc("Close")] *= 1.3
    before = conn.execute("SELECT COUNT(*) FROM px_adjust").fetchone()[0]
    r_noisy = pv.save_bars(conn, "SPL", noisy)
    assert abs(r_noisy["factor"] - 1.0) < 1e-9, r_noisy                  # 이미 10배 단위로 맞춰져 있어 대부분 겹치는 날 비율 1 → 하루 오류로는 안 바뀜
    assert conn.execute("SELECT COUNT(*) FROM px_adjust").fetchone()[0] == before
    conn.commit()
    b = pv.bars("SPL", conn)
    assert b is not None and list(b.columns) == pv.COLS and b.index.is_monotonic_increasing

# 빈 일봉·NaN 만 있는 일봉은 저장하지 않음
with closing(db.connect()) as conn:
    nan = frame(5); nan["Close"] = np.nan
    assert pv.save_bars(conn, "NAN", nan)["saved"] == 0

# fill: 빠진 종목만 채움
data = {"SPL": None, "NEW": frame(10)}
assert pv.fill(data, ["SPL", "NEW", "NONE"]) == ["SPL"] and data["SPL"] is not None and "NONE" not in data

# ------------------------------------------------------------------ 2) 대상 고르기
import papertrade, scoreboard as sb, pick30
with closing(db.connect()) as conn:
    conn.execute(papertrade.DDL)
    conn.execute("INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, status) VALUES ('b', ?, 'HOLD', 1, 50, '[]', 1.0, 100, 'open')", ((T - timedelta(days=12)).isoformat(),))
    conn.execute(pick30.LOG_DDL)
    conn.execute("INSERT INTO pick_signals VALUES (?,?,?,?,?,?,?,?)", ((T - timedelta(days=5)).isoformat(), "PICK", "$1 상장 유지", 1.0, 0.5, 100.0, "가능", 0))
    conn.execute("INSERT INTO pick_signals VALUES (?,?,?,?,?,?,?,?)", ((T - timedelta(days=190)).isoformat(), "OLD", "$1 상장 유지", 1.0, 0.5, 100.0, "가능", 0))  # 평가 끝난 지 오래
    conn.commit()
    tg = pv.targets(conn)
assert "HOLD" in tg and tg["HOLD"]["prio"] == 0 and "PICK" in tg and "OLD" not in tg, tg
assert any("PICK" in x for x in tg["PICK"]["reasons"])

# ------------------------------------------------------------------ 3) 매일 아침: 받음 · 못 받음 3번 → 끊김 · 새 봉 없음 → 끊김 · 인터넷 문제 · 다시 거래
with closing(db.connect()) as conn:
    for t in ("GONE1", "STALE", "OK1", "OK2", "OK3"):
        conn.execute("INSERT OR REPLACE INTO px_watch (ticker, reasons, first_added, keep_until, misses) VALUES (?, '[]', ?, ?, 0)", (t, T.isoformat(), (T + timedelta(days=30)).isoformat()))
    pv.save_bars(conn, "GONE1", frame(30, start_px=0.3))
    conn.commit()
stale = frame(40, end=T - timedelta(days=30), start_px=0.2)       # 마지막 봉이 한 달 전에 멈춤
dl = lambda ts: {t: (stale if t == "STALE" else frame(30)) for t in ts if t not in ("GONE1",)}  # noqa: E731
for i in range(3):
    r = pv.daily(download=dl, out=lambda *_: None)
g = pv.gone()
assert "GONE1" in g and "연속 3번" in g["GONE1"]["reason"] and abs(g["GONE1"]["last_close"] - frame(30, start_px=0.3)["Close"].iloc[-1]) < 1e-9, g
assert "STALE" in g and "새 봉 없음" in g["STALE"]["reason"], g
assert "OK1" not in g
# 인터넷 문제(대부분 못 받음)인 날은 못 받음 횟수를 세지 않음
with closing(db.connect()) as conn:
    conn.execute("UPDATE px_watch SET misses=0 WHERE ticker='OK1'"); conn.commit()
r = pv.daily(download=lambda ts: {}, out=lambda *_: None)
assert r["outage"]
with closing(db.connect()) as conn:
    assert conn.execute("SELECT misses FROM px_watch WHERE ticker='OK1'").fetchone()[0] == 0
# 다시 거래되면 끊김 해제
r = pv.daily(download=lambda ts: {t: frame(30) for t in ts}, out=lambda *_: None)
assert "STALE" in r["back"] and "STALE" not in pv.gone() and "GONE1" in r["back"]

# ------------------------------------------------------------------ 4) 진입가 병합 보정
adjdf = frame(60, start_px=5.0)                 # 병합 뒤 다시 조정된 가격(5달러대)
day = adjdf.index[20].strftime("%Y-%m-%d")
with closing(db.connect()) as conn:
    import rsplit
    for d_ in rsplit.DDL:
        conn.execute(d_)
    conn.execute("INSERT INTO rs_events (ticker, date, ratio, split_close) VALUES ('RS', ?, 0.1, 5.0)", (adjdf.index[40].strftime("%Y-%m-%d"),))
    conn.commit()
    e, why = pv.fix_entry("RS", day, 0.5, adjdf, conn)                                  # 기록 있음 + 데이터 조정됨 → ×10
    assert abs(e - 5.0) < 1e-9 and "병합 기록" in why, (e, why)
    raw = frame(60, start_px=0.5)                                                       # 기록 있지만 데이터가 아직 조정 안 됨 → 그대로
    e, why = pv.fix_entry("RS", day, 0.5, raw, conn)
    assert abs(e - 0.5) < 1e-9 and why == "", (e, why)
    e, why = pv.fix_entry("NOREC", day, 0.5, adjdf, conn)                               # 기록 없음 + 10배 차이 → 신호일 종가
    assert abs(e - float(adjdf["Close"].iloc[20])) < 1e-9 and "병합 추정" in why
    e, why = pv.fix_entry("NOREC", day, 4.0, adjdf, conn)                               # 정상(차이 작음) → 그대로
    assert e == 4.0 and why == ""
    assert pv.fix_entry("X", day, None, adjdf, conn) == (None, "")

# ------------------------------------------------------------------ 5) 성과 공표: 병합 오판 방지 · 끊김 확정(7일 유예) · 예전 오판 다시 판정
sigday = adjdf.index[20].strftime("%Y-%m-%d")
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM pick_signals")
    for t, px in (("RS", 0.5), ("DEAD", 1.0), ("FRESH", 1.0)):
        conn.execute("INSERT INTO pick_signals VALUES (?,?,?,?,?,?,?,?)", (sigday, t, "$1 상장 유지", px * 1.5, px, 50.0, "가능", 0))
    pv.save_bars(conn, "DEAD", frame(25, end=adjdf.index[30], start_px=1.0))
    pv.save_bars(conn, "FRESH", frame(25, end=adjdf.index[30], start_px=1.0))
    conn.execute("INSERT OR REPLACE INTO px_gone VALUES ('DEAD', ?, 1.0, ?, '연속 3번 주가 못 받음')", (adjdf.index[30].strftime("%Y-%m-%d"), (T - timedelta(days=10)).isoformat()))
    conn.execute("INSERT OR REPLACE INTO px_gone VALUES ('FRESH', ?, 1.0, ?, '연속 3번 주가 못 받음')", (adjdf.index[30].strftime("%Y-%m-%d"), (T - timedelta(days=2)).isoformat()))
    conn.execute(sb.DDL)
    conn.execute("""INSERT OR REPLACE INTO pred_outcomes (source, date, ticker, ref, entry, max_up, max_down, close_h, bars, status, updated_at)
                    VALUES ('pick_strong', ?, 'RS', ?, 0.5, 900, 0, 900, 60, '성공', 'x')""", (sigday, "$1 상장 유지"[:12]))   # 예전 오판
    conn.commit()
    res = sb.update(conn, out=lambda *_: None, download=lambda ts: {t: adjdf for t in ts if t == "RS"})
    st = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT ticker, status, max_up FROM pred_outcomes")}
assert st["RS"][1] < 100, st                      # +900% '성공' → 병합 맞춤 뒤 정상 범위로 다시 판정
assert st["DEAD"][0] == "실패", st                 # 끊긴 지 10일 → 목표 못 넘고 끊김 = 실패
assert st["FRESH"][0] == "대기", st                # 끊긴 지 2일 → 아직 기다림(거래정지가 풀릴 수 있음)

# ------------------------------------------------------------------ 6) 가상매매: 보관소로 채움 · 끊긴 종목 정리 · 병합 단위
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM pt_trades")
    d0 = adjdf.index[20].strftime("%Y-%m-%d")
    conn.execute("INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, status) VALUES ('b', ?, 'DEAD', 1, 50, '[]', 1.0, 100, 'open')", (d0,))
    conn.execute("INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, status) VALUES ('b', ?, 'RS', 1, 50, '[]', 0.5, 100, 'open')", (d0,))
    # 진입 바로 뒤 주가가 끊긴 종목: 보관소엔 진입일까지만 있음 → 3일 보유를 못 채움 → 끊긴 지 10일이면 마지막 가격으로 정리
    dead2 = frame(25, end=adjdf.index[20], start_px=0.8)
    pv.save_bars(conn, "DEAD2", dead2)
    conn.execute("INSERT OR REPLACE INTO px_gone VALUES ('DEAD2', ?, 0.8, ?, '연속 3번 주가 못 받음')", (d0, (T - timedelta(days=10)).isoformat()))
    conn.execute("INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, status) VALUES ('b', ?, 'DEAD2', 1, 50, '[]', 0.8, 100, 'open')", (d0,))
    # 가격 기록이 아예 없는 종목 → 전액 손실
    conn.execute("INSERT OR REPLACE INTO px_gone VALUES ('NOPX', NULL, NULL, ?, '연속 3번 주가 못 받음 · 보관된 가격 없음')", ((T - timedelta(days=10)).isoformat(),))
    conn.execute("INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, status) VALUES ('b', ?, 'NOPX', 1, 50, '[]', 0.8, 100, 'open')", (d0,))
    conn.commit()
flat = frame(60, start_px=5.0)          # 병합 뒤 단위(×10)로 횡보 → 3일 보유 종가로 청산, 장부에는 병합 전 단위로
n = papertrade.update({"RS": flat})
with closing(db.connect()) as conn:
    rows = {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM pt_trades")}
assert rows["RS"]["status"] == "closed" and abs(rows["RS"]["exit"] / rows["RS"]["entry"] - 1) < 0.01 and "병합" in rows["RS"]["reason"], rows["RS"]
assert rows["DEAD"]["status"] == "closed" and rows["DEAD"]["reason"] == "3일 보유 종가", rows["DEAD"]       # yfinance 에 없어도 보관소 일봉으로 정상 판정
assert rows["DEAD2"]["status"] == "closed" and "주가 끊김" in rows["DEAD2"]["reason"] and abs(rows["DEAD2"]["exit"] - float(dead2["Close"].iloc[-1])) < 1e-9, rows["DEAD2"]
assert rows["NOPX"]["status"] == "closed" and rows["NOPX"]["exit"] == 0.0 and "전액 손실" in rows["NOPX"]["reason"], rows["NOPX"]

# ------------------------------------------------------------------ 7) 이벤트 연구: yfinance 에 없는 종목은 보관소로 라벨
import eventlab as ev
with closing(db.connect()) as conn:
    ev.ensure_tables(conn)
    pv.save_bars(conn, "VAULTONLY", frame(120))
    f = frame(120).index[60].strftime("%Y-%m-%d")
    conn.execute("INSERT INTO ev_docs (accession, ticker, form, items, filed, accepted, title, types, sentiment, ok) VALUES ('v1','VAULTONLY','8-K','8.01',?,?,'t','[\"기타\"]','중립',1)",
                 (f, f"{f} 08:00:00"))
    conn.commit()
ev.label(download=lambda ts: {"IWM": frame(120)} if ts == ["IWM"] else {}, out=lambda *_: None)
with closing(db.connect()) as conn:
    assert conn.execute("SELECT COUNT(*) FROM ev_labels WHERE ticker='VAULTONLY'").fetchone()[0] == 1
    assert pv.summary(conn)["tickers"] >= 5
# ------------------------------------------------------------------ 8) 화면: 🏆 성과 공표 맨 아래 '🗄 주가 보관소' 칸
with closing(db.connect()) as conn:
    now = db.utcnow_iso()
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "ZZZ", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 1.2, "low_20d": 0.8,
        "drawdown_pct": -10.0, "day_change_pct": -1.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 1e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
import halts; halts.fetch = lambda *a, **k: []
from streamlit.testing.v1 import AppTest
os.environ["QUANT_TEST_PAGE"] = "score"
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]
assert "🗄 주가 보관소 · 주가가 끊긴 종목" in [e.label for e in at.expander]
cap = " ".join(c.value for c in at.caption)
assert "보관 " in cap and "SPL ×10" in cap and any("마지막 거래일" in d.value.columns for d in at.dataframe), cap[:600]
os.environ.pop("QUANT_TEST_PAGE", None)
print("ALL OK")
