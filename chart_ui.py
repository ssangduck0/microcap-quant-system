"""📈 차트 분석 — 종합 순위 1~5위 자동 차트 + 보조지표 설정(이동평균 2~3개 · RSI · MACD · 일목균형표 구름 두께)."""
import json

import altair as alt
import pandas as pd
import streamlit as st

import chartpop

import access
import db
import ta
import ui_kit as ui


def settings() -> dict:
    m = db.get_meta("ta_settings")
    try:
        saved = json.loads(m["value"]) if m and m.get("value") else {}
    except (TypeError, ValueError):
        saved = {}
    return {**ta.DEFAULTS, **saved, **st.session_state.get("_ta_tmp", {})}


def settings_box() -> dict:
    p = settings()
    with st.expander("⚙️ 보조지표 설정"):
        c1, c2, c3 = st.columns(3)
        ma = [c1.number_input(f"이동평균 {i + 1}", 0, 250, int(v), key=f"ta_ma{i}") for i, v in enumerate((p["ma"] + [0, 0, 0])[:3])]
        rsi_n = c2.number_input("RSI 기간", 2, 50, int(p["rsi_n"]), key="ta_rsi_n")
        rsi_low = c2.number_input("RSI 바닥 기준", 5, 50, int(p["rsi_low"]), key="ta_rsi_low")
        m1 = c3.number_input("MACD 빠른선", 2, 50, int(p["macd"][0]), key="ta_m1")
        m2 = c3.number_input("MACD 느린선", 3, 100, int(p["macd"][1]), key="ta_m2")
        m3 = c3.number_input("MACD 시그널", 2, 50, int(p["macd"][2]), key="ta_m3")
        d1, d2, d3, d4 = st.columns(4)
        ichi = [d1.number_input("일목 전환선", 2, 60, int(p["ichi"][0]), key="ta_i1"), d2.number_input("일목 기준선", 2, 120, int(p["ichi"][1]), key="ta_i2"),
                d3.number_input("일목 선행스팬B", 2, 240, int(p["ichi"][2]), key="ta_i3")]
        thin = d4.number_input("구름 '얇음' 기준(%)", 0.1, 50.0, float(p["cloud_thin"]), 0.5, key="ta_thin", help="구름 두께 = |선행스팬A − 선행스팬B| ÷ 주가. 이 값 이하면 얇은 구름(돌파·이탈이 쉬움)")
        cross = st.slider("골든·데드크로스를 찾을 최근 일수", 1, 20, int(p["cross_days"]), key="ta_cross")
        newp = {"ma": [int(x) for x in ma if x], "rsi_n": int(rsi_n), "rsi_low": int(rsi_low), "macd": [int(m1), int(m2), int(m3)], "ichi": [int(x) for x in ichi],
                "cloud_thin": float(thin), "cross_days": int(cross), "lookback": int(p["lookback"])}
        st.session_state["_ta_tmp"] = newp
        if not access.is_guest() and st.button("이 설정 저장(다음에도 사용)", key="ta_save"):
            db.set_meta("ta_settings", json.dumps(newp))
            st.success("저장했어요.")
    return settings()


def chart(t: str, df: pd.DataFrame, p: dict) -> None:
    x = ta.compute(df, p).tail(int(p["lookback"])).reset_index()
    x = x.rename(columns={x.columns[0]: "날짜"})
    # 세 차트를 따로 그리고 날짜 범위를 똑같이 맞춤(예전엔 vconcat 이라 화면 폭에 안 맞고 오른쪽으로 넘쳐 최근 구간이 잘렸음)
    dom = [pd.Timestamp(x["날짜"].min()).isoformat(), pd.Timestamp(x["날짜"].max()).isoformat()]
    base = alt.Chart(x).encode(x=alt.X("날짜:T", title=None, scale=alt.Scale(domain=dom)))
    cloud = base.mark_area(opacity=.18, color="#30A46C").encode(y="span_a:Q", y2="span_b:Q")
    price = base.mark_line(color="#E6E8EB", strokeWidth=1.8).encode(y=alt.Y("Close:Q", title="가격($)", scale=alt.Scale(zero=False)),
                                                                     tooltip=["날짜:T", alt.Tooltip("Close:Q", format=".4f")])
    colors = ["#F76B15", "#3678F6", "#8E4EC6"]
    mas = [base.mark_line(color=colors[i % 3], strokeWidth=1.2).encode(y=f"MA{n}:Q") for i, n in enumerate(p["ma"]) if f"MA{n}" in x]
    top = alt.layer(cloud, price, *mas).properties(height=260, title=f"{t} · 가격 · 이동평균(" + "/".join(map(str, p["ma"])) + ") · 일목 구름")
    rs = alt.layer(base.mark_line(color="#E5484D").encode(y=alt.Y("RSI:Q", scale=alt.Scale(domain=[0, 100]), title="RSI")),
                   alt.Chart(pd.DataFrame({"y": [p["rsi_low"], 70]})).mark_rule(strokeDash=[4, 4], opacity=.5).encode(y="y:Q")).properties(height=110)
    md = alt.layer(base.mark_bar(opacity=.5).encode(y=alt.Y("hist:Q", title="MACD"), color=alt.condition("datum.hist > 0", alt.value("#30A46C"), alt.value("#E5484D"))),
                   base.mark_line(color="#3678F6").encode(y="macd:Q"), base.mark_line(color="#F76B15").encode(y="signal:Q")).properties(height=110)
    for nm, ch in (("가격·이동평균", top), ("RSI", rs), ("MACD", md)):
        chartpop.show(ch, key=f"ta_{nm}_{t}", title=f"{t} {nm}", data=x)


def render() -> None:
    import rank_ui
    import watch_ui
    ui.title("차트 분석", "종합 순위 1~5위를 자동으로 그리고 보조지표 신호를 정리해요. 신호는 참고용이며 매수·매도 권유가 아닙니다.")
    p = settings_box()
    with st.expander("📐 최근 7일 스승 관점 신호(눌림 타점 · 60분 200선 돌파 · 골든크로스 · 이탈 경고)"):
        import chartview_ui
        chartview_ui.recent_table(7)
    df_rank = rank_ui.table()
    top = [] if df_rank.empty else list(df_rank["ticker"].head(5))
    c1, c2 = st.columns([3, 1])
    extra = c2.text_input("다른 티커", key="ta_extra", placeholder="예: HUBC").strip().upper()
    picks = top + ([extra] if extra and extra not in top else [])
    if not picks:
        st.info("종합 순위가 아직 없어요. 다른 티커를 입력해 보세요.")
        return
    c1.caption("종합 순위 TOP5: " + (" · ".join(f"{i + 1}. {t}" for i, t in enumerate(top)) or "-"))
    data = watch_ui.prices(tuple(picks))
    for t, tab in zip(picks, st.tabs([f"{i + 1}. {t}" if t in top else t for i, t in enumerate(picks)])):
        with tab:
            df = data.get(t)
            if df is None or len(df.dropna()) < 30:
                st.caption("가격 자료가 부족해요.")
                continue
            sig = ta.signals(ta.compute(df, p), p)
            st.markdown(" ".join(ui.chip(n, {"good": "green", "bad": "red"}.get(k, "gray"), tip=d) for n, d, k in sig["items"]) or ui.chip("뚜렷한 신호 없음", "gray"),
                        unsafe_allow_html=True)
            st.caption(" · ".join(f"{n}: {d}" for n, d, _ in sig["items"]))
            chart(t, df, p)
            with st.expander("📐 스승 관점 — 기준봉 채널 · 매물대 · 키쟈키라/ANO 체크리스트", expanded=True):   # 2026-10-27 래빗스탁 차트 고수 관점
                import chartview_ui
                chartview_ui.section(t, df, key="ta_cv")
