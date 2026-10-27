"""화면 없이 도는 프로그램(스캐너·아침 갱신·이벤트 수집기)에서 Streamlit 경고 줄을 끈다.

화면용 모듈(@st.cache_data 등)을 불러오면 'missing ScriptRunContext' 경고가 로그에 수백 줄씩 쌓여 실제 기록을 읽기 어려웠다.
가장 먼저 import 하면 된다: import quiet  # noqa: F401
"""
import logging
import os

os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")


class _NoStreamlitWarnings(logging.Filter):
    def filter(self, rec: logging.LogRecord) -> bool:  # noqa: D102
        return not (rec.name.startswith("streamlit") and rec.levelno < logging.ERROR)


logging.getLogger().addFilter(_NoStreamlitWarnings())
for _h in logging.getLogger().handlers:
    _h.addFilter(_NoStreamlitWarnings())
try:
    import streamlit.logger as _stl
    _stl.set_log_level("error")
except Exception:  # noqa: BLE001
    pass
