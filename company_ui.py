"""🏢 기업 분석 화면 — 📰 한 장 요약(B단계 2026-10-28) · 1 회사 · 2 진입 판단 · 3 희석·런웨이 · 4 목적 · 5 일정·보유자 · 6 타임라인·메모."""
import pandas as pd
import streamlit as st

import chartpop

import access
import company
import summary_ui
import tosslink
import ui_kit as ui


def _dd(n) -> str:
    return "" if n is None else (f"D-{n}" if n >= 0 else f"D+{-n}")


DIL_BADGE = {"ATM": ("ATM", "red"), "ELOC": ("ELOC", "red"), "CB": ("전환사채(TOXIC)", "red"), "OFFERING": ("공모·사모", "orange"), "CLEAN": ("희석 없음", "green")}


def header_facts(t: str) -> dict:
    """헤더 한 줄: 섹터·산업(SIC) · 발행 주식 · 유통 주식 · 유통 비율 · 희석 조달 상태. 값이 없으면 None(화면엔 '-')."""
    from contextlib import closing
    import db
    out = {"industry": None, "themes": [], "shares_out": None, "float": None, "float_pct": None, "dilution": None, "share_chg": None}
    try:
        with closing(db.connect()) as conn:
            try:
                m = conn.execute("SELECT sic_desc, themes FROM ticker_meta WHERE ticker=?", (t,)).fetchone()
            except Exception:  # noqa: BLE001  (표가 아직 없는 새 DB·테스트 — 한 단계 실패가 나머지 정보까지 비우지 않게, 2026-10-28)
                m = None
            if m:
                out["industry"] = m[0]
                try:
                    import json
                    out["themes"] = json.loads(m[1] or "[]")
                except Exception:  # noqa: BLE001
                    out["themes"] = []
            f = db.get_fundamentals(conn, t) or {}
            out["shares_out"], out["float"] = f.get("shares_out"), f.get("float_shares")
            try:  # 📡 ChartExchange 발행·유통 주식수(있으면 더 최신)
                import chartex
                cx = chartex.float_of(conn, t)
                if cx and cx.get("shares_float"):
                    out["float"] = cx["shares_float"]
                    out["shares_out"] = cx.get("shares_out") or out["shares_out"]
            except Exception:  # noqa: BLE001
                pass
            if out["shares_out"] and out["float"]:
                out["float_pct"] = float(out["float"]) / float(out["shares_out"]) * 100
            d = db.get_dilution(conn, t) or {}
            out["dilution"] = d.get("status")
            try:  # 🔬 ⑥ 직전 분기 주식수 변동(SEC 표지 이력, 2026-10-28) — 🏁 순위 카드·🎯 PICK·🐷 저금통과 같은 기준·색
                import shares as _sh
                sc = _sh.change(t, conn)
                if sc:
                    _p = round(sc["pct"], 6)
                    out["share_chg"] = {"pct": sc["pct"], "cls": "bad" if _p > 20 else "warn" if _p > 10 else "ok", "d": f"{sc['d0']}→{sc['d1']}", "src": sc.get("src", "")}
            except Exception:  # noqa: BLE001
                out["share_chg"] = None
    except Exception:  # noqa: BLE001
        pass
    return out


def _fmt_sh(v) -> str:
    return "-" if not v else (f"{v / 1e6:,.2f}M주" if v >= 1e6 else f"{v:,.0f}주")


def share_chip(hf: dict) -> str:
    """⑥ 직전 분기 주식수 변동 칩(순위 카드와 같은 색: +20% 초과 빨강 · 10~20% 주황 · 이내 회색). 표지 자료가 없으면 빈 문자열."""
    sc = hf.get("share_chg")
    if not sc:
        return ""
    color = {"bad": "red", "warn": "orange"}.get(sc["cls"], "gray")
    return ui.chip(f"주식수 {sc['pct']:+.0f}%(분기)", color,
                   f"직전 두 분기 SEC 표지 {sc['d']} · 검증(10/28): +20% 초과는 60일 뒤 중앙값 −16%·급락 터치 52%, 10~20% 는 −10%·44%, 이내는 −5%·35%")


def render(t: str) -> None:
    import aisummary
    import watch_ui
    t = t.upper()
    df = watch_ui.prices((t,)).get(t)
    c = company.build(t, df)
    s = aisummary.latest(t) or {}
    pr = c.get("pressure") or {}
    # ---------------- 머리말
    h1, h2 = st.columns([4, 1])
    h1.markdown(f'<span class="qk-tk" style="font-size:1.6rem">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">{ui.esc(c["name"])} · {ui.esc(c["sector"] or "")}</span>',
                unsafe_allow_html=True)
    h2.link_button("📲 토스", tosslink.url(t), width="stretch")
    hf = header_facts(t)   # 2026-10-27: 래빗스탁 종목 헤더처럼 기본 정보 한 줄(섹터·산업 · 발행/유통 주식 · 유통 비율 · 희석 배지)
    badge = DIL_BADGE.get(hf["dilution"] or "", ("희석 미확인", "gray"))
    try:  # P1: 토스에서 못 사는 종목(상폐·ETF·미지원)은 헤더에 배지
        import tradable
        _tl = tradable.label(t)
    except Exception:  # noqa: BLE001
        _tl = ""
    try:  # ⚠️ 대폭 할인 전환(OMH 패턴) 배지
        import toxic
        _tx = toxic.badge(t)
    except Exception:  # noqa: BLE001
        _tx = None
    try:  # 📐 차트 관점 칩(기준봉 채널에서 지금 자리 · 생명선/허리) — 2026-10-27
        import chartview_ui
        _cv = chartview_ui.header_chip(t, df)
    except Exception:  # noqa: BLE001
        _cv = ""
    st.markdown(ui.kv([("산업", hf["industry"] or (c["sector"] or "-")), ("발행 주식", _fmt_sh(hf["shares_out"]) if hf["shares_out"] else _fmt_sh(c["shares"])),
                       ("유통 주식", _fmt_sh(hf["float"])), ("유통 비율", "-" if hf["float_pct"] is None else f"{hf['float_pct']:.1f}%")])
                + "<div style='margin:4px 0 8px'>" + ui.chip(f"희석 조달 {badge[0]}", badge[1]) + share_chip(hf) + (ui.chip(f"⛔ {_tl}", "red") if _tl else "") + (ui.chip(_tx[0], _tx[1]) if _tx else "") + _cv
                + "".join(ui.chip(x, "blue") for x in hf["themes"][:3]) + "</div>", unsafe_allow_html=True)
    import verdict_ui   # 🧭 종합 판단 카드(2026-10-31, 김곰 워치리스트 참고): 한 줄 판단 · 올려야 하는 이유 · 현금조달 가능성 · 공시 흐름
    verdict_ui.render(t, c)
    with st.expander("⚡ 지금 분석(1분봉 · 장전·정규장·애프터)"):
        import live_ui
        live_ui.render(t, key="co")
    with st.expander("📊 매매강도 — 토스 실시간 체결 · 금액 구간(XL/L/M/S)별 매수·매도"):   # P2 2026-10-27: 래빗스탁·오르텍스 식
        import flow_ui
        flow_ui.card(t, key="co")
    with st.expander("🕶 다크풀 · 🧨 공매도 · 대차(IBKR) · 숏볼륨"):   # B단계 2026-10-27: 래빗스탁 종목 화면의 다크풀·공매도 카드
        import darkpool_ui
        import shortpanel_ui
        darkpool_ui.card(t, key="co")
        shortpanel_ui.render(t)
    names = ["📰 한 장 요약", "1 회사", "2 진입 판단", "3 희석·런웨이", "4 목적", "5 일정·보유자", "6 타임라인·메모"]   # 📰 BRAI식 한 장 요약(B단계 2026-10-28)
    try:   # 🔁 리셋 사이클(2026-10-30): reset_config 에 행이 있는 종목만, 주인에게만 탭 추가(메뉴 수는 안 늘림 — docs/HANDOFF_whlr.md 검토 메모 6)
        import resetcycle
        rc_on = (not access.is_guest()) and resetcycle.has(t)
    except Exception:  # noqa: BLE001
        rc_on = False
    if rc_on:
        names.append("🔁 리셋 사이클")
    tabs_all = st.tabs(names)
    tabs = tabs_all[1:7]
    with tabs_all[0]:
        summary_ui.render(t, c, df)
    with tabs[0]:
        a, b = st.columns([2, 1])
        with a:
            st.markdown(ui.kv([(c.get("price_label") or "현재가", "-" if not c["price"] else f"${c['price']:.4f}"), ("시가총액(추정)", "-" if not c["mcap"] else f"약 ${c['mcap'] / 1e6:,.2f}M"),
                               ("주식 수(추정)", "-" if not c["shares"] else f"약 {c['shares'] / 1e6:,.2f}M주"), ("회전율", "-" if not c["turnover"] else f"{c['turnover']['pct']:.0f}%")]),
                        unsafe_allow_html=True)
            st.caption(f"주식 수 출처: {c['shares_tag']}")
        with b:
            if df is not None and not df.empty:
                st.caption("최근 20거래일")
                chartpop.line(df["Close"].dropna().tail(20).rename("종가"), key="co_20d", title="최근 20거래일 종가", height=120)
        verdict = " ".join(s.get("판정") if isinstance(s.get("판정"), list) else [str(s.get("판정", ""))]).split()[:1]
        chips = ""
        if verdict and verdict[0]:
            chips += ui.chip(f"AI 판정 {verdict[0]}", "purple")
        for k in (pr.get("parts") or {}):
            chips += ui.chip(k, "red")
        if pr.get("stance"):
            chips += ui.chip(f"구조 {pr['stance']}", {"회피": "red", "보통": "green"}.get(pr["stance"], "gray"))
        st.markdown("**판단** " + (chips or ui.chip("뚜렷한 압박 없음", "gray")), unsafe_allow_html=True)
        sit = "".join(ui.chip(x[:22], "orange") for x in c["risk"][:4])
        st.markdown("**상황** " + (sit or ui.chip("큰 위험 표시 없음", "green")), unsafe_allow_html=True)
        if c["themes"]:
            st.markdown("**테마** " + "".join(ui.chip(x, "blue") for x in c["themes"][:5]), unsafe_allow_html=True)
        ch = c["chain"]
        if ch["count"]:
            st.markdown("**역분할 이력** " + " · ".join(f"{x['date']} {x['text']}" for x in ch["items"][:9])
                        + f"<br>{ui.chip(f'{ch['count']}회 · 누적 1:{ch['cum']:,.0f}', 'red')}" + (ui.chip(f"3년 안 {ch['n3y']}회 — 반복", "red") if ch["n3y"] >= 2 else ""),
                        unsafe_allow_html=True)
        if s.get("한줄요약"):
            st.info(str(s["한줄요약"]))
    with tabs[1]:
        st.markdown(f"**가격 사다리** — 위로 갈수록 회사·물량이 노리는 가격, ★ {c.get('price_label') or '현재가'}")
        for x in c["ladder"]:
            now = x["kind"] == "now"
            st.markdown(f'<div style="display:flex;gap:14px;padding:7px 10px;border-radius:8px;{"background:rgba(54,120,246,.12);font-weight:800" if now else ""}">'
                        f'<span style="width:90px"><b>${x["price"]:.4f}</b></span><span style="width:70px" class="qk-sub">{"" if x["pct"] is None or now else f"{x["pct"]:+.0f}%"}</span>'
                        f'<span>{ui.esc(x["label"])}</span><span class="qk-sub">{ui.esc(x["note"])}</span></div>', unsafe_allow_html=True)
        st.markdown(ui.box("✅ 충족 신호", c["ok"] or ["뚜렷한 신호 없음"], "#30A46C"), unsafe_allow_html=True)
        summary_ui.rule_cards(c.get("clock") or {}, key="co2")   # ⏰ A단계: 보고 기한 · 하락 원인 · PR 소화력
    with tabs[2]:
        st.markdown("**2-1. 희석 물량** (⭐ 워치리스트의 물량 장부 — 공시에서 자동 추출 + 직접 입력)")
        if c["overhang"]:
            st.dataframe(pd.DataFrame([{"종류": o.get("kind"), "수량(M주)": o.get("qty_m"), "행사·전환가($)": o.get("price"), "상태": o.get("status"), "만기": o.get("expiry"),
                                        "비고": o.get("note") or ""} for o in c["overhang"]]), hide_index=True, width="stretch")
        else:
            st.caption("물량 장부가 비어 있어요. ⭐ 워치리스트의 '공시에서 후보 찾기'나 🧾 덕구 스캔으로 채울 수 있어요.")
        rw = c["runway"]
        st.markdown("**3. 런웨이**")
        from pressure import money as _money
        ui.cards([{"t": "현금" + (" (지금 추정)" if rw.get("note") and rw["months"] is not None else ""), "v": _money(rw["cash"]), "s": f"기준 {rw['asof'] or '-'}"},
                  {"t": "월 소진", "v": _money(rw["burn"])},
                  {"t": "런웨이", "v": (rw.get("note") or "-") if rw["months"] is None else f"{rw['months']:.1f}개월", "accent": rw["months"] is not None and rw["months"] < 6,
                   "s": "SEC 재무 기준(종목 리포트 없음)" if rw.get("note") else ""},
                  {"t": "소진 예상 시점", "v": rw["end"] or "-", "s": _dd(rw["dday"])}])
    with tabs[3]:
        st.markdown("**4. 목적** — 회사가 주가를 움직일 이유(필요한 주가 · 기한 · 근거)")
        if not c["purposes"]:
            st.caption("규칙으로 찾은 뚜렷한 목적이 없어요.")
        for p in c["purposes"]:
            dd = None if not p["deadline"] else (pd.Timestamp(p["deadline"]).date() - pd.Timestamp.today().date()).days
            st.markdown(ui.box(f"{p['title']} · {p['urgency']}", [("필요한 주가 " + (f"${p['need']:.4f} ({p['need_pct']:+.0f}%)" if p["need"] else "—")),
                                                                  "기한 " + (f"{p['deadline']} ({_dd(dd)})" if p["deadline"] else "—"), "근거 " + p["why"]], "#E5484D"),
                        unsafe_allow_html=True)
        if s:
            st.caption("서술형 판단(해소하려는 문제·압박 목적)은 리포트 팝업의 🤖 AI 요약, 깊은 원문 분석은 🧾 덕구 스캔을 보세요.")
    with tabs[4]:
        st.markdown("**5. 예정 이벤트**")
        ev = c["events_ahead"]
        if ev:
            for e in ev[:12]:
                st.markdown(f'{ui.chip(_dd(e["dday"]), "red" if e["dday"] <= 3 else "orange" if e["dday"] <= 14 else "gray")} <b>{e["date"]}</b> {ui.esc(e["kind"])} — '
                            f'<span class="qk-sub">{ui.esc(e["title"])}</span>', unsafe_allow_html=True)
        else:
            st.caption("등록된 예정 이벤트가 없어요.")
        h = c["holders"]
        st.markdown("**6. 보유자·내부자** (Form 4 내부자 거래 · 13D/13G 5% 신고)")
        if h["insiders"]:
            st.dataframe(pd.DataFrame([{"이름": x["owner"], "직책": x["title"], "매수($)": x["buy"], "매도($)": x["sell"], "거래 후 보유(주)": x["after"], "최근": x["last"]}
                                       for x in h["insiders"]]), hide_index=True, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="%,.0f") for k in ("매수($)", "매도($)", "거래 후 보유(주)")})
        if h["big"]:
            st.caption("5% 대량보유 신고: " + " · ".join(f"{x['d']} {x['form']}" for x in h["big"]))
        if not h["insiders"] and not h["big"]:
            st.caption("기록된 내부자 거래·대량보유 신고가 없어요. 헤지펀드 평단·매도 선례는 🧾 덕구 스캔에서 확인하세요.")
    with tabs[5]:
        st.markdown("**8. 타임라인** (최근 1년 공시·병합·통지·내부자)")
        tl = c["timeline"]
        if tl:
            st.markdown(ui.box("", [f"{e['icon']} {e['date']} {e['text']}" for e in tl[:30]]), unsafe_allow_html=True)
        else:
            st.caption("기록이 없어요.")
        if not access.is_guest():
            st.markdown("**7. 내 메모** (나만 보임)")
            memo = st.text_area("메모", company.memo_get(t), height=120, key=f"memo_{t}", label_visibility="collapsed", placeholder="진입가·근거·관찰 포인트")
            if st.button("메모 저장", key=f"memo_save_{t}"):
                company.memo_set(t, memo)
                st.success("저장했어요.")
    if rc_on:
        with tabs_all[7]:
            import resetcycle_ui
            resetcycle_ui.render(t, df)
