"""🧭 종합 판단 카드 화면(🏢 종목 맨 위). 계산은 verdict.py."""
from __future__ import annotations

from datetime import date

import streamlit as st

import ui_kit as ui
import verdict

LV_COLOR = {"높음": "red", "중간": "orange", "낮음": "green"}
KIND_COLOR = {"호재": "green", "희석": "red", "악재": "red", "중립": "gray"}


def _dday(s) -> str:
    d = verdict._d(s)
    if not d:
        return ""
    n = (d - date.today()).days
    return f"D-{n}" if n >= 0 else f"D+{-n}"


def _purposes(ps: list[dict]) -> str:
    if not ps:
        return "<div class='qk-sub'>뚜렷한 이유 없음 — 런웨이 넉넉 · 상장 기준 충족 · 행사가 높은 워런트 없음</div>"
    rows = []
    for p in ps:
        need = "" if not p.get("need") else f" · 필요 주가 ${p['need']:.4f}" + (f" (+{p['need_pct']:.0f}%)" if p.get("need_pct") and p["need_pct"] > 0 else "")
        dd = f" · {p['deadline']} {_dday(p['deadline'])}" if p.get("deadline") else ""
        rows.append(f"<li><b>{ui.esc(p['title'])}</b> {ui.chip(p.get('urgency') or '-', 'red' if p.get('urgency') in verdict.STRONG else 'gray')}"
                    f"{ui.esc(need + dd)}<br><span class='qk-sub'>{ui.esc(p.get('why') or '')}</span></li>")
    return "<ul style='margin:0;padding-left:1.1rem'>" + "".join(rows) + "</ul>"


def _fin(f: dict, stats: dict) -> str:
    color = LV_COLOR.get(f["level"], "gray")
    head = ui.chip(f"현금조달 가능성 {f['level']} · {f['score']}점", color)
    lis = "".join(f"<li>{'+' if p > 0 else ''}{p} {ui.esc(r)}</li>" for p, r in f["reasons"]) or "<li>특별한 조달 신호 없음</li>"
    pu = f["pump"]
    pl = ""
    if pu["pumps"]:
        ex = " · ".join(f"{a} 급등 → {b} {c}" for a, b, c in pu["examples"][-2:])
        pl = (f"<div class='qk-sub' style='margin-top:4px'>📈→💸 최근 3년 급등 {pu['pumps']}번 중 7일 안 조달 공시 {pu['raised']}번"
              + (f" (평소 아무 날이나 7일 안 조달 확률 {pu['base']}%)" if pu.get("base") is not None else "") + (f"<br>{ui.esc(ex)}" if ex else "") + "</div>")
    if stats:
        sv = " · ".join(f"{k} → {v[1]}%({v[0]}건)" for k, v in stats.items())
        val = f"<div class='qk-sub' style='margin-top:4px'>🏆 이 판정의 지난 성적(30일 안 실제 조달): {ui.esc(sv)}</div>"
    else:
        val = "<div class='qk-sub' style='margin-top:4px'>🏆 판정 성적은 기록 30일 뒤부터 보여요(아침마다 기록 중)</div>"
    return head + f"<ul style='margin:4px 0 0;padding-left:1.1rem'>{lis}</ul>" + pl + val


def _flow(fl: dict) -> str:
    c = fl["count"]
    head = (f"<b>{ui.esc(fl['verdict'])}</b> " + ui.chip(f"호재 {c['호재']}", "green") + ui.chip(f"희석 {c['희석']}", "red") + ui.chip(f"악재 {c['악재']}", "red")
            + f" <span class='qk-sub'>최근 {fl['days']}일 · 종목 뉴스 {fl['news']}건</span>")
    lis = "".join(f"<li>{ui.esc(x['date'])} {ui.esc(x['form'])} {ui.chip(x['kind'], KIND_COLOR.get(x['kind'], 'gray'))}"
                  f"<span class='qk-sub'>{ui.esc(', '.join(x['tags']))}</span></li>" for x in fl["items"])
    agm = ("<div class='qk-sub' style='margin-top:4px'>🗳 주총: " + ui.esc(" · ".join(fl["agm"])) + "</div>") if fl["agm"] else ""
    return head + (f"<ul style='margin:4px 0 0;padding-left:1.1rem'>{lis}</ul>" if lis else "") + agm


def render(t: str, b: dict | None = None) -> None:
    try:
        v = verdict.build(t, b)
    except Exception as e:  # noqa: BLE001
        st.caption(f"🧭 종합 판단을 만들지 못했어요: {e}")
        return
    sm = v["summary"]
    st.markdown(ui.verdict("🧭 " + sm["label"], sm["text"], color=sm["color"]), unsafe_allow_html=True)
    if v.get("forensic"):
        st.caption(f"🧾 공시분석 한 줄({v['forensic']['as_of']}): {v['forensic']['one_liner']}")
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown("**🎯 주가를 올려야 하는 이유**", help="회사가 주가를 올려야 풀리는 일들 — 필요한 주가·기한·근거. 주총·역분할 자체는 상승 이유로 치지 않아요.")
        st.markdown(_purposes(v["purposes"]), unsafe_allow_html=True)
    with c2.container(border=True):
        st.markdown("**🏦 현금조달 가능성**", help="높을수록 곧 공모·ATM 등으로 주식을 팔 가능성이 커요(급등 뒤 물량이 나올 위험). 점수는 이유별 +/− 합계.")
        st.markdown(_fin(v["fin"], v.get("fin_stats") or {}), unsafe_allow_html=True)
    with c3.container(border=True):
        st.markdown("**📰 공시 흐름**", help="최근 14일 공시를 호재·희석(공모·등록·3.02 등)·악재로 셈 + 주총 흐름.")
        st.markdown(_flow(v["flow"]), unsafe_allow_html=True)
    st.caption("규칙으로 정리한 판단(비용 0 · 예측 아님) — 숫자는 공시·시세 기반 추정이니 원문 확인. 김곰 워치리스트의 종합 판단 구성을 참고했어요.")
