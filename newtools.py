"""🏦 대량 보유 — 📝 공시 요약(secdigest)이 뽑은 13D(경영개입형)·13G(단순투자형) 보유자·지분율.
(🌀 폭풍의 눈은 🕰 타임머신 시험 조건으로만 둠 — 효과가 확인되면 기존 화면에 표시를 붙임. 🌑 다크풀은 보류: 초소형주·SPAC 는 원래 장외 비율이 높아 신호로 쓰기 어려움)
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db
import ui_kit as ui

VAC_LEVELS = ((5, "극도로 조용"), (10, "매우 조용"), (15, "조용"), (20, "보통"))
LOW52_BAND = 1.15      # 52주 최저가의 1.15배 이내 = 바닥권
SMALL_CAP = 50e6


def render_holders() -> None:
    ui.title("대량 보유", "13D(경영개입형)·13G(단순투자형) 기관 대량 보유 공시 — 📝 공시 요약이 원문에서 보유자·지분율을 뽑아요. 13D 는 행동주의 촉매, 보유 지분 감소는 물량 신호일 수 있어요.")
    import secdigest
    with closing(db.connect()) as conn:
        df = secdigest.holders(conn)
    if df.empty:
        st.info("아직 대량 보유 공시 요약이 없어요. 스캐너가 새 13D/13G 공시를 받으면 자동으로 요약해요.")
        return
    ui.cards([{"t": "종목", "v": f"{df['ticker'].nunique()}"}, {"t": "경영개입형(13D)", "v": f"{int((df['type'] == '경영개입형').sum())}", "accent": True},
              {"t": "단순투자형(13G)", "v": f"{int((df['type'] == '단순투자형').sum())}"}])
    kind = st.segmented_control("분류", ["전체", "경영개입형", "단순투자형"], default="전체", key="hd_kind") or "전체"
    v = df if kind == "전체" else df[df["type"] == kind]
    tb = pd.DataFrame([{"티커": r["ticker"], "공시일": r["filed"], "서류": r["form"], "보유자": r["holder"], "지분율(%)": r["pct"], "분류": r["type"] or "-",
                        "요약": (r["summary_ko"] or "")[:90]} for r in v.head(100).to_dict("records")])
    import pick as picker
    t = picker.clickable(ui.tidy(tb), list(tb["티커"]), "hd_t", hide_index=True, width="stretch")
    if t:
        import report_dialog
        report_dialog.button(t, "hd")
