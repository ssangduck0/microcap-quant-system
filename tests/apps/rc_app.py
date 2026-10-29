import os, sys; sys.path.insert(0, os.environ["QS_ROOT"])
import pandas as pd
import streamlit as st
import market, ui_kit, company_ui
_df = pd.read_csv(os.environ["QUANT_RC_CSV"], index_col=0, parse_dates=True)
market.download_daily = lambda tk, period="3mo", chunk=200: {t: _df for t in tk}
if os.environ.get("QUANT_RC_GUEST") == "1":
    st.session_state["_guest"] = True
ui_kit.inject()
company_ui.render("WHLR")
