"""📊 매매강도 카드 — 토스 실시간 체결을 금액 구간(XL/L/M/S)별 매수·매도로(래빗스탁·오르텍스 식). 🏢 종목 화면 · 🕶 다크풀 상세에서 쓴다."""
from contextlib import closing
from datetime import date, datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

import chartpop
import db
import flowsize as fz
import ui_kit as ui

KST = ZoneInfo("Asia/Seoul")


def _kst(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(KST).strftime("%m/%d %H:%M")
    except Exception:  # noqa: BLE001
        return iso or "-"


def _usd(v: float) -> str:
    return f"${v / 1e6:.2f}M" if abs(v) >= 1e6 else (f"${v / 1e3:.1f}K" if abs(v) >= 1e3 else f"${v:,.0f}")


def card(t: str, key: str = "co") -> None:
    t = t.upper()
    with closing(db.connect()) as conn:
        ds = fz.days(conn, t)
        today_et = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        if not ds:
            b = fz.basic(conn, t, today_et) or next((fz.basic(conn, t, d) for d in []), None)
            if b:
                st.caption(f"금액 구간별 기록은 아직 없고, 주식 수 기준 체결만 있어요(토스 실시간 · {_kst(b['first'])}~{_kst(b['last'])} · {b['n']:,}건).")
                ui.cards([{"t": "매수 비중(주식 수)", "v": "-" if b["buy_pct"] is None else f"{b['buy_pct']:.0f}%", "s": f"매수 {b['buy_sh']:,.0f}주 · 매도 {b['sell_sh']:,.0f}주", "accent": True}])
            else:
                st.caption("실시간 체결 기록이 없어요. 스캐너가 구독하는 종목(장마감 후보·다크풀 상위·워치리스트·저금통, 최대 50개)에 들어오면 그때부터 쌓여요.")
            return
        d = st.selectbox("기준일", ds, index=0, key=f"fz_day_{key}_{t}", format_func=lambda x: f"{x} (오늘 · 실시간)" if x == today_et else x, label_visibility="collapsed")
        s = fz.summary(conn, t, d)
        tl = fz.timeline(conn, t, d)
    if not s:
        st.caption("그날 체결 기록이 없어요.")
        return
    color = {"매수세 우세": "green", "매도세 우세": "red"}.get(s["verdict"], "gray")
    pct = s["buy_pct"] or 0
    st.markdown(ui.chip(s["verdict"], color) + f"<span class='qk-sub'>&nbsp;기준 {_kst(s['first'])} ~ {_kst(s['last'])} KST · 토스 실시간 체결, 호가 기준 매수/매도 분류</span>", unsafe_allow_html=True)
    st.markdown(f"<div style='display:flex;align-items:center;gap:8px;margin:4px 0 10px'><span style='color:#30A46C;font-weight:600'>매수 {pct:.0f}%</span>"
                f"<div style='flex:1;height:10px;border-radius:5px;background:linear-gradient(90deg,#30A46C {pct:.0f}%,#E5484D {pct:.0f}%)'></div>"
                f"<span style='color:#E5484D;font-weight:600'>매도 {100 - pct:.0f}%</span></div>", unsafe_allow_html=True)
    ui.cards([{"t": "순매수", "v": ("+" if s["net"] >= 0 else "−") + _usd(abs(s["net"])), "s": f"매수 {_usd(s['buy'])} · 매도 {_usd(s['sell'])}", "accent": True},
              {"t": "기관(XL+L) 순매수", "v": ("+" if (s["by"]["XL"]["net"] + s["by"]["L"]["net"]) >= 0 else "−") + _usd(abs(s["by"]["XL"]["net"] + s["by"]["L"]["net"])),
               "s": f"XL {s['by']['XL']['buy_n'] + s['by']['XL']['sell_n']}건 · L {s['by']['L']['buy_n'] + s['by']['L']['sell_n']}건"},
              {"t": "개인(M+S) 순매수", "v": ("+" if (s["by"]["M"]["net"] + s["by"]["S"]["net"]) >= 0 else "−") + _usd(abs(s["by"]["M"]["net"] + s["by"]["S"]["net"])),
               "s": f"M {s['by']['M']['buy_n'] + s['by']['M']['sell_n']}건 · S {s['by']['S']['buy_n'] + s['by']['S']['sell_n']}건"}])
    rows = []
    for z in fz.SIZES:
        v = s["by"][z]
        tot = v["buy"] + v["sell"]
        rows.append({"구간": f"{z} · {fz.SIZE_LABEL[z]}", "매수($)": v["buy"], "매도($)": v["sell"], "순매수($)": v["net"], "매수 비중(%)": None if tot <= 0 else v["buy"] / tot * 100,
                     "매수 건수": v["buy_n"], "매도 건수": v["sell_n"], "매수 주식": v["buy_sh"], "매도 주식": v["sell_sh"]})
    tb = pd.DataFrame(rows)
    c1, c2 = st.columns([2, 3])
    with c1:
        long = pd.DataFrame([{"구간": z, "방향": "매수", "금액": s["by"][z]["buy"]} for z in fz.SIZES] + [{"구간": z, "방향": "매도", "금액": s["by"][z]["sell"]} for z in fz.SIZES])
        donut = alt.Chart(long[long["금액"] > 0]).mark_arc(innerRadius=45).encode(theta=alt.Theta("금액:Q"), color=alt.Color("방향:N", scale=alt.Scale(domain=["매수", "매도"], range=["#30A46C", "#E5484D"]), legend=alt.Legend(orient="bottom", title=None)),
                                                                                   opacity=alt.Opacity("구간:N", scale=alt.Scale(domain=list(fz.SIZES), range=[1.0, 0.8, 0.6, 0.4]), legend=None),
                                                                                   tooltip=["구간:N", "방향:N", alt.Tooltip("금액:Q", format=",.0f")]).properties(height=200)
        chartpop.show(donut, key=f"fz_donut_{key}_{t}", title=f"{t} 구간별 매수·매도 금액({d})", data=tb, note="진할수록 큰 금액 구간(XL→S).")
    with c2:
        st.dataframe(tb, hide_index=True, width="stretch", column_config={"매수($)": st.column_config.NumberColumn(format="%,.0f"), "매도($)": st.column_config.NumberColumn(format="%,.0f"),
                                                                        "순매수($)": st.column_config.NumberColumn(format="%+,.0f"), "매수 비중(%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                                                                        "매수 주식": st.column_config.NumberColumn(format="%,.0f"), "매도 주식": st.column_config.NumberColumn(format="%,.0f")})
    if not tl.empty:
        chartpop.line(tl[["누적 순매수($)"]], key=f"fz_tl_{key}_{t}", title=f"{t} 누적 순매수 타임라인({d}, KST)", height=180, zero=True, fmt=",.0f",
                      note="분 단위 매수 금액 − 매도 금액의 누적. 구독이 끊긴 구간은 비어 있을 수 있어요.")
    st.caption("XL $100K↑ · L $10K~100K · M $1K~10K · S $1K↓ (체결 한 건 금액). 스캐너가 구독 중인 종목만, 구독 시작 뒤부터 쌓여요. 전 종목 하루치는 유료 틱 데이터가 있어야 해요.")
