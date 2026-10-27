"""🏢 기업 분석 데이터 — 김곰 기업분석 형식(1 회사 · 2 진입 판단 · 2-1 희석 물량 · 3 런웨이 · 4 목적 · 5 예정 이벤트 · 6 보유자·내부자 · 8 타임라인).

우리 데이터(SEC 주식 수·분할 이력·회사 압박·물량 장부·리포트·상장유지 통지·일정·Form 4·공시)로 규칙에 따라 채운다. 서술형 판단은 🤖 AI 요약·🧾 덕구 스캔.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, timedelta

import db


def split_chain(t: str) -> dict:
    """역분할 이력(최신순) · 횟수 · 누적 비율 · 3년 안 횟수."""
    rep = db.get_report(t) or {}
    sp = {x["date"]: float(x["ratio"]) for x in (rep.get("company") or {}).get("splits") or [] if float(x.get("ratio", 1)) < 1}
    try:
        with closing(db.connect()) as conn:
            for d, r in conn.execute("SELECT date, ratio FROM rs_events WHERE ticker=?", (t,)):
                sp.setdefault(d, float(r))
    except Exception:  # noqa: BLE001
        pass
    items = sorted(sp.items(), reverse=True)
    cum = 1.0
    for _, r in items:
        cum *= 1 / r
    y3 = (date.today() - timedelta(days=365 * 3)).isoformat()
    return {"items": [{"date": d, "text": f"1:{round(1 / r):g}"} for d, r in items], "count": len(items), "cum": cum, "n3y": sum(1 for d, _ in items if d >= y3)}


def ladder(t: str, price: float | None, pr: dict | None, oh_rows: list[dict], df=None) -> list[dict]:
    """가격 사다리: 위에서 아래로(높은 가격 먼저). 현재가는 ★."""
    lv = []
    if price:
        lv.append({"price": price, "label": "★ 현재가", "note": "", "kind": "now"})
    for n, v, _p in (pr or {}).get("targets") or []:
        lv.append({"price": v, "label": n, "note": {"$1 상장 유지": "나스닥 최저 호가 기준", "baby shelf 탈출": "공개유통시총 $75M — 선반 발행 한도 해제",
                                                     "시가총액 기준 회복": "상장증권 시가총액 기준 충족"}.get(n, ""), "kind": "target"})
    for o in oh_rows:
        if o.get("price"):
            lv.append({"price": float(o["price"]), "label": f"{o.get('kind', '')} 행사·전환가", "note": f"{o.get('qty_m') or '-'}M주 · {o.get('status') or ''}"
                       + (f" · 만기 {o['expiry']}" if o.get("expiry") else ""), "kind": "overhang"})
    if df is not None and not df.empty:
        c = df["Close"].dropna().tail(60)
        if len(c):
            lv.append({"price": float(df["High"].dropna().tail(60).max()), "label": "60일 고점", "note": "직전 고점(분할 반영값)", "kind": "ref"})
            lv.append({"price": float(df["Low"].dropna().tail(60).min()), "label": "60일 저점(지지선 후보)", "note": "", "kind": "ref"})
    for x in lv:
        x["pct"] = None if not price else (x["price"] / price - 1) * 100
    return sorted(lv, key=lambda x: -x["price"])


def runway(t: str) -> dict:
    rw = (db.get_report(t) or {}).get("runway") or {}
    if rw.get("cash") is None:  # 종목 리포트가 없으면 🪙 런웨이 저장소(SEC 재무 · 지금 추정 현금) — 예전엔 전부 '-'
        try:
            from contextlib import closing as _cl
            import runway as _rwm
            with _cl(db.connect()) as c:
                rn = _rwm.now(t, c)
        except Exception:  # noqa: BLE001
            rn = None
        if rn:
            note = _rwm.label(rn)
            end = None if rn.get("stale") else rn.get("floor")
            return {"months": None if rn.get("stale") else rn.get("runway_now"), "cash": rn.get("cash_now") if not rn.get("stale") else rn.get("cash"),
                    "burn": rn.get("monthly_burn"), "asof": rn.get("cash_asof"), "end": end, "note": note,
                    "dday": None if not end else (date.fromisoformat(end) - date.today()).days}
    m, asof = rw.get("runway_months"), rw.get("cash_asof")
    end = None
    if m is not None and asof:
        try:
            import runway as _rwm
            end = _rwm.months_to_date(date.fromisoformat(asof), m)  # 아주 긴 런웨이에서 날짜 계산이 넘쳐 화면이 멈추지 않게
        except (ValueError, TypeError):
            end = None
    return {"months": m, "cash": rw.get("cash"), "burn": rw.get("monthly_burn"), "asof": asof, "end": end,
            "dday": None if not end else (date.fromisoformat(end) - date.today()).days}


def purposes(t: str, price: float | None, pr: dict | None, oh_rows: list[dict], rwy: dict, ln: dict | None, ev: list[dict]) -> list[dict]:
    """회사가 주가를 움직일 이유(목적)별 — 필요한 주가 · 기한 · 근거."""
    out = []
    tg = {n: v for n, v, _ in (pr or {}).get("targets") or []}

    def pct(v):
        return None if not (price and v) else (v / price - 1) * 100
    if rwy.get("months") is not None and rwy["months"] < 12:
        need = tg.get("baby shelf 탈출")
        out.append({"title": "현금 조달", "urgency": "급함" if rwy["months"] < 3 else "필요", "need": need, "need_pct": pct(need),
                    "deadline": rwy.get("end"), "why": f"런웨이 {rwy['months']:.1f}개월(현금 ${(rwy.get('cash') or 0) / 1e6:,.2f}M · 월 소진 ${(rwy.get('burn') or 0) / 1e6:,.2f}M)"
                    + ("" if not need else " — baby shelf 를 벗어나야 선반 발행 한도가 풀림")})
    if ln or (price and price < 1):
        kind = ln["kinds"][0] if ln else "주가 $1 기준"
        need = tg.get("시가총액 기준 회복") if kind == "상장증권 시가총액 기준" else (1.0 if kind == "주가 $1 기준" else None)
        out.append({"title": "상장 유지", "urgency": "기한 있음" if ln else "주의", "need": need, "need_pct": pct(need), "deadline": None if not ln else ln["deadline"],
                    "why": (f"{kind} 미달 통지 {ln['filed']}" + (f" · 기준 {ln['threshold']}" if ln.get("threshold") else "")) if ln else "주가 $1 미만"})
    locked = [o for o in oh_rows if str(o.get("status", "")) in ("잠김", "락업")]
    lock_ev = [e for e in ev if any(k in e.get("kind", "") for k in ("락업", "만기"))]
    if locked or lock_ev:
        out.append({"title": "물량 출회", "urgency": "예정", "need": None, "need_pct": None, "deadline": min((e["date"] for e in lock_ev), default=None),
                    "why": ", ".join([f"{o.get('kind')} {o.get('qty_m') or '-'}M주 잠김" for o in locked][:3] + [f"{e['date']} {e['kind']}" for e in lock_ev][:3])})
    cbs = [o for o in oh_rows if "전환" in str(o.get("kind", "")) and o.get("price")]
    if cbs:
        v = min(float(o["price"]) for o in cbs)
        out.append({"title": "부채 주식결제", "urgency": "가능", "need": v, "need_pct": pct(v), "deadline": None,
                    "why": f"전환사채 전환가 ${v:.4f} — 주가가 이 근처면 빚을 주식으로 갚는(물량 출회) 유인"})
    return out


def holders(t: str) -> dict:
    with closing(db.connect()) as conn:
        def q(sql, p):
            try:
                return [dict(r) for r in conn.execute(sql, p)]
            except Exception:  # noqa: BLE001
                return []
        ins = q("""SELECT owner, title, SUM(CASE WHEN code='P' THEN value ELSE 0 END) AS buy, SUM(CASE WHEN code='S' THEN value ELSE 0 END) AS sell,
                   MAX(date) AS last, MAX(after_shares) AS after FROM insider_tx WHERE ticker=? GROUP BY owner, title ORDER BY last DESC""", (t,))
        big = q("SELECT COALESCE(filed, substr(updated,1,10)) AS d, form, company, url FROM sec_feed WHERE ticker=? AND (form LIKE 'SC 13%' OR form LIKE 'SCHEDULE 13%') ORDER BY d DESC", (t,))
        big += q("SELECT filed AS d, form, '' AS company, '' AS url FROM sec_hist WHERE ticker=? AND (form LIKE 'SC 13%' OR form LIKE 'SCHEDULE 13%') ORDER BY filed DESC LIMIT 8", (t,))
    seen, b2 = set(), []
    for x in big:
        k = (x["d"], x["form"])
        if k not in seen:
            seen.add(k)
            b2.append(x)
    return {"insiders": ins, "big": b2[:8]}


def build(t: str, df=None) -> dict:
    import events_brief
    import glance
    import listing
    import watch
    t = t.upper()
    g = glance.build(t, df)
    pr = g.get("pressure")
    try:
        oh = watch.overhang_rows(t).to_dict("records")
    except Exception:  # noqa: BLE001
        oh = []
    rwy = runway(t)
    ln = listing.latest(t)
    with closing(db.connect()) as conn:
        try:
            ev = [dict(r) for r in conn.execute("SELECT date, kind, title FROM events WHERE ticker=? AND date >= ? ORDER BY date", (t, date.today().isoformat()))]
        except Exception:  # noqa: BLE001
            ev = []
        try:  # ⏰ 시계·반응 규칙(A단계 2026-10-28): PR 소화력 · 하락 원인 · 보고 기한(캐시) · 사다리 보강(50일선 · PR 고점/직전 종가)
            import clock
            ck = clock.rule_block(conn, t, g["price"], df)
        except Exception:  # noqa: BLE001
            ck = {}
    for e in ev:
        e["dday"] = (date.fromisoformat(e["date"]) - date.today()).days
    return {**g, "chain": split_chain(t), "ladder": sorted(ladder(t, g["price"], pr, oh, df) + list(ck.get("levels") or []), key=lambda x: -x["price"]), "clock": ck, "overhang": oh, "runway": rwy,
            "purposes": purposes(t, g["price"], pr, oh, rwy, ln, ev), "events_ahead": ev, "holders": holders(t), "timeline": events_brief.build(t, days=365, ahead=0)}


def memo_get(t: str) -> str:
    m = db.get_meta(f"memo_{t.upper()}")
    return (m or {}).get("value") or ""


def memo_set(t: str, text: str) -> None:
    db.set_meta(f"memo_{t.upper()}", text)
