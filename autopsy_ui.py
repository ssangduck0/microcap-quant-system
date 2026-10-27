"""🔍 부검 화면 — 🏆 검증 안 탭. 놓친 펌핑 · 잡은 펌핑 · 실패 신호 원인 태그 · 특징 비교(잡음/놓침/실패). 계산은 autopsy.py."""
import json
from contextlib import closing

import pandas as pd
import streamlit as st

import access
import autopsy
import chartpop
import db
import ui_kit as ui

SESS_KO = {"night": "데이마켓", "pre": "프리장", "reg": "정규장", "post": "애프터", "toss": "토스 순위"}
COLS_PUMP = {"date": "날짜", "ticker": "티커", "pump_pct": "종가(%)", "hi_pct": "고가(%)", "session": "시작 세션", "ai_cat": "🤖 분류", "ai_note": "🤖 근거", "catalyst": "촉매(공시·뉴스)", "bucket": "가격대", "dil": "희석",
             "float": "유통주식", "dvol20": "거래대금20일($)", "dd20": "20일 낙폭(%)", "rsi": "RSI", "zone": "📐 채널 위치", "regime": "🚦 장세", "sv_pct": "숏볼륨(%)", "si_pct": "공매 잔고(%)"}


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "session" in d:
        d["session"] = d["session"].map(lambda s: SESS_KO.get(s, s))
    if "float" in d:
        d["float"] = d["float"].map(lambda v: None if v is None or pd.isna(v) else round(float(v) / 1e6, 2))
    if "dvol20" in d:
        d["dvol20"] = pd.to_numeric(d["dvol20"], errors="coerce").round(0)
    for k in ("pump_pct", "hi_pct", "dd20", "rsi", "sv_pct", "si_pct"):
        if k in d:
            d[k] = pd.to_numeric(d[k], errors="coerce").round(1)
    if "regime" in d:
        d["regime"] = d["regime"].map({"green": "🟢", "yellow": "🟡", "red": "🔴"}).fillna("-")
    return d


def review_section() -> None:
    """🤖 Claude 복기(3단계): 마지막 복기 요약 · 규칙 후보 · AI 분류 집계 · 지금 돌리기."""
    import review
    with closing(db.connect()) as conn:
        last = review.latest(conn)
        cc = review.cat_counts(conn)
        is_due = review.due(conn)
    st.markdown("#### 🤖 Claude 복기(주 1회) — 놓친 펌핑의 촉매 · 실패 신호의 원인 · 규칙 후보")
    if not access.is_guest():
        c1, c2 = st.columns([1, 3])
        if c1.button("🤖 지금 복기 돌리기", key="ap_review_run", help="최근 7일 놓친 펌핑·실패 신호 중 아직 안 본 것을 Haiku 에 보냄(약 20~40원, 월 예산 안)"):
            logs: list[str] = []
            with st.spinner("Claude 가 읽는 중…"):
                try:
                    res = review.run(out=logs.append, force=True)
                    logs.append(f"결과: {res.get('status')}")
                except Exception as e:  # noqa: BLE001
                    logs.append(f"실패: {e}")
            st.code("\n".join(logs) or "-")
            st.rerun()
        c2.caption(("다음 복기 예정: 아침 작업에서 자동(마지막 복기 뒤 6일)" if not is_due else "아침 작업 때 자동으로 돌아갈 차례예요") + " · 규칙 후보는 제안일 뿐, 🕰 타임머신으로 검증한 뒤에만 반영해요.")
    if not last:
        st.caption("아직 복기 기록이 없어요. 부검 데이터가 쌓인 첫 아침 작업에서 자동으로 한 번 돌고, 그 뒤 주 1회 돌아요.")
        return
    st.markdown(ui.chip(f"마지막 복기 {str(last['run_at'])[:16].replace('T', ' ')} UTC", "blue") + ui.chip(f"놓친 펌핑 {last['n_miss']}건 · 실패 신호 {last['n_fail']}건", "gray")
                + ui.chip(f"약 {float(last['cost_krw'] or 0):.0f}원", "gray"), unsafe_allow_html=True)
    if last.get("summary"):
        st.caption("📝 " + last["summary"])
    if last.get("rules"):
        st.dataframe(pd.DataFrame(last["rules"]).rename(columns={"name": "규칙 후보", "condition": "조건", "expect": "기대", "check": "검증 방법"}), hide_index=True, width="stretch",
                     column_config={"조건": st.column_config.TextColumn(width="large"), "검증 방법": st.column_config.TextColumn(width="medium")})
    k1, k2 = st.columns(2)
    if cc["miss"]:
        k1.dataframe(pd.DataFrame(cc["miss"], columns=["놓친 펌핑 촉매(AI 분류, 90일)", "건수"]), hide_index=True, width="stretch")
    if cc["fail"]:
        k2.dataframe(pd.DataFrame(cc["fail"], columns=["실패 원인(AI 분류, 90일)", "건수"]), hide_index=True, width="stretch")


def render() -> None:
    ui.title("🔍 부검", "놓친 펌핑과 실패한 신호를 '그날 이전 정보'로 다시 봅니다. 왜 못 잡았고 왜 틀렸는지가 쌓여야 2단계(신호 승률 모델)·3단계(Claude 복기)가 가능해요.")
    days = st.radio("기간", [7, 30, 90], index=1, horizontal=True, key="ap_days", format_func=lambda d: f"최근 {d}일")
    if not access.is_guest() and st.button("🔍 오늘 부검 다시 돌리기(일봉 최신 날짜 기준)", key="ap_run"):
        with st.spinner("펌핑·실패 신호를 다시 보는 중…"):
            logs: list[str] = []
            try:
                import market
                with closing(db.connect()) as conn:
                    autopsy.run(conn, out=logs.append, download=lambda t: market.download_daily([t], period="6mo").get(t))
            except Exception as e:  # noqa: BLE001
                logs.append(f"실패: {e}")
        st.code("\n".join(logs[:20]) or "-")
    with closing(db.connect()) as conn:
        s = autopsy.stats(conn, days)
    pumps, fails = s["pumps"], s["fails"]
    for df_ in (pumps, fails):
        for col in ("ai_cat", "ai_note"):
            if col not in df_.columns:
                df_[col] = None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("펌핑(+30% 종가·+50% 고가)", f"{s['n_pump']}종목")
    c2.metric("우리 신호·보유에 있었음", f"{s['n_caught']}종목")
    c3.metric("놓친 비율", "-" if s["miss_rate"] is None else f"{s['miss_rate']:.0f}%")
    c4.metric("실패 신호 부검", f"{len(fails)}건")
    if pumps.empty and fails.empty:
        st.info("아직 부검 기록이 없어요. 매일 아침 작업(07:30)이 어제 펌핑과 새로 '실패'가 된 신호를 넣어요. 위 버튼으로 지금 한 번 돌릴 수도 있어요.")
        return
    review_section()
    if not pumps.empty:
        st.markdown("#### ❌ 놓친 펌핑 — 전날 무엇이 있었나")
        miss = pumps[pumps["caught"] == 0]
        if miss.empty:
            st.caption("이 기간에 놓친 펌핑이 없어요.")
        else:
            st.dataframe(_fmt(miss[list(COLS_PUMP)]).rename(columns=COLS_PUMP), hide_index=True, width="stretch",
                         column_config={"촉매(공시·뉴스)": st.column_config.TextColumn(width="large"), "유통주식": st.column_config.NumberColumn("유통주식(M)", format="%.2f")})
        with st.expander(f"✅ 잡은 펌핑 {int(pumps['caught'].sum())}종목 — 어떤 신호·보유였나"):
            hit = pumps[pumps["caught"] == 1].copy()
            if hit.empty:
                st.caption("없음")
            else:
                hit["우리 신호"] = hit["caught_by"].map(lambda x: ", ".join(json.loads(x)) if isinstance(x, str) and x.startswith("[") else (x or ""))
                hit["보유"] = hit["held"].map(lambda x: ", ".join(json.loads(x)) if isinstance(x, str) and x.startswith("[") else (x or ""))
                st.dataframe(_fmt(hit[["date", "ticker", "pump_pct", "hi_pct", "session", "우리 신호", "보유", "catalyst"]]).rename(columns=COLS_PUMP), hide_index=True, width="stretch")
        cc1, cc2, cc3 = st.columns(3)
        for col, key, title in ((cc1, "by_session", "시작 세션별"), (cc2, "by_bucket", "가격대별"), (cc3, "by_dil", "희석 상태별")):
            tb = s.get(key)
            if tb is not None and not tb.empty:
                with col:
                    tb = tb.rename(index=SESS_KO) if key == "by_session" else tb
                    chartpop.bar(tb, key=f"ap_{key}", title=f"펌핑 {title} — 잡음 vs 놓침", height=180)
    if not fails.empty:
        st.markdown("#### 💥 실패 신호 — 왜 틀렸나(규칙 태그)")
        tc = s.get("tag_counts")
        if tc is not None and not tc.empty:
            chartpop.bar(tc.rename("건수"), key="ap_tags", title="실패 원인 태그(한 신호에 여러 태그 가능)", height=200, horizontal=True)
        tbs = s.get("tag_by_source")
        if tbs is not None and not tbs.empty:
            import scoreboard as sb
            tbs = tbs.rename(index=lambda k: sb.SOURCES.get(k, (k,))[0])
            st.dataframe(tbs, width="stretch")
        with st.expander("실패 신호 목록"):
            f = fails.copy()
            f["태그"] = f["tags"].map(lambda x: ", ".join(autopsy.TAGS.get(k, k) for k in json.loads(x)) if isinstance(x, str) and x.startswith("[") else (x or ""))
            import scoreboard as sb
            f["출처"] = f["source"].map(lambda k: sb.SOURCES.get(k, (k,))[0])
            cols = {"date": "신호일", "ticker": "티커", "출처": "출처", "entry": "진입($)", "max_up": "최고(%)", "max_down": "최저(%)", "태그": "원인 태그", "ai_cat": "🤖 분류", "ai_note": "🤖 근거", "bucket": "가격대", "dil": "희석", "regime": "🚦 장세", "zone": "📐 채널 위치"}
            st.dataframe(_fmt(f[list(cols)]).rename(columns=cols), hide_index=True, width="stretch", column_config={"원인 태그": st.column_config.TextColumn(width="large")})
    comp = s.get("compare")
    if comp is not None and not comp.empty:
        st.markdown("#### 📊 특징 비교(중앙값) — 잡은 펌핑 · 놓친 펌핑 · 실패 신호")
        st.caption("놓친 펌핑과 잡은 펌핑의 차이가 큰 열이 '우리 기준이 빠뜨린 조건' 후보예요. 표본이 쌓이면(수백 건) 2단계 모델의 입력이 됩니다.")
        st.dataframe(comp.round(2), hide_index=True, width="stretch")
    st.caption("태그 규칙: 🚦 장세 나쁨 = 신호일 신호등 🟡/🔴 · 🧾 희석 출회 = 신호 뒤 424B·S-1/S-3·EFFECT 공시 또는 ATM/ELOC/CB · 🩳 공매 눌림 = 신호 뒤 숏볼륨 60%↑ · 💧 거래량 없음 = 20일 거래대금 $50만 미만 · "
               "📰 호재 없음 = 7일 안 호재 공시·뉴스 없음 · 🌙 시간외 되돌림 = 시간외 고가 +15%↑인데 정규장 고가는 그 85% 미만 · 📐 생명선 이탈 = 신호 뒤 생명선/허리 이탈 기록 · 📉 시장 하락 = 기간 중 🚦 4점↑")
