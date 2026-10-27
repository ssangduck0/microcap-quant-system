import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys
src = open("test_fundscan.py").read().split("# 병합 환산")[0]
exec(compile(src, "fs_setup", "exec"))
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ["QUANT_TEST_PAGE"] = "fundscan"
import halts; halts.fetch = lambda *a, **k: []
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "추적 종목" in html and "주가 부양 유인 충족" in html and "SMSI" in html and "양면 신호 70" in html and "부양 유인" in html and "+26.7%" in html
at.toggle(key="fs_only").set_value(True).run(); assert "SMSI" in "\n".join(m.value for m in at.markdown)
at.text_input(key="fs_q").set_value("ZZZZ").run(); assert "SMSI" not in "\n".join(m.value for m in at.markdown if "qk-tk" in m.value)
os.environ.pop("QUANT_TEST_PAGE")
at = AppTest.from_file(__import__("os").path.join(__import__("tempfile").gettempdir(), "fsd_app.py"), default_timeout=120).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "주가 부양 유인 구간" in html and "워런트 행사 최소 주가" in html and "Series A @" in html and "프리펀디드 워런트" in html and "현금 버틸 기간" in html
assert any("구조적으로" in i.value for i in at.info)
assert any("원인 확인율" in m.value and "83.3%" in m.value for m in at.markdown) and any("H.C. Wainwright" in m.value for m in at.markdown)
print("ALL OK")
