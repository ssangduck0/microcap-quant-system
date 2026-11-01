"""종목을 고르는 표 — 표에서 종목을 고르면 그 종목 상세가 아래에 열린다(검색 대신).
2026-11-02(사용자 '눌리는 표는 전부 바꿔 줘'): 안 눌리는 표(ui_table) + 표 바로 아래 '📄 종목 고르기' — 예전엔 행을 누르면 빨간 선택 테두리.
관리 모드 '📋 표 모양' old 면 예전처럼 행을 눌러 고름."""
import pandas as pd
import streamlit as st


def _open(cur, popup: bool, popup_focus: str | None) -> None:
    if popup and cur:  # 종목을 고르면 상세정보(대시보드 기본 동작)
        try:
            import report_dialog
            report_dialog.open_report(str(cur).split("|")[0], popup_focus)
        except Exception:  # noqa: BLE001
            pass


def _clickable_old(df: pd.DataFrame, ids: list, key: str, popup: bool, popup_focus: str | None, **kwargs):
    import ui_table as utb
    sk = f"{key}_pick"
    ev = utb._orig()(df, on_select="rerun", selection_mode="single-row", key=key, **kwargs)
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
    if fresh:
        _open(cur, popup, popup_focus)
    return cur


def clickable(df: pd.DataFrame, ids: list, key: str, popup: bool = True, popup_focus: str | None = None, **kwargs):
    """df 를 그리고, 고른 종목의 id 를 돌려준다(아직 안 골랐으면 첫 행). 고른 id 는 session_state[f"{key}_pick"] 에 기억해서
    필터가 바뀌어도(목록에 남아 있으면) 유지된다 — 테스트·다른 화면이 그 값을 바꾸면 아래 선택도 따라감."""
    import ui_table as utb
    if utb._style() == "old":
        return _clickable_old(df, ids, key, popup, popup_focus, **kwargs)
    ids = list(ids)
    sk, skey, pkey = f"{key}_pick", f"{key}_sel", f"{key}_sel_prev"
    utb.frame(df, key=key, **{k: v for k, v in kwargs.items() if k in ("column_config", "column_order", "hide_index")})
    cur = st.session_state.get(sk)
    v = st.session_state.get(skey)
    fresh = v is not None and v in ids and v != st.session_state.get(pkey)   # 사용자가 아래 선택에서 새로 고름
    if fresh:
        cur = v
    if cur not in ids:
        cur = ids[0] if ids else None
    st.session_state[sk] = cur
    if ids:
        if st.session_state.get(skey) != cur:   # 다른 곳에서 고른 종목(테스트·이전 선택)에 맞춤 — 위젯을 만들기 전이라 바꿀 수 있음
            st.session_state[skey] = cur
        st.selectbox("📄 종목 고르기(상세 리포트)", ids, key=skey, format_func=lambda x: str(x).split("|")[0])
    st.session_state[pkey] = cur
    st.caption("👆 위 '📄 종목 고르기'에서 종목을 고르면 상세 리포트 창이 뜨고, 아래에도 열립니다." + (f" 지금 보는 종목: **{str(cur).split('|')[0]}**" if cur else ""))
    if fresh:
        _open(cur, popup, popup_focus)
    return cur
