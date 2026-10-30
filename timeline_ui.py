"""희석·기한 이벤트 타임라인 — 공시(424B·S-1/F-1·EFFECT·8-K 3.01 등), 일정(락업·워런트 만기·주총·역분할·호재), 물량 장부 만기를 시간축에 점으로."""
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import chartpop

import db


def events_for(ticker: str) -> pd.DataFrame:
    t = ticker.upper()
    rows = []
    rep = db.get_report(t) or {}
    for e in rep.get("timeline") or []:
        rows.append({"날짜": e.get("date"), "줄": "공시", "종류": e.get("type") or "공시", "내용": e.get("text") or "", "원문": e.get("url") or ""})
    try:
        import watch
        ev = watch.events_df([t])
        for e in ev.itertuples():
            lane = "일정(만기·기한)" if any(k in e.kind for k in ("만기", "락업", "기한")) else ("일정(희석)" if e.kind in ("희석 임박", "발행") else "일정(기타)")
            rows.append({"날짜": e.date, "줄": lane, "종류": e.kind, "내용": e.title, "원문": e.source or ""})
        oh = watch.overhang_rows(t)
        for o in oh.itertuples():
            if o.expiry:
                rows.append({"날짜": o.expiry, "줄": "물량 장부 만기", "종류": o.kind, "내용": f"{o.kind} {o.qty_m or '-'}M주 @ ${o.price or '-'} ({o.status})", "원문": o.source or ""})
    except Exception:  # noqa: BLE001
        pass
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    return df.dropna(subset=["날짜"]).drop_duplicates(subset=["날짜", "종류", "내용"])


def render(ticker: str, key: str = "tl", back_days: int = 365, ahead_days: int = 365) -> None:
    df = events_for(ticker)
    st.markdown(f"##### 🗓 {ticker} 희석·기한 타임라인")
    if df.empty:
        st.caption("표시할 공시·일정이 없습니다. 🗂 종목 리포트를 만들거나 ⭐ 워치리스트에서 '공시에서 후보 찾기'를 하면 채워집니다.")
        return
    today = pd.Timestamp(date.today())
    df = df[(df["날짜"] >= today - timedelta(days=back_days)) & (df["날짜"] <= today + timedelta(days=ahead_days))]
    if df.empty:
        st.caption(f"최근 {back_days}일 ~ 앞으로 {ahead_days}일 사이 이벤트가 없습니다.")
        return
    df["시점"] = df["날짜"].map(lambda d: "앞으로" if d >= today else "지남")
    base = alt.Chart(df).encode(x=alt.X("날짜:T", title=None), y=alt.Y("줄:N", title=None, sort=["공시", "일정(희석)", "일정(만기·기한)", "물량 장부 만기", "일정(기타)"]))
    pts = base.mark_point(size=110, filled=True, opacity=0.85).encode(color=alt.Color("종류:N", legend=alt.Legend(orient="bottom", columns=4)),
                                                                     shape=alt.Shape("시점:N"), tooltip=[alt.Tooltip("날짜:T", format="%Y-%m-%d"), "종류:N", "내용:N"])
    now = alt.Chart(pd.DataFrame({"x": [today]})).mark_rule(color="#d62728", strokeDash=[4, 4]).encode(x="x:T")
    chartpop.show((pts + now).properties(height=60 + 34 * df["줄"].nunique()).interactive(), key="timeline", title="타임라인(공시·일정)", data=df, click=False)
    up = df[df["시점"] == "앞으로"].sort_values("날짜").head(5)
    if not up.empty:
        st.caption("다가오는 것: " + " · ".join(f"{d:%m-%d} {k}" for d, k in zip(up["날짜"], up["종류"])) + " — 오버행 물량이 나올 수 있는 시점(빨간 점선 = 오늘)")
