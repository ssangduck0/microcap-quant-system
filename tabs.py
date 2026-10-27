"""🗂 화면 안 탭 묶음(메뉴 정리 2026-10-26) — 한 메뉴 아래 여러 화면을 탭으로.

- 고른 탭만 그린다(안 보이는 탭은 계산하지 않아 속도는 따로 있을 때와 같다).
- 주소 끝 `?tab=키` 로 바로 열리고, 탭을 바꾸면 주소에도 남는다(공유·새로고침 가능).
- 다른 화면에서 보내려면 `st.session_state["_want_tab_<화면키>"] = 탭키` 를 넣고 그 화면으로 옮긴다(옛 주소 자동 이동이 이 방식).
- 테스트의 '모든 화면 한 번에' 모드(QUANT_TEST_ALL_PAGES=1)에서는 st.tabs 로 전부 그린다.
"""
from __future__ import annotations

import os
from typing import Callable

import streamlit as st


def select(page_key: str, items: list[tuple[str, str, Callable[[], None]]]) -> str:
    """items = [(탭키, 라벨, 그리는 함수)]. 고른 탭을 그리고 그 탭키를 돌려준다."""
    keys, labels = [k for k, _, _ in items], [l for _, l, _ in items]
    if os.environ.get("QUANT_TEST_ALL_PAGES") == "1" or not hasattr(st, "segmented_control"):
        for tab, (_k, _l, fn) in zip(st.tabs(labels), items):
            with tab:
                fn()
        return keys[0]
    sk = f"tab_{page_key}"
    want = st.session_state.pop(f"_want_tab_{page_key}", None)
    if want is None:  # 주소의 ?tab= — 우리가 방금 적은 값이 아니면(새로 연 주소) 적용
        q = st.query_params.get("tab")
        if q and q != st.session_state.get(f"_tab_q_{page_key}"):
            want = q
    if want in keys:
        st.session_state[sk] = labels[keys.index(want)]
    kw = {} if sk in st.session_state else {"default": labels[0]}
    sel = st.segmented_control("보기", labels, key=sk, label_visibility="collapsed", **kw) or labels[0]
    k = keys[labels.index(sel)] if sel in labels else keys[0]
    try:
        if st.query_params.get("tab") != k:
            st.query_params["tab"] = k
    except Exception:  # noqa: BLE001  — 테스트 환경 등
        pass
    st.session_state[f"_tab_q_{page_key}"] = k
    items[keys.index(k)][2]()
    return k


def go(page_key: str, tab_key: str | None = None) -> None:
    """다른 화면의 탭으로 이동(버튼 눌렀을 때). dashboard 가 st.session_state['_pages'] 에 화면 객체를 넣어 둔다."""
    pg = (st.session_state.get("_pages") or {}).get(page_key)
    if tab_key:
        st.session_state[f"_want_tab_{page_key}"] = tab_key
    if pg is not None:
        st.switch_page(pg)
