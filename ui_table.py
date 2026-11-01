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


# ---------------------------------------------------------------- 자동 변환(2026-11-02 · 사용자 '더 좋은 방법' → 표마다 칸 코드 대신 한 줄 교체)
# st.dataframe(df, column_config=…, column_order=…, hide_index=…) 를 utb.frame(df, key, 같은 인자) 로 바꾸면 같은 칸·같은 형식으로 안 눌리는 표가 된다.
# 내용 보존: 숨긴 칸(column_config 값 None)·칸 순서·이름·숫자 형식은 그대로 따르고, 모든 줄은 '더 보기'로, 기본 표 도구(검색·CSV)는 '찾기'·'⬇ CSV' 로 대신.
# 관리 모드 '표 모양'(TABLE_STYLE)이 old 면 예전 기본 표 그대로(배포 없이 비교·되돌리기).
import re as _re

import pandas as _pd

_GOOD = ("✅", "통과", "충족", "예", "O", "pass", "PASS")
_BAD = ("❌", "미달", "실패", "아니오", "X", "fail", "FAIL")
_WARN = ("⚠️", "⚠", "주의")
_UNK = ("❓", "➖", "모름", "확인 불가", "미확인", "unknown")
_URL = _re.compile(r"https?://\S+")
_EMO = ("✅", "❌", "⚠️", "⚠", "❓", "➖")


def _fmt_num(v, fmt: str | None) -> str:
    """Streamlit 숫자 형식(printf 꼴: %.1f · %+.0f · %,.0f · %.0f%% · $%.2f · %d)을 그대로."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return esc(v)
    if fmt:
        def rep(m):
            flags, prec, typ = m.group(1) or "", m.group(2) or "", m.group(3)
            spec = ("+" if "+" in flags else "") + ("," if "," in flags else "") + prec + ("d" if typ == "d" else "e" if typ == "e" else "f")
            return format(int(round(x)) if typ == "d" else x, spec)
        try:
            return esc(_re.sub(r"%([+,]*)(\.\d+)?([dfe])", rep, fmt.replace("%%", "\x00")).replace("\x00", "%"))
        except (ValueError, TypeError):
            pass
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x):,}"
    return f"{x:,.4f}".rstrip("0").rstrip(".") if abs(x) < 1 else f"{x:,.2f}"


def _chip(s: str) -> str | None:
    t = s.strip()
    if len(t) > 12:
        return None
    for keys, color in ((_GOOD, "green"), (_BAD, "red"), (_WARN, "orange"), (_UNK, "gray")):   # 글자는 딱 맞을 때만('예상'이 '예'로 잡히지 않게) · 이모지는 앞에 오면
        if t in keys or any(t.startswith(k) for k in keys if k in _EMO):
            return ui.chip(t, color)
    return None


def _link(v, display: str | None) -> str:
    s = "" if v is None else str(v)
    m = _URL.search(s)
    if not m:
        return esc(s) if s else '<span class="mut">-</span>'
    lab = _re.sub(r"(\d{4})-(\d{2})-(\d{2})", lambda x: f"{x.group(2)}/{x.group(3)}", s[:m.start()].strip())[:24]
    text = display if (display and not any(ch in display for ch in "^$()[]*+?\\")) else "열기"
    return (f'<span class="mut">{esc(lab)}</span> ' if lab else "") + f'<a href="{esc(m.group(0))}" target="_blank">{esc(text)}</a>'


def cell_html(v, cfg: dict | None) -> str:
    """값 + 칸 설정 → 칸 HTML. 빈 값은 '-'(기본 표의 빈칸과 같은 뜻)."""
    try:
        if v is None or (not isinstance(v, (list, dict, tuple)) and _pd.isna(v)):
            return '<span class="mut">-</span>'
    except (TypeError, ValueError):
        pass
    tc = (cfg or {}).get("type_config") or {}
    typ = tc.get("type")
    if typ == "link":
        return _link(v, tc.get("display_text"))
    if typ in ("number", "progress"):
        return _fmt_num(v, tc.get("format"))
    if typ == "checkbox" or isinstance(v, bool):
        return ui.chip("예", "green") if bool(v) else '<span class="mut">아니오</span>'
    if isinstance(v, (int, float)):
        return _fmt_num(v, None)
    if isinstance(v, (_pd.Timestamp,)):
        return esc(v.strftime("%Y-%m-%d %H:%M") if (v.hour or v.minute) else v.strftime("%Y-%m-%d"))
    s = str(v)
    if _URL.search(s):
        return _link(s, None)
    return _chip(s) or esc(s)


def _style() -> str:
    try:
        import config
        return str(getattr(config, "TABLE_STYLE", "new") or "new").lower()
    except Exception:  # noqa: BLE001
        return "new"


def _orig():
    """예전 기본 표(install 이 바꾸기 전 st.dataframe)."""
    return getattr(st, "_utb_orig_dataframe", None) or st.dataframe


def _in_apptest() -> bool:
    """Streamlit 화면 테스트(AppTest) 안이면 True — 테스트 과정만 streamlit.testing 을 불러옴(서버는 안 부름)."""
    import sys
    return "streamlit.testing.v1" in sys.modules


def new_run() -> None:
    """dashboard.py 맨 위에서 매 실행마다: 이번 실행에 쓴 표 key 기록을 비움(같은 표가 한 화면에 여러 번 그려지면 _2·_3 을 붙여 겹치지 않게)."""
    st.session_state["_utb_used"] = {}


def _run_token():
    """이번 실행을 가리키는 값 — Streamlit 이 실행마다 새로 만드는 cursors 묶음(없으면 None). new_run 을 안 부르는 화면(테스트 앱)에서도 실행마다 기록을 비우게."""
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx
        ctx = get_script_run_ctx()
        return id(ctx.cursors) if ctx is not None else None
    except Exception:  # noqa: BLE001
        return None


def _unique(key: str) -> str:
    tok = _run_token()
    if st.session_state.get("_utb_tok") != tok:
        st.session_state["_utb_tok"] = tok
        st.session_state["_utb_used"] = {}
    used = st.session_state.setdefault("_utb_used", {})
    n = used.get(key, 0)
    used[key] = n + 1
    return key if n == 0 else f"{key}_{n + 1}"


def _spark(v) -> str:
    """작은 선 그래프(LineChartColumn 대신)."""
    try:
        xs = [float(x) for x in list(v) if x is not None and not _pd.isna(x)]
    except (TypeError, ValueError):
        return '<span class="mut">-</span>'
    if len(xs) < 2:
        return '<span class="mut">-</span>'
    lo, hi = min(xs), max(xs)
    rng = (hi - lo) or 1.0
    pts = " ".join(f"{i * 100 / (len(xs) - 1):.1f},{28 - (x - lo) / rng * 26:.1f}" for i, x in enumerate(xs))
    color = "#30A46C" if xs[-1] >= xs[0] else "#E5484D"
    return f'<svg viewBox="0 0 100 30" preserveAspectRatio="none" style="width:100%;max-width:140px;height:24px"><polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/></svg>'


def frame(df, key: str, column_config: dict | None = None, column_order=None, hide_index: bool | None = None, page: int = 15,
          on_open: Callable[[str], None] | None = None, ticker: str | None = None, csv: bool = True, **kw):
    """st.dataframe 자리에 그대로: 같은 인자로 안 눌리는 표. kw(width·height 등 기본 표 인자)는 예전 표로 돌아갈 때만 씀."""
    if _style() == "old":   # 관리 모드 '표 모양: old' — 예전 기본 표
        return _orig()(df, column_config=column_config, column_order=column_order, hide_index=hide_index, **kw)
    if df is None:
        return None
    if hasattr(df, "data") and not isinstance(df, _pd.DataFrame):   # pandas Styler → 원래 표
        df = df.data
    df = df if isinstance(df, _pd.DataFrame) else _pd.DataFrame(df)
    base = key
    key = _unique(key)
    cc = column_config or {}
    names = [c for c in (list(column_order) if column_order else list(df.columns)) if c in df.columns and not (c in cc and cc[c] is None)]
    show_idx = hide_index is False or (hide_index is None and not isinstance(df.index, _pd.RangeIndex))
    try:   # 테스트(오프라인 모드)에서만: 화면에 넘긴 칸 그대로의 표를 남겨 기존 테스트가 값으로 확인하게(운영에선 안 남김)
        import config
        if getattr(config, "OFFLINE", False):
            st.session_state[f"_utb_{base}"] = df[names].copy()
    except Exception:  # noqa: BLE001
        pass
    if _in_apptest():   # 화면 테스트는 예전 표 값으로 확인하는 것이 많아 같은 표를 하나 더(운영 화면엔 안 그림)
        _orig()(df, column_config=column_config, column_order=column_order, hide_index=hide_index)
    recs = df[names].to_dict("records") if names else [{} for _ in range(len(df))]
    rows = [{"_i": i, "_raw": raw, "_idx": idx, ticker or "ticker": (str(raw.get(ticker)) if ticker else None)} for i, (idx, raw) in enumerate(zip(df.index, recs))]
    if len(rows) > page:   # 찾기(기본 표의 검색 대신)
        q = st.text_input("찾기", key=f"{key}_q", placeholder="표 안에서 찾기", label_visibility="collapsed")
        if q:
            ql = q.lower()
            rows = [r for r in rows if any(ql in str(v).lower() for v in r["_raw"].values()) or ql in str(r["_idx"]).lower()]
    label = lambda c: ((cc.get(c) or {}).get("label") or str(c))  # noqa: E731

    def _len(c):   # 칸 너비 = 글 양에 비례(긴 글 칸이 넓게) · 주소 칸은 '열기'만 보이니 좁게
        vals = [r["_raw"][c] for r in rows[:60]]
        t = ((cc.get(c) or {}).get("type_config") or {}).get("type")
        if t == "link" or any(isinstance(v, str) and _URL.search(v) for v in vals[:5]):
            return 9.0
        if t in ("line_chart", "bar_chart", "area_chart"):
            return 14.0
        avg = sum(min(60, len(str(v))) for v in vals) / max(1, len(vals))
        return max(len(label(c)) * 1.2, avg, 3.0)
    lens = {c: _len(c) for c in names}
    tot = sum(lens.values()) + (8 if show_idx else 0) or 1.0

    def _cell(r, c):   # 보이는 줄만 그때 그림(큰 표도 가볍게)
        cfg = cc.get(c)
        if ((cfg or {}).get("type_config") or {}).get("type") in ("line_chart", "bar_chart", "area_chart"):
            return _spark(r["_raw"][c])
        return cell_html(r["_raw"][c], cfg)
    cols = ([Col(df.index.name or "", lambda r: esc(r["_idx"]), f"{max(6, 8 / tot * 100):.0f}%")] if show_idx else []) + \
        [Col(label(c), (lambda r, c=c: _cell(r, c)), f"{max(6, lens[c] / tot * 100):.0f}%") for c in names]
    sortable = [c for c in names if _pd.api.types.is_numeric_dtype(df[c]) or _pd.api.types.is_datetime64_any_dtype(df[c])][:6]
    sorts = None
    if len(df) > 5 and sortable:
        def _k(c, desc):
            def f(r):
                v = r["_raw"][c]
                bad = v is None or (isinstance(v, float) and _pd.isna(v))
                return (bad, (-v if desc and not bad and not hasattr(v, "year") else v) if not bad else 0)
            return f
        sorts = {"원래 순서": lambda r: r["_i"]}
        for c in sortable:
            if _pd.api.types.is_numeric_dtype(df[c]):
                sorts[f"{label(c)} 큰 순"] = _k(c, True)
                sorts[f"{label(c)} 작은 순"] = _k(c, False)
    first = cols[0] if cols else None

    def card(r):
        rest = " · ".join(f'<span class="mut">{esc(c.label)}</span> {c.cell(r)}' for c in cols[1:])
        return (first.cell(r) if first else "", "", rest)
    out = table(rows, cols, key, sorts=sorts, page=page, card=card, on_open=on_open, ticker=ticker or "ticker", empty="없습니다.")
    if csv and len(df):
        st.download_button("⬇ CSV", df[[c for c in names]].to_csv(index=show_idx).encode("utf-8-sig"), file_name=f"{base}.csv", mime="text/csv", key=f"{key}_csv")
    return out


def dataframe_compat(data=None, width="stretch", height="auto", *, use_container_width=None, hide_index=None, column_order=None, column_config=None,
                     key=None, on_select="ignore", selection_mode="multi-row", row_height=None, **kw):
    """install 뒤의 st.dataframe: 고르기(on_select)를 쓰는 표만 예전 표, 나머지는 안 눌리는 표(key 가 없으면 부른 파일·줄로)."""
    if on_select != "ignore" or _style() == "old":
        return _orig()(data, width=width, height=height, use_container_width=use_container_width, hide_index=hide_index, column_order=column_order,
                       column_config=column_config, key=key, on_select=on_select, selection_mode=selection_mode, row_height=row_height, **kw)
    if key is None:
        import os
        import sys
        f = sys._getframe(1)
        key = f"t_{os.path.basename(f.f_code.co_filename).rsplit('.', 1)[0]}_{f.f_lineno}"
    return frame(data, key=key, column_config=column_config, column_order=column_order, hide_index=hide_index)


def install() -> None:
    """dashboard.py 에서 한 번: 모든 화면의 st.dataframe 을 안 눌리는 표로(관리 모드 '📋 표 모양' old 면 예전 표). 매 실행마다 key 기록도 비움."""
    if getattr(st, "_utb_orig_dataframe", None) is None:
        st._utb_orig_dataframe = st.dataframe
        st.dataframe = dataframe_compat
    new_run()
