"""🤖 AI 요약 · 🔀 교차검증 화면 조각 — 종목 검색·공시 리포트에 들어간다."""
import os

import pandas as pd
import streamlit as st

import aisummary as ai
import ui_kit as ui

ICON = {"일치": "✅ 일치", "시점차": "🕒 시점 차이", "다름": "⚠️ 다름", "한쪽만": "❓ 한쪽만"}


def render(ticker: str, key: str = "ai") -> None:
    st.markdown("##### 🤖 AI 요약 · 🔀 교차검증")
    render_summary(ticker, key)
    render_check(ticker, key, show_button=False)


GROUPS = [("📋 핵심 포인트", ["매수 동기", "해소하려는 문제"], "#3678F6"), ("➕ 상승 트리거", ["압박 목적", "가격 사다리"], "#30A46C"),
          ("⚠ 구조적 리스크", ["출회 주체", "주의사항"], "#F76B15")]


def _as_list(v) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])


def render_summary(ticker: str, key: str = "ai") -> None:
    t = ticker.upper()
    import access
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()) and access.can_edit()
    left = ai.budget_left_krw()
    if access.is_guest():
        st.caption("👀 방문객 모드 — 저장된 AI 요약만 볼 수 있어요.")
    else:
        st.caption(f"이번 달 AI 사용 {ai.month_spend_usd() * ai.fx():,.0f}원 · 남은 예산 {max(left, 0):,.0f}원 · 모델 {ai.model()} · 우리 시스템이 정리한 사실만 넘겨 요약합니다(틀릴 수 있음).")
    if not has_key and not access.is_guest():
        st.info("`.env` 에 `ANTHROPIC_API_KEY=…` 를 넣고 대시보드를 재시작하면 사용할 수 있어요.")
    c1, c2 = st.columns(2)
    _ = c2
    if c1.button("🤖 AI 요약 만들기(오늘 것 있으면 다시)", key=f"{key}_sum_{t}", disabled=not has_key, width="stretch"):
        try:
            with st.spinner("요약 중..."):
                ai.summarize(t, force=True)
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    s = ai.latest(t)
    if s:
        verdict = " ".join(_as_list(s.get("판정")))
        color = "#30A46C" if verdict.startswith("매력") else ("#E5484D" if verdict.startswith("회피") else "#F76B15" if verdict.startswith("대기") else "#8B8D98")
        st.markdown(ui.verdict(verdict.split()[0] if verdict else "-", s.get("한줄요약", ""), None, color), unsafe_allow_html=True)
        cols = st.columns(3)
        for col, (title, secs, color) in zip(cols, GROUPS):  # 래빗스탁처럼 세 칸: 핵심 · 상승 트리거 · 구조적 리스크
            bullets = [f"[{sec}] {x}" for sec in secs for x in _as_list(s.get(sec))]
            col.markdown(ui.box(title, bullets, color), unsafe_allow_html=True)
        if s.get("확인필요"):
            st.warning("확인 필요: " + " · ".join(s["확인필요"] if isinstance(s["확인필요"], list) else [str(s["확인필요"])]))
        st.caption(f"AI 요약 {str(s.get('_at', ''))[:16]} · {s.get('_model')} · 비용 약 {s.get('_cost_krw', 0):,.0f}원 · 판정: {verdict}")



def render_check(ticker: str, key: str = "ai", show_button: bool = True) -> None:
    t = ticker.upper()
    import access
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()) and access.can_edit()
    if access.can_edit() and st.button("🔀 덕구 스캔과 교차검증", key=f"{key}_chk_{t}", disabled=not has_key, width="stretch"):
        try:
            with st.spinner("두 보고서를 대조하는 중..."):
                ai.cross_check(t)
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    chk = ai.latest(t, "check")
    if not chk:
        st.caption("아직 교차검증이 없습니다. 덕구 스캔 보고서가 있으면 위 버튼으로 대조할 수 있어요(새 덕구 보고서는 자동).")
    if chk:
        rate = chk.get("일치율")
        st.markdown(ui.verdict(f"일치율 {rate}%" if rate is not None else "교차검증", chk.get("종합", ""), float(rate) if isinstance(rate, (int, float)) else None,
                               "#30A46C" if (rate or 0) >= 80 else "#F76B15" if (rate or 0) >= 60 else "#E5484D", "일치율(시점 차이·한쪽만 제외)"), unsafe_allow_html=True)
        items = chk.get("항목") or []
        if items:
            st.dataframe(pd.DataFrame([{"항목": x.get("이름"), "판정": ICON.get(x.get("판정"), x.get("판정")), "우리 시스템 데이터": x.get("A"),
                                        "덕구 스캔(공시 원문)": x.get("B"), "메모": x.get("메모")} for x in items]), hide_index=True, width="stretch")
        bad = ai.conflicts(chk)
        if bad:
            st.error("⚠️ 어긋난 항목 — 원문 확인 필요: " + ", ".join(x.get("이름", "") for x in bad))
        if chk.get("원문확인"):
            st.caption("원문에서 확인할 것: " + " · ".join(chk["원문확인"] if isinstance(chk["원문확인"], list) else [str(chk["원문확인"])]))
        st.caption(f"교차검증 {str(chk.get('_at', ''))[:16]} · 덕구 보고서 {chk.get('_forensic_at', '-')} · 비용 약 {chk.get('_cost_krw', 0):,.0f}원")
