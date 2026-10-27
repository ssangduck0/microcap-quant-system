"""🩳 공매도 흐름(스승님 꿀팁) 화면 조각 — 워치리스트·저금통 표의 단계 열, 종목 상세 패널, 신호 기록·검증."""
from contextlib import closing

import pandas as pd
import streamlit as st

import db
import intel
import shortflow as sf

STAGE_BOX = {sf.STAGES[0]: "warning", sf.STAGES[1]: "info", sf.STAGES[2]: "success", sf.STAGES[3]: "info", sf.STAGES[4]: "caption"}


def params() -> dict:
    g = st.session_state.get
    d = sf.DEFAULTS
    return {"lookback": d["lookback"], "near_pct": float(g("sf_near", d["near_pct"])), "vol_drop": g("sf_vol", int(d["vol_drop"] * 100)) / 100,
            "flat_pct": float(g("sf_flat", d["flat_pct"])), "bounce_pct": float(g("sf_bounce", d["bounce_pct"])), "min_cycles": int(g("sf_cycles", d["min_cycles"])),
            "cover_n": int(g("sf_cover", d["cover_n"])), "cover_max": d["cover_max"], "body_max_pct": float(g("sf_body", d["body_max_pct"])),
            "cover_vol_max": d["cover_vol_max"], "lift_pct": float(g("sf_lift", d["lift_pct"])), "lift_vol": float(g("sf_liftvol", d["lift_vol"]))}


def live_metrics(tickers: list[str]) -> dict:
    """오늘 스캐너 값(장중 등락·거래량 배수). 오늘 기록이 없으면 비움(일봉으로 판정)."""
    if not tickers:
        return {}
    df = db.read_df(f"SELECT ticker, date, day_change_pct, volume_mult FROM daily_snapshots WHERE ticker IN ({','.join('?' * len(tickers))}) ORDER BY date DESC",
                    tuple(tickers)).drop_duplicates("ticker")
    if df.empty:
        return {}
    today = df["date"].max()
    return {r.ticker: {"day_change_pct": r.day_change_pct, "volume_mult": r.volume_mult} for r in df.itertuples() if r.date == today}


def short_of(ticker: str) -> dict | None:
    with closing(db.connect()) as conn:
        lat = intel.latest(conn, ticker)
    return (lat[1] or {}).get("short") if lat else None


def stages(tickers: list[str], prices: dict) -> dict:
    lm, p = live_metrics(tickers), params()
    out = {}
    for t in tickers:
        r = sf.analyze(prices.get(t), p, lm.get(t), short_of(t))
        out[t] = r["stage"] if r else "데이터 부족"
    return out


def tip_card() -> None:
    with st.expander(f"📜 {sf.TIP_TITLE}"):
        st.text(sf.TIP_TEXT)
        st.caption(sf.CAVEAT)


def settings() -> None:
    with st.expander("⚙️ 공매도 흐름 기준값 (스승님이 숫자를 주지 않아 출발값입니다)"):
        a = st.columns(4)
        a[0].slider("① 저점 근처: 저점의 +%", 5, 40, int(sf.DEFAULTS["near_pct"]), key="sf_near")
        a[1].slider("① 거래량 감소: 이전의 %", 30, 100, int(sf.DEFAULTS["vol_drop"] * 100), key="sf_vol")
        a[2].slider("① 횡보: 10일 가격 폭 ≤ %", 5, 50, int(sf.DEFAULTS["flat_pct"]), key="sf_flat")
        a[3].slider("② 반등 인정: +%", 5, 40, int(sf.DEFAULTS["bounce_pct"]), key="sf_bounce")
        b = st.columns(4)
        b[0].slider("② 반복 횟수 ≥", 1, 6, int(sf.DEFAULTS["min_cycles"]), key="sf_cycles")
        b[1].slider("③ 얇은 양봉 연속 ≥", 2, 8, int(sf.DEFAULTS["cover_n"]), key="sf_cover")
        b[2].slider("③ 양봉 몸통 ≤ %", 1.0, 8.0, float(sf.DEFAULTS["body_max_pct"]), 0.5, key="sf_body")
        b[3].slider("④ 들어올림: 상승 ≥ %", 5, 60, int(sf.DEFAULTS["lift_pct"]), key="sf_lift")
        st.slider("④ 들어올림: 거래량 ≥ 평균 배수", 1.0, 10.0, float(sf.DEFAULTS["lift_vol"]), 0.5, key="sf_liftvol")


def render_panel(ticker: str, df: pd.DataFrame | None, key: str = "sf") -> None:
    st.markdown(f"##### 🩳 {ticker} 공매도 흐름 (스승님 꿀팁)")
    r = sf.analyze(df, params(), live_metrics([ticker]).get(ticker), short_of(ticker))
    if not r:
        st.caption("일봉이 부족해서 판정할 수 없습니다(최근 40거래일 이상 필요).")
        tip_card()
        return
    box = STAGE_BOX.get(r["stage"], "caption")
    getattr(st, box)(f"지금 단계: **{r['stage']}**")
    st.dataframe(pd.DataFrame([{**i, "결과": "✅" if i["결과"] else "❌"} for i in r["items"]]), hide_index=True, width="stretch")
    for h in r["hints"]:
        st.caption("보조 신호: " + h)
    tip_card()


def render_tab(tickers: list[str], prices: dict) -> None:
    st.caption("⭐ 워치리스트(블랙 제외)와 🐷 저금통 종목에 스승님의 '공매도 흐름' 꿀팁을 적용한 단계입니다. ②③④ 단계에 처음 들어가면 스캐너가 기록하고 텔레그램으로 알려 줍니다.")
    settings()
    if not tickers:
        st.info("워치리스트나 저금통에 종목이 없습니다.")
        return
    stg = stages(tickers, prices)
    tb = pd.DataFrame([{"티커": t, "단계": s} for t, s in stg.items()])
    tb["_o"] = tb["단계"].map({s: i for i, s in enumerate(sf.STAGES)}).fillna(9)
    tb = tb.sort_values(["_o", "티커"]).drop(columns="_o")
    st.dataframe(tb, hide_index=True, width="stretch")
    st.markdown("**신호 기록 · 검증** (신호가 난 뒤 5거래일: 최고·최저·다음날 종가·5일 뒤 종가, 신호 가격 대비 %)")
    ev = sf.events()
    if ev.empty:
        st.caption("아직 기록된 신호가 없습니다. 스캐너가 ②③④ 단계를 처음 잡으면 쌓입니다.")
        return
    import watch_ui
    px = watch_ui.prices(tuple(sorted(ev["ticker"].unique())))
    rows = []
    for e in ev.itertuples():
        oc = sf.outcome(px.get(e.ticker), e.date, e.price)
        rows.append({"날짜": e.date, "티커": e.ticker, "단계": e.stage, "신호 가격($)": e.price, "확인 일수": oc.get("days"), "5일 최고(%)": oc.get("max_up"),
                     "5일 최저(%)": oc.get("max_down"), "다음날 종가(%)": oc.get("next_close"), "5일 뒤 종가(%)": oc.get("close_n")})
    od = pd.DataFrame(rows)
    num = {c: st.column_config.NumberColumn(format="%+.1f") for c in ("5일 최고(%)", "5일 최저(%)", "다음날 종가(%)", "5일 뒤 종가(%)")}
    num["신호 가격($)"] = st.column_config.NumberColumn(format="%.4f")
    import tosslink_ui
    st.dataframe(tosslink_ui.with_links(od), hide_index=True, width="stretch", column_config={**num, "토스": tosslink_ui.COLUMN})
    agg = od.dropna(subset=["5일 최고(%)"]).groupby("단계").agg(신호=("티커", "size"), 평균_5일최고=("5일 최고(%)", "mean"), 평균_5일최저=("5일 최저(%)", "mean"),
                                                             평균_다음날종가=("다음날 종가(%)", "mean"), 평균_5일뒤종가=("5일 뒤 종가(%)", "mean")).reset_index()
    if not agg.empty:
        st.markdown("**단계별 평균** — 꿀팁이 맞다면: ② 뒤에는 오르고, ③ 뒤에는 한 번 눌렸다가(5일 최저 음수) 오르고, ④ 뒤에는 다음날 종가가 내려가야 합니다.")
        st.dataframe(agg, hide_index=True, width="stretch", column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in agg.columns if c.startswith("평균")})
        if agg["신호"].sum() < 20:
            st.caption(f"신호 {int(agg['신호'].sum())}건 — 20건 이상 쌓여야 꿀팁이 실제로 맞는지 판단할 수 있어요.")
