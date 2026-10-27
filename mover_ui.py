"""📈 급상승/급하락 화면 — 토스 순위 상위 100(스캐너가 사이클마다 기록) · 희석 배지 · 산업 · 시가총액 · 7일 뉴스/공시 · 종목 보기."""
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import db
import mover
import pick as picker
import tosslink_ui
import ui_kit as ui

KST = ZoneInfo("Asia/Seoul")


def _load(kind: str):
    with closing(db.connect()) as conn:
        meta, rows = mover.latest(conn, kind)
        tb = mover.enrich(conn, rows)
    return meta, tb


def render() -> None:
    ui.title("급상승/급하락", "토스 순위 상위 100(세션 상관없이 지금 순위 · ETF·워런트 제외)에 희석 배지·산업·시가총액·최근 뉴스/공시 수를 붙여요. "
             "희석 배지가 붙은 급등주는 회사가 그 틈에 물량을 풀 수 있으니 조심하세요.")
    kind = st.radio("종류", ["📈 급상승", "📉 급하락"], horizontal=True, key="mv_kind", label_visibility="collapsed")
    k = "up" if kind.startswith("📈") else "down"
    meta, tb = _load(k)
    if tb is None or tb.empty:
        st.info("아직 순위 기록이 없어요. 서버 스캐너가 돌기 시작하면 사이클마다(몇 분) 채워져요.")
        return
    when = ""
    if meta.get("at"):
        try:
            when = datetime.fromisoformat(meta["at"]).astimezone(KST).strftime("%m/%d %H:%M KST")
        except Exception:  # noqa: BLE001
            when = meta["at"]
    st.caption(f"{meta.get('source', '')} · 기준일 {meta.get('date', '-')}" + (f" · 갱신 {when}" if when else "") + (f" · 세션 {meta['session']}" if meta.get("session") else "")
               + f" · {len(tb)}종목")
    import rank_ui
    dils = sorted({x for x in tb["희석"] if x})
    f1, f2 = st.columns([2, 3])
    only_clean = f1.toggle("희석 배지 없는 종목만", False, key="mv_clean")
    pick_dil = f2.multiselect("희석 배지 고르기", dils, key="mv_dil", placeholder="전체")
    v = tb[tb["희석"] == ""] if only_clean else (tb[tb["희석"].isin(pick_dil)] if pick_dil else tb)
    v = v.copy()
    v.insert(2, "토스", tosslink_ui.links(v["티커"]))
    v.insert(3, "종합 순위", rank_ui.column(v["티커"]))
    cfg = {"토스": tosslink_ui.COLUMN, "현재가": st.column_config.NumberColumn(format="%.4f"), "등락률(%)": st.column_config.NumberColumn(format="%+.2f"),
           "시가총액($M)": st.column_config.NumberColumn(format="%.1f")}
    t = picker.clickable(v, list(v["티커"]), "mv_table", hide_index=True, width="stretch", column_config=cfg)
    if t:
        c1, c2 = st.columns([1, 4])
        if c1.button("🏢 종목 보기", key="mv_go"):
            st.session_state["lookup_ticker"] = t
            import tabs
            tabs.go("lookup", "lookup")
        row = v[v["티커"] == t].iloc[0]
        c2.caption(f"{t} · {row['이름']} · {row['산업'] or '산업 미확인'} · 희석 {row['희석'] or '배지 없음'} · 뉴스 {row['뉴스 7일']}건 · 공시 {row['공시 7일']}건(7일)")
