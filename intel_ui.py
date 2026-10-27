"""공통 인텔 화면 조각 — 퀀트 스냅샷 표의 요약 열, 종목 상세·종목 리포트의 상세 섹션에 같은 값을 보여 준다."""
from contextlib import closing

import pandas as pd
import streamlit as st

import config
import db
import intel

SUMMARY_COLS = ["가격 흐름(2시간)", "체결강도(30분)", "체결강도(%)", "체강 출처", "거래정지", "공매도(전일%)", "대차수수료(%)", "대차가능 변화(%)", "장중 희석", "자금조달(7일)", "워런트(7일)"]
COLUMN_CONFIG = {
    "가격 흐름(2시간)": st.column_config.LineChartColumn(help="최근 2시간 1분봉 종가(토스, 스캐너가 저장). 미니 차트로 수급이 쏠리는 종목을 빠르게 찾기"),
    "체결강도(30분)": st.column_config.LineChartColumn(help="최근 30분 분당 체결강도(토스 실시간 체결가↔호가, 100 = 매수·매도 균형). 실시간 구독 종목만"),
    "체결강도(%)": st.column_config.NumberColumn(format="%.0f", help="매수 체결량 / 매도 체결량 × 100 (100 = 균형). 최근 30분 기준. "
                                                "'실시간' = 토스 체결가를 그 순간의 호가와 비교(토스 호가창 방식), '추정' = 1분봉 방향. 토스 화면의 당일 누적값과 다를 수 있음"),
    "체강 출처": st.column_config.TextColumn(width="small"),
    "거래정지": st.column_config.TextColumn(help="업킷 거래정지: 하킷(하한)·상킷(상한) LULD 정지 횟수, 지금 정지 중 여부"),
    "공매도(전일%)": st.column_config.NumberColumn(format="%.0f", help="FINRA: 직전 거래일 공매도 거래량 / 전체 거래량. 장외(TRF) 보고분만 집계라 실제보다 높게 보일 수 있음. 장 마감 후 공개"),
    "대차수수료(%)": st.column_config.NumberColumn(format="%.1f", help="IBKR: 대차 수수료(연율). 높을수록 빌리기 어렵고 공매도 비용이 큼. 15분마다 갱신"),
    "대차가능 변화(%)": st.column_config.NumberColumn(format="%+.0f", help="IBKR: 대차 가능 수량이 오늘 처음 본 값 대비 얼마나 변했는지. 크게 줄면 공매도가 몰렸다는 신호(IBKR 물량 기준)"),
    "장중 희석": st.column_config.TextColumn(help="SEC: 오늘 제출된 공시 중 희석(공모·ATM·ELOC·전환사채 등) 키워드가 있는 공시 수 — 원문 확인 필요"),
    "자금조달(7일)": st.column_config.TextColumn(help="SEC: 최근 7일 자금조달 유형과 출회 제한 여부(사모·ELOC의 재판매 등록 전/대기) — 원문 확인 필요"),
    "워런트(7일)": st.column_config.TextColumn(help="SEC: 최근 7일 워런트 관련 공시 수 — 원문 확인 필요"),
}


@st.cache_data(ttl=30)
def load_all() -> dict:
    """{(날짜, 티커): 데이터}"""
    intel.ensure_table()
    df = db.read_df("SELECT date, ticker, data FROM ticker_intel")
    import json
    return {(r.date, r.ticker): json.loads(r.data) for r in df.itertuples()}


def summary_frame(view: pd.DataFrame) -> pd.DataFrame:
    """view(date, ticker 열)와 같은 순서의 요약 열."""
    m = load_all()
    return pd.DataFrame([intel.summary_cells(m.get((d, t))) for d, t in zip(view["date"], view["ticker"])], index=view.index)[SUMMARY_COLS]


def _kst(iso: str | None) -> str:
    if not iso:
        return "-"
    return pd.to_datetime(iso, utc=True).tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")


def render_ticker(ticker: str, day: str | None = None, key: str = "intel") -> None:
    """한 종목의 체결강도·거래정지·공매도·SEC 장중 공시 상세."""
    st.markdown(f"#### 📡 {ticker} 체결강도 · 거래정지 · 공매도 · 장중 공시")
    with closing(db.connect()) as conn:
        if day:
            data, upd = intel.get(conn, day, ticker), None
            row = conn.execute("SELECT updated_at FROM ticker_intel WHERE date=? AND ticker=?", (day, ticker)).fetchone() if data else None
            upd = row["updated_at"] if row else None
        else:
            got = intel.latest(conn, ticker)
            day, data, upd = (got if got else (None, None, None))
    b1, b2 = st.columns([4, 1])
    b1.caption(("스캐너 갱신 " + _kst(upd) + f" KST · 거래일 {day}") if data else "스캐너가 아직 이 종목을 분석하지 않았습니다.")
    if b2.button("🔄 지금 조회", key=f"{key}_refresh_{ticker}", help="SEC 공시·거래정지·공매도(FINRA·IBKR)를 지금 다시 확인합니다(토스 체결강도는 스캐너만 갱신)"):
        if "@" not in config.SEC_USER_AGENT:
            st.error("SEC_USER_AGENT 가 .env 에 설정되어 있지 않습니다.")
        else:
            import halts
            import shortdata
            import sec
            with st.spinner("SEC 공시·거래정지·공매도 확인 중..."):
                try:
                    hl = halts.fetch()
                except Exception:  # noqa: BLE001
                    hl = None
                fc = shortdata.ShortClient.from_config()
                with closing(db.connect()) as conn:
                    data = intel.on_demand(conn, sec.SecClient(config.SEC_USER_AGENT), ticker, fc, hl)
            load_all.clear()
            st.rerun()
    if not data:
        return
    c1, c2, c3 = st.columns(3)
    cs = data.get("cs") or {}
    with c1:
        st.markdown("**체결강도 (토스)**")
        if cs:
            st.metric("최근 30분", "-" if cs.get("late") is None else f"{cs['late']:.0f}%",
                      None if cs.get("late") is None or cs.get("prior") is None else f"{cs['late'] - cs['prior']:+.0f}%p vs 그 전 60분")
            if cs.get("cum") is not None:
                st.caption(f"수집 시작 후 누적 {cs['cum']:.0f}%")
            st.caption(f"출처: {cs.get('source')}" + (f" · 체결 {cs['trades']:,}건" if cs.get("trades") else ""))
        else:
            st.caption("아직 값이 없습니다(스캐너가 1분봉이나 실시간 체결을 받으면 채워짐).")
    with c2:
        st.markdown("**공매도 (FINRA·IBKR)**")
        sh = data.get("short")
        if sh:
            if sh.get("sv_ratio") is not None:
                st.metric(f"{sh.get('sv_date') or '전일'} 공매도 비중", f"{sh['sv_ratio']:.0f}%", f"5일 평균 {sh.get('sv_avg5_ratio', 0):.0f}%", delta_color="off")
            if sh.get("borrow_fee") is not None or sh.get("borrow_avail") is not None:
                fee = "-" if sh.get("borrow_fee") is None else f"{sh['borrow_fee']:.1f}%"
                avail = "-" if sh.get("borrow_avail") is None else ((">" if sh.get("borrow_avail_capped") else "") + f"{sh['borrow_avail']:,.0f}주")
                chg = "" if sh.get("borrow_avail_chg_pct") is None else (
                    f" (오늘 처음 {sh['borrow_avail_open']:,.0f}주 대비 {sh['borrow_avail_chg_pct']:+.0f}%)" if sh.get("borrow_avail_open") else f" (오늘 {sh['borrow_avail_chg_pct']:+.0f}%)")
                st.caption(f"대차 수수료 {fee} · 대차 가능 {avail}{chg}" + (f" · {sh['borrow_date']}" if sh.get("borrow_date") else ""))
                if sh.get("borrow_stale"):
                    st.warning(sh.get("borrow_note") or "최신 IBKR 파일에 없음")
            if sh.get("si_shares") is not None:
                st.caption(f"공매도 잔고 {sh['si_shares']:,.0f}주" + (f" ({sh['si_pct_float']:.1f}% float)" if sh.get("si_pct_float") is not None else "")
                           + (f" · {sh['si_date']}" if sh.get("si_date") else ""))
        st.caption(((sh or {}).get("short_src") or "") + ((" · " + data["short_note"]) if data.get("short_note") else ("" if sh else " 값 없음")))
    with c3:
        st.markdown("**거래정지 (업킷)**")
        h = data.get("halt")
        if h is None:
            st.caption("확인 불가(조회 실패 또는 꺼짐)")
        elif not h.get("halts"):
            st.caption("오늘 거래정지 없음" + (f" · 출처 {h.get('src')}" if h.get("src") else ""))
        else:
            st.metric("하킷 / 상킷", f"{h.get('halt_down', 0)} / {h.get('halt_up', 0)}", "🔴 지금 정지 중" if h.get("halt_active") else None, delta_color="off")
            st.dataframe(pd.DataFrame([{"정지(ET)": x.get("time", ""), "사유": x.get("reason", x.get("code", "")), "방향": x.get("dir") or "-", "재개": x.get("resume") or ("호가만 재개" if x.get("quote_resumed") else "정지 중"),
                                        "밴드 가격": x.get("threshold")} for x in h["halts"]]), hide_index=True, width="stretch")
    st.markdown("**SEC 공시 (키워드 판정 — 원문을 꼭 확인하세요)**" + (f" · 확인 {_kst(data.get('sec_at'))} KST" if data.get("sec_at") else ""))
    s = data.get("sec")
    if s is None:
        st.caption("아직 확인 전입니다(스캐너가 종목당 10분 간격으로 확인).")
    elif "error" in s:
        st.caption(s["error"])
    else:
        intr = s.get("intraday") or []
        hits = [x for x in intr if [t for t in x.get("tags", []) if t != "WARRANT"]]
        (st.error if hits else st.success)(f"장중 희석: 오늘 공시 {len(intr)}건 중 희석 정황 {len(hits)}건")
        for x in intr:
            st.markdown(f"- [{x['form']}]({x['url']})" + (f" `{', '.join(x['tags'])}`" if x.get("tags") else " (희석 키워드 없음)"))
        f = s.get("financing")
        if f:
            (st.warning if f["sellable"] != "restricted" else st.info)(f"자금조달(최근 7일): [{f['date']} {f['form']}]({f['url']}) — **{f['type']}** → **{f['label']}**")
        else:
            st.caption("자금조달(최근 7일): 없음")
        w = s.get("warrants") or []
        if w:
            st.warning("워런트(최근 7일): " + " · ".join(f"[{x['date']} {x['form']}]({x['url']})" for x in w))
        else:
            st.caption("워런트(최근 7일): 없음")
