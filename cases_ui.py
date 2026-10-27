"""과거 사례 탭 화면 (dashboard.py 에서 호출). 스캐너 데이터가 없어도 단독으로 표시할 수 있도록 분리했습니다."""
import pandas as pd
import streamlit as st

import chartpop

import analytics
import db
import ui_kit as ui

@st.cache_data(ttl=60)
def case_overview() -> dict:
    ev = db.read_df("SELECT COUNT(*) n, SUM(next_high_pct IS NOT NULL) known, SUM(fwd_5d IS NOT NULL) known5, MIN(date) d0, MAX(date) d1 FROM case_events").iloc[0]
    pr = db.read_df("SELECT status, is_delisted, COUNT(*) n FROM case_progress GROUP BY status, is_delisted")
    return {"events": int(ev["n"] or 0), "known": int(ev["known"] or 0), "known5": int(ev["known5"] or 0),
            "d0": ev["d0"], "d1": ev["d1"], "progress": pr}


@st.cache_data(ttl=60)
def load_cases(d0, d1, thr, pmin, pmax, dvmin, vmmin, deli) -> pd.DataFrame:
    sql = ("SELECT e.*, COALESCE(p.is_delisted,0) AS is_delisted FROM case_events e LEFT JOIN case_progress p ON p.ticker=e.ticker "
           "WHERE e.date BETWEEN ? AND ? AND e.drop_pct <= ? AND e.close BETWEEN ? AND ? "
           "AND COALESCE(e.avg_dollar_vol,0) >= ? AND COALESCE(e.vol_mult,0) >= ?")
    if deli == "상장폐지 목록 종목 제외":
        sql += " AND COALESCE(p.is_delisted,0)=0"
    elif deli == "상장폐지 목록 종목만":
        sql += " AND COALESCE(p.is_delisted,0)=1"
    return db.read_df(sql + " ORDER BY e.date DESC", (d0, d1, thr, pmin, pmax, dvmin, vmmin))


def render() -> None:
    st.subheader("📚 과거 사례 — 전일 종가 대비 급락 사건과 그 이후 결과")
    ov = case_overview()
    if ov["events"] == 0:
        st.info("아직 과거 사례가 없습니다. cmd에서 `python cases.py build --years 10` 을 실행하세요 "
                "(수십 분 걸리고, 중단해도 같은 명령으로 이어집니다). 이후 매일 `python cases.py update` 로 누적합니다.")
    else:
        pg = ov["progress"]
        cnt = lambda st_, dl=None: int(pg[(pg["status"] == st_) & ((pg["is_delisted"] == dl) if dl is not None else True)]["n"].sum())
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("저장된 사건", f"{ov['events']:,}", help=f"{ov['d0']} ~ {ov['d1']}")
        k2.metric("다음날 결과 확인", f"{ov['known']:,}")
        k3.metric("결과 미확인", f"{ov['events'] - ov['known']:,}", help="사건이 가장 최근 거래일이라 다음날 데이터가 아직 없음")
        k4.metric("처리 종목 / 오류", f"{cnt('done'):,} / {cnt('error'):,}", help="오류는 `python cases.py build` 를 다시 실행하면 재시도")
        dl_listed = int(pg[pg["is_delisted"] == 1]["n"].sum())
        k5.metric("상장폐지 목록 중 가격 확보", f"{cnt('done', 1):,} / {dl_listed:,}",
                  help="분모는 토스의 상장폐지 종목 목록 수. 가격 데이터가 없으면 사건에서 빠집니다(생존편향 지표).")
        if dl_listed == 0:
            st.warning("상장폐지 종목이 한 개도 포함되지 않았습니다. 이 통계는 **살아남은 종목만** 본 것이라 반등·성공 비율이 실제보다 좋게 나옵니다.")
        elif cnt("done", 1) < dl_listed * 0.5:
            st.warning(f"상장폐지 목록 {dl_listed:,}개 중 가격이 남아 있는 종목은 {cnt('done', 1):,}개뿐입니다. 급락 후 상장폐지된 사례가 많이 빠져 있어 결과가 낙관적일 수 있습니다.")

        st.markdown("---")
        f1, f2, f3, f4 = st.columns(4)
        dmin = pd.to_datetime(ov["d0"]).date()
        dmax = pd.to_datetime(ov["d1"]).date()
        rng = f1.date_input("기간(미국 거래일)", (dmin, dmax), min_value=dmin, max_value=dmax)
        thr = f2.select_slider("급락 기준(등락률 이하)", options=[-10, -15, -20, -25, -30, -40, -50, -60], value=-20)
        pmin, pmax = f3.slider("종가 범위($, 분할 보정값)", 0.0, 100.0, (0.05, 20.0))
        dvmin = f4.number_input("20일 평균 거래대금 최소($)", 0, 100_000_000, 100_000, step=50_000)
        g1, g2, g3 = st.columns(3)
        vmmin = g1.number_input("거래량 배수 최소(사건일/20일 평균)", 0.0, 1000.0, 0.0, step=0.5)
        deli = g2.radio("상장폐지 목록 종목", ["전체", "상장폐지 목록 종목 제외", "상장폐지 목록 종목만"], horizontal=True)
        target = g3.slider("성공 기준: 다음날 고가가 사건일 종가 대비 +N% 이상", 1, 100, 10)

        d0, d1 = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (dmin, dmax)
        cs = load_cases(str(d0), str(d1), float(thr), float(pmin), float(pmax), float(dvmin), float(vmmin), deli)
        if cs.empty:
            st.info("조건에 맞는 사건이 없습니다.")
        else:
            known = cs["next_high_pct"].dropna()
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("조건에 맞는 사건", f"{len(cs):,}", help=f"{cs['ticker'].nunique():,}개 종목")
            s2.metric("결과 확인된 사건", f"{len(known):,}")
            s3.metric(f"성공률 (다음날 고가 ≥ +{target}%)", f"{(known >= target).mean() * 100:.1f}%" if len(known) else "-",
                      help="일봉이라 다음날 안에서 고가와 저가 중 무엇이 먼저였는지는 알 수 없습니다. 성공이어도 먼저 급락했을 수 있습니다.")
            s4.metric("5일 후 종가 중앙값", f"{cs['fwd_5d'].median():.1f}%" if cs["fwd_5d"].notna().any() else "-")
            st.dataframe(ui.tidy(analytics.case_summary(cs, target)), hide_index=True, width="stretch")
            st.markdown("**급락 폭별**")
            st.dataframe(ui.tidy(analytics.case_summary(cs, target, "drop_pct", [-101, -50, -30, -20, -10.0001],
                                                ["≤-50%", "-50~-30%", "-30~-20%", "-20~-10%"])), hide_index=True, width="stretch")
            st.markdown("**거래량 배수별 (사건일 거래량 / 직전 20일 평균)**")
            st.dataframe(ui.tidy(analytics.case_summary(cs, target, "vol_mult", [0, 1, 3, 10, 1e9], ["<1배", "1~3배", "3~10배", "≥10배"])),
                         hide_index=True, width="stretch")
            hist = pd.cut(known.clip(upper=100), [-100, -10, 0, 5, 10, 20, 30, 50, 100.0001]).value_counts().sort_index()
            st.markdown("**다음날 고가 등락률 분포 (구간별 사건 수, 100%↑는 100%로 묶음)**")
            chartpop.bar(pd.Series(hist.values, index=[str(i) for i in hist.index], name="사건 수"), key="cases_hist", title="다음날 고가 등락률 분포")

            st.markdown("**수익률 분포와 리스크/리워드**")
            import dist_ui
            dist_ui.render(cs, target, key="cases_dist")
            render_sec_flags(cs, target)
            st.markdown("**사건 목록** (최근순, 화면에는 최대 1,000건 · CSV는 전체)")
            show = cs.rename(columns={"ticker": "티커", "date": "거래일", "close": "종가($)", "drop_pct": "급락(%)", "gap_pct": "시가 갭(%)",
                                      "vol_mult": "거래량 배수", "avg_dollar_vol": "20일 평균 거래대금($)", "pre_dd_pct": "전일까지 20일 낙폭(%)",
                                      "next_open_pct": "다음날 시가(%)", "next_high_pct": "다음날 고가(%)", "next_low_pct": "다음날 저가(%)",
                                      "next_close_pct": "다음날 종가(%)", "fwd_5d": "5일 후(%)", "fwd_10d": "10일 후(%)",
                                      "max_up_5d": "5일 내 최고(%)", "max_down_5d": "5일 내 최저(%)", "is_delisted": "상장폐지 목록"})
            cols = ["거래일", "티커", "종가($)", "급락(%)", "시가 갭(%)", "거래량 배수", "20일 평균 거래대금($)", "전일까지 20일 낙폭(%)",
                    "다음날 시가(%)", "다음날 고가(%)", "다음날 저가(%)", "다음날 종가(%)", "5일 후(%)", "10일 후(%)", "5일 내 최고(%)", "5일 내 최저(%)", "상장폐지 목록"]
            st.dataframe(show[cols].head(1000), hide_index=True, width="stretch")
            st.download_button("⬇️ 조건에 맞는 사건 전체 CSV (엑셀용)", show[cols].to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"cases_{d0}_{d1}.csv", mime="text/csv")
        st.caption("가격 데이터는 yfinance 일봉(분할 보정값)입니다. 오래된 사건의 '종가' 필터는 역분할 때문에 부정확하지만 수익률은 일관됩니다. "
                   "일봉 기준이라 분 단위 결과(예: 10분 내 반등)는 포함되지 않습니다.")


def render_sec_flags(cs: pd.DataFrame, target: float) -> None:
    """급락일 전후 공시 종류별 다음날 결과 — 과거 공시 백필(secbackfill.py) 데이터."""
    import db
    import secbackfill as sb
    st.markdown("**📑 급락일 전후 공시별 결과** (그때 어떤 공시가 있었나 — 공모·등록 서류, 상장유지 통지, 정관 변경, 뉴스성 공시, 공시 공백)")
    stt = sb.status()
    if not stt["done"]:
        st.info("과거 공시 기록이 아직 없습니다. 명령 프롬프트에서 한 번 실행하세요(이어받기 가능, 수십 분): `python secbackfill.py build --years 10`")
        return
    hist = db.read_df(f"SELECT ticker, form, filed, items FROM sec_hist WHERE ticker IN ({','.join('?' * cs['ticker'].nunique())})", tuple(cs["ticker"].unique()))
    fl = sb.event_flags(cs, hist)
    rows = []
    covered = fl["offering"].notna()
    base = cs[covered]
    for k, (desc, _, _) in sb.FLAGS.items():
        for yes in (True, False):
            g = cs[covered & (fl[k] == yes)]
            h = g["next_high_pct"].dropna()
            rows.append({"공시 조건": desc, "해당": "예" if yes else "아니오", "사건 수": len(g),
                         f"성공률(고가 ≥ +{target:g}%)": (h >= target).mean() * 100 if len(h) else None,
                         "다음날 고가 중앙값(%)": h.median() if len(h) else None, "다음날 종가 중앙값(%)": g["next_close_pct"].median() if len(g) else None,
                         "5일 후 중앙값(%)": g["fwd_5d"].median() if "fwd_5d" in g and len(g) else None})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                 (f"성공률(고가 ≥ +{target:g}%)", "다음날 고가 중앙값(%)", "다음날 종가 중앙값(%)", "5일 후 중앙값(%)")})
    st.caption(f"공시 기록이 있는 사건 {len(base):,}/{len(cs):,}건 기준(백필 완료 {stt['done']:,}종목). 서류 종류·날짜만 보고 본문은 읽지 않습니다. "
               "'예'와 '아니오'의 차이가 크면 그 공시가 급락 뒤 반등에 영향을 준다는 힌트입니다. 상장폐지 종목은 빠져 있어 낙관적일 수 있습니다.")
