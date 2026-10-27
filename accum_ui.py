"""🧲 매집 의심(일간·주간·월간) · ⚡ EFFECT 감지 화면 — 카드(펼침) / 티커만 보기."""
from contextlib import closing
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import accum
import db
import tosslink
import ui_kit as ui


def _fx() -> float:
    try:
        return float((db.get_meta("usdkrw") or {}).get("value") or 1350.0)
    except (TypeError, ValueError):
        return 1350.0


def _open_lookup(t: str) -> None:
    st.session_state["lookup_ticker"] = t
    pg = st.session_state.get("_pg_lookup")
    if pg is not None:
        st.switch_page(pg)


def render() -> None:
    import piggy
    import watch
    ui.title("매집 의심", "큰 거래량을 소화하면서 주가가 버티거나 오른 날(흡수일)이 반복되는데 뉴스·공시가 없는 종목. 규칙 기반 추정이며 매수·매도 권유가 아닙니다.")
    with st.expander("점수 기준", expanded=False):
        st.markdown("흡수일 = 거래량 20일 평균 **2배 이상** + 전일 대비 하락 안 함 · 강한 매집 의심일 = **5배 이상 + 5% 이상 상승**  \n"
                    "합계 = 흡수일 수(최대 5) + 강한 날 2 + 이유 미확인(기간 안 8-K·6-K 없음) 1 + 최근 45일 희석 서류 없음 1 + 30일 +30% 이상 1 + Reg SHO 0.5 + $1 근처 0.5")
    c1, c2, c3 = st.columns([3, 2, 2])
    per = c1.radio("기간", list(accum.PERIODS), index=1, horizontal=True, key="ac_per", label_visibility="collapsed")
    view = c2.radio("보기", ["펼침", "티커만"], horizontal=True, key="ac_view", label_visibility="collapsed")
    order = c2.radio("정렬", ["합계순", "종합 순위순"], horizontal=True, key="ac_sort", label_visibility="collapsed")
    min_s = c3.slider("합계 ≥", 0.0, 11.0, 4.0, 0.5, key="ac_min")
    import access
    if access.can_edit() and c1.button("🔄 지금 분석(수 분)", key="ac_run"):
        bar = st.progress(0.0, text="시작...")
        accum.run(progress=lambda p, m: bar.progress(min(p, 1.0), text=m), out=lambda *_: None)
        _latest.clear()
        st.rerun()
    df = _latest(per).copy()
    if df.empty:
        st.info("아직 분석 결과가 없습니다. 매일 아침 갱신 작업이 채우거나, 위 '지금 분석'을 누르세요.")
        return
    df = df[df["score"] >= min_s]
    import rank_ui
    _rk = rank_ui.lookup()
    if order == "종합 순위순":
        df = df.assign(_r=df["ticker"].map(lambda x: _rk.get(x, {}).get("rank", 10 ** 6))).sort_values("_r")
    st.caption(f"분석일 {df['date'].iloc[0] if not df.empty else '-'} · {per} · {len(df)}종목 · 합계 순")
    if df.empty:
        st.caption("조건에 맞는 종목이 없습니다. 합계 기준을 낮춰 보세요.")
        return
    mine, cmap, fx = set(watch.scanner_priority()) | set(piggy.tickers()), tosslink.codes(), _fx()
    _tmap, _hot = _themes_ctx()
    _dp = _dp_flags()   # B단계 2026-10-27: 🕶 다크풀 동반 표시
    if view == "티커만":
        st.markdown(" ".join(f'<a href="{tosslink.url(t, cmap)}" target="_blank" style="text-decoration:none">{ui.chip(f"{t} {s:g}", "red" if s >= 7 else "orange" if s >= 5 else "gray")}</a>'
                             for t, s in zip(df["ticker"], df["score"])), unsafe_allow_html=True)
        st.caption("칩을 누르면 토스증권으로 이동합니다. 자세히 보려면 '펼침'.")
        return
    for r in df.head(60).to_dict("records"):
        d, t = r["data"], r["ticker"]
        dots = "●" * min(5, round(d["score"] / 2)) + "○" * (5 - min(5, round(d["score"] / 2)))
        chips = rank_ui.chip(t, _rk) + ui.chip(d["level"], "red") + (ui.chip("이유 미확인", "blue") if not d["news"] else ui.chip(f"공시 {len(d['news'])}건", "gray"))
        chips += ui.chip("희석 서류 없음(45일)", "green") if not d["dilution"] else ui.chip(f"희석 서류 {len(d['dilution'])}건", "red")
        if d.get("regsho"):
            chips += ui.chip(f"Reg SHO {d['regsho']}일째", "red")
        if _dp.get(t):
            chips += ui.chip(f"🕶 {_dp[t]}", "purple")
        if d["parts"].get("$1 근처"):
            chips += ui.chip("$1 근처", "orange")
        import shares as _sh
        _to = _sh.turnover(t)
        if _to and _to["pct"] >= 30:  # 📐 회전율 = 거래량 ÷ 주식 수
            chips += ui.chip(f"회전율 {_to['pct']:.0f}%", "red" if _to["pct"] >= 100 else "orange", tip=_to["tag"])
        if t in mine:
            chips += ui.chip("관심", "green")
        for _x in _tmap.get(t, [])[:3]:  # 🏷 테마(오늘 3종목 이상 움직인 테마는 🔥)
            chips += ui.chip(("🔥 " if _x in _hot else "") + _x, "purple" if _x in _hot else "blue")
        lines = [f"{d['top_day']} {d['level']} ×{d['top_vr']:.1f} {d['top_chg']:+.1f}% · " + ("뉴스·공시 없음" if not d["news"] else "공시: " + ", ".join(f"{x[0][5:]} {x[1]}" for x in d["news"][:3])),
                 f"흡수일 {d['n_absorb']}일({', '.join(d['absorb_days'][-6:])})" + ("" if d.get("cum") is None else f" · 기간 누적 {d['cum']:+.1f}%")
                 + ("" if d.get("r30") is None else f" · 30일 {d['r30']:+.1f}%"),
                 "공급: 최근 45일 희석 서류 없음" if not d["dilution"] else "공급: " + ", ".join(f"{x[0][5:]} {x[1]}" for x in d["dilution"][:3])]
        with st.container(border=True):
            a, b = st.columns([6, 1.4])
            a.markdown(f'<span class="qk-tk">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">${d["price"]:.4f} · {d["price"] * fx:,.0f}원</span>'
                       f'&nbsp;&nbsp;{ui.chip(f"합계 {d["score"]:g}", "green")}<span style="letter-spacing:2px;opacity:.8">{dots}</span><br>{chips}'
                       + "<ul style='margin:.4rem 0 0 1rem;padding:0'>" + "".join(f"<li class='qk-sub' style='opacity:.85'>{ui.esc(x)}</li>" for x in lines) + "</ul>",
                       unsafe_allow_html=True)
            import report_dialog
            bb = b.container(key=f"acb_{per}_{t}")  # 휴대폰에서 버튼 3개를 한 줄에(ui_kit CSS)
            report_dialog.button(t, f"ac_{per}", bb)
            bb.link_button("📲 토스", tosslink.url(t, cmap), width="stretch")
            if bb.button("🔎 종목", key=f"ac_lk_{per}_{t}", width="stretch"):
                _open_lookup(t)


@st.cache_data(ttl=600, show_spinner=False)
@st.cache_data(ttl=600, show_spinner=False)
def _dp_flags() -> dict:
    try:
        import darkpool
        return darkpool.flag_map()
    except Exception:  # noqa: BLE001
        return {}


def _themes_ctx() -> tuple[dict, set]:
    """종목별 테마 · 오늘 움직이는 테마 — 10분 동안 기억(예전엔 매집 화면을 열 때마다 새로 계산해 10~18초)."""
    import themes as _th
    _tb = _th.table()
    if _tb.empty:
        return {}, set()
    return dict(zip(_tb["ticker"], _tb["themes"])), set(_th.hot(_tb, _th.moves()).query("움직임 >= 3")["테마"])


@st.cache_data(ttl=300, show_spinner=False)
def _latest(per: str):
    return accum.latest(per)


def render_effect() -> None:
    """⚡ EFFECT 감지 — 등록 효력(EFFECT) = 곧 발행·재판매 가능(희석 임박). 앞선 등록서류와 그 뒤 424B(가격 확정)를 함께."""
    import watch_ui
    ui.title("EFFECT 감지", "SEC 가 등록서류(S-1·F-1·S-3·F-3)에 효력을 준 종목 — 곧 공모·워런트 행사·재판매 물량이 나올 수 있습니다(희석 임박).")
    days = st.select_slider("기간", [7, 14, 30, 60], value=30, key="ef_days", format_func=lambda d: f"최근 {d}일")
    since = (date.today() - timedelta(days=days)).isoformat()
    with closing(db.connect()) as conn:
        f = accum.filings_map(conn, [], (date.today() - timedelta(days=days + 120)).isoformat())
    rows, seen = [], set()
    for t, fl in f.items():
        for d, fm in fl:
            if fm.upper() == "EFFECT" and d >= since and (t, d) not in seen:  # 같은 종목·같은 날 EFFECT 여러 건 → 한 줄
                seen.add((t, d))
                before = sorted({(x, y) for x, y in fl if y.upper().startswith(("S-1", "F-1", "S-3", "F-3")) and x <= d}, reverse=True)
                after = sorted({(x, y) for x, y in fl if y.upper().startswith("424B") and x >= d})
                rows.append({"ticker": t, "date": d, "before": before[:2], "after": after[:2]})
    if not rows:
        st.info("기간 안에 EFFECT 공시가 없습니다(과거 공시 백필·실시간 공시 피드 기준).")
        return
    rows.sort(key=lambda x: x["date"], reverse=True)
    px = watch_ui.prices(tuple(sorted({r["ticker"] for r in rows})))
    cmap, fx = tosslink.codes(), _fx()
    st.caption(f"{len(rows)}건 · 최신순")
    for r in rows:
        t, df = r["ticker"], px.get(r["ticker"])
        ch = None
        if df is not None and not df.empty:
            dd = df.copy()
            dd.index = pd.to_datetime(dd.index).tz_localize(None).normalize()
            on = dd[dd.index <= pd.Timestamp(r["date"])]
            if not on.empty:
                ch = (float(dd["Close"].iloc[-1]) / float(on["Close"].iloc[-1]) - 1) * 100
        chips = ui.chip("희석 임박", "red") + (ui.chip("424B 가격 확정 " + r["after"][0][0][5:], "orange") if r["after"] else ui.chip("424B 아직", "gray"))
        with st.container(border=True):
            a, b = st.columns([6, 1.4])
            a.markdown(f'<span class="qk-tk">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">EFFECT {r["date"]}</span>&nbsp;&nbsp;{chips}<br>'
                       f'<span class="qk-sub">앞선 등록서류: {", ".join(f"{x[0]} {x[1]}" for x in r["before"]) or "기록 없음"}'
                       + ("" if ch is None else f" · EFFECT 이후 {ch:+.1f}%") + "</span>", unsafe_allow_html=True)
            b.link_button("📲 토스", tosslink.url(t, cmap), width="stretch")
