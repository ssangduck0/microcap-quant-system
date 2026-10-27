"""📈 더 오를까 더 내릴까(스승님 꿀팁: 분산·털기·다크풀) — 표의 판정 열, 종목 상세 패널, 신호 기록·검증."""
from contextlib import closing

import pandas as pd
import streamlit as st

import db
import flowread as fr
import intel


def params() -> dict:
    g = st.session_state.get
    return {"spike": float(g("fr_spike", fr.DEFAULTS["spike"])), "dark_high": float(g("fr_dark", fr.DEFAULTS["dark_high"])), "fall_days": fr.DEFAULTS["fall_days"]}


def labels(tickers: list[str], prices: dict) -> dict:
    p = params()
    return {t: fr.verdict(fr.classify(prices.get(t), p)) for t in tickers}


def tip_card() -> None:
    with st.expander("📜 " + fr.TIP_TITLE):
        st.text(fr.TIP_TEXT)
        st.caption("판정 기준(출발값): 전일 대비 거래량 2.5배 이상이면 '급증'. 양봉·음봉은 스승님 예시대로 전일 대비 상승·하락 마감으로 봅니다(시가 대비는 표에 함께 표시). "
                   "다크풀은 FINRA 장외 거래량 ÷ 전체 거래량 근사치이고, 소형주는 평소에도 높을 수 있습니다.")


def render_panel(ticker: str, df: pd.DataFrame | None, key: str = "fr") -> None:
    import pumpsetup
    st.markdown(f"##### 📈 {ticker} 더 오를까 더 내릴까 (스승님 꿀팁: 분산·털기·다크풀)")
    p = params()
    tb = fr.classify(df, p, n=10)
    if tb.empty:
        st.caption("일봉이 부족합니다.")
        tip_card()
        return
    v = fr.verdict(tb)
    (st.error if v.startswith("🔻") else st.success if v.startswith("🔺 털기 확인") else st.warning if v.startswith(("⚠️", "🔺")) else st.caption)(
        f"최근 판정: **{v}**" if v and v != "–" else "최근 3거래일에 거래량 급증(분산·털기) 신호 없음")
    st.dataframe(tb.iloc[::-1], hide_index=True, width="stretch", column_config={
        "종가": st.column_config.NumberColumn(format="%.4f"), "등락(%)": st.column_config.NumberColumn(format="%+.2f"), "거래량": st.column_config.NumberColumn(format="%d"),
        "전일 대비 거래량(배)": st.column_config.NumberColumn(format="%.2f"), "고점 되돌림(%)": st.column_config.NumberColumn(format="%.0f", help="고가에서 종가까지 내려온 정도(0=고가 마감, 100=저가 마감)")})
    with closing(db.connect()) as conn:
        lat = intel.latest(conn, ticker)
        short = (lat[1] or {}).get("short") if lat else None
        dm = fr.dumping(df, pumpsetup.dark_stats(conn, ticker, df), short, p)
        rc = fr.risk_checks(ticker, conn, df)
    if dm["status"]:
        st.error("**다크풀 덤핑·매집 의심** — 대차(공매도 가용잔고)가 넉넉한데 장외 비중이 높고 주가가 빠지고 있어요. 주체가 공매도가 아니라 장외 매도일 수 있습니다. "
                 "아래 리스크를 철저히 확인하세요. · " + dm["text"])
    else:
        st.caption("다크풀: " + dm["text"] + (" — 판정에 필요한 값이 부족합니다" if dm["status"] is None else " — 덤핑·매집 의심 조건 아님"))
    st.dataframe(pd.DataFrame([{"확인 항목": x["항목"], "결과": "➖ 확인 불가" if x["문제"] is None else ("❌ 문제" if x["문제"] else "✅ 없음"), "값": x["값"]} for x in rc]),
                 hide_index=True, width="stretch")
    tip_card()


def render_section() -> None:
    import watch_ui
    st.caption("워치리스트·저금통 종목에서 스캐너가 분산·털기·털기 확인/실패를 처음 잡은 날을 기록합니다. 신호 뒤 5거래일 결과로 꿀팁을 검증해요.")
    with st.expander("⚙️ 기준값"):
        c = st.columns(2)
        c[0].slider("거래량 급증: 전일 대비 배수 ≥", 1.5, 10.0, float(fr.DEFAULTS["spike"]), 0.5, key="fr_spike")
        c[1].slider("다크풀(장외) 비중 ≥ %", 30, 90, int(fr.DEFAULTS["dark_high"]), key="fr_dark")
    ev = fr.events()
    if ev.empty:
        st.info("아직 기록된 신호가 없습니다.")
        tip_card()
        return
    import shortflow
    px = watch_ui.prices(tuple(sorted(ev["ticker"].unique())))
    rows = []
    for e in ev.itertuples():
        oc = shortflow.outcome(px.get(e.ticker), e.date, e.price)
        rows.append({"날짜": e.date, "티커": e.ticker, "판정": e.kind, "가격($)": e.price, "다음날 종가(%)": oc.get("next_close"), "5일 최고(%)": oc.get("max_up"),
                     "5일 최저(%)": oc.get("max_down"), "5일 뒤 종가(%)": oc.get("close_n")})
    od = pd.DataFrame(rows)
    num = {k: st.column_config.NumberColumn(format="%+.1f") for k in ("다음날 종가(%)", "5일 최고(%)", "5일 최저(%)", "5일 뒤 종가(%)")}
    import tosslink_ui
    st.dataframe(tosslink_ui.with_links(od), hide_index=True, width="stretch", column_config={**num, "토스": tosslink_ui.COLUMN, "가격($)": st.column_config.NumberColumn(format="%.4f")})
    agg = od.dropna(subset=["5일 최고(%)"]).groupby("판정").agg(신호=("티커", "size"), 평균_다음날종가=("다음날 종가(%)", "mean"), 평균_5일뒤종가=("5일 뒤 종가(%)", "mean")).reset_index()
    if not agg.empty:
        st.markdown("**판정별 평균** — 꿀팁이 맞다면 분산 뒤에는 내리고(음수), 털기 확인 뒤에는 오르고(양수), 털기 실패 뒤에는 약해야 합니다.")
        st.dataframe(agg, hide_index=True, width="stretch", column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in agg.columns if c.startswith("평균")})
    tip_card()
