"""📛 Reg SHO 공매도 감시 — 등록 종목 순위(연속일수), 날짜별 조회, 연속 등록 히스토리, 공매도 현황."""
from contextlib import closing

import pandas as pd
import re

import streamlit as st

import db
import multisignal
import regsho
import tosslink
import ui_kit as ui


def _fx() -> float:
    try:
        return float((db.get_meta("usdkrw") or {}).get("value") or 1350.0)
    except (TypeError, ValueError):
        return 1350.0


def render() -> None:
    ui.title("Reg SHO 공매도 감시", "공매도 결제 실패가 쌓여 규제 명단(Reg SHO 기준 미달 목록, 나스닥)에 오른 종목을 연속일수 순으로 추적합니다.")
    with closing(db.connect()) as conn:
        ds = regsho.dates(conn)
    if not ds:
        st.info("아직 Reg SHO 목록이 없습니다. 스캐너가 하루 한 번 받거나, 명령 프롬프트에서 `python regsho.py` 를 실행하세요.")
        return
    c1, c2 = st.columns([3, 1])
    day = c2.selectbox("날짜", ds, index=0, key="rg_day", format_func=lambda d: f"{d} (최신)" if d == ds[0] else d)
    with closing(db.connect()) as conn:
        sm = regsho.summary(conn, day)
        st_ = regsho.streaks_at(conn, day)
        names = regsho.names_at(conn, day)
    cur, dl = sm["cur"], sm["delta"]
    ui.cards([{"t": "등록된 티커", "v": f"{cur['등록']}", "d": dl["등록"], "accent": True},
              {"t": "고위험 (13일↑)", "v": f"{cur['고위험']}", "d": dl["고위험"], "s": "13결제일 연속이면 강제 상환 대상"},
              {"t": "위험 (5~12일)", "v": f"{cur['위험']}", "d": dl["위험"]},
              {"t": "신규 (오늘 처음)", "v": f"{cur['신규']}", "d": dl["신규"]}])
    import piggy
    import watch
    mine = set(watch.scanner_priority()) | set(piggy.tickers())
    tab = c1.radio("보기", ["전체", "관심", "고위험", "위험", "신규"], horizontal=True, key="rg_tab", label_visibility="collapsed")
    rows = sorted(st_.items(), key=lambda x: (-x[1], x[0]))
    pick = {"전체": lambda s, n: True, "관심": lambda s, n: s in mine, "고위험": lambda s, n: n >= regsho.HIGH_DAYS,
            "위험": lambda s, n: regsho.RISK_DAYS <= n < regsho.HIGH_DAYS, "신규": lambda s, n: n == 1}[tab]
    rows = [(s, n) for s, n in rows if pick(s, n)]
    no_etf = st.toggle("ETF·펀드·토스 미지원 숨기기", True, key="rg_noetf", help="레버리지·인버스 ETF 는 늘 명단에 많이 오르지만 개별 종목 판단과는 달라요. 토스 거래 가능 목록이 있으면 그 기준으로 거릅니다")
    if no_etf:
        import tradable
        act = tradable.active()
        if act:   # P1: 토스 거래 가능 보통주 목록 기준(ETF·상폐·미지원 모두 제외)
            hid = [s for s, n in rows if s not in act]
        else:
            etf = re.compile(r"\bETF\b|\bETN\b|\bFUND\b|\bDAILY\b|\bBULL\b|\bBEAR\b|LEVERAGE|INVERSE|\b[123]X\b|SHARES TR|PORTFOLIO|INDEX|UNIT TR", re.I)  # 2026-10-27: TR·TRUST 는 REIT 오인 → ETF 특징어로
            hid = [s for s, n in rows if etf.search(names.get(s, "") or "")]
        rows = [(s, n) for s, n in rows if s not in set(hid)]
        if hid:
            st.caption(f"ETF·펀드·토스 미지원 {len(hid)}종목 숨김" + ("(토스 거래 가능 목록 기준)" if act else "(이름 기준)"))
    if not rows:
        st.caption("해당하는 종목이 없습니다.")
        return
    ms = multisignal.collect()
    import rank_ui
    _rk = rank_ui.lookup()
    if st.toggle("종합 순위순으로 보기", False, key="rg_rank"):
        rows = sorted(rows, key=lambda x: _rk.get(x[0], {}).get("rank", 10 ** 6))
    snap = db.read_df("SELECT ticker, price, dilution_status FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots)").set_index("ticker")
    cmap, fx = tosslink.codes(), _fx()
    st.caption(f"{day} 기준 · {len(rows)}종목 · 연속일수 내림차순 · 연속일수는 받아 둔 목록 {len(ds)}일치 기준(이만큼이면 실제로는 더 오래됐을 수 있어요)")
    open_t = st.session_state.get("rg_open")
    try:  # 📡 ChartExchange FTD(최근 결제일)
        import chartex
        with closing(db.connect()) as _c:
            chartex.ensure(_c)
            _ftd = chartex.ftd_map(_c)
    except Exception:  # noqa: BLE001
        _ftd = {}
    for rank, (s, n) in enumerate(rows, 1):
        lv = regsho.level(n)
        price = snap.loc[s, "price"] if s in snap.index else None
        dil = snap.loc[s, "dilution_status"] if s in snap.index else None
        sig = ms.get(s, [])
        with st.container(border=True):
            a, b, c, d, e = st.columns([5, 2, 1.4, 1.6, 1.2])
            chips = rank_ui.chip(s, _rk) + ui.chip(lv, {"고위험": "red", "위험": "orange", "신규": "blue"}.get(lv, "gray"))
            if sig:
                chips += ui.chip(f"멀티 시그널 {len(sig)}", "purple", tip=", ".join(sig))
            if dil in ("ATM", "ELOC", "CB"):
                chips += ui.chip(f"희석 {dil}", "red")
            if s in mine:
                chips += ui.chip("관심", "green")
            if _ftd.get(s) and (_ftd[s].get("fails") or 0) > 0:
                chips += ui.chip(f"FTD {(_ftd[s]['fails'] or 0) / 1e3:,.0f}K({_ftd[s]['settle_date'][5:]})", "orange", tip="결제 실패 주식 수(ChartExchange · SEC 월 2회 공개)")
            a.markdown(f'<span class="qk-rank">{rank}</span>&nbsp;&nbsp;<span class="qk-tk">{ui.esc(s)}</span>&nbsp;<span class="qk-sub">{ui.esc(names.get(s, ""))[:40]}</span><br>'
                       + (f'<span class="qk-sub">${price:.4f} · {price * fx:,.0f}원</span>&nbsp;&nbsp;' if price else "") + chips, unsafe_allow_html=True)
            b.markdown(f'<span class="qk-sub">최근 포착일</span><br><b>{ui.esc(day)}</b>', unsafe_allow_html=True)
            c.markdown(f'<span class="qk-pill">{n}일째{"+" if n >= len(ds) else ""}</span>', unsafe_allow_html=True)
            if d.button("공매도 현황" if open_t != s else "닫기", key=f"rg_btn_{s}", width="stretch", type="primary" if open_t != s else "secondary"):
                st.session_state["rg_open"] = None if open_t == s else s
                st.rerun()
            e.link_button("📲 토스", tosslink.url(s, cmap), width="stretch")
            import report_dialog
            report_dialog.button(s, "rg", e)
            if open_t == s:
                detail(s, day, sig)


def detail(s: str, day: str, sig: list[str]) -> None:
    import json
    with closing(db.connect()) as conn:
        hist = regsho.history(conn, s)
        r = conn.execute("SELECT data FROM ticker_intel WHERE ticker=? ORDER BY date DESC LIMIT 1", (s,)).fetchone() if conn.execute(
            "SELECT name FROM sqlite_master WHERE name='ticker_intel'").fetchone() else None
        sh = (json.loads(r["data"]).get("short") or {}) if r else {}
        try:
            bday = pd.DataFrame([dict(x) for x in conn.execute("SELECT date, open_avail, min_avail, max_fee FROM ibkr_borrow_day WHERE symbol=? ORDER BY date DESC", (s,))])
            fin = pd.DataFrame([dict(x) for x in conn.execute("SELECT date, short, total FROM finra_shvol WHERE symbol=? ORDER BY date DESC", (s,))])
        except Exception:  # noqa: BLE001
            bday, fin = pd.DataFrame(), pd.DataFrame()
    fee = sh.get("borrow_fee")
    av = sh.get("borrow_avail")
    ui.cards([{"t": "대차수수료(연)", "v": "-" if fee is None else f"{fee:,.1f}%", "s": "IBKR"},
              {"t": "가용주식", "v": "-" if av is None else ((">" if sh.get("borrow_avail_capped") else "") + f"{av:,.0f}"), "s": "IBKR 대여 가능" + (" · 최신 파일에 없음" if sh.get("borrow_stale") else "")},
              {"t": "DP 숏비율", "v": "-" if sh.get("sv_ratio") is None else f"{sh['sv_ratio']:.1f}%", "s": f"FINRA 장외 · {sh.get('sv_date') or '-'}"},
              {"t": "DP 숏거래량", "v": "-" if sh.get("sv_short") is None else f"{sh['sv_short']:,.0f}", "s": "FINRA 장외 공매도 거래량"}])
    st.caption("Float Short %·Short Interest·Days to Cover 는 격주 공시 데이터가 필요해 아직 넣지 않았습니다.")
    l, r_ = st.columns(2)
    with l:
        st.markdown("**가용주식 · 대차이자 추이 (IBKR, 일별)**")
        if bday.empty:
            st.caption("기록 없음(스캐너가 15분마다 쌓음)")
        else:
            st.dataframe(bday.rename(columns={"date": "날짜", "open_avail": "그날 처음 가용주식", "min_avail": "그날 최저 가용주식", "max_fee": "그날 최고 수수료(%)"}),
                         hide_index=True, width="stretch", column_config={"그날 처음 가용주식": st.column_config.NumberColumn(format="%,.0f"),
                                                                          "그날 최저 가용주식": st.column_config.NumberColumn(format="%,.0f"),
                                                                          "그날 최고 수수료(%)": st.column_config.NumberColumn(format="%.1f")})
    with r_:
        st.markdown("**다크풀(장외) 공매도 추이 (FINRA, 일별)**")
        if fin.empty:
            st.caption("기록 없음")
        else:
            fin["숏비율(%)"] = fin["short"] / fin["total"] * 100
            st.dataframe(fin.rename(columns={"date": "날짜", "short": "숏거래량", "total": "장외 거래량"}), hide_index=True, width="stretch",
                         column_config={"숏거래량": st.column_config.NumberColumn(format="%,.0f"), "장외 거래량": st.column_config.NumberColumn(format="%,.0f"),
                                        "숏비율(%)": st.column_config.NumberColumn(format="%.1f")})
    st.markdown("**연속 등록 히스토리**")
    st.markdown("".join(f'<span class="qk-hist{" on" if d == day else ""}">{d[5:]}{" (조회일)" if d == day else ""}</span>' for d in hist[:40]), unsafe_allow_html=True)
    if sig:
        st.markdown("**멀티 시그널** " + "".join(ui.chip(x, "purple") for x in sig), unsafe_allow_html=True)
