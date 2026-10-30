"""🎯 회사 압박 선별 화면 — 종목 · 회사 압박 · 목표가 · 진입·주의사항(김곰 워치리스트 표 형태)."""
from contextlib import closing

import streamlit as st

import db
import pressure
import tosslink
import ui_kit as ui


def _line(label: str, text: str, strong: bool) -> str:
    return (f'<div style="margin:3px 0">{ui.chip(label, "red" if strong else "gray")}<span class="qk-sub" style="opacity:.9">{ui.esc(text)}</span></div>')


@st.cache_data(ttl=600, show_spinner="회사 압박 계산 중(10분마다 새로 계산)…")
def _scan_cached() -> tuple[list, int]:
    import watch_ui
    with closing(db.connect()) as conn:
        tickers = pressure.candidates(conn)
    px = watch_ui.prices(tuple(tickers[:300]))
    with closing(db.connect()) as conn:
        rows = pressure.scan(conn, px)
    return rows, len(tickers)


def render() -> None:
    ui.title("회사 압박 선별", "회사가 주가를 올리거나 자금을 구해야 할 이유가 급한 종목(런웨이·$1 상장유지·baby shelf·역분할·상습 희석). 규칙 기반이며 매수·매도 권유가 아닙니다.")
    with st.expander("점수 기준"):
        st.markdown("런웨이 3개월 미만 3 · 6개월 미만 2 · 12개월 미만 1 / $1 상장유지 미달 2(회복 기한 60일 이내 +1) / baby shelf 대상 1 / 최근 90일 역분할 1 / "
                    "상습 희석(최근 1년 조달·희석 서류 2회↑) 1 — 최대 10.  \n**목표가**: $1 상장유지까지, baby shelf 탈출가(7,500만 달러 ÷ 유통주식)까지 필요한 상승률.  \n"
                    "**구조**: ATM·ELOC 열림 + 런웨이 6개월 미만 → 회피, 압박 4점↑ → 보통, 그 외 대기.")
    c1, c2 = st.columns([3, 1])
    min_s = c1.slider("압박 점수 ≥", 0.0, 10.0, 3.0, 0.5, key="pr_min")
    hide_atm = c2.checkbox("ATM·ELOC 열림 숨기기", False, key="pr_atm")
    rows, n_tk = _scan_cached()
    rows = [r for r in rows if r["score"] >= min_s and not (hide_atm and r["atm_open"])]
    st.caption(f"선별 대상 {n_tk}종목(최근 스캐너 기록·워치리스트·저금통·Reg SHO·매집 의심·최근 병합) 중 {len(rows)}종목 · 압박 점수 순")
    if not rows:
        st.info("조건에 맞는 종목이 없습니다. 런웨이는 종목 리포트가 있어야 계산돼요(매일 아침 압박 후보 25종목씩 자동 생성).")
        return
    cmap = tosslink.codes()
    import rank_ui
    _rk = rank_ui.lookup()
    if st.toggle("종합 순위순으로 보기", False, key="pr_rank"):
        rows = sorted(rows, key=lambda x: _rk.get(x["ticker"], {}).get("rank", 10 ** 6))
    h = st.columns([1.6, 4.2, 2.2, 3])
    for col, name in zip(h, ["종목", "회사 압박", "목표가", "진입 · 주의사항"]):
        col.markdown(f'<span class="qk-sub"><b>{name}</b></span>', unsafe_allow_html=True)
    for i, r in enumerate(rows[:80], 1):
        t = r["ticker"]
        with st.container(border=True):
            a, b, c, d = st.columns([1.6, 4.2, 2.2, 3])
            a.markdown(f'<span class="qk-rank">{i}</span>&nbsp;<span class="qk-tk">{ui.esc(t)}</span>&nbsp;{ui.chip(f"압박 {r["score"]:g}", "red" if r["score"] >= 5 else "orange")}<br>'
                       + ("" if not r["price"] else f'<span class="qk-sub">${r["price"]:.4f}</span>') + ("" if r["has_report"] else "<br>" + ui.chip("리포트 없음", "gray")) + "<br>" + rank_ui.chip(t, _rk),
                       unsafe_allow_html=True)
            a.link_button("📲 토스", tosslink.url(t, cmap), width="stretch")
            import report_dialog
            report_dialog.button(t, "pr", a)
            b.markdown("".join(_line(lb, tx, s) for lb, tx, s in r["press"])
                       + ("" if not r["notes"] else '<div class="qk-sub" style="margin-top:6px"><b>압박 원인·참고</b></div>' + "".join(_line("역분할", n, False) for n in r["notes"])),
                       unsafe_allow_html=True)
            c.markdown("".join(f'<div style="margin:3px 0"><b style="font-size:1.05rem">{"" if p is None else f"{p:+.0f}%"}</b> <span class="qk-sub">{ui.esc(n)} ${v:.4f}</span></div>'
                               for n, v, p in r["targets"]) or '<span class="qk-sub">—</span>', unsafe_allow_html=True)
            d.markdown((ui.chip("ATM·ELOC 열림", "red") if r["atm_open"] else ui.chip("ATM·ELOC 잠김/없음", "green"))
                       + "".join(f'<div class="qk-sub" style="margin:2px 0">❗ {ui.esc(w)}</div>' for w in r["warn"])
                       + ui.chip(f"구조 {r['stance']}", {"회피": "red", "보통": "green", "대기": "gray"}[r["stance"]]), unsafe_allow_html=True)
