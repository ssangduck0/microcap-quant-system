"""🔍 차트 팝업 (2026-10-27 D단계) — 화면의 작은 차트를 **클릭하면** 팝업(st.dialog)에 큰 차트 · 숫자 표 · CSV 내려받기가 뜬다.

홈의 시장 지표(VIX·공포탐욕·수입물가)만 빼고 대시보드의 모든 차트가 이 도우미를 쓴다.
- Streamlit 기본 차트(line_chart·bar_chart)는 클릭을 못 받아서 전부 Altair 로 그린다(line() · bar() 도우미).
- 클릭 감지 = Altair 점 선택(on_select="rerun"). 같은 선택이 남아 있으면 팝업이 다시 뜨지 않게 선택 내용의 서명을 기억한다.
- 휴대폰 터치가 선택으로 안 잡힐 때를 위해 차트 아래에 '🔍 크게 보기' 버튼도 둔다.
- 팝업 안(리포트 팝업 등)에서 또 팝업을 열 수는 없으므로(Streamlit 제한) 그때는 펼침(expander)으로 대신 보여 준다.
- 확대·이동(.interactive()) 차트는 드래그와 클릭이 겹쳐 click=False 로 두고 버튼만 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import altair as alt
import pandas as pd
import streamlit as st


def _slug(key: str) -> str:
    s = re.sub(r"\W+", "_", key)
    if s != key or not s or s[0].isdigit():
        s = "k" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    return s


def _data_of(chart, data):
    if data is not None:
        return data
    try:
        d = chart.data
        if isinstance(d, pd.DataFrame):
            return d
    except Exception:  # noqa: BLE001
        pass
    try:
        for lyr in getattr(chart, "layer", None) or []:
            d = getattr(lyr, "data", None)
            if isinstance(d, pd.DataFrame):
                return d
    except Exception:  # noqa: BLE001
        pass
    return None


def _table(data) -> pd.DataFrame | None:
    if data is None:
        return None
    if isinstance(data, pd.Series):
        data = data.to_frame()
    if not isinstance(data, pd.DataFrame) or data.empty:
        return None
    show = data if isinstance(data.index, pd.RangeIndex) else data.reset_index()
    show = show.loc[:, [c for c in show.columns if not str(c).startswith("_")]]
    show.columns = [str(c) for c in show.columns]
    for c in show.select_dtypes("float").columns:   # 0.0000000000001 같은 계산 찌꺼기 정리
        show[c] = show[c].round(6)
    return show


def _detail(chart, title: str, data, note: str | None, big_height: int, key: str) -> None:
    try:
        big = chart.properties(height=big_height)
    except Exception:  # noqa: BLE001
        big = chart
    st.altair_chart(big, width="stretch")
    if note:
        st.caption(note)
    tb = _table(data)
    if tb is not None:
        st.markdown(f"**숫자 표** ({len(tb):,}행)")
        st.dataframe(tb, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(tb)))
        st.download_button("⬇️ CSV 내려받기", tb.to_csv(index=False).encode("utf-8-sig"), file_name=f"{re.sub(r'[^\\w가-힣]+', '_', title)}.csv", mime="text/csv", key=f"cp_dl_{key}")


@st.dialog("🔍 차트 자세히", width="large")
def _popup(chart, title: str, data, note: str | None, big_height: int, key: str) -> None:
    st.markdown(f"**{title}**")
    _detail(chart, title, data, note, big_height, key)


def _widget(fn, key: str, **kw):
    """같은 화면에 같은 차트가 두 번 그려져도(전체 화면 테스트 등) 키가 겹치지 않게 뒤에 번호를 붙여 다시 시도."""
    for i in range(1, 6):
        k = key if i == 1 else f"{key}_{i}"
        try:
            return fn(k)
        except Exception as e:  # noqa: BLE001
            if "Duplicate" not in type(e).__name__ and "duplicate" not in str(e).lower():
                raise
    return fn(f"{key}_x")


def show(chart, key: str, title: str, data=None, note: str | None = None, click: bool = True, height: int | None = None, big_height: int = 460) -> None:
    """작은 Altair 차트를 그리고 클릭·'크게 보기'로 팝업. data = 팝업의 숫자 표(없으면 차트 데이터)."""
    key = _slug(key)
    data = _data_of(chart, data)
    small = chart if height is None else chart.properties(height=height)
    opened = False
    if click and os.environ.get("QUANT_TEST_ALL_PAGES") != "1":
        try:
            name = f"cpsel_{key}"
            sel = alt.selection_point(name=name, on="click", empty=False)
            ev = _widget(lambda k: st.altair_chart(small.add_params(sel), key=f"cp_{k}", on_select="rerun", selection_mode=[name], width="stretch"), key)
            s = {}
            try:
                s = dict(ev["selection"]) if ev is not None else {}
            except Exception:  # noqa: BLE001
                s = {}
            picked = s.get(name)
            sig = json.dumps(s, sort_keys=True, default=str)
            if picked and sig != st.session_state.get(f"_cp_sig_{key}"):
                opened = True
            st.session_state[f"_cp_sig_{key}"] = sig
        except Exception:  # noqa: BLE001  (선택 파라미터를 못 다는 차트 등) → 그냥 그림
            st.altair_chart(small, width="stretch")
    else:
        st.altair_chart(small, width="stretch")
    if _widget(lambda k: st.button("🔍 크게 보기", key=f"cp_btn_{k}", help="큰 차트 · 숫자 표 · CSV 내려받기"), key) or opened:
        try:
            _popup(chart, title, data, note, big_height, key)
        except Exception:  # noqa: BLE001  팝업 안에서는 팝업을 또 못 열어요 → 펼침으로
            with st.expander(f"🔍 {title} — 자세히", expanded=True):
                _detail(chart, title, data, note, big_height, key + "_x")


def _long(data) -> tuple[pd.DataFrame, str, bool]:
    """넓은 표(index = 가로축, 열 = 계열) → 긴 표(x · 계열 · 값). 반환: (긴 표, x 축 종류 T/O, 계열이 하나인지)."""
    if isinstance(data, pd.Series):
        data = data.to_frame(name=data.name if data.name is not None else "값")
    df = data.copy()
    df.columns = [str(c) for c in df.columns]
    xt = "T" if isinstance(df.index, pd.DatetimeIndex) else "O"
    xname = str(df.index.name or "x")
    long = df.reset_index().rename(columns={df.index.name or "index": xname}).melt(id_vars=[xname], var_name="계열", value_name="값")
    long = long.rename(columns={xname: "x"})
    long["x순"] = long.groupby("계열").cumcount()
    return long, xt, len(df.columns) == 1


def line(data, key: str, title: str, height: int = 200, y_title: str | None = None, x_title: str | None = None, note: str | None = None, click: bool = True,
         zero: bool = False, fmt: str = ".4g") -> None:
    """st.line_chart 대신: 넓은 표/시리즈 → Altair 선 차트 + 팝업."""
    long, xt, single = _long(data)
    if long.empty:
        st.caption("표시할 데이터가 없습니다.")
        return
    x = alt.X("x:T", title=x_title) if xt == "T" else alt.X("x:O", title=x_title, sort=None, axis=alt.Axis(labelAngle=0, labelOverlap="greedy"))
    ch = alt.Chart(long).mark_line(point=len(long) <= 80, strokeWidth=1.8).encode(
        x=x, y=alt.Y("값:Q", title=y_title, scale=alt.Scale(zero=zero)),
        color=alt.Color("계열:N", legend=None if single else alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("x:T", title=x_title or "날짜", format="%Y-%m-%d") if xt == "T" else alt.Tooltip("x:O", title=x_title or ""), "계열:N", alt.Tooltip("값:Q", format=fmt)]
    ).properties(height=height)
    show(ch, key, title, data=data if isinstance(data, pd.DataFrame) else data.to_frame(), note=note, click=click)


def bar(data, key: str, title: str, height: int = 200, horizontal: bool = False, y_title: str | None = None, x_title: str | None = None, note: str | None = None,
        click: bool = True, fmt: str = ".4g") -> None:
    """st.bar_chart 대신: 시리즈/넓은 표 → Altair 막대 차트 + 팝업. horizontal=True 면 가로 막대(항목이 많을 때)."""
    long, xt, single = _long(data)
    if long.empty:
        st.caption("표시할 데이터가 없습니다.")
        return
    cat = alt.X("x:O", title=x_title, sort=None, axis=alt.Axis(labelAngle=0, labelOverlap="greedy")) if not horizontal else alt.Y("x:O", title=x_title, sort=None)
    val = alt.Y("값:Q", title=y_title) if not horizontal else alt.X("값:Q", title=y_title)
    enc = {"x": cat, "y": val} if not horizontal else {"x": val, "y": cat}
    ch = alt.Chart(long).mark_bar(opacity=0.85).encode(**enc, color=alt.Color("계열:N", legend=None if single else alt.Legend(orient="bottom", title=None)),
                                                      tooltip=[alt.Tooltip("x:O", title=x_title or ""), "계열:N", alt.Tooltip("값:Q", format=fmt)])
    if not single and not horizontal:
        ch = ch.encode(xOffset="계열:N")
    ch = ch.properties(height=max(height, 24 * long["x"].nunique() + 40)) if horizontal else ch.properties(height=height)
    show(ch, key, title, data=data if isinstance(data, pd.DataFrame) else data.to_frame(), note=note, click=click)
