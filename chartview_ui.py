"""📐 스승 관점 화면 — 📈 차트의 '스승 관점' 구역(채널 선 차트 · 매물대 · 두 고수 체크리스트 · 한 줄 판독) · 🏢 종목 헤더 칩 · 최근 신호 표.
근거: docs/chart_masters.md (키쟈키라 · ANO). 계산은 전부 chartview.py — 여기는 그리기만."""
from contextlib import closing

import altair as alt
import pandas as pd
import streamlit as st

import chartpop
import chartview as cv
import db
import ui_kit as ui

STATUS_ICON = {"good": "✅", "warn": "⚠️", "bad": "❌", "none": "➖"}
LEVEL_COLORS = {"발": "#8B8D98", "무릎": "#30A46C", "허리": "#E5484D", "어깨": "#30A46C", "머리": "#3678F6", "보라돌이": "#8E4EC6", "생명선": "#F76B15"}
SIG_COLOR = {1: "green", -1: "red", 0: "blue"}


@st.cache_data(ttl=600, show_spinner=False)
def _intraday(t: str) -> tuple:
    try:
        h60, m5 = cv.fetch_intraday([t])
        return h60.get(t), m5.get(t)
    except Exception:  # noqa: BLE001
        return None, None


@st.cache_data(ttl=3600, show_spinner=False)
def _float(t: str) -> float | None:
    try:
        import chartex
        with closing(db.connect()) as conn:
            f = chartex.float_of(conn, t)
        return float(f["shares_float"]) if f and f.get("shares_float") else None
    except Exception:  # noqa: BLE001
        return None


def analysis(t: str, df: pd.DataFrame | None, intraday: bool = True) -> dict | None:
    if df is None or df.empty:
        return None
    h60, m5 = _intraday(t) if intraday else (None, None)
    try:
        return cv.analyze(df, h60, m5, _float(t))
    except Exception:  # noqa: BLE001
        return None


def level_chart(t: str, df: pd.DataFrame, a: dict, key: str) -> None:
    x = df.dropna(subset=["Close"]).tail(120).reset_index()
    x = x.rename(columns={x.columns[0]: "날짜"})
    dom = [pd.Timestamp(x["날짜"].min()).isoformat(), pd.Timestamp(x["날짜"].max()).isoformat()]
    base = alt.Chart(x).encode(x=alt.X("날짜:T", title=None, scale=alt.Scale(domain=dom)))
    layers = [base.mark_line(color="#E6E8EB", strokeWidth=1.8).encode(y=alt.Y("Close:Q", title="가격($)", scale=alt.Scale(zero=False)),
                                                                        tooltip=["날짜:T", alt.Tooltip("Close:Q", format=".4f")])]
    if a.get("levels"):
        lv = pd.DataFrame([{"이름": k, "가격": v, "색": LEVEL_COLORS.get(k, "#888")} for k, v in a["levels"].items()])
        rules = alt.Chart(lv).mark_rule(strokeDash=[5, 3], opacity=.85).encode(y="가격:Q", color=alt.Color("색:N", scale=None), tooltip=["이름:N", alt.Tooltip("가격:Q", format=".4f")])
        labels = alt.Chart(lv).mark_text(align="left", dx=4, dy=-4, fontSize=10).encode(y="가격:Q", text=alt.Text("라벨:N"), color=alt.Color("색:N", scale=None),
                                                                                       x=alt.value(2)).transform_calculate(라벨="datum.이름 + ' $' + format(datum.가격, '.3f')")
        bd = pd.DataFrame({"날짜": [pd.Timestamp(a["base"]["date"])], "이름": ["기준봉"]})
        layers += [rules, labels, alt.Chart(bd).mark_rule(color="#F76B15", opacity=.6).encode(x="날짜:T", tooltip=["이름:N", "날짜:T"])]
    ch = alt.layer(*layers).properties(height=280, title=f"{t} · 일봉 120일 · 기준봉 채널(발·무릎·허리·어깨·머리·보라돌이)")
    chartpop.show(ch, key=f"{key}_lv_{t}", title=f"{t} 채널", data=x, note="주황 세로선 = 기준봉(거래 터진 급등 마디) · 가로 점선 = 채널 자리. 지지/저항 '예상' 자리이지 반드시 지지·도달이 아님")


def profile_chart(t: str, a: dict, key: str) -> None:
    prof = a.get("profile")
    if prof is None or prof.empty:
        return
    p = prof.copy()
    p["가격대"] = [f"${lo:.3f}~{hi:.3f}" for lo, hi in zip(p["lo"], p["hi"])]
    p["mid"] = (p["lo"] + p["hi"]) / 2
    ch = alt.Chart(p).mark_bar().encode(y=alt.Y("mid:Q", title="가격($)", scale=alt.Scale(zero=False)), x=alt.X("share:Q", title="거래량 비중(%)"),
                                        color=alt.Color("kind:N", scale=alt.Scale(domain=["진함", "보통", "공백"], range=["#E5484D", "#8B8D98", "#30A46C"]), title="매물"),
                                        tooltip=["가격대:N", alt.Tooltip("share:Q", format=".1f", title="비중(%)"), "kind:N"])
    px = alt.Chart(pd.DataFrame({"y": [a["px"]]})).mark_rule(color="#E6E8EB", strokeWidth=2).encode(y="y:Q")
    chartpop.show(alt.layer(ch, px).properties(height=280, title="매물대(120일) — 진함 = 시체 많음 · 공백 = 빠르게 통과"), key=f"{key}_pf_{t}", title=f"{t} 매물대",
                  data=p[["가격대", "share", "kind"]].rename(columns={"share": "비중(%)", "kind": "구분"}))


def checklist_table(a: dict) -> pd.DataFrame:
    rows = [{"누구": k["who"], "항목": k["name"], "상태": STATUS_ICON.get(k["status"], "➖"), "내용": k["detail"]} for k in a.get("checks", [])]
    return pd.DataFrame(rows, columns=["누구", "항목", "상태", "내용"])


def signal_chips(a: dict) -> str:
    return "".join(ui.chip(s["name"], SIG_COLOR.get(s["dir"], "gray"), tip=s.get("note") or "") for s in a.get("signals", [])) or ui.chip("신호 없음", "gray")


def section(t: str, df: pd.DataFrame | None, key: str = "cv", intraday: bool = True) -> dict | None:
    """📈 차트 탭 안의 '스승 관점' 구역."""
    a = analysis(t, df, intraday)
    if not a:
        st.caption("📐 스승 관점: 일봉 자료가 25일 미만이라 계산하지 않았어요.")
        return None
    st.markdown(signal_chips(a), unsafe_allow_html=True)
    st.caption("📐 " + a["verdict"])
    c1, c2 = st.columns([3, 2])
    with c1:
        level_chart(t, df, a, key)
    with c2:
        profile_chart(t, a, key)
    tb = checklist_table(a)
    good, bad = int((tb["상태"] == "✅").sum()), int((tb["상태"] == "❌").sum())
    st.caption(f"체크리스트 ✅ {good} · ❌ {bad} · 키쟈키라 = 급등주 눌림목 단타 관점 · ANO = 추세·다이버전스·캔들 관점 (참고용, 매수·매도 권유 아님)")
    st.dataframe(tb, hide_index=True, width="stretch", column_config={"내용": st.column_config.TextColumn(width="large")})
    m60, m5 = a.get("ma_60"), a.get("ma_5")
    bits = []
    if m60:
        bits.append("60분봉 " + ("정배열 확장" if m60["aligned"] else ("20선 위" if m60["alive"] else "약세")) + (f" · 200선 {m60['dist200']:+.1f}%" if m60.get("dist200") is not None else ""))
    if m5:
        bits.append("5분봉 " + ("5·20 꺾임 ❗" if m5["broken"] else ("이평 수렴" if m5["converged"] else ("5선 타고 상승" if m5["riding5"] else "보통")))
                    + (f" · VWAP {m5['dist_vwap']:+.1f}%" if m5.get("dist_vwap") is not None else ""))
    if not intraday or (m60 is None and m5 is None):
        bits.append("60분·5분봉 자료 없음(야후 분봉은 최근 60일·5일만)")
    st.caption(" · ".join(bits))
    return a


def header_chip(t: str, df: pd.DataFrame | None) -> str:
    """🏢 종목 헤더용 칩 HTML(일봉만, 분봉 안 받음)."""
    try:
        a = analysis(t, df, intraday=False)
        c = cv.chip(a)
        return ui.chip(c[0], c[1], tip=a["verdict"]) if c else ""
    except Exception:  # noqa: BLE001
        return ""


def recent_table(days: int = 7, key: str = "cv_recent") -> None:
    with closing(db.connect()) as conn:
        df = cv.recent(conn, days)
    if df.empty:
        st.caption(f"최근 {days}일 기록된 📐 신호가 없어요(아침 작업·스캐너가 후보군을 점검해 기록해요).")
        return
    show = df.rename(columns={"date": "날짜", "ticker": "티커", "name": "신호", "price": "가격($)", "note": "내용"})[["날짜", "티커", "신호", "가격($)", "내용"]]
    st.dataframe(show, hide_index=True, width="stretch", column_config={"가격($)": st.column_config.NumberColumn(format="%.4f"), "내용": st.column_config.TextColumn(width="large")})
