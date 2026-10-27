"""🌎 시장 지표 줄(맨 위) — VIX · 공포·탐욕 · 수입물가지수 + 📎 데이터 출처 링크."""
from datetime import date

import pandas as pd
import streamlit as st

import macro
import ui_kit as ui


def _age(it: dict) -> str:
    return "" if not it.get("_err") else " · ⚠️ 최근 받기 실패(예전 값)"


def render_strip() -> None:
    d, man = macro.get(), macro.manual()
    v, f, i, nx = d.get("vix") or {}, d.get("fng") or {}, d.get("imp") or {}, d.get("imp_next") or {}
    cards = []
    if v.get("value") is not None:
        cards.append({"t": "VIX 변동성", "v": f"{v['value']:.2f}", "d": None, "s": f"{v.get('level', '')} · 전일 대비 {v.get('chg', 0):+.2f} · {v.get('date', '')}{_age(v)}"})
    else:
        cards.append({"t": "VIX 변동성", "v": "확인 불가", "s": "스캐너가 받으면 채워져요"})
    if f.get("score") is not None:
        cards.append({"t": "공포·탐욕 지수(CNN)", "v": f"{f['score']:.0f} · {f.get('rating', '')}",
                      "s": ("" if f.get("prev") is None else f"전일 {f['prev']:.0f}") + ("" if f.get("week") is None else f" · 1주 전 {f['week']:.0f}") + _age(f)})
    else:
        cards.append({"t": "공포·탐욕 지수(CNN)", "v": "확인 불가", "s": "CNN 사이트에서 직접 확인(아래 링크)"})
    nd = man.get("next_date") or nx.get("date")
    left = "" if not nd else f" · 다음 발표 {nd}" + (f"(D-{(date.fromisoformat(nd) - date.today()).days})" if nd >= date.today().isoformat() else "")
    fc = man.get("forecast")
    if i.get("mom") is not None:
        diff = "" if fc is None else f" · 예상 {fc:+.1f}% 대비 {'상회' if i['mom'] > fc else '하회' if i['mom'] < fc else '부합'}"
        cards.append({"t": f"수입물가지수 {i.get('month', '')}" + (" (잠정)" if i.get("prelim") else ""), "v": f"전월비 {i['mom']:+.1f}%",
                      "s": ("" if i.get("yoy") is None else f"전년비 {i['yoy']:+.1f}%") + diff + left + _age(i)})
    else:
        cards.append({"t": "수입물가지수", "v": "확인 불가" if fc is None else f"예상 {fc:+.1f}%", "s": "BLS 발표치는 스캐너가 받으면 채워져요" + left})
    st.markdown('<div class="qk-sub" style="margin:-6px 0 6px">🌎 시장 지표 · 참고용(정확한 시장 분석은 원문에서 직접 확인)</div>', unsafe_allow_html=True)
    spec = [(v, "VIX", "#3678F6", "line", (20, 30), "최근 6개월"), (f, "공포·탐욕", "#F76B15", "line", (25, 75), "최근 1년"), (i, "전월비(%)", "#8E4EC6", "bar", (0,), "최근 2년")]
    for col, card, sp in zip(st.columns(3), cards, spec):  # 카드 바로 아래에 그 지표의 작은 차트(휴대폰에서는 한 묶음씩 세로로)
        with col:
            s_ = card.get("s", "")
            st.markdown(f'<div class="qk-card" style="margin-bottom:4px"><div class="t">{ui.esc(card["t"])}</div><div class="v">{ui.esc(card["v"])}</div>'
                        f'<div class="s">{ui.esc(s_)}</div></div>', unsafe_allow_html=True)
            spark(*sp)
    st.markdown('<div class="qk-sub" style="margin:-10px 0 14px">📎 데이터 출처 '
                + " ".join(f'<a href="{u}" target="_blank" style="text-decoration:none">{ui.chip(n, "blue")}</a>' for n, u in macro.LINKS) + "</div>", unsafe_allow_html=True)



LIGHT_COLOR = {"green": "green", "yellow": "orange", "red": "red"}


def render_light() -> None:
    """🚦 소형주 장세 신호등(ANO 거시 관점, regime.py) — 홈 시장 지표 줄 아래. 2026-10-27"""
    import regime
    r = regime.get()
    if not r or not r.get("light"):
        st.caption("🚦 소형주 장세: 스캐너가 VIX 기간 구조·하이일드 스프레드·금리·SPY 200일선을 받으면 신호등이 켜져요.")
        return
    err = " · ⚠️ 최근 받기 실패(예전 값)" if r.get("_err") else ""
    st.markdown(ui.chip(f"🚦 소형주 장세 {r['label']}", LIGHT_COLOR.get(r["light"], "gray"))
                + f'<span class="qk-sub"> 위험 {r.get("points", 0)}점 · {r.get("date") or ""}{err} · ANO: "돈이 안 돌면 소형주는 종목이 안 나온다"</span>', unsafe_allow_html=True)
    if r.get("reasons"):
        st.caption("⚠️ " + " / ".join(r["reasons"]))
    if r.get("ok"):
        st.caption("✅ " + " / ".join(r["ok"]))
    m = r.get("metrics") or {}
    with st.expander("🚦 숫자 보기 — VIX 기간 구조 · 하이일드 스프레드 · 2년/10년물 · SPY 200일선 · 나스닥 20일선"):
        rows = [("VIX", m.get("vix"), "18.5 경계 · 20 스퀴즈 조건 · 30 폭락권"), ("VIX 하루 변화(%)", m.get("vix_chg_pct"), "+15% 이상 = 급변"),
                ("9일 VIX ÷ 3개월 VIX", m.get("term_ratio"), "1.0 이상 = 백워데이션(당장 공포)"), ("하이일드 스프레드(%)", m.get("hy"), "5일 +0.3pp · 20일 +0.5pp = 유동성 경색"),
                ("  5일 변화(pp)", m.get("hy_chg5"), ""), ("  20일 변화(pp)", m.get("hy_chg20"), ""),
                ("HYG/IEF 비율 5일(%) — 스프레드 대체", m.get("hy_proxy_chg5"), "−1% = 스프레드 확대"), ("HYG/IEF 비율 20일(%)", m.get("hy_proxy_chg20"), "−2% = 확대"),
                ("2년물(%)", m.get("dgs2"), "5일 −0.15pp + SPY↓ = 주식 팔아 채권"),
                ("  5일 변화(pp)", m.get("dgs2_chg5"), ""), ("10년물(%)", m.get("dgs10"), ""), ("SPY 200일선 대비(%)", m.get("spy_vs200_pct"), "아래면 강세장 아님"),
                ("SPY 5일(%)", m.get("spy_5d_pct"), ""), ("나스닥 20일선 기울기(%)", m.get("ixic_slope"), "20일선 아래 + 기울기↓ = 단기 추세 꺾임")]
        st.dataframe(pd.DataFrame([(a, "-" if b is None else f"{float(b):.2f}", c) for a, b, c in rows], columns=["지표", "값", "기준(ANO)"]), hide_index=True, width="stretch")   # 값은 글자(숫자·"-" 섞이면 Arrow 오류)
        st.caption("재료: 야후 ^VIX ^VIX9D ^VIX3M SPY ^IXIC HYG IEF · FRED BAMLH0A0HYM2(하이일드 스프레드) DGS2 DGS10(한국에서 FRED 가 막히면 금리는 DBnomics, 스프레드는 HYG/IEF 비율로 대체) — 30분마다 갱신. 옵션(Put/Call wall) 자료는 없어 뺐어요.")


def render_line() -> None:
    """다른 화면용 한 줄 요약(자세히는 🏠 홈)."""
    d, parts = macro.get(), []
    try:
        import regime
        rg = regime.get()
        if rg.get("label"):
            parts.append(f"🚦 {rg['label'].split('(')[0].strip()}")
    except Exception:  # noqa: BLE001
        pass
    v, f, i = d.get("vix") or {}, d.get("fng") or {}, d.get("imp") or {}
    if v.get("value") is not None:
        parts.append(f"VIX {v['value']:.1f}({v.get('chg', 0):+.1f})")
    if f.get("score") is not None:
        parts.append(f"공포·탐욕 {f['score']:.0f} {f.get('rating', '')}")
    if i.get("mom") is not None:
        parts.append(f"수입물가 {i.get('month', '')} 전월비 {i['mom']:+.1f}%")
    if parts:
        st.markdown(f'<div class="qk-sub" style="margin:-8px 0 10px">🌎 {ui.esc(" · ".join(parts))} — 자세히는 🏠 홈</div>', unsafe_allow_html=True)



def spark(it: dict, name: str, color: str, kind: str, refs: tuple, period: str) -> None:
    """카드 아래 작은 차트(축 최소화·높이 90). 기준선은 옅은 점선."""
    import altair as alt
    import pandas as pd
    h = it.get("hist") or []
    if len(h) < 2:
        st.caption("차트 자료 준비 중")
        return
    df = pd.DataFrame(h, columns=["날짜", name])
    x = alt.X("날짜:T" if kind == "line" else "날짜:N", title=None, axis=None)
    y = alt.Y(f"{name}:Q", title=None, axis=alt.Axis(labelFontSize=9, tickCount=3, grid=False, domain=False))
    base = alt.Chart(df)
    ch = (base.mark_line(color=color, strokeWidth=1.8) if kind == "line" else base.mark_bar(color=color, opacity=.8)).encode(x=x, y=y, tooltip=["날짜", alt.Tooltip(f"{name}:Q", format=".2f")])
    for r in refs:
        ch = ch + alt.Chart(pd.DataFrame({"y": [r]})).mark_rule(strokeDash=[3, 3], opacity=.35).encode(y="y:Q")
    st.altair_chart(ch.properties(height=90).configure_view(strokeWidth=0), width="stretch")
    st.caption(f"{name} · {period}" + ("" if not refs or refs == (0,) else " · 점선 " + "/".join(map(str, refs))))


def charts(v: dict, f: dict, i: dict) -> None:
    """VIX(6개월) · 공포·탐욕(CNN 이력) · 수입물가지수 전월비(2년) 작은 차트."""
    import altair as alt
    import pandas as pd
    cols = st.columns(3)
    spec = [(v, "VIX", "#3678F6", "line", (20, 30)), (f, "공포·탐욕", "#F76B15", "line", (25, 75)), (i, "전월비(%)", "#8E4EC6", "bar", (0, None))]
    for col, (it, name, color, kind, refs) in zip(cols, spec):
        h = it.get("hist") or []
        with col:
            if len(h) < 2:
                st.caption("차트 자료가 아직 없어요(다음 갱신 때 채워져요).")
                continue
            df = pd.DataFrame(h, columns=["날짜", name])
            x = alt.X("날짜:T" if kind == "line" else "날짜:N", title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True))
            base = alt.Chart(df)
            ch = (base.mark_line(color=color, strokeWidth=2) if kind == "line" else base.mark_bar(color=color, opacity=.75)).encode(
                x=x, y=alt.Y(f"{name}:Q", title=None), tooltip=["날짜", alt.Tooltip(f"{name}:Q", format=".2f")])
            rules = [alt.Chart(pd.DataFrame({"y": [r]})).mark_rule(strokeDash=[4, 4], opacity=.5).encode(y="y:Q") for r in refs if r is not None]
            for r in rules:
                ch = ch + r
            st.altair_chart(ch.properties(height=130), width="stretch")
