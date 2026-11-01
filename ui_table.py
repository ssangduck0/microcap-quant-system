"""📋 안 눌리는 표(2026-11-01 · 사용자 '표가 불편 · 칸이 눌리고 긴 글이 잘림 → 안 눌리게').

Streamlit 기본 데이터 표는 칸을 누르면 선택 테두리가 생기고 긴 글은 잘려 가로로 밀어야 보인다 → 글이 긴 목록은 이 부품으로:
칸이 안 눌림(글자 복사는 됨) · 긴 글은 줄바꿈 · 색 칩 · PC 는 표 / 휴대폰(768px↓)은 같은 줄이 카드로 · 정렬은 표 위 선택 ·
처음 n줄 + '더 보기' · 리포트 열기는 표 아래 '📄 종목 리포트' 선택(HTML 안 클릭은 화면 코드로 못 받음).
정렬이 중요한 숫자 표(순위·스크리너·성과)는 기본 데이터 표를 그대로 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import streamlit as st

import ui_kit as ui

CSS = ("<style>.qk-st table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:.88rem}"
       ".qk-st th{text-align:left;font-weight:400;opacity:.7;padding:6px 6px;border-bottom:1px solid rgba(128,128,128,.45)}"
       ".qk-st td{padding:7px 6px;border-bottom:1px solid rgba(128,128,128,.22);vertical-align:top;line-height:1.45;word-break:break-word}"
       ".qk-st .mut{opacity:.6}.qk-st .tk{font-weight:700}.qk-st a{text-decoration:none}"
       ".qk-st-cards{display:none}.qk-st-card{border:1px solid rgba(128,128,128,.28);border-radius:12px;padding:8px 10px;margin:0 0 7px;font-size:.86rem;line-height:1.45}"
       ".qk-st-card .top{display:flex;justify-content:space-between;align-items:center;gap:6px}"
       "@media (max-width:768px){.qk-st table{display:none}.qk-st-cards{display:block}}</style>")


@dataclass
class Col:
    label: str
    cell: Callable[[dict], str]          # 줄 → 칸 HTML(자료 글자는 ui.esc 로 이미 감싸 둘 것)
    width: str | None = None             # 예: "12%"


def esc(v) -> str:
    return "" if v is None else ui.esc(str(v))


def table(rows: list[dict], cols: list[Col], key: str, sorts: dict[str, Callable[[dict], object]] | None = None, page: int = 15,
          card: Callable[[dict], tuple[str, str, str]] | None = None, on_open: Callable[[str], None] | None = None,
          ticker: str = "ticker", empty: str = "없습니다.") -> list[dict]:
    """rows 를 안 눌리는 표로. 반환 = 지금 정렬된 줄(테스트·다른 칸에서 씀).
    card(row) → (카드 제목 HTML, 오른쪽 칩 HTML, 아래 줄 HTML) — 없으면 첫 칸 / 둘째 칸 / 나머지 칸으로."""
    if not rows:
        st.caption(empty)
        return []
    order = list(rows)
    if sorts:
        names = list(sorts)
        how = st.selectbox("정렬", names, key=f"{key}_sort", label_visibility="collapsed") if len(names) > 1 else names[0]
        f = sorts.get(how) or sorts[names[0]]
        order = sorted(rows, key=f)
    nk = f"{key}_n"
    n = st.session_state.get(nk, page)
    shown = order[:n]
    head = "".join(f'<th style="width:{c.width}">{esc(c.label)}</th>' if c.width else f"<th>{esc(c.label)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c.cell(r)}</td>" for c in cols) + "</tr>" for r in shown)

    def _card(r: dict) -> str:
        t, chip, sub = card(r) if card else (cols[0].cell(r), cols[1].cell(r) if len(cols) > 1 else "", " · ".join(c.cell(r) for c in cols[2:] if c.cell(r)))
        return f'<div class="qk-st-card"><div class="top"><span class="tk">{t}</span><span>{chip}</span></div><div>{sub}</div></div>'
    html = (f'<div class="qk-st"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
            f'<div class="qk-st-cards">{"".join(_card(r) for r in shown)}</div></div>').replace("$", "&#36;")   # $ 두 개가 수식으로 바뀌지 않게
    st.markdown(CSS + html, unsafe_allow_html=True)
    c1, c2 = st.columns([1, 2])
    if len(order) > page:
        rest = len(order) - n
        if c1.button(f"더 보기 ({rest}줄 더)" if rest > 0 else "접기", key=f"{key}_more"):
            st.session_state[nk] = len(order) if rest > 0 else page
            st.rerun()
    c2.caption(f"{len(shown)} / {len(order)}줄")
    if on_open:
        tks = list(dict.fromkeys(r.get(ticker) for r in order if r.get(ticker)))
        pick = st.selectbox("📄 종목 리포트", ["(선택)"] + tks, key=f"{key}_open")
        if pick and pick != "(선택)":
            on_open(pick)
    return order
