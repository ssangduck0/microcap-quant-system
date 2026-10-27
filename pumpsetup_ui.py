"""🕵️ 세력·셋업 탭과 종목 상세 패널 — 스승님 꿀팁(세력 1집단·작전 셋업·흔적·병합+수권)."""
import json
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st

import config
import db
import intel
import pick as picker
import pumpsetup as ps

VERDICT_BOX = {"강한 셋업": "success", "셋업 일부": "info", "셋업 약함": "caption", "주의 — 악재·상대방 혼재": "warning", "피함 — 시장가 희석(ATM·ELOC)": "error"}


def fomo_card() -> None:
    st.info("💡 " + ps.FOMO_CARD)


def tip_cards() -> None:
    for title, text in ps.TIPS.items():
        with st.expander("📜 " + title):
            st.text(text)
    st.caption(ps.CAVEAT)


def label(data: dict | None) -> str:
    if not data:
        return ""
    if "error" in data:
        return "확인 불가"
    return f"{data['verdict']} (+{data['plus']}/−{data['minus']})"


def labels(tickers: list[str]) -> dict:
    with closing(db.connect()) as conn:
        return {t: label((ps.cached(conn, t) or (None, None))[1]) for t in tickers}


def run(ticker: str, df: pd.DataFrame | None = None) -> dict:
    """대시보드에서 바로 분석(토스는 쓰지 않음)."""
    import sec
    t = ticker.strip().upper()
    snap = db.read_df("SELECT float_shares, price, dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
    s0 = snap.iloc[0] if not snap.empty else None
    with closing(db.connect()) as conn:
        lat = intel.latest(conn, t)
        short = (lat[1] or {}).get("short") if lat else None
        dark = ps.dark_stats(conn, t, df)
        res = ps.analyze(sec.SecClient(config.SEC_USER_AGENT), conn, t, shares_out=None if s0 is None or pd.isna(s0["float_shares"]) else float(s0["float_shares"]),
                         dark=dark, short=short, dilution_status=None if s0 is None else s0["dilution_status"])
        price = None if s0 is None or pd.isna(s0["price"]) else float(s0["price"])
        if price is None and df is not None and not df.empty:
            price = float(df["Close"].dropna().iloc[-1])
        ps.save(conn, t, res, price)
    return res


def render_panel(ticker: str, df: pd.DataFrame | None = None, key: str = "ps") -> None:
    st.markdown(f"##### 🕵️ {ticker} 세력·셋업 (스승님 꿀팁)")
    with closing(db.connect()) as conn:
        got = ps.cached(conn, ticker)
    c1, c2 = st.columns([4, 1])
    if c2.button("🔎 셋업 분석", key=f"{key}_setup_{ticker}", help="최근 1년 SEC 공시(주총 서류·6-K·8-K·F-1/S-1·424B)와 공매도 데이터로 판정. 30초~1분"):
        if "@" not in config.SEC_USER_AGENT:
            st.error("SEC_USER_AGENT 가 .env 에 설정되어 있지 않습니다.")
        else:
            with st.spinner(f"{ticker} 공시를 읽는 중..."):
                run(ticker, df)
            st.rerun()
    if not got:
        c1.caption("아직 분석 전입니다. 워치리스트·저금통 종목은 스캐너가 하루 한 번 자동으로 분석합니다.")
        tip_cards()
        return
    at, data = got
    c1.caption(f"분석 {pd.to_datetime(at, utc=True).tz_convert('Asia/Seoul'):%m-%d %H:%M} KST")
    if "error" in data:
        st.caption(data["error"])
        return
    getattr(st, VERDICT_BOX.get(data["verdict"], "info"))(f"**{data['verdict']}** · 펌핑 셋업 신호 +{data['plus']} · 피할 신호 −{data['minus']}")
    rows = [{"구분": s["구분"], "신호": s["신호"], "결과": "➖" if s["결과"] is None else ("✅" if s["결과"] else "❌"), "값": s.get("값") or "", "근거": s.get("근거")}
            for s in data["signals"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={"근거": st.column_config.LinkColumn("원문", display_text="열기")})
    tip_cards()


def render_tab() -> None:
    import flowread_ui
    st.subheader("🕵️ 세력·셋업 — 스승님 꿀팁")
    fomo_card()
    a, b = st.tabs(["🕵️ 셋업 레이더", "📈 분산·털기 (더 오를까 내릴까)"])
    with a:
        render_radar()
    with b:
        flowread_ui.render_section()


def render_radar() -> None:
    import piggy
    import watch
    import watch_ui
    c1, c2, c3 = st.columns([2, 1, 2])
    t_in = c1.text_input("종목 분석", placeholder="티커 입력 후 분석", key="ps_in").strip().upper()
    if c2.button("🔎 분석", key="ps_go") and t_in:
        with st.spinner(f"{t_in} 공시를 읽는 중..."):
            run(t_in, watch_ui.prices((t_in,)).get(t_in))
        st.rerun()
    tks = list(dict.fromkeys(watch.scanner_priority() + piggy.tickers()))
    import access
    if access.can_edit() and c3.button(f"⭐·🐷 전체 분석 ({len(tks)})", key="ps_all", disabled=not tks):  # 방문객에게는 숨김
        px = watch_ui.prices(tuple(tks))
        bar = st.progress(0.0, text="분석 중...")
        for i, t in enumerate(tks):
            bar.progress((i + 1) / len(tks), text=f"{t} ({i + 1}/{len(tks)})")
            run(t, px.get(t))
        st.rerun()
    df = ps.all_cached()
    if df.empty:
        st.info("아직 분석한 종목이 없습니다. 위에서 분석하거나, 스캐너가 워치리스트·저금통 종목을 하루 한 번 자동 분석합니다.")
        tip_cards()
        return
    recs = []
    for r in df.itertuples():
        d = json.loads(r.data)
        if "error" in d:
            continue
        recs.append({"티커": r.ticker, "판정": d["verdict"], "+신호": d["plus"], "−신호": d["minus"], "설립지": d.get("incorporation") or "",
                     "조달 상대방": ", ".join(d.get("counterparties") or []), "첫 분석일": r.first_date, "첫 분석 가격": r.first_price})
    tb = pd.DataFrame(recs)
    if tb.empty:
        st.info("분석 가능한 결과가 없습니다.")
        return
    px = watch_ui.prices(tuple(tb["티커"]))
    after = []
    for _, r in tb.iterrows():
        p, p0 = px.get(r["티커"]), r["첫 분석 가격"]
        if p is None or p.empty or not p0 or pd.isna(p0):
            after.append((None, None))
            continue
        d = p.copy()
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        a = d[d.index > pd.Timestamp(r["첫 분석일"])].head(20)
        after.append((None if a.empty else float((a["High"].max() / p0 - 1) * 100), int(len(a))))
    tb["이후 20일 최고(%)"] = [a for a, _ in after]
    tb["경과(거래일)"] = [n for _, n in after]
    tb["이후 결과"] = ["아직 없음" if a is None else f"{a:+.0f}%" for a, _ in after]  # 표에 'None' 글자 대신
    tb = tb.sort_values(["−신호", "+신호"], ascending=[True, False]).reset_index(drop=True)
    st.markdown("**셋업 레이더** — +신호가 많고 −신호가 없는 종목이 위로 옵니다. 행을 누르면 아래에 근거가 열립니다.")
    import tosslink_ui
    tb.insert(1, "토스", tosslink_ui.links(tb["티커"]))
    disp = tb.drop(columns=["이후 20일 최고(%)"]).assign(**{"경과(거래일)": [("-" if a is None else str(n)) for a, n in after]})  # 표에 'None' 대신 '아직 없음'·'-'
    t = picker.clickable(disp, list(tb["티커"]), "ps_radar", hide_index=True, width="stretch", column_config={"토스": tosslink_ui.COLUMN,
        "첫 분석 가격": st.column_config.NumberColumn(format="%.4f"), "이후 결과": st.column_config.TextColumn("이후 20일 최고(%)",
        help="처음 분석한 날 뒤 최대 20거래일 동안의 최고가(첫 분석 가격 대비). '곧 펌핑' 꿀팁 검증용 · '아직 없음' = 분석 뒤 거래일이 아직 없음")})
    v = tb.dropna(subset=["이후 20일 최고(%)"])
    if not v.empty:
        v = v.assign(구간=pd.cut(v["+신호"], [-1, 1, 3, 99], labels=["+0~1", "+2~3", "+4 이상"]))
        g = v.groupby("구간", observed=True).agg(종목=("티커", "size"), 이후_20일_최고_중앙값=("이후 20일 최고(%)", "median"),
                                                   _50퍼센트_이상_비율=("이후 20일 최고(%)", lambda x: (x >= 50).mean() * 100)).reset_index()
        st.markdown("**검증: 셋업 신호가 많을수록 이후 크게 올랐나?** (꿀팁이 맞다면 '+4 이상' 구간의 숫자가 가장 커야 합니다)")
        st.dataframe(g.rename(columns={"_50퍼센트_이상_비율": "+50% 이상 도달 비율(%)", "이후_20일_최고_중앙값": "이후 20일 최고 중앙값(%)"}), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.0f") for c in ("이후 20일 최고 중앙값(%)", "+50% 이상 도달 비율(%)")})
        if len(v) < 30:
            st.caption(f"결과가 있는 종목 {len(v)}개 — 30개 이상 쌓여야 판단할 수 있어요. 셋업 종목은 펌핑 뒤 급락도 빠르니 최고가만이 아니라 흐름을 함께 보세요.")
    if t:
        render_panel(t, px.get(t), key="ps_tab")
