"""🔁 병합 후 반등 레이더 탭."""
from contextlib import closing

import altair as alt
import pandas as pd
import streamlit as st

import chartpop

import db
import pick as picker
import rsplit as rs
import tosslink_ui


def _fx() -> float:
    try:
        return float((db.get_meta("usdkrw") or {}).get("value") or 1350.0)
    except (TypeError, ValueError):
        return 1350.0


def render() -> None:
    st.subheader("🔁 병합(역분할) 후 반등 레이더")
    st.caption("최근 1년 안에 역분할한 종목이 지금 '병합 후 N거래일째, 병합일 대비 이만큼' 와 있을 때, 과거 10년 동안 같은 시점·비슷한 낙폭이었던 역분할 종목들이 "
               "그 뒤 10거래일 동안 어떻게 움직였는지로 성공률·예상 반등 출발가·예상 장중 고가·반등 소요를 계산합니다. 상장폐지 종목이 빠져 있어(생존편향) 낙관적일 수 있어요.")
    render_upcoming()
    with closing(db.connect()) as conn:
        rs.ensure_tables(conn)
        n_ev = conn.execute("SELECT COUNT(*) FROM rs_events").fetchone()[0]
        n_path = conn.execute("SELECT COUNT(*) FROM rs_paths").fetchone()[0]
    if not n_ev:
        st.info("아직 분할 기록이 없습니다. 명령 프롬프트에서 한 번 실행하세요(10년치, 수십 분): `python rsplit.py build --years 10` "
                "— 이후에는 매일 아침 갱신 작업이 최근 1년을 다시 확인합니다.")
        return
    c = st.columns(4)
    target = c[0].slider("성공 기준: 10거래일 안 최고 +%", 5, 100, 20, key="rs_target")
    band_k = c[1].slider("병합 후 거래일 허용 ±", 3, 30, 10, key="rs_bk")
    band_dd = c[2].slider("병합일 대비 등락 허용 ±%p", 3, 30, 10, key="rs_bd")
    min_n = c[3].slider("유사 사례 최소", 5, 200, 20, key="rs_n")
    with closing(db.connect()) as conn:
        rd = rs.radar(conn, float(target), int(band_k), float(band_dd))
    st.caption(f"과거 역분할 {n_ev:,}건 · 병합 후 경로 {n_path:,}개 · 최근 병합 종목 {len(rd)}개")
    if rd.empty:
        st.info("최근 1년 안에 역분할한 종목이 없습니다(매일 아침 갱신).")
        return
    fx = _fx()
    rd = rd[rd["n"].fillna(0) >= min_n].sort_values("success", ascending=False) if "success" in rd else rd.iloc[0:0]
    if rd.empty:
        st.info("유사 사례가 충분한 종목이 없습니다. 허용 범위를 넓히거나 최소 사례 수를 낮춰 보세요.")
        return
    try:
        dil = dict(db.read_df("SELECT ticker, status FROM dilution").values)
    except Exception:  # noqa: BLE001
        dil = {}
    try:
        import regsho
        with closing(db.connect()) as conn:
            sho = regsho.streaks(conn)
    except Exception:  # noqa: BLE001
        sho = {}
    tb = pd.DataFrame({"티커": rd["ticker"], "토스": tosslink_ui.links(rd["ticker"]), "병합일": rd["split_date"],
                       "비율": rd["ratio"].map(lambda r: f"{round(1 / r):g}:1" if r else ""), "병합 후 거래일": rd["k"], "병합 후 등락(%)": rd["dd"],
                       "현재가(원)": rd["price"] * fx, "유사 사례": rd["n"], f"성공률(10일 내 +{target}%)": rd["success"],
                       "예상 반등 출발가(원)": rd["start_price"] * fx, "예상 장중 고가(원)": rd["exp_high"] * fx, "고가 상위 25%(원)": rd["exp_high_q75"] * fx,
                       "반등 소요(일)": rd["days_med"], "희석": rd["ticker"].map(lambda x: dil.get(x, "미확인")), "Reg SHO": rd["ticker"].map(lambda x: regsho_label(sho.get(x)))})
    cfg = {"토스": tosslink_ui.COLUMN, **{k: st.column_config.NumberColumn(format="%,.0f") for k in ("현재가(원)", "예상 반등 출발가(원)", "예상 장중 고가(원)", "고가 상위 25%(원)")},
           "병합 후 등락(%)": st.column_config.NumberColumn(format="%+.0f"), f"성공률(10일 내 +{target}%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
           "반등 소요(일)": st.column_config.NumberColumn(format="%.0f", help="유사 사례에서 10거래일 안 최고가가 나온 날(중앙값)")}
    t = picker.clickable(tb.reset_index(drop=True), list(rd["ticker"]), "rs_table", hide_index=True, width="stretch", column_config=cfg)
    if not t:
        return
    r = rd[rd["ticker"] == t].iloc[0]
    st.markdown(f"#### 🔁 {t} — 병합 {r['split_date']} 후 {int(r['k'])}거래일째 · 병합일 대비 {r['dd']:+.0f}%")
    tosslink_ui.button(t, key="rs")
    paths = db.read_df("SELECT * FROM rs_paths WHERE k BETWEEN ? AND ?", (int(r["k"]) - band_k, int(r["k"]) + band_k))
    sim = rs.similar(paths, int(r["k"]), float(r["dd"]), band_k, band_dd, exclude=(t, r["split_date"]))
    if not sim.empty:
        h = sim.assign(**{"10일 내 최고(%)": sim["fwd_max"].clip(upper=200)})
        chartpop.show(alt.Chart(h).mark_bar(opacity=0.7).encode(x=alt.X("10일 내 최고(%):Q", bin=alt.Bin(step=5), title="유사 사례의 10거래일 안 최고 상승(%) — 200%↑는 200%"),
                                                                 y=alt.Y("count():Q", title="사례 수")).properties(height=220)
                        + alt.Chart(pd.DataFrame({"x": [target]})).mark_rule(color="#d62728", strokeDash=[4, 4]).encode(x="x:Q"), key="rs_hist", title="유사 사례의 10거래일 안 최고 상승 분포", data=h)
        st.caption(f"유사 사례 {int(r['n'])}개(역분할 {int(r['events'])}건) · 10일 안 최저 중앙값 {r['min_med']:+.0f}% → 예상 반등 출발가 ${r['start_price']:.4f} · "
                   f"최고 중앙값 {r['max_med']:+.0f}% → 예상 장중 고가 ${r['exp_high']:.4f} · 10일 뒤 종가 중앙값 {r['close_med']:+.0f}%")


def regsho_label(n) -> str:
    return "" if not n else f"📛 {int(n)}일째"


def render_upcoming() -> None:
    """📅 병합 예정 — 🗓 일정의 '역분할 시행'(앞으로) + 세력·셋업 분석에서 병합 안건이 잡힌 종목."""
    import json
    from datetime import date
    rows = []
    try:
        from contextlib import closing
        import db
        with closing(db.connect()) as conn:
            up = rs.upcoming(conn)   # C단계 2026-10-27: 시행일·비율·환산가·병합 후 주식 수(래빗스탁 RS Scanner 예정 목록처럼)
        for e in up.to_dict("records"):
            rows.append({"티커": e["티커"], "근거": "역분할 시행일", "날짜": e["시행일"], "내용": f"{e['D-day']} · 비율 {e['비율'] or '미확인'}"
                         + ("" if e["병합 환산가($)"] is None else f" · 환산가 ${e['병합 환산가($)']:.2f}(현재가×비율, 예측 아님)")
                         + ("" if e["병합 후 주식 수(만주)"] is None else f" · 병합 후 약 {e['병합 후 주식 수(만주)']:,.0f}만주"), "원문": e["근거"]})
    except Exception:  # noqa: BLE001
        pass
    try:
        import pumpsetup
        for r in pumpsetup.all_cached().itertuples():
            d = json.loads(r.data)
            for sgl in d.get("signals") or []:
                if sgl["신호"].startswith("병합(역분할) 안건") and sgl["결과"]:
                    rows.append({"티커": r.ticker, "근거": "병합 안건(주총 서류)", "날짜": d.get("analyzed"), "내용": d.get("verdict"), "원문": sgl.get("근거")})
    except Exception:  # noqa: BLE001
        pass
    with st.expander(f"📅 병합 예정 — 공시 기준 {len(rows)}건", expanded=bool(rows)):
        if not rows:
            st.caption("아직 없습니다. ⭐ 워치리스트의 '공시에서 후보 찾기'(일정)나 🕵️ 세력·셋업 분석을 돌리면 병합 안건·시행일이 잡힙니다.")
            return
        df = pd.DataFrame(rows).drop_duplicates(subset=["티커", "근거"])
        df.insert(1, "토스", tosslink_ui.links(df["티커"]))
        st.dataframe(df, hide_index=True, width="stretch", column_config={"토스": tosslink_ui.COLUMN, "원문": st.column_config.LinkColumn(display_text="열기")})
        st.caption("병합 직후는 유통 주식이 줄어 급등·급락이 모두 커집니다. 병합 뒤에는 아래 레이더에서 과거 사례와 비교하세요.")
