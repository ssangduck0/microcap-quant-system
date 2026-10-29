"""📰 한 장 요약 — BRAI식 공시분석(B단계 2026-10-28): Claude 공시분석 v2 가 남긴 SUMMARY_JSON 을 카드 여섯 장으로.
⏰ 시계(돈이 언제 떨어지나) · 🏗 구조(누가 주식을 들고 있나) · 💸 갚아야 할 돈 일정 · 🏦 조달 예상(ATM 가능일·워런트·사모 시뮬) · 📅 물량 달력 · 🎯 가격대·시나리오
+ ⏰ 규칙 카드(A단계 clock.py · 비용 0): PR 소화력 · 하락 원인 · 다음 보고 기한 — Claude 요약이 없어도 보인다."""
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st

import access
import chartpop
import db
import ui_kit as ui

STATUS_COLOR = {"급함": "#E5484D", "보통": "#F76B15", "여유": "#30A46C"}
DROP_COLOR = {"현물 매도 추정": "#E5484D", "공매 눌림 가능": "#8E4EC6"}
SCEN = (("attack", "🚀 공격", "#30A46C"), ("base", "➖ 기본", "#888"), ("fail", "💀 실패", "#E5484D"))


def _usd(v) -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"${v / 1e6:,.2f}M" if abs(v) >= 1e5 else f"${v:,.0f}"


def _dday(s) -> str:
    if not s:
        return ""
    try:
        n = (date.fromisoformat(str(s)[:10]) - date.today()).days
    except ValueError:
        return ""
    return f"D-{n}" if n >= 0 else f"D+{-n}"


def _md(s) -> str:
    """st.success·st.caption 에 넣는 자유 글: $ 두 개가 있으면 스트림릿이 수식(LaTeX)으로 그려 숫자가 깨짐 → 역슬래시+$ 로."""
    return str(s or "").replace("$", "\\$")


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def rule_cards(ck: dict, key: str = "rc") -> None:
    """⏰ A단계 규칙 카드: 다음 보고 기한 · 하락 원인 · PR 소화력(표)."""
    if not ck:
        return
    c1, c2, c3 = st.columns(3)
    due = ck.get("due") or {}
    with c1:
        if due.get("due"):
            fye = str(due.get("fye") or "")
            st.markdown(ui.box(f"⏰ 다음 정기 보고 {_dday(due['due'])}", [f"{due.get('next_form')} 기한 {due['due']}", f"연장(NT) 제출 땐 {due.get('nt_due')}",
                                                                      f"회계연도 말 {fye[:2]}/{fye[2:]} · {due.get('category') or '-'}" + (" · 외국 발행사(20-F)" if due.get("fpi") else "")], "#3678F6"),
                        unsafe_allow_html=True)
        else:
            st.markdown(ui.box("⏰ 다음 정기 보고", ["아직 계산 전 — 아침 갱신 때 SEC 에서 회계연도 말을 받아 채워요"], "#888"), unsafe_allow_html=True)
    dr = ck.get("drop") or {}
    with c2:
        st.markdown(ui.box(f"📉 하락 원인(규칙) — {dr.get('verdict') or '-'}", [dr.get("why") or "-"], DROP_COLOR.get(dr.get("verdict"), "#888")), unsafe_allow_html=True)
    pr = ck.get("pr") or {}
    with c3:
        st.markdown(ui.box("📣 PR 소화력 — 호재 뒤 고점을 지키는 힘", [pr.get("note") or "최근 240일 안 호재 공시·급등일 없음"] + ([f"PR·급등일 {pr['n']}회"] if pr.get("n") else []),
                           {"약해짐": "#E5484D", "강해짐": "#30A46C"}.get(pr.get("trend"), "#888")), unsafe_allow_html=True)
    if pr.get("rows"):
        df = pd.DataFrame([{"날짜": r["date"], "사유": r["why"], "직전 종가($)": r["prev"], "고가($)": r["high"], "장중 %": r["hi_pct"], "종가 %": r["close_pct"],
                            "상승분 반납 %": None if r["fade"] is None else min(r["fade"], 2) * 100} for r in pr["rows"]])
        st.dataframe(ui.tidy(df), hide_index=True, width="stretch", height=min(300, 38 + 35 * len(df)))


def render(t: str, c: dict, df=None) -> None:
    """🏢 종목 화면 첫 탭. c = company.build(...)(price·shares·clock)."""
    import clock
    import forensic
    import forensic_ai
    t = t.upper()
    price = _num(c.get("price"))
    ck = c.get("clock") or {}
    with closing(db.connect()) as conn:
        s = forensic_ai.summary_latest(conn, t)
        try:
            fu = db.get_fundamentals(conn, t) or {}
        except Exception:  # noqa: BLE001
            fu = {}
    if not access.is_guest():
        b1, b2 = st.columns([1, 2])
        if t in forensic.queue_list():
            b1.caption("📰 공시분석 대기열에 있음 — 아침 갱신 때 분석")
        elif b1.button("📰 Claude 공시분석 요청(대기열)", key="sum_req", help="아침 갱신 때 Sonnet 5.5 가 SEC 원문을 읽고 11개 섹션 보고서 + 한 장 요약을 만듭니다(종목당 약 100~200원, AI 월 예산 안)"):
            forensic.queue_add([t])
            st.success("대기열에 넣었어요 — 다음 아침 갱신 때 분석됩니다.")
        if s:
            b2.caption(f"as-of {s['as_of']} · Claude 공시분석 v2(Sonnet 5.5) · 숫자는 공시 발췌 기반 추정 — 출처 공시일을 꼭 확인")
    if not s:
        st.info("아직 '한 장 요약'이 없어요. Claude 공시분석 v2 가 돌면 ⏰ 시계 · 🏗 구조 · 💸 갚아야 할 돈 · 🏦 조달 예상 · 📅 물량 달력 · 🎯 가격대·시나리오가 채워집니다. "
                "아래는 비용 없이 규칙으로 계산한 것(PR 소화력 · 하락 원인 · 보고 기한).")
        rule_cards(ck, key="sum_rule")
        return
    if s.get("one_liner"):
        st.success(_md(s["one_liner"]))
    clk = s.get("clock") or {}
    r1 = st.columns(3)
    with r1[0]:   # ⏰ 시계
        status = clk.get("status") or "-"
        rm = _num(clk.get("runway_months"))
        bl = [("런웨이 " + (f"{rm:.1f}개월" if rm is not None else "-")), f"현금 {_usd(clk.get('cash_usd'))} · 월 소진 {_usd(clk.get('monthly_burn_usd'))}"]
        if clk.get("cash_need_by"):
            bl.append(f"돈이 필요한 시점 {clk['cash_need_by']} {_dday(clk['cash_need_by'])}")
        if clk.get("why"):
            bl.append(str(clk["why"])[:140])
        st.markdown(ui.box(f"⏰ 시계 — {status}", bl, STATUS_COLOR.get(status, "#888")), unsafe_allow_html=True)
    with r1[1]:   # 🏗 구조
        stc = s.get("structure") or {}
        bl = [str(stc.get("who_holds") or "-")]
        ip = _num(stc.get("insider_pct"))
        if ip is not None:
            bl.append(f"내부자 지분 {ip:.0f}%")
        if stc.get("note"):
            bl.append(str(stc["note"])[:140])
        st.markdown(ui.box("🏗 구조 — 누가 주식을 들고 있나", bl, "#3678F6"), unsafe_allow_html=True)
    with r1[2]:   # 🏦 조달 예상
        fd = s.get("funding") or {}
        bl = [f"가장 가능성 큰 방법: {fd.get('likely') or '불명'}"]
        if fd.get("atm_ok_from"):
            bl.append(f"ATM 가능 시점 {fd['atm_ok_from']} {_dday(fd['atm_ok_from'])}" + (f" · 한도 {_usd(fd['atm_capacity_usd'])}" if _num(fd.get("atm_capacity_usd")) else ""))
        if _num(fd.get("warrants_cash_usd")) is not None:
            bl.append(f"워런트 행사로 들어올 돈 {_usd(fd['warrants_cash_usd'])}")
        if _num(fd.get("convertibles_usd")):
            bl.append(f"전환사채 {_usd(fd['convertibles_usd'])}")
        amt = _num(s.get("total_committed_usd")) or (_num(clk.get("monthly_burn_usd")) or 0) * 6 or None
        sim = clock.pipe_sim(price, amt, _num(fu.get("float_shares")), _num(fu.get("shares_out")) or _num(c.get("shares")))
        if sim:
            bl.append(f"사모 20% 할인 가정: ${sim['price']:.4f}에 {sim['shares'] / 1e6:.2f}M주" + (f" = 유통주식의 {sim['pct_float']:.0f}%" if sim["pct_float"] is not None else "")
                      + f" ({_usd(amt)} 조달 시)")
        if fd.get("why"):
            bl.append(str(fd["why"])[:140])
        st.markdown(ui.box("🏦 조달 예상", bl, "#8E4EC6"), unsafe_allow_html=True)
    # 💸 갚아야 할 돈
    pays = [p for p in (s.get("payments") or []) if isinstance(p, dict)]
    tot = _num(s.get("total_committed_usd"))
    cash = _num(clk.get("cash_usd"))
    st.markdown(_md(f"**💸 갚아야 할 돈·내야 할 돈 일정(12개월)** — 합계 {_usd(tot)}" + (f" · 현금의 {tot / cash * 100:.0f}%" if tot and cash else "")))
    if pays:
        pdf = pd.DataFrame([{"날짜": p.get("date") or "-", "D-day": _dday(p.get("date")), "금액($M)": None if _num(p.get("amount_usd")) is None else _num(p["amount_usd"]) / 1e6,
                             "무엇": p.get("what") or "", "출처": p.get("source") or ""} for p in pays])
        a, b = st.columns([3, 2])
        a.dataframe(ui.tidy(pdf), hide_index=True, width="stretch", height=min(300, 38 + 35 * len(pdf)))
        m = pdf.dropna(subset=["금액($M)"]).copy()
        if not m.empty:
            m["월"] = m["날짜"].astype(str).str[:7].replace("-", "날짜 미정")
            with b:
                chartpop.bar(m.groupby("월")["금액($M)"].sum().rename("금액($M)"), key="sum_pay", title="월별 갚아야 할 돈($M)", height=180, fmt=".2f")
    else:
        st.caption("공시에 적힌 12개월 안 상환·지급 일정 없음(또는 미확인)")
    a, b = st.columns(2)
    with a:   # 📅 물량 달력
        st.markdown("**📅 물량 달력** — 락업 해제 · 등록 효력 · 전환/행사 가능일")
        oc = [x for x in (s.get("overhang_calendar") or []) if isinstance(x, dict)]
        if oc:
            st.dataframe(ui.tidy(pd.DataFrame([{"날짜": x.get("date") or "-", "D-day": _dday(x.get("date")), "무엇": x.get("what") or "", "주식(M)": _num(x.get("shares_m")), "메모": x.get("note") or ""} for x in oc])),
                         hide_index=True, width="stretch", height=min(300, 38 + 35 * len(oc)))
        else:
            st.caption("예정된 물량 일정 없음(또는 미확인)")
        nd = s.get("next_deadline") or {}
        if nd.get("date"):
            st.markdown(ui.chip(f"다음 기한 {nd['date']} {_dday(nd['date'])} · {nd.get('what') or ''}", "orange"), unsafe_allow_html=True)
    with b:   # 🎯 가격대·시나리오
        st.markdown(f"**🎯 주요 가격대·시나리오** — ★ {c.get('price_label') or '현재가'} 기준")
        sc = s.get("scenarios") or {}
        lv = [{"price": _num(x.get("price")), "label": x.get("label") or "", "note": x.get("why") or "", "kind": "ai", "color": ""} for x in (s.get("levels") or []) if isinstance(x, dict) and _num(x.get("price"))]
        for k, nm, col in SCEN:
            x = sc.get(k) or {}
            if _num(x.get("target")):
                lv.append({"price": _num(x["target"]), "label": f"{nm} 시나리오 목표", "note": str(x.get("trigger") or "")[:60], "kind": k, "color": col})
        if price:
            lv.append({"price": price, "label": "★ " + (c.get("price_label") or "현재가"), "note": "", "kind": "now", "color": ""})
        for x in sorted(lv, key=lambda v: -v["price"]):
            now = x["kind"] == "now"
            pct = None if not price or now else (x["price"] / price - 1) * 100
            style = ("background:rgba(54,120,246,.12);font-weight:800;" if now else "") + (f"border-left:4px solid {x['color']};" if x["color"] else "")
            st.markdown(f'<div style="display:flex;gap:12px;padding:6px 10px;border-radius:8px;{style}"><span style="width:86px"><b>${x["price"]:.4f}</b></span>'
                        f'<span style="width:64px" class="qk-sub">{"" if pct is None else f"{pct:+.0f}%"}</span><span>{ui.esc(x["label"])}</span><span class="qk-sub">{ui.esc(x["note"])}</span></div>',
                        unsafe_allow_html=True)
        for k, nm, _col in SCEN:
            x = sc.get(k) or {}
            if x.get("trigger") or x.get("note"):
                st.caption(_md(f"{nm}: {x.get('trigger') or ''}" + (f" → {x['note']}" if x.get("note") else "")))
    svs = s.get("sell_vs_short") or "불명"
    dr = ck.get("drop") or {}
    st.markdown(ui.box("📈 과거 호재 뒤 패턴 · 하락은 현물 매도인가 공매인가", [s.get("pattern") or "-", f"AI 판단: {svs}" + (f" · 규칙 판단: {dr['verdict']}" if dr.get("verdict") else "")],
                       {"현물 매도": "#F76B15", "공매": "#8E4EC6"}.get(svs, "#888")), unsafe_allow_html=True)
    st.markdown("**⏰ 규칙 계산(비용 0 · 매일 갱신)**")
    rule_cards(ck, key="sum_rule")
