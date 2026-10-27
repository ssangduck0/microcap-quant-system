"""🧨 공매도 상세 — 공매도 종합 현황(비율·청산 소요일·대차 수수료·가용주식·1개월 모멘텀) + 추이 4종(차트·표)."""
from contextlib import closing

import altair as alt
import pandas as pd
import streamlit as st

import chartpop

import db
import squeeze as sq
import ui_kit as ui


def _level(v, cuts, words):
    if v is None:
        return "-"
    for c, w in zip(cuts, words):
        if v >= c:
            return w
    return words[-1]


def _area(df: pd.DataFrame, x: str, y: str, color: str, title: str, fmt: str = ".1f", xtype: str = "T"):
    if df.empty:
        st.caption(f"{title}: 기록이 아직 없습니다(쌓이는 중).")
        return
    ch = alt.Chart(df).mark_area(line={"color": color}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color=color, offset=0),
                                                                                                    alt.GradientStop(color="rgba(0,0,0,0)", offset=1)], x1=1, x2=1, y1=0, y2=1),
                                 opacity=0.35, interpolate="monotone").encode(x=alt.X(f"{x}:{xtype}", title=None), y=alt.Y(f"{y}:Q", title=None),
                                                                              tooltip=[alt.Tooltip(f"{x}:{xtype}"), alt.Tooltip(f"{y}:Q", format=fmt)]).properties(height=170, title=title)
    chartpop.show(ch, key=f"sp_{y}", title=title, data=df)


def render(t: str) -> None:
    t = t.upper()
    r = next((x for x in sq.rows() if x["ticker"] == t), None)
    with closing(db.connect()) as conn:
        def q(sql, *a):
            try:
                return pd.DataFrame([dict(x) for x in conn.execute(sql, a)])
            except Exception:  # noqa: BLE001
                return pd.DataFrame()
        fin = q("SELECT date, short, total FROM finra_shvol WHERE symbol=? ORDER BY date", t)
        bday = q("SELECT date, open_avail, min_avail, max_fee FROM ibkr_borrow_day WHERE symbol=? ORDER BY date", t)
        hist = q("SELECT ts, avail, fee FROM ibkr_avail_hist WHERE symbol=? ORDER BY ts", t)
        si = q("SELECT date, si_pct, dtc, shares_short FROM short_interest WHERE ticker=? ORDER BY date", t)
    if r is None:
        r = {"score": None, "si_pct": None, "dtc": None, "fee": None, "avail": None, "stale": False, "r30": None, "si_date": None, "parts": {}}
    try:
        import watch_ui
        px = watch_ui.prices((t,)).get(t)
        if px is not None and len(px) > 22:
            c = px["Close"].dropna()
            r["r30"] = (float(c.iloc[-1]) / float(c.iloc[-22]) - 1) * 100
    except Exception:  # noqa: BLE001
        pass
    head = f'<span class="qk-sub">스퀴즈 점수</span> {ui.chip("-" if r["score"] is None else f"{r["score"]:g}점", "red" if (r["score"] or 0) >= 60 else "orange")}'
    st.markdown(head, unsafe_allow_html=True)
    htb = r["stale"] or r["avail"] == 0
    sv = None   # B단계 2026-10-27: 숏볼륨(장외 거래 중 공매도 표시 비율, FINRA) 카드 — 래빗스탁 '숏볼륨'과 같은 값
    if not fin.empty and fin.iloc[-1]["total"]:
        sv = {"date": fin.iloc[-1]["date"], "pct": float(fin.iloc[-1]["short"] or 0) / float(fin.iloc[-1]["total"]) * 100, "short": float(fin.iloc[-1]["short"] or 0)}
    ui.cards([{"t": "숏볼륨(장외 공매도 비중)", "v": "-" if sv is None else f"{sv['pct']:.1f}%", "s": "-" if sv is None else f"{sv['date']} · 공매도 {sv['short']:,.0f}주 (FINRA)",
               "accent": bool(sv and sv["pct"] >= 60)}])
    try:  # 📡 ChartExchange(2026-10-27): FTD · 공매도 잔고 일별 시계열 · 거래소 포함 숏볼륨
        import chartex
        with closing(db.connect()) as conn:
            chartex.ensure(conn)
            ftd = chartex.ftd_summary(conn, t)
            sis = chartex.si_series(conn, t)
            svx = chartex.sv_latest(conn, t)
        if ftd or not sis.empty or not svx.empty:
            st.markdown("**📡 숏 데이터(ChartExchange)**")
        if ftd:
            L, M = ftd["last"], ftd["max"]
            ui.cards([{"t": "FTD 최근(결제 실패 주식)", "v": f"{(L['fails'] or 0):,.0f}주", "s": f"{L['settle_date']} 결제일 · ${(L['notional'] or 0):,.0f} · 강제 매수 기한 T+35 {L['t35'] or '-'}", "accent": (L["fails"] or 0) >= 100_000},
                      {"t": "60일 최대 FTD", "v": f"{(M['fails'] or 0):,.0f}주", "s": f"{M['settle_date']} · 60일 합계 {ftd['total']:,.0f}주"},
                      {"t": "FTD 금액 합(60일)", "v": f"${ftd['notional'] / 1e3:,.0f}K", "s": "SEC 월 2회 공개, 약 2주 늦음"}])
        if not sis.empty:
            chartpop.line(sis.set_index("date")[["si_pct"]].rename(columns={"si_pct": "유통 대비 공매도 잔고(%)"}), key=f"cx_si_{t}", title=f"{t} 공매도 잔고 일별 추이(ChartExchange)", height=170, zero=True, fmt=".1f",
                          note="보고일 사이는 직전 보고값을 이월한 일별 시계열(ChartExchange). 점이 찍힌 날이 실제 보고일.")
        if not svx.empty:
            st.dataframe(svx.rename(columns={"date": "날짜", "total": "전체 거래량", "short_total": "숏볼륨(장외+거래소)", "finra_short": "장외 공매도", "finra_exempt": "장외 면제", "exch_short": "거래소 공매도", "short_pct": "숏볼륨 비중(%)"}),
                         hide_index=True, width="stretch", column_config={c: st.column_config.NumberColumn(format="%,.0f") for c in ("전체 거래량", "숏볼륨(장외+거래소)", "장외 공매도", "장외 면제", "거래소 공매도")} | {"숏볼륨 비중(%)": st.column_config.NumberColumn(format="%.1f")})
            st.caption("숏볼륨(장외+거래소) = 래빗스탁 '숏볼륨'과 같은 집계. 위의 'FINRA 장외' 카드는 장외(TRF)만이라 더 작게 보여요.")
    except Exception:  # noqa: BLE001
        pass
    ui.cards([{"t": "공매도 비율", "v": "-" if r["si_pct"] is None else f"{r['si_pct']:.2f}%", "s": _level(r["si_pct"], [30, 20, 10], ["매우 높음(≥30%)", "높음", "보통", "낮음"])
               + ("" if not r.get("si_date") else f" · {r['si_date']} 기준")},
              {"t": "청산 소요일", "v": "-" if r["dtc"] is None else f"{r['dtc']:.2f}일", "s": _level(r["dtc"], [10, 5, 2], ["극단적 · 청산 어려움", "높음", "보통", "낮음"])},
              {"t": "대차 수수료", "v": "-" if r["fee"] is None else f"{r['fee']:.2f}%", "s": _level(r["fee"], [100, 30, 10], ["빌리기 극히 어려움", "높음", "보통", "낮음"])},
              {"t": "대차 가용주식", "v": "0K" if htb else ("-" if r["avail"] is None else f"{r['avail'] / 1e3:,.0f}K"), "s": "HTB — 빌릴 주식 없음" if htb else "IBKR"},
              {"t": "가격 모멘텀", "v": "-" if r.get("r30") is None else f"{r['r30']:+.2f}%", "s": "1개월 주가 변동률"}])
    if (r["fee"] or 0) >= 50 or htb:
        st.warning(("대차 수수료 " + (f"{r['fee']:.1f}%" if r["fee"] is not None else "-") + " — 빌리는 비용이 매우 높아 공매도 포지션 유지 부담이 큽니다." if (r["fee"] or 0) >= 50 else "")
                   + (" 가용주식 0 — 새로 빌릴 주식이 없습니다(HTB)." if htb else ""))
    a, b = st.columns(2)
    with a:
        if not fin.empty:
            fin["공매도 비중(%)"] = fin["short"] / fin["total"] * 100
        _area(fin.rename(columns={"date": "날짜"}), "날짜", "공매도 비중(%)", "#E5484D", "공매도 거래 비중 추이(FINRA 장외)")
        if not fin.empty:
            st.dataframe(fin.sort_values("date", ascending=False).head(7).rename(columns={"date": "날짜", "short": "공매도", "total": "장외 거래"}), hide_index=True, width="stretch",
                         column_config={"공매도 비중(%)": st.column_config.NumberColumn(format="%.2f"), "공매도": st.column_config.NumberColumn(format="%,.0f"),
                                        "장외 거래": st.column_config.NumberColumn(format="%,.0f")})
    with b:
        _area(si.rename(columns={"date": "날짜", "si_pct": "공매도 비율(%)"}), "날짜", "공매도 비율(%)", "#F76B15", "공매도 잔고 추이(Float Short %)")
        if not si.empty:
            st.dataframe(si.sort_values("date", ascending=False).head(7).rename(columns={"date": "날짜", "si_pct": "Float %", "dtc": "청산일", "shares_short": "잔고 수량"}),
                         hide_index=True, width="stretch", column_config={"Float %": st.column_config.NumberColumn(format="%.2f"), "청산일": st.column_config.NumberColumn(format="%.2f"),
                                                                          "잔고 수량": st.column_config.NumberColumn(format="%,.0f")})
    c, d = st.columns(2)
    with c:
        _area(bday.rename(columns={"date": "날짜", "max_fee": "수수료(%)"}), "날짜", "수수료(%)", "#E5484D", "대차 수수료 추이(IBKR 연이율)")
        if not bday.empty:
            st.dataframe(bday.sort_values("date", ascending=False).head(7)[["date", "max_fee"]].rename(columns={"date": "날짜", "max_fee": "연이율(%)"}), hide_index=True, width="stretch")
    with d:
        if not hist.empty:
            _area(hist.rename(columns={"ts": "시각", "avail": "가용주식"}), "시각", "가용주식", "#3678F6", "대차 가용주식 추이(15분)", ",.0f")
            st.dataframe(hist.sort_values("ts", ascending=False).head(7).rename(columns={"ts": "시각", "avail": "빌릴 수 있는 주식", "fee": "수수료(%)"}), hide_index=True, width="stretch",
                         column_config={"빌릴 수 있는 주식": st.column_config.NumberColumn(format="%,.0f")})
        else:
            _area(bday.rename(columns={"date": "날짜", "min_avail": "가용주식"}), "날짜", "가용주식", "#3678F6", "대차 가용주식 추이(일별 최저)", ",.0f")
    if r.get("parts"):
        st.markdown(ui.box("점수 구성", [f"{k} {v:.1f}" for k, v in r["parts"].items()], "#8E4EC6"), unsafe_allow_html=True)
