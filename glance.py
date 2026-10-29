"""📌 한눈에 — 래빗스탁·스크리닝 보고서처럼: 기본 정보 → ✅ 충족 신호 → 📌 이벤트 → ⚠️ 리스크 플래그 → 📝 최종 정리 (+ 💬 커뮤니티는 참고만).

신호·리스크는 우리 데이터로 규칙에 따라 고른다. 커뮤니티 심리는 점수·판정에 넣지 않는다.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, timedelta

import db


def build(t: str, df=None, guest: bool | None = None) -> dict:
    """df: 6개월 일봉(있으면 3개월 수익률·60일 고점 격차·52주 저점 근처 계산). guest: 방문객이면 price 를 전일 종가로(토스 데이터 정책 A안, 2026-10-30) — None 이면 화면 상태로 판단."""
    import events_brief
    import multisignal
    import shares
    t = t.upper()
    with closing(db.connect()) as conn:
        s = conn.execute("SELECT price, float_shares, dilution_status, volume_mult FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        s = dict(s) if s else {}
        import access
        guest = access.is_guest() if guest is None else guest
        price_label = "현재가"
        if guest:   # 👥 A안: 스냅샷의 당일 현재가(토스 1분봉) 대신 전일 종가(야후 일봉 확정 봉) — 헤더·한 장 요약·가격 사다리 % 가 같이 바뀜
            import guestpx
            gp = guestpx.one(t, conn=conn)
            s["price"] = gp["close"] if gp else None
            price_label = guestpx.LABEL

        def q1(sql, p):
            try:
                r = conn.execute(sql, p).fetchone()
                return r
            except Exception:  # noqa: BLE001
                return None
        meta = q1("SELECT name, sic_desc, themes FROM ticker_meta WHERE ticker=?", (t,))
        acc = q1("SELECT data FROM accum WHERE ticker=? AND period='주간' ORDER BY date DESC LIMIT 1", (t,))
        acc = json.loads(acc[0]) if acc else None
        try:
            import regsho
            sho = regsho.streaks(conn).get(t)
        except Exception:  # noqa: BLE001
            sho = None
        try:
            import squeeze
            sq = next((r for r in squeeze.rows() if r["ticker"] == t), None)
        except Exception:  # noqa: BLE001
            sq = None
        ins = q1("SELECT SUM(value), COUNT(DISTINCT owner) FROM insider_tx WHERE ticker=? AND code='P' AND date >= ?", (t, (date.today() - timedelta(days=60)).isoformat()))
        news = [r[0] for r in (conn.execute("SELECT sentiment FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) >= ?",
                                             (t, (date.today() - timedelta(days=14)).isoformat())).fetchall() if q1("SELECT name FROM sqlite_master WHERE name='sec_feed'", ()) else [])]
        try:
            import pressure
            pr = pressure.evaluate(t, conn, None, df)
        except Exception:  # noqa: BLE001
            pr = None
        rs2 = [r[0] for r in (conn.execute("SELECT date FROM rs_events WHERE ticker=? AND date >= ?", (t, (date.today() - timedelta(days=730)).isoformat())).fetchall()
                               if q1("SELECT name FROM sqlite_master WHERE name='rs_events'", ()) else [])]
    rep = db.get_report(t) or {}
    rs2 = sorted(set(rs2) | {x["date"] for x in (rep.get("company") or {}).get("splits") or [] if x.get("ratio", 1) < 1 and x["date"] >= (date.today() - timedelta(days=730)).isoformat()})
    price = s.get("price")
    sh, sh_tag = shares.best(t, s.get("float_shares"))
    mcap = price * sh if price and sh else None
    to = shares.turnover(t, None, s.get("float_shares"))
    ms = multisignal.collect().get(t, [])
    r3m = hi60 = near_low = None
    if df is not None and not df.empty:
        c = df["Close"].dropna()
        if len(c) > 63:
            r3m = (float(c.iloc[-1]) / float(c.iloc[-64]) - 1) * 100
        if len(c) > 5:
            hi60 = float(df["High"].dropna().tail(60).max())
            near_low = float(c.iloc[-1]) <= float(df["Low"].dropna().min()) * 1.15
    ok, risk = [], []
    if acc:
        ok.append(f"거래량 급증 · {acc['top_day']} ×{acc['top_vr']:.1f}({acc['top_chg']:+.1f}%) · {acc['level']} 합계 {acc['score']:g}" + (" · 뉴스·공시 없음" if not acc.get("news") else ""))
    elif s.get("volume_mult") and s["volume_mult"] >= 3:
        ok.append(f"거래량 급증 · 평소의 {s['volume_mult']:.1f}배")
    yahoo = "야후" in (sh_tag or "")  # 주식 수가 SEC 표지가 아니라 야후 유통주식 → 병합·발행 직후 크게 틀릴 수 있어 신호로 세지 않음
    if to and to["pct"] >= 30 and not yahoo:
        ok.append(f"회전율 {to['pct']:.0f}% — " + ("하루 거래량이 주식 전체를 넘음(극단적 손바뀜)" if to["pct"] >= 100 else "손바뀜 활발"))
    if sh and sh <= 5e6 and not yahoo:
        ok.append(f"초소형 주식 수 · 약 {sh / 1e6:.2f}M주({sh_tag}) — 적은 매수에도 크게 움직일 수 있는 구조")
    if yahoo and sh and (sh <= 5e6 or (to and to["pct"] >= 30)):
        risk.append(f"주식 수 확인 필요 — 약 {sh / 1e6:.2f}M주는 야후 유통주식 값(SEC 표지 아님) · 병합·발행 직후엔 크게 틀릴 수 있어 회전율·초소형 신호로 세지 않았어요")
    if (r3m is not None and r3m <= -70) or near_low:
        ok.append("과매도 · " + ("" if r3m is None else f"3개월 {r3m:+.0f}% · ") + ("52주(6개월) 저점 부근" if near_low else ""))
    if hi60 and price and hi60 / price >= 3:
        ok.append(f"직전 고점 격차 · 60일 고점 ${hi60:.2f} 대비 현재 ${price:.4f} ({(hi60 / price - 1) * 100:+.0f}% 여지) — 병합 전후 가격은 분할 반영값")
    if sq and sq.get("score", 0) >= 50:
        ok.append(f"숏커버링 압력 · 스퀴즈 {sq['score']:.0f}점" + ("" if sq.get("si_pct") is None else f" · 공매도 잔고 {sq['si_pct']:.0f}%") + ("" if sq.get("dtc") is None else f" · 청산 {sq['dtc']:.1f}일"))
    if sho:
        ok.append(f"Reg SHO {sho}일째 — 공매도 결제 실패 누적" + (" · 강제 상환 구간" if sho >= 13 else ""))
    if ins and ins[0]:
        ok.append(f"내부자 장내 매수 · ${ins[0]:,.0f} · {ins[1]}명(60일)")
    if any(x in ("호재", "약한 호재") for x in news):
        ok.append("최근 2주 호재 공시")
    if len(ms) >= 2:
        ok.append(f"멀티 시그널 {len(ms)}개 · {', '.join(ms[:5])}")
    dil = s.get("dilution_status")
    if dil in ("ATM", "ELOC", "CB"):
        risk.append({"ATM": "ATM 열림 — 주가가 오르면 바로 팔 수 있음", "ELOC": "ELOC — 정해진 한도까지 계속 주식을 넘길 수 있음", "CB": "전환사채(TOXIC) — 주가가 내릴수록 주식이 더 풀림"}[dil])
    sd = shares.get(t) or {}
    if sd.get("warn"):
        risk.append("추가 발행 가능성 · 주식 수 기준일 뒤 발행 공시: " + ", ".join(sd.get("issuance_after", [])[:3]))
    if len(rs2) >= 2:
        risk.append(f"재병합 반복 · 최근 2년 역분할 {len(rs2)}회({', '.join(rs2[-3:])}) — 발행 후 병합이 되풀이될 수 있음")
    if pr:
        for a, txt, strong in pr["press"]:
            if a in ("상장 유지", "런웨이") and strong:
                risk.append(f"{a} · {txt}")
        risk += [w for w in pr["warn"] if "상습 희석" in w or "출회" in w]
    if any(x in ("악재", "주의") for x in news):
        risk.append("최근 2주 악재·주의 공시")
    ev = events_brief.build(t, days=120)
    return {"ticker": t, "name": meta[0] if meta else "", "sector": (meta[1] if meta else "") or "", "themes": json.loads(meta[2]) if meta and meta[2] else [],
            "price": price, "price_label": price_label, "shares": sh, "shares_tag": sh_tag, "mcap": mcap, "turnover": to, "ok": ok, "risk": risk, "events": ev[:10], "pressure": pr}


def render(t: str) -> None:
    import streamlit as st

    import aisummary
    import community
    import ui_kit as ui
    import watch_ui
    df = watch_ui.prices((t.upper(),)).get(t.upper())
    g = build(t, df)
    rows = [("가격" if g.get("price_label", "현재가") == "현재가" else g["price_label"], "-" if not g["price"] else f"${g['price']:.4f}"), ("시가총액(추정)", "-" if not g["mcap"] else f"약 ${g['mcap'] / 1e6:,.1f}M"),
            ("주식 수(추정)", "-" if not g["shares"] else f"약 {g['shares'] / 1e6:,.2f}M주"), ("회전율", "-" if not g["turnover"] else f"{g['turnover']['pct']:.0f}%"),
            ("업종 · 테마", (g["sector"] or "-") + ("" if not g["themes"] else " · " + ", ".join(g["themes"][:3])))]
    st.markdown(ui.kv(rows), unsafe_allow_html=True)
    st.caption(f"주식 수 출처: {g['shares_tag']}")
    l, r = st.columns(2)
    l.markdown(ui.box(f"✅ 충족 신호 {len(g['ok'])}", g["ok"] or ["뚜렷한 신호 없음"], "#30A46C"), unsafe_allow_html=True)
    r.markdown(ui.box(f"⚠️ 리스크 플래그 {len(g['risk'])}", g["risk"] or ["확인된 큰 위험 없음(공시 원문은 직접 확인)"], "#E5484D"), unsafe_allow_html=True)
    st.markdown(ui.box("📌 이벤트", [f"{e['icon']} {e['date'][5:]} {e['text']}" for e in g["events"]] or ["최근 120일 기록 없음"], "#3678F6"), unsafe_allow_html=True)
    s = aisummary.latest(t)
    summary = str(s.get("한줄요약", "")) if s else ""
    if not summary:
        summary = (f"충족 신호 {len(g['ok'])}개, 위험 {len(g['risk'])}개가 함께 있어요. "
                   + ("위험이 신호보다 많아 보수적으로 볼 필요가 있어요." if len(g["risk"]) > len(g["ok"]) else "신호가 위험보다 많지만 위험 항목은 원문으로 꼭 확인하세요."))
    st.markdown(ui.box("📝 최종 정리", [summary, "점수·신호는 규칙 기반 추정이며 투자 권유가 아닙니다."], "#8E4EC6"), unsafe_allow_html=True)
    if st.button("💬 커뮤니티 심리 보기(참고 · 점수 미반영)", key=f"cm_{t}"):
        c = community.fetch(t)
        if c.get("ok"):
            st.info(f"스톡트윗츠 최근 메시지 {c['n']}개 · 강세 {c['bull']} · 약세 {c['bear']}" + ("" if c.get("bull_pct") is None else f" · 강세 비율 {c['bull_pct']:.0f}%")
                    + ("" if not c.get("watchers") else f" · 관심 등록 {c['watchers']:,}명") + " — 커뮤니티 열기는 고점 신호일 때도 많아요.")
        else:
            st.caption(f"커뮤니티 심리를 가져오지 못했어요({c.get('err')}). 스톡트윗츠에서 직접 확인하세요.")
