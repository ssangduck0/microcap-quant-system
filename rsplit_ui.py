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


@st.cache_data(ttl=300, show_spinner=False)
def _radar(target: float, band_k: int, band_dd: float):
    """경로·최근 병합 표는 아침 작업 때만 바뀜 → 같은 조건이면 5분 동안 재사용(2026-10-30 화면 속도 점검: 9.4초 → 1.2초 → 다시 볼 때 즉시)."""
    with closing(db.connect()) as conn:
        return rs.radar(conn, target, band_k, band_dd)


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
    rd = _radar(float(target), int(band_k), float(band_dd))
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
    try:   # 🔁 병합 체크포인트(2026-11-01 · rsrisk): 지금가 · 변동성 · 상습 병합 → 6개월 안 다시 $1 아래(병합 1년 안이면 유예 없이 상폐 결정)
        import rsrisk
        with closing(db.connect()) as conn:
            _tab = rsrisk.table(conn)
            rk = {t: rsrisk.current(conn, t, tab=_tab) for t in rd["ticker"]}
    except Exception:  # noqa: BLE001
        rk = {}
    tb = pd.DataFrame({"티커": rd["ticker"], "토스": tosslink_ui.links(rd["ticker"]), "병합일": rd["split_date"],
                       "비율": rd["ratio"].map(lambda r: f"{round(1 / r):g}:1" if r else ""), "병합 후 거래일": rd["k"], "병합 후 등락(%)": rd["dd"],
                       "6개월 안 $1 아래(%)": rd["ticker"].map(lambda x: None if not rk.get(x) else (100.0 if rk[x]["below"] else rk[x]["prob"])),
                       "현재가(원)": rd["price"] * fx, "유사 사례": rd["n"], f"성공률(10일 내 +{target}%)": rd["success"],
                       "예상 반등 출발가(원)": rd["start_price"] * fx, "예상 장중 고가(원)": rd["exp_high"] * fx, "고가 상위 25%(원)": rd["exp_high_q75"] * fx,
                       "반등 소요(일)": rd["days_med"], "희석": rd["ticker"].map(lambda x: dil.get(x, "미확인")), "Reg SHO": rd["ticker"].map(lambda x: regsho_label(sho.get(x)))})
    cfg = {"토스": tosslink_ui.COLUMN, **{k: st.column_config.NumberColumn(format="%,.0f") for k in ("현재가(원)", "예상 반등 출발가(원)", "예상 장중 고가(원)", "고가 상위 25%(원)")},
           "병합 후 등락(%)": st.column_config.NumberColumn(format="%+.0f"), f"성공률(10일 내 +{target}%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
           "반등 소요(일)": st.column_config.NumberColumn(format="%.0f", help="유사 사례에서 10거래일 안 최고가가 나온 날(중앙값)"),
           "6개월 안 $1 아래(%)": st.column_config.NumberColumn(format="%.0f", help="지금가 · 60일 변동성 · 상습 병합(직전 3년)으로 본 과거 비율(100 = 이미 $1 아래). "
                                                               "나스닥: 병합 1년 안 다시 $1 아래면 180일 유예 없이 상장폐지 결정(2025-01-30~)")}
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


def _num(v):
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def upcoming_rows(conn) -> list[dict]:
    """병합 예정 줄: 🗓 '역분할 시행'(앞으로 · 7일 안이면 🔁 재이탈 확률) + 세력·셋업 분석의 병합 안건. 비율을 모르면 None(예전 표는 nan 으로 찍혔음)."""
    import json
    from datetime import date
    import rsrisk
    rows = []
    try:
        up = rs.upcoming(conn)   # C단계 2026-10-27: 시행일·비율·환산가·병합 후 주식 수(래빗스탁 RS Scanner 예정 목록처럼)
        tab = rsrisk.table(conn)
        today = date.today()
        for e in up.to_dict("records"):
            ratio = e["비율"] if isinstance(e["비율"], str) and e["비율"] else None
            rows.append({"ticker": e["티커"], "kind": "시행", "date": e["시행일"], "d": (date.fromisoformat(e["시행일"]) - today).days, "ratio": ratio,
                         "exp": _num(e["병합 환산가($)"]), "sh": _num(e["병합 후 주식 수(만주)"]), "risk": rsrisk.upcoming(conn, e["티커"], tab=tab),
                         "src": e["근거"] or "", "text": None})
    except Exception:  # noqa: BLE001
        pass
    try:
        import pumpsetup
        for r in pumpsetup.all_cached().itertuples():
            d = json.loads(r.data)
            for sgl in d.get("signals") or []:
                if sgl["신호"].startswith("병합(역분할) 안건") and sgl["결과"]:
                    rows.append({"ticker": r.ticker, "kind": "안건", "date": d.get("analyzed"), "d": None, "ratio": None, "exp": None, "sh": None, "risk": None,
                                 "src": sgl.get("근거") or "", "text": d.get("verdict")})
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for r in rows:
        if (r["ticker"], r["kind"]) not in seen:
            seen.add((r["ticker"], r["kind"]))
            out.append(r)
    return out


def _up_cells():
    """병합 예정 표 칸(ui_table) — 자료 글자는 모두 감싸서."""
    import rsrisk
    import ui_kit as ui
    import ui_table as utb

    import tosslink
    cmap = tosslink.codes()   # 줄마다 다시 읽지 않게 한 번만

    def tk(r):
        u = tosslink.url(r["ticker"], cmap)
        return f'<span class="tk">{utb.esc(r["ticker"])}</span>' + (f' <a href="{utb.esc(u)}" target="_blank" title="토스에서 열기">↗</a>' if u else "")

    def when(r):
        if r["kind"] == "안건":
            return ui.chip("안건(주총 서류)", "gray") + f'<br><span class="mut">{utb.esc((r["date"] or "")[:10])}</span>'
        d = r["d"]
        return ui.chip("오늘" if d == 0 else f"D-{d}", "red" if d <= 2 else "orange" if d <= 7 else "gray") + f'<br><span class="mut">{utb.esc(r["date"][5:].replace("-", "/"))}</span>'

    def ratio(r):
        return '<span class="mut">-</span>' if r["kind"] == "안건" else (utb.esc(r["ratio"]) if r["ratio"] else '<span class="mut">미확인</span>')

    def after(r):
        if r["kind"] == "안건":
            return utb.esc(r["text"] or "")
        if r["exp"] is None:
            return '<span class="mut">비율을 몰라 계산 안 함</span>'
        return f"예상 ${r['exp']:.2f}" + (f" · 약 {r['sh']:,.0f}만주" if r["sh"] else "")

    def risk(r):
        k = r.get("risk")
        if k and k.get("prob") is not None:
            return ui.chip(f"{k['prob']:.0f}%", "red" if k["prob"] >= rsrisk.RED else "gray")
        if r["kind"] == "시행" and r["d"] is not None and r["d"] <= 7:
            return '<span class="mut">자료 부족</span>'
        return '<span class="mut">7일 안만 계산</span>' if r["kind"] == "시행" else '<span class="mut">-</span>'

    def src(r):   # 근거 글은 '6-K 2026-10-29 https://…' 꼴 → 주소는 링크로 숨기고 '6-K 10/29 열기' 만
        import re
        s = r["src"] or ""
        m = re.search(r"https?://\S+", s)
        if not m:
            return utb.esc(s[:40]) if s else '<span class="mut">-</span>'
        lab = re.sub(r"(\d{4})-(\d{2})-(\d{2})", lambda x: f"{x.group(2)}/{x.group(3)}", s[:m.start()].strip())[:24]
        return (f'<span class="mut">{utb.esc(lab)}</span> ' if lab else "") + f'<a href="{utb.esc(m.group(0))}" target="_blank">열기</a>'
    cols = [utb.Col("티커", tk, "12%"), utb.Col("시행일", when, "13%"), utb.Col("비율", ratio, "9%"), utb.Col("병합 뒤", after),
            utb.Col("6개월 안 $1 아래", risk, "17%"), utb.Col("원문", src, "13%")]
    card = lambda r: (tk(r), when(r).replace("<br>", " "), " · ".join(x for x in (ratio(r), after(r), risk(r)) if x))  # noqa: E731
    return cols, card


def render_upcoming() -> None:
    """📅 병합 예정 — 🗓 일정의 '역분할 시행'(앞으로) + 세력·셋업 분석에서 병합 안건이 잡힌 종목.
    2026-11-01(사용자 '표가 불편 · 안 눌리게'): 안 눌리는 표(ui_table) — 칸 클릭·가로 스크롤 없이 칸을 나누고 색 칩 · 휴대폰은 카드 · 비율 모름 = '미확인'(예전엔 nan)."""
    import report_dialog
    import ui_table as utb
    with closing(db.connect()) as conn:
        rows = upcoming_rows(conn)
    with st.expander(f"📅 병합 예정 — 공시 기준 {len(rows)}건", expanded=bool(rows)):
        if not rows:
            st.caption("아직 없습니다. ⭐ 워치리스트의 '공시에서 후보 찾기'(일정)나 🕵️ 세력·셋업 분석을 돌리면 병합 안건·시행일이 잡힙니다.")
            return
        cols, card = _up_cells()
        big = 10 ** 6
        utb.table(rows, cols, "rs_up", page=15, card=card, on_open=report_dialog.open_report,
                  sorts={"시행일 가까운 순": lambda r: (r["kind"] != "시행", r["d"] if r["d"] is not None else big, r["ticker"]),
                         "재이탈 위험 높은 순": lambda r: (-((r.get("risk") or {}).get("prob") or -1), r["d"] if r["d"] is not None else big),
                         "티커 순": lambda r: r["ticker"]})
        st.caption("병합 직후는 유통 주식이 줄어 급등·급락이 모두 커집니다. '6개월 안 \\$1 아래' 는 병합 7일 안 종목만(병합 뒤 예상가 · 지금 변동성) — "
                   "나스닥: 병합 1년 안 다시 \\$1 아래면 유예 없이 상장폐지 결정. 병합 뒤에는 아래 레이더에서 과거 사례와 비교하세요.")   # $ 두 개면 수식으로 바뀜 → \\$
