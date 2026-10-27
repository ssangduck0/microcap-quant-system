"""📒 실제 매매 일지 화면(🏆 검증의 탭, 2026-10-28) — 입력 폼 · 보유/실현 손익 · 근거 신호별 실전 성적 · 🧪 가상매매와 비교 · 기록 삭제·CSV. 계산은 journal.py."""
from contextlib import closing
from datetime import date

import streamlit as st

import access
import db
import journal
import ui_kit as ui


def render() -> None:
    st.subheader("📒 실제 매매 일지")
    st.caption("실제로 산 것·판 것을 적어 두면 보유·실현 손익, 근거 신호별 실전 성적, 같은 종목을 🧪 가상매매는 어떻게 했는지 보여 줘요. 매도는 먼저 산 것부터 짝지어요(FIFO).")
    if access.is_guest():
        st.info("개인 기록이라 방문객에겐 보이지 않아요.")
        return
    with st.form("jr_form", clear_on_submit=True):
        c = st.columns([1.2, 1, 1.3, 1, 1, 2])
        tk = c[0].text_input("티커", "", placeholder="예: BRAI")
        side = c[1].radio("구분", list(journal.SIDES), horizontal=True)
        day = c[2].date_input("날짜", value=date.today(), max_value=date.today())
        px = c[3].number_input("가격($)", min_value=0.0, value=0.0, step=0.01, format="%.4f")
        qty = c[4].number_input("수량", min_value=0.0, value=0.0, step=1.0)
        sig = c[5].selectbox("근거 신호", journal.signal_options())
        note = st.text_input("메모(선택)", "", placeholder="왜 샀나 · 어디서 팔 생각인가")
        ok = st.form_submit_button("➕ 기록", type="primary")
    if ok:
        try:
            with closing(db.connect()) as conn:
                journal.add(conn, tk, side, day.isoformat(), px, qty, sig, note)
            st.success(f"{tk.upper()} {side} {qty:g}주 @ ${px:.4f} 기록했어요.")
        except ValueError as e:
            st.error(str(e))
    with closing(db.connect()) as conn:
        led = journal.ledger(conn)
        cmp_ = journal.paper_compare(conn)
        allrows = journal.rows(conn)
    s = led["summary"]
    if not s["n_trades"]:
        st.info("아직 기록이 없어요. 위 폼에 첫 매수를 적어 보세요.")
        return
    ui.cards([{"t": "실현 손익", "v": f"${s['realized']:+,.2f}", "s": f"마감 {s['n_closed']}건", "accent": True},
              {"t": "실전 승률", "v": "-" if s["win_rate"] is None else f"{s['win_rate']:.0f}%", "s": "실현된 거래 기준"},
              {"t": "평균 수익률", "v": "-" if s["avg_pct"] is None else f"{s['avg_pct']:+.1f}%"},
              {"t": "평가 손익(보유)", "v": f"${s['unrealized']:+,.2f}", "s": f"보유 {s['n_open']}건 · 우리 일봉 마지막 종가 기준"},
              {"t": "기록", "v": f"{s['n_trades']}건"}])
    if not led["open"].empty:
        st.markdown("**보유 중**")
        st.dataframe(ui.tidy(led["open"]), hide_index=True, width="stretch")
    if not led["closed"].empty:
        st.markdown("**마감(실현)**")
        st.dataframe(ui.tidy(led["closed"]), hide_index=True, width="stretch")
        bs = journal.by_signal(led["closed"])
        if not bs.empty:
            st.markdown("**근거 신호별 실전 성적** — 어떤 신호를 믿고 산 게 실제로 돈이 됐나")
            st.dataframe(ui.tidy(bs), hide_index=True, width="stretch")
    if not cmp_.empty:
        st.markdown("**🧪 가상매매와 비교** — 같은 종목을 가상매매도 샀나(내 매수일 ±2일)")
        st.dataframe(ui.tidy(cmp_), hide_index=True, width="stretch")
        st.caption("가상매매는 규칙대로만 사고판 결과라, 내 실제 결과와 차이가 크면 '진입 시점'이나 '손절 규칙' 중 어느 쪽이 달랐는지 메모와 함께 보세요.")
    with st.expander("기록 전체 · 삭제 · CSV"):
        show = allrows.rename(columns={"id": "번호", "ticker": "종목", "side": "구분", "day": "날짜", "price": "가격($)", "qty": "수량", "fee": "수수료($)", "signal": "근거 신호", "note": "메모"})
        st.dataframe(ui.tidy(show.drop(columns=["created_at"])), hide_index=True, width="stretch")
        d1, d2 = st.columns([1, 3])
        rid = d1.selectbox("삭제할 번호", list(allrows["id"]), key="jr_del_id")
        if d2.button("🗑 이 기록 삭제", key="jr_del"):
            with closing(db.connect()) as conn:
                journal.delete(conn, rid)
            st.rerun()
        st.download_button("⬇️ CSV", allrows.to_csv(index=False).encode("utf-8-sig"), file_name="trade_journal.csv", mime="text/csv", key="jr_csv")
