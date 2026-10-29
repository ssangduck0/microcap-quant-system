"""🎲 매매 전 시뮬레이션 화면 — 배지(저금통·PICK·순위 카드) + 📇 스크리너 카드 ⑥ 칸(입력 → 1만 번 → 결과). 계산은 presim.py, 여기는 그리기만."""
from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import access
import db
import presim
import ui_kit as ui

COLOR = {"🟢": "green", "🪙": "orange", "🔴": "red", "❔": "gray"}


def badges(tickers, days: int = 3) -> dict[str, dict]:
    """{티커: 최근 기록} — 화면 한 번에 한 번만 읽어서 카드들에 나눠 씀."""
    try:
        with closing(db.connect()) as conn:
            return presim.latest_map(conn, list(tickers), days)
    except Exception:  # noqa: BLE001
        return {}


def badge_text(r: dict | None) -> str:
    """표 셀용 짧은 글: '🟢 익절 48% · 손절 31%'"""
    if not r:
        return ""
    p_tp, p_sl = r.get("p_tp"), r.get("p_sl")
    if p_tp is None:
        p_tp, p_sl = r.get("own_p_tp"), r.get("own_p_sl")
    return f"{r['verdict']} 익절 {p_tp:.0f}% · 손절 {p_sl:.0f}%" if p_tp is not None and p_sl is not None else str(r.get("verdict") or "")


def badge_chip(t: str, lm: dict | None = None) -> str:
    """카드용 칩 HTML(기록 없으면 빈 문자열)."""
    r = (lm or {}).get(t)
    if not r:
        return ""
    txt = badge_text(r)
    tip = (f"🎲 매매 전 시뮬레이션({r['day']}): {presim.KEYS.get(r.get('key'), ('?',))[0]} {r.get('n_ep') or 0}건 기준 · 손절 ${r['sl']:.4g} · 목표 ${r['tp']:.4g} · {r['horizon']}거래일"
           f" · 기대값 {r['ev_pct'] if r.get('ev_pct') is not None else r.get('own_ev')}% — 과거 통계일 뿐, 예측 아님")
    return ui.chip("🎲 " + txt, COLOR.get(r["verdict"], "gray"), tip=tip)


def _bars(t: str) -> pd.DataFrame | None:
    since = (date.today() - timedelta(days=420)).isoformat()
    with closing(db.connect()) as conn:
        d = presim._load_bars(conn, [t], since).get(t)
    if d is None or len(d) < presim.MIN_BARS:
        try:
            import cases, market
            d = cases.drop_incomplete_last_bar(market.download_daily([t], period="2y").get(t))   # 장중이면 오늘 봉 제외(_load_bars 와 같은 규칙)
        except Exception:  # noqa: BLE001
            d = None
    return d


def _result_block(r: dict, key: str) -> None:
    l1, own, sz = r["layer1"], r["own"], r["size"]
    st.markdown(f"**{r['verdict']} {ui.esc(r['verdict_text'])}** <span class='qk-sub'>— 판정 근거: {ui.esc(r['basis'])}</span>", unsafe_allow_html=True)
    cols = st.columns(4)
    if l1.get("n"):
        cols[0].metric("익절 먼저(같은 신호 과거)", f"{l1['p_tp']:.0f}%", help=f"같은 날 둘 다 닿은 날을 익절로 보면 {l1['p_tp_opt']:.0f}% (범위)")
        cols[1].metric("손절 먼저", f"{l1['p_sl']:.0f}%")
        cols[2].metric("결판 안 남", f"{l1['p_none']:.0f}%", help=f"기간 끝 종가 평균 {l1['none_avg'] if l1.get('none_avg') is not None else '-'}%")
        cols[3].metric("기대값(거래당)", f"{l1['ev_pct']:+.1f}%", help=f"낙관 가정이면 {l1['ev_opt']:+.1f}%")
        _plan = (f"사건마다 **그날 박스**(하단×0.95 / 상단)로 — 손절 중앙값 −{l1.get('sl_pct') or 0:.1f}% · 목표 +{l1.get('tp_pct') or 0:.1f}%" if r.get("plan") == "box"
                 else f"손절 −{r['sl_pct']:.1f}% · 목표 +{r['tp_pct']:.1f}%")
        st.caption(f"1겹 · {ui.esc(l1['name'])} 사건 {l1['n']:,}건(2년 × 전체 종목, 신호가 처음 켜진 날 · 유효 표본 {l1.get('n_eff') or 0:,.0f}) · {_plan} · {r['horizon']}거래일"
                   + (f" · 같은 날 둘 다 닿음 {l1['both_pct']:.0f}%" if l1.get("both_pct") else ""), unsafe_allow_html=True)
        b, rec = r.get("base") or {}, r.get("recent") or {}
        if b.get("n"):
            _e = "" if r.get("edge") is None else f" → **기준 대비 {r['edge']:+.1f}%p**(보정 전 {r['edge_raw']:+.1f}%p)"
            st.caption(f"기준(아무 날 {b['n']:,}건)에 같은 계획: 익절 {b['p_tp']:.0f}% · 손절 {b['p_sl']:.0f}% · 기대값 {b['ev_pct']:+.1f}%{_e} · 동전 던지기라면 익절 {r.get('p0') or 0:.0f}%", unsafe_allow_html=True)
        if rec.get("n"):
            st.caption(f"최근 6개월 {rec['n']:,}건만: 익절 {rec['p_tp']:.0f}% · 손절 {rec['p_sl']:.0f}% · 기대값 {rec['ev_pct']:+.1f}%")
    else:
        cols[0].caption("같은 신호의 과거 사건이 아직 부족해요(아침 작업이 사건 표를 쌓아요)")
    if own.get("ok"):
        st.caption(f"2겹 · 이 종목 최근 {own['n_days']}일 섞어 1만 번: 익절 {own['p_tp']:.0f}% · 손절 {own['p_sl']:.0f}% · 결판 안 남 {own['p_none']:.0f}% · 기대값 {own['ev_pct']:+.1f}%"
                   + (f" · 둘 다 {own['both_pct']:.0f}%" if own.get("both_pct") else ""))
    else:
        st.caption(f"2겹(이 종목 최근 250일): {own.get('why', '자료 부족')}")
    for n_ in r.get("notes") or []:
        st.warning(n_)
    try:
        import chartpop
        src = l1 if l1.get("n") else own
        if src.get("p_tp") is not None:
            chartpop.bar(pd.Series({"익절 먼저": src["p_tp"], "손절 먼저": src["p_sl"], "결판 안 남": src["p_none"]}), f"presim_bar_{key}", "확률(%)", height=160, fmt=".0f",
                         note="같은 날 익절·손절이 둘 다 닿은 날은 보수적으로 손절로 셌어요")
    except Exception:  # noqa: BLE001
        pass
    st.markdown(f"**수량** {sz['shares']:,}주 · 약 ${sz['cost_usd']:,.0f}({sz['cost_krw']:,.0f}원) · 손절 때 손실 ${sz['risk_usd']:,.0f}  <span class='qk-sub'>{ui.esc(sz['why'])}</span>", unsafe_allow_html=True)
    st.caption("⚠️ " + presim.WARN)


def render_section(ticker: str, card: dict | None = None) -> None:
    """📇 스크리너 카드 ⑥. 그날 자동 결과가 있으면 먼저 보여 주고, 관리자는 손절·목표를 바꿔 다시 돌릴 수 있음(방문객은 보기만)."""
    t = (ticker or "").upper()
    if not t:
        return
    st.markdown("**🎲 ⑥ 매매 전 시뮬레이션** — 이 손절·이 목표면 과거엔 어땠나(같은 신호 전체 2년 + 이 종목 최근 250일) · 🕰 타임머신과 다른 것: 신호가 아니라 **내 매매 계획**을 재요")
    with closing(db.connect()) as conn:
        last = presim.latest(conn, t, days=7)
    if last:
        st.caption(f"오늘 자동 실행({last['day']} · 출처 {last['source']}): {badge_text(last)} · 손절 ${last['sl']:.4g} · 목표 ${last['tp']:.4g} · {last['horizon']}거래일")
    d = _bars(t)
    if d is None or len(d) < presim.MIN_BARS:
        st.caption(f"일봉이 {0 if d is None else len(d)}일뿐이라 돌릴 수 없어요(필요 {presim.MIN_BARS}일).")
        return
    base = presim.defaults(d, "scr")
    if access.is_guest():
        if not last:
            st.caption("방문객 화면에서는 아침에 자동으로 돌린 결과만 보여요.")
        return
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 0.8, 0.8])
    entry = c1.number_input("매수가($)", min_value=0.0001, value=float(round(base["entry"], 4)), format="%.4f", key=f"ps_e_{t}")
    sl = c2.number_input("손절가($)", min_value=0.0001, value=float(round(base["sl"], 4)), format="%.4f", key=f"ps_s_{t}", help="기본값: 레벨 맵 1차 지지 하단(없으면 −10%)")
    tp = c3.number_input("목표가($)", min_value=0.0001, value=float(round(base["tp"], 4)), format="%.4f", key=f"ps_t_{t}", help="기본값: 1차 저항(20일 고가, 없으면 +30%)")
    hz = c4.selectbox("기간(거래일)", [5, 10, 20, 40], index=3, key=f"ps_h_{t}")
    n_sim = c5.selectbox("횟수", [2000, 10000], index=1, key=f"ps_n_{t}")
    if st.button("🎲 1만 번 돌려 보기", key=f"ps_go_{t}", type="primary"):
        with closing(db.connect()) as conn:
            try:
                import timemachine as tm
                dil, cov = tm._dil_dates(conn, {t}), tm._covered(conn)
            except Exception:  # noqa: BLE001
                dil, cov = {}, set()
            r = presim.run_one(conn, t, d, "scr", entry=entry, sl=sl, tp=tp, horizon=int(hz), n_sim=int(n_sim), dil_dates=dil.get(t, []), covered=t in cov, seed=None)
        st.session_state[f"ps_res_{t}"] = r
    r = st.session_state.get(f"ps_res_{t}")
    if r:
        if not r.get("ok"):
            st.warning(r.get("why", "실패"))
        else:
            if card and card.get("exclusion"):
                st.error("⚠️ 이 종목은 우리 후보에서 제외된 이유가 있어요(위 ① 참고) — 확률이 좋아 보여도 희석·상장유지 위험이 먼저예요")
            _result_block(r, t)
