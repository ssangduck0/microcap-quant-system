import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🔁 병합 체크포인트(rsrisk) — 재생(그날 실제 가격 환산 · 앞으로 120거래일 다 지난 것) · 표(거리÷변동성 × 상습 병합) · 지금 위험(병합 1년 안) ·
이미 $1 아래 · 병합 예정(예상가) · 이유 줄(병합 뒤 증자 · 1년 조달) · 토요일에만 다시 · 알림 '🚫 병합 예정' 꼬리 · 서랍 머리 값."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np
import pandas as pd
import db, rsplit, rsrisk
db.init_db()
T = date.today()
days = [x.date().isoformat() for x in pd.bdate_range(end=T - timedelta(days=1), periods=700)]
rng = np.random.default_rng(3)
prices, events = [], []
# 재생용 80종목: 병합(1:10) 뒤 실제 가격 $2~6 · 반은 서서히 $1 아래로, 반은 그대로 · 일봉은 지금 단위(병합 전도 ×10 환산돼 매끄러움) · 10종목은 1년 전에도 병합(상습)
for n in range(80):
    t = f"R{n:02d}"
    i0 = 200 + (n * 4) % 300
    base = 2 + (n % 5)
    down = n % 2 == 0
    cl = np.empty(len(days))
    for i in range(len(days)):
        lvl = base if i <= i0 else (base * max(0.15, 1 - (i - i0) / 150) if down else base)
        cl[i] = lvl * (1 + rng.normal(0, 0.02))
    prices += [(t, d, c) for d, c in zip(days, cl)]
    events.append((t, days[i0], 0.1, float(cl[i0])))
    if n < 10:
        events.append((t, days[i0 - 150], 0.1, float(cl[i0 - 150])))
# 지금 병합 1년 안: NEW1(30거래일 전 병합 · $1.6 로 내려오는 중) · NEW2(이미 $0.8) · 병합 예정 UPC($0.3 · 1:10 · 3일 뒤)
def path(a, b, n):
    return np.linspace(a, b, n) * (1 + rng.normal(0, 0.03, n))
for t, end in (("NEW1", 1.6), ("NEW2", 0.8)):
    cl = np.r_[np.full(len(days) - 31, 3.0) * (1 + rng.normal(0, 0.03, len(days) - 31)), path(3.0, end, 31)]
    prices += [(t, d, c) for d, c in zip(days, cl)]
    events.append((t, days[-31], 0.1, 3.0))
prices += [("UPC", d, c) for d, c in zip(days, 0.3 * (1 + rng.normal(0, 0.03, len(days))))]
with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn)
    conn.executemany("INSERT OR REPLACE INTO daily_prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                     [(t, d, c, c, c, c, 1e5) for t, d, c in prices])
    conn.executemany("INSERT OR REPLACE INTO rs_events VALUES (?,?,?,?)", events)
    conn.execute("CREATE TABLE IF NOT EXISTS sec_hist (accession TEXT PRIMARY KEY, ticker TEXT NOT NULL, form TEXT, filed TEXT, items TEXT)")
    conn.executemany("INSERT INTO sec_hist VALUES (?,?,?,?,?)", [("a1", "NEW1", "424B5", days[-10], ""), ("a2", "NEW1", "S-1", days[-200], ""),
                                                               ("a3", "NEW1", "8-K", days[-5], "3.02,9.01"), ("a4", "NEW1", "8-K", days[-6], "5.02"), ("a5", "NEW1", "424B5", days[-400], "")])
    conn.commit()
import watch
watch.ensure_tables(); watch.add_event("UPC", (T + timedelta(days=3)).isoformat(), "역분할 시행", "1:10 역분할 시행")
with closing(db.connect()) as conn:

    # 1. 재생 · 표
    ob = rsrisk.observations(conn, T)
    assert len(ob) >= 100 and set(ob.k) <= set(rsrisk.KS) and ob.y.any() and (~ob.y).any(), (len(ob), ob.y.mean())
    assert "NEW1" not in set(ob.t)                                   # 앞으로 120거래일이 안 지난 병합은 재생에서 뺌
    assert ob[ob.t == "R01"].y.sum() == 0 and ob[ob.t == "R00"].y.any()   # 그대로인 종목은 안 떨어짐 · 내려가는 종목은 떨어짐
    assert ob[ob.t.isin([f"R{n:02d}" for n in range(10)])].serial.eq(1).all() and ob[ob.t == "R10"].serial.eq(0).all()
    logs = []
    r = rsrisk.build(conn, T, out=logs.append)
    assert r["ok"] and "🔁 병합 체크포인트 표:" in logs[0], (r, logs)
    tab = rsrisk.table(conn)
    lo = [v[1] for (zb, se), v in tab.items() if se == -1 and zb == min(z for z, s in tab if s == -1)]
    hi = [v[1] for (zb, se), v in tab.items() if se == -1 and zb == max(z for z, s in tab if s == -1)]
    assert lo[0] > hi[0], tab                                        # 가까울수록(거리÷변동성 작을수록) 더 자주 $1 아래
    assert rsrisk.lookup({(1, 1): (5, 90.0), (1, -1): (40, 30.0)}, 0.7, True) == 30.0      # 칸이 작으면 합친 줄
    assert rsrisk.lookup({(1, 1): (25, 90.0), (1, -1): (40, 30.0)}, 0.7, True) == 90.0
    assert rsrisk.lookup({}, 0.7, False) is None
    # 2. 토요일에만 다시
    sat = T + timedelta(days=(5 - T.weekday()) % 7 or 7)
    assert rsrisk.maybe_build(conn, sat - timedelta(days=1), out=lambda *_: None) is None or (sat - timedelta(days=1)).weekday() == 5
    assert rsrisk.maybe_build(conn, sat, out=lambda *_: None) is not None and rsrisk.maybe_build(conn, sat, out=lambda *_: None) is None

    # 3. 지금 위험(병합 1년 안)
    n1 = rsrisk.current(conn, "NEW1", T)
    assert n1 and n1["days"] == 30 and n1["rs_date"] == days[-31] and not n1["below"] and n1["prob"] is not None and n1["serial"] == 0, n1
    assert n1["off_after"] == 2 and n1["fin_1y"] == 1, n1            # 병합 뒤 424B5 + 8-K 3.02 · 병합 전 1년 S-1(1년 넘은 424B5 · 8-K 5.02 는 안 셈)
    c1 = rsrisk.chip(n1)
    assert c1[0].startswith("🔁 병합 30일째 · 6개월 안 $1 아래 약 ") and c1[1] == ("red" if n1["prob"] >= 30 else "orange"), c1
    rl = rsrisk.reason_line(n1)
    assert "지금가 $1." in rl and "병합 뒤 증자 서류 2건" in rl and "병합 전 1년 조달 서류 1건" in rl, rl
    n2 = rsrisk.current(conn, "NEW2", T)
    assert n2["below"] and n2["prob"] is None and rsrisk.chip(n2) == ("🔁 병합 30일째 · 이미 $1 아래", "red"), n2
    assert rsrisk.current(conn, "R01", T) is None and rsrisk.current(conn, "ZZZ", T) is None   # 1년 넘은 병합 · 없는 종목
    assert rsrisk.short(n2) == "🔁 병합 30일째 · 이미 $1 아래" and rsrisk.short(None) == ""
    # 4. 병합 예정(7일 안 · 1:10) → 예상가 $3 · 같은 표
    u = rsrisk.upcoming(conn, "UPC", T)
    assert u and u["ratio"] == 10 and abs(u["exp_price"] - 3.0) < 0.3 and u["prob"] is not None and u["d"] == 3, u
    tail = rsrisk.upcoming_tail(u)
    assert tail.startswith(" · 병합 뒤 예상 $") and "→ 6개월 안 $1 아래 약 " in tail, tail
    fl = rsplit.flag_line(conn, "UPC", T)
    assert fl.startswith("🚫 병합 예정 D-3(") and fl.endswith(tail), fl
    assert rsrisk.upcoming(conn, "NEW1", T) is None and rsrisk.upcoming_tail(None) == ""
    # 5. 서랍 머리 값
    import drawer
    hd = drawer.headline(conn, "NEW1")
    assert hd["rs_risk"]["days"] == 30 and hd["rs_up"] is None, hd.get("rs_risk")
    hu = drawer.headline(conn, "UPC")
    assert hu["rs_soon"] and hu["rs_up"]["ratio"] == 10 and hu["rs_risk"] is None

# 6. 서랍 머리 칩(화면)
from streamlit.testing.v1 import AppTest
at = AppTest.from_string(
    "import report_dialog, drawer, db\n"
    "from contextlib import closing\n"
    "with closing(db.connect()) as c:\n"
    "    hd = drawer.headline(c, 'NEW1'); hu = drawer.headline(c, 'UPC')\n"
    "report_dialog._head('NEW1', {'name': 'New One'}, hd, [], '')\n"
    "report_dialog._head('UPC', {'name': 'Upcoming'}, hu, [], '')\n", default_timeout=60).run()
assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown).replace("&#36;", "$")   # 화면은 $ 를 &#36; 로 씀
assert "🔁 병합 30일째 · 6개월 안 $1 아래 약 " in html and "병합 뒤 증자 서류 2건" in html and "유예 없이 상장폐지 결정" in html, html[:1500]
assert "🚫 병합 예정" in html and "🔁 병합 뒤 예상 $" in html
print("ALL OK")
