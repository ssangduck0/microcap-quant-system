"""🔎 종목 검색 — 티커 하나의 모든 정보를 한 화면에(체결강도·공매도·분산/털기·공매도 흐름·세력/셋업·타임라인·공시분석)."""
import pandas as pd
import streamlit as st

import db


def render() -> None:
    import flowread_ui
    import forensic_ui
    import intel_ui
    import pumpsetup_ui
    import shortflow_ui
    import timeline_ui
    import tosslink_ui
    import watch
    import watch_ui
    st.subheader("🔎 종목 검색 — 한 종목의 모든 정보")
    fav = list(watch.all_items()["ticker"]) if not watch.all_items().empty else []
    if fav:
        st.caption("⭐ 즐겨찾기(워치리스트)")
        cols = st.columns(min(len(fav), 8))
        for i, f in enumerate(fav[:16]):
            if cols[i % len(cols)].button(f, key=f"lk_fav_{f}", width="stretch"):
                st.session_state["lookup_ticker"] = f
                st.rerun()
    t = st.text_input("티커", value=st.session_state.get("lookup_ticker", ""), key="lookup_in", placeholder="예: HODO").strip().upper()
    if not t:
        st.info("왼쪽 메뉴 맨 위 검색창이나 여기에 티커를 입력하세요.")
        return
    st.session_state["lookup_ticker"] = t
    snap = db.read_df("SELECT * FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
    import company_ui
    company_ui.render(t)  # 🏢 기업 분석(김곰식 1~6)
    st.divider()
    st.markdown(f"### {t} · 세부 패널")
    tosslink_ui.button(t, key="lk")
    import report_dialog
    report_dialog.button(t, "lk")
    watch_ui.add_button(t, None if snap.empty else float(snap.iloc[0]["price"]), key="lk")
    if not snap.empty:
        r = snap.iloc[0]
        m = st.columns(5)
        m[0].metric("현재가", f"${r['price']:.4f}", help=f"스캐너 기록 {r['date']}")
        m[1].metric("오늘 등락", "-" if pd.isna(r["day_change_pct"]) else f"{r['day_change_pct']:+.1f}%")
        m[2].metric("거래량 배수", "-" if pd.isna(r["volume_mult"]) else f"{r['volume_mult']:.1f}배")
        m[3].metric("승률 점수", "-" if pd.isna(r.get("win_score")) else f"{r['win_score']:.0f}")
        m[4].metric("희석", r["dilution_status"] or "-")
    else:
        st.caption("스캐너가 아직 이 종목을 기록하지 않았습니다. ⭐ 워치리스트에 넣으면 스캐너가 항상 분석합니다.")
    px = watch_ui.prices((t,)).get(t)
    with st.expander("📡 체결강도 · 거래정지 · 공매도 · 장중 공시", expanded=True):
        intel_ui.render_ticker(t, None, key="lk")
    flowread_ui.render_panel(t, px, key="lk")
    shortflow_ui.render_panel(t, px, key="lk")
    pumpsetup_ui.render_panel(t, px, key="lk")
    timeline_ui.render(t, key="lk")
    import ai_ui
    ai_ui.render(t, key="lk")
    forensic_ui.render(t, key="lk")
