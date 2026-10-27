"""화면 디자인 도구 — 카드·칩·순위 줄(래빗스탁처럼: 큰 숫자, 흐린 설명, 빨강은 강조에만)."""
import html

import streamlit as st

RED, BLUE, GREEN, ORANGE, PURPLE = "#E5484D", "#3678F6", "#30A46C", "#F76B15", "#8E4EC6"
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&display=swap');
html, body, [data-testid="stAppViewContainer"], .stMarkdown, button, input, textarea { font-family: 'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif !important; }
[data-testid="stAppDeployButton"], [data-testid="stDecoration"] { display: none !important; }
[data-testid="stMainBlockContainer"], .block-container { max-width: 1480px; padding-top: 4rem !important; }
h1 { font-weight: 800 !important; letter-spacing: -.02em; } h2, h3 { font-weight: 800 !important; letter-spacing: -.01em; }
[data-testid="stMetricValue"] { font-weight: 800 !important; }
[data-testid="stExpander"] details { border-radius: 12px !important; }
.qk-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; margin: 6px 0 20px; }
/* 📱 휴대폰: 촘촘하게 · 카드 2열 · 아래 고정 메뉴 */
.st-key-qk_bottomnav { display: none; }
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"], .block-container { padding: 3.4rem .6rem 6.6rem !important; }
  .qk-cards { grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 12px; }
  .qk-card { padding: 10px 12px !important; }
  .qk-card .v { font-size: 1.15rem !important; }
  h1, h2 { font-size: 1.3rem !important; }
  h3 { font-size: 1.12rem !important; }  /* 화면 제목(subheader)이 휴대폰에서 두 줄로 넘치지 않게 */
  [data-testid="stMainBlockContainer"], .block-container { padding-top: 2.9rem !important; }  /* 위쪽 빈 공간 줄이기 */
  .st-key-qk_bottomnav { display: block; position: fixed; left: 0; right: 0; bottom: 0; z-index: 999990; background: #101318f2; backdrop-filter: blur(8px);
                         border-top: 1px solid rgba(128,128,128,.3); padding: 6px 2px calc(6px + env(safe-area-inset-bottom)); }
  .pk-ctrl, .st-key-pk_ctrl [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 6px !important; align-items: center; }
  .st-key-pk_ctrl [data-testid="stColumn"], .st-key-pk_ctrl [data-testid="column"] { min-width: 0 !important; width: auto !important; }
  .st-key-pk_ctrl [data-testid="stColumn"], .st-key-pk_ctrl [data-testid="column"] { flex: 0 0 auto !important; }  /* 빈칸 없이 왼쪽부터 붙임 */
  .st-key-pk_ctrl button { padding: 4px 9px !important; min-height: 34px !important; }
  .st-key-pk_ctrl [data-testid="stWidgetLabel"] p, .st-key-pk_ctrl label p { font-size: .8rem !important; white-space: nowrap; }
  .st-key-qk_bottomnav [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0 !important; }
  .st-key-qk_bottomnav [data-testid="stColumn"], .st-key-qk_bottomnav [data-testid="column"] { min-width: 0 !important; width: auto !important; flex: 1 1 0 !important; }
  /* 링크를 감싼 칸들이 글자 폭(16px)으로 줄어들던 문제 → 칸 전체 폭·높이로 */
  .st-key-qk_bottomnav [data-testid="stColumn"] > div, .st-key-qk_bottomnav [data-testid="column"] > div,
  .st-key-qk_bottomnav .stElementContainer, .st-key-qk_bottomnav .stPageLink, .st-key-qk_bottomnav .stPageLink > div { width: 100% !important; min-width: 0 !important; }
  .st-key-qk_bottomnav [data-testid="stPageLink-NavLink"] { flex-direction: column; gap: 3px; width: 100% !important; height: auto !important; min-height: 52px; padding: 5px 0 4px !important;
                                                           margin: 0 !important; justify-content: center; align-items: center; border-radius: 10px; color: #E6E8EB !important; }
  .st-key-qk_bottomnav [data-testid="stPageLink-NavLink"] > span:first-child { width: auto !important; height: auto !important; margin: 0 !important; }
  .st-key-qk_bottomnav [data-testid="stPageLink-NavLink"] [data-testid="stIconEmoji"] { font-size: 1.3rem !important; line-height: 1; }
  .st-key-qk_bottomnav [data-testid="stPageLink-NavLink"] > span:last-child { overflow: visible !important; max-width: none !important; }
  .st-key-qk_bottomnav [data-testid="stPageLink-NavLink"] p { font-size: .68rem !important; font-weight: 600; line-height: 1.1; white-space: nowrap; margin: 0; color: #E6E8EB !important; letter-spacing: -.03em; }
  .st-key-qk_bottomnav [data-testid="stPageLink-NavLink"]:active { background: rgba(229,72,77,.18); }
}
@media (max-width: 380px) {  /* 작은 휴대폰(360px): PICK 정렬 줄을 더 촘촘하게 */
  .st-key-pk_ctrl [data-testid="stHorizontalBlock"] { gap: 4px !important; }
  .st-key-pk_ctrl button { padding: 4px 7px !important; font-size: .82rem !important; }
  .st-key-pk_ctrl [data-testid="stWidgetLabel"] p, .st-key-pk_ctrl label p { font-size: .74rem !important; }
}
/* 📱 간략 보기: 화면 위 같은 묶음 화면 칩(옆으로 밀기) */
.st-key-qk_subnav { flex-wrap: nowrap !important; overflow-x: auto; overflow-y: visible; scrollbar-width: none; gap: 6px !important; margin: -4px 0 6px; padding: 2px 1px 4px; }  /* 칩 테두리 잘림 방지 */
.st-key-qk_subnav::-webkit-scrollbar { display: none; }
.st-key-qk_subnav > div { flex: 0 0 auto !important; width: auto !important; }
.st-key-qk_subnav [data-testid="stPageLink-NavLink"] { border: 1px solid rgba(128,128,128,.35); border-radius: 999px; padding: 4px 12px !important; white-space: nowrap; }
.st-key-qk_subnav [data-testid="stPageLink-NavLink"] p { font-size: .86rem !important; font-weight: 600; white-space: nowrap; }
@media (max-width: 768px) {  /* 매집 카드 버튼(리포트·토스·종목)을 한 줄에 나란히 — 예전엔 세로 3줄로 카드가 길었음 */
  [class*="st-key-acb_"] { flex-direction: row !important; flex-wrap: nowrap !important; gap: 6px !important; }
  [class*="st-key-acb_"] > div { flex: 1 1 0 !important; min-width: 0 !important; width: auto !important; }
  [class*="st-key-acb_"] button, [class*="st-key-acb_"] a { padding: 4px 6px !important; font-size: .82rem !important; }
}
@media (max-width: 768px) {  /* 📱 휴대폰 조밀 화면: 한 화면에 더 많이(글자 약간 작게 · 위아래 여백 줄임) */
  html { font-size: 14px; }                                              /* 글자·버튼·입력칸 전체가 약 12% 작아짐(rem 기준) */
  [data-testid="stVerticalBlock"] { gap: .55rem !important; }           /* 요소 사이 간격 */
  [data-testid="stMarkdownContainer"] p { margin-bottom: .35rem; }
  [data-testid="stMetricValue"] { font-size: 1.35rem !important; }
  [data-testid="stMetricLabel"] p { font-size: .8rem !important; }
  [data-testid="stExpander"] summary { padding: .45rem .7rem !important; }
  [data-testid="stCaptionContainer"] { font-size: .78rem !important; }
  .qk-title { font-size: 1.2rem !important; } .qk-desc { font-size: .8rem !important; margin-bottom: .45rem !important; }
  .qk-card .t { font-size: .76rem !important; } .qk-card .s { font-size: .7rem !important; }
  .qk-cards { gap: 6px !important; margin: 4px 0 10px !important; }
  .qk-chip { font-size: .7rem !important; padding: 1px 6px !important; }
  [data-testid="stHeadingWithActionElements"] h3, h3 { margin: .2rem 0 .1rem !important; }
}
/* 아래 메뉴는 휴대폰 라이트/다크 설정과 상관없이 항상 어두운 막대 + 밝은 글씨(예전엔 라이트 모드 폰에서 흰 바탕에 흰 글씨가 됨) */
.qk-card { border: 1px solid rgba(128,128,128,.22); border-radius: 16px; padding: 16px 18px 14px; background: rgba(128,128,128,.035); }
.qk-card .t { font-size: .86rem; font-weight: 700; opacity: .72; }
.qk-card.accent .t { color: #E5484D; opacity: 1; }
.qk-card .v { font-size: 1.9rem; font-weight: 800; line-height: 1.15; margin-top: 6px; }
.qk-card .s { font-size: .8rem; opacity: .6; margin-top: 2px; }
.qk-delta { display: inline-block; margin-top: 10px; font-size: .78rem; font-weight: 700; padding: 3px 10px; border-radius: 999px; }
.qk-up { background: rgba(229,72,77,.12); color: #E5484D; } .qk-down { background: rgba(54,120,246,.12); color: #3678F6; } .qk-flat { background: rgba(128,128,128,.12); }
.qk-chip { display: inline-block; font-size: .74rem; font-weight: 700; padding: 2px 9px; border-radius: 6px; margin: 2px 6px 2px 0; border: 1px solid transparent; white-space: nowrap; }
.qk-red { background: rgba(229,72,77,.10); color: #E5484D; border-color: rgba(229,72,77,.35); }
.qk-blue { background: rgba(54,120,246,.10); color: #3678F6; border-color: rgba(54,120,246,.35); }
.qk-green { background: rgba(48,164,108,.10); color: #30A46C; border-color: rgba(48,164,108,.35); }
.qk-orange { background: rgba(247,107,21,.10); color: #F76B15; border-color: rgba(247,107,21,.35); }
.qk-purple { background: rgba(142,78,198,.10); color: #8E4EC6; border-color: rgba(142,78,198,.35); }
.qk-gray { background: rgba(128,128,128,.10); border-color: rgba(128,128,128,.3); }
.qk-pill { display: inline-block; font-weight: 800; color: #E5484D; border: 1px solid rgba(229,72,77,.45); border-radius: 999px; padding: 4px 13px; background: rgba(229,72,77,.07); }
.qk-tk { font-weight: 800; font-size: 1.08rem; } .qk-sub { font-size: .8rem; opacity: .62; } .qk-rank { font-size: 1.15rem; font-weight: 800; opacity: .75; }
.qk-title { font-size: 1.5rem; font-weight: 800; letter-spacing: -.02em; margin: .2rem 0 .1rem; } .qk-desc { font-size: .9rem; opacity: .62; margin-bottom: .8rem; }
.qk-hist { display: inline-block; font-size: .78rem; padding: 4px 11px; border-radius: 999px; margin: 3px 4px 3px 0; border: 1px solid rgba(128,128,128,.3); }
.qk-hist.on { border-color: rgba(229,72,77,.6); color: #E5484D; background: rgba(229,72,77,.07); font-weight: 700; }
.qk-verdict { border: 1.5px solid rgba(128,128,128,.35); border-radius: 14px; padding: 14px 16px; margin: 4px 0 12px; }
.qk-verdict .h { font-weight: 800; font-size: 1.05rem; } .qk-verdict .x { opacity: .7; font-size: .88rem; margin-left: 8px; }
.qk-bar { margin-top: 10px; border-radius: 10px; padding: 8px 12px; background: rgba(128,128,128,.08); font-size: .82rem; display: flex; align-items: center; gap: 12px; }
.qk-bar .track { flex: 1; height: 6px; border-radius: 6px; background: rgba(128,128,128,.25); overflow: hidden; } .qk-bar .fill { height: 100%; border-radius: 6px; }
.qk-flags { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 6px 0 10px; }
.qk-flag { border: 1px solid rgba(128,128,128,.28); border-radius: 12px; text-align: center; padding: 12px 6px; font-weight: 800; }
.qk-flag .n { font-size: .8rem; opacity: .7; } .qk-flag .v { font-size: 1.1rem; opacity: .35; margin-top: 2px; }
.qk-flag.on { border-color: rgba(229,72,77,.6); background: rgba(229,72,77,.08); } .qk-flag.on .v, .qk-flag.on .n { color: #E5484D; opacity: 1; }
.qk-kv { display: flex; justify-content: space-between; padding: 10px 4px; border-bottom: 1px solid rgba(128,128,128,.18); font-size: .92rem; } .qk-kv b { font-weight: 800; }
.qk-box { border: 1px solid rgba(128,128,128,.22); border-radius: 14px; padding: 12px 14px; height: 100%; }
.qk-box .h { font-weight: 800; margin-bottom: 6px; } .qk-box ul { margin: 0; padding-left: 1.1rem; } .qk-box li { font-size: .88rem; margin: 4px 0; opacity: .9; }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x)).replace("$", "&#36;")  # '$' 를 수식 기호로 읽지 않게


def md_safe(text: str) -> str:
    """마크다운 그대로 보여 줄 때 '$' 가 수식(LaTeX)으로 바뀌지 않게(예: $1.07 ... $2.08M)."""
    return str(text or "").replace("\\$", "$").replace("$", "\\$")


def title(text: str, desc: str = "") -> None:
    st.markdown(f'<div class="qk-title">{esc(text)}</div>' + (f'<div class="qk-desc">{esc(desc)}</div>' if desc else ""), unsafe_allow_html=True)


def delta_html(d) -> str:
    if d is None:
        return ""
    cls = "qk-up" if d > 0 else ("qk-down" if d < 0 else "qk-flat")
    arrow = "↗" if d > 0 else ("↘" if d < 0 else "→")
    return f'<span class="qk-delta {cls}">{arrow} 전일 대비 {d:+,}</span>'


def cards(items: list[dict]) -> None:
    """items: {"t": 제목, "v": 값, "s": 작은 설명, "d": 전일 대비(정수), "accent": True}"""
    body = "".join(f'<div class="qk-card{" accent" if it.get("accent") else ""}"><div class="t">{esc(it["t"])}</div><div class="v">{esc(it["v"])}</div>'
                   + (f'<div class="s">{esc(it["s"])}</div>' if it.get("s") else "") + delta_html(it.get("d")) + "</div>" for it in items)
    st.markdown(f'<div class="qk-cards">{body}</div>', unsafe_allow_html=True)


def chip(text: str, color: str = "gray", tip: str = "") -> str:
    return f'<span class="qk-chip qk-{color}"' + (f' title="{esc(tip)}"' if tip else "") + f">{esc(text)}</span>"


def verdict(label: str, desc: str, strength: float | None = None, color: str = "#30A46C", bar_label: str = "관심도(규칙 기반 추정)") -> str:
    bar = "" if strength is None else (f'<div class="qk-bar"><span>{esc(bar_label)}</span><div class="track"><div class="fill" style="width:{max(0, min(100, strength)):.0f}%;'
                                       f'background:{color}"></div></div><b>{strength:.0f}</b></div>')
    return f'<div class="qk-verdict" style="border-color:{color}55"><span class="h" style="color:{color}">{esc(label)}</span><span class="x">{esc(desc)}</span>{bar}</div>'


def flags(items: list[tuple[str, bool]]) -> str:
    return '<div class="qk-flags">' + "".join(f'<div class="qk-flag{" on" if on else ""}"><div class="n">{"⚠ " if on else ""}{esc(n)}</div><div class="v">{"ON" if on else "OFF"}</div></div>'
                                              for n, on in items) + "</div>"


def kv(rows: list[tuple[str, str]]) -> str:
    return "".join(f'<div class="qk-kv"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in rows)


def box(title: str, bullets: list[str], color: str = "") -> str:
    lis = "".join(f"<li>{esc(b)}</li>" for b in bullets) or "<li>해당 없음</li>"
    return f'<div class="qk-box"><div class="h" style="color:{color}">{esc(title)}</div><ul>{lis}</ul></div>'


PRICE_HINTS = ("가($", "가격", "($)", "진입가", "종가(", "시가(", "고가(", "저가(", "현재가", "price", "entry")


def tidy(df):
    """표 보기 좋게: 숫자는 소수 한 자리(가격 열은 네 자리) · 빈칸(None·NaN)은 '-'. 화면 표시용 복사본을 돌려줌.
    예전엔 '-33.5516'·'96.003'·'None' 처럼 들쭉날쭉했음."""
    import pandas as pd
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    for c in out.columns:
        col = out[c]
        name = str(c)
        if pd.api.types.is_float_dtype(col):
            nd = 4 if any(h in name for h in PRICE_HINTS) else 1
            out[c] = [("-" if pd.isna(v) else (f"{v:,.{nd}f}" if abs(v) >= 1000 and nd == 1 else f"{v:.{nd}f}")) for v in col]
        elif not pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_bool_dtype(col):  # 글자 열(object·str) — pandas 3 은 문자열이 'str' 종류
            out[c] = ["-" if (v is None or (not isinstance(v, (list, dict, tuple)) and pd.isna(v))) else v for v in col]
    return out


def scanner_universe(days: int = 30) -> set[str]:
    """'초소형주' = 스캐너가 최근 days일 안에 본 종목(가격만으로 자르면 병합 직후 $20 넘는 초소형 시총 종목이 빠짐). 5분 기억."""
    import streamlit as _st

    @_st.cache_data(ttl=300, show_spinner=False)
    def _u(d: int) -> tuple:
        from datetime import date as _d, timedelta as _td
        import db as _db
        try:
            return tuple(_db.read_df("SELECT DISTINCT ticker FROM daily_snapshots WHERE date >= ?", ((_d.today() - _td(days=d)).isoformat(),))["ticker"])
        except Exception:  # noqa: BLE001
            return ()
    return set(_u(days))
