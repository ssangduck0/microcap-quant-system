"""'장마감 펌핑 체크리스트(토스 기준)' 탭 화면. 스캐너가 정규장 중 close_state 에 기록한 원본 수치를, 화면의 기준값으로 판정한다."""
import json
from contextlib import closing

import pandas as pd
import streamlit as st

import closewatch as cw
import db
import halts
import pick as picker

ICON = {"pass": "✅", "fail": "❌", "unknown": "➖", "na": "·"}
SHORT = {"drop": "낙폭", "vol": "거래량 폭발", "decay": "거래량 감소", "buy": "체강↑", "ask_thin": "호가 얇아짐", "no_wall": "매도벽 없음",
         "no_atm_cb": "ATM·CB 없음", "no_intraday": "장중 희석 없음", "no_warrant": "워런트 없음", "fin_restricted": "출회제한 조달", "supply": "공급 제한",
         "halt": "하킷", "short": "공매도 압력", "dist": "분산"}
GRADE_HELP = {"BEST": "패턴 충족이 기준 이상 + 장중 희석 없음 + (출회 제한형 자금조달 또는 공급 제한)",
              "후보": "패턴 충족이 기준 이상, 희석 위험 없음", "관찰": "패턴 일부 충족", "미달": "패턴 거의 미충족",
              "희석 위험": "ATM·전환사채 정황 또는 장중 희석 공시", "낙폭 미달": "과대 낙폭 기준 미달 (일단 낙폭이 커야 함)"}


@st.cache_data(ttl=15)
def load_state() -> pd.DataFrame:
    cw.ensure_tables()
    return db.read_df("SELECT date, ticker, metrics, updated_at FROM close_state WHERE date=(SELECT MAX(date) FROM close_state)")


@st.cache_data(ttl=15)
def load_samples(day: str, ticker: str) -> pd.DataFrame:
    ws = db.read_df("SELECT minute AS ts, ask_usd_avg AS ask_depth_usd FROM close_flow WHERE date=? AND ticker=? AND ask_usd_avg IS NOT NULL ORDER BY minute", (day, ticker))
    if len(ws) >= 4:  # 웹소켓 분 단위 시계열이 있으면 우선
        return ws
    return db.read_df("SELECT ts, price, ask_depth_usd FROM close_samples WHERE date=? AND ticker=? ORDER BY ts", (day, ticker))


def kst(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce").dt.tz_convert("Asia/Seoul").dt.strftime("%H:%M")


# ---------------------------------------------------------------- 오늘 거래정지 현황 (장외에도 항상 표시)
@st.cache_data(ttl=30, show_spinner=False)
def load_halts() -> tuple[list[dict], str | None, str | None, str]:
    """(목록, 출처, 오류, 받은 시각 KST). 업킷이 기본, 실패하면 나스닥 RSS. 30초 캐시."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    got = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")
    try:
        data = halts.fetch(ttl=25)
        return data, halts.last_source, None, got
    except Exception as e:  # noqa: BLE001
        return [], None, f"{type(e).__name__}: {e}", got


@st.cache_data(ttl=60)
def scanner_tickers() -> tuple[set, set, dict]:
    """(오늘 스캐너가 발견한 종목, 체크리스트 종목, 체크리스트가 계산한 정지 방향 {(티커, 'MM-DD HH:MM:SS'): 상한/하한})"""
    seen = set(db.read_df("SELECT ticker FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots)")["ticker"])
    st_df = load_state()
    dirs = {}
    for r in st_df.itertuples():
        for h in (json.loads(r.metrics).get("halts") or []):
            if h.get("dir"):
                dirs[(r.ticker, h["time"])] = h["dir"]
    return seen, set(st_df["ticker"]), dirs


def render_halts() -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    et, kz = ZoneInfo("America/New_York"), ZoneInfo("Asia/Seoul")
    st.markdown("#### 🚦 오늘 거래정지 현황 (업킷 UpCuit)")
    hs, src, err, got = load_halts()
    c0, c1 = st.columns([5, 1])
    if c1.button("🔄 새로고침", key="halt_refresh"):
        load_halts.clear()
        st.rerun()
    if err:
        c0.warning(f"거래정지 정보를 받지 못했습니다(업킷·나스닥 모두): {err}")
        return
    c0.caption(f"출처: **{'업킷 API' if src == 'upcuit' else '나스닥 공식 RSS (업킷 응답 없음)'}** · 받은 시각 {got} KST (30초 캐시) · "
               "업킷은 참고용(SLA 없음)이며 정지 여부는 토스·거래소에서 최종 확인하세요.")
    now = datetime.now(et)
    seen, watched, dirs = scanner_tickers()
    rows = []
    for h in hs:
        if not h.get("halt"):
            continue
        status = h.get("status") or ("resumed" if h.get("resume") else "halted")
        state = {"halted": "🔴 정지 중", "quote_resumed": "🟡 호가만 재개", "resumed": "🟢 재개"}.get(status, status)
        tkey = (h["symbol"], h["halt"].strftime("%m-%d %H:%M:%S"))
        note = ""
        if status == "halted":
            mins = (now - h["halt"]).total_seconds() / 60
            if h["code"] in ("LUDP", "LUDS", "M"):  # LULD 정지는 보통 5분 뒤 재개(마감 직전·연장 시 달라질 수 있음)
                left = (h["halt"] + timedelta(minutes=5) - now).total_seconds()
                note = f"예상 재개 {(h['halt'] + timedelta(minutes=5)):%H:%M:%S} ET ({int(left)}초 남음)" if left > 0 else f"정지 {mins:.0f}분째(5분 넘음·연장 가능)"
            else:
                note = f"정지 {mins:.0f}분째"
        rows.append({"상태": state, "티커": h["symbol"], "종목명": h.get("name") or "", "시장": h.get("market") or "",
                     "사유": f"{h['code']} {halts.CODE_KO.get(h['code']) or h.get('title') or ''}".strip(),
                     "정지(ET)": h["halt"].strftime("%m-%d %H:%M:%S"), "정지(KST)": h["halt"].astimezone(kz).strftime("%H:%M:%S"),
                     "재개(ET)": h["resume"].strftime("%H:%M:%S") if h.get("resume") else "", "진행": note,
                     "밴드 가격": h.get("threshold"), "방향": dirs.get(tkey, ""),
                     "스캐너": "✅" if h["symbol"] in seen else "", "체크리스트": "✅" if h["symbol"] in watched else "",
                     "이월": "전날" if h["halt"].date() < now.date() else "", "_t": h["halt"], "_luld": h["code"] in ("LUDP", "LUDS", "M"),
                     "_active": status != "resumed"})
    if not rows:
        st.info("현재 거래정지 목록이 비어 있습니다(장 시작 전이거나 오늘 정지가 없음).")
        return
    tb = pd.DataFrame(rows).sort_values("_t", ascending=False)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("전체", f"{len(tb)} 건")
    m2.metric("지금 정지 중", f"{int(tb['_active'].sum())} 건", help="정지 중 + 호가만 재개")
    m3.metric("LULD(상킷·하킷)", f"{int(tb['_luld'].sum())} 건", help="LUDP·LUDS·M 변동성 정지")
    m4.metric("스캐너 발견 종목", f"{int((tb['스캐너'] == '✅').sum())} 건", help="오늘 스캐너가 발견한 종목 중 정지된 것")
    f1, f2, f3, f4 = st.columns(4)
    if f1.checkbox("지금 정지 중만", False, key="halt_active"):
        tb = tb[tb["_active"]]
    if f2.checkbox("LULD(변동성 정지)만", False, key="halt_luld"):
        tb = tb[tb["_luld"]]
    if f3.checkbox("스캐너 발견 종목만", False, key="halt_seen"):
        tb = tb[tb["스캐너"] == "✅"]
    q = f4.text_input("티커 검색", "", key="halt_q").strip().upper()
    if q:
        tb = tb[tb["티커"].str.contains(q, regex=False)]
    cols = ["상태", "티커", "종목명", "시장", "사유", "정지(ET)", "정지(KST)", "재개(ET)", "진행", "밴드 가격", "방향", "스캐너", "체크리스트", "이월"]
    st.dataframe(tb[cols], hide_index=True, width="stretch", height=min(420, 38 + 35 * max(len(tb), 1)), column_config={
        "밴드 가격": st.column_config.NumberColumn(format="%.4f", help="LULD 정지 기준가(PauseThresholdPrice)"),
        "방향": st.column_config.TextColumn(help="상한(상킷)/하한(하킷): 밴드 가격을 정지 직전 토스 1분봉 가격과 비교. 체크리스트 종목만 계산됨"),
        "진행": st.column_config.TextColumn(help="LULD 정지는 보통 5분 뒤 재개 — 마감 직전·연장 시 달라질 수 있음")})
    st.caption("상한/하한 방향은 업킷도 주지 않아, 스캐너가 정규장 중 체크리스트 종목에 한해 정지 직전 가격과 비교해 계산합니다. 화면은 자동으로 바뀌지 않으니 🔄 또는 F5로 갱신하세요.")
    st.divider()


@st.cache_data(ttl=15)
def load_lists() -> tuple[str | None, list[dict], list[dict]]:
    """(날짜, 고정 목록, 현재 순위) — 가장 최근 날짜 기준."""
    from contextlib import closing
    with closing(db.connect()) as conn:
        cw.ensure_tables(conn)
        r = conn.execute("SELECT MAX(date) AS d FROM close_watchlist").fetchone()
        d = r["d"] if r else None
        if not d:
            return None, [], []
        return d, cw.load_list(conn, d, "frozen"), cw.load_list(conn, d, "live")


def render_targets(df: pd.DataFrame) -> pd.DataFrame:
    """대상 종목 안내 + 고정 목록이 있으면 체크리스트 표를 그 종목으로 좁힌다."""
    import config
    day, frozen, live = load_lists()
    cfg = {"등락(%)": st.column_config.NumberColumn(format="%.1f"), "가격($)": st.column_config.NumberColumn(format="%.4f")}
    ren = {"rank": "순위", "ticker": "티커", "change_pct": "등락(%)", "price": "가격($)"}
    n, m = config.CLOSE_WATCH_TOP_N, config.CLOSE_WATCH_FREEZE_MIN
    if frozen:
        at = kst(pd.Series([frozen[0]["at"]])).iloc[0]
        st.info(f"🔒 **대상 고정** {day} · {at} KST (정규장 마감 {m}분 전) — 토스 **급하락 순위 1~{n}위** 중 {len(frozen)}종목"
                + (f" (ETF·워런트 등 {n - len(frozen)}개 제외 또는 순위 부족)" if len(frozen) < n else "") + ". 마감까지 이 종목들만 추적합니다.")
        with st.expander(f"고정된 {len(frozen)}종목 (고정 당시 순위)", expanded=False):
            st.dataframe(pd.DataFrame(frozen)[["rank", "ticker", "change_pct", "price"]].rename(columns=ren),
                         hide_index=True, width="stretch", column_config=cfg)
        if not df.empty and day in set(df["date"]):
            df = df[df["ticker"].isin({x["ticker"] for x in frozen})]
    elif live:
        at = kst(pd.Series([live[0]["at"]])).iloc[0]
        st.warning(f"⏳ **아직 대상 고정 전** — 정규장 마감 {m}분 전(한국시간 04:00, 11월 이후 05:00 · 조기 폐장일은 앞당겨짐)에 "
                   f"토스 **급하락 순위 1~{n}위**로 고정한 뒤 체크리스트를 기록합니다. 아래는 {at} KST 현재 순위입니다.")
        st.dataframe(pd.DataFrame(live)[["rank", "ticker", "change_pct", "price"]].rename(columns=ren),
                     hide_index=True, width="stretch", column_config=cfg, height=min(420, 38 + 35 * len(live)))
        df = df.iloc[0:0] if not df.empty and day in set(df["date"]) else df
    else:
        st.caption(f"대상: 정규장 마감 {m}분 전의 토스 **급하락 순위 1~{n}위**(ETF·워런트·우선주 제외). 정규장 중 스캐너가 순위를 받으면 여기에 표시됩니다.")
    return df


def render() -> None:
    import access
    if access.guest_block():   # 2026-10-29 토스 데이터 정책 B안(방문객에게 호가·체결강도·1분봉 숨김)
        return
    t1, t2, t3 = st.tabs(["🎯 오늘 체크리스트", "📈 결과 추적 (반등 성공·실패)", "🚦 거래정지 현황"])
    with t1:
        render_today()
    with t2:
        render_results()
    with t3:
        render_halts()


def params_from_state() -> dict:
    """오늘 체크리스트 탭의 기준값 슬라이더 값(없으면 기본값)."""
    g = st.session_state.get
    best_min = g("cw_best", 5)
    return {"drop": float(g("cw_drop", -20)), "vol_mult": g("cw_vol", 3.0), "decay": g("cw_decay", 50) / 100, "cs_late": float(g("cw_cs_late", 110)),
            "cs_delta": float(g("cw_cs_delta", 10)), "ask_thin": g("cw_thin", 60) / 100, "ask_minutes": g("cw_askmin", 5.0), "wall_ratio": g("cw_wall", 3.0),
            "shares_max": g("cw_shares", 20) * 1e6, "best_min": best_min, "cand_min": max(best_min - 1, 1), "short_ratio": float(g("cw_short", 55))}


def render_today() -> None:
    st.subheader("🎯 장마감 펌핑 체크리스트 (토스증권 기준)")
    import pumpsetup_ui
    pumpsetup_ui.fomo_card()
    sess = (db.get_meta("us_session") or {}).get("value")
    if sess == "정규장":
        st.success("지금은 **미국 정규장**입니다. 스캐너가 후보 종목의 호가·1분봉·공시를 사이클마다 기록하고 있습니다. **마감 30분 전**(한국시간 04:30~05:00, 11월 이후 05:30~06:00)부터의 값이 가장 의미 있습니다.")
    elif sess:
        st.warning(f"지금은 **{sess}**입니다. 이 탭의 데이터는 **정규장 중에만** 기록되므로 아래 값은 **마지막 정규장 사이클** 기준입니다.")
    st.caption("데이터 출처 — **토스증권 Open API**: 현재가·1분봉·일봉·호가·발행주식수, 실시간 체결·호가(웹소켓)로 계산한 **체결강도**(체결가를 그 순간의 호가와 비교한 매수/매도 체결량 비, 토스 화면의 체결강도와 같은 정의의 추정치) · "
               "**SEC 공시 키워드**(원문 확인 필요): 장중 희석·자금조달 유형·워런트 · **업킷(UpCuit) 거래정지 API**(실패 시 나스닥 RSS): 하킷·상킷(LULD) · **FINRA·IBKR(무료)**: 공매도 거래량·대차 수수료·대차 가능 수량. "
               "퀀트 스냅샷과는 기준이 다른 별도 체크리스트입니다.")

    df = load_state()
    df = render_targets(df)
    if df.empty:
        st.info("아직 기록이 없습니다. **토스 연동이 켜져 있고**(`toss_check.py` 통과), 스캐너가 **미국 정규장 중**에 오늘 등락이 "
                f"{cw_cfg_drop():g}% 이하인 종목을 발견하면 사이클마다 여기에 기록됩니다.")
        return

    with st.expander("⚙️ 기준값 조정 (저장된 원본 수치를 이 기준으로 다시 판정합니다)"):
        a1, a2, a3, a4, a5 = st.columns(5)
        drop = a1.slider("과대 낙폭 ≤ (%)", -70, -5, -20, key="cw_drop")
        vol = a2.slider("거래량 폭발 ≥ (배, 토스 20일 평균)", 1.0, 20.0, 3.0, 0.5, key="cw_vol")
        decay = a3.slider("거래량 감소: 최근 60분 ≤ 피크의 (%)", 10, 100, 50, key="cw_decay")
        cs_late = a4.slider("체결강도 최근 30분 ≥ (%)", 80, 200, 110, key="cw_cs_late", help="매수 체결량 / 매도 체결량 × 100. 100% = 균형")
        cs_delta = a5.slider("체결강도 이전 60분 대비 +%p ≥", 0, 50, 10, key="cw_cs_delta")
        b1, b2, b3, b4, b5 = st.columns(5)
        thin = b1.slider("호가 얇아짐: 현재 ≤ 이전의 (%)", 20, 100, 60, key="cw_thin")
        askmin = b2.slider("매도잔량 ≤ 최근 거래 (분치)", 1.0, 30.0, 5.0, 0.5, key="cw_askmin")
        wall = b3.slider("최대 호가 < 나머지 평균의 (배)", 1.5, 10.0, 3.0, 0.5, key="cw_wall")
        shares = b4.slider("공급 제한: 발행주식수 ≤ (백만 주)", 5, 200, 20, key="cw_shares")
        best_min = b5.slider("BEST 최소 패턴 충족 (6개 중)", 3, 6, 5, key="cw_best")
        short_ratio = st.slider("공매도 압력: 직전 거래일 공매도 거래량 비중 ≥ (%)", 30, 90, 55, key="cw_short",
                                help="FINRA 일별 공매도 거래량(장외 거래 기준). 높을수록 공매도 진입이 많았다는 뜻. 이 항목은 등급 계산에는 넣지 않고 참고로만 표시합니다.")
    params = {"drop": float(drop), "vol_mult": vol, "decay": decay / 100, "cs_late": float(cs_late), "cs_delta": float(cs_delta), "ask_thin": thin / 100,
              "ask_minutes": askmin, "wall_ratio": wall, "shares_max": shares * 1e6, "best_min": best_min, "cand_min": max(best_min - 1, 1), "short_ratio": float(short_ratio)}

    rows = []
    for r in df.itertuples():
        m = json.loads(r.metrics)
        ev = cw.evaluate(m, params)
        st_ = {i["key"]: i["status"] for i in ev["items"]}
        row = {"등급": ev["grade"], "티커": r.ticker, "낙폭(%)": m.get("drop_pct"), "패턴": f"{ev['n_pattern']}/{ev['n_pattern_total']}"}
        for k in SHORT:
            row[SHORT[k]] = ICON[st_[k]]
        fin = m.get("financing")
        row.update({"거래량 배수": m.get("vol_mult"), "최근60분/피크": m.get("decay"), "체강 최근30분(%)": m.get("cs_late"), "호가 비율": m.get("thin_ratio"),
                    "매도잔량(분치)": m.get("ask_minutes"), "발행주식(백만)": None if m.get("shares_out") is None else m["shares_out"] / 1e6,
                    "자금조달(7일)": "없음" if fin is None else f"{fin['type']} · {fin['label']}", "현재가($)": m.get("price"),
                    "갱신(KST)": kst(pd.Series([r.updated_at])).iloc[0], "_ev": ev, "_m": m, "_date": r.date})
        rows.append(row)
    tbl = pd.DataFrame(rows)
    tbl["_o"] = tbl["등급"].map(cw.GRADE_ORDER)
    tbl = tbl.sort_values(["_o", "낙폭(%)"], na_position="last")

    cnt = tbl["등급"].value_counts()
    g1, g2, g3, g4, g5 = st.columns(5)
    for col, g in zip((g1, g2, g3, g4, g5), ("BEST", "후보", "관찰", "희석 위험", "낙폭 미달")):
        col.metric(g, f"{int(cnt.get(g, 0))} 개", help=GRADE_HELP[g])
    hide = st.checkbox("낙폭 미달·희석 위험·미달 등급 숨기기", True, key="cw_hide")
    shown = tbl[tbl["등급"].isin(["BEST", "후보", "관찰"])] if hide else tbl
    if shown.empty:
        st.info("표시할 종목이 없습니다. 기준값을 낮추거나 '숨기기'를 해제해 보세요.")
        return
    cols = ["등급", "티커", "낙폭(%)", "패턴"] + list(SHORT.values()) + ["거래량 배수", "최근60분/피크", "체강 최근30분(%)", "호가 비율", "매도잔량(분치)",
                                                                         "발행주식(백만)", "자금조달(7일)", "현재가($)", "갱신(KST)"]
    cfg = {SHORT[k]: st.column_config.TextColumn(width="small", help=f"{SHORT[k]}  (✅ 충족 / ❌ 미충족 / ➖ 확인 불가 / · 해당 없음)") for k in SHORT}
    cfg.update({"낙폭(%)": st.column_config.NumberColumn(format="%.1f", help="토스 전일 종가 대비"), "거래량 배수": st.column_config.NumberColumn(format="%.2f", help="토스 오늘 거래량 / 토스 20일 일봉 평균"),
                "최근60분/피크": st.column_config.NumberColumn(format="%.2f", help="1보다 훨씬 작을수록 폭발 이후 거래가 줄어든 것"),
                "체강 최근30분(%)": st.column_config.NumberColumn(format="%.0f", help="매수 체결량 / 매도 체결량 × 100 (토스 웹소켓 체결가↔호가 기준 추정, 데이터가 없으면 1분봉 추정)"),
                "호가 비율": st.column_config.NumberColumn(format="%.2f", help="현재 매도 호가 깊이 / 이전 중앙값. 작을수록 얇아짐"),
                "매도잔량(분치)": st.column_config.NumberColumn(format="%.1f"), "발행주식(백만)": st.column_config.NumberColumn(format="%.2f"),
                "현재가($)": st.column_config.NumberColumn(format="%.4f")})
    import tosslink_ui
    _tv = shown[cols].copy()
    _tv.insert(1, "토스", tosslink_ui.links(_tv["티커"]))
    import rank_ui
    _tv.insert(2, "종합 순위", rank_ui.column(_tv["티커"]))
    clicked = picker.clickable(_tv, list(shown["티커"]), "cw_table", hide_index=True, width="stretch", column_config={**cfg, "토스": tosslink_ui.COLUMN})
    st.caption("✅ 충족 · ❌ 미충족 · ➖ 확인 불가(데이터 부족/조회 실패) · · 해당 없음. 확인 불가는 충족으로 세지 않습니다. 호가·체강 추세는 **마감 30~60분 전부터** 샘플이 쌓여야 판정됩니다. "
               "등급: " + " / ".join(f"**{g}** = {h}" for g, h in GRADE_HELP.items()))

    st.markdown("#### 🔎 종목 상세")
    pick = clicked
    tosslink_ui.button(pick, key="cw")
    r = shown[shown["티커"] == pick].iloc[0]
    ev, m = r["_ev"], r["_m"]
    bad = [f"{i['name']} → {i['value']}" for i in ev["items"] if i["status"] == "fail"]
    msg = f"**{pick}** — 등급 **{ev['grade']}** · 패턴 {ev['n_pattern']}/{ev['n_pattern_total']} 충족"
    (st.warning if bad else st.success)(msg + (f"  \n미충족: " + " / ".join(bad) if bad else ""))
    det = pd.DataFrame([{"그룹": {"pattern": "수급 패턴", "money": "돈 유입", "dilution": "희석 안전", "bonus": "베스트 가산", "info": "참고"}.get(i["group"], i["group"]), "항목(기준)": i["name"],
                         "현재 값": i["value"], "결과": {"pass": "✅ 충족", "fail": "❌ 미충족", "unknown": "➖ 확인 불가", "na": "· 해당 없음"}[i["status"]]} for i in ev["items"]])
    st.dataframe(det, hide_index=True, width="stretch")

    fin = m.get("financing")
    if fin:
        st.markdown(f"**최근 자금조달(SEC)**: [{fin['date']} {fin['form']}]({fin['url']}) — {fin['type']} → **{fin['label']}**  \n"
                    "키워드 판정이라 사모/공모 구분과 재판매 등록 상태는 반드시 원문으로 확인하세요(재판매 등록서류가 'EFFECT' 되기 전에는 사모 주식이 시장에 나오기 어렵다는 점을 근거로 한 추정입니다).")
    intr = m.get("intraday_filings")
    if intr:
        st.markdown("**오늘 공시(SEC)**: " + " · ".join(f"[{x['form']}]({x['url']})" + (f" `{','.join(x['tags'])}`" if x["tags"] else "") for x in intr))
    elif m.get("sec_error"):
        st.caption(f"SEC 확인 실패: {m['sec_error']}")

    wf = m.get("warrant_filings")
    if wf:
        st.markdown("**최근 워런트 관련 공시(SEC)**: " + " · ".join(f"[{x['date']} {x['form']}]({x['url']})" for x in wf[:5]) + "  \n키워드 판정이라 신규 발행인지 기존 워런트 언급인지 원문으로 확인하세요.")
    if m.get("halts"):
        st.markdown("**오늘 거래정지 이력(나스닥 피드)** — 상한/하한은 정지 직전 가격과 변동성 밴드 가격을 비교한 추정입니다.")
        st.dataframe(pd.DataFrame([{"정지 시각(ET)": x["time"], "사유": x["reason"], "방향": x["dir"] or "-", "밴드 가격": x["threshold"], "직전 가격": x["price_before"],
                                   "재개(ET)": x["resume"] or "정지 중"} for x in m["halts"]]), hide_index=True, width="stretch")
    if m.get("short") is not None or m.get("short_note"):
        st.caption("공매도 거래량은 FINRA 장외(TRF) 거래 기준이라 **당일치는 장 마감 뒤에** 나옵니다(마감 전에는 직전 거래일까지). 대차 수수료·가능 수량은 장중에도 갱신됩니다. "
                   "공매도가 많다는 것이 반등 신호인지 추가 하락 신호인지는 검증된 바 없어 등급에는 반영하지 않았습니다.")

    c1, c2 = st.columns(2)
    vs = pd.DataFrame(m.get("vol_series") or [])
    if not vs.empty:
        c1.markdown("**10분 단위 거래량 (정규장, 토스 1분봉)**")
        c1.bar_chart(vs.set_index("t")["v"], height=220)
    sm = load_samples(r["_date"], pick)
    if not sm.empty and sm["ask_depth_usd"].notna().any():
        sm = sm.assign(시각=kst(sm["ts"])).set_index("시각")
        c2.markdown("**매도 호가 깊이($) 추이 (토스 호가)**")
        c2.line_chart(sm["ask_depth_usd"], height=220)
    else:
        c2.caption("호가 샘플이 아직 없습니다(스캐너가 정규장 중 사이클마다 쌓습니다).")


def cw_cfg_drop() -> float:
    import config
    return config.CLOSE_WATCH_MIN_DROP


# ---------------------------------------------------------------- 📈 결과 추적: 고정된 종목이 실제로 반등했는가
RESULT_BASIS = {"다음날 고가": "next_high_pct", "다음날 종가": "next_close_pct", "5일 내 최고가": "max_up_5d"}


@st.cache_data(ttl=60)
def load_results() -> pd.DataFrame:
    import tracker
    cw.ensure_tables()
    tracker.ensure_close_table()
    return db.read_df("""SELECT w.date, w.ticker, w.rank, w.change_pct AS frozen_chg, w.at AS frozen_at, s.metrics,
                                o.entry_close, o.next_open_pct, o.next_high_pct, o.next_low_pct, o.next_close_pct, o.max_up_5d, o.max_down_5d, o.bars_after, o.status
                         FROM close_watchlist w
                         LEFT JOIN close_state s ON s.date=w.date AND s.ticker=w.ticker
                         LEFT JOIN close_outcomes o ON o.date=w.date AND o.ticker=w.ticker
                         WHERE w.kind='frozen' ORDER BY w.date DESC, w.rank""")


def judge_results(df: pd.DataFrame, basis: str, target: float, params: dict) -> pd.DataFrame:
    """등급(마감 직전 기록을 params 로 판정)과 성공/실패/대기."""
    grades, npat, fails = [], [], []
    for m in df["metrics"]:
        if not isinstance(m, str) or not m:  # 체크리스트 기록이 없는 고정 종목(빈 값은 NaN 으로 들어옴)
            grades.append("기록 없음"); npat.append(None); fails.append("")
            continue
        ev = cw.evaluate(json.loads(m), params)
        grades.append(ev["grade"]); npat.append(ev["n_pattern"])
        fails.append(", ".join(SHORT[i["key"]] for i in ev["items"] if i["status"] == "fail" and i["key"] in SHORT))
    v = df[RESULT_BASIS[basis]]
    if basis == "5일 내 최고가":
        hit = v >= target
        known = hit | (df["bars_after"].fillna(-1) >= 5)
    else:
        hit = v >= target
        known = v.notna()
    res = pd.Series("⏳ 대기", index=df.index)
    res[known & hit] = "✅ 반등"
    res[known & ~hit] = "❌ 실패"
    res[df["status"] == "no_data"] = "· 가격 없음"
    return df.assign(등급=grades, 패턴=npat, 미충족=fails, 결과=res, _known=known & (df["status"] != "no_data"), _hit=known & hit)


def _summary(g: pd.DataFrame) -> dict:
    k = g[g["_known"]]
    return {"종목 수": len(g), "결과 확인": len(k), "반등": int(k["_hit"].sum()), "성공률(%)": (k["_hit"].mean() * 100) if len(k) else None,
            "다음날 고가 중앙값(%)": k["next_high_pct"].median() if len(k) else None, "다음날 종가 중앙값(%)": k["next_close_pct"].median() if len(k) else None,
            "5일 최고 중앙값(%)": k["max_up_5d"].median() if len(k) else None}


def render_results() -> None:
    import tracker
    st.subheader("📈 장마감 체크리스트 결과 추적")
    st.caption("마감 1시간 전에 고정된 종목(토스 급하락 1~20위)이 **실제로 반등했는지** 기록합니다. 진입가 = 고정된 날 **정규장 종가**(일봉), "
               "결과는 진입가 대비 %. 다음 날 장 마감 후 채워지고(매일 아침 자동 갱신 또는 아래 버튼), 일봉 기준이라 체결·수수료·호가 공백은 반영되지 않습니다.")
    df = load_results()
    b1, b2 = st.columns([1, 4])
    if b1.button("🔄 결과 지금 갱신", key="cr_refresh", help="고정 종목의 일봉(Yahoo)을 받아 다음날·5일 결과를 채웁니다"):
        with st.spinner("결과 계산 중..."):
            with closing(db.connect()) as conn:
                r = tracker.update_close(conn, out=lambda *_: None)
        load_results.clear()
        b2.success(f"갱신 {r.get('updated', 0)}건 · 대기 {r.get('pending', 0)}건")
        st.rerun()
    if df.empty:
        st.info("아직 고정된 체크리스트가 없습니다. 정규장 마감 1시간 전에 스캐너가 토스 급하락 1~20위를 고정하면 여기에 쌓입니다.")
        return
    dmin, dmax = pd.to_datetime(df["date"].min()).date(), pd.to_datetime(df["date"].max()).date()
    c1, c2, c3, c4 = st.columns(4)
    rng = c1.date_input("기간", (dmin, dmax), min_value=dmin, max_value=dmax, key="cr_rng")
    basis = c2.selectbox("반등 기준", list(RESULT_BASIS), key="cr_basis")
    target = c3.slider("반등 성공: +N% 이상", 1, 50, 10, key="cr_target")
    mode = c4.radio("등급 판정", ["기본 기준값", "오늘 탭의 기준값"], key="cr_mode", help="저장된 마감 직전 원본 수치를 어떤 기준으로 등급 매길지")
    d0, d1 = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (dmin, dmax)
    df = df[(df["date"] >= str(d0)) & (df["date"] <= str(d1))]
    params = cw.DEFAULT_PARAMS if mode == "기본 기준값" else params_from_state()
    j = judge_results(df, basis, float(target), params)

    s = _summary(j)
    m = st.columns(5)
    m[0].metric("고정 종목", f"{s['종목 수']}", help=f"{j['date'].nunique()}거래일")
    m[1].metric("결과 확인", f"{s['결과 확인']}")
    m[2].metric(f"반등 성공 (≥ +{target}%)", f"{s['반등']}")
    m[3].metric("성공률", "-" if s["성공률(%)"] is None else f"{s['성공률(%)']:.1f}%")
    m[4].metric("다음날 종가 중앙값", "-" if s["다음날 종가 중앙값(%)"] is None else f"{s['다음날 종가 중앙값(%)']:+.1f}%",
                help="반등 성공률이 높아도 이 값이 낮으면 장중에 반등했다가 다시 밀린 경우가 많다는 뜻")
    if 0 < s["결과 확인"] < 30:
        st.warning(f"결과가 확인된 종목이 {s['결과 확인']}건뿐이라 성공률이 우연에 크게 흔들립니다. 몇 주 쌓인 뒤에 판단하세요.")

    st.markdown("**등급별 성과 — 체크리스트 등급이 높을수록 실제로 더 잘 반등하는가?**")
    order = ["BEST", "후보", "관찰", "미달", "희석 위험", "낙폭 미달", "기록 없음"]
    gt = pd.DataFrame([{"등급": g, **_summary(j[j["등급"] == g])} for g in order if (j["등급"] == g).any()])
    num = {c: st.column_config.NumberColumn(format="%.1f") for c in ["성공률(%)", "다음날 고가 중앙값(%)", "다음날 종가 중앙값(%)", "5일 최고 중앙값(%)"]}
    st.dataframe(gt, hide_index=True, width="stretch", column_config=num)
    st.markdown("**토스 순위대별 성과**")
    j["_band"] = pd.cut(j["rank"], [0, 5, 10, 20, 1000], labels=["1~5위", "6~10위", "11~20위", "21위~"])
    bt = pd.DataFrame([{"순위대": b, **_summary(j[j["_band"] == b])} for b in ["1~5위", "6~10위", "11~20위", "21위~"] if (j["_band"] == b).any()])
    st.dataframe(bt, hide_index=True, width="stretch", column_config=num)
    st.caption("등급이 높은 쪽(BEST·후보)의 성공률과 다음날 종가 중앙값이 낮은 등급보다 꾸준히 높아야 체크리스트가 옳은 방향입니다. "
               "차이가 없거나 거꾸로면 기준값(오늘 탭의 ⚙️)을 바꿔 '오늘 탭의 기준값'으로 다시 판정해 보세요.")

    cols = ["date", "ticker", "rank", "frozen_chg", "등급", "패턴", "미충족", "entry_close", "next_open_pct", "next_high_pct", "next_low_pct", "next_close_pct",
            "max_up_5d", "max_down_5d", "결과"]
    ren = {"date": "날짜", "ticker": "티커", "rank": "토스 순위", "frozen_chg": "고정 시 등락(%)", "entry_close": "진입가(종가,$)", "next_open_pct": "다음날 시가(%)",
           "next_high_pct": "다음날 고가(%)", "next_low_pct": "다음날 저가(%)", "next_close_pct": "다음날 종가(%)", "max_up_5d": "5일 최고(%)", "max_down_5d": "5일 최저(%)"}
    cfg = {v: st.column_config.NumberColumn(format="%+.1f") for k, v in ren.items() if k.endswith("_pct") or k.startswith("max_") or k == "frozen_chg"}
    cfg["진입가(종가,$)"] = st.column_config.NumberColumn(format="%.4f")
    cfg["미충족"] = st.column_config.TextColumn(help="마감 직전 체크리스트에서 ❌ 였던 항목")
    tabs = st.tabs(["✅ 반등 성공", "❌ 반등 실패", "⏳ 결과 대기", "전체"])
    for tb, key in zip(tabs, ["✅ 반등", "❌ 실패", "⏳ 대기", None]):
        with tb:
            part = j if key is None else j[j["결과"] == key]
            if part.empty:
                st.caption("없음")
            else:
                import tosslink_ui
                st.dataframe(tosslink_ui.with_links(part[cols].rename(columns=ren), "티커"), hide_index=True, width="stretch", column_config={**cfg, "토스": tosslink_ui.COLUMN})
    st.download_button("⬇️ 결과 CSV (엑셀용)", j[cols].rename(columns=ren).to_csv(index=False).encode("utf-8-sig"), file_name="close_checklist_results.csv", mime="text/csv")
