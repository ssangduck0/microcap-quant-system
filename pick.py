"""행을 눌러 고르는 표 — 표에서 행을 누르면 그 종목 상세가 아래에 열린다(검색 대신 클릭)."""
import pandas as pd
import streamlit as st


def clickable(df: pd.DataFrame, ids: list, key: str, popup: bool = True, popup_focus: str | None = None, **kwargs):
    """df 를 그리고, 사용자가 누른 행의 id(ids[행 위치])를 돌려준다. 아직 안 눌렀으면 첫 행.
    고른 id 는 session_state[f"{key}_pick"] 에 기억해서 필터가 바뀌어도(목록에 남아 있으면) 유지된다."""
    sk = f"{key}_pick"
    ev = st.dataframe(df, on_select="rerun", selection_mode="single-row", key=key, **kwargs)
    try:
        rows = list(ev.selection.rows)
    except Exception:  # noqa: BLE001  (선택 기능이 없는 오래된 Streamlit)
        rows = []
    lk = f"{key}_last_rows"
    # 표의 선택 상태는 '몇 번째 행'으로 남아 있어서, 정렬·필터로 순서가 바뀌면 다른 종목을 가리킨다.
    # 그래서 사용자가 새로 누른 경우(선택이 바뀐 경우)에만 종목을 바꾸고, 그 외에는 보던 종목을 유지한다.
    fresh = bool(rows and rows != st.session_state.get(lk) and rows[0] < len(ids))
    if fresh:
        st.session_state[sk] = ids[rows[0]]
    st.session_state[lk] = rows
    cur = st.session_state.get(sk)
    if cur not in ids:
        cur = ids[0] if ids else None
        st.session_state[sk] = cur
    st.caption("👆 표에서 **행을 누르면** 📄 상세 리포트 창이 뜨고, 아래에도 열립니다." + (f" 지금 보는 종목: **{str(cur).split('|')[0]}**" if cur else ""))
    if fresh and popup and cur:  # 티커를 누르면 상세정보(대시보드 기본 동작)
        try:
            import report_dialog
            report_dialog.open_report(str(cur).split("|")[0], popup_focus)
        except Exception:  # noqa: BLE001
            pass
    return cur
