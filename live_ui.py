"""⚡ 지금 분석 카드 — SHFS 분석 결과 형식(큰 숫자 · 구간·52주 위치 막대 · 1분봉 · 신호 요약)."""
import altair as alt
import pandas as pd
import streamlit as st

import chartpop

import live
import ui_kit as ui

COL = {"red": "#E5484D", "blue": "#3678F6", "green": "#30A46C", "orange": "#F76B15"}


@st.cache_data(ttl=60, show_spinner=False)
def _get(t: str):
    return live.fetch(t)


def _bar(pos: float | None, left: str, mid: str, right: str, color: str) -> str:
    p = 0 if pos is None else max(0, min(100, pos))
    return (f'<div style="position:relative;height:8px;border-radius:6px;background:rgba(128,128,128,.25);margin:10px 0 6px">'
            f'<div style="position:absolute;left:calc({p:.1f}% - 9px);top:-5px;width:18px;height:18px;border-radius:50%;background:{color}"></div></div>'
            f'<div style="display:flex;justify-content:space-between" class="qk-sub"><span>{left}</span><span>{mid}</span><span>{right}</span></div>')


def render(t: str, key: str = "lv") -> None:
    t = t.upper()
    a, b = st.columns([4, 1])
    if b.button("↻ 새로", key=f"{key}_re_{t}"):
        _get.clear()
    try:
        r = _get(t)
    except Exception as e:  # noqa: BLE001
        st.caption(f"1분봉을 받지 못했어요({type(e).__name__}).")
        return
    if not r:
        st.caption("1분봉 자료가 없어요(거래가 없거나 장외 시간).")
        return
    a.markdown(f'<b style="font-size:1.3rem">{ui.esc(t)} 분석 결과</b> <span class="qk-sub" style="float:right">{r["session"]} {r["time"]}(동부) 기준</span>', unsafe_allow_html=True)
    sign = lambda v: "" if v is None else f"{v:+.2f}%"  # noqa: E731
    big = lambda v, c="": f'<div style="font-size:2rem;font-weight:800;{c}">{v}</div>'  # noqa: E731
    up = "color:#E5484D" if (r["chg_prev"] or 0) >= 0 else "color:#3678F6"
    c1, c2 = st.columns(2)
    c1.markdown('<span class="qk-sub">현재가</span>' + big(f"{r['price']:.4f}") + f'<span style="{up}">{sign(r["chg_session"])} ({"정규장 종가" if r["session"] == "애프터" else "전일 종가"} 대비)</span>',
                unsafe_allow_html=True)
    c2.markdown('<span class="qk-sub">전일 종가 대비</span>' + big(sign(r["chg_prev"]), up) + f'<span class="qk-sub">전일 종가 {r["prev_close"] or 0:.4f}</span>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if r["reg_close"]:
        c1.markdown('<span class="qk-sub">정규장 마감</span>' + big(f"{r['reg_close']:.4f}") + f'<span style="{up}">{sign(r["reg_chg"])}</span>', unsafe_allow_html=True)
    c2.markdown('<span class="qk-sub">구간 변동폭</span>' + big(f"{r['range_pct'] or 0:.2f}%") + f'<span class="qk-sub">저가 {r["lo"]:.4f}, 고가 {r["hi"]:.4f}</span>', unsafe_allow_html=True)
    st.markdown("**차트 구간 내 위치**" + _bar(r["pos"], f"저가 {r['lo']:.4f}", f"현재 {r['pos'] or 0:.0f}% 지점", f"고가 {r['hi']:.4f}", "#3678F6"), unsafe_allow_html=True)
    if r.get("hi52"):
        st.markdown("**52주 범위 내 위치**" + _bar(r["pos52"], f"52주 저가 {r['lo52']:.4f}", f"고점 대비 {r['from_hi52']:+.2f}%", f"52주 고가 {r['hi52']:.2f}", "#E5484D"),
                    unsafe_allow_html=True)
    w = r["window"].reset_index()
    w = w.rename(columns={w.columns[0]: "시각"})
    ref = r["reg_close"] if r["session"] == "애프터" else r["prev_close"]
    line = alt.Chart(w).mark_area(line={"color": "#3678F6"}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color="rgba(54,120,246,0.25)", offset=0),
                                                                                                         alt.GradientStop(color="rgba(54,120,246,0)", offset=1)], x1=1, x2=1, y1=0, y2=1)).encode(
        x=alt.X("시각:T", title=None, axis=alt.Axis(format="%H:%M")), y=alt.Y("Close:Q", title=None, scale=alt.Scale(zero=False)), tooltip=[alt.Tooltip("시각:T", format="%H:%M"), "Close:Q"])
    layers = [line]
    if ref:
        layers.append(alt.Chart(pd.DataFrame({"y": [ref]})).mark_rule(strokeDash=[5, 4], color="#8B8D98").encode(y="y:Q"))
    st.markdown(f"**{r['session']} 1분봉 추이** <span class='qk-sub'>— 점선: {'정규장 종가' if r['session'] == '애프터' else '전일 종가'} {ref or 0:.4f}</span>", unsafe_allow_html=True)
    chartpop.show(alt.layer(*layers).properties(height=220), key=f"live_{key}", title=f"{r['session']} 1분봉 추이")
    st.markdown("**신호 요약**")
    for name, txt, color in r["signals"]:
        st.markdown(f'<div style="display:flex;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid rgba(128,128,128,.2)">'
                    f'<span style="min-width:84px;text-align:center;padding:3px 10px;border-radius:8px;background:{COL[color]}22;color:{COL[color]};font-weight:700">{name}</span>'
                    f'<span>{ui.esc(txt)}</span></div>', unsafe_allow_html=True)
    if not r["signals"]:
        st.caption("뚜렷한 신호가 없어요.")
