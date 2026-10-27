"""🧪 가상매매 화면 — 전략 5개 비교표(이번 장부) + 고른 전략의 수익률·승률·열린 포지션·거래 기록·누적 손익 + 지난 장부 + (종합 순위) 신호별 성과."""
import pandas as pd
import streamlit as st

import chartpop

import access
import db
import papertrade as pt
import tosslink
import ui_kit as ui


def _last() -> dict:
    try:
        m = db.read_df("SELECT ticker, price FROM daily_move WHERE date=(SELECT MAX(date) FROM daily_move)")
        return dict(zip(m["ticker"], m["price"]))
    except Exception:  # noqa: BLE001
        return {}


def _strategies() -> list[str]:
    keys = list(pt.STRATEGIES)
    if access.is_guest():   # 👥 방문객에게는 저금통 종목을 보이지 않음 → 저금통 장부도 숨김
        keys = [k for k in keys if k != "piggy"]
    return keys


def render() -> None:
    ui.title("가상매매", "전략 5개를 각각 따로 장부로 돌려 어느 방식의 승률이 좋은지 비교해요. 청산은 '익절·손절 중 먼저 닿은 쪽'이고 데이마켓·프리·애프터까지 봐요"
             "(스캐너 1분봉 실시간 + 아침에 세션별 고점·저점 기록으로 보완). 같은 구간에서 둘 다 닿으면 손절로 봐요(보수적). 실제 체결과 다를 수 있어요.")
    keys = _strategies()
    last = _last()
    cmp_df = pt.compare(last, keys)
    st.markdown("**전략 비교(각 전략의 이번 장부)** — 규칙은 ⚙️ 관리 모드 → 🧪 가상매매 전략별 규칙에서 바꿔요(새 매수부터 적용).")
    st.dataframe(cmp_df.drop(columns=["key"]), hide_index=True, width="stretch",
                 column_config={"승률(%)": st.column_config.NumberColumn(format="%.0f%%"), "평균 수익률(%)": st.column_config.NumberColumn(format="%+.1f%%"),
                                "청산 수익률(%)": st.column_config.NumberColumn(format="%+.1f%%"), "실현 손익($)": st.column_config.NumberColumn(format="%+.0f"),
                                "평가 손익($)": st.column_config.NumberColumn(format="%+.0f")})
    st.caption("승률 = 청산한 거래 중 수익인 비율 · 평균 수익률 = 거래당 평균 · 청산 수익률 = 실현 손익 ÷ 투입 금액. 거래 수가 적을 때는 우연일 수 있어요.")
    names = [pt.STRATEGIES[k]["name"] for k in keys]
    sel = st.radio("전략", names, horizontal=True, key="pt_strat", label_visibility="collapsed")
    k = keys[names.index(sel)] if sel in names else keys[0]
    c = pt.settings()[k]
    st.markdown(f"#### {pt.STRATEGIES[k]['name']}")
    st.caption(f"{pt.STRATEGIES[k]['desc']} · 지금 규칙: {pt.rule_text(c, k)} · 종목당 ${c['usd']:,.0f} · 하루 최대 {c['n']}개" + ("" if c["on"] else " · ⏸ 꺼짐(새 매수 없음)"))
    b = pt.book(k)
    df = pt.trades(b, k)
    s = pt.summary(df, last)
    st.caption(f"이번 장부 시작: {b[:10]} · 충분히 쌓이면 '초기화'로 새로 시작하세요(지난 장부는 아래에 남아요).")
    ui.cards([{"t": "청산 수익률(이번 장부)", "v": "-" if s["ret"] is None else f"{s['ret']:+.1f}%", "s": f"실현 손익 ${s['pnl']:+,.0f}", "accent": True},
              {"t": "승률", "v": "-" if s["win"] is None else f"{s['win']:.0f}%", "s": f"청산 {s['closed']}건"},
              {"t": "평균 수익률/건", "v": "-" if s["avg"] is None else f"{s['avg']:+.1f}%"},
              {"t": "열린 포지션", "v": f"{s['open']}개", "s": f"평가 손익 ${s['open_pnl']:+,.0f}"}])
    if df.empty:
        when = {"rank": "내일 아침 갱신 작업부터", "pick": "PICK '유력' 종목이 나오면 아침 갱신 때", "close": "장마감 전 BEST·후보가 나오면 스캐너가",
                "piggy": "저금통 종목이 🟢 저점 구간에 들어오면 아침 갱신 때", "after": "애프터 진입 구간 신호가 나면 스캐너가"}[k]
        st.info(f"아직 이 전략의 기록이 없어요. {when} 매수를 시작해요.")
    else:
        op = df[df["status"] == "open"].copy()
        if not op.empty:
            op["현재가"] = [last.get(t) for t in op["ticker"]]
            op["평가(%)"] = [(p / e - 1) * 100 if p else None for p, e in zip(op["현재가"], op["entry"])]
            op["익절가"] = [pt.levels(r)[0] for r in op.to_dict("records")]
            op["손절가"] = [pt.levels(r)[1] for r in op.to_dict("records")]
            st.markdown("**열린 포지션**")
            st.dataframe(op[["day", "ticker", "entry", "현재가", "평가(%)", "익절가", "손절가", "note"]].rename(columns={"day": "매수일", "ticker": "티커", "entry": "매수가", "note": "메모"}),
                         hide_index=True, width="stretch", column_config={"평가(%)": st.column_config.NumberColumn(format="%+.1f%%")})
        cl = df[df["status"] == "closed"].copy()
        if not cl.empty:
            cum = cl.sort_values("exit_day").groupby("exit_day")["pnl"].sum().cumsum().reset_index()
            st.markdown("**누적 실현 손익($)**")
            chartpop.line(cum.set_index("exit_day")["pnl"].rename("누적 손익($)"), key=f"pt_cum_{k}", title="누적 실현 손익($)", height=180, zero=True)
            st.markdown("**거래 기록**")
            cl["규칙"] = [pt.rule_text({"tp": r["tp"] or 0, "sl": r["sl"] or 0, "hold": r["hold"] or 0}, k) for r in cl.to_dict("records")]
            tb = cl[["day", "ticker", "entry", "exit_day", "exit", "ret", "pnl", "reason", "규칙", "note"]].rename(columns={
                "day": "매수일", "ticker": "티커", "entry": "매수가", "exit_day": "매도일", "exit": "매도가", "ret": "수익률(%)", "pnl": "손익($)", "reason": "청산 이유", "note": "메모"})
            tb.insert(2, "토스", [tosslink.url(t) for t in tb["티커"]])
            st.dataframe(tb, hide_index=True, width="stretch", column_config={"토스": st.column_config.LinkColumn(display_text="📲"),
                                                                              "수익률(%)": st.column_config.NumberColumn(format="%+.1f%%"), "손익($)": st.column_config.NumberColumn(format="%+.0f")})
    st.divider()
    allt = pt.trades(strategy=k)
    if not allt.empty:
        books = []
        for bk, g in allt.groupby("book"):
            sm = pt.summary(g)
            books.append({"장부 시작": bk[:10], "거래": sm["n"], "청산": sm["closed"], "승률(%)": sm["win"], "수익률(%)": sm["ret"], "실현 손익($)": sm["pnl"]})
        st.markdown("**장부별 결과(초기화 기록)**")
        st.dataframe(pd.DataFrame(books).sort_values("장부 시작", ascending=False).round(1), hide_index=True, width="stretch")  # 승률 16.6667 → 16.7
        if k == "rank":
            bs = pt.by_signal(allt)
            if not bs.empty:
                st.markdown("**신호별 성과(전체 기간 · 가중치 조정 참고)** — '있을 때 평균'이 '없을 때'보다 낮은 신호는 🏁 순위 가중치를 줄여 볼 후보예요(거래 수가 적으면 우연일 수 있어요).")
                st.dataframe(bs, hide_index=True, width="stretch", column_config={c_: st.column_config.NumberColumn(format="%+.1f%%") for c_ in ("있을 때 평균(%)", "없을 때 평균(%)")})
    if not access.is_guest():
        with st.expander(f"🔄 초기화({pt.STRATEGIES[k]['name']} 새 장부 시작)"):
            st.caption("이 전략의 장부를 닫고 오늘부터 새 장부로 시작해요. 다른 전략은 그대로, 지난 기록은 '장부별 결과'에 남아요.")
            if st.button("초기화", key="pt_reset", type="primary"):
                pt.reset(k)
                st.rerun()
