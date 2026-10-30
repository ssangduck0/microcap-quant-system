"""📨 보낸 알림 — 텔레그램으로 나간 모든 알림(📐 차트 · 🔔 공시 · 🌙 애프터 · 🩳 공매 · 📈 판정 …)을 한 곳에서 시간순으로(2026-10-28).
밤에 온 알림을 아침에 되짚어 보는 용도. 기록은 notify.send_telegram 이 남긴다(alert_log 표)."""
from contextlib import closing

import streamlit as st

import chartpop
import db
import notify
import ui_kit as ui


def render() -> None:
    st.subheader("📨 보낸 알림")
    st.caption("텔레그램으로 나간 알림 전부 — 종류·종목으로 거르고, 밤사이 온 것을 아침에 한눈에. ❌ 는 보내려 했지만 전송에 실패한 것.")
    c1, c2, c3 = st.columns([1, 2, 1])
    days = c1.radio("기간", [1, 3, 7, 30], index=2, horizontal=True, key="sent_days", format_func=lambda d: f"{d}일", label_visibility="collapsed")
    with closing(db.connect()) as conn:
        df = notify.recent(conn, days, limit=2000)
        today = notify.recent(conn, 1, limit=2000)
    kinds = sorted(df["종류"].unique()) if not df.empty else []
    sel = c2.multiselect("종류", kinds, default=kinds, key="sent_kinds", label_visibility="collapsed", placeholder="종류 고르기")
    tk = c3.text_input("종목", "", key="sent_tk", placeholder="티커", label_visibility="collapsed").strip().upper()
    if df.empty:
        st.info("아직 기록된 알림이 없어요. 스캐너·아침 갱신이 텔레그램으로 보내는 순간부터 여기에 쌓입니다(10/28 배포 뒤).")
        return
    v = df[df["종류"].isin(sel)] if sel else df
    if tk:
        v = v[v["종목"] == tk]
    top = v["종류"].value_counts()
    ui.cards([{"t": f"최근 {days}일", "v": f"{len(v):,}건", "accent": True}, {"t": "오늘(24시간)", "v": f"{len(today):,}건"},
              {"t": "가장 많은 종류", "v": top.index[0] if len(top) else "-", "s": f"{int(top.iloc[0])}건" if len(top) else ""},
              {"t": "종목 수", "v": f"{v.loc[v['종목'] != '', '종목'].nunique()}"}, {"t": "전송 실패", "v": f"{(v['보냄'] == '❌').sum()}건"}])
    ct = v.pivot_table(index="날짜", columns="종류", values="내용", aggfunc="count", fill_value=0).sort_index()
    if len(ct) > 1 or days > 1:
        chartpop.bar(ct, key="sent_bar", title="날짜별 알림 건수(종류별)", height=180, fmt=",.0f")
    st.dataframe(v.drop(columns=["날짜"]), hide_index=True, width="stretch", height=min(600, 38 + 35 * len(v)),
                 column_config={"내용": st.column_config.TextColumn("내용", width="large")})
    st.download_button("⬇️ CSV", v.to_csv(index=False).encode("utf-8-sig"), file_name=f"alerts_{days}d.csv", mime="text/csv", key="sent_csv")
