"""🧨 스퀴즈 랭크 화면 v2 — 공매도 잔고·청산 소요일 중심 점수, 순위 변화, 검색, 누르면 상세(🧨 공매도 탭)."""
import pandas as pd
import streamlit as st

import squeeze as sq
import tosslink
import ui_kit as ui


def render(fx: float) -> None:
    import multisignal
    import pick as picker
    import report_dialog
    import shortint
    ui.title("스퀴즈 랭크", "숏스퀴즈 위험 순위 — 공매도 잔고(Float Short %)·청산 소요일·대차 수수료·가용주식·Reg SHO·공매도 거래 비중·유통주식·1개월 상승(100점). 행을 누르면 상세 분석.")
    with st.expander("점수 기준"):
        st.markdown(sq.__doc__.split("\n\n")[1])
    rs = sq.rows()
    if not rs:
        st.info("후보가 없습니다. 스캐너가 공매도 데이터(FINRA·IBKR)와 Reg SHO 를 받으면 채워집니다.")
        return
    have_si = sum(1 for r in rs if r["si_pct"] is not None)
    if have_si == 0:
        st.warning("공매도 잔고(Float Short %·청산 소요일)가 아직 없습니다 — 매일 아침 갱신 작업이 후보 400종목씩 받습니다. 지금 받으려면 아래 버튼.")
    import access
    if access.can_edit() and st.button("🔄 공매도 잔고 지금 받기(상위 150종목, 1~2분)", key="sq_si_now"):  # 방문객은 서버에 무거운 작업을 못 시키게
        with st.spinner("Yahoo 에서 받는 중..."):
            shortint.refresh([r["ticker"] for r in rs[:150]], max_n=150, out=lambda *_: None)
        st.rerun()
    chg = sq.save_ranks(rs[:100], track_from=rs)
    ui.cards([{"t": "조회 종목", "v": f"{len(rs)}", "s": f"공매도 잔고 있는 종목 {have_si}", "accent": True},
              {"t": "공매도 비율 20%↑", "v": f"{sum(1 for r in rs if (r['si_pct'] or 0) >= 20)}"},
              {"t": "청산 소요일 5일↑", "v": f"{sum(1 for r in rs if (r['dtc'] or 0) >= 5)}"},
              {"t": "빌릴 주식 없음(HTB)", "v": f"{sum(1 for r in rs if r['stale'] or r['avail'] == 0)}"}])
    c1, c2, c3 = st.columns([2, 1, 1])
    q = c1.text_input("검색", key="sq_q", placeholder="티커 검색", label_visibility="collapsed").strip().upper()
    min_s = c2.slider("점수 ≥", 0, 100, 30, key="sq_min2")
    no_dil = c3.checkbox("ATM·ELOC·CB 제외", False, key="sq_dil2")
    import db
    dil = dict(db.read_df("SELECT ticker, dilution_status FROM daily_snapshots WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM daily_snapshots GROUP BY ticker)").values)
    ms = multisignal.collect()
    v = [r for r in rs[:100] if r["score"] >= min_s and (not q or q in r["ticker"]) and not (no_dil and dil.get(r["ticker"]) in ("ATM", "ELOC", "CB"))]
    if not v:
        st.caption("조건에 맞는 종목이 없습니다.")
        return
    rank = {r["ticker"]: i for i, r in enumerate(rs[:100], 1)}
    tb = pd.DataFrame([{"순위": rank[r["ticker"]], "변화": "" if chg.get(r["ticker"]) is None else ("↑" + str(chg[r["ticker"]]) if chg[r["ticker"]] > 0 else ("↓" + str(-chg[r["ticker"]]) if chg[r["ticker"]] < 0 else "-")),
                        "티커": r["ticker"], "토스": tosslink.url(r["ticker"]), "스퀴즈 점수": r["score"], "공매도 비율(%)": r["si_pct"], "청산 소요일": r["dtc"],
                        "대차 수수료(%)": r["fee"], "대차 가용": "0 (HTB)" if (r["stale"] or r["avail"] == 0) else (None if r["avail"] is None else f"{r['avail']:,.0f}"),
                        "Reg SHO": "" if not r["sho"] else f"{r['sho']}일째", "멀티 시그널": multisignal.label(ms.get(r["ticker"])), "희석": dil.get(r["ticker"]) or ""} for r in v])
    cfg = {"토스": st.column_config.LinkColumn(display_text="📲"), "스퀴즈 점수": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f점"),
           "공매도 비율(%)": st.column_config.NumberColumn(format="%.2f"), "청산 소요일": st.column_config.NumberColumn(format="%.2f일"),
           "대차 수수료(%)": st.column_config.NumberColumn(format="%.1f")}
    import rank_ui
    tb.insert(list(tb.columns).index("티커") + 1, "종합 순위", rank_ui.column(tb["티커"]))
    t = picker.clickable(tb, list(tb["티커"]), "sq_table2", hide_index=True, width="stretch", column_config=cfg, popup=True, popup_focus="short")
    try:
        import chartex
        _cx = chartex.enabled()
    except Exception:  # noqa: BLE001
        _cx = False
    st.caption(("공매도 잔고(공매도 비율·청산 소요일)는 📡 ChartExchange 일별 시계열(보고 사이 이월) 우선, 없는 종목은 Yahoo(FINRA 격주) · " if _cx else
                "공매도 잔고(공매도 비율·청산 소요일)는 Yahoo(FINRA 격주 공시) 기준이라 며칠 늦습니다 · ") + "대차는 IBKR 15분 · 공매도 거래 비중은 FINRA 일별.")
    if t:
        report_dialog.button(t, "sq_sel")
