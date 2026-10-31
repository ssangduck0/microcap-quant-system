"""🛠 운영 현황 화면(홈 · 주인만): 🩺 아침 작업 점검표 · ⏱ 자동 작업 일정 · 📜 작업 기록. 계산은 jobs.py."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

import jobs
import ui_kit as ui

BG = {"red": "rgba(229,72,77,.22)", "yellow": "rgba(247,107,21,.20)", "": "transparent"}
WD = "월화수목금토일"
TH = "padding:4px 8px;border-bottom:1px solid rgba(128,128,128,.35);text-align:right;white-space:nowrap;font-weight:600"
TD = "padding:3px 8px;border-bottom:1px solid rgba(128,128,128,.18);text-align:right;white-space:nowrap"


def _num(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _day(r: dict) -> str:
    t = jobs._ts(r.get("finished"))
    if not t:
        return "-"
    k = t.astimezone(jobs.KST)
    return f"{k:%m/%d}({WD[k.weekday()]})"


def _table_html(t: dict) -> str:
    head = f'<th style="{TH};text-align:left">항목</th>' + "".join(f'<th style="{TH}">{ui.esc(_day(r))}</th>' for r in t["days"])
    body = ""
    for row in t["rows"]:
        tip = {"up": "클수록 정상 — 평소(직전 6번 중앙값)의 절반 아래·0이면 빨강", "down": "작을수록 정상 — 기준을 넘으면 노랑·빨강", "info": "참고"}[row["dir"]]
        cells = "".join(f'<td style="{TD};background:{BG[c]}">{ui.esc(_num(v))}</td>' for v, c in row["vals"])
        body += f'<tr><td style="{TD};text-align:left" title="{ui.esc(tip)}">{ui.esc(row["name"])}</td>{cells}</tr>'
    return (f'<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:.86rem;width:100%"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _health() -> None:
    t = jobs.table(7)
    if not t["days"]:
        st.info("아직 기록이 없어요. 다음 아침 작업(화~토 07:30)이 끝나면 첫 줄이 생겨요.")
        return
    if t["alerts"]:
        st.markdown(ui.chip(f"🔴 오늘 빨간 칸 {len(t['alerts'])}개", "red") + " " + ui.esc(" · ".join(
            f"{n} {_num(v)}(평소 {_num(None if p is None else round(p))})" for n, v, p in t["alerts"])), unsafe_allow_html=True)
    else:
        st.markdown(ui.chip("🟢 오늘 빨간 칸 없음", "green"), unsafe_allow_html=True)
    st.markdown(_table_html(t), unsafe_allow_html=True)
    st.caption("아침 작업이 끝날 때 지난 24시간 숫자를 남겨요. 빨강 = 평소(직전 6번 중앙값)의 절반 아래·0, 또는 기준 초과('내용 없음' 60%↑·스퀴즈 순위 4일↑·"
               "텔레그램 실패 10건↑·경고 5건↑) · 노랑 = 조금 낮거나 기준 근처. 항목에 마우스를 올리면 설명.")


def _schedule() -> None:
    now = datetime.now(timezone.utc)
    rows = jobs.schedule(now)
    head = "".join(f'<th style="{TH};text-align:left">{h}</th>' for h in ("작업", "하는 일", "주기", "다음 실행", "지난 실행"))
    body = ""
    for r in rows:
        nx = "-" if r["next"] is None else f"{r['next'].astimezone(jobs.KST):%m/%d %H:%M} · {r['next_txt']}"
        if r["kind"] == "loop":
            nx = r["next_txt"]
        mark = "" if r["last_ok"] is None else ("✅ " if r["last_ok"] else "❌ ")
        last = f"{mark}{r['last_txt']}" + (f" · {r['last_note']}" if r["last_note"] else "")
        body += (f'<tr><td style="{TD};text-align:left"><b>{ui.esc(r["name"])}</b></td><td style="{TD};text-align:left;white-space:normal">{ui.esc(r["what"])}</td>'
                 f'<td style="{TD};text-align:left">{ui.esc(r["when"])}</td><td style="{TD};text-align:left">{ui.esc(nx)}</td>'
                 f'<td style="{TD};text-align:left;white-space:normal">{ui.esc(last)}</td></tr>')
    st.markdown(f'<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:.86rem;width:100%"><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>", unsafe_allow_html=True)
    st.caption("한국 시간 · 지난 실행은 각 작업이 남긴 기록(스캐너·수집기는 마지막 활동, 백업은 마지막 파일).")


def _history() -> None:
    page = int(st.session_state.get("jobs_page", 0))
    rows = jobs.runs(limit=10, offset=page * 10)
    if not rows:
        st.info("아직 기록이 없어요.")
        return
    total = rows[0]["total"]
    for r in rows:
        t = jobs._ts(r["finished"])
        when = "-" if not t else f"{t.astimezone(jobs.KST):%m/%d %H:%M}"
        color = "blue" if r["ok"] else "red"
        st.markdown(ui.chip(jobs.TAG.get(r["job"], r["job"]), color) + f" <b>{ui.esc(r['summary'] or r['job'])}</b> "
                    f"<span style='opacity:.65'>{ui.esc(when)}</span>", unsafe_allow_html=True)
    pages = max(1, -(-total // 10))
    a, b, c = st.columns([1, 1, 4])
    if a.button("← 최근", key="jobs_prev", disabled=page == 0):
        st.session_state["jobs_page"] = page - 1
        st.rerun()
    if b.button("이전 기록 →", key="jobs_next", disabled=page + 1 >= pages):
        st.session_state["jobs_page"] = page + 1
        st.rerun()
    c.caption(f"{page + 1} / {pages} 쪽 · 모두 {total}줄")


def render() -> None:
    st.markdown("### 🛠 운영 현황")
    a, b, c = st.tabs(["🩺 아침 작업 점검표", "⏱ 자동 작업 일정", "📜 작업 기록"])
    with a:
        _health()
    with b:
        _schedule()
    with c:
        _history()
