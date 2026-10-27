"""👤 내부자 매수 화면 — 일간·주간·월간, 종목별 합계(총 매수액·평단·현재가 대비)와 거래 내역."""
import pandas as pd
import streamlit as st

import db
import insider
import tosslink
import ui_kit as ui


def render() -> None:
    import watch_ui
    ui.title("내부자 매수", "임원·이사·10% 주주가 장내에서 직접 산 거래(Form 4 거래 코드 P)만 모았습니다. 보상 지급·옵션 행사는 빼고, 금액이 클수록 의미가 큽니다.")
    per = st.radio("기간", ["일간", "주간", "월간"], index=1, horizontal=True, key="in_per", label_visibility="collapsed")
    days = {"일간": 1, "주간": 7, "월간": 30}[per]
    b = insider.buys(days)
    if b.empty:
        st.info("기간 안에 기록된 내부자 장내 매수가 없습니다. 스캐너가 매 사이클 Form 4 공시를 읽어 쌓습니다.")
        return
    if st.toggle("초소형주만", True, key="in_small", help="스캐너가 최근 30일 안에 본 종목만(대형주 이사 매수 등은 숨김). 끄면 전부"):
        _uni = ui.scanner_universe()
        _hid = b[~b["ticker"].isin(_uni)]["ticker"].nunique() if _uni else 0
        if _uni:
            b = b[b["ticker"].isin(_uni)]
        if _hid:
            st.caption(f"스캐너 대상이 아닌 {_hid}종목 숨김")
        if b.empty:
            st.info("기간 안에 초소형주(스캐너 대상)의 내부자 장내 매수가 없어요. '초소형주만'을 끄면 전체를 볼 수 있어요.")
            return
    s = insider.summary_by_ticker(b)
    fx = float((db.get_meta("usdkrw") or {}).get("value") or 1350.0)
    ui.cards([{"t": "매수 종목", "v": f"{len(s)}", "accent": True}, {"t": "총 매수액", "v": f"${b['value'].sum() / 1e3:,.0f}K", "s": f"약 {b['value'].sum() * fx / 1e8:,.1f}억 원"},
              {"t": "매수한 내부자", "v": f"{b['owner'].nunique()}명"}, {"t": "거래", "v": f"{len(b)}건"}])
    px = watch_ui.prices(tuple(s["ticker"]))
    cmap = tosslink.codes()
    for r in s.to_dict("records"):
        t = r["ticker"]
        df = px.get(t)
        cur = None if df is None or df.empty else float(df["Close"].dropna().iloc[-1])
        vs = None if not cur or not r["평단"] else (cur / r["평단"] - 1) * 100
        rows = b[b["ticker"] == t]
        with st.container(border=True):
            a, c = st.columns([6, 1.4])
            import rank_ui
            chips = rank_ui.chip(t) + ui.chip(f"총 ${r['총매수액']:,.0f}", "green") + ui.chip(f"내부자 {r['내부자수']}명", "blue") + ("" if not r["직책"] else ui.chip(r["직책"], "gray"))
            if vs is not None:
                chips += ui.chip(f"평단 대비 {vs:+.0f}%", "red" if vs < 0 else "green")
            lines = [f"{x['date'][5:]} {x['owner']} ({x['title'] or '-'}) {x['shares']:,.0f}주 @ ${x['price']:.4f} = ${(x['value'] or 0):,.0f}"
                     + ("" if not x["after_shares"] else f" · 거래 후 보유 {x['after_shares']:,.0f}주") for x in rows.head(5).to_dict("records")]
            a.markdown(f'<span class="qk-tk">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">최근 {r["최근"]} · 평단 ${r["평단"]:.4f}' + ("" if cur is None else f" · 현재 ${cur:.4f}")
                       + f'</span><br>{chips}<ul style="margin:.4rem 0 0 1rem;padding:0">' + "".join(f"<li class='qk-sub' style='opacity:.85'>{ui.esc(x)}</li>" for x in lines) + "</ul>",
                       unsafe_allow_html=True)
            c.link_button("📲 토스", tosslink.url(t, cmap), width="stretch")
            c.link_button("원문", rows.iloc[0]["url"], width="stretch")
            import report_dialog
            report_dialog.button(t, "in", c)
