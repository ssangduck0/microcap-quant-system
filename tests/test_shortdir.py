"""🧭 공매도 방향 기록(2026-11-01): IBKR 대차 방향(신규 숏 유입·커버 의심) · 장세 공포 사후 가설 → 🏆 출처 · 공매도 상세 표시 · 스퀴즈 랭크 2년 검증 안내."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_PAGE", None); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, halts, shortdata, chartex, shortdir, scoreboard as sb

db.init_db(); halts.fetch = lambda *a, **k: []
T = date.today()
wd = [T - timedelta(days=i) for i in range(20)]
wd = [d for d in wd if d.weekday() < 5][:7]                     # 최근 평일 7일(최신순)
d1, d0 = wd[0], wd[5]                                            # 최근 vs 5평일 전

with closing(db.connect()) as conn:
    shortdata.ensure_tables(conn); chartex.ensure(conn)
    pat = {"AAA": ((100_000, 10.0), (30_000, 20.0)),   # 빌릴 주식 30%·수수료 2배 → 신규 숏 유입 의심
           "BBB": ((1_000, 60.0), (5_000, 30.0)),      # 5배·절반 → 커버 의심
           "CCC": ((50_000, 10.0), (45_000, 11.0)),    # 변화 적음
           "DDD": ((5_000, 10.0), (1_000, 30.0)),      # 5일 전 1만 주 미만 → 유입 판정 안 함
           "EEE": ((100_000, 10.0), (20_000, 30.0))}   # 유입 모양이지만 가격 $25 → 기록 안 함
    for t, ((a0, f0), (a1, f1)) in pat.items():
        conn.execute("INSERT INTO ibkr_borrow_day VALUES (?,?,?,?,?)", (d0.isoformat(), t, a0, a0, f0))
        conn.execute("INSERT INTO ibkr_borrow_day VALUES (?,?,?,?,?)", (d1.isoformat(), t, a1, a1, f1))
        for d in wd[1:5]:
            conn.execute("INSERT INTO ibkr_borrow_day VALUES (?,?,?,?,?)", (d.isoformat(), t, (a0 + a1) / 2, (a0 + a1) / 2, (f0 + f1) / 2))
    sat = next(T - timedelta(days=i) for i in range(1, 8) if (T - timedelta(days=i)).weekday() == 5)
    conn.execute("INSERT OR IGNORE INTO ibkr_borrow_day VALUES (?,?,?,?,?)", (sat.isoformat(), "AAA", 1, 1, 999.0))   # 주말 날짜는 건너뜀
    # 일봉: 결제일 s(20일 전) 종가 2.0 → 지금
    s = (T - timedelta(days=20)).isoformat()
    closes = {"AAA": (5.0, 4.0), "BBB": (3.0, 3.5), "CCC": (2.0, 2.0), "DDD": (1.0, 1.0), "EEE": (30.0, 25.0),
              "FFF": (2.0, 1.5), "GGG": (2.0, 1.4), "HHH": (2.0, 2.2), "III": (40.0, 30.0)}
    for t, (c0, c1) in closes.items():
        conn.execute("INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?)", (t, s, c0, c0, c0, c0, 1e6))
        conn.execute("INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?)", (t, (T - timedelta(days=1)).isoformat(), c1, c1, c1, c1, 1e6))
    # 공식 잔고(보고 행): FFF 15%·−25% → 후보 · GGG 5% → 잔고 부족 · HHH 15% 하지만 +10% · III 가격 $30
    for t, p in (("FFF", 15.0), ("GGG", 5.0), ("HHH", 15.0), ("III", 20.0)):
        conn.execute("INSERT INTO cx_short_interest (ticker, date, si_pct, short_shares, dtc, change_shares, change_pct, reported) VALUES (?,?,?,?,?,?,?,1)", (t, s, p, 1e6, 3.0, 1e5, 10.0))
    conn.execute("INSERT INTO cx_short_interest (ticker, date, si_pct, short_shares, dtc, change_shares, change_pct, reported) VALUES ('FFF', ?, 99, 1, 1, 1, 1, 1)",
                 ((T - timedelta(days=80)).isoformat(),))   # 45일 지난 보고는 안 봄
    conn.commit()

    bd = shortdir.borrow_dir(conn)
    assert bd["AAA"]["kind"] == "ib_inflow" and bd["BBB"]["kind"] == "ib_cover" and bd["CCC"]["kind"] is None and bd["DDD"]["kind"] is None, bd
    assert bd["AAA"]["d1"] == d1.isoformat() and bd["AAA"]["d0"] == d0.isoformat() and bd["AAA"]["fee1"] == 20.0     # 주말(999%) 제외
    assert list(shortdir.borrow_dir(conn, symbol="aaa")) == ["AAA"]
    assert shortdir.label(conn, "AAA")["label"] == "🆕 신규 숏 유입 의심" and shortdir.label(conn, "CCC")["label"] == "변화 적음" and shortdir.label(conn, "ZZZ") is None

    assert shortdir.fear_si(conn, "green") == [] and shortdir.fear_si(conn, None) == []          # 🟢 장세엔 기록 안 함
    fs = shortdir.fear_si(conn, "red")
    assert [r["ticker"] for r in fs] == ["FFF"] and "결제일 뒤 -25%" in fs[0]["note"] and fs[0]["price"] == 1.5, fs

    logs = []
    res = shortdir.daily(conn, out=logs.append, light="yellow")
    assert res == {"ib_inflow": 1, "ib_cover": 1, "fear_si": 1}, res
    assert "신규 숏 유입 의심 1" in logs[0] and "장세 yellow" in logs[0]
    assert shortdir.daily(conn, out=logs.append, light="yellow") == {"ib_inflow": 0, "ib_cover": 0, "fear_si": 0}   # 10일에 한 번
    got = {(r[0], r[1]): r[2] for r in conn.execute("SELECT ticker, kind, price FROM short_dir_signals")}
    assert got == {("AAA", "ib_inflow"): 4.0, ("BBB", "ib_cover"): 3.5, ("FFF", "fear_si"): 1.5}, got

    col = sb.collect(conn)
    m = dict(zip(col.ticker, col.source))
    assert m["AAA"] == "sd_ib_inflow" and m["BBB"] == "sd_ib_cover" and m["FFF"] == "sd_fear_si", m
    row = col[col.ticker == "AAA"].iloc[0]
    assert row["direction"] == -1 and row["target"] == 20.0 and row["horizon"] == 10 and "수수료 10.0→20.0%" in row["note"]

# 🧨 공매도 상세: 대차 방향 칩 · 해석 주의 문구
from streamlit.testing.v1 import AppTest
app = os.path.join(tmp, "sd_app.py")
with open(app, "w", encoding="utf-8") as f:
    f.write(f"import sys; sys.path.insert(0, {os.environ['QS_ROOT']!r})\nimport ui_kit, shortpanel_ui\nui_kit.inject()\nshortpanel_ui.render('AAA')\n")
at = AppTest.from_file(app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
md = "\n".join(m.value for m in at.markdown)
cap = "\n".join(c.value for c in at.caption)
assert "🧭 대차 방향" in md and "신규 숏 유입 의심" in md and "100,000→30,000주" in md, md[:800]
assert "한 달에 2번" in cap and "잔고가 아니고" in cap

# 🧨 스퀴즈 랭크: 2년 검증 안내
import inspect, squeeze_ui
src = inspect.getsource(squeeze_ui.render)
assert "2년 검증(2026-11-01)" in src and "양쪽으로 크게 움직일 종목" in src
print("ALL OK")
