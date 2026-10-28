"""✅ 3대 조건 화면 — 지금 후보(일봉 판정 + 고른 종목의 60분봉 확인). 🕰 타임머신(render_time)은 🏆 검증 화면의 탭이 부른다(메뉴 정리 2026-10-26)."""
from __future__ import annotations

import os
from contextlib import closing

import pandas as pd
import streamlit as st

import chartpop

import db
import setup3 as s3
import ui_kit as ui

TIP = ("① **돈 들어온 거래량** — 거래량과 OBV 가 같이 올라야 함(돈 없는 거래량은 사팔이, 못해도 돈은 들어와 있어야 함). 일봉·분봉 확인, 종가 체크는 5분봉(🎯 장마감 체크리스트), 나머지는 60분봉.  \n"
       "② **지지선이 명확하거나 과매도**(예: 인리프) — 🕰 검증 결과 과매도가 효과적이라 판정은 과매도(RSI ≤ 30·볼린저 하단 아래), 지지선은 참고로 표시.  \n③ 그리고 가장 중요한 **희석의 부재**. — 스승님")


@st.cache_data(ttl=900, show_spinner="3대 조건 계산 중(15분마다 새로)…")
def _scan_cached() -> list[dict]:
    import watch_ui
    with closing(db.connect()) as conn:
        tk = s3.candidates(conn)
    px = watch_ui.prices(tuple(tk))
    with closing(db.connect()) as conn:
        return s3.scan(conn, px, tk)


@st.cache_data(ttl=900, show_spinner="60분봉 받는 중…")
def _intra60(t: str):
    import market
    try:
        return market._download([t], period="1mo", interval="60m").get(t)
    except Exception:  # noqa: BLE001
        return None


def render() -> None:
    ui.title("✅ 3대 조건 — 돈·지지·희석 없음", "스승님 급등 조건 세 가지를 같이 보는 화면. 규칙 기반 판정이며 매수 권유가 아닙니다.")
    with st.expander("📜 스승님 3대 조건 · 판정 기준"):
        st.markdown(TIP)
        st.caption(f"① 최근 {s3.N_RECENT}봉 OBV 순증가 ≥ 그 구간 거래량의 {s3.OBV_MIN:.0%} → 돈 들어옴, 거래량도 직전 {s3.N_PRIOR}봉 대비 {s3.VOL_UP:g}배↑ → 강한 유입, "
                   f"거래량만 늘고 OBV 그대로 → 사팔이 · ② 최근 120봉 저점 중 ±{s3.SUPPORT_BAND:.0%} 안에 {s3.SUPPORT_TOUCHES}번↑ 닿은 가격대 위 {s3.SUPPORT_ABOVE:.0%} 안, "
                   f"또는 RSI ≤ {s3.RSI_OVERSOLD:g}·볼린저 하단 아래 · ③ 최근 {s3.DIL_DAYS}일 희석 서류(424B·S-1·S-3·F-1·F-3·EFFECT·8-K 3.02)·공시 알림 희석 태그 없음")
    render_now()
    st.divider()
    _c1, _c2 = st.columns([1, 4])
    if _c1.button("🕰 타임머신 열기", key="s3_go_tm", help="지금의 3대 조건을 과거에 적용한 적중률 — 🏆 검증 화면의 탭으로 옮겼어요"):
        import tabs
        tabs.go("score", "timemachine")
    _c2.caption("🕰 타임머신(과거 검증)은 🏆 검증 화면에 있어요.")


def render_now() -> None:
    rows = _scan_cached()
    if not rows:
        st.info("판정할 종목이 없어요. 스캐너가 돌면 최근 7일에 본 종목($20 미만)과 워치리스트를 판정해요.")
        return
    full = [r for r in rows if r["all"]]
    tiered = [r for r in rows if r.get("tier")]
    import config as _cfg
    st.info("🕰 **검증 순위**(타임머신 3,000종목·2년, 2024·2025·2026 모두 기준보다 좋음): ⭐ 1순위 RSI≤20+희석 없음 · 2순위 RSI≤25+희석 없음 · 3순위 과매도+희석 없음. "
            "단타보다 **반등형**이 맞아요 — 1순위 기대값(+30% 익절·−20% 손절) 5일 +2.2% → 10일 +3.7% → 20일 +4.3% → 40일 +6.1%, 나쁜 해였던 2026년에도 40일 +4.2%(아무 종목 +0.1%). "
            "3순위는 비용(약 2%)을 빼면 거의 0이라 참고용이에요. "
            f"지금 기준: **{_cfg.TIER_HOLD_DAYS}거래일 보유 · +{_cfg.TIER_TARGET:g}% 익절 · {_cfg.TIER_STOP:g}% 손절**(관리 모드에서 변경). 비용(왕복 1~5%) 빼기 전.")
    ui.cards([{"t": "⭐ 1순위", "v": f"{sum(1 for r in rows if r.get('tier') == 1)}", "accent": True}, {"t": "2순위", "v": f"{sum(1 for r in rows if r.get('tier') == 2)}"},
              {"t": "3순위", "v": f"{sum(1 for r in rows if r.get('tier') == 3)}"}])
    ui.cards([{"t": "판정 종목", "v": f"{len(rows)}"}, {"t": "✅ 3대 조건 충족", "v": f"{len(full)}"},
              {"t": "💰 강한 유입", "v": f"{sum(1 for r in rows if r['money']['ok'])}"}, {"t": "❌ 희석 있음", "v": f"{sum(1 for r in rows if r['dilution']['ok'] is False)}"}])
    view = st.radio("보기", ["검증 순위(1~3)만", "3대 조건 충족만", "전체"], index=0 if tiered else (1 if full else 2), horizontal=True, key="s3_view",
                    label_visibility="collapsed")
    v = tiered if view.startswith("검증") else (full if view.startswith("3대") else rows)
    tb = pd.DataFrame([{"티커": r["ticker"], "검증 순위": r.get("tier_name") or "-", "판정": r["verdict"], "① 돈(거래량+OBV·일봉)": r["money"]["label"], "② 과매도(지지선 참고)": r["support"]["label"],
                        "③ 희석": r["dilution"]["label"], "가격($)": r["price"],
                        "OBV 순유입(%)": None if r["money"]["obv_ratio"] is None else r["money"]["obv_ratio"] * 100,
                        "거래량 배수": r["money"]["vol_ratio"], "RSI": r["support"]["rsi"]} for r in v[:300]])
    if tb.empty:
        st.info("고른 보기에 해당하는 종목이 지금 없어요. '전체'를 고르면 모든 판정 종목을 볼 수 있어요.")
        return
    import pick as picker
    t = picker.clickable(ui.tidy(tb), list(tb["티커"]), "s3_tb", hide_index=True, width="stretch")
    st.caption("👆 행을 누르면 60분봉으로 '돈 들어옴'을 한 번 더 확인해요. 일봉 판정은 15분마다 새로 계산해요.")
    if t:
        r = next(x for x in v if x["ticker"] == t)
        m60 = s3.money_flow(_intra60(t))
        st.markdown(f"**{t}** — 일봉: {r['money']['label']} · **60분봉: {m60['label']}**"
                    + ("" if m60["obv_ratio"] is None else f" (OBV 순유입 {m60['obv_ratio'] * 100:+.0f}% · 거래량 {m60['vol_ratio'] or 0:.1f}배)"))
        st.caption(f"{r['support']['label']} · {r['dilution']['label']}")
        import report_dialog
        report_dialog.button(t, "s3")


def render_time() -> None:
    import timemachine as tm
    res = tm.load_result()
    st.markdown("**🕰 타임머신** — 지금의 3대 조건을 **과거의 그날**로 돌아가 적용하고, 실제로 그 뒤 10거래일 안에 급등(+30%)했는지로 적중률을 재요.")
    st.caption("컨닝 금지: 그날까지의 일봉 · 그날 '전에' 접수된 공시만 사용하고, 결과(이후 최고가)는 판정 뒤에만 붙여요. "
               "⚠️ 일봉 저장소에 상장폐지 종목이 적으면 적중률이 실제보다 좋게 나와요. 분봉 OBV 는 과거 분봉이 없어 일봉으로만 검증해요.")
    import access
    if access.can_edit() and st.button("🔄 지금 다시 계산(수 분)", key="tm_run"):
        bar = st.progress(0.0, text="시작…")
        r = tm.run(out=lambda msg: bar.progress(0.5, text=str(msg)))
        if r.get("hint"):
            st.warning(r["hint"])
        else:
            st.rerun()
    if not res or not res.get("combos"):
        st.info("아직 결과가 없어요. 과거 일봉이 필요해요: PC에서 `python timemachine.py 2 --fill`(처음 10~30분) — 아침 갱신도 하루 300종목씩 채우고, 매주 토요일에 다시 계산해요.")
        return
    st.caption(f"기간 {res['start']} ~ {res['end']} · 종목 {res['n_tickers']:,}(공시 이력 있는 종목 {res.get('with_sec', 0):,}) · 판정 {res['n']:,}건 "
               f"({res['step']}거래일마다, 가격 ${res['max_price']:g} 미만·20일 거래대금 ${res['min_dv']:,.0f}↑) · 계산일 {res['at']}")
    ui.cards([{"t": "기준: 아무 종목 +30%", "v": f"{res['base_big']:.2f}%", "s": "10거래일 안 +30% 닿은 비율(변동성도 섞임)"},
              {"t": "기준: +30% 먼저", "v": "-" if res.get("base_first") is None else f"{res['base_first']:.2f}%", "s": "−20% 에 먼저 닿기 전에 +30%(위험까지 본 값)"},
              {"t": "기준: 기대값", "v": "-" if res.get("base_ev") is None else f"{res['base_ev']:+.2f}%", "s": "+30% 익절·−20% 손절·10일째 매도 평균"},
              {"t": "공시 이력 있는 판정", "v": "-" if res.get("covered_pct") is None else f"{res['covered_pct']:.0f}%", "s": "③ 희석 없음은 이 종목들만(나머지는 '모름')"}])
    cb = pd.DataFrame(res["combos"])
    if res.get("short"):
        st.markdown(f"**⚡ 단타 기준** — 장마감 종가에 사서 **5거래일 안에 무조건 탈출**(매집·애프터·장마감·3대 조건 방식). 목표에 닿으면 그 가격에 팔고, 못 닿으면 5일째 종가. "
                    f"고점은 🌙 세션별 기록이 있는 날이면 프리·애프터·데이마켓까지 포함(지금 판정의 {res.get('ext_pct', 0)}% — 기록이 쌓일수록 늘어요)")
        st.dataframe(ui.tidy(pd.DataFrame(res["short"])), hide_index=True, width="stretch")
        st.caption("D+1 +10% = 다음날 고점이 +10% 이상 닿은 비율. '수익' 은 수수료·호가 차이(초소형주 왕복 2~5%)를 빼기 전 값이에요. "
                   "표 머리글의 ⋮ 메뉴(영어)는 Streamlit 기본 기능: Sort ascending 오름차순 · Sort descending 내림차순 · Statistics 통계 · Autosize 폭 자동 · Pin column 열 고정 · Hide column 열 숨기기.")
        if res.get("exit_days"):
            st.markdown("**⏱ 못 튀면 며칠째 정리할까?** — 분할 매도(+10·20·30% 각 1/3) 수익. 앞 기간으로 고르고 최근 기간으로 확인해야 과거에만 맞는 규칙을 피해요")
            st.dataframe(ui.tidy(pd.DataFrame(res["exit_days"])), hide_index=True, width="stretch")
        if res.get("ext_cmp"):
            st.markdown("**🌙 정규장만 vs 시간외 포함** — 5일 모두 시간외 기록이 있는 판정만 비교(시간외 고점을 빼면 급등을 얼마나 놓치는지)")
            st.dataframe(ui.tidy(pd.DataFrame(res["ext_cmp"])), hide_index=True, width="stretch")
        st.markdown("**참고: 10거래일 · +30% 익절 / −20% 손절**")
    st.dataframe(ui.tidy(cb), hide_index=True, width="stretch")
    st.caption("읽는 법: '적중' = 신호가 난 뒤 10거래일 안에 그만큼 올랐던 비율(정밀도). '기준 대비' 가 1보다 크면 아무 종목보다 잘 고른 것. "
               "'재현율' = 실제 급등 중 이 조합이 미리 잡은 비율. 신호 수가 적으면(수십 건) 우연일 수 있어요.")
    if res.get("hold"):
        st.markdown("**⭐ 반등형 보유 기간 검증** — 깊은 과매도+희석 없음은 오래 들고 있을수록 좋아지는지, 앞 기간과 최근 기간 모두 그런지")
        st.dataframe(ui.tidy(pd.DataFrame(res["hold"])), hide_index=True, width="stretch")
    if res.get("horizons"):
        st.markdown("**기간별(주요 조합)** — 5·10·20·40거래일. 기대값 = +30% 익절·−20% 손절·기간 끝 종가 매도 규칙의 평균 수익(수수료·호가 차이 빠짐)")
        st.dataframe(ui.tidy(pd.DataFrame(res["horizons"])), hide_index=True, width="stretch")
    if res.get("by_year"):
        st.markdown("**연도별(주요 조합)** — 해마다 비슷하게 나와야 우연이 아니에요")
        st.dataframe(ui.tidy(pd.DataFrame(res["by_year"])), hide_index=True, width="stretch")
    st.markdown("**🔎 종목 하나 되돌려 보기** — 그 종목의 날짜별 판정(그날까지 정보만)과 실제 결과")
    tk = st.text_input("티커", key="tm_tk", placeholder="예: INLF").strip().upper()
    if tk:
        rp = tm.replay(tk)
        if rp.empty:
            st.info("일봉 저장소에 이 종목 자료가 없어요(`python timemachine.py 2 --fill`).")
        else:
            big = rp[rp["up10"] >= tm.BIG]
            st.caption(f"판정 {len(rp)}일 · 10거래일 안 +{tm.BIG:g}% 오른 '급등 직전 날' {len(big)}일 · "
                       + " · ".join(f"{nm} {int(big[k].sum())}/{len(big)}" for k, nm in (("strong", "💰강한 유입"), ("supl", "②a 지지선"), ("ovs", "②b 과매도"), ("dil", "③ 희석 없음"))))
            import altair as alt
            ch = rp.assign(날짜=pd.to_datetime(rp["date"]), 신호=["💰" if s else "" for s in rp["strong"]], 급등직전=rp["up10"] >= tm.BIG)
            line = alt.Chart(ch).mark_line().encode(x=alt.X("날짜:T", title=None), y=alt.Y("price:Q", title="종가($)"))
            pts = alt.Chart(ch[ch["급등직전"]]).mark_point(color="#E5484D", size=60, filled=True).encode(x="날짜:T", y="price:Q", tooltip=["date", "up10", "strong", "supl", "ovs", "dil"])
            chartpop.show(line + pts, key="s3_price", title="종가와 급등 직전 날(빨간 점)", data=ch)
            st.caption("빨간 점 = 그날 사서 10거래일 안에 +30% 닿은 날(급등 직전 날). 그날 각 조건이 켜져 있었는지 아래 표에서 보세요.")
            show = (big if not big.empty else rp.tail(30))[["date", "price", "up10", "exit10", "strong", "money", "supl", "sup_lv", "touches", "ovs", "rsi", "obv_r", "vol_r", "dil"]]
            st.dataframe(ui.tidy(show.rename(columns={"date": "날짜", "price": "종가($)", "up10": "10일 최고(%)", "exit10": "규칙 수익(%)", "strong": "💰강한 유입",
                                                      "money": "OBV↑", "supl": "지지선", "sup_lv": "지지 가격($)", "touches": "닿은 횟수", "ovs": "과매도", "rsi": "RSI",
                                                      "obv_r": "OBV 순유입", "vol_r": "거래량 배수", "dil": "희석 없음"})), hide_index=True, width="stretch")
