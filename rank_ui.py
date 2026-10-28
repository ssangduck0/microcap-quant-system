"""🏁 종합 순위 화면 + 다른 화면에 붙는 '종합 N위 · ⏱' 칩/열."""
import streamlit as st

import rank as rk
import tosslink
import db
import ui_kit as ui


@st.cache_data(ttl=120, show_spinner=False)
def table():
    """🏁 순위 표 — 🔥 화면 캐시(pagecache 'rank': quant-warm.timer 가 10분마다 갱신)에서 꺼내고, 없거나 25분 넘게 오래됐으면 직접 계산해 넣어 둔다.
    (2026-10-28: 서버에서 계산 20~27초 → 즉시. 🎯 장마감 체크리스트의 '종합 N위' 열(column)도 이 표를 쓴다)"""
    import pagecache
    df = pagecache.get("rank", pagecache.ENTRIES["rank"][2])
    if df is None:
        df = rk.compute()
        try:
            pagecache.put("rank", df)
        except Exception:  # noqa: BLE001
            pass
    return df


def lookup() -> dict:
    df = table()
    return {} if df.empty else {r["ticker"]: r for r in df.to_dict("records")}


def chip(t: str, m: dict | None = None) -> str:
    r = (m if m is not None else lookup()).get(str(t).upper())
    if not r:
        return ""
    color = "red" if r["urgency"] == 100 else "orange" if r["urgency"] == 60 else "gray"
    return ui.chip(f"🏁 종합 {r['rank']}위 · {r['score']:g}" + (f" · 상위 {r['top_pct']}%" if r.get("top_pct") else ""), "purple") + ui.chip(r["when"], color, tip=" · ".join(r["when_why"]))


def column(tickers, m: dict | None = None) -> list[str]:
    m = m if m is not None else lookup()
    return [("" if not m.get(str(t).upper()) else f"{m[str(t).upper()]['rank']}위 · {m[str(t).upper()]['when'].replace('⏱ ', '')}") for t in tickers]



@st.cache_data(ttl=900, show_spinner=False)
def s3_marks(tickers: tuple) -> dict[str, str]:
    """✅ 스승님 3대 조건 표시(① 💰 거래량+OBV 동반 상승 · ② 📉 과매도 · ③ 🛡 희석 없음) — 켜진 것만 칩으로. 15분 기억.
    판정 데이터는 pagecache.s3_data(🔥 캐시 'rank_s3' 우선, 없으면 setup3.marks 로 직접 — 2026-10-28: 야후 7.5초 → 즉시)."""
    import pagecache
    data = pagecache.s3_data(tickers)
    out = {}
    for t in tickers:
        r = data.get(t)
        if not r:
            continue
        m, s, d = r["m"], r["s"], r["d"]
        chips = []
        if m["strong"]:
            chips.append(ui.chip("①💰", "green", tip=m["label"]))
        if s["oversold"]:
            chips.append(ui.chip("②📉", "green", tip=s["label"]))
        if d["ok"]:
            chips.append(ui.chip("③🛡", "green", tip=d["label"]))
        elif d["ok"] is False:
            chips.append(ui.chip("③❌", "red", tip=d["label"]))
        n = sum(1 for x in (m["strong"], s["oversold"], d["ok"]) if x)
        out[t] = (ui.chip("✅ 3대 조건", "green") if n == 3 else "") + "".join(chips)
    return out


def render() -> None:
    import report_dialog
    ui.title("종합 순위", "신호 강도(매집·회사 압박·스퀴즈·멀티 시그널·공시·내부자) × 출발 임박도(최근 강한 매집·장마감 BEST·3일 안 일정·Reg SHO 강제 상환 직전)로 매긴 순위. 규칙 기반 추정입니다.")
    with st.expander("점수 기준"):
        st.markdown("강도 = 매집 25% + 회사 압박 20% + 스퀴즈 20% + 멀티 시그널 15% + 공시 호재 10% + 내부자 매수 10% − ATM·ELOC 열림 15 − 최근 30일 희석 서류 15 − 최근 3일 악재 10  \n"
                    "임박도: ⏱ 3일 이내 100 · ⏱ 1~2주 60 · ⏱ 수주 25 · ⏱ 미정 10 — **종합 = 강도 × 0.7 + 임박도 × 0.3**  \n"
                    "💡 100점은 6가지 신호가 **모두 만점**이면서 3일 안에 출발해야 나와서 사실상 안 나와요. 보통 좋은 종목도 2~3가지 신호만 강해서 "
                    "**1위가 50~60점대면 정상**이에요. 그래서 점수 옆에 **상위 몇 %**를 같이 보여 줘요. "
                    "(📒 발견 종목 추적·브리핑의 **승률 점수**는 다른 점수예요 — 급락 종목이 다음날 고가 목표에 닿을 확률이 과거 급락 사건 중 몇 번째 백분위인지라 90점대가 흔해요.)")
    c1, c2, c3 = st.columns([2, 1, 1])
    when = c1.radio("예상 시점", ["전체", "⏱ 3일 이내", "⏱ 1~2주", "⏱ 수주"], horizontal=True, key="rk_when", label_visibility="collapsed")
    min_s = c2.slider("종합 ≥", 0, 100, 20, key="rk_min")
    if c3.button("🔄 다시 계산", key="rk_re"):
        import pagecache
        pagecache.invalidate("rank")   # 캐시도 비워야 진짜 다시 계산
        table.clear()
    df = table()
    if df.empty:
        st.info("아직 순위를 매길 신호가 없습니다(매집 분석·스캐너가 쌓이면 채워집니다).")
        return
    v = df[df["score"] >= min_s]
    if when != "전체":
        v = v[v["when"] == when]
    try:  # 2026-10-28: 공시분석 범위 — 표시되는 상위 종목 중 45일 안 🧾 보고서가 있는 비율(없는 종목은 🏢 종목 📰 탭에서 요청)
        import forensic
        from datetime import date as _d, timedelta as _td
        _ld = forensic.latest_dates()
        _top = list(v.head(60)["ticker"])
        _cut = (_d.today() - _td(days=45)).isoformat()
        _cov = sum(1 for t in _top if _ld.get(t, "") >= _cut)
        _cov_card = {"t": "🧾 공시분석 있음(45일)", "v": f"{_cov}/{len(_top)}", "s": f"{_cov / len(_top) * 100:.0f}% — 없는 종목은 📰 탭에서 요청" if _top else ""}
    except Exception:  # noqa: BLE001
        _cov_card = {"t": "🧾 공시분석 있음(45일)", "v": "-"}
    ui.cards([{"t": "순위 대상", "v": f"{len(df)}", "accent": True}, {"t": "⏱ 3일 이내", "v": f"{(df['urgency'] == 100).sum()}"},
              {"t": "⏱ 1~2주", "v": f"{(df['urgency'] == 60).sum()}"}, {"t": "조건에 맞는 종목", "v": f"{len(v)}"}, _cov_card])
    cmap = tosslink.codes()
    _s3 = s3_marks(tuple(v.head(60)["ticker"]))
    for r in v.head(60).to_dict("records"):
        t = r["ticker"]
        parts = _s3.get(t, "") + "".join(ui.chip(f"{k} {p}", "blue") for k, p in r["parts"].items() if p)
        risk = "".join(ui.chip(x, "red") for x in r["risk"])
        if r.get("share_cls") in ("bad", "warn"):   # 🔬 ⑥ 직전 분기 주식수 변동(10/28): 표시만, 본 점수 불변(가상매매로 4주 비교 중)
            risk += ui.chip(f"주식수 {r['share_pct']:+.0f}%(분기)", "red" if r["share_cls"] == "bad" else "orange",
                            f"SEC 표지 {r.get('share_d') or ''} · 검증: +20% 초과는 60일 뒤 중앙값 −16%·급락 터치 52%, 10~20% 는 −10%·44%")
        color = "red" if r["urgency"] == 100 else "orange" if r["urgency"] == 60 else "gray"
        lines = ([f"⏱ {' · '.join(r['when_why'])}"] if r["when_why"] else []) + r["why"][:4]
        with st.container(border=True):
            a, b = st.columns([6, 1.4])
            a.markdown(f'<span class="qk-rank">{r["rank"]}</span>&nbsp;&nbsp;<span class="qk-tk">{ui.esc(t)}</span>&nbsp;{ui.chip(f"종합 {r["score"]:g} · 상위 {r.get("top_pct", "-")}%", "purple")}'
                       f'{ui.chip(r["when"], color)}<span class="qk-sub">강도 {r["strength"]:g}</span><br>{parts}{risk}'
                       + "<ul style='margin:.4rem 0 0 1rem;padding:0'>" + "".join(f"<li class='qk-sub' style='opacity:.85'>{ui.esc(x)}</li>" for x in lines) + "</ul>",
                       unsafe_allow_html=True)
            report_dialog.button(t, "rk", b)
            b.link_button("📲 토스", tosslink.url(t, cmap), width="stretch")
