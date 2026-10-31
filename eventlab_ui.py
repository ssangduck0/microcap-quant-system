"""🔬 이벤트 연구 화면 — 수집 진행 · 사건 종류별 성과 · 사례 · 🏁 순위 가중치 제안."""
import json

import pandas as pd
import streamlit as st

import chartpop

import access
import config
import db
import eventlab as ev
import ui_kit as ui


@st.cache_data(ttl=900, show_spinner=False)
def _table():
    return ev.table()



def _pct_cfg(df) -> dict:
    """표 숫자 자릿수 통일: 수익률 +0.0 · 확률 0.0 (예전엔 47.7876 처럼 들쭉날쭉)."""
    return {c: st.column_config.NumberColumn(format="%.1f" if "확률" in c else "%+.1f") for c in df.columns if "(%)" in c}

def render() -> None:
    ui.title("이벤트 연구", "최근 3년 8-K·6-K 보도자료가 나온 뒤 주가가 실제로 어떻게 움직였는지(장 마감 뒤 공시는 다음 거래일 기준) 사건 종류별로 봐요. 과거 통계이며 예측이 아닙니다.")
    st.caption("⚠️ 생존 편향: 상장폐지된 회사는 주가 자료를 구할 수 없어 대부분 빠져 있어요. 사라진 회사는 보통 나쁜 일 뒤에 사라지므로, "
               "실제 결과는 이 표보다 조금 더 나빠요(특히 공모·상장유지 통지·병합). 좋고 나쁨의 순서는 대체로 그대로예요. "
               "앞으로는 🗄 주가 보관소가 신호 낸 종목의 주가를 남겨 두어 점점 보완돼요.")
    with db.connect() as conn:
        ev.ensure_tables(conn)
        n_doc = conn.execute("SELECT COUNT(*) FROM ev_docs").fetchone()[0]
        n_ok = conn.execute("SELECT COUNT(*) FROM ev_docs WHERE ok=1").fetchone()[0]
        n_lab = conn.execute("SELECT COUNT(*) FROM ev_labels").fetchone()[0]
    pg = json.loads((db.get_meta("ev_progress") or {}).get("value") or "{}")
    ui.cards([{"t": "수집한 공시", "v": f"{n_doc:,}", "s": f"보도자료·본문 읽음 {n_ok:,}", "accent": True}, {"t": "남은 수집", "v": f"{pg.get('left', '-'):,}" if isinstance(pg.get("left"), int) else "-",
               "s": "start_collector.bat 가 하루 종일 이어받기"}, {"t": "주가 반응 계산", "v": f"{n_lab:,}", "s": "공시 8일 지난 것부터"}])
    df = _table()
    if df.empty:
        st.info("아직 계산된 사건이 없어요. 수집기(start_collector.bat 또는 `python eventlab.py run`)가 돌면 채워져요.")
        return
    c1, c2, c3 = st.columns(3)
    pr = c1.selectbox("기준일 전 주가", ["전체", "$1 미만", "$1~5", "$5 이상"], key="ev_px")
    tm = c2.selectbox("공시 시점", ["전체", "장전", "장중", "장후", "시각 미상"], key="ev_tm")
    mn = c3.slider("최소 건수", 1, 100, 10, key="ev_min")
    lo, hi = {"전체": (None, None), "$1 미만": (None, 1.0), "$1~5": (1.0, 5.0), "$5 이상": (5.0, None)}[pr]
    v = df
    if lo is not None:
        v = v[v["price"] >= lo]
    if hi is not None:
        v = v[v["price"] < hi]
    if tm != "전체":
        v = v[v["timing"] == tm]
    s = ev.stats(v, "type", mn)
    st.markdown(f"**사건 종류별 성과** — {len(v):,}건 · 표는 'D+5 초과수익'(같은 기간 IWM 대비) 순")
    if s.empty:
        st.caption("조건에 맞는 사건이 부족해요. 최소 건수를 낮춰 보세요.")
    else:
        st.dataframe(s, hide_index=True, width="stretch", column_config=_pct_cfg(s))
        chartpop.bar(s.set_index("type")["D+5 초과 절사평균(%)"], key="ev_type", title="사건 종류별 D+5 초과 절사평균(%)", height=220)  # 극단값에 덜 흔들리는 값
    st.markdown("**판정별(호재·악재·혼재·중립)**")
    _ss = ev.stats(v, "sentiment", 1)
    st.dataframe(_ss, hide_index=True, width="stretch", column_config=_pct_cfg(_ss))
    typ = st.selectbox("사례 보기", ["(선택)"] + sorted(v["type"].unique()), key="ev_type")
    if typ != "(선택)":
        ex = v[v["type"] == typ].sort_values("up5", ascending=False).copy()
        ex["title"] = ex["title"].map(ev.clean_title)   # 예전 수집분 제목 앞의 파일 머리글 떼기
        st.dataframe(ex[["day0", "ticker", "timing", "title", "price", "gap", "ret0", "up5", "dn5", "ret5"]].rename(columns={
            "day0": "기준일", "ticker": "티커", "timing": "시점", "title": "제목", "price": "전일 종가", "gap": "갭(%)", "ret0": "당일(%)", "up5": "D+5 최고(%)", "dn5": "D+5 최저(%)", "ret5": "D+5 종가(%)"}),
            hide_index=True, width="stretch")
    st.divider()
    st.markdown("**🏁 순위 가중치 제안** (호재 공시 사건 30건 이상부터)")
    sg = ev.suggest(df)
    if not sg:
        st.caption("아직 근거가 부족해요.")
    for x in sg:
        st.markdown(f"- `{x['key']}`: {x['cur']:g} → **{x['new']:g}** — {ui.esc(x['why'])}", unsafe_allow_html=True)
        if not access.is_guest() and x["new"] != x["cur"] and st.button(f"적용: {x['key']} = {x['new']:g}", key=f"ev_apply_{x['key']}"):
            ov = config.overrides()
            ov[x["key"]] = x["new"]
            config.save_overrides(ov)
            st.success("적용했어요. 다음 순위 계산부터 반영돼요(관리 모드에서 되돌릴 수 있어요).")
    st.caption("가상매매의 '신호별 성과'와 함께 보세요. 표본이 적은 종류는 우연일 수 있어요.")
    st.divider()
    st.markdown("**🧮 과거 성과 기반 공시 점수** — 사건 종류 × 가격대 × 시점별 'D+5 시장보다 이긴 확률'로 공시마다 점수(표본 적은 칸은 기준선 쪽으로)")
    import evscore
    x = evscore.load()
    if not x or not x.get("table"):
        st.caption("아직 점수표가 없어요. 매일 아침 갱신이 만들어요(지금 바로: python evscore.py).")
    else:
        v, tb = x.get("validation") or {}, x["table"]
        st.caption(f"만든 시각 {x['built']} · 사건 {tb.get('n', 0):,}건 · 기준선 {tb.get('p0', 0) * 100:.1f}% · 판정: {v.get('why', '-')}"
                   + ("" if config.RANK_NEWS_EVIDENCE else " · ⚠️ 관리 모드에서 꺼 둠(예전 규칙 사용)"))
        if "new" in v:
            st.dataframe(pd.DataFrame([{"방식": "🧮 새 점수(위 20% vs 아래 20%)", "순위 상관": v["new"]["rho"], "좋은 쪽 이긴 확률(%)": v["new"]["top"],
                                        "나쁜 쪽(%)": v["new"]["bottom"], "차이(%p)": v["new"]["spread"]},
                                       {"방식": "지금 규칙(호재 vs 악재)", "순위 상관": v["old"]["rho"], "좋은 쪽 이긴 확률(%)": v["old"]["top"],
                                        "나쁜 쪽(%)": v["old"]["bottom"], "차이(%p)": v["old"]["spread"]}]), hide_index=True, width="stretch")
            st.caption(f"검증: ~{v['cut']} 까지 {v['train']:,}건으로 점수표를 만들고, 그 뒤 {v['test']:,}건에 맞춰 봄(과거에만 맞춘 규칙을 걸러냄).")
        cells = pd.DataFrame([{"칸(종류|가격대|시점)": k, "건수": n, "점수(%p)": round((p - tb["p0"]) * 100, 1)} for k, (n, p) in tb.get("cell", {}).items()])
        if not cells.empty:
            st.dataframe(cells.sort_values("점수(%p)"), hide_index=True, width="stretch", height=260)
