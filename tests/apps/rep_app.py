import sys, json; sys.path.insert(0, __import__("os").environ["QS_ROOT"])
import ui_kit, alerts_ui, streamlit as st
ui_kit.inject()
r = json.loads(st.session_state.get("r", "{}")) if "r" in st.session_state else json.load(open(__import__("os").path.join(__import__("tempfile").gettempdir(), "rep_r.json")))
alerts_ui.render_report(r)
