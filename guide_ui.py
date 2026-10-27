"""📖 가이드북 화면 — 탭별 내용 + 검색. 방문객에게는 주인 전용 내용을 숨긴다."""
import streamlit as st

import access
import guide_content as gc
import ui_kit as ui


def render() -> None:
    ui.title("가이드북", "처음 쓰는 분을 위한 사용법 · 화면별 설명 · 용어 사전 · 자주 묻는 질문")
    secs = [s for s in gc.SECTIONS if not (s["owner"] and access.is_guest())]
    q = st.text_input("검색", key="gd_q", placeholder="찾고 싶은 말을 입력하세요 (예: ATM, Reg SHO, 런웨이, 리포트)", label_visibility="collapsed").strip()
    if q:
        hits = [s for s in secs if q.lower() in (s["title"] + " " + s["body"]).lower()]
        st.caption(f"'{q}' 검색 결과 {len(hits)}개")
        for s in hits:
            with st.expander(f"{s['tab']} · {s['title']}", expanded=True):
                st.markdown(ui.md_safe(s["body"]))
        if not hits:
            st.info("검색 결과가 없어요. 다른 말로 찾아보거나 아래 탭을 둘러보세요.")
        return
    tabs = list(dict.fromkeys(s["tab"] for s in secs))
    for tab, box in zip(tabs, st.tabs(tabs)):
        with box:
            for i, s in enumerate([x for x in secs if x["tab"] == tab]):
                with st.expander(s["title"], expanded=(tab == tabs[0] and i < 2)):
                    st.markdown(ui.md_safe(s["body"]))
