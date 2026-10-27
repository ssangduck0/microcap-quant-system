"""🕶 다크풀 화면 — 장외 거래 비중 상위 30 · 5일 추이 · 20일 평균 대비 괴리도 · 신호(급등·연속상승·매집의심) + 종목 카드(🏢 종목 화면용)."""
from contextlib import closing

import pandas as pd
import streamlit as st

import chartpop
import darkpool as dp
import db
import pick as picker
import tosslink_ui
import ui_kit as ui


@st.cache_data(ttl=600, show_spinner=False)
def _top(n: int = 30):
    with closing(db.connect()) as conn:
        day, df = dp.top(conn, n=n)
    return day, df


def _trend_text(tr) -> str:
    return " → ".join(f"{p:.0f}" for _, p in (tr or [])[-dp.TREND_DAYS:])


def render() -> None:
    ui.title("다크풀", "일반 거래창에 안 보이는 장외(다크풀·TRF) 거래 비중이 높은 종목. 비중 = FINRA 장외 거래량 ÷ 그날 전체 거래량. "
             "비중이 갑자기 뛰거나(급등) 며칠 연속 오르면(연속상승) 큰손이 조용히 모으는 중일 수 있어요. 규칙 기반 추정이며 매수 권유가 아닙니다.")
    day, df = _top(30)
    if df is None or df.empty:
        st.info("아직 계산할 데이터가 없어요. FINRA 장외 거래량(매일 저녁)과 일봉이 쌓이면 자동으로 채워져요.")
        return
    n50 = int((df["dp_pct"] >= 50).sum())
    sig = df[df["flags"].map(bool)]
    ui.cards([{"t": "DP 50%↑ 종목(상위 30 중)", "v": f"{n50}개", "accent": True}, {"t": "평균 DP 비율(상위 30)", "v": f"{df['dp_pct'].mean():.1f}%"},
              {"t": "DP 1위", "v": df.iloc[0]["ticker"], "s": f"{df.iloc[0]['dp_pct']:.1f}%"}, {"t": "시그널 감지", "v": f"{len(sig)}종목", "s": "급등·연속상승·매집의심"}])
    st.caption(f"{day} 기준(FINRA 는 미국 장 마감 뒤 저녁에 공개) · 장외 거래량 {dp.MIN_DP_VOL:,}주 미만 종목 제외 · 급등 = 20일 평균 대비 +{dp.SPIKE_PP:.0f}%p · 연속상승 = 4일 연속 증가")
    flt = st.radio("보기", ["전체", "시그널", "급등", "연속상승", "매집의심"], horizontal=True, key="dp_flt", label_visibility="collapsed")
    v = df if flt == "전체" else (sig if flt == "시그널" else df[df["flags"].map(lambda f: flt in f)])
    if v.empty:
        st.caption("해당하는 종목이 없습니다.")
        return
    import rank_ui
    tb = pd.DataFrame({"티커": v["ticker"], "신호": v["flags"].map(lambda f: " · ".join(f)), "DP%": v["dp_pct"], "20일 평균": v["avg20"], "괴리도(%p)": v["gap"],
                       "전일비(%p)": v["prev_diff"], "DP 거래량": v["dp_vol"], "전체 거래량": v["vol"], "장외 공매도%": v["short_pct"], "5일 추이": v["trend"].map(_trend_text),
                       "매집 합계": v["accum"]})
    tb.insert(1, "토스", tosslink_ui.links(tb["티커"]))
    tb.insert(2, "종합 순위", rank_ui.column(tb["티커"]))
    cfg = {"토스": tosslink_ui.COLUMN, "DP%": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
           "20일 평균": st.column_config.NumberColumn(format="%.1f"), "괴리도(%p)": st.column_config.NumberColumn(format="%+.1f"), "전일비(%p)": st.column_config.NumberColumn(format="%+.1f"),
           "DP 거래량": st.column_config.NumberColumn(format="%,.0f"), "전체 거래량": st.column_config.NumberColumn(format="%,.0f"), "장외 공매도%": st.column_config.NumberColumn(format="%.0f")}
    t = picker.clickable(tb, list(tb["티커"]), "dp_table", hide_index=True, width="stretch", column_config=cfg)
    if t:
        st.markdown(f"#### {t}")
        card(t, key="dp_page")
        st.markdown("**📊 매매강도(토스 실시간 체결 · 금액 구간별)**")
        import flow_ui
        flow_ui.card(t, key="dp")


def card(t: str, key: str = "co") -> None:
    """🏢 종목 화면 카드: 최신 비중 · 20일 평균 · 괴리도 · 전일비 + 25일 추이 차트(클릭 → 팝업)."""
    with closing(db.connect()) as conn:
        s = dp.series(conn, t)
        st_ = dp._stats(s) if not s.empty else {}
    if not st_:
        st.caption("다크풀 기록이 없어요(FINRA 장외 거래량 또는 일봉 없음).")
        return
    ui.cards([{"t": "DP 비율(최근)", "v": f"{st_['dp_pct']:.1f}%", "s": st_["date"], "accent": st_["dp_pct"] >= dp.SIGNAL_DP},
              {"t": "20일 평균", "v": "-" if st_["avg20"] is None else f"{st_['avg20']:.1f}%"},
              {"t": "괴리도(vs 20일)", "v": "-" if st_["gap"] is None else f"{st_['gap']:+.1f}%p", "s": "급등" if st_["spike"] else ("연속상승" if st_["rising"] else "")},
              {"t": "DP 거래량 / 전체", "v": f"{st_['dp_vol'] / 1e6:.1f}M / {st_['vol'] / 1e6:.1f}M", "s": "" if st_["prev_diff"] is None else f"전일비 {st_['prev_diff']:+.1f}%p"}])
    d = s.dropna(subset=["dp_pct"]).set_index("date")
    if not d.empty:
        chartpop.line(d[["dp_pct", "short_pct"]].rename(columns={"dp_pct": "DP 비중(%)", "short_pct": "장외 공매도 비중(%)"}), key=f"dp_{key}_{t}",
                      title=f"{t} 다크풀 비중 추이(최근 {len(d)}거래일)", height=180, y_title="%", zero=True, fmt=".1f",
                      note="DP 비중 = FINRA 장외 거래량 ÷ 전체 거래량. 장외 공매도 비중 = 장외 거래 중 공매도 표시 비율(FINRA).")
