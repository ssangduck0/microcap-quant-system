"""📇 종목 스크리너 카드 화면 — 🗂 종목 리포트 안에서."""
from __future__ import annotations

from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st

import db
import ui_kit as ui


def _money(v) -> str:
    if v is None:
        return "-"
    v = float(v)
    return f"${v / 1e9:.2f}B" if abs(v) >= 1e9 else (f"${v / 1e6:.2f}M" if abs(v) >= 1e6 else f"${v / 1e3:.0f}K")


def render(ticker: str) -> None:
    import access
    import screener
    t = (ticker or "").upper()
    if not t:
        return
    with closing(db.connect()) as conn:
        card = screener.latest_card(conn, t)
    st.markdown("**📇 스크리너 카드** — 제외 사유 · 실적 일정·컨센서스 · 이벤트 로그와 주가 반응 · 레벨 맵(규칙) · AI 시나리오(참고)")
    if not access.is_guest() and st.button(f"📇 {t} 카드 생성/갱신 (AI 판단 포함 · 약 100원)", key=f"scr_make_{t}"):
        with st.spinner("실적 일정·공시·주가를 모으고 Claude 가 시나리오를 쓰는 중… (30초~1분)"):
            try:
                card = screener.build(t, source="직접")
            except Exception as e:  # noqa: BLE001
                st.error(f"카드 만들기 실패: {e}")
    if not card:
        st.caption("아직 카드가 없어요. 위 버튼으로 만들면 종목·날짜별로 저장돼요.")
        return
    lv, e, ai = card.get("levels") or {}, card.get("earnings") or {}, card.get("ai")
    st.caption(f"기준 {card.get('date')} · 출처 {card.get('source', '')}" + ("" if card.get("in_universe") else " · ⚠️ 우리 스캐너 감시 종목이 아니에요(자료가 적을 수 있어요)"))
    # ① 제외 사유
    if card.get("exclusion"):
        for w in card["exclusion"]:
            st.error("⚠️ 우리 후보에서 제외된 이유 — " + w)
    else:
        st.success("✅ 우리 후보 조건(희석 상태·③ 희석 판정·상장유지 통지·점수)에 걸리는 게 없어요")
    # ② 가격·실적
    if lv:
        box = lv.get("day_box") or (None, None)
        vm = lv.get("vs_month_start") or {}
        ui.cards([{"t": "현재가(최근 종가)", "v": f"${lv['last']:.4g}", "s": f"전일 ${lv['prev']:.4g} · 52주 ${lv.get('lo52', 0):.3g}~{lv.get('hi52', 0):.3g}"},
                  {"t": "당일 박스", "v": f"${box[0]:.4g}~{box[1]:.4g}" if box[0] else "-", "s": f"변동폭 {lv.get('day_range_pct', 0)}% · 박스 내 위치 {lv.get('pos_in_box', '-')}%"},
                  {"t": "시가총액 추정", "v": _money(card.get("mcap")), "s": f"{(card.get('shares') or 0) / 1e6:.1f}M주 기준" if card.get("shares") else "주식 수 없음"},
                  {"t": "월초 대비", "v": f"{vm.get('pct', 0):+.1f}%" if vm else "-", "s": f"{vm.get('date', '')} ${vm.get('base', 0):.4g} 기준" if vm else ""}])
    nd = e.get("next_date")
    dn = (date.fromisoformat(nd) - date.today()).days if nd else None
    ui.cards([{"t": "다음 실적 발표", "v": nd or "미정", "s": f"D{dn:+d}" if dn is not None else "야후 일정 없음", "accent": bool(dn is not None and 0 <= dn <= 14)},
              {"t": "매출 컨센서스", "v": _money(e.get("rev_avg")), "s": f"{_money(e.get('rev_low'))} ~ {_money(e.get('rev_high'))}" if e.get("rev_low") else ""},
              {"t": "EPS 컨센서스", "v": f"${e['eps_avg']:.2f}" if e.get("eps_avg") is not None else "-"},
              {"t": "직전 분기", "v": _money(e.get("last_rev")), "s": (f"{e.get('last_q', '')} · EPS ${e['last_eps']:.2f}" if e.get("last_eps") is not None else e.get("last_q", "") or "")}])
    # ③ 이벤트 로그
    if card.get("events"):
        st.markdown("**🗒 이벤트 로그** — 최근 240일 공시(수집분 + 과거 이력)·일정·딜·내부자·병합, 사건 뒤 주가 반응(D+1·D+5 종가)")
        st.dataframe(ui.tidy(pd.DataFrame(card["events"]).rename(columns={"date": "날짜", "kind": "종류", "text": "내용", "d1": "D+1 %", "d5": "D+5 %"})), hide_index=True, width="stretch")
    # ④ 레벨 맵
    if lv:
        gap = lv.get("gap")
        sup = lv.get("support") or (None, None)
        r1, r2 = lv.get("resistance1"), lv.get("resistance")
        if r1 and r2 and abs(r1 - r2) > 1e-12:
            rows = [("🔴 2차 저항", f"${r2:.4g} 이상", "60일 최고 종가"), ("🟥 1차 저항", f"${r1:.4g}", "20일 고가(가까운 벽)")]
        else:  # 예전 카드(1차 없음) 또는 20일 고가가 곧 60일 최고
            rows = [("🔴 상단 저항", f"${r2:.4g} 이상", "20일 고가 = 60일 최고 종가" if r1 else "60일 최고 종가")]
        rows += [("🟠 갭 회복 확인", f"${gap[0]:.4g}~{gap[1]:.4g}" if gap else "없음", "직전 종가가 당일 고가보다 위면 메워야 할 갭"),
                ("⬜ 당일 박스", f"${box[0]:.4g}~{box[1]:.4g} (현재 ${lv['last']:.4g})" if lv.get("day_box") else "-", f"위치 {lv.get('pos_in_box', '-')}%"),
                ("🟢 1차 지지", f"${sup[0]:.4g}~{sup[1]:.4g}" if sup[0] else "-", "20일 저가 −3%"),
                ("🔻 하방 위험", f"${lv['danger']:.4g} 이하", "52주 저가 근처")]
        st.markdown("**🗺 레벨 맵** (규칙 계산 · AI 아님)")
        st.dataframe(ui.tidy(pd.DataFrame(rows, columns=["구간", "가격", "근거"])), hide_index=True, width="stretch")
        if lv.get("after_high"):
            st.caption(f"🌙 최근 애프터 고점 ${lv['after_high']:.4g}")
    # ⑤ AI
    if ai and not ai.get("error"):
        sc = {"회피": "red", "관망": "gray", "소량": "orange", "관심": "green"}
        st.markdown(f"**🤖 AI 판단(참고)** {ui.chip(ai.get('stance', ''), sc.get(ai.get('stance', ''), 'gray'))} <b>{ui.esc(ai.get('headline', ''))}</b><br>"
                    f"<span class='qk-sub'>{ui.esc(ai.get('why', ''))} · 위험 대비 보상 {ui.esc(str(ai.get('rr', '-')))}</span>", unsafe_allow_html=True)
        for cp in ai.get("check_points") or []:
            st.markdown(f"- ✅ {cp}")
        if ai.get("scenarios"):
            st.dataframe(ui.tidy(pd.DataFrame(ai["scenarios"]).rename(columns={"name": "시나리오", "condition": "조건", "path": "예상 경로"})), hide_index=True, width="stretch")
        st.caption(f"Claude {screener.MODEL} · 이번 카드 ${ai.get('cost_usd', 0):.3f} · 투자 권유가 아니에요")
    elif ai and ai.get("error"):
        st.warning(f"AI 판단 없음: {ai['error']}")
    # ⑥ 🎲 매매 전 시뮬레이션(2026-10-29): 같은 신호 전체 과거 + 이 종목 최근 250일 — 입력은 관리자만, 방문객은 아침 자동 결과만
    try:
        import presim_ui
        presim_ui.render_section(t, card)
    except Exception as e:  # noqa: BLE001
        st.caption(f"🎲 매매 전 시뮬레이션을 못 그렸어요: {e}")
