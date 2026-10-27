"""🌙 애프터 스캘핑 탭 — 스캐너가 애프터 시간대에 저장한 판정·분봉을 보여 주고, 진입 신호 결과로 승률을 검증."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import chartpop

import afterscalp as af
import db
import pick as picker
import tosslink_ui

KST, ET = ZoneInfo("Asia/Seoul"), ZoneInfo("America/New_York")


def _meta_dt(key: str):
    m = db.get_meta(key)
    try:
        return datetime.fromisoformat(m["value"]) if m and m.get("value") else None
    except ValueError:
        return None


def tip_card() -> None:
    with st.expander("📜 " + af.TIP_TITLE):
        st.text(af.TIP_TEXT)
        st.caption("해석: '50/200일 선'은 스캘핑·분봉 판단이라 분봉 기준 50·200 이동평균으로 봤습니다(일봉이 맞다면 알려 주세요). "
                   "'08시 50분'은 서머타임 기준이라 판정은 '애프터 종료 10분 전'으로 합니다(11월부터 09:50 KST). "
                   "데이마켓·데이→프리 방법은 아직 받지 않았어요.")


def render() -> None:
    st.subheader("🌙 애프터마켓 스캘핑 — 스승님 꿀팁")
    sess = (db.get_meta("us_session") or {}).get("value") or "알 수 없음"
    a_end = _meta_dt("us_after_end")
    dl = af.deadline_of(a_end) if a_end else None
    c = st.columns(3)
    c[0].metric("지금 세션", sess)
    c[1].metric("오늘 매도 마감", "-" if dl is None else dl.astimezone(KST).strftime("%H:%M KST"), help="애프터 종료 10분 전(서머타임 08:50, 11월부터 09:50 KST, 조기 폐장 반영)")
    c[2].metric("기준", "10억↑ · 캔들 · 급등 · MA±2%", help="① 애프터 거래대금 10억 원 이상 ② 최근 60분 분봉 80% 이상 정상 캔들, 공백 3분 이하 ③ 오늘 저점→고점 +15% 이상 ④ 고점에서 눌려 분봉 50·200 이동평균 ±2%")
    st.caption("스캐너가 애프터 시간대에 토스 실시간 거래량 상위 30종목(+급상승, 워치리스트·저금통)을 매 사이클 판정합니다. 🌙 진입 구간에 처음 들어가면 텔레그램으로 목표·손절·마감 시각을 보내고, 마감 5분 전에도 알려 줍니다.")
    tip_card()
    t1, t2 = st.tabs(["🌙 오늘 후보", "📒 신호 기록 · 승률 검증"])
    with t1:
        render_today()
    with t2:
        render_signals()


def render_today() -> None:
    from contextlib import closing
    with closing(db.connect()) as conn:
        af.ensure_tables(conn)
        r = conn.execute("SELECT MAX(date) AS d FROM after_state").fetchone()
    day = r["d"] if r else None
    if not day:
        st.info("아직 애프터 판정 기록이 없습니다. 애프터마켓 시간(서머타임 KST 05:00~09:00)에 스캐너가 켜져 있으면 쌓입니다.")
        return
    rows = af.states(day)
    if st.toggle("초소형주만", True, key="af_small", help="스캐너가 최근 30일 안에 본 종목만(거래대금 상위로 들어온 대형주는 숨김). 끄면 전부"):
        import ui_kit as _ui
        _uni = _ui.scanner_universe()
        if _uni:
            _n0 = len(rows)
            rows = [x for x in rows if x[0] in _uni or x[2]["stage"] in (af.STAGE_IN, af.STAGE_WATCH)]  # 진입·관찰 단계는 대형주라도 남김
            if _n0 - len(rows):
                st.caption(f"스캐너 대상이 아닌 {_n0 - len(rows)}종목 숨김(진입·관찰 단계는 남겨 둠)")
    order = {af.STAGE_IN: 0, af.STAGE_WATCH: 1}
    rows.sort(key=lambda x: (order.get(x[2]["stage"], 2), -x[2]["value_krw"]))
    tb = pd.DataFrame([{"티커": t, "단계": d["stage"], "현재가($)": d["price"], "거래대금(억 원)": d["value_krw"] / 1e8, "정상 캔들(%)": d["candle_ratio"] * 100,
                        "최대 공백(분)": d["max_gap"], "급등(%)": d["spike_pct"], "MA50 거리(%)": d["dist_ma50"], "MA200 거리(%)": d["dist_ma200"],
                        "목표 +5%($)": d["plan"]["target"], "손절 -5%($)": d["plan"]["stop"],
                        "갱신": pd.to_datetime(at).tz_convert(KST).strftime("%H:%M")} for t, at, d in rows])
    st.caption(f"애프터 날짜 {day} (동부시간) · {len(tb)}종목 · 🌙 {int((tb['단계'] == af.STAGE_IN).sum())} · 👀 {int((tb['단계'] == af.STAGE_WATCH).sum())}")
    cfg = {k: st.column_config.NumberColumn(format="%.4f") for k in ("현재가($)", "목표 +5%($)", "손절 -5%($)")}
    cfg.update({k: st.column_config.NumberColumn(format="%.0f") for k in ("거래대금(억 원)", "정상 캔들(%)", "급등(%)")})
    cfg.update({k: st.column_config.NumberColumn(format="%+.1f") for k in ("MA50 거리(%)", "MA200 거리(%)")})
    tb.insert(1, "토스", tosslink_ui.links(tb["티커"]))
    import rank_ui
    tb.insert(2, "종합 순위", rank_ui.column(tb["티커"]))
    cfg["토스"] = tosslink_ui.COLUMN
    t = picker.clickable(tb, list(tb["티커"]), "af_table", hide_index=True, width="stretch", column_config=cfg)
    if not t:
        return
    d = next(x[2] for x in rows if x[0] == t)
    st.markdown(f"#### 🌙 {t} — {d['stage']}")
    tosslink_ui.button(t, key="af")
    st.dataframe(pd.DataFrame([{**i, "결과": "✅" if i["결과"] else "❌"} for i in d["items"]]), hide_index=True, width="stretch")
    ch = d.get("chart") or {}
    if ch.get("t"):
        cdf = pd.DataFrame({"종가": ch["close"], "MA50": ch["ma50"], "MA200": ch["ma200"]}, index=pd.to_datetime(ch["t"]).tz_convert(KST).strftime("%H:%M"))
        pl = d["plan"]
        cdf["목표 +5%"], cdf["손절 -5%"] = pl["target"], pl["stop"]
        chartpop.line(cdf, key=f"after_{t}", title=f"{t} 애프터 1분봉 · 이동평균 · 목표/손절", height=300, y_title="$")
    pl = d["plan"]
    st.caption(f"진입 ${pl['entry']:.4f} → 목표 +5% ${pl['target']:.4f} · +7% ${pl['target7']:.4f} · +20% ${pl['target20']:.4f} · 손절 -5% ${pl['stop']:.4f}. "
               "분봉으로 수급이 계속 이어지는지 직접 확인하고, 마감 시각 전에 정리하세요.")


def render_signals() -> None:
    sg = af.signals()
    if sg.empty:
        st.info("아직 진입 신호가 없습니다. 제대로 된 급등 종목이 없는 날은 신호가 없는 게 정상입니다(스승님: 이틀에 한 번 꼴).")
        return
    sg = sg.assign(**{"신호 시각": pd.to_datetime(sg["at"]).dt.tz_convert(KST).dt.strftime("%m-%d %H:%M"),
                      "마감 전 청산(%)": (sg["exit_price"] / sg["price"] - 1) * 100})
    known = sg[sg["first_hit"].isin(["목표 +5%", "손절 -5%"])]
    win = (known["first_hit"] == "목표 +5%").mean() * 100 if len(known) else None
    days = sg["date"].nunique()
    m = st.columns(4)
    m[0].metric("신호", f"{len(sg)}", help=f"{days}일")
    m[1].metric("승률(+5%가 -5%보다 먼저)", "-" if win is None else f"{win:.0f}%", help=f"판정된 {len(known)}건 기준. 스승님 체감 승률 70%")
    m[2].metric("마감 전 청산 평균", "-" if sg["마감 전 청산(%)"].dropna().empty else f"{sg['마감 전 청산(%)'].mean():+.1f}%",
                help="목표·손절에 안 닿았을 때 마감 직전 가격에 팔았다고 보면")
    m[3].metric("신호 있는 날", f"{days}일")
    st.dataframe(tosslink_ui.with_links(sg[["date", "신호 시각", "ticker", "price", "max_up", "max_down", "first_hit", "마감 전 청산(%)"]].rename(columns={
        "date": "날짜", "ticker": "티커", "price": "진입가($)", "max_up": "마감 전 최고(%)", "max_down": "마감 전 최저(%)", "first_hit": "먼저 닿은 쪽"})),
        hide_index=True, width="stretch", column_config={"토스": tosslink_ui.COLUMN, "진입가($)": st.column_config.NumberColumn(format="%.4f"),
        **{k: st.column_config.NumberColumn(format="%+.1f") for k in ("마감 전 최고(%)", "마감 전 최저(%)", "마감 전 청산(%)")}})
    if len(known) < 20:
        st.caption(f"판정된 신호 {len(known)}건 — 20건 이상 쌓여야 승률을 믿을 수 있어요. 분봉 고가·저가 기준이라 실제 체결(호가 간격·슬리피지)은 더 불리할 수 있습니다.")
