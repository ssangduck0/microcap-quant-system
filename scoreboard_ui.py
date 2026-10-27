"""🏆 성과 공표 탭 — 모든 예측의 성공·실패를 일간·주간·월간·연간으로."""
from contextlib import closing

import altair as alt
import pandas as pd
import streamlit as st

import chartpop

import db
import scoreboard as sb
import tosslink_ui
import ui_kit as ui


def _pinned():
    try:
        return st.column_config.TextColumn(pinned=True)  # 옆으로 밀어도 이 열은 고정
    except TypeError:  # 옛 Streamlit
        return st.column_config.TextColumn()


def render() -> None:
    st.subheader("🏆 성과 공표")
    st.caption("우리 신호(예측)가 실제로 맞았는지 — 일·주·월·연간")
    crit = pd.DataFrame([{"출처": v[0], "방향": "오름" if v[1] > 0 else "내림(청산·분산)",
                          "성공 기준": ("분봉 +5%가 -5%보다 먼저" if k == "after" else ("박스 상단 도달" if k == "piggy" else ("60거래일 안 회사 목표가 도달" if k.startswith("pick") else
                                    (f"{v[3]}거래일 안 최고 ≥ +{v[2]:g}%" if v[1] > 0 else f"{v[3]}거래일 뒤 종가 < 진입가"))))} for k, v in sb.SOURCES.items()])
    if st.session_state.pop("_sb_done", None):
        st.success(st.session_state.pop("_sb_msg", "갱신했어요."))
    with closing(db.connect()) as conn:
        df = sb.table(conn)
    if df.empty:
        st.info("아직 기록된 예측이 없습니다. 스캐너와 매일 아침 갱신 작업이 신호를 쌓으면 여기에 모입니다.")
        _bottom(crit)
        return
    c = st.columns([2, 2, 3])
    units = ["일간", "주간", "월간", "연간"]
    if hasattr(st, "segmented_control"):  # 이름 줄 없이 한 줄로(휴대폰 공간 절약)
        unit = c[0].segmented_control("기간 단위", units, default="일간", key="sb_unit", label_visibility="collapsed") or "일간"
    else:
        unit = c[0].radio("기간 단위", units, horizontal=True, key="sb_unit", label_visibility="collapsed")
    df["기간"] = sb.period_key(df["date"], unit)
    periods = ["전체"] + sorted(df["기간"].unique(), reverse=True)
    judged_p = sorted(df.loc[df["status"].isin(["성공", "실패"]), "기간"].unique(), reverse=True)   # 2026-10-28: 기본 보기 = 가장 최근 '판정이 난' 기간(오늘은 대기뿐이라 성공률 '-' 만 보이던 것)
    default_p = judged_p[0] if judged_p else (periods[1] if len(periods) > 1 else periods[0])
    per = c[1].selectbox("기간", periods, index=periods.index(default_p), key="sb_per", label_visibility="collapsed")
    all_src = sorted(df["출처"].unique())
    with c[2].expander(f"출처 고르기 ({len(st.session_state.get('sb_src', all_src))}/{len(all_src)})"):  # 휴대폰에서 칩이 잘리지 않게 접어 둠
        srcs = st.multiselect("출처", all_src, default=all_src, key="sb_src", label_visibility="collapsed")
    v = df[df["출처"].isin(srcs)]
    cur = v if per == "전체" else v[v["기간"] == per]
    judged = cur[cur["status"].isin(["성공", "실패"])]
    rate = "-" if judged.empty else f"{(judged['status'] == '성공').mean() * 100:.1f}%"
    ui.cards([{"t": "성공률", "v": rate, "s": f"판정 {len(judged):,}건 기준", "accent": True},  # 휴대폰: 2열 작은 카드(예전엔 숫자 하나가 한 화면)
              {"t": "예측", "v": f"{len(cur):,}", "s": per},
              {"t": "✅ 성공", "v": f"{(cur['status'] == '성공').sum():,}"},
              {"t": "❌ 실패", "v": f"{(cur['status'] == '실패').sum():,}"},
              {"t": "⏳ 대기", "v": f"{(cur['status'] == '대기').sum():,}", "s": "아직 기간이 안 끝남"}])
    if not cur.empty:
        st.markdown(f"**출처별 — {per}**")
        sm = sb.summarize(cur)
        sm = sm[["출처", "성공률(%)"] + [x for x in sm.columns if x not in ("출처", "성공률(%)")]]  # 중요한 성공률을 출처 바로 옆에
        for _c in [c for c in sm.columns if c.startswith("평균")]:  # 판정된 결과가 아직 없으면 표에 'None' 대신 '-'
            sm[_c] = ["-" if v is None or pd.isna(v) else f"{float(v):+.1f}" for v in sm[_c]]
        st.dataframe(sm, hide_index=True, width="stretch", column_config={
            "출처": _pinned(),  # 옆으로 밀어도 출처는 고정
            "성공률(%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
            "평균 최고 상승(%)": st.column_config.TextColumn(), "평균 기간 끝 등락(%)": st.column_config.TextColumn()})  # 위에서 '+1.2'·'-' 글자로 바꿈
    tr = v[v["status"].isin(["성공", "실패"])].groupby(["기간", "출처"]).agg(성공률=("status", lambda x: (x == "성공").mean() * 100), 판정=("status", "size")).reset_index()
    if tr["기간"].nunique() >= 2:
        st.markdown(f"**{unit} 성공률 추이** (판정된 예측 기준 — 스캐너를 고친 뒤 올라가는지 보세요)")
        tr["축"] = tr["기간"].str[5:] if unit == "일간" else (tr["기간"].str[2:] if unit in ("주간", "월간") else tr["기간"])  # 10-21 / 26-W43 / 26-10 처럼 짧게
        chartpop.show(alt.Chart(tr).mark_line(point=True).encode(
            x=alt.X("축:N", sort="ascending", title=None, axis=alt.Axis(labelAngle=0, labelOverlap="greedy")),
            y=alt.Y("성공률:Q", scale=alt.Scale(domain=[0, 100]), title="성공률(%)"),
            color=alt.Color("출처:N", legend=alt.Legend(orient="bottom", columns=2, title=None, labelLimit=170)),  # 범례를 아래로 → 차트가 화면 폭을 다 씀
            tooltip=["기간", "출처", alt.Tooltip("성공률:Q", format=".0f"), "판정"]).properties(height=200 + 24 * ((tr["출처"].nunique() + 1) // 2)),
            key="sb_trend", title=f"{unit} 성공률 추이", data=tr)
    show = cur.sort_values(["date", "출처"], ascending=[False, True])
    cols = {"ticker": "티커", "status": "결과", "p30": "AI 확률(%)", "max_up": "최고 상승(%)", "close_h": "기간 끝(%)", "date": "날짜", "출처": "출처",  # 휴대폰: 중요한 열을 왼쪽에
            "토스": "토스", "entry": "진입가($)", "target": "목표(%)", "horizon": "기간(일)", "max_down": "최대 하락(%)", "note": "메모"}
    if "p30" not in show.columns:
        show["p30"] = None
    show = show.assign(토스=tosslink_ui.links(show["ticker"]))[list(cols)].rename(columns=cols)
    show["AI 확률(%)"] = (pd.to_numeric(show["AI 확률(%)"], errors="coerce") * 100).round(0)   # 🧠 신호 승률 모델(2단계): 10거래일 안 +30% 확률 — 참고용
    show["결과"] = show["결과"].map({"성공": "✅ 성공", "실패": "❌ 실패", "대기": "⏳ 대기"})
    cfg = {"티커": _pinned(), "토스": tosslink_ui.COLUMN, "진입가($)": st.column_config.NumberColumn(format="%.4f"),
           "AI 확률(%)": st.column_config.NumberColumn(format="%.0f%%", help="🧠 신호 승률 모델: 신호일 기준 10거래일 안 +30% 갈 확률(2년치 사전학습, 참고용 · 판정엔 안 씀). 비어 있으면 그 신호는 아직 확률을 안 붙인 것"),
           **{k: st.column_config.NumberColumn(format="%+.1f") for k in ("최고 상승(%)", "최대 하락(%)", "기간 끝(%)")}}
    tabs = st.tabs(["✅ 성공", "❌ 실패", "⏳ 대기", "전체"])
    for tb, key in zip(tabs, ["✅ 성공", "❌ 실패", "⏳ 대기", None]):
        with tb:
            part = show if key is None else show[show["결과"] == key]
            st.dataframe(part, hide_index=True, width="stretch", column_config=cfg) if not part.empty else st.caption("없음")
    st.download_button("⬇️ 예측·결과 CSV (엑셀용)", show.to_csv(index=False).encode("utf-8-sig"), file_name=f"scoreboard_{unit}_{per}.csv", mime="text/csv")
    _bottom(crit)


def _bottom(crit: pd.DataFrame) -> None:
    with st.expander("판정 기준 · 결과 갱신"):  # 자주 안 쓰는 것은 맨 아래로
        st.dataframe(crit, hide_index=True, width="stretch")
        st.caption("진입가 = 신호 때 기록된 가격(없으면 신호일 종가). 일봉 기준이라 체결 비용·호가 간격은 반영되지 않습니다. 매일 아침 갱신 작업이 결과를 채웁니다. "
                   "주식 병합 뒤에는 진입가를 같은 단위로 맞춰 비교해요(예전엔 1:10 병합 종목이 +900% '성공'으로 잡힐 수 있었음). "
                   "주가가 끊긴(상장폐지·거래정지 추정) 종목은 7일 기다린 뒤 끊기기 전까지의 가격으로 확정해요 — 오름 예측은 목표를 못 넘었으면 실패.")
        import access
        if access.can_edit() and st.button("🔄 결과 지금 갱신", key="sb_refresh"):
            with st.spinner("결과 계산 중(일봉 받는 중)..."):
                with closing(db.connect()) as conn:
                    r = sb.update(conn, out=lambda *_: None)
            st.session_state["_sb_done"], st.session_state["_sb_msg"] = True, f"{r['rows']:,}건 갱신했어요."
            st.rerun()
    _vault()


def _vault() -> None:
    """🗄 주가 보관소 상태 — 신호 낸 종목의 일봉 보관 · 끊긴 종목."""
    import pricevault as pv
    with st.expander("✅ 3대 조건별 성적 — 신호 난 날 조건을 갖췄을 때 vs 안 갖췄을 때"):
        st.caption("신호 난 날 그 종목이 스승님 3대 조건(① 거래량+OBV 동반 상승 ② 과매도 ③ 최근 90일 희석 서류 없음)을 갖췄는지를 "
                   "그날까지의 일봉·그날 전에 접수된 공시만으로 계산해(컨닝 없음) 성공률을 나눠 봐요. '차이'가 꾸준히 + 인 출처에는 그 조건을 걸면 좋아요. "
                   "신호가 수십 건 쌓이기 전에는 우연일 수 있어요.")
        try:
            import setup3
            with closing(db.connect()) as _c:
                _j = df[df["status"].isin(["성공", "실패"])]
                _cd = setup3.conditions_at(_c, list(zip(_j["ticker"], _j["date"])))
            _rep = setup3.condition_report(df, _cd)
            if _rep.empty:
                st.info("판정이 끝난 신호가 아직 없어요.")
            else:
                st.dataframe(ui.tidy(_rep), hide_index=True, width="stretch")
        except Exception as _e:  # noqa: BLE001
            st.caption(f"계산하지 못했어요: {_e}")
    with st.expander("🗄 주가 보관소 · 주가가 끊긴 종목"):
        try:
            with closing(db.connect()) as conn:
                sm = pv.summary(conn)
                gone = pv.gone(conn)
                adj = conn.execute("SELECT ticker, at, factor, rows FROM px_adjust ORDER BY at DESC LIMIT 20").fetchall()
        except Exception as e:  # noqa: BLE001
            st.caption(f"보관소를 읽지 못했어요: {e}")
            return
        st.caption(f"보관 {sm['tickers']:,}종목 · {sm['rows']:,}줄 ({sm['first'] or '-'} ~ {sm['last'] or '-'}) · 오늘 대상 {sm['watch']:,}종목 · 끊김 {sm['gone']:,}종목. "
                   "yfinance·토스 모두 상장폐지 종목의 과거 주가를 주지 않아서, 우리가 신호를 낸 종목만 미리 보관해요(매일 아침).")
        if gone:
            st.dataframe(pd.DataFrame([{"티커": t, "마지막 거래일": g["last_date"], "마지막 종가($)": g["last_close"], "알아챈 날": g["detected"], "이유": g["reason"]}
                                       for t, g in sorted(gone.items(), key=lambda kv: kv[1]["detected"] or "", reverse=True)]),
                         hide_index=True, width="stretch", column_config={"마지막 종가($)": st.column_config.NumberColumn(format="%.4f")})
        if adj:
            st.caption("병합으로 예전 보관 가격을 맞춘 기록: " + " · ".join(f"{t} ×{f:.3g}({str(a)[:10]}, {n}줄)" for t, a, f, n in adj))
