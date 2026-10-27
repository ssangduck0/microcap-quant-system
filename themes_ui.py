"""🏷 테마 화면 — 오늘 움직인 테마, 테마별 종목, 테마 직접 고치기."""
import pandas as pd
import streamlit as st

import themes as th
import tosslink
import ui_kit as ui


def render() -> None:
    import multisignal
    ui.title("테마", "업종(SEC 업종 코드)과 키워드(회사 이름·최근 공시 문장)로 묶은 테마. 오늘 등락 ≥ +10% 또는 거래량 3배 이상인 종목이 많을수록 '움직이는 테마'입니다.")
    tb, mv = th.table(), th.moves()
    if tb.empty:
        st.info("아직 테마 정보가 없습니다. 명령 프롬프트에서 한 번 `python themes.py build` (수 분) — 이후 매일 아침 새 종목만 자동으로 추가됩니다.")
        return
    c1, c2 = st.columns(2)
    chg_min = c1.slider("움직임: 등락 ≥ +%", 3, 50, 10, key="th_chg")
    vr_min = c2.slider("또는 거래량 배수 ≥", 1.5, 10.0, 3.0, 0.5, key="th_vr")
    h = th.hot(tb, mv, chg_min, vr_min)
    day = mv["date"].iloc[0] if not mv.empty else "-"
    if h.empty:
        st.caption("오늘 움직임 데이터가 없습니다(매일 아침 매집 분석 때 함께 저장).")
    else:
        top = h[h["움직임"] > 0].head(8)
        st.markdown(f'<div class="qk-sub">{day} 기준 · 오늘 관심 테마</div>', unsafe_allow_html=True)
        ui.cards([{"t": r["테마"], "v": f"{int(r['움직임'])}종목", "s": f"전체 {int(r['종목'])} · 평균 {r['평균 등락(%)']:+.1f}% · {r['대표']}", "accent": i == 0}
                  for i, r in enumerate(top.to_dict("records"))] or [{"t": "움직인 테마", "v": "없음"}])
    names = th.all_themes(tb)
    order = list(h["테마"]) + [n for n in names if n not in set(h["테마"])] if not h.empty else names
    pick = st.selectbox("테마 보기", order, key="th_pick")
    mem = tb[tb["themes"].map(lambda x: pick in x)]
    m = mem.merge(mv, on="ticker", how="left") if not mv.empty else mem.assign(price=None, chg=None, vr=None, r5=None)
    m = m.sort_values("chg", ascending=False, na_position="last")
    ms, cmap = multisignal.collect(), tosslink.codes()
    st.caption(f"{pick} · {len(m)}종목 · 오늘 등락순")
    for r in m.head(60).to_dict("records"):
        t = r["ticker"]
        chg, vr = r.get("chg"), r.get("vr")
        import rank_ui
        chips = rank_ui.chip(t) + "".join(ui.chip(x, "blue" if x == pick else "gray") for x in r["themes"][:4])
        if pd.notna(chg) and chg >= chg_min:
            chips += ui.chip(f"오늘 {chg:+.1f}%", "red")
        if pd.notna(vr) and vr >= vr_min:
            chips += ui.chip(f"거래량 ×{vr:.1f}", "orange")
        if ms.get(t):
            chips += ui.chip(f"멀티 시그널 {len(ms[t])}", "purple", tip=", ".join(ms[t]))
        if r.get("manual"):
            chips += ui.chip("직접 지정", "green")
        with st.container(border=True):
            a, b = st.columns([6, 1.4])
            a.markdown(f'<span class="qk-tk">{ui.esc(t)}</span>&nbsp;<span class="qk-sub">{ui.esc(r.get("name") or "")} · {ui.esc(r.get("sic_desc") or "")}</span><br>'
                       + ("" if pd.isna(r.get("price")) else f'<span class="qk-sub">${r["price"]:.4f} · 오늘 {chg:+.1f}% · 5일 {r["r5"]:+.1f}%</span>&nbsp;') + chips,
                       unsafe_allow_html=True)
            b.link_button("📲 토스", tosslink.url(t, cmap), width="stretch")
            import report_dialog
            report_dialog.button(t, "th", b)
    import access
    if access.is_guest():
        return
    with st.expander("✏️ 종목 테마 직접 고치기"):
        e1, e2 = st.columns([1, 3])
        tk = e1.text_input("티커", key="th_edit_t").strip().upper()
        cur = tb.set_index("ticker")["themes"].get(tk, []) if tk else []
        sel = e2.multiselect("테마", names, default=[x for x in cur if x in names], key=f"th_edit_s_{tk}")
        new = st.text_input("새 테마 이름(쉼표로 여러 개, 선택)", key="th_edit_new")
        if st.button("저장", key="th_edit_save", disabled=not tk):
            th.set_manual(tk, list(dict.fromkeys(sel + [x.strip() for x in new.split(",") if x.strip()])))
            st.success(f"{tk} 테마 저장")
            st.rerun()
