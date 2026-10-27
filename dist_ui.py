"""수익률 분포 차트 — 승률 숫자 뒤에 숨은 극단값(+100% 펌핑)과 하방 깊이를 한눈에 (Altair, 추가 설치 없음)."""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import chartpop

CLIP = 200.0


def tail_stats(sub: pd.DataFrame) -> dict:
    hi = sub["next_high_pct"].dropna()
    lo = (sub["next_low_pct"] if "next_low_pct" in sub else pd.Series(dtype=float)).dropna()
    dn5 = (sub["max_down_5d"] if "max_down_5d" in sub else pd.Series(dtype=float)).dropna()
    q = lambda s, p: None if s.empty else float(np.percentile(s, p))  # noqa: E731
    return {"n": int(len(hi)), "p50": None if hi.empty else float((hi >= 50).mean() * 100), "p100": None if hi.empty else float((hi >= 100).mean() * 100),
            "hi_p90": q(hi, 90), "hi_med": q(hi, 50), "lo_p10": q(lo, 10), "dn5_p10": q(dn5, 10)}


def render(sub: pd.DataFrame, target: float, key: str = "dist") -> None:
    if sub is None or sub.empty or sub["next_high_pct"].dropna().empty:
        return
    s = tail_stats(sub)
    f = lambda x: "-" if x is None else f"{x:+.0f}%"  # noqa: E731
    m = st.columns(5)
    m[0].metric("다음날 고가 중앙값", f(s["hi_med"]))
    m[1].metric("상위 10% 다음날 고가", f(s["hi_p90"]), help="10건 중 가장 잘 된 1건 수준")
    m[2].metric("+50% 이상 / +100% 이상", f"{s['p50']:.1f}% / {s['p100']:.1f}%", help="극단적 펌핑이 얼마나 자주 나왔는지")
    m[3].metric("하위 10% 다음날 저가", f(s["lo_p10"]), help="잘못됐을 때 다음날 장중에 얼마나 깊이 빠졌는지")
    m[4].metric("하위 10% 5일 내 최저", f(s["dn5_p10"]))
    d = sub.copy()
    cols = [c for c in ("next_high_pct", "next_close_pct") if c in d]
    long = d[cols].rename(columns={"next_high_pct": "다음날 고가", "next_close_pct": "다음날 종가"}).melt(var_name="지표", value_name="수익률(%)").dropna()
    long["수익률(%)"] = long["수익률(%)"].clip(-100, CLIP)
    hist = alt.Chart(long).mark_bar(opacity=0.6).encode(
        x=alt.X("수익률(%):Q", bin=alt.Bin(step=5), title=f"수익률(%) — {CLIP:.0f}% 이상은 {CLIP:.0f}%로 묶음"),
        y=alt.Y("count():Q", stack=None, title="사건 수"), color=alt.Color("지표:N"), tooltip=["지표:N", "count():Q"]).properties(height=240)
    rule = alt.Chart(pd.DataFrame({"x": [target]})).mark_rule(strokeDash=[4, 4], color="#d62728").encode(x="x:Q")
    chartpop.show(hist + rule, key="dist_hist", title="수익률 분포(사건 수)")
    if "next_low_pct" in d:
        sc = d.dropna(subset=["next_high_pct", "next_low_pct"]).copy()
        sc["다음날 고가(%)"] = sc["next_high_pct"].clip(upper=CLIP)
        sc["다음날 저가(%)"] = sc["next_low_pct"]
        sc["성공"] = np.where(sc["next_high_pct"] >= target, f"고가 ≥ +{target:g}%", "미달")
        tips = [c for c in ("ticker", "date") if c in sc] + ["다음날 고가(%)", "다음날 저가(%)"]
        pts = alt.Chart(sc).mark_circle(size=28, opacity=0.5).encode(
            x=alt.X("다음날 저가(%):Q", title="다음날 저가(%) — 리스크"), y=alt.Y("다음날 고가(%):Q", title="다음날 고가(%) — 리워드"),
            color=alt.Color("성공:N"), tooltip=tips).properties(height=260).interactive()
        chartpop.show(pts, key="dist_scatter", title="다음날 고가·저가 분포", data=sc, click=False)
        st.caption("점 하나가 과거 사건 하나입니다. 위로 높이 뜬 점이 극단적 펌핑, 왼쪽 멀리 있는 점이 깊은 하방입니다. 일봉이라 고가·저가 중 무엇이 먼저였는지는 알 수 없습니다.")
