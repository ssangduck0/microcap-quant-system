"""🎯 PICK +30% 화면 — 고정 조건 깔때기 · 유력·임박 / 임박 / 압박 순 · 칩 그리드(휴대폰 3열) · 새로고침 순서 비교 · 텍스트 복사 · 📊 PICK 변동."""
from contextlib import closing

import pandas as pd
import streamlit as st

import db

import pick30
import ui_kit as ui

STC = {"유력": "#E5484D", "가능": "#F76B15", "대기": "#B58A00"}


@st.cache_data(ttl=120, show_spinner=False)
def _scan():
    """🔥 화면 캐시(pagecache 'pick30', quant-warm 10분마다)에서 꺼내고, 없거나 25분 넘게 오래됐으면 직접 계산해 넣어 둠(2026-10-30: 첫 화면 12초 → 즉시)."""
    import pagecache
    return pagecache.get_or_build("pick30")


def grid(rows: list[dict], first: dict | None = None, badges: dict | None = None, guest: bool | None = None) -> str:
    """두 줄 칩: 1줄 순위·티커(↑↓) / 2줄 상태·상승률·D-day — 글자가 잘리지 않게. 방문객(A안)은 상승률을 전일 종가 기준으로 다시 계산."""
    import access
    guest = access.is_guest() if guest is None else guest
    gp = {}
    if guest:   # 👥 토스 데이터 정책 A안(2026-10-30): 회사 목표가 대비 % 를 스냅샷의 당일 현재가가 아니라 전일 종가(야후 일봉)로
        import guestpx
        gp = guestpx.prev_close([r["ticker"] for r in rows])
    cells = []
    for i, r in enumerate(rows, 1):
        pct = r["pct"]
        if guest:
            px = (gp.get(r["ticker"]) or {}).get("close")
            tgt = r.get("target") or (None if not r.get("price") or pct is None else float(r["price"]) * (1 + float(pct) / 100))
            pct = None if not px or not tgt else (float(tgt) / px - 1) * 100
        mv = ""
        if first and r["ticker"] in first and first[r["ticker"]] != i:
            d = first[r["ticker"]] - i
            mv = f'<span style="color:{"#E5484D" if d > 0 else "#3678F6"};font-size:.72rem;margin-left:4px">{"↑" if d > 0 else "↓"}{abs(d)}</span>'
        dd = "" if r["imm_days"] is None or r["imm_days"] > 365 else f' · D-{r["imm_days"]}'
        cells.append(f'<div class="qk-pick"><div class="l1"><span class="n">{i}</span><b>{ui.esc(r["ticker"])}</b>{mv}</div>'
                     f'<div class="l2"><span style="color:{STC[r["status"]]};font-weight:700">{r["status"]}</span>'
                     + ('<span class="wk" title="약한 목표: baby shelf 탈출">약</span>' if r.get("weak") else "")
                     + (f' · +{pct:.0f}%{dd}' if pct is not None else f' · -{dd}')
                     + ((lambda b: f' <span title="{ui.esc("🎲 매매 전 시뮬레이션 " + __import__("presim_ui").badge_text(b))}">{__import__("presim").main_verdict(b) or b["verdict"]}</span>')(badges[r["ticker"]]) if badges and r["ticker"] in badges else "")
                     + '</div></div>')
    return ('<style>.qk-pick-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:6px 0 12px}'
            '.qk-pick{border:1px solid rgba(128,128,128,.28);border-radius:12px;padding:8px 10px;line-height:1.35}'
            '.qk-pick .l1{font-size:1.02rem;white-space:nowrap}.qk-pick .n{opacity:.55;font-size:.8rem;margin-right:6px}'
            '.qk-pick .l2{font-size:.8rem;opacity:.9;white-space:nowrap}'
            '.qk-pick .wk{display:inline-block;margin-left:4px;padding:0 4px;border-radius:5px;font-size:.68rem;font-weight:700;background:rgba(128,128,128,.25)}'
            '@media (max-width:768px){.qk-pick-grid{grid-template-columns:repeat(3,1fr);gap:6px}.qk-pick{padding:7px 8px}.qk-pick .l1{font-size:.95rem}.qk-pick .l2{font-size:.72rem}}</style>'
            '<div class="qk-pick-grid">' + "".join(cells) + "</div>")


def why_box(rows: list[dict], w: dict) -> None:
    """⏳ 왜 대기인가 — 자료가 없어서(수집 문제)인지, 일정이 멀어서(정상)인지 한눈에."""
    wait = [r for r in rows if r["status"] == "대기"]
    if not wait:
        return
    with st.expander(f"⏳ 왜 '대기'인가요? — {len(wait)}종목"):
        st.caption("'가능'이 되려면 45일 안에 임박한 일(📅 일정·현금 바닥·상장유지 기한)이 있거나 런웨이가 3개월 이하여야 해요. "
                   "'임박 자료 없음'·'런웨이 미확인'이 많으면 자료 수집 문제, '45일 넘게 남음'이 많으면 정상적으로 기다리는 중이에요.")
        st.markdown("".join(ui.chip(f"{k} {v}", "red" if k in ("임박 자료 없음", "런웨이 미확인") and v else "gray")
                            for k, v in w.items() if k != "대기"), unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"티커": r["ticker"], "목표": (r["target_name"] or "-") + (" (약)" if r.get("weak") else ""), "이유": r.get("why", ""), "런웨이(개월)": r["runway"], "가장 가까운 일": r["imm_kind"] or "-",
                                    "D-": r["imm_days"], "압박": r["pressure"]} for r in wait]),
                     hide_index=True, width="stretch", column_config={"런웨이(개월)": st.column_config.NumberColumn(format="%.1f")})


def render() -> None:
    import tabs
    import pressure_ui
    tabs.select("pick", [("pick", "🎯 PICK +30%", render_pick), ("changes", "📊 PICK 변동", render_changes), ("ai", "🤖 AI PICK", render_ai),
                         ("pressure", "🧭 전체 후보", pressure_ui.render)])  # 전체 후보 = 옛 '회사 압박 선별' 화면(메뉴 정리로 탭이 됨)


def render_ai() -> None:
    """🤖 AI PICK — Claude 판단(추정): 가장 빨리 +30% 갈 순서 · 시점 · 확신 · 근거 · 주의점 · 직전 대비 ▲▼."""
    import json as _json
    import access
    import aipick
    import config
    with closing(db.connect()) as conn:
        cur, prev = aipick.latest(conn)
    last = (db.get_meta("ai_pick_last") or {}).get("value")
    try:
        last = _json.loads(last) if last else {}
    except ValueError:
        last = {}
    st.markdown("**🤖 AI PICK** — Claude 가 우리 자료(PICK·종합 순위·회사 압박·희석·딜·런웨이·일정·공시·뉴스·내부자·공매도·주가 흐름)를 요약본으로 읽고 '가장 빨리 +30%' 순서를 매긴 **추정**이에요. "
                "규칙 기반 PICK 과 달리 '언제'를 봐요. 투자 권유가 아니며, 🏆 성과 공표에서 확신별 적중률로 검증돼요.")
    spent = aipick.spent_usd() * aipick.FX
    budget = float(getattr(config, "AI_MONTHLY_BUDGET_KRW", 10000))
    ui.cards([{"t": "판단일", "v": cur[0]["date"] if cur else "-", "s": f"{last.get('sent', '-')}종목 읽고 상위 {len(cur)}"},
              {"t": "확신 높음", "v": f"{sum(1 for r in cur if r['confidence'] == '높음')}", "accent": True},
              {"t": "이번 달 AI 비용", "v": f"{spent:,.0f}원", "s": f"예산 {budget:,.0f}원 · 1회 약 {last.get('usd', 0) * aipick.FX:,.0f}원"}])
    if not access.is_guest():
        if st.button("🔄 지금 다시 판단(오늘 판단을 새로 · 예산 안에서)", key="ai_rerun"):
            with st.spinner("Claude 가 판단하는 중… (30초~1분)"):
                try:
                    r = aipick.run(force=True, out=lambda *_: None)
                    (st.success if r.get("ok") else st.warning)(r.get("msg"))
                except Exception as e:  # noqa: BLE001
                    st.error(f"실패: {e}")
            st.rerun()
    if not cur:
        st.info("아직 판단이 없어요. 아침 갱신(화~토 07:30)에 자동으로 판단하거나, 위 버튼으로 지금 판단할 수 있어요.")
        return
    tcol = {"진행 중": "red", "이번 주": "orange", "다음 주": "blue", "나중": "gray"}
    ccol = {"높음": "red", "중간": "orange", "낮음": "gray"}
    html = []
    for r in cur:
        p = prev.get(r["ticker"])
        mv = "" if not prev else (ui.chip("🆕", "green") if p is None else (ui.chip(f"▲{p - r['rank']}", "red") if p > r["rank"] else
                                                                          (ui.chip(f"▼{r['rank'] - p}", "blue") if p < r["rank"] else "")))
        px = "-" if r["price"] is None else f"${r['price']:.4g}"
        html.append(f"<div style='padding:8px 0;border-bottom:1px solid rgba(128,128,128,.2)'><b>{r['rank']}. {r['ticker']}</b> {mv}"
                    f"{ui.chip('⚡ ' + r['timing'], tcol.get(r['timing'], 'gray'))}{ui.chip('확신 ' + r['confidence'], ccol.get(r['confidence'], 'gray'))}"
                    f" <span style='opacity:.7'>판단 {px}</span><br><span>{r['reason']}</span><br>"
                    f"<span style='opacity:.7'>⚠️ {r['risk']}</span></div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    if st.toggle("📋 텍스트(메신저에 붙여 넣기)", False, key="ai_txt"):   # 2026-10-31: PICK 처럼 복사용 글(김곰 워치리스트 '사유 텍스트 복사' 참고)
        st.code("\n".join(f"{r['rank']}. {r['ticker']} · ⚡{r['timing']} · 확신 {r['confidence']}\n   근거: {r['reason']}\n   주의: {r['risk']}" for r in cur)
                + f"\n(🤖 AI PICK {cur[0]['date']} · Claude 판단 추정 · 투자 권유 아님)", language=None)
    st.caption(f"모델 {last.get('model', '-')} · 입력 {last.get('in', 0):,} · 출력 {last.get('out', 0):,} 토큰. 공시 원문은 다시 열지 않고 우리 요약만 보냈어요 — 근거는 리포트·기업 분석에서 원문으로 확인하세요.")
    tk = st.selectbox("📄 종목 리포트", ["-"] + [r["ticker"] for r in cur], key="ai_rep")
    if tk and tk != "-":
        import report_dialog
        report_dialog.button(tk, "aipk")


def render_changes() -> None:
    """📊 PICK 변동 — 직전 기록 대비 새로 들어옴·빠짐·순위 ▲▼·상태 변화(대기→가능→유력)·목표 % 변화."""
    with closing(db.connect()) as conn:
        try:
            pick30.snapshot(conn, _scan())  # 오늘 기록이 없으면 지금 결과로 남김(하루 한 번)
        except Exception:  # noqa: BLE001
            pass
        ch = pick30.changes(conn)
    st.markdown("**📊 PICK 변동** — 매일 PICK 결과를 저장해 어제와 비교해요. 새로 올라온 종목·밀려난 종목·상태가 좋아진 종목을 한눈에.")
    if len(ch["dates"]) < 2:
        st.info("아직 비교할 이전 기록이 없어요. 내일 아침 갱신부터 변동이 보여요(오늘 기록은 저장했어요).")
    else:
        st.caption(f"{ch['dates'][0]} 기준 · 직전 기록 {ch['dates'][1]} 와 비교")
    rows = ch["rows"]
    if not rows:
        st.info("기록된 PICK 종목이 없어요.")
        return
    newc = sum(1 for r in rows if r["new"])
    upc = sum(1 for r in rows if (r["move"] or 0) > 0 or r["status_up"])
    ui.cards([{"t": "PICK 종목", "v": f"{len(rows)}"}, {"t": "🆕 새로 들어옴", "v": f"{newc}", "accent": bool(newc)},
              {"t": "▲ 순위·상태 상승", "v": f"{upc}"}, {"t": "❌ 빠짐", "v": f"{len(ch['gone'])}"}])

    def mv(r):
        if r["new"]:
            return "🆕"
        if r["move"] is None or r["move"] == 0:
            return "–"
        return f"▲{r['move']}" if r["move"] > 0 else f"▼{-r['move']}"
    tb = pd.DataFrame([{"순위": r["rank"], "변동": mv(r), "티커": r["ticker"], "상태": r["status"] + (" · 약" if r["weak"] else ""),
                        "상태 변화": r["status_change"] or "", "목표": r["target_name"] or "", "목표까지(%)": r["pct"],
                        "목표 % 변화(%p)": None if r["pct_prev"] is None or r["pct"] is None else round(r["pct"] - r["pct_prev"], 1),
                        "임박(일)": r["imm_days"]} for r in rows])
    import pick as picker
    t = picker.clickable(ui.tidy(tb), list(tb["티커"]), "pk_chg", hide_index=True, width="stretch")
    if ch["gone"]:   # 2026-10-31: 왜 빠졌는지(지금 걸린 탈락 조건) — 김곰 'PICK 변동 이유' 참고
        try:
            why = {f["ticker"]: f["fail"] for f in _scan().get("fail") or []}
        except Exception:  # noqa: BLE001
            why = {}
        st.caption("❌ 빠진 종목: " + " · ".join(f"{g['ticker']}(전 {g['rank']}위·{g['status']}" + (f" → 탈락: {why[g['ticker']]}" if why.get(g["ticker"]) else "") + ")"
                                              for g in ch["gone"][:20]))
    if t:
        with closing(db.connect()) as conn:
            hs = pick30.history(conn, t)
        if hs:
            st.markdown(f"**{t} 기록** — 최근 {len(hs)}일")
            st.dataframe(ui.tidy(pd.DataFrame(hs).rename(columns={"date": "날짜", "rank": "순위", "status": "상태", "pct": "목표까지(%)", "imm_days": "임박(일)"})),
                         hide_index=True, width="stretch")
        import report_dialog
        report_dialog.button(t, "pkchg")


def render_pick() -> None:
    import report_dialog
    ui.title("PICK +30%", "회사가 노리는 목표가가 +30%~+150% 안에 있고 하방 희석·매도 압력·다른 해결 방법이 없는 종목. 규칙 기반이며 매수 권유가 아닙니다.")
    with st.container(key="pk_ctrl"):  # 정렬 · 새로고침 · 텍스트를 한 줄에(휴대폰에서도)
        c1, c2, c3 = st.columns([3.2, 1, 1])
        opts = ["유력·임박 순", "임박 순", "압박 순"]
        if hasattr(st, "segmented_control"):
            short = {"유력·임박 순": "유력순", "임박 순": "임박순", "압박 순": "압박순"}  # 휴대폰 한 줄에 들어가게 짧게(정렬 값은 그대로)
            how = c1.segmented_control("정렬", opts, default=opts[0], key="pk_sort", label_visibility="collapsed",
                                       format_func=lambda o: short.get(o, o), help="유력순 = 유력·임박 순") or opts[0]
        else:
            how = c1.radio("정렬", opts, horizontal=True, key="pk_sort", label_visibility="collapsed")
        if c2.button("↻", key="pk_re", help="다시 계산하고 처음 연 순서와 비교(↑↓)", width="stretch"):
            _scan.clear()
        show_txt = c3.toggle("텍스트", False, key="pk_txt")
    s = _scan()
    rows = pick30.sort(s["pass"], how)
    first_key = f"pk_first_{how}"
    if first_key not in st.session_state:
        st.session_state[first_key] = {r["ticker"]: i for i, r in enumerate(rows, 1)}
    funnel = "".join(ui.chip(f"{c} −{n:,}", "gray" if c == "목표가 있음" else "red") for c, n in s["funnel"].items())
    st.markdown(f'<div class="qk-verdict" style="border-style:dashed;padding:10px 12px"><div style="margin-bottom:6px"><b>🔒 고정 조건</b> '
                f'<span class="qk-sub">등록 {s["registered"]:,} → <b>{len(rows)}종목 통과</b> · 유력 {sum(r["status"] == "유력" for r in rows)}</span></div>{funnel}'
                f'{ui.chip("주총·역분할·소송 = 상승 요인 아님", "gray")}</div>', unsafe_allow_html=True)
    if not rows:
        st.info("조건을 통과한 종목이 없어요. 회사 압박·펀드스캔 자료가 쌓이면 채워져요.")
    else:
        import presim_ui
        import access
        if access.is_guest():
            import guestpx
            st.caption(guestpx.NOTE)
        st.markdown(grid(rows, st.session_state[first_key], presim_ui.badges([r["ticker"] for r in rows])), unsafe_allow_html=True)
        if show_txt:
            st.code("\n".join(f"{i}. {r['ticker']} {r['status']}{'(약)' if r.get('weak') else ''} +{r['pct']:.0f}% → {r['target_name']} ${r['target']:.4f}" + ("" if r["imm_days"] is None else f" · D-{r['imm_days']} {r['imm_kind']}") + f" · {r.get('why', '')}"
                              for i, r in enumerate(rows, 1)), language=None)
        if any(r.get("weak") for r in rows):
            st.caption("**약** = 'baby shelf 탈출' 목표(약한 목표): 기한이 없고, 도달하면 회사가 오히려 대량 조달(희석)할 수 있어요. "
                       "'유력'이 될 수 없고, 같은 상태 안에서 상장 유지·워런트 목표 뒤에 놓여요.")
        why_box(rows, s.get("why") or {})
        pick = st.selectbox("자세히", ["(선택)"] + [r["ticker"] for r in rows], key="pk_open")
        if pick != "(선택)":
            report_dialog.open_report(pick)
    with st.expander(f"하방 희석·매도 압력·다른 해결 방법 등으로 뺀 종목 — {len(s['fail'])}종목"):
        if s["fail"]:
            st.dataframe(pd.DataFrame([{"티커": r["ticker"], "탈락 조건": r["fail"], "주식수(분기)": r.get("share_chg") or "-", "목표": r["target_name"] or "-", "목표가": r["target"], "필요 상승(%)": r["pct"], "상태": r["status"]}
                                       for r in s["fail"]]), hide_index=True, width="stretch", column_config={"필요 상승(%)": st.column_config.NumberColumn(format="%+.0f")})
    with st.expander(f"미등록 — 최근 매집 신호 {len(s['unregistered'])}종목"):
        st.caption("회사 압박·펀드스캔 분석이 아직 없는 매집 의심 종목이에요. 분석이 쌓이면 목표가로 판단해요.")
        st.write(" · ".join(s["unregistered"]) or "없음")
    with st.expander("PICK 기준"):
        st.markdown(pick30.__doc__.replace("$", "\\$"))
