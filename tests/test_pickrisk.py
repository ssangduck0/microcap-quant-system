import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🎯 PICK '과거 비슷한 사례'(pickrisk) — 재생(병합 환산 · 그날까지 제출된 표지만) · 표 · 조회 · 유력·안전 순 · 🏆 목표 먼저(−30% 전에) · 기록 칸 · 칩/표."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np
import pandas as pd
import db, shares, rsplit, pickrisk, pick30, scoreboard
db.init_db()
T = date.today()
days = [d.date().isoformat() for d in pd.bdate_range(end=T - timedelta(days=1), periods=300)]
N = len(days)


def series(base, moves=()):
    """종가 배열: base 에서 시작해 ±1% 흔들림 · moves = [(시작 i, 끝 i, 끝 가격)] 사이를 직선으로."""
    cl = np.array([base * (1.01 if i % 2 else 1.0) for i in range(N)])
    for a, b, px in moves:
        cl[a:b + 1] = np.linspace(cl[a], px, b - a + 1)
        cl[b + 1:] = np.array([px * (1.01 if i % 2 else 1.0) for i in range(b + 1, N)])
    return cl


def put(conn, t, cl):
    conn.executemany("INSERT OR REPLACE INTO daily_prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                     [(t, d, c, c * 1.005, c * 0.995, c, 1_000_000) for d, c in zip(days, cl)])


with closing(db.connect()) as conn:
    conn.execute(shares.HIST_DDL); rsplit.ensure_tables(conn)
    put(conn, "BSUP", series(2.0, [(200, 230, 3.2)]))      # baby shelf: 2,500만 주 → 탈출가 $3(+50%) · 200일째부터 $3.2 로 → 목표 먼저
    put(conn, "BSDN", series(2.0, [(200, 215, 1.3)]))      # 같은 목표인데 −35% 로 → −30% 먼저
    put(conn, "ONE", series(0.7, [(200, 220, 1.05)]))      # $1 목표(+43%) · 시총 커서 baby shelf 아님
    put(conn, "SPLT", series(5.0))                         # 일봉은 지금 단위 $5 · 150일째 1:10 병합(그 전 실제 가격 $0.5)
    put(conn, "LATE", series(2.0, [(200, 230, 3.2)]))      # BSUP 와 같지만 표지가 250일째에야 제출 → 그 전엔 몰랐어야 함
    rows = [("BSUP", days[0], days[5], "10-Q", 25e6), ("BSDN", days[0], days[5], "10-Q", 25e6), ("ONE", days[0], days[5], "10-Q", 500e6),
            ("SPLT", days[0], days[5], "10-Q", 100e6), ("SPLT", days[160], days[165], "10-Q", 10e6), ("LATE", days[0], days[250], "10-Q", 25e6)]
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", rows)
    conn.execute("INSERT INTO rs_events VALUES ('SPLT', ?, 0.1, 5.0)", (days[150],))
    conn.commit()
    ev = pickrisk.events(conn, T)
by = {t: g for t, g in ev.groupby("t")}
assert set(by) == {"BSUP", "BSDN", "ONE", "SPLT"}, set(by)               # LATE: 표지 제출 전엔 사건 없음(컨닝 금지)
b = by["BSUP"]
assert (b.kind == "baby shelf").all() and b.pct.between(48, 50.5).all(), b
assert b.tfirst.any() and not b.sfirst.any() and b.hit.any(), b
assert (pd.to_datetime(b.d).diff().dropna() >= pd.Timedelta(days=30)).all()                  # 같은 종목·목표 30일에 한 번
dn = by["BSDN"]
assert dn.sfirst.any() and not dn.tfirst.any(), dn
o = by["ONE"]
assert (o.kind == "$1").all() and o.pct.between(41, 43.5).all() and o.tfirst.any(), o
sp = by["SPLT"]
assert (sp.kind == "baby shelf").all() and sp.pct.between(48, 50.5).all(), sp                  # 병합 전 표지(1억 주)를 1/10 로 환산해야 시총 $5,000만 → 탈출가 $7.5
assert (sp.d < days[150]).any(), sp                                                            # 병합 전 날짜에도 사건이 잡힘
assert (ev.sv < 0.3).all()

# 표 만들기 · 토요일에만 다시 · 조회(작은 칸은 종류 × 변동성 줄)
with closing(db.connect()) as conn:
    r = pickrisk.build(conn, T, out=lambda *_: None)
    assert r["events"] == len(ev) and r["cells"] >= 4, r
    tab = pickrisk.table(conn)
    assert ("baby shelf", 0, -1) in tab and ("$1", 0, -1) in tab, tab
    sat = T + timedelta(days=(5 - T.weekday()) % 7 or 7)
    assert pickrisk.maybe_build(conn, sat - timedelta(days=1), out=lambda *_: None) is None or (sat - timedelta(days=1)).weekday() == 5
    assert pickrisk.maybe_build(conn, sat, out=lambda *_: None) is not None                    # 토요일 = 다시
    assert pickrisk.maybe_build(conn, sat, out=lambda *_: None) is None                        # 같은 날 두 번은 안 함
    lk = pickrisk.lookup(tab, "baby shelf", 0.1, 50)
    assert lk and lk["group"] == "baby shelf · 변동성 30%↓" and not lk["high_vol"] and lk["n"] == int((ev.kind == "baby shelf").sum()), lk
    conn.execute("INSERT OR REPLACE INTO pick_risk VALUES ('baby shelf', 2, 0, 80, 20.0, 55.0, -15.0, ?)", (T.isoformat(),)); conn.commit()
    tab = pickrisk.table(conn)
lk = pickrisk.lookup(tab, "baby shelf", 0.6, 45)
assert lk["group"] == "baby shelf · 변동성 50%↑ · +30~60%" and lk["high_vol"] and lk["score"] == -35.0 and lk["n"] == 80, lk
assert pickrisk.lookup(tab, "baby shelf", 0.6, 160) is None and pickrisk.lookup(tab, None, 0.1, 50) is None and pickrisk.lookup({}, "$1", 0.1, 50) is None
assert pickrisk.chip(lk) == "🎯20 · 📉55 ⚠️" and "과거 비슷한 PICK 80건" in pickrisk.label(lk) and "⚠️ 급락 위험" in pickrisk.label(lk)
assert pickrisk.kind_of("baby shelf 탈출") == "baby shelf" and pickrisk.kind_of("$1 상장 유지") == "$1" and pickrisk.kind_of("워런트 최저 행사가") is None
with closing(db.connect()) as conn:
    fr = pickrisk.for_row(conn, "BSUP", "baby shelf 탈출", 50.0)
assert fr and fr["vol"] < 30 and not fr["high_vol"], fr

# 유력·안전 순: 상태 → 목표 세기 → (목표 먼저 − −30% 먼저) 큰 순 · 표 없는 목표는 가운데 점수 · 유력·임박 순은 예전 그대로
mk = lambda t, st, weak, sc, imm=None: {"ticker": t, "status": st, "weak": weak, "imm_days": imm, "pressure": 3, "risk": None if sc is None else {"score": sc}}
rows = [mk("A", "대기", 1, -30), mk("B", "대기", 1, -1), mk("C", "대기", 1, -20), mk("D", "가능", 1, -40), mk("W", "대기", 0, None, 5), mk("E", "대기", 1, None, 3)]
assert [r["ticker"] for r in pick30.sort(rows, "유력·안전 순")] == ["D", "W", "B", "E", "C", "A"], [r["ticker"] for r in pick30.sort(rows, "유력·안전 순")]
assert [r["ticker"] for r in pick30.sort(rows, "유력·임박 순")] == ["D", "W", "E", "A", "B", "C"]

# 🏆 목표 먼저(−30% 전에): 먼저 닿은 쪽 · 같은 날 둘 다면 실패 · 손절 없으면 예전처럼
idx = pd.bdate_range("2026-01-05", periods=4)
def df(rows_):
    return pd.DataFrame(rows_, index=idx[:len(rows_)], columns=["High", "Low", "Close"])
base = [(1.0, 1.0, 1.0)]
assert scoreboard.outcome(df(base + [(1.6, 0.9, 1.5)]), "2026-01-05", 1.0, 60, 1, 50.0, 30.0)["status"] == "성공"
assert scoreboard.outcome(df(base + [(1.1, 0.65, 0.7), (1.6, 0.7, 1.5)]), "2026-01-05", 1.0, 60, 1, 50.0, 30.0)["status"] == "실패"
assert scoreboard.outcome(df(base + [(1.6, 0.65, 1.0)]), "2026-01-05", 1.0, 60, 1, 50.0, 30.0)["status"] == "실패"
assert scoreboard.outcome(df(base + [(1.6, 0.65, 1.0)]), "2026-01-05", 1.0, 60, 1, 50.0)["status"] == "성공"             # 손절 없는 예전 판정
assert scoreboard.outcome(df(base + [(1.1, 0.9, 1.0)] * 3), "2026-01-05", 1.0, 3, 1, 50.0, 30.0)["status"] == "실패"   # 기간 끝 · 둘 다 안 닿음
assert scoreboard.outcome(df(base + [(1.1, 0.9, 1.0)] * 3), "2026-01-05", 1.0, 60, 1, 50.0, 30.0)["status"] == "대기"
assert scoreboard.STOP["pick_bs_tf"] == 30.0 and scoreboard.SOURCES["pick_bs_tf"][3] == 60

# 기록: 예전 pick_signals(8칸)에 tf_p·sf_p 칸을 더해 그날 값 저장 → 🏆 는 같은 신호를 닿음/목표 먼저 두 줄로
with closing(db.connect()) as conn:
    conn.execute(pick30.LOG_DDL)
    conn.execute("INSERT INTO pick_signals VALUES ('2026-01-02', 'OLD', '$1 상장 유지', 1.0, 0.6, 67.0, '대기', 0)")
    p = {"ticker": "BSUP", "price": 2.0, "target": 3.0, "target_name": "baby shelf 탈출", "pct": 50.0, "status": "대기", "weak": True, "risk": {"tf": 14.4, "sf": 14.7}}
    assert pick30.record(conn, {"pass": [p]}, T) == 1
    got = conn.execute("SELECT tf_p, sf_p FROM pick_signals WHERE ticker='BSUP'").fetchone()
    assert tuple(got) == (14.4, 14.7), tuple(got)
    assert conn.execute("SELECT tf_p FROM pick_signals WHERE ticker='OLD'").fetchone()[0] is None
    c = scoreboard.collect(conn)
assert {"pick_bs", "pick_bs_tf", "pick_strong", "pick_strong_tf"} <= set(c["source"]), set(c["source"])
assert (c[c.source == "pick_bs_tf"].target == 50.0).all()

# 화면: 칩 셋째 줄 · 변동성 50%↑ 빨강 · 표(📉 과거 비슷한 PICK 결과)
import pick30_ui
g = pick30_ui.grid([{"ticker": "BSUP", "status": "대기", "weak": True, "pct": 50.0, "imm_days": None, "risk": lk},
                    {"ticker": "WAR", "status": "대기", "weak": False, "pct": 60.0, "imm_days": None, "risk": None}], guest=False)
assert '<div class="l3 hv"' in g and "🎯20 · 📉55 ⚠️" in g and g.count('class="l3') == 1, g
from streamlit.testing.v1 import AppTest
at = AppTest.from_string(
    "import pick30_ui\n"
    "lk = {'tf': 20.0, 'sf': 55.0, 'med': -15.0, 'n': 80, 'score': -35.0, 'vol': 62.0, 'high_vol': True, 'group': 'baby shelf · 변동성 50%↑ · +30~60%', 'built': '2026-11-07'}\n"
    "pick30_ui.risk_box([{'ticker': 'BSUP', 'status': '대기', 'weak': True, 'target_name': 'baby shelf 탈출', 'pct': 50.0, 'risk': lk},"
    " {'ticker': 'WAR', 'status': '대기', 'weak': False, 'target_name': '워런트 최저 행사가', 'pct': 60.0, 'risk': None}])\n", default_timeout=60).run()
assert not at.exception, [e.value for e in at.exception]
t = at.dataframe[0].value
assert list(t["티커"]) == ["BSUP"] and t.loc[0, "−30% 먼저(%)"] == 55.0 and t.loc[0, "묶음"].endswith("⚠️"), t
assert any("표 만든 날 2026-11-07" in x.value for x in at.caption) and any("양쪽을 같이" in x.value for x in at.caption)
print("ALL OK")
