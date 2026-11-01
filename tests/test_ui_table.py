import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""📋 안 눌리는 표(ui_table) — 표·카드 HTML · 글자 감싸기 · 정렬 선택 · 더 보기/접기 · 리포트 선택 + 📅 병합 예정 표(비율 모름 = '미확인', 예전 nan)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np
import pandas as pd
import db, watch
db.init_db(); watch.ensure_tables()
from streamlit.testing.v1 import AppTest

# 1. 부품: 20줄 · 처음 15줄 · 정렬 · 더 보기 · 리포트 선택 · 글자 감싸기
APP = '''
import streamlit as st, ui_table as utb
rows = [{"ticker": f"T{i:02d}", "v": i, "note": "<b>위험</b>" if i == 19 else f"줄 {i}"} for i in range(20)]
cols = [utb.Col("티커", lambda r: utb.esc(r["ticker"]), "20%"), utb.Col("값", lambda r: str(r["v"])), utb.Col("메모", lambda r: utb.esc(r["note"]))]
opened = []
order = utb.table(rows, cols, "k", sorts={"큰 값 순": lambda r: -r["v"], "작은 값 순": lambda r: r["v"]}, page=15, on_open=opened.append)
st.session_state["_order"] = [r["ticker"] for r in order]
st.session_state["_opened"] = opened
'''
at = AppTest.from_string(APP, default_timeout=60).run()
assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert '<div class="qk-st"><table>' in html and '<div class="qk-st-cards">' in html and "@media (max-width:768px)" in html
assert html.count("<tr>") == 1 + 15 and html.count('class="qk-st-card"') == 15, html.count("<tr>")   # 머리 + 15줄 · 카드도 15장
assert "&lt;b&gt;위험&lt;/b&gt;" in html and "<b>위험</b>" not in html                                  # 자료 글자는 감쌈
assert at.session_state["_order"][0] == "T19"                                                          # 기본 = 첫 정렬(큰 값 순)
assert any("15 / 20줄" in c.value for c in at.caption)
at.button(key="k_more").click().run()
html = "\n".join(m.value for m in at.markdown)
assert html.count("<tr>") == 1 + 20 and at.button(key="k_more").label == "접기"
at.button(key="k_more").click().run()
assert "\n".join(m.value for m in at.markdown).count("<tr>") == 16
at.selectbox(key="k_sort").set_value("작은 값 순").run()
assert at.session_state["_order"][:2] == ["T00", "T01"]
at.selectbox(key="k_open").set_value("T07").run()
assert at.session_state["_opened"] == ["T07"]
at2 = AppTest.from_string("import ui_table as utb\nutb.table([], [utb.Col('a', lambda r: '')], 'e', empty='비었어요')", default_timeout=30).run()
assert not at2.exception and any("비었어요" in c.value for c in at2.caption)

# 2. 📅 병합 예정 줄: 비율 있음(1:10 · 환산가) / 비율 모름(None — 예전 nan) / 7일 넘는 병합은 재이탈 '7일 안만 계산'
T = date.today()
days = [x.date().isoformat() for x in pd.bdate_range(end=T - timedelta(days=1), periods=80)]
with closing(db.connect()) as conn:
    conn.executemany("INSERT OR REPLACE INTO daily_prices (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
                     [(t, d, p, p, p, p * (1 + 0.02 * ((i % 3) - 1)), 1e5) for t, p in (("RAT", 0.3), ("NOR", 0.5), ("FAR", 0.4)) for i, d in enumerate(days)])
    conn.commit()
watch.add_event("RAT", (T + timedelta(days=2)).isoformat(), "역분할 시행", "1:10 역분할 시행")
watch.add_event("NOR", (T + timedelta(days=4)).isoformat(), "역분할 시행", "역분할 시행(비율 미정)")
watch.add_event("FAR", (T + timedelta(days=20)).isoformat(), "역분할 시행", "1:20 역분할 시행")
import rsplit_ui
with closing(db.connect()) as conn:
    rows = {r["ticker"]: r for r in rsplit_ui.upcoming_rows(conn)}
assert set(rows) == {"RAT", "NOR", "FAR"}, rows
assert rows["RAT"]["ratio"] == "1:10" and abs(rows["RAT"]["exp"] - 3.0) < 0.2 and rows["RAT"]["d"] == 2, rows["RAT"]
assert rows["NOR"]["ratio"] is None and rows["NOR"]["exp"] is None and rows["NOR"]["sh"] is None, rows["NOR"]      # nan 아님
cols, card = rsplit_ui._up_cells()
cell = {c.label: c.cell for c in cols}
assert cell["비율"](rows["NOR"]) == '<span class="mut">미확인</span>' and "비율을 몰라 계산 안 함" in cell["병합 뒤"](rows["NOR"])
assert "예상 $3." in cell["병합 뒤"](rows["RAT"]) and "D-2" in cell["시행일"](rows["RAT"]) and "qk-red" in cell["시행일"](rows["RAT"])
assert "7일 안만 계산" in cell["6개월 안 $1 아래"](rows["FAR"]) and "자료 부족" in cell["6개월 안 $1 아래"](rows["RAT"])   # 표(rs_risk)가 없으면 자료 부족
assert "tossinvest.com" in cell["티커"](rows["RAT"])
t, chip, sub = card(rows["NOR"])
assert "NOR" in t and "D-4" in chip and "미확인" in sub
at3 = AppTest.from_string("import rsplit_ui\nrsplit_ui.render_upcoming()", default_timeout=60).run()
assert not at3.exception, [e.value for e in at3.exception]
h3 = "\n".join(m.value for m in at3.markdown)
assert "RAT" in h3 and "nan" not in h3 and "미확인" in h3 and not at3.dataframe, h3[:500]                   # 기본 데이터 표 안 씀
print("ALL OK")
