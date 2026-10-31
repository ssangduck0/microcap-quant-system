"""⭐ 검증 순위 보류 규칙(2026-10-31 개선 U1·U2): 🟢 조용한 장세 날 · 1년 조달 서류 4건↑(상습 조달)이면 1·2순위를 보류(⏸) — 기록은 하되 🏆 에선 따로 검증."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import db, setup3 as s3, secbackfill, presim, scoreboard as sb

db.init_db()
T = date.today()


def bars(close, start="2025-01-02"):
    idx = pd.bdate_range(start=start, periods=len(close))
    c = np.asarray(close, float)
    return pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": np.full(len(c), 1e5)}, index=idx)


deep = bars(np.linspace(2.0, 0.5, 60))     # 계속 내려 RSI 매우 낮음 → 희석 없으면 1순위

with closing(db.connect()) as conn:
    for d_ in secbackfill.DDL:
        conn.execute(d_)
    conn.execute(presim.REGIME_DDL)
    # 희석 없음(③)이려면 공시 이력은 있어야 함 — 오래된(100일↑) 조달 서류 4건은 ③ 은 통과하지만 1년 안이라 상습 조달
    for i, d in enumerate((100, 150, 200, 300)):
        conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES (?, 'HAB', ?, ?, '')", (f"h{i}", ("424B5", "S-3", "424B4", "S-1")[i], (T - timedelta(days=d)).isoformat()))
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('h9', 'HAB', '8-K', ?, '7.01')", ((T - timedelta(days=120)).isoformat(),))   # 조달 아님
    for i, d in enumerate((100, 200, 400)):   # 1년 안 2건 + 400일 전(제외) → 상습 아님
        conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES (?, 'CLN', ?, ?, '')", (f"c{i}", "424B5", (T - timedelta(days=d)).isoformat()))
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('c8', 'CLN', '8-K', ?, '1.01,3.02')", ((T - timedelta(days=250)).isoformat(),))   # 8-K 3.02 도 조달
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('c9', 'CLN', '10-Q', ?, '')", ((T - timedelta(days=95)).isoformat(),))
    conn.commit()

    # 상습 조달 수
    assert s3.habit_count("HAB", conn) == 4 and s3.habit_count("hab", conn) == 4, s3.habit_count("HAB", conn)
    assert s3.habit_count("CLN", conn) == 3                                              # 424B5 2건(1년 안) + 8-K 3.02
    assert s3.habit_count("HAB", conn, as_of=(T - timedelta(days=150)).isoformat()) == 2   # 그날 전 1년만(컨닝 없음) · 접수 당일 제외
    assert s3.habit_count("NONE", conn) == 0

    # 장세: 날짜별 표에서 그날 이전 가장 가까운 날
    for d, lt in ((T - timedelta(days=30), "red"), (T - timedelta(days=10), "green"), (T - timedelta(days=3), "yellow")):
        conn.execute("INSERT INTO presim_regime (date, points, light, vix, src, at) VALUES (?, 0, ?, 20, 't', 'x')", (d.isoformat(), lt))
    conn.commit()
    assert s3.regime_light(conn, (T - timedelta(days=12)).isoformat()) == "red"
    assert s3.regime_light(conn, (T - timedelta(days=10)).isoformat()) == "green"
    assert s3.regime_light(conn, (T - timedelta(days=60)).isoformat()) is None
    assert s3.regime_light(conn) == "yellow"                                               # 🚦 지금 장세(meta) 없으면 표의 최신
    db.set_meta("regime", json.dumps({"light": "green", "points": 1}))
    assert s3.regime_light(conn) == "green" and s3.regime_light() == "green"               # 지금 장세(🚦 meta) 우선
    assert s3.regime_light(conn, (T - timedelta(days=3)).isoformat()) == "yellow"         # 과거 날짜는 표만(지금 장세로 덮지 않음)

    # 보류 이유
    assert s3.tier_hold("CLN", 1, conn, light="green") == "🟢 조용한 장세"
    assert s3.tier_hold("CLN", 2, conn, light="red") == ""
    assert s3.tier_hold("HAB", 1, conn, light="yellow") == "상습 조달(1년 4번)"
    assert s3.tier_hold("HAB", 2, conn, light="green") == "🟢 조용한 장세 · 상습 조달(1년 4번)"
    assert s3.tier_hold("HAB", 3, conn, light="green") == "" and s3.tier_hold("HAB", None, conn, light="green") == ""   # 3순위(참고)·순위 없음은 그대로
    assert s3.tier_hold("CLN", 1, None, light="green") == ""

    # evaluate: 🟢 장세면 1순위 → 보류(순위 없음 · 원래 순위·이유는 남김)
    ev = s3.evaluate("CLN", deep, conn)
    assert ev["tier_raw"] == 1 and ev["tier"] is None and ev["tier_hold"] == "🟢 조용한 장세", ev
    assert ev["tier_name"].startswith("⏸ 보류 · ") and s3.TIER_NAMES[1] in ev["tier_name"] and ev["tier_name"].endswith("🟢 조용한 장세")
    ev2 = s3.evaluate("CLN", deep, conn, light="red")
    assert ev2["tier"] == 1 and ev2["tier_hold"] == "" and ev2["tier_name"] == s3.TIER_NAMES[1]
    ev3 = s3.evaluate("CLN", deep, conn, as_of=(T - timedelta(days=3)).isoformat())        # 과거 날(🟡 · 지금 🟢 장세로 덮지 않음) → 보류 아님
    assert ev3["tier"] == 1 and not ev3["tier_hold"], ev3
    assert s3.evaluate("CLN", deep, None)["tier"] is None                                   # DB 없으면 ③ 모름 → 순위 없음(보류도 없음)

    # scan: 장세는 한 번만 읽고 모든 종목에 같게
    db.set_meta("regime", json.dumps({"light": "red", "points": 5}))
    rows = s3.scan(conn, {"CLN": deep, "HAB": deep}, ["CLN", "HAB"])
    by = {r["ticker"]: r for r in rows}
    assert by["CLN"]["tier"] == 1 and by["HAB"]["tier"] is None and by["HAB"]["tier_hold"] == "상습 조달(1년 4번)", by
    assert rows[0]["ticker"] == "CLN"                                                       # 정상 1순위가 보류보다 먼저

    # record_tiers: 보류도 이유와 함께 기록 · 옛 표(hold 칸 없음)에 칸 추가
    conn.execute("CREATE TABLE IF NOT EXISTS s3_tier_signals (date TEXT, ticker TEXT, price REAL, tier INTEGER, rsi REAL, note TEXT, PRIMARY KEY (date, ticker))")
    conn.execute("INSERT INTO s3_tier_signals VALUES ('2020-01-01', 'OLD', 1.0, 2, 22.0, 'x')")
    conn.commit()
    assert s3.record_tiers(conn, rows) == 2 and s3.record_tiers(conn, rows) == 0
    got = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT ticker, tier, hold FROM s3_tier_signals")}
    assert got["CLN"] == (1, None) and got["HAB"] == (1, "상습 조달(1년 4번)") and got["OLD"] == (2, None), got
    old = [{"ticker": "OLDROW", "tier": 2, "price": 1.0, "support": {"rsi": 23.0}, "dilution": {"label": "희석 없음"}}]   # 예전 형식 행(tier_raw 없음)
    assert s3.record_tiers(conn, old) == 1

    # 🏆 성과 공표: 보류 1·2순위는 s3_h1/s3_h2 로 따로
    col = sb.collect(conn)
    srcs = dict(zip(col["ticker"], col["source"]))
    assert srcs["CLN"] == "s3_t1" and srcs["HAB"] == "s3_h1" and srcs["OLD"] == "s3_t2" and srcs["OLDROW"] == "s3_t2", srcs
    assert "보류: 상습 조달" in col[col["ticker"] == "HAB"].iloc[0]["note"]
    assert "s3_h1" in sb.SOURCES and "낮아야 맞음" in sb.SOURCES["s3_h2"][0]

    # 🤖 AI PICK · 외부 알림은 보류 신호를 쓰지 않음
    import aipick, extalert, inspect
    it = extalert.interest(conn)
    assert "CLN" in it and "HAB" not in it, it
    assert "not_held(conn)" in inspect.getsource(aipick.brief)
    assert s3.not_held(conn) == " AND COALESCE(hold,'')=''"
    with closing(db.connect()) as c2:                                                     # 옛 표(hold 칸 없음 · 배포 뒤 첫 아침 갱신 전)도 그대로 읽힘
        c2.execute("CREATE TEMP TABLE s3_tier_signals (date TEXT, ticker TEXT, price REAL, tier INTEGER, rsi REAL, note TEXT)")
        assert s3.not_held(c2) == ""

# ✅ 3대 조건 화면: 보류 카드 · 규칙 안내 · 검증 순위 보기에 회색(⏸)으로
from streamlit.testing.v1 import AppTest
app = os.path.join(tmp, "s3_app.py")
with open(app, "w", encoding="utf-8") as f:
    f.write(f"""import sys; sys.path.insert(0, {os.environ['QS_ROOT']!r})
import setup3_ui, setup3 as s3, numpy as np, pandas as pd
from contextlib import closing
import db
idx = pd.bdate_range(start='2025-01-02', periods=60); c = np.linspace(2.0, 0.5, 60)
deep = pd.DataFrame({{'Open': c, 'High': c * 1.02, 'Low': c * 0.98, 'Close': c, 'Volume': np.full(60, 1e5)}}, index=idx)
def fake():
    with closing(db.connect()) as conn:
        return s3.scan(conn, {{'CLN': deep, 'HAB': deep}}, ['CLN', 'HAB'])
setup3_ui._scan_cached = fake
setup3_ui.render_now()
""")
db.set_meta("regime", json.dumps({"light": "green", "points": 1}))
at = AppTest.from_file(app, default_timeout=60).run()
assert not at.exception, at.exception
md = " ".join(m.value for m in at.markdown)
cap = " ".join(c.value for c in at.caption)
assert "⏸ 보류" in md and "🟢 장세·상습 조달" in md, md[:500]
assert "보류 규칙" in cap and "🟢 조용함 — 1·2순위 보류 중" in cap, cap[:500]
assert at.radio[0].value.startswith("검증")                                                 # 보류만 있어도 검증 순위 보기가 기본
print("ALL OK")
