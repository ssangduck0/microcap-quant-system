import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import datetime, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np
import pandas as pd
import db, presim, presim_ui, rank as _rank
db.init_db()
presim.MIN_EP = 20

# 가짜 일봉 2년치(daily_prices) + 오늘 순위 1위 → 아침 자동 실행 → presim_log
days = pd.bdate_range("2024-09-02", periods=560)
r = np.random.default_rng(5)
rets = r.normal(0.0, 0.03, len(days)); rets = rets - rets.mean()
c = 2.0 * np.cumprod(1 + rets)
bars = pd.DataFrame({"Open": c, "High": c * (1 + np.abs(r.normal(0, 0.02, len(days)))), "Low": c * (1 - np.abs(r.normal(0, 0.02, len(days)))), "Close": c, "Volume": 200_000.0}, index=days)
TODAY = days[-1].strftime("%Y-%m-%d")
with closing(db.connect()) as conn:
    conn.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)",
                     [("AAA", d.strftime("%Y-%m-%d"), float(o), float(h), float(l), float(cl), 200_000.0) for d, o, h, l, cl in zip(days, bars["Open"], bars["High"], bars["Low"], bars["Close"])])
    conn.execute(_rank.HIST_DDL)
    conn.execute("INSERT INTO rank_hist VALUES (?,?,?,?,?)", (TODAY, "AAA", 1, 90.0, 1))
    conn.commit()
    m = presim.morning(conn, out=lambda *_: None, bars={"AAA": bars}, n_sim=800, now=datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc))
    assert m["done"] == 1, m
    row = conn.execute("SELECT * FROM presim_log WHERE ticker='AAA'").fetchone()
    assert row["source"] == "rank" and row["verdict"] in "🟢🪙🔴" and row["horizon"] == 40 and row["n_ep"] >= 20, dict(row)
    # 🏆 성과 공표 출처: 판정에 따라 presim_g/c/r 하나 · 목표 +30% · 40거래일 · 진입가 = 매수가
    import scoreboard as sb
    col = sb.collect(conn)
    ps = col[col["source"].str.startswith("presim_")]
    assert len(ps) == 1 and ps.iloc[0]["ticker"] == "AAA" and ps.iloc[0]["target"] == 30.0 and ps.iloc[0]["horizon"] == 40 and abs(ps.iloc[0]["entry"] - row["entry"]) < 1e-9, ps
    assert ps.iloc[0]["source"] == {"🟢": "presim_g", "🪙": "presim_c", "🔴": "presim_r"}[row["verdict"]] and "익절" in ps.iloc[0]["note"]
    assert "🔴 불리(낮아야 맞음)" in sb.SOURCES["presim_r"][0]

# 배지
DAYS_AGO = (datetime.now(timezone.utc).date() - days[-1].date()).days + 2
bd = presim_ui.badges(["AAA", "NOPE"], days=DAYS_AGO)
assert set(bd) == {"AAA"} and presim_ui.badge_text(bd["AAA"]).startswith(row["verdict"]) and "익절" in presim_ui.badge_text(bd["AAA"])
chip = presim_ui.badge_chip("AAA", bd)
assert "🎲" in chip and row["verdict"] in chip and "qk-chip" in chip and presim_ui.badge_chip("NOPE", bd) == "" and presim_ui.badge_text(None) == ""

# 화면 ⑥(관리자): 오늘 자동 결과 안내 · 기본값 입력칸 · 버튼 → 결과(확률 4칸 · 수량 · 경고) · 제외 사유가 있으면 빨간 경고
from streamlit.testing.v1 import AppTest
def _app():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import presim, presim_ui
    presim.MIN_EP = 20
    presim_ui.render_section("AAA", {"exclusion": ["ATM 증자 활성"]})
at = AppTest.from_function(_app, default_timeout=180).run()
assert not at.exception, [e.value for e in at.exception]
caps = " ".join(x.value for x in at.caption)
assert "오늘 자동 실행" in caps and "출처 rank" in caps, caps[:400]
assert at.number_input(key="ps_e_AAA").value == round(float(bars["Close"].iloc[-1]), 4)
assert 0 < at.number_input(key="ps_s_AAA").value < at.number_input(key="ps_e_AAA").value < at.number_input(key="ps_t_AAA").value
at.selectbox(key="ps_n_AAA").set_value(2000).run()
at.button(key="ps_go_AAA").click().run()
assert not at.exception, [e.value for e in at.exception]
labels = [x.label for x in at.metric]
assert "익절 먼저(같은 신호 과거)" in labels and "손절 먼저" in labels and "기대값(거래당)" in labels, labels
md = " ".join(x.value for x in at.markdown)
assert "**수량**" in md and ("🟢" in md or "🪙" in md or "🔴" in md), md[:600]
assert any("제외된 이유" in e.value for e in at.error)
caps2 = " ".join(x.value for x in at.caption)
assert "1겹" in caps2 and "2겹" in caps2 and presim.WARN in caps2, caps2[:800]

# 방문객: 입력칸·버튼 없이 자동 결과만
def _guest():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import streamlit as st
    st.session_state["_guest"] = True
    import presim_ui
    presim_ui.render_section("AAA", None)
ag = AppTest.from_function(_guest, default_timeout=180).run()
assert not ag.exception, [e.value for e in ag.exception]
assert not [b for b in ag.button if b.key == "ps_go_AAA"] and not ag.number_input
assert "오늘 자동 실행" in " ".join(x.value for x in ag.caption)

# 일봉이 없는 종목: 안내만
def _none():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import presim_ui
    presim_ui.render_section("ZZZZ", None)
an = AppTest.from_function(_none, default_timeout=120).run()
assert not an.exception and any("돌릴 수 없어요" in x.value for x in an.caption)
print("ALL OK")
