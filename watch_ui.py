"""⭐ 워치리스트(물량 장부·런웨이·일정) · 🗓 일정 탭 화면. (📰 오늘 브리핑 화면은 2026-10-26 메뉴 정리로 삭제 — 홈과 같은 내용)"""
from contextlib import closing
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import config
import db
import forensic
import forensic_ui
import pick as picker
import flowread_ui
import pumpsetup_ui
import tosslink_ui
import shortflow_ui
import intel
import intel_ui
import market
import watch
from scoring import baby_shelf

ET = ZoneInfo("America/New_York")
LIST_ICON = {"관심": "⭐ 관심", "보유": "💼 보유", "그레이": "▫️ 그레이", "블랙": "⛔ 블랙"}
EVENT_KINDS = ["주총", "임시주총", "상장유지 기한", "상장유지 미달", "역분할 시행", "워런트 만기", "락업 해제(추정)", "희석 임박", "발행", "실적 발표", "기타"]


# ---------------------------------------------------------------- 데이터 읽기
@st.cache_data(ttl=600, show_spinner=False)
def prices(tickers: tuple) -> dict:
    """워치리스트 종목 일봉(Yahoo, 6개월). 10분 캐시."""
    if not tickers:
        return {}
    try:
        return market.download_daily(list(tickers), period="6mo")
    except Exception:  # noqa: BLE001
        return {}


def latest_snapshots(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    q = f"SELECT * FROM daily_snapshots WHERE ticker IN ({','.join('?' * len(tickers))}) ORDER BY date DESC"
    return db.read_df(q, tuple(tickers)).drop_duplicates("ticker").set_index("ticker")


def dilution_map() -> dict:
    try:
        return dict(db.read_df("SELECT ticker, status FROM dilution").values)
    except Exception:  # noqa: BLE001
        return {}


def runway_of(ticker: str) -> dict | None:
    rep = db.get_report(ticker)
    return (rep or {}).get("runway") if rep else None


def sec_client():
    import sec
    if "@" not in config.SEC_USER_AGENT:
        st.error("SEC_USER_AGENT 가 .env 에 설정되어 있지 않습니다.")
        return None
    return sec.SecClient(config.SEC_USER_AGENT)


def _today_et() -> date:
    return datetime.now(ET).date()


def _px_stats(df: pd.DataFrame | None, added: float | None) -> dict:
    if df is None or df.empty:
        return {}
    c = df["Close"].dropna()
    if c.empty:
        return {}
    price = float(c.iloc[-1])
    out = {"price": price, "date": c.index[-1].strftime("%Y-%m-%d")}
    if len(c) >= 2 and c.iloc[-2] > 0:
        out["chg"] = (price / float(c.iloc[-2]) - 1) * 100
    hi = float(df["High"].tail(20).max()) if "High" in df else None
    if hi:
        out["dd20"] = (price / hi - 1) * 100
    if added:
        out["since"] = (price / added - 1) * 100
    out.update(watch.dollar_streak(df))
    return out


# ---------------------------------------------------------------- 공용: 워치리스트 추가 버튼
def add_button(ticker: str, price: float | None = None, key: str = "wl") -> None:
    import access
    if access.is_guest():  # 👥 방문객: 내 워치리스트를 보이거나 바꾸지 않음
        return
    lm = watch.lists_map()
    if ticker in lm:
        st.caption(f"워치리스트: **{LIST_ICON.get(lm[ticker], lm[ticker])}** (⭐ 워치리스트 탭에서 관리)")
        return
    c1, c2 = st.columns([1, 3])
    lst = c1.selectbox("리스트", watch.LISTS, key=f"{key}_list_{ticker}", label_visibility="collapsed")
    if c2.button(f"⭐ {ticker} 워치리스트에 추가", key=f"{key}_add_{ticker}"):
        watch.add(ticker, lst, price)
        st.rerun()


# ---------------------------------------------------------------- ⭐ 워치리스트
def render_watchlist() -> None:
    st.subheader("⭐ 워치리스트")
    forensic_ui.render_cowork_setup()
    st.caption("관심·보유·그레이(후순위)·블랙(제외) 종목. 블랙을 뺀 종목은 스캐너가 **항상 우선 분석**합니다. 가격은 Yahoo 일봉(10분 캐시), "
               "희석·체결강도·거래정지·공매도는 스캐너 공통 데이터, 물량·일정은 공시에서 찾은 후보를 직접 확정한 값입니다.")
    with st.form("wl_add_form", clear_on_submit=True):
        a1, a2, a3, a4 = st.columns([2, 1, 4, 1])
        t_new = a1.text_input("티커", placeholder="예: JBDI")
        l_new = a2.selectbox("리스트", watch.LISTS)
        n_new = a3.text_input("메모", placeholder="왜 보는지 한 줄")
        a4.write("")
        if a4.form_submit_button("➕ 추가", width="stretch") and t_new.strip():
            t = t_new.strip().upper()
            st_px = _px_stats(prices((t,)).get(t), None)
            watch.add(t, l_new, st_px.get("price"), n_new)
            st.rerun()
    items = watch.all_items()
    if items.empty:
        st.info("워치리스트가 비어 있습니다. 위에서 티커를 추가하거나, 📊 종목 상세·🗂 리포트의 **⭐ 워치리스트에 추가** 버튼을 쓰세요.")
        return
    show_lists = st.multiselect("리스트", watch.LISTS, default=["보유", "관심", "그레이"], key="wl_lists")
    items = items[items["list"].isin(show_lists)]
    if items.empty:
        st.info("선택한 리스트에 종목이 없습니다.")
        return
    tickers = list(items["ticker"])
    px = prices(tuple(tickers))
    snap = latest_snapshots(tickers)
    dil = dilution_map()
    today = _today_et()
    ev = watch.events_df(tickers, start=today.isoformat())
    rows = []
    with closing(db.connect()) as conn:
        intel.ensure_table(conn)
        for r in items.itertuples():
            t = r.ticker
            s = _px_stats(px.get(t), r.added_price)
            lat = intel.latest(conn, t)
            ic = intel.summary_cells(lat[1] if lat else None)
            oh = watch.overhang_summary(watch.overhang_rows(t).to_dict("records"), s.get("price"))
            rw = runway_of(t) or {}
            nxt = ev[ev["ticker"] == t].head(1)
            sn = snap.loc[t] if t in snap.index else None
            rows.append({"리스트": LIST_ICON.get(r.list, r.list), "티커": t, "현재가($)": s.get("price"), "오늘(%)": s.get("chg"), "추가 후(%)": s.get("since"),
                         "20일 고점 대비(%)": s.get("dd20"), "$1 연속": (f"위 {s['above']}일" if s.get("above") else (f"아래 {s['below']}일" if s.get("below") else "")),
                         "승률 점수": None if sn is None else sn.get("win_score"), "희석": dil.get(t, ""), "체결강도(%)": ic["체결강도(%)"], "거래정지": ic["거래정지"],
                         "장중 희석": ic["장중 희석"], "출회 가능(M주)": oh["below_m"], "위 대역(M주)": oh["above_m"],
                         "바로 위 물량대": "" if oh["next_price"] is None else f"${oh['next_price']:g} (+{oh['next_dist_pct']:.0f}%)",
                         "확인 필요": oh["pending"] or None, "런웨이(개월)": rw.get("runway_months"),
                         "다음 일정": "" if nxt.empty else f"{nxt.iloc[0]['date'][5:]} {nxt.iloc[0]['kind']}", "메모": r.note or ""})
    tb = pd.DataFrame(rows)
    _fx = forensic.latest_dates()
    tb.insert(2, "공시분석", [_fx.get(x, "") for x in tb["티커"]])
    tb.insert(2, "토스", tosslink_ui.links(tb["티커"]))
    import regsho as _rg
    with closing(db.connect()) as _c:
        _sho = _rg.streaks(_c)
    tb["Reg SHO"] = [_rg.label(_sho.get(x)) for x in tb["티커"]]
    _sf = shortflow_ui.stages(list(tb["티커"]), px)
    tb.insert(3, "공매도 흐름", [_sf.get(x, "") for x in tb["티커"]])
    _ps = pumpsetup_ui.labels(list(tb["티커"]))
    tb.insert(4, "셋업", [_ps.get(x, "") for x in tb["티커"]])
    _fr = flowread_ui.labels(list(tb["티커"]), px)
    tb.insert(5, "분산·털기", [_fr.get(x, "") for x in tb["티커"]])
    clicked = picker.clickable(tb, list(tb["티커"]), "wl_table", hide_index=True, width="stretch", column_config={"토스": tosslink_ui.COLUMN,
        "현재가($)": st.column_config.NumberColumn(format="%.4f"), "오늘(%)": st.column_config.NumberColumn(format="%+.1f"),
        "추가 후(%)": st.column_config.NumberColumn(format="%+.1f", help="워치리스트에 넣은 날 가격 대비"),
        "20일 고점 대비(%)": st.column_config.NumberColumn(format="%.1f"),
        "$1 연속": st.column_config.TextColumn(help="종가 ≥ $1 연속 일수(나스닥 회복 요건 10거래일) / 종가 < $1 연속 일수(30거래일이면 미달 통지 대상)"),
        "승률 점수": st.column_config.NumberColumn(format="%.0f"), "체결강도(%)": st.column_config.NumberColumn(format="%.0f"),
        "출회 가능(M주)": st.column_config.NumberColumn(format="%.2f", help="물량 장부의 '활성' 중 행사가·전환가가 현재가 이하 — 지금 행사·매도 가능"),
        "위 대역(M주)": st.column_config.NumberColumn(format="%.2f", help="'활성' 중 현재가보다 위 — 그 가격까지 오르면 나올 물량"),
        "확인 필요": st.column_config.NumberColumn(format="%d", help="공시에서 자동으로 찾은 후보 중 아직 확정하지 않은 건수"),
        "런웨이(개월)": st.column_config.NumberColumn(format="%.1f", help="종목 리포트(XBRL) 기준. 리포트가 없으면 비어 있음")})

    st.markdown("#### 🔎 종목 상세")
    t = clicked
    st.markdown(f"##### {t}")
    tosslink_ui.button(t, key="wl")
    it = items.set_index("ticker").loc[t]
    s = _px_stats(px.get(t), it["added_price"])
    c1, c2, c3 = st.columns([1, 3, 1])
    new_list = c1.selectbox("리스트", watch.LISTS, index=watch.LISTS.index(it["list"]), key=f"wl_l_{t}")
    if new_list != it["list"]:
        watch.update(t, list=new_list)
        st.rerun()
    nk = f"wl_note_{t}"
    if nk not in st.session_state:
        st.session_state[nk] = it["note"] or ""
    c2.text_input("메모 (입력창 밖을 클릭하면 저장)", key=nk, on_change=lambda: watch.update(t, note=st.session_state[nk]))
    c3.write("")
    if c3.button("🗑 워치리스트에서 빼기", key=f"wl_del_{t}"):
        watch.remove(t)
        st.rerun()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("현재가", "-" if s.get("price") is None else f"${s['price']:.4f}", None if s.get("chg") is None else f"{s['chg']:+.1f}% (오늘)")
    m2.metric("추가 후", "-" if s.get("since") is None else f"{s['since']:+.1f}%", help=f"추가가 ${it['added_price']}" if it["added_price"] else "추가가 없음")
    m3.metric("$1 연속", "-" if s.get("above") is None else (f"위 {s['above']}일" if s["above"] else f"아래 {s['below']}일"),
              help="나스닥: 역분할·미달 통지 후 종가 $1 이상 10거래일 연속이면 회복, $1 미만 30거래일 연속이면 미달 통지")
    rw = runway_of(t)
    m4.metric("런웨이", "-" if not rw or rw.get("runway_months") is None else f"{rw['runway_months']:.1f}개월",
              help=None if not rw else f"현금 ${(rw.get('cash') or 0) / 1e6:,.1f}M ({rw.get('cash_asof', '')}) · 월 소진 ${(rw.get('monthly_burn') or 0) / 1e6:,.2f}M")
    sn = latest_snapshots([t])
    fs = None if sn.empty or pd.isna(sn.iloc[0].get("float_shares")) else float(sn.iloc[0]["float_shares"])
    bs = baby_shelf(fs, s.get("price"))
    m5.metric("Baby Shelf", "-" if not bs else ("대상" if bs["is_baby_shelf"] else "비대상"),
              None if not bs or not bs["is_baby_shelf"] else f"12개월 상한 ≈ ${bs['cap'] / 1e6:,.1f}M", delta_color="off",
              help="공개유통시가총액 < $75M 이면 S-3 1차 발행이 12개월간 그 1/3 로 제한(근사)")
    if not rw:
        st.caption("런웨이·조달 이력은 종목 리포트에서 가져옵니다. 🗂 종목 리포트 탭에서 이 종목의 **리포트 생성/갱신**을 눌러 주세요.")

    # ---- 물량 장부
    st.markdown("##### 🧮 희석 물량 장부")
    oh_df = watch.overhang_rows(t)
    oh = watch.overhang_summary(oh_df.to_dict("records"), s.get("price"))
    o1, o2, o3, o4 = st.columns(4)
    o1.metric("지금 출회 가능", "-" if oh["below_m"] is None else f"{oh['below_m']:.2f}M주", help="'활성' 중 행사가·전환가 ≤ 현재가")
    o2.metric("위 대역", "-" if oh["above_m"] is None else f"{oh['above_m']:.2f}M주", help="'활성' 중 현재가보다 위")
    o3.metric("바로 위 물량대", "-" if oh["next_price"] is None else f"${oh['next_price']:g}", None if oh["next_dist_pct"] is None else f"+{oh['next_dist_pct']:.0f}% ({oh['next_kind']})", delta_color="off")
    o4.metric("잠김 / 확인 필요", f"{oh['locked_m']:.2f}M주 / {oh['pending']}건")
    if oh["no_price"]:
        st.caption("가격 없는 활성 물량(시장가로 계속 나올 수 있음): " + ", ".join(oh["no_price"]))
    b1, b2 = st.columns([1, 3])
    if b1.button("🔎 공시에서 후보 찾기", key=f"wl_scan_{t}", help="최근 1년 공시(8-K·424B·S-1/S-3·주총 서류·최근 분기보고서)에서 워런트·전환사채·ATM·ELOC·공모 물량과 일정을 찾습니다"):
        cl = sec_client()
        if cl:
            with st.spinner(f"{t} 공시를 읽는 중... (30초~1분)"):
                res = watch.scan_ticker(cl, t)
            if "error" in res:
                st.error(res["error"])
            else:
                st.success(f"공시 {res['docs']}건 확인 — 새 물량 후보 {res['new_overhang']}건, 새 일정 {res['new_events']}건" + (f" (읽기 실패 {res['errors']}건)" if res["errors"] else ""))
    b2.caption("자동 후보는 **키워드 추출이라 틀릴 수 있어요.** 원문 링크를 열어 확인한 뒤 상태를 **활성 / 잠김 / 소멸**로 바꾸고 저장하세요. "
               "행을 추가하거나 지울 수도 있습니다(수량은 백만 주, 가격은 달러).")
    edited = st.data_editor(
        oh_df, key=f"wl_oh_{t}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={"id": None, "kind": st.column_config.SelectboxColumn("종류", options=watch.KINDS, required=True),
                       "qty_m": st.column_config.NumberColumn("수량(M주)", format="%.4f"), "price": st.column_config.NumberColumn("행사가·전환가($)", format="%.4f"),
                       "expiry": st.column_config.TextColumn("만기(YYYY-MM-DD)"), "status": st.column_config.SelectboxColumn("상태", options=watch.STATUSES, required=True),
                       "note": st.column_config.TextColumn("메모·원문 일부", width="large"), "origin": st.column_config.TextColumn("구분", disabled=True),
                       "filed": st.column_config.TextColumn("공시일", disabled=True), "source": st.column_config.LinkColumn("원문", display_text="열기", disabled=True)})
    if st.button("💾 물량 장부 저장", key=f"wl_oh_save_{t}"):
        watch.save_overhang_edits(t, edited)
        st.success("저장했습니다.")
        st.rerun()

    # ---- 일정
    import timeline_ui
    timeline_ui.render(t, key="wl")
    st.markdown("##### 🗓 이 종목 일정")
    tev = watch.events_df([t], start=(_today_et() - timedelta(days=30)).isoformat())
    _events_table(tev, key=f"wl_ev_{t}")
    _event_form(t, key=f"wl_evf_{t}")

    shortflow_ui.render_panel(t, px.get(t), key="wl")
    pumpsetup_ui.render_panel(t, px.get(t), key="wl")
    flowread_ui.render_panel(t, px.get(t), key="wl")
    with st.expander("📡 체결강도 · 거래정지 · 공매도 · 장중 공시", expanded=False):
        intel_ui.render_ticker(t, None, key="wl")
    forensic_ui.render(t, key="wl")


# ---------------------------------------------------------------- 🗓 일정
def _dday(d: str, today: date) -> str:
    dd = date.fromisoformat(d)
    if dd < today:
        return f"지남 {(today - dd).days}일 — 결과 확인"
    n = watch.trading_days_between(today, dd)
    return "오늘" if dd == today else f"D-{(dd - today).days} ({n}거래일)"


def _events_table(df: pd.DataFrame, key: str) -> None:
    if df.empty:
        st.caption("일정이 없습니다. **🔎 공시에서 후보 찾기**를 누르거나 아래에서 직접 추가하세요.")
        return
    today = _today_et()
    v = df.assign(남은기간=[_dday(d, today) for d in df["date"]],
                  임박=["🔥" if (date.fromisoformat(d) >= today and watch.trading_days_between(today, date.fromisoformat(d)) <= 3) else "" for d in df["date"]])
    st.dataframe(v[["임박", "date", "남은기간", "ticker", "kind", "title", "origin", "source"]].rename(columns={"date": "날짜", "ticker": "티커", "kind": "종류", "title": "내용", "origin": "구분"}),
                 hide_index=True, width="stretch", column_config={"source": st.column_config.LinkColumn("원문", display_text="열기")})
    with st.expander("일정 삭제"):
        opts = {f"{r.date} {r.ticker} {r.kind} — {r.title[:40]}": r.id for r in df.itertuples()}
        pick = st.selectbox("삭제할 일정", list(opts), key=f"{key}_delpick")
        if st.button("삭제", key=f"{key}_del"):
            watch.delete_event(opts[pick])
            st.rerun()


def _event_form(ticker: str | None, key: str) -> None:
    with st.form(f"{key}_form", clear_on_submit=True):
        cols = st.columns([1, 1, 1, 3, 1])
        t = cols[0].text_input("티커", value=ticker or "", disabled=ticker is not None)
        d = cols[1].date_input("날짜", value=_today_et())
        k = cols[2].selectbox("종류", EVENT_KINDS)
        title = cols[3].text_input("내용", placeholder="예: 워런트 2.5M주 만기, 주총 역분할 안건")
        cols[4].write("")
        if cols[4].form_submit_button("➕ 일정 추가", width="stretch") and (ticker or t.strip()) and title.strip():
            watch.add_event((ticker or t).strip().upper(), d.isoformat(), k, title.strip())
            st.rerun()


def render_events() -> None:
    st.subheader("🗓 일정 · 기한 이벤트")
    st.caption("공시에서 자동으로 찾은 일정(주총·상장유지 기한·역분할 시행·워런트 만기·락업 해제, EFFECT·424B·8-K 3.01)과 직접 넣은 일정. "
               "자동 일정은 **키워드 추출이라 원문 확인이 필요**합니다. 🔥 = 오늘~3거래일 안.")
    c1, c2, c3 = st.columns([2, 2, 2])
    scope = c1.radio("대상", ["워치리스트(블랙 제외)", "전체"], horizontal=True, key="ev_scope")
    ahead = c2.slider("앞으로 며칠", 7, 180, 60, key="ev_ahead")
    back = c3.slider("지난 며칠까지", 0, 60, 7, key="ev_back")
    wl = watch.scanner_priority()
    today = _today_et()
    df = watch.events_df(wl if scope.startswith("워치") else None, (today - timedelta(days=back)).isoformat(), (today + timedelta(days=ahead)).isoformat())
    hot = df[[date.fromisoformat(d) >= today and watch.trading_days_between(today, date.fromisoformat(d)) <= 3 for d in df["date"]]] if not df.empty else df
    m1, m2, m3 = st.columns(3)
    m1.metric("일정", f"{len(df)} 건")
    m2.metric("🔥 3거래일 안", f"{len(hot)} 건")
    m3.metric("희석 임박·발행 (기간 내)", f"{int(df['kind'].isin(['희석 임박', '발행']).sum()) if not df.empty else 0} 건")
    _events_table(df, key="ev_all")
    _event_form(None, key="ev_add")
    b1, b2 = st.columns([1, 3])
    if b1.button("🔎 워치리스트 전체 공시 스캔", key="ev_scan_all", disabled=not wl):
        cl = sec_client()
        if cl:
            bar = st.progress(0.0, text="공시 확인 중...")
            tot = {"new_overhang": 0, "new_events": 0, "errors": 0}
            for i, t in enumerate(wl):
                bar.progress((i + 1) / len(wl), text=f"{t} 공시 확인 중... ({i + 1}/{len(wl)})")
                r = watch.scan_ticker(cl, t)
                for k in tot:
                    tot[k] += r.get(k, 0)
            st.success(f"{len(wl)}종목 확인 — 새 일정 {tot['new_events']}건, 새 물량 후보 {tot['new_overhang']}건" + (f" (읽기 실패 {tot['errors']}건)" if tot["errors"] else ""))
    b2.caption("종목당 최근 1년 공시 최대 12건을 읽어서 종목 수에 따라 몇 분 걸릴 수 있어요. 결과는 저장되어 다시 읽지 않아도 됩니다.")

    st.markdown("##### 💲 $1 상장유지 현황 (워치리스트, 가격 $2 미만)")
    px = prices(tuple(wl))
    rows = []
    for t in wl:
        s = _px_stats(px.get(t), None)
        if s.get("price") is not None and s["price"] < 2:
            note = ("회복 요건 충족(10거래일)" if s["above"] >= 10 else f"회복까지 {10 - s['above']}거래일") if s.get("above") else (
                f"미달 통지 대상(30거래일 이상)" if (s.get("below") or 0) >= 30 else f"$1 미만 {s.get('below')}거래일째")
            rows.append({"티커": t, "현재가($)": s["price"], "$1 이상 연속": s.get("above"), "$1 미만 연속": s.get("below"), "판단": note})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={"현재가($)": st.column_config.NumberColumn(format="%.4f")})
        st.caption("나스닥 최저호가 요건: 종가 $1 미만 30거래일 연속이면 미달 통지, 이후 종가 $1 이상 10거래일 연속이면 회복. 휴장일은 Yahoo 일봉 기준으로 셉니다.")
    else:
        st.caption("가격이 $2 미만인 워치리스트 종목이 없습니다.")
