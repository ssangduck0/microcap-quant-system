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


TABS = ["📌 한눈에", "🧨 숏·수급", "🏦 공급·근거", "🏆 성과·이력", "⚡ 지금", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]
_COLOR = {"red": "red", "orange": "orange", "green": "green", "gray": "gray"}


def _money(v) -> str:
    return "-" if v is None else (f"${v:,.2f}" if v >= 1 else f"${v:.4f}")


def _head(t: str, b: dict, hd: dict, ms: list, why: str) -> None:
    """서랍 머리: 티커·이름·가격·등락 + 칩 + 한 줄(하락 원인 첫 후보 또는 공식 잔고)."""
    chips = ""
    if hd.get("sho"):
        chips += ui.chip(f"Reg SHO {hd['sho']}일째", "red")
    if hd.get("dil"):
        chips += ui.chip(f"희석 {hd['dil']}", "red" if hd["dil"] in ("ATM", "ELOC", "CB") else "orange" if hd["dil"] not in ("CLEAN", "NONE") else "gray")
    if hd.get("listing"):
        chips += ui.chip("상장 기준 미달 통지", "red")
    if hd.get("n_sig"):
        chips += ui.chip(f"우리 신호 {hd['n_sig']}(30일)", "blue")
    if ms:
        chips += ui.chip(f"멀티 시그널 {len(ms)}", "purple", tip=", ".join(ms))
    px = hd.get("price")
    chg = hd.get("chg")
    st.markdown(f'<span class="qk-drawer"></span><span class="qk-tk qk-dr-num" style="font-size:1.45rem">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">{ui.esc(b["name"])}</span><br>'
                + ("" if not px else f'<span class="qk-dr-num" style="font-size:1.05rem">{ui.esc(_money(px))}</span>&nbsp;'
                   + ("" if chg is None else f'<span style="color:{"#E5484D" if chg < 0 else "#30A46C"};font-weight:700">{chg:+.1f}%</span>&nbsp;')
                   + f'<span class="qk-dr-lbl">{ui.esc(hd.get("asof") or "")} 종가</span>')
                + f'<div style="margin-top:4px">{chips}</div>' + (f'<div class="qk-sub" style="margin-top:2px">{ui.esc(why)}</div>' if why else ""), unsafe_allow_html=True)


def _grid(hd: dict) -> str:
    stale = hd.get("ib_asof") and str(hd["ib_asof"])[:10].replace(".", "-") < (date.today() - timedelta(days=4)).isoformat()
    cells = [("공식 공매도 잔고", "-" if hd.get("si") is None else f"{hd['si']:.1f}%", f"{hd['si_date'] or ''} 결제 기준"),
             ("청산 소요일", "-" if hd.get("dtc") is None else f"{hd['dtc']:.1f}일", "공식"),
             ("대차 수수료(IBKR)", "-" if hd.get("fee") is None else f"{hd['fee']:,.0f}%", ("목록에서 빠짐 · " + str(hd["ib_asof"])[:10]) if stale else f"빌릴 주식 {hd['avail'] or 0:,.0f}"),
             ("유통주식", "-" if not hd.get("float") else (f"{hd['float'] / 1e6:,.2f}M주"), "적을수록 크게 움직임"),
             ("Reg SHO", f"{hd['sho']}일 연속" if hd.get("sho") else "미등재", "미등재 ≠ 결제 실패 없음"),
             ("30일 고점", _money(hd.get("hi30")), "" if not (hd.get("hi30") and hd.get("price")) else f"지금은 {(hd['price'] / hd['hi30'] - 1) * 100:+.0f}%")]
    return '<div class="qk-dr-grid">' + "".join(f'<div class="c"><div class="qk-dr-lbl">{ui.esc(a)}</div><div class="qk-dr-num">{ui.esc(v)}</div><div class="qk-dr-lbl">{ui.esc(s)}</div></div>'
                                               for a, v, s in cells) + "</div>"


def _box(title: str, rows: list[str]) -> str:
    return f'<div class="qk-dr-box"><div class="h">{ui.esc(title)}</div>' + "".join(rows) + "</div>"


def _ladder_html(pts: list[dict]) -> str:
    if not pts:
        return ""
    lo, hi = pts[0]["price"], pts[-1]["price"]
    span = (hi - lo) or 1
    out, last_x = [], -99
    for p in pts:
        x = (p["price"] - lo) / span * 100
        low = x - last_x < 12   # 가까우면 아래 줄로
        last_x = x if not low else last_x
        out.append(f'<div class="p {p["kind"]}{" lo" if low else ""}" style="left:{x:.1f}%"><div class="qk-dr-num">{ui.esc(_money(p["price"]))}</div><div class="dot"></div>'
                   f'<div class="qk-dr-lbl">{ui.esc(p["label"])}</div></div>')
    return '<div class="qk-ladder"><div class="ln"></div>' + "".join(out) + "</div>"


def _tab_short(t: str, hd: dict) -> None:
    with closing(db.connect()) as conn:
        try:
            last = conn.execute("SELECT MAX(date) FROM regsho_files WHERE status='ok'").fetchone()[0]
        except Exception:  # noqa: BLE001
            last = None
    url = f"https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{last.replace('-', '')}.txt" if last else "https://www.nasdaqtrader.com/trader.aspx?id=regshothreshold"
    st.markdown(_box("Reg SHO(결제 실패 기준 미달 목록)", [
        f'<div class="qk-dr-row"><b style="color:{"#E5484D" if hd.get("sho") else "inherit"}">{"등재 · " + str(hd["sho"]) + "일 연속" if hd.get("sho") else "미등재"}</b>'
        f'<span class="d">NASDAQ · 기준일 {ui.esc(last or "-")} · <a href="{url}" target="_blank">거래소 공식 목록</a></span></div>',
        '<div class="qk-dr-lbl">미등재가 결제 실패(FTD)가 없다는 뜻은 아니에요 · 등재가 숏스퀴즈 증거도 아니에요</div>']), unsafe_allow_html=True)
    import shortpanel_ui
    shortpanel_ui.render(t)


def _tab_supply(t: str, hd: dict) -> None:
    import drawer
    with closing(db.connect()) as conn:
        sup = drawer.supply_status(conn, t)
        pts = drawer.ladder(conn, t, hd.get("price"))
        ul = drawer.unlock(conn, t, hd.get("price"))
        fs = [f for f in drawer.filings(conn, t, 365) if f["form"].upper().startswith(("8-K", "S-1", "F-1", "S-3", "F-3", "424B", "EFFECT", "DEF 14", "PRE 14", "10-Q", "10-K", "20-F", "6-K"))]
    st.markdown(_box("희석 수단 — 확인됨 / 공시에 없음 / 모름", [
        f'<div class="qk-dr-row"><span style="width:42%">{ui.esc(s["name"])}</span>{ui.chip(s["state"], _COLOR.get(s["color"], "gray"))}<span class="d">{ui.esc(s["detail"])}</span></div>' for s in sup]
        + ['<div class="qk-dr-lbl">SEC 공시 이력(1년)·물량 장부·스냅샷으로 판정 — \'모름\'은 기록이 없다는 뜻이지 없다는 뜻이 아니에요</div>']), unsafe_allow_html=True)
    rows = [_ladder_html(pts)]
    if ul:
        rows.append("".join(f'<div class="qk-dr-row"><span>{u["label"]} {_money(u["at"])}</span><span class="d">행사가 아래 물량 {u["qty_m"]:,.2f}M주 ({u["n"]}건)</span></div>' for u in ul))
    else:
        rows.append('<div class="qk-dr-lbl" style="margin-top:6px">+30%·+50% 오르면 팔 수 있게 되는 물량: 물량 장부가 비어 있어 계산 못 함(⭐ 워치리스트 \'공시에서 후보 찾기\'·🧾 덕구 스캔으로 채우면 보여요)</div>')
    st.markdown(_box("가격 사다리", rows), unsafe_allow_html=True)
    st.markdown(_box("SEC 공시 근거(최근 1년 · 핵심 양식)", [
        f'<div class="qk-dr-row"><b style="width:74px">{ui.esc(f["form"])}</b><span style="width:46px">{ui.esc(drawer._md(f["filed"]))}</span>'
        f'<span class="d">{ui.esc(("항목 " + f["items"]) if f["items"] else "")} <a href="{drawer.edgar_url(t, f["form"])}" target="_blank">원문 목록</a></span></div>' for f in fs[:10]]
        or ['<div class="qk-dr-lbl">최근 1년 핵심 공시 기록 없음</div>']), unsafe_allow_html=True)


def _tab_track(t: str) -> None:
    import drawer
    with closing(db.connect()) as conn:
        sg = drawer.signals(conn, t)
        hs = drawer.history(conn, t)
    col = {"성공": "green", "실패": "red"}
    st.markdown(_box("이 종목에 난 우리 신호와 결과(🏆 성과 공표 기준)", [
        f'<div class="qk-dr-row"><span style="width:44px">{ui.esc(s["date"][5:].replace("-", "/"))}</span><span style="flex:1">{ui.esc(s["name"])}</span>'
        f'<span class="qk-dr-num" style="width:70px;text-align:right">{ui.esc(_money(s["entry"]) if s["entry"] else "-")}</span>'
        f'<span class="d" style="flex:none;width:110px">{"" if s["max_up"] is None else f"{s["max_up"]:+.1f}% / {s["max_down"]:+.1f}%"}</span>{ui.chip(s["status"] or "-", col.get(s["status"], "gray"))}</div>'
        for s in sg] + ['<div class="qk-dr-lbl">최고 / 최저 = 신호 뒤 지금까지 · \'낮아야 맞음\' 출처는 실패가 맞는 쪽</div>'] if sg else ['<div class="qk-dr-lbl">최근 기록된 신호 없음</div>']),
        unsafe_allow_html=True)
    st.markdown(_box("상태 변화 이력(60일)", [f'<div class="qk-tl"><span class="d">{ui.esc(h["date"][5:].replace("-", "/"))}</span><span>{ui.esc(h["text"])}</span></div>' for h in hs]
                     or ['<div class="qk-dr-lbl">큰 변화 없음</div>']), unsafe_allow_html=True)


def render(t: str, focus: str | None = None) -> None:
    import drawer
    import multisignal
    t = t.upper()
    b = _basics(t)
    sn, rep = b["snap"], db.get_report(t) or {}
    rw = rep.get("runway") or {}
    ms = multisignal.collect().get(t, [])
    with closing(db.connect()) as conn:
        hd = drawer.headline(conn, t)
        cz = drawer.causes(conn, t)
        sup = drawer.supply_status(conn, t)
    if hd.get("price") is None and sn.get("price"):
        hd["price"], hd["chg"] = sn["price"], sn.get("day_change_pct")
    why = (cz[0]["title"] + " — " + cz[0]["why"]) if cz else ("" if hd.get("si") is None else f"공식 공매도 잔고 {hd['si']:.1f}%({hd['si_date']} 결제 기준)")
    _head(t, b, hd, ms, why)
    h1, h2 = st.columns(2)
    h1.link_button("📲 토스증권 이동", tosslink.url(t), width="stretch")
    if h2.button("🏢 기업 분석 전체 보기", key=f"dlg_co_{t}", width="stretch"):
        st.session_state["lookup_ticker"] = t
        pg = st.session_state.get("_pg_lookup")
        if pg is not None:
            st.switch_page(pg)
    names = list(TABS)
    if focus == "short":  # 스퀴즈 화면에서 열면 숏·수급 탭부터
        names = ["🧨 숏·수급"] + [n for n in TABS if n != "🧨 숏·수급"]
    if focus == "live":  # 애프터·실시간 화면에서 열면 지금 분석부터
        names = ["⚡ 지금"] + [n for n in TABS if n != "⚡ 지금"]
    tl = st.tabs(names)
    with tl[names.index("⚡ 지금")]:
        import live_ui
        live_ui.render(t, key="dlg")
    tabs = [tl[names.index(n)] for n in ["📌 한눈에", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]]
    with tl[names.index("🧨 숏·수급")]:
        _tab_short(t, hd)
    with tl[names.index("🏦 공급·근거")]:
        _tab_supply(t, hd)
    with tl[names.index("🏆 성과·이력")]:
        _tab_track(t)
    with tabs[0]:  # 📌 한눈에: 지표 6칸 · 하락 원인 후보 → 기본 정보 → ✅ 충족 신호 · ⚠️ 리스크 → 📌 이벤트 → 📝 최종 정리 (+ 💬 참고)
        st.markdown(_grid(hd), unsafe_allow_html=True)
        if cz:
            st.markdown(_box("하락 원인 후보 — 규칙으로 고름 · 확정 아님", [f'<div style="font-size:.86rem;padding:3px 0"><b>{i + 1}. {ui.esc(c["title"])}</b> '
                                                                     f'<span class="qk-sub">{ui.esc(c["why"])} · 다음 확인: {ui.esc(c["next"])}</span></div>' for i, c in enumerate(cz)]),
                        unsafe_allow_html=True)
        st.markdown("**희석 수단** " + "".join(ui.chip(f"{s['name'].split('(')[0]} {s['state']}", _COLOR.get(s["color"], "gray"), tip=s["detail"]) for s in sup)
                    + ' <span class="qk-sub">· 자세히는 🏦 공급·근거</span>', unsafe_allow_html=True)
        import glance
        glance.render(t)
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
