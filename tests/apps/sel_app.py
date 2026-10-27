import streamlit as st, pandas as pd
df = pd.DataFrame({"티커": ["AAA", "BBB", "CCC"], "x": [1, 2, 3]})
ev = st.dataframe(df, on_select="rerun", selection_mode="single-row", key="t1", hide_index=True)
rows = ev.selection.rows if ev is not None and hasattr(ev, "selection") else []
if rows:
    st.session_state["t1_ticker"] = df["티커"].iloc[rows[0]]
st.write("picked:", st.session_state.get("t1_ticker", df["티커"].iloc[0]))
