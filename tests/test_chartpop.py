import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🔍 차트 팝업: 넓은 표 → 긴 표 변환 · 키 정리 · '크게 보기' 버튼 → 팝업(큰 차트·숫자 표·CSV) · 같은 키 두 번 그려도 오류 없음 · 대시보드에 st.line_chart/bar_chart 가 남아 있지 않음."""
import os, sys, tempfile, re, glob
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import pandas as pd
import chartpop as cp

# 1) 넓은 표 → 긴 표
idx = pd.date_range("2026-10-01", periods=5)
long, xt, single = cp._long(pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [5, 4, 3, 2, 1]}, index=idx))
assert xt == "T" and not single and len(long) == 10 and set(long["계열"]) == {"a", "b"} and list(long.columns) == ["x", "계열", "값", "x순"]
long2, xt2, single2 = cp._long(pd.Series([3, 1, 2], index=["c", "a", "b"], name="점수"))
assert xt2 == "O" and single2 and list(long2["x"]) == ["c", "a", "b"]          # 순서 유지(정렬 안 함)
assert cp._slug("pt_cum_rank") == "pt_cum_rank" and cp._slug("sp_공매도 거래량").startswith("k") and cp._slug("1abc").startswith("k")
tb = cp._table(pd.Series([1.0, 2.0], index=idx[:2], name="v")); assert list(tb.columns) == ["index", "v"] and len(tb) == 2
assert cp._table(pd.DataFrame()) is None and cp._table(None) is None

# 2) 화면: 버튼 → 팝업 안에 표·CSV. 같은 키로 두 번 그려도 오류 없음(뒤에 번호)
APP = """
import os, sys; sys.path.insert(0, os.environ["QS_ROOT"])
import pandas as pd, streamlit as st, altair as alt
import chartpop as cp
s = pd.Series([1.0, 3.0, 2.0], index=pd.date_range("2026-10-01", periods=3), name="종가")
cp.line(s, key="t_line", title="테스트 선", height=100)
cp.line(s, key="t_line", title="테스트 선 2", height=100)
cp.bar(pd.Series({"가": 1, "나": 2}, name="n"), key="t_bar", title="테스트 막대", horizontal=True)
cp.show(alt.Chart(pd.DataFrame({"x": [1, 2], "y": [2, 1]})).mark_point().encode(x="x:Q", y="y:Q").interactive(), key="t_show", title="테스트 점", click=False)
"""
from streamlit.testing.v1 import AppTest
at = AppTest.from_string(APP, default_timeout=60).run(); assert not at.exception, [e.value for e in at.exception]
btns = [b for b in at.button if b.key.startswith("cp_btn_")]
assert {b.key for b in btns} >= {"cp_btn_t_line", "cp_btn_t_line_2", "cp_btn_t_bar", "cp_btn_t_show"}, [b.key for b in btns]
assert not at.dataframe                                                           # 팝업 전에는 표 없음
[b for b in btns if b.key == "cp_btn_t_line"][0].click().run(); assert not at.exception, [e.value for e in at.exception]
assert at.dataframe and list(at.dataframe[0].value.columns) == ["index", "종가"] and len(at.dataframe[0].value) == 3     # 팝업: 숫자 표
assert any("테스트 선" in m.value for m in at.markdown) and any(b.key == "cp_dl_t_line" for b in at.get("download_button"))   # 제목 · CSV
[b for b in at.button if b.key == "cp_btn_t_bar"][0].click().run(); assert not at.exception
assert any(list(d.value.columns) == ["index", "n"] for d in at.dataframe)

# 3) 대시보드 코드에 Streamlit 기본 차트가 남아 있지 않음(홈 시장 지표 macro_ui 는 제외 대상이지만 원래 Altair)
left = []
for f in glob.glob(os.path.join(os.environ["QS_ROOT"], "*.py")):
    if os.path.basename(f) in ("chartpop.py",):
        continue
    src = open(f, encoding="utf-8").read()
    for m in re.finditer(r"st\.(line_chart|bar_chart|area_chart|scatter_chart)\(", src):
        left.append((os.path.basename(f), m.group(1)))
    if os.path.basename(f) != "macro_ui.py":
        for m in re.finditer(r"\bst\.altair_chart\(", src):
            left.append((os.path.basename(f), "altair_chart"))
assert not left, left
print("ALL OK")
