"""'발견 종목 추적' 탭: 스캐너가 발견한 종목이 그 뒤 실제로 올랐는지(성공률)를 보여준다."""
import numpy as np
import pandas as pd
import streamlit as st

import db
import tracker

BASIS = {"다음날 고가": "next_high_pct", "5일 내 최고가": "max_up_5d", "다음날 종가": "next_close_pct"}


@st.cache_data(ttl=60)
def load_tracking() -> pd.DataFrame:
    tracker.ensure_table()  # 테이블이 없으면(예: db.py 가 이전 버전) 스스로 만든다
    return db.read_df(
        "SELECT s.date, s.ticker, s.last_seen, s.price AS scan_price, s.drawdown_pct, s.day_change_pct, s.volume_mult, s.dilution_status, "
        "s.excluded, s.quant_score, s.pump_score, s.win_score, s.win_p, o.entry_close, o.next_open_pct, o.next_high_pct, o.next_low_pct, "
        "o.next_close_pct, o.fwd_3d, o.fwd_5d, o.fwd_10d, o.max_up_5d, o.max_down_5d, o.bars_after, o.complete "
        "FROM daily_snapshots s LEFT JOIN tracked_outcomes o ON o.date=s.date AND o.ticker=s.ticker")


def add_held_close(df: pd.DataFrame) -> pd.DataFrame:
    """마지막 스캔이 정규장 마감 30분 전(동부 15:30) 이후인가 = 마감 무렵에도 조건이 유지된 종목."""
    ls = pd.to_datetime(df["last_seen"], utc=True).dt.tz_convert("America/New_York")
    cut = pd.to_datetime(df["date"]).dt.tz_localize("America/New_York") + pd.Timedelta(hours=15, minutes=30)
    return df.assign(held_close=ls >= cut)


def judge(df: pd.DataFrame, basis: str, target: float) -> pd.DataFrame:
    """성공/확인 여부. 5일 내 최고가는 이미 도달했으면 확정 성공, 아니면 5거래일이 지나야 확정(아직이면 미확인)."""
    col = BASIS[basis]
    v = df[col]
    if basis == "5일 내 최고가":
        hit = v >= target
        known = hit | (df["bars_after"].fillna(-1) >= 5)
    else:
        hit = v >= target
        known = v.notna()
    return df.assign(hit=hit & known, known=known)


def render() -> None:
    st.subheader("📒 발견 종목 추적 — 스캐너가 발견한 종목은 그 뒤 어떻게 됐나")
    raw = load_tracking()
    if raw.empty:
        st.info("아직 스캐너가 저장한 종목이 없습니다.")
        return
    raw = add_held_close(raw)
    n_out = int(raw["entry_close"].notna().sum())
    if n_out == 0:
        st.info("결과가 아직 없습니다. 미국 장 마감 후 `python cases.py update`(또는 `python tracker.py update`)를 실행하면 "
                "발견한 종목의 다음날·5일 후 결과가 채워집니다. 작업 스케줄러에 등록해 두면 자동으로 채워져요.")
    st.caption("진입가 = 발견한 날 정규장 종가(일봉). 결과는 진입가 대비 %이며, 체결가·수수료·호가 공백은 반영되지 않습니다. "
               "매매 없이 '이 조건으로 골랐다면 어땠을지'를 쌓는 기록입니다.")

    dmin, dmax = pd.to_datetime(raw["date"].min()).date(), pd.to_datetime(raw["date"].max()).date()
    f1, f2, f3, f4 = st.columns(4)
    rng = f1.date_input("발견 기간", (dmin, dmax), min_value=dmin, max_value=dmax, key="trk_rng")
    basis = f2.selectbox("성공 기준", list(BASIS), key="trk_basis")
    target = f3.slider("성공 기준: +N% 이상", 1, 50, 10, key="trk_target")
    topn = f4.number_input("하루 상위 N개만 (0=전체)", 0, 200, 0, key="trk_topn", help="승률 점수(없으면 퀀트 점수) 순위")
    g1, g2, g3, g4 = st.columns(4)
    held = g1.checkbox("마감 무렵까지 조건 유지된 종목만", True, key="trk_held",
                       help="마지막 스캔이 미국 동부 15:30 이후인 종목 — '장 마감 무렵에 산다'와 같은 조건. 장 초반에만 잡혔다 사라진 종목을 제외")
    no_atm = g2.checkbox("ATM 정황 종목 제외", False, key="trk_atm")
    crash = g3.checkbox("오늘 등락 -10% 이하만", False, key="trk_crash")
    min_ws = g4.slider("승률 점수 ≥", 0, 100, 0, key="trk_ws")
    statuses = st.multiselect("희석 상태", sorted(raw["dilution_status"].dropna().unique()), default=sorted(raw["dilution_status"].dropna().unique()), key="trk_status")

    d0, d1 = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (dmin, dmax)
    base = raw[(raw["date"] >= str(d0)) & (raw["date"] <= str(d1))].copy()          # 기준선: 기간만 맞춘 전체 발견 종목
    sel = base[base["dilution_status"].isin(statuses)]
    if held:
        sel = sel[sel["held_close"]]
    if no_atm:
        sel = sel[sel["excluded"] == 0]
    if crash:
        sel = sel[sel["day_change_pct"] <= -10]
    if min_ws > 0:
        sel = sel[sel["win_score"] >= min_ws]
    if topn:
        rank = sel["win_score"].fillna(sel["quant_score"].fillna(0) - 1000)   # 승률 점수가 없는 종목은 뒤로(퀀트 점수 순)
        sel = sel.assign(_r=rank).sort_values(["date", "_r"], ascending=[True, False]).groupby("date").head(int(topn)).drop(columns="_r")

    sel, base = judge(sel, basis, target), judge(base, basis, target)
    known, hits = int(sel["known"].sum()), int(sel["hit"].sum())
    rate = hits / known * 100 if known else None
    brate = base["hit"].sum() / base["known"].sum() * 100 if base["known"].sum() else None
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("발견 종목-일", f"{len(sel):,}", help=f"{sel['ticker'].nunique():,}개 종목")
    m2.metric("결과 확인", f"{known:,}", help="장 마감 후 일봉이 확정돼야 채워짐")
    m3.metric(f"성공 (≥ +{target}%)", f"{hits:,}")
    m4.metric("성공률", f"{rate:.1f}%" if rate is not None else "-",
              delta=None if rate is None or brate is None else f"{rate - brate:+.1f}%p vs 조건 없이 전체 {brate:.1f}%", delta_color="off")
    ok = sel[sel["known"]]
    m5.metric("다음날 종가 중앙값", f"{ok['next_close_pct'].median():+.1f}%" if ok["next_close_pct"].notna().any() else "-",
              help="성공률만 높고 이 값이 낮으면 손실이 큰 종목이 섞여 있다는 뜻")
    if known == 0:
        st.info("조건에 맞고 결과가 확인된 종목이 아직 없습니다.")
        return
    if known < 30:
        st.warning(f"결과가 확인된 종목이 {known}건뿐이라 성공률이 우연에 크게 흔들립니다. 몇 주 쌓인 뒤에 판단하세요.")

    day = sel.groupby("date").agg(발견=("ticker", "size"), 확인=("known", "sum"), 성공=("hit", "sum")).reset_index()
    day["성공률(%)"] = day["성공"] / day["확인"].replace(0, np.nan) * 100
    day["누적 성공률(%)"] = day["성공"].cumsum() / day["확인"].cumsum().replace(0, np.nan) * 100
    day = day.rename(columns={"date": "발견일"})
    c1, c2 = st.columns([1, 1])
    c1.markdown("**날짜별 (예: 발견 10 · 성공 4 → 40%)**")
    c1.dataframe(day.sort_values("발견일", ascending=False), hide_index=True, width="stretch", column_config={
        "성공률(%)": st.column_config.NumberColumn(format="%.1f"), "누적 성공률(%)": st.column_config.NumberColumn(format="%.1f")})
    c2.markdown("**누적 성공률 추이**")
    c2.line_chart(day.set_index("발견일")["누적 성공률(%)"])

    st.markdown("**발견 종목 목록** (최근순, 화면에는 최대 1,000건 · CSV는 전체)")
    show = sel.sort_values(["date", "win_score"], ascending=[False, False]).rename(columns={
        "date": "발견일", "ticker": "티커", "entry_close": "진입가(종가,$)", "day_change_pct": "그날 등락(%)", "volume_mult": "거래량 배수",
        "dilution_status": "희석 상태", "win_score": "승률 점수", "quant_score": "퀀트점수", "next_open_pct": "다음날 시가(%)",
        "next_high_pct": "다음날 고가(%)", "next_low_pct": "다음날 저가(%)", "next_close_pct": "다음날 종가(%)", "fwd_5d": "5일 후(%)",
        "max_up_5d": "5일 내 최고(%)", "max_down_5d": "5일 내 최저(%)", "hit": "성공", "known": "확인"})
    cols = ["발견일", "티커", "진입가(종가,$)", "그날 등락(%)", "거래량 배수", "희석 상태", "승률 점수", "퀀트점수", "다음날 시가(%)", "다음날 고가(%)",
            "다음날 저가(%)", "다음날 종가(%)", "5일 후(%)", "5일 내 최고(%)", "5일 내 최저(%)", "확인", "성공"]
    import tosslink_ui
    import ui_kit as _ui
    st.dataframe(_ui.tidy(tosslink_ui.with_links(show[cols].head(1000), "티커")), hide_index=True, width="stretch", column_config={"토스": tosslink_ui.COLUMN})  # 자릿수·None 정리
    st.download_button("⬇️ 발견 종목 추적 CSV (엑셀용)", show[cols].to_csv(index=False).encode("utf-8-sig"), file_name="tracked.csv", mime="text/csv")
    st.caption("'5일 내 최고가' 기준은 이미 도달했으면 바로 성공으로, 아니면 5거래일이 지나야 확인으로 셉니다. "
               "일봉 기준이라 고가·저가의 순서와 실제로 그 가격에 팔 수 있었는지는 알 수 없어, 성공률은 실제 수익보다 낙관적입니다.")
