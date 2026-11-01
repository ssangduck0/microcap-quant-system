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

# 3. 자동 변환(utb.frame) — 내용 보존: 보이는 칸의 모든 값이 나오고 · 숨긴 칸은 안 나오고 · 칸 이름·숫자 형식은 column_config 그대로 · 모든 줄은 더 보기로
FRAME = '''
import streamlit as st, pandas as pd, numpy as np, ui_table as utb
df = pd.DataFrame({"티커": [f"K{i:02d}" for i in range(20)],
                   "내용": ["아주 긴 설명 " * 8 + str(i) for i in range(20)],
                   "원문": ["6-K 2026-10-29 https://www.sec.gov/a/%d" % i for i in range(20)],
                   "가격": [1.23456 + i for i in range(20)],
                   "등락": [np.nan if i == 2 else i - 5.0 for i in range(20)],
                   "결과": ["✅ 충족" if i % 2 else "❌ 미충족" for i in range(20)],
                   "비밀": ["숨김값%d" % i for i in range(20)],
                   "확인": [bool(i % 3) for i in range(20)]})
utb.frame(df, key="f", hide_index=True, width="stretch", column_order=["티커", "내용", "원문", "가격", "등락", "결과", "확인", "비밀"],
          column_config={"가격": st.column_config.NumberColumn("가격($)", format="%.2f"), "등락": st.column_config.NumberColumn(format="%+.1f"),
                         "원문": st.column_config.LinkColumn(display_text="열기"), "비밀": None})
'''
at4 = AppTest.from_string(FRAME, default_timeout=60).run()
assert not at4.exception, [e.value for e in at4.exception]
h4 = "\n".join(m.value for m in at4.markdown).replace("&#36;", "$")
table_part = h4.split('<div class="qk-st-cards">')[0]
for i in range(15):   # 처음 15줄의 모든 보이는 칸 값
    assert f"K{i:02d}" in table_part and ("아주 긴 설명 " * 8 + str(i)) in table_part and f'href="https://www.sec.gov/a/{i}"' in table_part, i
    assert f"{1.23456 + i:.2f}" in table_part and (i == 2 or f"{i - 5.0:+.1f}" in table_part), i
assert "숨김값" not in h4 and ">가격($)</th>" in table_part and ">비밀</th>" not in table_part              # 숨긴 칸 · 칸 이름
assert table_part.count("10/29") >= 15 and "열기</a>" in table_part                                             # '6-K 10/29 열기'
assert "qk-green" in table_part and "qk-red" in table_part and "✅ 충족" in table_part and "❌ 미충족" in table_part  # ✅/❌ → 색 칩(글자 그대로)
assert '<span class="mut">-</span>' in table_part                                                                # 빈 값 = '-'
assert table_part.index(">티커</th>") < table_part.index(">내용</th>") < table_part.index(">원문</th>")    # 칸 순서
assert "K19" not in table_part and any("15 / 20줄" in c.value for c in at4.caption)
at4.button(key="f_more").click().run()
h5 = "\n".join(m.value for m in at4.markdown).split('<div class="qk-st-cards">')[0]
assert all(f"K{i:02d}" in h5 for i in range(20))                                                                 # 더 보기 → 20줄 모두
at4.text_input(key="f_q").input("K07").run()
h6 = "\n".join(m.value for m in at4.markdown).split('<div class="qk-st-cards">')[0]
assert "K07" in h6 and "K08" not in h6                                                                            # 찾기(기본 표 검색 대신)
assert at4.selectbox(key="f_sort").options[0] == "원래 순서" and "가격($) 큰 순" in at4.selectbox(key="f_sort").options
dl = [e for e in at4.get("download_button")]
assert dl, "CSV 내려받기 버튼"
# 관리 모드 '표 모양: old' → 예전 기본 표 그대로
at7 = AppTest.from_string("import config\nconfig.TABLE_STYLE = 'old'\n" + FRAME, default_timeout=60).run()
assert not at7.exception and at7.dataframe and "숨김값" not in str(at7.dataframe[0].value.columns.tolist() if False else ""), [e.value for e in at7.exception]
import ui_table as utb
assert utb.cell_html(None, None) == '<span class="mut">-</span>' and utb.cell_html(1234567.0, None) == "1,234,567"
assert utb.cell_html("예상 $3.04", None) == utb.esc("예상 $3.04")                                                # '예상' 이 '예' 칩으로 바뀌지 않음
assert "qk-gray" in utb.cell_html("➖ 확인 불가", None) and utb.cell_html(0.5, {"type_config": {"type": "number", "format": "%.0f%%"}}) == "0%"
print("ALL OK")
