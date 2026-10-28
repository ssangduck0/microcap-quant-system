"""🐷 저금통 탭 — 저가 박스권 종목 담기·감시·매매 기록."""
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st

import chartpop

import config
import db
import forensic
import forensic_ui
import intel
import intel_ui
import piggy
import pick as picker
import flowread_ui
import pumpsetup_ui
import tosslink_ui
import shortflow_ui
import watch_ui

@st.cache_data(ttl=1800, show_spinner=False)
def prices_1y(tickers: tuple) -> dict:
    """1년 일봉(Yahoo, 30분 캐시) — 과거 급등 이력·발사대 자리용."""
    if not tickers:
        return {}
    try:
        import market
        return market.download_daily(list(tickers), period="1y")
    except Exception:  # noqa: BLE001
        return {}


def _q_icon(v, warn: bool = False) -> str:
    """결과 아이콘. warn(⑥ 10~20%) 이면 통과여도 ⚠️ 로 보여 줌(집계는 통과)."""
    return "➖" if v is None else ("⚠️" if v == "주의" or (warn and v is True) else ("✅" if v else "❌"))


def _q_label(x: dict) -> str:
    """상세 표의 결과 글: ⑥ 10~20% 는 '⚠️ 통과(주의)'."""
    if x.get("주의") and x["결과"] is True:
        return "⚠️ 통과(주의)"
    return {True: "✅ 통과", False: "❌ 미달", "주의": "⚠️ 주의"}.get(x["결과"], "➖ 확인 불가")


ZONE_ORDER = {"⚠️ 박스 이탈": 0, "🟢 저점 구간": 1, "🔴 고점 구간": 2, "⏸ 중간": 3, "확인 불가": 4}


def _dilution() -> dict:
    try:
        return dict(db.read_df("SELECT ticker, status FROM dilution").values)
    except Exception:  # noqa: BLE001
        return {}


def _snap_price(tickers: list[str]) -> dict:
    """오늘 스캐너가 저장한 가격(장중 최신). 없으면 비움."""
    if not tickers:
        return {}
    df = db.read_df(f"SELECT ticker, price, date FROM daily_snapshots WHERE ticker IN ({','.join('?' * len(tickers))}) ORDER BY date DESC", tuple(tickers))
    df = df.drop_duplicates("ticker")
    today = df["date"].max() if not df.empty else None
    return {r.ticker: float(r.price) for r in df.itertuples() if r.date == today and r.price == r.price}


def _chart(df: pd.DataFrame | None, lo: float | None, hi: float | None) -> None:
    if df is None or df.empty:
        st.caption("가격 데이터가 없습니다(Yahoo 일봉).")
        return
    c = df["Close"].dropna().tail(120)
    data = pd.DataFrame({"종가": c})
    if lo:
        data["박스 하단"] = lo
    if hi:
        data["박스 상단"] = hi
    data.index = data.index.strftime("%m-%d")
    chartpop.line(data, key="piggy_box", title="종가와 박스(최근 120거래일)", height=260, y_title="$")


def _cats(current: str | None = None) -> list[str]:
    have = [c for c in piggy.items()["category"].dropna().unique()] if not piggy.items().empty else []
    out = list(dict.fromkeys([*(have), *piggy.DEFAULT_CATEGORIES]))
    if current and current not in out:
        out.insert(0, current)
    return out


def _category_input(key: str, current: str | None = None) -> str:
    opts = _cats(current) + ["➕ 새 카테고리"]
    sel = st.selectbox("카테고리", opts, index=opts.index(current) if current in opts else 0, key=f"{key}_sel")
    if sel == "➕ 새 카테고리":
        return st.text_input("새 카테고리 이름", key=f"{key}_new").strip() or "기타"
    return sel


def render(fx: float) -> None:
    st.subheader("🐷 저금통 — 저가 박스권 종목")
    st.caption("기준: ① 시장가 희석(ATM·ELOC·전환사채) 없음 ② 펀더멘탈(런웨이·현금) ③ 박스권이 오래 유지됨. 저점 구간에서 담고 고점·급등 때 판다. "
               "⚠️ **$1 미만 종목은 30거래일 연속이면 나스닥 미달 통지 → 역분할**로 박스가 깨지기 쉽고, 호가 간격이 커서 왕복 2~5%가 비용으로 나갈 수 있습니다. "
               "📒 매매 기록으로 실제 성과를 꼭 확인하세요.")
    with st.expander("📜 " + piggy.PROFIT_TIP_TITLE):
        st.text(piggy.PROFIT_TIP_TEXT)
        st.caption("① 상폐 위험은 단계로 봅니다: $1 미만 180거래일 이상이거나 미달 통지 + 회복 기한 60일 이내면 ❌, $1 미만 30거래일 이상·최근 미달 통지면 ⚠️. "
                   "③ 1년 안 +30% 이상 급등, ⑤ 6개월에 +20% 이상 3회 이상, 종배 이력은 과거 사례 DB의 급락 다음날 시가로 봅니다.")
    labels = ["🐷 내 저금통", "🔎 후보 찾기", "📒 매매 기록", "🩳 공매도 흐름 (스승님 꿀팁)"]

    def _flow():
        import watch
        tks = list(dict.fromkeys(piggy.tickers() + watch.scanner_priority()))
        shortflow_ui.render_tab(tks, watch_ui.prices(tuple(tks)))
    parts = [lambda: render_list(fx), lambda: render_screen(fx), lambda: render_trades(fx), _flow]
    import os
    if os.environ.get("QUANT_TEST_ALL_PAGES") == "1" or not hasattr(st, "segmented_control"):  # 테스트(전체 화면 한 번에)·옛 Streamlit: 예전처럼 탭
        for tab, fn in zip(st.tabs(labels), parts):
            with tab:
                fn()
        return
    # 탭은 안 보는 탭까지 전부 계산해서 15~20초 걸렸음(특히 '공매도 흐름'이 수십~수백 종목) → 고른 것 하나만 그림
    sel = st.segmented_control("보기", labels, default=labels[0], key="pg_sec", label_visibility="collapsed") or labels[0]
    parts[labels.index(sel)]()


# ---------------------------------------------------------------- 🐷 내 저금통
def render_list(fx: float) -> None:
    it = piggy.items()
    if it.empty:
        st.info("저금통이 비어 있습니다. **🔎 후보 찾기**에서 종목을 골라 담으세요(20~30개 권장).")
        return
    tickers = list(it["ticker"])
    px = watch_ui.prices(tuple(tickers))
    snap = _snap_price(tickers)
    mm = piggy.metrics_map()
    dil = _dilution()
    fxd = forensic.latest_dates()
    rows = []
    with closing(db.connect()) as conn:
        intel.ensure_table(conn)
        for r in it.to_dict("records"):
            t = r["ticker"]
            m = mm.get(t) or piggy.box_metrics(px.get(t))
            df = px.get(t)
            price = snap.get(t) or (float(df["Close"].dropna().iloc[-1]) if df is not None and not df.empty else None)
            lo, hi, src = piggy.box_of(r, m)
            z = piggy.zone(price, lo, hi)
            lat = intel.latest(conn, t)
            ic = intel.summary_cells(lat[1] if lat else None)
            budget = r.get("budget_krw") or 1_000_000
            rows.append({"카테고리": r.get("category") or "기타", "티커": t, "상태": z, "현재가($)": price, "현재가(원)": None if price is None else price * fx,
                         "박스 하단($)": lo, "박스 상단($)": hi, "박스": src, "박스 위치(%)": None if None in (price, lo, hi) or hi == lo else (price - lo) / (hi - lo) * 100,
                         "상단까지(%)": None if not price or not hi else (hi / price - 1) * 100, "안정성": (m or {}).get("score"),
                         "$1 미만(일)": (m or {}).get("below1_days"), "희석": dil.get(t, ""), "체결강도(%)": ic["체결강도(%)"], "장중 희석": ic["장중 희석"],
                         "예산(원)": budget, "수량(주)": None if not price else int(budget / (price * fx)), "공시분석": fxd.get(t, ""), "메모": r.get("note") or ""})
    tb = pd.DataFrame(rows)
    p1 = prices_1y(tuple(tickers))
    with closing(db.connect()) as conn:
        qs = {t: piggy.quality(t, conn, p1.get(t), dil.get(t)) for t in tickers}
    tb.insert(3, "손익비 기준", [f"{sum(1 for q in qs[x] if q['결과'] is True)}/{len(qs[x])} " + "".join(_q_icon(q["결과"], q.get("주의", False)) for q in qs[x]) for x in tb["티커"]])
    nz = {t: piggy.near_zone(tb.set_index("티커").loc[t, "현재가($)"], piggy.launch_zones(p1.get(t))) for t in tickers}
    tb.insert(4, "발사대", ["" if not nz.get(x) else (("🎯 " if nz[x]["near"] else "") + f"${nz[x]['level']:.4f} ({nz[x]['dist_pct']:+.0f}%)") for x in tb["티커"]])
    _sf = shortflow_ui.stages(tickers, px)
    tb.insert(3, "공매도 흐름", [_sf.get(x, "") for x in tb["티커"]])
    _ps = pumpsetup_ui.labels(tickers)
    tb.insert(4, "셋업", [_ps.get(x, "") for x in tb["티커"]])
    _fr = flowread_ui.labels(tickers, px)
    tb.insert(5, "분산·털기", [_fr.get(x, "") for x in tb["티커"]])
    tb.insert(2, "토스", tosslink_ui.links(tb["티커"]))
    import rank_ui
    tb.insert(3, "종합 순위", rank_ui.column(tb["티커"]))
    import regsho as _rg
    with closing(db.connect()) as _c:
        _sho = _rg.streaks(_c)
    tb["Reg SHO"] = [_rg.label(_sho.get(x)) for x in tb["티커"]]
    tb["_o"] = tb["상태"].map(ZONE_ORDER)
    tb = tb.sort_values(["카테고리", "_o", "박스 위치(%)"], na_position="last").drop(columns="_o").reset_index(drop=True)
    cnt = tb["상태"].value_counts()
    seed = piggy.seed_krw()
    s1, s2 = st.columns([1, 3])
    new_seed = s1.number_input("총 시드(원)", 0, 10_000_000_000, int(seed or 0), step=1_000_000, key="pg_seed", help="종목당 예산이 시드의 몇 %인지 봅니다")
    if new_seed != int(seed or 0):
        piggy.set_seed_krw(new_seed)
        seed = float(new_seed)
    s2.info("💡 " + piggy.SEED_TIP)
    if seed:
        tb["시드 대비(%)"] = tb["예산(원)"] / seed * 100
        over = tb[tb["시드 대비(%)"] > 10]
        if not over.empty:
            st.warning(f"종목당 예산이 시드의 10%를 넘는 종목: {', '.join(over['티커'])} — 포모가 올 때는 시드의 10% 정도로만 움직이세요(스승님).")
    m = st.columns(5)
    m[0].metric("담은 종목", f"{len(tb)}개", help="스승님 권장 10~20개(처음 꿀팁은 20~30개)")
    m[1].metric("카테고리", f"{tb['카테고리'].nunique()}")
    m[2].metric("🟢 저점 구간", f"{int(cnt.get('🟢 저점 구간', 0))}")
    m[3].metric("🔴 고점 구간", f"{int(cnt.get('🔴 고점 구간', 0))}")
    m[4].metric("⚠️ 박스 이탈", f"{int(cnt.get('⚠️ 박스 이탈', 0))}")
    if len(tb) > 30:
        st.warning(f"{len(tb)}개를 담았습니다. 종목당 예산과 감시 부담을 생각하면 30개 이하를 권합니다.")
    cats = ["전체"] + sorted(tb["카테고리"].unique())
    cat = st.radio("카테고리", cats, horizontal=True, key="pg_cat")
    view = tb if cat == "전체" else tb[tb["카테고리"] == cat]
    num = {c: st.column_config.NumberColumn(format="%.4f") for c in ("현재가($)", "박스 하단($)", "박스 상단($)")}
    num["토스"] = tosslink_ui.COLUMN
    num.update({"현재가(원)": st.column_config.NumberColumn(format="%d"), "박스 위치(%)": st.column_config.NumberColumn(format="%.0f", help="0=하단, 100=상단"),
                "상단까지(%)": st.column_config.NumberColumn(format="%+.1f"), "안정성": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                "체결강도(%)": st.column_config.NumberColumn(format="%.0f"), "예산(원)": st.column_config.NumberColumn(format="%d"),
                "$1 미만(일)": st.column_config.NumberColumn(format="%d", help="30거래일 연속이면 나스닥 최저호가 미달 통지 대상")})
    t = picker.clickable(view, list(view["티커"]), "pg_table", hide_index=True, width="stretch", column_config=num)
    if not t:
        return
    r = it.set_index("ticker").loc[t].to_dict()
    m_ = mm.get(t) or piggy.box_metrics(px.get(t))
    lo, hi, src = piggy.box_of(r, m_)
    st.markdown(f"#### 🐷 {t}")
    tosslink_ui.button(t, key="pg")
    warn = []
    if (m_ or {}).get("recent_break"):
        warn.append("최근 10거래일 안에 박스 아래로 이탈한 적이 있습니다")
    if ((m_ or {}).get("below1_days") or 0) >= 30:
        warn.append(f"$1 미만 {m_['below1_days']}거래일 연속 — 나스닥 미달 통지·역분할 위험(🗓 일정에서 상장유지 기한 확인)")
    if _dilution().get(t) in ("ATM", "ELOC", "CB"):
        warn.append(f"희석 정황 {_dilution()[t]} — 시장가 희석 종목은 저금통 기준에 맞지 않습니다")
    for w in warn:
        st.warning(w)
    c1, c2 = st.columns([3, 2])
    with c1:
        _chart(px.get(t), lo, hi)
        if m_:
            st.caption(f"자동 박스(최근 {m_['n']}거래일, 최근 10일 제외 구간 기준): ${m_['support']:.4f} ~ ${m_['resistance']:.4f} · 폭 {m_['width_pct']:.0f}% · "
                       f"박스 안 {m_['inside_pct']:.0f}% · 추세 {m_['trend_month_pct']:+.1f}%/월 · 반등 {m_['bounces']}회 · 20일 거래대금 ${m_['dollar_vol']:,.0f}")
    with c2:
        cat_new = _category_input(f"pg_cat_{t}", r.get("category"))
        b1, b2 = st.columns(2)
        lo_in = b1.number_input("박스 하단($, 0=자동)", 0.0, 1000.0, float(r["box_low"]) if r.get("box_low") == r.get("box_low") and r.get("box_low") else 0.0,
                                step=0.0001, format="%.4f", key=f"pg_lo_{t}")
        hi_in = b2.number_input("박스 상단($, 0=자동)", 0.0, 1000.0, float(r["box_high"]) if r.get("box_high") == r.get("box_high") and r.get("box_high") else 0.0,
                                step=0.0001, format="%.4f", key=f"pg_hi_{t}")
        bud = st.number_input("종목 예산(원)", 0, 100_000_000, int(r.get("budget_krw") or 1_000_000), step=100_000, key=f"pg_bud_{t}")
        note = st.text_input("메모", r.get("note") or "", key=f"pg_note_{t}")
        s1, s2 = st.columns(2)
        if s1.button("💾 저장", key=f"pg_save_{t}"):
            piggy.update(t, category=cat_new, box_low=lo_in or None, box_high=hi_in or None, budget_krw=bud, note=note)
            st.rerun()
        if s2.button("🗑 저금통에서 빼기", key=f"pg_del_{t}"):
            piggy.remove(t)
            st.rerun()
        st.caption(f"지금 쓰는 박스: {src}. 자동 박스가 실제 흐름과 다르면 직접 입력하세요.")
    render_profit(t, r, prices_1y((t,)).get(t), dict(zip(view["티커"], view["현재가($)"])).get(t), view.set_index("티커").loc[t, "예산(원)"] if t in set(view["티커"]) else None)
    shortflow_ui.render_panel(t, px.get(t), key="pg")
    pumpsetup_ui.render_panel(t, px.get(t), key="pg")
    flowread_ui.render_panel(t, px.get(t), key="pg")
    with st.expander("📡 체결강도 · 거래정지 · 공매도 · 장중 공시"):
        intel_ui.render_ticker(t, None, key="pg")
    forensic_ui.render(t, key="pg")


# ---------------------------------------------------------------- 🔎 후보 찾기
def render_screen(fx: float) -> None:
    d, sc = piggy.latest_scan()
    c1, c2 = st.columns([1, 3])
    max_krw = c2.number_input("기준 가격(원 미만)", 100, 10000, 1000, step=100, key="ps_krw")
    st.caption(f"🤖 자동 담기: {'켜짐' if piggy.rules()['on'] else '꺼짐'} — 매일 아침 아래 기본 필터(안정성·반등·거래대금·폭 15~80%·최근 이탈 없음·희석 아님)를 통과한 종목을 "
               f"최대 {piggy.rules()['n']}개 '{piggy.AUTO_CAT}' 카테고리로 담고, 기준에서 벗어나면 뺍니다(직접 담은 종목은 안 뺌). 기준은 ⚙️ 관리 모드에서.")
    if c1.button("🔎 후보 다시 찾기", key="ps_run", help="전체 종목 가격 확인 후 기준 가격 미만 종목의 6개월 일봉으로 박스 분석(2~5분)"):
        uni = piggy.universe()
        if not uni:
            st.error("종목 목록이 없습니다. 먼저 과거 사례 수집(`python cases.py build`)을 한 번 실행해 주세요.")
        else:
            bar = st.progress(0.0, text="시작...")
            piggy.screen(uni, fx, max_krw=float(max_krw), progress=lambda p, msg: bar.progress(min(p, 1.0), text=msg))
            st.rerun()
    if sc.empty:
        st.info("아직 분석 결과가 없습니다. **🔎 후보 다시 찾기**를 누르세요(매일 아침 자동 갱신 작업에서도 돌아갑니다).")
        return
    st.caption(f"분석일 {d} · {len(sc)}종목(가격 기준 통과) · 환율 1 USD = {fx:,.0f} KRW")
    f = st.columns(5)
    min_score = f[0].slider("안정성 ≥", 0, 100, int(config.PIGGY_AUTO_SCORE), key="ps_score")
    min_b = f[1].slider("반등 횟수 ≥", 0, 6, int(config.PIGGY_AUTO_BOUNCES), key="ps_b")
    wmin, wmax = f[2].slider("박스 폭(%)", 0, 150, (15, 80), key="ps_w")
    min_dv = f[3].number_input("20일 거래대금 ≥ ($)", 0, 10_000_000, int(config.PIGGY_AUTO_DVOL), step=10_000, key="ps_dv")
    zone_only = f[4].checkbox("저점 구간만", False, key="ps_low")
    h = st.columns(2)
    min_spk = h[0].slider("⑤ 간간이 발작: 6개월 +20% 이상 횟수 ≥", 0, 10, 0, key="ps_spk", help="스승님 꿀팁(손익비): 간간이 발작이 일어나는 종목이면 더 좋음")
    need_big = h[1].checkbox("③ 과거 급등 이력(+30% 이상) 있는 종목만", False, key="ps_big")
    g = st.columns(3)
    no_break = g[0].checkbox("최근 이탈 제외", True, key="ps_nb")
    no_dil = g[1].checkbox("희석(ATM·ELOC·CB) 제외", True, key="ps_nd")
    hide_have = g[2].checkbox("이미 담은 종목 숨기기", False, key="ps_hh")
    dil = _dilution()
    have = set(piggy.tickers())
    v = sc[(sc["price"] * fx < max_krw) & (sc["score"] >= min_score) & (sc["bounces"] >= min_b) & (sc["width_pct"].between(wmin, wmax)) & (sc["dollar_vol"] >= min_dv)]
    if no_break:
        v = v[~v["recent_break"].fillna(False).astype(bool)]
    if no_dil:
        v = v[~v["ticker"].map(lambda x: dil.get(x) in ("ATM", "ELOC", "CB"))]
    if zone_only:
        v = v[v["pos"] <= piggy.BAND]
    if hide_have:
        v = v[~v["ticker"].isin(have)]
    if "spikes20" in v:
        v = v[v["spikes20"].fillna(0) >= min_spk]
        if need_big:
            v = v[v["spikes30"].fillna(0) >= 1]
    v = v.sort_values("score", ascending=False).reset_index(drop=True)
    if v.empty:
        st.info("조건에 맞는 종목이 없습니다. 필터를 풀어 보세요.")
        return
    show = pd.DataFrame({"티커": v["ticker"], "안정성": v["score"], "현재가($)": v["price"], "현재가(원)": v["price"] * fx, "박스 하단($)": v["support"],
                         "박스 상단($)": v["resistance"], "박스 폭(%)": v["width_pct"], "박스 위치(%)": v["pos"] * 100, "상단까지(%)": v["upside_pct"],
                         "반등": v["bounces"], "박스 안(%)": v["inside_pct"], "추세(%/월)": v["trend_month_pct"], "$1 미만(일)": v["below1_days"],
                         "거래대금($)": v["dollar_vol"], "발작(6개월)": v["spikes20"] if "spikes20" in v else None, "급등 +30%(6개월)": v["spikes30"] if "spikes30" in v else None,
                         "희석": v["ticker"].map(lambda x: dil.get(x, "미확인")), "저금통": v["ticker"].map(lambda x: "🐷" if x in have else "")})
    cfg = {"안정성": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"), "현재가(원)": st.column_config.NumberColumn(format="%d"),
           "거래대금($)": st.column_config.NumberColumn(format="%d")}
    cfg.update({k: st.column_config.NumberColumn(format="%.4f") for k in ("현재가($)", "박스 하단($)", "박스 상단($)")})
    cfg.update({k: st.column_config.NumberColumn(format="%.0f") for k in ("박스 폭(%)", "박스 위치(%)", "박스 안(%)")})
    cfg.update({"상단까지(%)": st.column_config.NumberColumn(format="%+.1f"), "추세(%/월)": st.column_config.NumberColumn(format="%+.1f"),
                "희석": st.column_config.TextColumn(help="SEC 희석 판정. '미확인'은 아직 검사 전 — 담으면 스캐너가 우선 검사합니다")})
    st.caption(f"{len(v)}종목 · 안정성 = 박스 안 체류 40% + 평평함 25% + 반등 20% + 적당한 폭 15% (최근 이탈·잦은 이탈은 절반). 과거 모양일 뿐 앞으로를 보장하지 않습니다.")
    show.insert(1, "토스", tosslink_ui.links(show["티커"]))
    cfg["토스"] = tosslink_ui.COLUMN
    t = picker.clickable(show, list(show["티커"]), "ps_table", hide_index=True, width="stretch", column_config=cfg)
    if not t:
        return
    row = v[v["ticker"] == t].iloc[0]
    st.markdown(f"#### {t}")
    c1, c2 = st.columns([3, 2])
    with c1:
        _chart(watch_ui.prices((t,)).get(t), row["support"], row["resistance"])
    with c2:
        if t in have:
            st.success("이미 저금통에 담겨 있습니다.")
        else:
            cat = _category_input(f"ps_cat_{t}")
            if st.button(f"🐷 {t} 저금통에 담기", key=f"ps_add_{t}"):
                piggy.add(t, cat)
                st.rerun()
        if dil.get(t) in (None, "UNKNOWN"):
            st.caption("희석 미확인: 담으면 스캐너가 우선 분석하면서 SEC 희석 검사도 합니다. 🧾 공시분석 자동 스캔 요청도 해 두세요.")


# ---------------------------------------------------------------- 📒 매매 기록
def render_trades(fx: float) -> None:
    pumpsetup_ui.fomo_card()
    st.caption("실제로 사고판 기록을 적으면 승률·평균 수익률·손익을 계산합니다. 매도가가 비어 있으면 보유 중으로 봅니다. 수수료는 왕복 % (예: 0.5).")
    df = piggy.trades()
    ed = st.data_editor(df, key="pt_edit", num_rows="dynamic", hide_index=True, width="stretch", column_config={
        "id": None, "date": st.column_config.TextColumn("날짜(YYYY-MM-DD)"), "ticker": st.column_config.TextColumn("티커"),
        "buy": st.column_config.NumberColumn("매수가($)", format="%.4f"), "sell": st.column_config.NumberColumn("매도가($)", format="%.4f"),
        "qty": st.column_config.NumberColumn("수량(주)", format="%d"), "fee_pct": st.column_config.NumberColumn("수수료(왕복 %)", format="%.2f"),
        "note": st.column_config.TextColumn("메모", width="large")})
    if st.button("💾 매매 기록 저장", key="pt_save"):
        piggy.save_trades(ed)
        st.rerun()
    s = piggy.trade_stats(df, fx)
    if not s["n"]:
        st.info(f"청산된 거래가 아직 없습니다(보유 중 {s['open']}건).")
        return
    m = st.columns(6)
    m[0].metric("청산 거래", f"{s['n']}", help=f"보유 중 {s['open']}건")
    m[1].metric("승률", f"{s['win_rate']:.0f}%")
    m[2].metric("평균 수익률", f"{s['avg_ret']:+.1f}%")
    m[3].metric("중앙값", f"{s['median_ret']:+.1f}%")
    m[4].metric("최고 / 최저", f"{s['best']:+.0f}% / {s['worst']:+.0f}%")
    m[5].metric("총 손익", f"{s['pnl_krw']:+,.0f}원")
    if s["n"] < 20:
        st.caption(f"청산 {s['n']}건 — 20건 이상 쌓여야 전략이 실제로 되는지 판단할 수 있어요. 손실 거래도 빠짐없이 적어 주세요.")


def render_profit(t: str, r: dict, df1y, price, budget) -> None:
    """스승님 꿀팁: 손익비 5가지 기준 · 발사대(과거 횡보 후 튄 자리) · 종배 이력 · 준비된 호재."""
    import watch
    st.markdown(f"##### 💰 {t} 손익비 기준 (스승님 꿀팁)")
    with closing(db.connect()) as conn:
        q = piggy.quality(t, conn, df1y, _dilution().get(t))
        cb = piggy.close_bounce(conn, t)
    st.dataframe(pd.DataFrame([{"기준": x["기준"], "결과": _q_label(x), "값": x["값"]} for x in q]),
                 hide_index=True, width="stretch")
    if any(x["결과"] is None and x["기준"].startswith("②") for x in q):
        st.caption("② 펀더멘탈은 종목 리포트의 런웨이로 봅니다. 🗂 종목 리포트 탭에서 이 종목 리포트를 만들어 주세요.")
    zones = piggy.launch_zones(df1y)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🎯 발사대 — 과거에 횡보하다가 튄 자리**")
        if zones:
            nz = piggy.near_zone(price, zones)
            st.dataframe(pd.DataFrame([{"자리($)": z["level"], "튄 날": ", ".join(z["dates"][-3:]), "횟수": len(z["dates"]), "최대 급등(%)": z["max_spike"],
                                        "현재가 거리(%)": None if not price else (price / z["level"] - 1) * 100} for z in zones]), hide_index=True, width="stretch",
                         column_config={"자리($)": st.column_config.NumberColumn(format="%.4f"), "최대 급등(%)": st.column_config.NumberColumn(format="%.0f"),
                                        "현재가 거리(%)": st.column_config.NumberColumn(format="%+.0f")})
            if nz and nz["near"]:
                st.success(f"지금 가격이 발사대 ${nz['level']:.4f} 근처예요({nz['dist_pct']:+.0f}%). 스스로 정한 저점 진입 패턴과 맞는지 확인하세요.")
            st.caption("1년 일봉에서 고가가 전일 종가 +30% 이상인 날, 직전 10거래일 종가 중앙값을 '자리'로 봅니다(±10%는 합침).")
        else:
            st.caption("1년 안에 +30% 이상 튄 날이 없어 발사대 자리가 없습니다.")
    with c2:
        st.markdown("**🌙 종배 이력 — 급락 다음날 시가(장 마감 후 튀는지)**")
        if cb:
            st.metric("다음날 갭 상승 비율", f"{cb['gap_up_rate']:.0f}%", help=f"과거 -10% 이하 급락 {cb['n']}건 기준(과거 사례 DB)")
            st.caption(f"다음날 시가 평균 {cb['open_avg']:+.1f}% · +10% 이상 갭 {cb['open_ge10_rate']:.0f}% · 다음날 고가 평균 "
                       + ("-" if cb["high_avg"] is None else f"{cb['high_avg']:+.1f}%") + " — 공모·시장가 희석으로 파괴된 때는 장 마감 후에도 눌리기 쉬우니 희석 상태를 함께 보세요.")
        else:
            st.caption("과거 사례 DB에 이 종목의 -10% 이하 급락 기록이 없습니다.")
    st.markdown("**📅 준비된 호재**")
    h1, h2, h3 = st.columns([3, 1, 1])
    cat = h1.text_input("호재 내용", r.get("catalyst") or "", key=f"pg_cat_txt_{t}", placeholder="예: FDA 결정, 임상 결과, 계약, 실적 발표")
    cd = h2.text_input("날짜(YYYY-MM-DD)", r.get("catalyst_date") or "", key=f"pg_cat_dt_{t}")
    h3.write("")
    if h3.button("💾 호재 저장", key=f"pg_cat_save_{t}"):
        piggy.update(t, catalyst=cat.strip(), catalyst_date=cd.strip() or None)
        if cd.strip() and cat.strip():
            try:
                date.fromisoformat(cd.strip())
                watch.add_event(t, cd.strip(), "기타", f"호재: {cat.strip()}", origin="수동")
            except ValueError:
                st.warning("날짜 형식이 YYYY-MM-DD 가 아니어서 🗓 일정에는 넣지 않았습니다.")
        st.rerun()
    st.caption("AI에 물어볼 때 쓰세요(오른쪽 위 복사 버튼):")
    st.code(f"{t}(나스닥)의 앞으로 예정된 호재와 날짜를 SEC 공시·보도자료 기준으로 찾아 줘. 임상·FDA 일정, 실적 발표, 계약·파트너십, 제품 출시, "
            f"주총 안건, 지수 편입 등을 포함하고, 각 항목에 출처 링크와 확실한 정도(확정/예상/루머)를 표시해 줘. 최근 희석(공모·ATM·워런트) 계획도 같이 알려 줘.", language=None)
    seed = piggy.seed_krw()
    if seed and budget:
        pct = budget / seed * 100
        (st.warning if pct > 10 else st.caption)(f"이 종목 예산은 시드의 {pct:.1f}%입니다." + (" 포모가 올 때는 10% 정도로만 움직이세요." if pct > 10 else ""))
