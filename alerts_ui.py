"""🔔 공시 알림 화면 — SEC 실시간 공시를 카드 피드로(판정·태그·멀티 시그널·Reg SHO, 원문·토스·덕구 스캔 버튼)."""
from contextlib import closing
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db
import evscore
import secfeed
import tosslink
import ui_kit as ui

SENT_COLOR = {"호재": "green", "약한 호재": "green", "중립": "gray", "주의": "orange", "악재": "red", "혼재": "purple"}
TAG_COLOR = {"희석 위험": "red", "희석 임박": "red", "ATM/ELOC": "red", "계속기업 의문": "red", "상장유지": "red", "파산": "red", "재무 정정": "red",
             "주식 병합": "orange", "정관 변경": "orange", "채무": "orange", "자사주매입": "green", "FDA 승인": "green", "수주": "green", "실적 개선": "green",
             "파트너십·계약": "blue", "계약": "blue", "인수합병": "blue", "경영진 변경": "gray", "대량보유": "purple"}


_EV_OK = False  # 점수표가 최근 1년 검증을 통과했는지(_ev_ctx 가 채움)


def _ev_ctx():
    """🧮 공시 점수표 + 최근 종가(가격대 판정용). 없으면 (None, {})."""
    global _EV_OK
    try:
        x = evscore.load()
        if not x or not x.get("table"):
            return None, {}
        _EV_OK = bool((x.get("validation") or {}).get("ok"))
        px = {r[0]: r[1] for r in db.read_df("SELECT ticker, price FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots)").itertuples(index=False)}
        return x["table"], px
    except Exception:  # noqa: BLE001
        return None, {}


def _ev_info(evt, evpx, r):
    if not evt:
        return None
    try:
        with closing(db.connect()) as c:
            return evscore.for_feed_row(evt, r, evpx.get(r.get("ticker")), c)
    except Exception:  # noqa: BLE001
        return None


def render() -> None:
    import forensic
    import multisignal
    import piggy
    import regsho
    import watch
    ui.title("공시 알림", "SEC 실시간 공시 중 우리가 보는 나스닥 종목만 모아, 8-K 항목·본문 키워드로 호재·악재와 태그를 붙였습니다(규칙 기반 — 원문 확인 필요).")
    c1, c2 = st.columns([3, 1])
    q = c1.text_input("검색", key="al_q", placeholder="티커·키워드 검색 (#병합: 병합 종목만, #희석, #호재, #관심)", label_visibility="collapsed").strip()
    days = c2.selectbox("기간", [1, 3, 7, 30], index=1, key="al_days", format_func=lambda d: "오늘" if d == 1 else f"최근 {d}일")
    f = secfeed.feed(days=days)
    if f.empty:
        st.info("아직 받은 공시가 없습니다. 스캐너가 매 사이클 SEC 실시간 공시 피드를 받아 쌓습니다.")
        return
    mine = set(watch.scanner_priority()) | set(piggy.tickers())
    flt = st.radio("필터", ["전체", "호재", "악재·주의", "희석 위험", "할인 전환", "주식 병합", "관심 종목"], horizontal=True, key="al_f", label_visibility="collapsed")
    def has(r, *tags):
        return any(t in r["tags"] for t in tags)
    if flt == "호재":
        f = f[f["sentiment"].isin(["호재", "약한 호재"])]
    elif flt == "악재·주의":
        f = f[f["sentiment"].isin(["악재", "주의"])]
    elif flt == "희석 위험":
        f = f[f.apply(lambda r: has(r, "희석 위험", "희석 임박", "ATM/ELOC"), axis=1)]
    elif flt == "할인 전환":   # ⚠️ 대폭 할인 전환사채·선급주식매입(OMH 패턴: 병합 → 50% 할인 전환 → 폭락)
        f = f[f.apply(lambda r: has(r, "할인 전환"), axis=1)]
    elif flt == "주식 병합":
        f = f[f.apply(lambda r: has(r, "주식 병합", "정관 변경"), axis=1)]
    elif flt == "관심 종목":
        f = f[f["ticker"].isin(mine)]
    if q:
        for tok in q.split():
            if tok.startswith("#"):
                k = tok[1:]
                f = f[f["ticker"].isin(mine)] if k == "관심" else f[f.apply(lambda r: k in r["sentiment"] or any(k in t for t in r["tags"]), axis=1)]
            else:
                f = f[f["ticker"].str.contains(tok.upper(), na=False) | f["company"].str.contains(tok, case=False, na=False)]
    st.markdown(f'<div class="qk-sub">공시 알림 <b style="color:#E5484D">{len(f):,}</b>건</div>', unsafe_allow_html=True)
    if f.empty:
        st.caption("조건에 맞는 공시가 없습니다.")
        return
    ms = multisignal.collect()
    with closing(db.connect()) as conn:
        sho = regsho.streaks(conn)
        try:
            rs90 = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM rs_events WHERE date >= ?", ((date.today() - timedelta(days=90)).isoformat(),))}
        except Exception:  # noqa: BLE001
            rs90 = set()
    cmap = tosslink.codes()
    evt, evpx = _ev_ctx()
    limit = st.session_state.get("al_limit", 50)
    try:  # 📝 공시 한국어 요약
        import secdigest
        with closing(db.connect()) as _cdg:
            _dg = secdigest.digests(_cdg, [x['accession'] for x in (f.head(limit).to_dict("records"))])
    except Exception:  # noqa: BLE001
        _dg = {}
    for r in f.head(limit).to_dict("records"):
        t = r["ticker"]
        chips = ui.chip(r["form"], "red" if r["form"].upper().startswith(("424B", "S-1", "F-1", "EFFECT")) else "gray") + ui.chip(r["sentiment"], SENT_COLOR.get(r["sentiment"], "gray"))
        chips += "".join(ui.chip(x, TAG_COLOR.get(x, "gray")) for x in r["tags"])
        evi = _ev_info(evt, evpx, r)
        if evi:  # 🧮 과거 비슷한 공시(종류·가격대·시점)의 실제 성과 — 검증 통과 전엔 회색 '참고'(색으로 확신을 주지 않게)
            chips += ui.chip(f"📊 과거 {evi['pp']:+.1f}%p" + ("" if _EV_OK else " · 참고"), evscore.chip_color(evi["pp"]) if _EV_OK else "gray",
                             tip=f"{evi['key']} · {evi['n']:,}건 · D+5 시장보다 이긴 확률 {evi['p']}% (전체 {evi['p0']}%)"
                             + ("" if _EV_OK else " · 최근 1년 검증 미통과 — 순위에는 안 씀"))
        if r.get("repeat"):
            chips += ui.chip("⚠ 반복 공시", "orange")
        if t in rs90:
            chips += ui.chip("90일 이내 병합", "blue")
        if sho.get(t):
            chips += ui.chip(f"Reg SHO {sho[t]}일째", "red")
        if ms.get(t):
            chips += ui.chip(f"멀티 시그널 {len(ms[t])}", "purple", tip=", ".join(ms[t]))
        if t in mine:
            chips += ui.chip("관심", "green")
        when = pd.to_datetime(r["updated"], errors="coerce", utc=True)
        when_s = "" if pd.isna(when) else when.tz_convert("Asia/Seoul").strftime("%m/%d %H:%M")
        names = secfeed.item_names(r["items"])
        dg = _dg.get(r["accession"]) or {}
        if dg.get("grade"):
            chips = ui.chip(f"{dg['grade']}등급 · {dg.get('category') or ''}", {"A": "red", "B": "orange"}.get(dg["grade"], "gray"),
                            tip="📝 공시 요약(Claude Haiku)의 주가 영향 등급 — A 큼 · B 보통 · C 작음") + chips
        with st.container(border=True):
            a, b = st.columns([6, 2])
            a.markdown(chips + f'<br><span class="qk-tk">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">{ui.esc(r["company"])}</span>'
                       + (f'<br><span class="qk-sub">{ui.esc(" · ".join(names))}</span>' if names else "")
                       + (f'<br><span>📝 {ui.esc(dg["summary_ko"])}</span>' if dg.get("summary_ko") else ""), unsafe_allow_html=True)
            b.markdown(f'<div style="text-align:right" class="qk-sub">{when_s} KST</div>', unsafe_allow_html=True)
            if b.button("📄 리포트", key=f"al_rep_{r['accession']}", type="primary", width="stretch"):
                show_report(r)
            x1, x2, x3 = b.columns(3)
            x1.link_button("원문", r["url"] or "https://www.sec.gov", width="stretch")
            x2.link_button("토스", tosslink.url(t, cmap), width="stretch")
            import access
            if access.can_edit() and x3.button("덕구", key=f"al_q_{r['accession']}", width="stretch", help="🧾 공시분석 자동 스캔(Cowork) 대기열에 추가"):
                forensic.queue_add(t)
                st.toast(f"{t} 덕구 스캔 대기열에 추가")
    if len(f) > limit and st.button(f"더 보기 ({len(f) - limit}건 남음)", key="al_more"):
        st.session_state["al_limit"] = limit + 50
        st.rerun()


TAG_DESC = {"주식 병합": "주식 병합(역분할) 관련 — 유통 주식이 줄어 변동성이 커짐", "정관 변경": "정관 변경(8-K 5.03) — 병합·수권주식 증가 등이 흔함",
            "희석 위험": "공모·사모·워런트 등 새 주식 발행 가능성", "희석 임박": "등록 효력 발생 — 곧 발행·재판매 가능", "ATM/ELOC": "시장가로 계속 주식을 파는 계약",
            "계속기업 의문": "감사인이 계속기업 존속에 의문을 표시", "상장유지": "나스닥 상장유지 요건 미달·이전 관련", "자사주매입": "회사가 자기 주식을 사들이는 계획",
            "FDA 승인": "FDA 승인·허가 관련 문구", "파트너십·계약": "파트너십·라이선스·유통 계약", "수주": "수주·구매 주문", "실적 개선": "매출·이익 개선 문구",
            "인수합병": "인수·합병·사업 결합", "경영진 변경": "임원·이사 변경", "사명 변경": "회사 이름 변경", "대량보유": "5% 이상 대량 보유 신고",
            "채무": "새 채무 발생", "재무 정정": "이전 재무제표 신뢰 불가(정정)", "파산": "파산·회생 절차", "계약": "중요 계약 체결", "계약 해지": "중요 계약 해지"}
GOOD = {"자사주매입", "FDA 승인", "파트너십·계약", "수주", "실적 개선"}
BAD = {"희석 위험", "희석 임박", "ATM/ELOC", "계속기업 의문", "상장유지", "재무 정정", "파산", "채무", "주식 병합", "정관 변경", "계약 해지"}
DESC = {"호재": "호재 우세 — 조건과 날짜를 원문에서 확인", "약한 호재": "호재 우세, 일부 리스크 존재 가능", "중립": "뚜렷한 방향 없음 — 추가 모니터링",
        "주의": "부정 요인 가능성 — 원문 확인", "악재": "희석·상장유지 등 부정 요인 우세", "혼재": "호재/악재 혼재 — 추가 모니터링 필요"}
COLOR = {"호재": "#30A46C", "약한 호재": "#30A46C", "중립": "#8B8D98", "주의": "#F76B15", "악재": "#E5484D", "혼재": "#8E4EC6"}


def report_parts(r: dict) -> dict:
    """리포트 화면에 들어갈 값(규칙 기반)."""
    import multisignal
    import regsho
    from datetime import date as _d
    t = r["ticker"]
    rep = db.get_report(t) or {}
    rw = rep.get("runway") or {}
    fin = rep.get("financing") or {}
    evs = fin.get("events") if isinstance(fin, dict) else (fin if isinstance(fin, list) else [])
    n_fin = sum(1 for e in evs or [] if str(e.get("date", "")) >= (_d.today() - timedelta(days=365)).isoformat())
    snap = db.read_df("SELECT float_shares, dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
    fs = None if snap.empty or pd.isna(snap.iloc[0]["float_shares"]) else float(snap.iloc[0]["float_shares"])
    dil = None if snap.empty else snap.iloc[0]["dilution_status"]
    try:
        import watch
        oh = watch.overhang_rows(t)
        act = set(oh[oh["status"] == "활성"]["kind"]) if not oh.empty else set()
    except Exception:  # noqa: BLE001
        act = set()
    with closing(db.connect()) as conn:
        sho = regsho.streaks(conn).get(t)
    ms = multisignal.collect().get(t, [])
    tags = list(r["tags"])
    key = [f"{r['form']} " + " · ".join(secfeed.item_names(r["items"]))] if r["items"] else [f"{r['form']} 공시"]
    key += [TAG_DESC[x] for x in tags if x in TAG_DESC]
    up = [TAG_DESC[x] for x in tags if x in GOOD]
    if sho and sho >= 5:
        up.append(f"Reg SHO {sho}일째 — 공매도 상환 압박")
    if len(ms) >= 2:
        up.append(f"멀티 시그널 {len(ms)}개: {', '.join(ms)}")
    if fs and fs < 10e6:
        up.append(f"유통 주식 {fs / 1e6:.1f}백만 주 — 수급에 민감")
    if rw.get("runway_months") is not None and rw["runway_months"] >= 12:
        up.append(f"런웨이 {rw['runway_months']:.0f}개월 — 당장 조달 압박 낮음")
    risk = [TAG_DESC[x] for x in tags if x in BAD]
    if dil in ("ATM", "ELOC", "CB"):
        risk.append(f"희석 정황 {dil}(SEC 판정)")
    if rw.get("runway_months") is not None and rw["runway_months"] < 6:
        risk.append(f"런웨이 {rw['runway_months']:.1f}개월 — 추가 자금조달(희석) 가능성 높음")
    if r.get("repeat"):
        risk.append("짧은 기간에 공시 반복 — 이벤트 연속")
    strength = max(0.0, min(100.0, 50 + (r.get("score") or 0) * 10 + min(len(ms), 3) * 8 + (8 if sho and sho >= 5 else 0) + (6 if fs and fs < 10e6 else 0)))
    usd = lambda v: "-" if v is None else f"${v / 1e6:,.2f}M"  # noqa: E731
    return {"key": key, "up": up, "risk": risk, "strength": strength, "fs": fs,
            "flags": [("ATM", dil == "ATM" or "ATM" in act), ("ELOC", dil == "ELOC" or "ELOC" in act), ("TOXIC(전환사채)", dil == "CB" or "전환사채" in act)],
            "fin": [("현금", usd(rw.get("cash")) + (f" ({rw.get('cash_asof')})" if rw.get("cash_asof") else "")), ("월 소진", usd(rw.get("monthly_burn"))),
                    ("런웨이", "-" if rw.get("runway_months") is None else f"{rw['runway_months']:.1f}개월"), ("최근 1년 자금조달", f"{n_fin}회" if rep else "-")],
            "has_rep": bool(rep)}


@st.dialog("소형주 공시 리포트", width="large")
def show_report(r: dict) -> None:
    render_report(r)


def render_report(r: dict) -> None:
    import forensic
    p = report_parts(r)
    when = pd.to_datetime(r["updated"], errors="coerce", utc=True)
    h1, h2, h3, h4 = st.columns([2.2, 1, 1.6, 1.4])
    h1.markdown(f'<span class="qk-tk" style="font-size:1.35rem">{ui.esc(r["ticker"])}</span><br><span class="qk-sub">{ui.esc(r["company"])}</span>', unsafe_allow_html=True)
    h1.link_button("📲 토스증권 이동", tosslink.url(r["ticker"]))
    h2.markdown(f'<span class="qk-sub">알림 종류</span><br><b>{ui.esc(r["form"])}</b>', unsafe_allow_html=True)
    h3.markdown(f'<span class="qk-sub">공시 키워드</span><br><b>{ui.esc(", ".join(r["tags"][:3]) or "-")}</b>', unsafe_allow_html=True)
    h4.markdown(f'<span class="qk-sub">발표</span><br><b>{"" if pd.isna(when) else when.tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M")}</b>', unsafe_allow_html=True)
    left, right = st.columns([1.7, 1])
    with left:
        st.markdown("**판단** <span class='qk-sub'>(규칙 기반 — AI 요약 아님)</span>", unsafe_allow_html=True)
        st.markdown(ui.verdict(r["sentiment"], DESC.get(r["sentiment"], ""), p["strength"], COLOR.get(r["sentiment"], "#8B8D98")), unsafe_allow_html=True)
        if r["tags"]:
            st.markdown("**감지 키워드** " + "".join(ui.chip(x, TAG_COLOR.get(x, "gray")) for x in r["tags"]), unsafe_allow_html=True)
        evt, evpx = _ev_ctx()
        evi = _ev_info(evt, evpx, r)
        if evi:
            _c = ui.chip(f"{evi['pp']:+.1f}%p" + ("" if _EV_OK else " · 참고"), evscore.chip_color(evi["pp"]) if _EV_OK else "gray")
            st.markdown(f"**📊 과거 비슷한 공시** {_c} "
                        f"<span class='qk-sub'>{ui.esc(evi['key'])} {evi['n']:,}건 — D+5에 시장(IWM)보다 이긴 확률 {evi['p']}% (전체 공시 {evi['p0']}%). "
                        "과거 통계일 뿐, 이 공시의 결과를 보장하지 않아요."
                        + ("" if _EV_OK else " 지금은 최근 1년 검증을 통과하지 못해 순위에는 쓰지 않는 참고 값이에요.") + "</span>", unsafe_allow_html=True)
        st.markdown("**공시 요약**")
        fx = forensic.reports(r["ticker"])
        if not fx.empty:
            st.caption(f"🧾 덕구 공시분석 저장본 ({str(fx.iloc[0]['created_at'])[:10]}) — 앞부분")
            st.markdown(fx.iloc[0]["content"][:900] + ("…" if len(fx.iloc[0]["content"]) > 900 else ""))
        elif r.get("lead"):
            st.caption("원문 핵심 문장(영문 발췌) — 한글 요약이 필요하면 아래 '덕구 스캔 요청'")
            st.markdown(f"> {r['lead']}")
        else:
            st.caption("본문 발췌가 아직 없습니다(스캐너가 몇 분 안에 본문을 읽습니다). 원문을 확인하세요.")
        b1, b2, b3 = st.columns(3)
        b1.markdown(ui.box("📋 핵심 포인트", p["key"], "#3678F6"), unsafe_allow_html=True)
        b2.markdown(ui.box("➕ 상승 트리거", p["up"], "#30A46C"), unsafe_allow_html=True)
        b3.markdown(ui.box("⚠ 구조적 리스크", p["risk"], "#F76B15"), unsafe_allow_html=True)
    with right:
        st.markdown("**희석 리스크 플래그**")
        st.markdown(ui.flags(p["flags"]), unsafe_allow_html=True)
        st.markdown(ui.kv([("유통 주식 수", "-" if not p["fs"] else f"약 {p['fs'] / 1e4:,.0f}만주")]), unsafe_allow_html=True)
        st.markdown("**재무지표 요약**")
        st.markdown(ui.kv(p["fin"]), unsafe_allow_html=True)
        if not p["has_rep"]:
            st.caption("재무지표는 🗂 종목 리포트에서 가져옵니다(리포트가 없으면 비어 있어요).")
    import ai_ui
    ai_ui.render(r["ticker"], key=f"rep_{r['accession']}")
    c1, c2 = st.columns(2)
    c1.link_button("원문 보기", r["url"] or "https://www.sec.gov", width="stretch")
    import access
    if access.can_edit() and c2.button("🧾 덕구 스캔 요청(한글 요약)", key=f"rep_q_{r['accession']}", width="stretch"):
        forensic.queue_add(r["ticker"])
        st.success("대기열에 넣었습니다. Cowork 예약 작업이 실행되면 한글 보고서가 저장돼요.")
