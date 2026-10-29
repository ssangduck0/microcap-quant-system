"""🔁 리셋 사이클 탭(🏢 기업 분석 안) — `reset_config` 에 행이 있는 종목만 탭이 뜬다. 주인 전용(방문객에겐 탭 자체가 안 뜨고, 혹시 와도 안내만).
숫자는 전부 resetcycle.compute() — 공식 근거 docs/whlr_check_2026-10-30.md. 투자 권유가 아니라 검증·관찰용.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import access
import resetcycle as rc
import ui_kit as ui


def _usd(x, nd: int = 2) -> str:
    return "-" if x is None else f"${x:,.{nd}f}"


def _pct(x, nd: int = 0) -> str:
    return "-" if x is None else f"{x:.{nd}f}%"


def _n(x, nd: int = 0) -> str:
    return "-" if x is None else f"{x:,.{nd}f}"


def render(t: str, df: pd.DataFrame | None) -> None:
    t = t.upper()
    if access.is_guest():
        st.caption(access.GUEST_HIDDEN_NOTE)
        return
    cfg = rc.config(t)
    if not cfg:
        st.caption("이 종목은 리셋 사이클 설정이 없어요. 아래 설정에서 추가하면 탭이 생겨요.")
        _settings(t, None)
        return
    st.caption(f"**{cfg.get('label') or '우선주 월례 상환 → 전환가 리셋 구조'}** · 기준가 = 상환일 직전 {cfg.get('window_days') or 10}거래일 **종가의 거래량 가중 평균** · "
               f"전환가 = 기준가 × {1 - float(cfg.get('discount_pct') or 45) / 100:.2f} · 투자 권유가 아니라 **검증용**(리셋가가 지지선이라는 건 가설이에요)")
    if df is None or len(df) == 0:
        st.caption("일봉이 없어 계산할 수 없어요.")
        _settings(t, cfg)
        return
    r0 = rc.compute(t, df, cfg)
    if not r0:
        st.caption("계산할 수 없어요.")
        return
    c1, c2 = st.columns([2, 3])
    vol = c1.number_input("남은 날 하루 거래량 가정(주)", min_value=0, value=int(round(r0["assume_vol"])), step=100_000, key=f"rc_vol_{t}",
                          help="창에 아직 안 들어온 날의 거래량. 기본값 = 최근 창 길이만큼의 거래량 중간값. 거래가 많이 터진 날의 가격이 평균을 지배해요.")
    r = r0 if int(round(r0["assume_vol"])) == int(vol) else rc.compute(t, df, cfg, assume_vol=float(vol))
    if r["adjust_notes"]:
        c2.markdown("".join(ui.chip(f"🔁 {x}", "orange") for x in r["adjust_notes"]) + ui.chip("야후가 아직 안 고친 봉을 현재 주식 기준으로 맞췄어요", "gray"), unsafe_allow_html=True)
    sc = r["scenarios"]
    convs = [s["conv"] for s in sc if s["conv"]]
    sc0 = next((s for s in sc if s["pct"] == 0), None)
    ui.cards([
        {"t": "다음 상환일", "v": f"D-{r['dday']} · {r['redeem'].isoformat()}", "s": rc.kst_note(r["redeem"]), "accent": r["dday"] <= 3},
        {"t": f"지금까지 기준가({r['known_n']}/{r['n']}일)", "v": _usd(r["base_known"]), "s": f"마지막 종가 {_usd(r['last_close'])} ({r['last_date']})"},
        {"t": "전환가 시나리오", "v": f"{_usd(min(convs))} ~ {_usd(max(convs))}" if convs else "-", "s": f"남은 {r['n'] - r['known_n']}일을 마지막 종가의 {int(min(rc.PCTS) * 100)}~+{int(max(rc.PCTS) * 100)}% 로 가정"},
        {"t": "현재가 ÷ 전환가(0% 가정)", "v": _pct(sc0["cur_over_conv"] * 100) if sc0 and sc0["cur_over_conv"] else "-", "s": "8월 105% · 9월 50% 에서 반등(표본 2개) · 10월은 40%→9% 로 패턴 깨짐"},
        {"t": "우선주 잔여 ÷ 시총", "v": f"{r['pref_over_mcap']:.0f}배" if r["pref_over_mcap"] else "-", "s": f"잔여 {_usd(r['pref_usd'], 0)} vs 시총 {_usd(r['mcap'], 0)}"},
    ])
    # ---- 기준가 창
    with st.expander(f"📅 기준가 창 — 상환일 직전 {r['n']}거래일(당일 제외)", expanded=False):
        tot = sum((w["vol"] if w["known"] else r["assume_vol"]) for w in r["window"]) or 1
        st.dataframe(ui.tidy(pd.DataFrame([{"날짜": w["date"].isoformat(), "종가($)": w["close"], "거래량": w["vol"] if w["known"] else r["assume_vol"],
                                            "가중치(%)": (w["vol"] if w["known"] else r["assume_vol"]) / tot * 100,
                                            "상태": "진행 중(장중)" if w.get("live") else ("확정" if w["known"] else "가정")} for w in r["window"]])),
                     hide_index=True, width="stretch")
        if any(w.get("live") for w in r["window"]):
            st.caption("'진행 중' = 미국 정규장이 아직 안 끝나 종가·거래량이 바뀌는 중이에요(지금 값으로 계산).")
    # ---- 시나리오
    st.markdown("**시나리오 — 남은 날 가격에 따라 기준가·전환가가 어디로 가나**")
    st.dataframe(ui.tidy(pd.DataFrame([{"남은 날 가격": f"{s['pct'] * 100:+.0f}% ({_usd(s['px'])})", "기준가($)": s["base"], "전환가($)": s["conv"],
                                        "우선주 1주당 보통주(주)": s["pref_shares"], "현재가÷전환가(%)": None if s["cur_over_conv"] is None else s["cur_over_conv"] * 100,
                                        "남은 날 가중치(%)": s["future_weight"] * 100} for s in sc])), hide_index=True, width="stretch")
    # ---- 물량
    nt = r["note"]
    bullets = []
    if nt:
        bullets.append((f"어음(가동 중): 하루 {_usd(nt['usd'], 0)} ÷ 결제가 {_usd(nt['settle'])} = 약 {_n(nt['shares'])}주 = 발행주식의 {_pct(nt['pct_out'], 1)}/일 · 4거래일이면 {_pct(nt['pct_4d'], 1)}"
                        if nt["active"] else
                        f"어음(아직 미가동 · {cfg.get('note_start') or '조건 미확인'}): 가동되면 하루 {_usd(nt['usd'], 0)} ÷ {_usd(nt['settle'])} = 약 {_n(nt['shares'])}주 = 발행주식의 {_pct(nt['pct_out'], 1)}/일"))
    if r["pref_shares_0"]:
        bullets.append(f"우선주 상환(주식 결제): 1주당 보통주 {r['pref_shares_0']:.0f}주(0% 가정) → 5,000주 상환이면 약 {_n(r['pref_shares_0'] * 5000)}주"
                       + (f" = 발행주식 {_n(cfg.get('shares_out'))}주의 {r['pref_shares_0'] * 5000 / cfg['shares_out'] * 100:.0f}%" if cfg.get("shares_out") else ""))
    if cfg.get("memo"):
        bullets.append(cfg["memo"])
    st.markdown(ui.box("📦 물량 — 어디서 신주가 나오나", bullets), unsafe_allow_html=True)
    # ---- 과거 사이클
    st.markdown("**과거 사이클 — 발표 전환가(현재 주식 기준) vs 상환일 이전 봉만으로 다시 계산한 값(컨닝 없음)**")
    rp = r["replay"]
    if rp:
        st.dataframe(ui.tidy(pd.DataFrame([{"차수": x["seq"], "상환일": x["redeem"], "발표 전환가($)": x["announced"], "재계산 전환가($)": x["calc"],
                                            "재계산−발표(%)": x["calc_vs_ann"], "상환일 종가÷전환가(%)": x["close_ratio"], f"뒤 {rc.AFTER_BARS}봉 최저(%)": x["low_ratio"],
                                            f"뒤 {rc.AFTER_BARS}봉 최고(%)": x["high_ratio"], "최고까지(봉)": x["days_to_high"], "그 사이 병합": x["split_after"] or "",
                                            "출처": x["src"]} for x in rp])), hide_index=True, width="stretch")
        st.caption("재계산이 발표와 크게 다르면: 그 달 창에 병합·미환산 봉이 섞였거나(야후 보정) 창 정의가 달랐던 것. 발표값이 있으면 발표값이 정답.")
    else:
        st.caption("일봉 범위 안에 지난 상환일이 없어요(발표 전환가는 아래 설정에서 추가).")
    # ---- 위험
    sr = r["split_rule"]
    risk = [f"나스닥 반복 병합 규정: 2년 안 병합 {sr['n2y']}번 · 누적 {sr['cum2y']:,.0f}:1 → " + ("**$1 미달 30일이면 유예 없이 상장폐지 절차**(5810(c)(3)(A)(iv))" if sr["flag"] else "해당 없음"),
            (f"발행주식 {_n(cfg.get('shares_out'))}주({cfg.get('shares_asof') or ''}) — 나스닥 공개 유통 50만 주 기준에 가까움" if (cfg.get("shares_out") or 0) < 2_000_000 else ""),
            "리셋가 = 지지선은 **가설**: 그 가격에 사 줄 장치가 없고, 표본은 8·9월 2개. 10월은 상환일 종가가 이미 전환가의 40%, 뒤에 9% 까지 하락.",
            "희석이 끝나지 않는 구조(우선주 청산가치 ≫ 시총) — 오래 들고 가면 녹아요. 반등은 짧게, 손절은 갭에 뚫릴 수 있어요(병합·교환 공시 날).",
            "어음 하한은 고정 문구라 병합 뒤 가격에선 의미 없음 = 주식 결제가 계속됨. 12/4 주총(어음 승인 · 월례 병합 권한)이 다음 갈림길."]
    st.markdown(ui.box("⚠️ 위험", [b for b in risk if b], color="#E5484D"), unsafe_allow_html=True)
    _settings(t, cfg)


def _settings(t: str, cfg: dict | None) -> None:
    """관리 모드(주인) 설정 — 공식·일정·금액을 코드가 아니라 여기서 바꾼다. 비슷한 종목은 이 칸으로 추가."""
    if access.is_guest():
        return
    cfg = cfg or {}
    with st.expander("⚙️ 설정(주인만) — 창 일수·할인율·상환일·우선주·어음·병합", expanded=not bool(cfg)):
        a, b, c = st.columns(3)
        win = a.number_input("기준가 창(거래일)", 1, 60, int(cfg.get("window_days") or 10), key=f"rc_win_{t}")
        disc = b.number_input("할인율(%)", 0.0, 99.0, float(cfg.get("discount_pct") or 45.0), step=1.0, key=f"rc_disc_{t}")
        day = c.number_input("매월 상환일", 1, 28, int(cfg.get("redeem_day") or 5), key=f"rc_day_{t}")
        a, b, c = st.columns(3)
        pp = a.number_input("우선주 1주 상환가($)", 0.0, 1e6, float(cfg.get("pref_price") or 0.0), key=f"rc_pp_{t}")
        pr = b.number_input("남은 우선주(주)", 0.0, 1e12, float(cfg.get("pref_remaining") or 0.0), step=1000.0, key=f"rc_pr_{t}")
        so = c.number_input("보통주 발행주식(현재 기준)", 0.0, 1e15, float(cfg.get("shares_out") or 0.0), step=10000.0, key=f"rc_so_{t}")
        a, b, c = st.columns(3)
        nu = a.number_input("어음 일일 상환액($)", 0.0, 1e9, float(cfg.get("note_daily_usd") or 0.0), step=10000.0, key=f"rc_nu_{t}")
        nf = b.number_input("어음 결제가 하한($)", 0.0, 1e6, float(cfg.get("note_floor") or 0.0), step=0.05, key=f"rc_nf_{t}")
        na = c.checkbox("어음 가동 중", bool(cfg.get("note_active")), key=f"rc_na_{t}")
        a, b, c = st.columns(3)
        sd = a.text_input("예정·방금 병합 날짜(YYYY-MM-DD)", cfg.get("split_date") or "", key=f"rc_sd_{t}")
        sn = b.number_input("병합 비율 1:N (0 = 없음)", 0, 100000, int(round(1 / cfg["split_ratio"])) if cfg.get("split_ratio") else 0, key=f"rc_sn_{t}")
        sa = c.text_input("발행주식 기준일·메모", cfg.get("shares_asof") or "", key=f"rc_sa_{t}")
        label = st.text_input("한 줄 설명", cfg.get("label") or "", key=f"rc_label_{t}")
        ns = st.text_input("어음 가동 조건", cfg.get("note_start") or "", key=f"rc_ns_{t}")
        memo = st.text_area("메모", cfg.get("memo") or "", height=70, key=f"rc_memo_{t}")
        if st.button("설정 저장", key=f"rc_save_{t}"):
            rc.save_config(t, window_days=int(win), discount_pct=float(disc), redeem_day=int(day), pref_price=pp or None, pref_remaining=pr or None,
                           shares_out=so or None, shares_asof=sa, note_daily_usd=nu or None, note_floor=nf or None, note_active=int(na),
                           split_date=sd.strip() or None, split_ratio=(1.0 / sn) if sn else None, label=label, note_start=ns, memo=memo)
            st.success("저장했어요. 화면을 새로 고치면 반영돼요.")
        st.markdown("**발표 전환가 추가**(8-K 의 그 달 전환가 — 발표 당시 주식 기준으로 적으면 병합은 자동으로 곱해요)")
        a, b, c, d = st.columns([2, 1, 1, 2])
        rd = a.text_input("상환일(YYYY-MM-DD)", key=f"rc_cd_{t}")
        sq = b.number_input("차수", 0, 999, 0, key=f"rc_cs_{t}")
        ap = c.number_input("발표 전환가($)", 0.0, 1e9, 0.0, step=0.01, format="%.4f", key=f"rc_cp_{t}")
        src = d.text_input("출처", key=f"rc_csrc_{t}")
        if st.button("사이클 추가", key=f"rc_cadd_{t}") and rd.strip():
            rc.add_cycle(t, rd.strip(), int(sq) or None, ap or None, src)
            st.success("추가했어요.")
