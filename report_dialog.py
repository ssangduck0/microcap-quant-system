"""📄 종목 리포트 팝업 — 어디서든 '📄 리포트' 를 누르면 래빗스탁처럼 창이 뜬다: 📌 한눈에 · 🤖 AI 요약 · 🔀 교차검증 · 🧾 덕구 스캔(섹션별 넘기기)."""
import json
from contextlib import closing
from datetime import date, timedelta

import streamlit as st

import db
import tosslink
import ui_kit as ui


def button(t: str, key: str, container=None) -> None:
    c = container or st
    if c.button("📄 리포트", key=f"rp_{key}_{t}", width="stretch", type="primary"):
        open_report(t)


@st.dialog("📄 종목 리포트", width="large")
def open_report(t: str, focus: str | None = None) -> None:
    render(t, focus)


def _basics(t: str) -> dict:
    with closing(db.connect()) as conn:
        s = conn.execute("SELECT price, day_change_pct, float_shares, dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        name = ""
        try:
            r = conn.execute("SELECT name FROM ticker_meta WHERE ticker=?", (t,)).fetchone()
            name = r[0] if r else ""
        except Exception:  # noqa: BLE001
            pass
        try:
            import regsho
            sho = regsho.streaks(conn).get(t)
        except Exception:  # noqa: BLE001
            sho = None
        try:
            news = [dict(x) for x in conn.execute("SELECT form, filed, sentiment, tags, url FROM sec_feed WHERE ticker=? ORDER BY updated DESC LIMIT 3", (t,))]
        except Exception:  # noqa: BLE001
            news = []
        try:
            import pressure
            pr = pressure.evaluate(t, conn, None, None)
        except Exception:  # noqa: BLE001
            pr = None
        try:
            a = conn.execute("SELECT data FROM accum WHERE ticker=? AND period='주간' ORDER BY date DESC LIMIT 1", (t,)).fetchone()
            acc = json.loads(a[0]) if a else None
        except Exception:  # noqa: BLE001
            acc = None
    return {"snap": dict(s) if s else {}, "name": name, "sho": sho, "news": news, "pr": pr, "acc": acc}


def render(t: str, focus: str | None = None) -> None:
    import multisignal
    t = t.upper()
    b = _basics(t)
    sn, rep = b["snap"], db.get_report(t) or {}
    rw = rep.get("runway") or {}
    ms = multisignal.collect().get(t, [])
    h1, h2 = st.columns([3, 1])
    chips = ""
    if sn.get("dilution_status"):
        chips += ui.chip(f"희석 {sn['dilution_status']}", "red" if sn["dilution_status"] in ("ATM", "ELOC", "CB") else "gray")
    if b["sho"]:
        chips += ui.chip(f"Reg SHO {b['sho']}일째", "red")
    if ms:
        chips += ui.chip(f"멀티 시그널 {len(ms)}", "purple", tip=", ".join(ms))
    h1.markdown(f'<span class="qk-tk" style="font-size:1.4rem">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">{ui.esc(b["name"])}</span><br>'
                + ("" if not sn.get("price") else f'<span class="qk-sub">${sn["price"]:.4f}' + ("" if sn.get("day_change_pct") is None else f' · {sn["day_change_pct"]:+.1f}%') + "</span>&nbsp;")
                + chips, unsafe_allow_html=True)
    h2.link_button("📲 토스증권 이동", tosslink.url(t), width="stretch")
    if h2.button("🏢 기업 분석 전체 보기", key=f"dlg_co_{t}", width="stretch"):
        st.session_state["lookup_ticker"] = t
        pg = st.session_state.get("_pg_lookup")
        if pg is not None:
            st.switch_page(pg)
    names = ["📌 한눈에", "⚡ 지금", "🧨 공매도", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]
    if focus == "short":  # 스퀴즈 화면에서 열면 공매도 탭부터
        names = ["🧨 공매도", "📌 한눈에", "⚡ 지금", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]
    if focus == "live":  # 애프터·실시간 화면에서 열면 지금 분석부터
        names = ["⚡ 지금", "📌 한눈에", "🧨 공매도", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]
    tl = st.tabs(names)
    with tl[names.index("⚡ 지금")]:
        import live_ui
        live_ui.render(t, key="dlg")
    tabs = [tl[names.index(n)] for n in ["📌 한눈에", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]]
    with tl[names.index("🧨 공매도")]:
        import shortpanel_ui
        shortpanel_ui.render(t)
    with tabs[0]:  # 📌 한눈에: 기본 정보 → ✅ 충족 신호 · ⚠️ 리스크 → 📌 이벤트 → 📝 최종 정리 (+ 💬 참고)
        import glance
        glance.render(t)
        dil = sn.get("dilution_status")
        st.markdown("**희석 리스크 플래그**" + ui.flags([("ATM", dil == "ATM"), ("ELOC", dil == "ELOC"), ("TOXIC(전환사채)", dil == "CB")]), unsafe_allow_html=True)
        fin = rep.get("financing") or {}
        since = (date.today() - timedelta(days=365)).isoformat()
        n_fin = sum(1 for e in (fin.get("events") if isinstance(fin, dict) else []) or [] if str(e.get("date", "")) >= since)
        rn = None
        try:  # 🪙 리포트가 없어도 SEC 재무 저장소로 · 자금조달 횟수는 공시 이력(회사 압박의 '상습 희석' 과 같은 기준)
            import pressure
            import runway as _rwm
            with closing(db.connect()) as _c:
                rn = _rwm.now(t, _c)
                n_dil = _c.execute("SELECT COUNT(*) FROM sec_hist WHERE ticker=? AND filed >= ? AND (" + " OR ".join("form LIKE ?" for _ in pressure.DILUTION_FORMS) + ")",
                                   (t, since, *[f"{f}%" for f in pressure.DILUTION_FORMS])).fetchone()[0]
        except Exception:  # noqa: BLE001
            n_dil = 0
        from pressure import money as usd
        cash = rw.get("cash") if rw.get("cash") is not None else (rn or {}).get("cash_now")
        burn = rw.get("monthly_burn") if rw.get("monthly_burn") is not None else (rn or {}).get("monthly_burn")
        if rw.get("runway_months") is not None:
            rwy = f"{rw['runway_months']:.1f}개월"
        else:
            import runway as _rwm
            rwy = _rwm.label(rn) if rn else "-"
        st.markdown("**재무지표 요약**" + ui.kv([("현금" + ("" if rw.get("cash") is not None or not rn else "(지금 추정)"), usd(cash)), ("월 소진", usd(burn)),
                                              ("런웨이", rwy), ("최근 1년 자금조달·희석 서류", f"{max(n_fin, n_dil)}회")]), unsafe_allow_html=True)
    import ai_ui
    with tabs[1]:
        ai_ui.render_summary(t, key="dlg")
    with tabs[2]:
        ai_ui.render_check(t, key="dlg")
    with tabs[3]:
        import forensic
        import forensic_ui
        fr = forensic.reports(t)
        if fr.empty:
            st.info("아직 덕구 스캔 보고서가 없습니다.")
        else:
            st.caption(f"저장 {str(fr.iloc[0]['created_at'])[:16]} · 섹션 이름을 누르거나 ◀ ▶ 로 넘기세요.")
            forensic_ui.paged(fr.iloc[0]["content"], key=f"dlg_{t}")
        import access
        if access.can_edit() and st.button("🧾 덕구 스캔 요청(다음 Cowork 실행 때)", key=f"dlg_q_{t}", width="stretch"):
            forensic.queue_add(t)
            st.success("대기열에 넣었습니다.")
