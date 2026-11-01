"""📄 종목 서랍 자료(2026-11-01, 김곰 G1.1 서랍 참고 · docs/kimgom_radar_compare_2026-11-01.md 6절) — 화면(report_dialog)이 그리는 값을 규칙으로 계산.

· supply_status: 희석 수단마다 '확인됨 / 1년 공시에 없음 / 모름'을 나눠서(예전 희석 플래그는 '아님'이 없는 건지 모르는 건지 구분이 안 됐음)
· ladder: 한 줄 가격 사다리(30일 최저 · 지금 · +30% · +50% · 30일 고점 · 물량 장부 행사가 · $1 · baby shelf 탈출가)
· unlock: 지금 / +30% / +50% 가격에서 행사가 아래가 되는(=팔 수 있게 되는) 물량 장부 수량
· causes: 최근 하락의 '원인 후보'(확정 아님) — 급등 뒤 되돌림 · 조달 서류 · 부채 · 결제 실패 · 상장 위험 · 병합 · 악재 공시
· signals / history: 이 종목에 난 우리 신호와 결과(🏆) · 상태 변화(Reg SHO 등재/해제 · 공식 잔고 · 큰 등락 · 핵심 공시 · ⭐ 순위)
김곰의 '일자별 숏 집단'(숏 원가대)은 2년 검증에서 2026 에 실패해 넣지 않음(docs/squeeze_validation_2026-11-01.md)."""
from __future__ import annotations

from datetime import date, timedelta

RAISE_REG = ("S-1", "F-1", "S-3", "F-3", "S-1/A", "F-1/A", "S-3/A", "F-3/A")
DROP_DAY, DROP_5D = -10.0, -15.0          # 하락 원인 후보를 보여 줄 조건: 하루 −10%↓ 또는 5거래일 −15%↓
SURGE_X = 1.8                              # 20거래일 최저→최고 1.8배↑ = 급등


def _q(conn, sql, *a) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, a)]
    except Exception:  # noqa: BLE001 (표 없음)
        return []


def bars(conn, t: str, n: int = 60) -> list[dict]:
    """최근 n 거래일 일봉(오래된 순)."""
    return list(reversed(_q(conn, "SELECT date, high, low, close, volume FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT ?", t.upper(), n)))


def filings(conn, t: str, days: int = 365) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    return _q(conn, "SELECT accession, form, filed, COALESCE(items,'') AS items FROM sec_hist WHERE ticker=? AND filed >= ? ORDER BY filed DESC", t.upper(), since)


def edgar_url(t: str, form: str = "") -> str:
    """공시 목록 링크(CIK 가 없어도 티커로 열림)."""
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={t.upper()}&type={form.split('/')[0]}&dateb=&owner=include&count=40"


def _md(d: str) -> str:
    return f"{int(d[5:7])}/{int(d[8:10])}" if d and len(d) >= 10 else (d or "")


def _sh(n) -> str:
    """주식 수 짧게(만·백만)."""
    n = float(n or 0)
    return f"{n / 1e6:,.1f}M" if n >= 1e6 else f"{n / 1e4:,.1f}만" if n >= 1e4 else f"{n:,.0f}"


def supply_status(conn, t: str) -> list[dict]:
    """[{name, state, color, detail}] — color: red 확인됨(위험) · orange 주의 · green 1년 공시에 없음 · gray 모름."""
    t = t.upper()
    fs = filings(conn, t)
    led = _q(conn, "SELECT kind, qty_m, price, status FROM overhang WHERE ticker=?", t)
    snap = (_q(conn, "SELECT float_shares, dilution_status, price FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", t) or [{}])[0]
    pick = lambda pred: [f for f in fs if pred(f)]
    out = []
    reg = pick(lambda f: f["form"].upper() in RAISE_REG)
    eff = pick(lambda f: f["form"].upper().startswith("EFFECT"))
    if reg:
        out.append({"name": "공모·재판매 등록(S-1·S-3)", "state": "확인됨", "color": "red",
                    "detail": " · ".join(f"{f['form']} {_md(f['filed'])}" for f in reg[:3]) + (f" · 효력(EFFECT) {_md(eff[0]['filed'])}" if eff else " · 효력(EFFECT) 미확인")})
    else:
        out.append({"name": "공모·재판매 등록(S-1·S-3)", "state": "1년 공시에 없음", "color": "green", "detail": "최근 1년 S-1·F-1·S-3·F-3 0건"})
    atm = pick(lambda f: f["form"].upper().startswith("424B5")) or [x for x in led if "ATM" in str(x.get("kind")).upper()]
    if snap.get("dilution_status") == "ATM" or atm:
        out.append({"name": "ATM(424B5 보충서)", "state": "확인됨", "color": "red",
                    "detail": " · ".join(f"424B5 {_md(f['filed'])}" for f in atm[:2] if "filed" in f) or "희석 상태 ATM"})
    else:
        out.append({"name": "ATM(424B5 보충서)", "state": "1년 공시에 없음", "color": "green", "detail": "최근 1년 424B5 0건"})
    off = pick(lambda f: f["form"].upper().startswith(("424B1", "424B4")))
    if off:
        out.append({"name": "공모 가격 확정(424B4)", "state": "확인됨", "color": "orange", "detail": " · ".join(f"{f['form']} {_md(f['filed'])}" for f in off[:2])})
    debt = pick(lambda f: f["form"].upper().startswith("8-K") and "2.03" in f["items"])
    pipe = pick(lambda f: f["form"].upper().startswith("8-K") and "3.02" in f["items"])
    cb = [x for x in led if any(k in str(x.get("kind")).upper() for k in ("CB", "CONV", "전환", "NOTE"))]
    if debt or cb or snap.get("dilution_status") == "CB":
        out.append({"name": "부채·전환사채", "state": "확인됨", "color": "orange",
                    "detail": " · ".join([f"8-K 2.03 {_md(f['filed'])}" for f in debt[:2]] + [f"장부 {x['kind']}" for x in cb[:2]]) or "희석 상태 CB"})
    else:
        out.append({"name": "부채·전환사채", "state": "모름", "color": "gray", "detail": "8-K 2.03·물량 장부 기록 없음(없다는 뜻은 아님)"})
    if pipe:
        out.append({"name": "사모 발행(8-K 3.02)", "state": "확인됨", "color": "red", "detail": " · ".join(f"8-K 3.02 {_md(f['filed'])}" for f in pipe[:2])})
    wr = [x for x in led if any(k in str(x.get("kind")).upper() for k in ("WARRANT", "워런트", "PFW"))]
    out.append({"name": "워런트", "state": "확인됨" if wr else "모름", "color": "orange" if wr else "gray",
                "detail": " · ".join(f"{x['qty_m'] or 0:g}M주 @${x['price'] or 0:g}" for x in wr[:3]) if wr else ("물량 장부 비어 있음" if not led else "장부에 워런트 없음")})
    rs = _q(conn, "SELECT date, ratio FROM rs_events WHERE ticker=? ORDER BY date DESC LIMIT 2", t)
    up = _q(conn, "SELECT date, title FROM events WHERE ticker=? AND kind='역분할 시행' AND date >= ? ORDER BY date LIMIT 1", t, date.today().isoformat())
    c14 = pick(lambda f: f["form"].upper().startswith(("DEF 14C", "PRE 14C")))
    if up or rs or c14:
        parts = [f"예정 {_md(up[0]['date'])} {up[0]['title']}" for _ in up[:1]] + [f"{r['date']} 1:{round(1 / r['ratio']):g}" for r in rs[:1] if r.get("ratio")] + \
                [f"동의서(14C) {_md(f['filed'])}" for f in c14[:2]]
        out.append({"name": "주식 병합", "state": "예정" if up else "이력 있음", "color": "red" if up else "orange", "detail": " · ".join(parts)})
    px = snap.get("price")
    fl = snap.get("float_shares")
    if px and fl:
        pfv = px * fl
        out.append({"name": "Baby shelf(공개유통 $75M 미만)", "state": "대상" if pfv < 75e6 else "아님", "color": "orange" if pfv < 75e6 else "green",
                    "detail": f"유통 시총 ≈ ${pfv / 1e6:,.1f}M"})
    lst = pick(lambda f: f["form"].upper().startswith("8-K") and "3.01" in f["items"] and f["filed"] >= (date.today() - timedelta(days=180)).isoformat())
    out.append({"name": "상장 위험(8-K 3.01)", "state": "확인됨" if lst else "6개월 공시에 없음", "color": "red" if lst else "green",
                "detail": " · ".join(f"8-K 3.01 {_md(f['filed'])}" for f in lst[:2]) if lst else "최근 6개월 상장 기준 미달 통지 0건"})
    return out


def ladder(conn, t: str, price: float | None = None) -> list[dict]:
    """[{label, price, kind}] 낮은 값부터 — kind: now·move·range·supply·line."""
    t = t.upper()
    b = bars(conn, t, 30)
    px = price or (b[-1]["close"] if b else None)
    if not px:
        return []
    pts = [{"label": "지금", "price": px, "kind": "now"}, {"label": "+30%", "price": px * 1.3, "kind": "move"}, {"label": "+50%", "price": px * 1.5, "kind": "move"}]
    if b:
        lo = min(x["close"] for x in b if x["close"])
        hi = max(x["high"] or x["close"] for x in b)
        if lo < px * 0.97:
            pts.append({"label": "30일 최저", "price": lo, "kind": "range"})
        if hi > px * 1.03:
            pts.append({"label": "30일 고점", "price": hi, "kind": "range"})
    for x in _q(conn, "SELECT kind, price FROM overhang WHERE ticker=? AND price > 0 AND COALESCE(status,'') NOT IN ('만료','소진','closed')", t):
        if px * 0.3 <= x["price"] <= px * 3:
            pts.append({"label": f"{x['kind']} 행사가", "price": x["price"], "kind": "supply"})
    if px < 1.5:
        pts.append({"label": "$1 상장 유지", "price": 1.0, "kind": "line"})
    try:
        import pressure
        for nm, tp, _ in (pressure.evaluate(t, conn, px).get("targets") or []):
            if "baby" in nm and tp and px * 0.3 <= tp <= px * 4:
                pts.append({"label": "baby shelf 탈출", "price": tp, "kind": "line"})
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for p in sorted(pts, key=lambda p: p["price"]):
        k = (p["label"], round(p["price"], 4))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def unlock(conn, t: str, price: float | None) -> list[dict] | None:
    """[{at, label, qty_m, n}] 지금·+30%·+50% 가격에서 행사가 이하(팔 수 있는) 물량 장부 수량 합. 장부가 비면 None."""
    led = [x for x in _q(conn, "SELECT kind, qty_m, price FROM overhang WHERE ticker=? AND COALESCE(status,'') NOT IN ('만료','소진','closed')", t.upper()) if x["qty_m"]]
    if not led or not price:
        return None
    out = []
    for lab, m in (("지금", 1.0), ("+30%", 1.3), ("+50%", 1.5)):
        hit = [x for x in led if x["price"] is not None and x["price"] <= price * m]
        out.append({"label": lab, "at": price * m, "qty_m": sum(x["qty_m"] for x in hit), "n": len(hit)})
    return out


def causes(conn, t: str) -> list[dict]:
    """최근 하락의 원인 후보 [{title, why, next}] — 하루 −10%↓ 또는 5거래일 −15%↓ 일 때만. 확정이 아니라 '같이 볼 것' 목록."""
    t = t.upper()
    b = bars(conn, t, 25)
    if len(b) < 6:
        return []
    c = [x["close"] for x in b]
    d1 = (c[-1] / c[-2] - 1) * 100 if c[-2] else 0
    d5 = (c[-1] / c[-6] - 1) * 100 if c[-6] else 0
    if d1 > DROP_DAY and d5 > DROP_5D:
        return []
    out = []
    w = b[-20:]
    lo_i = min(range(len(w)), key=lambda i: w[i]["close"])
    hi_i = max(range(lo_i, len(w)), key=lambda i: w[i]["high"] or w[i]["close"])
    lo, hi = w[lo_i]["close"], (w[hi_i]["high"] or w[hi_i]["close"])
    if lo and hi / lo >= SURGE_X and hi_i < len(w) - 1:
        vmax = max(x["volume"] or 0 for x in w)
        out.append({"title": "급등 뒤 되돌림(차익 실현)", "why": f"{_md(w[lo_i]['date'])} ${lo:.2f} → {_md(w[hi_i]['date'])} ${hi:.2f}(+{(hi / lo - 1) * 100:.0f}%)"
                    + (f" · 오늘 거래량은 최대일의 {(w[-1]['volume'] or 0) / vmax * 100:.0f}%" if vmax else ""), "next": "고점 대비 위치 · 다음 지지 가격"})
    fs = filings(conn, t, 120)
    reg = [f for f in fs if f["form"].upper() in RAISE_REG or f["form"].upper().startswith(("424B", "EFFECT"))]
    if reg:
        out.append({"title": "조달 수단 대기·실행", "why": " · ".join(f"{f['form']} {_md(f['filed'])}" for f in reg[:3]), "next": "효력(EFFECT)·424B 가격·발행 주식 수"})
    debt = [f for f in fs if f["form"].upper().startswith("8-K") and ("2.03" in f["items"] or "3.02" in f["items"])]
    if debt:
        out.append({"title": "부채·사모 발행", "why": " · ".join(f"8-K {('2.03' if '2.03' in f['items'] else '3.02')} {_md(f['filed'])}" for f in debt[:2]), "next": "전환 가격·만기·할인율"})
    sho = None
    try:
        import regsho
        sho = regsho.streaks(conn).get(t)
    except Exception:  # noqa: BLE001
        pass
    ftd = _q(conn, "SELECT date FROM pred_outcomes WHERE ticker=? AND source='cx_ftd_spike' AND date >= ? LIMIT 1", t, (date.today() - timedelta(days=20)).isoformat())
    if sho or ftd:
        out.append({"title": "결제 실패 지속", "why": " · ".join(([f"Reg SHO {sho}일 연속"] if sho else []) + (["FTD 급증"] if ftd else [])), "next": "공식 잔고 다음 공개 · 대차 방향"})
    lst = [f for f in fs if f["form"].upper().startswith("8-K") and "3.01" in f["items"]]
    if lst:
        out.append({"title": "상장 기준 미달", "why": f"8-K 3.01 {_md(lst[0]['filed'])}", "next": "회복 기한 · 병합 안건"})
    rs = _q(conn, "SELECT date FROM rs_events WHERE ticker=? AND date >= ?", t, (date.today() - timedelta(days=30)).isoformat())
    up = _q(conn, "SELECT date FROM events WHERE ticker=? AND kind='역분할 시행' AND date >= ? LIMIT 1", t, date.today().isoformat())
    if rs or up:
        out.append({"title": "주식 병합 전후", "why": (f"병합 {_md(rs[0]['date'])} 실행" if rs else f"병합 예정 {_md(up[0]['date'])}"), "next": "병합 뒤 $1 여유 · 추가 조달"})
    bad = _q(conn, "SELECT form, filed, tags FROM sec_feed WHERE ticker=? AND filed >= ? AND (tags LIKE '%악재%' OR sentiment='악재') ORDER BY filed DESC LIMIT 2",
             t, (date.today() - timedelta(days=10)).isoformat())
    if bad:
        out.append({"title": "악재 공시", "why": " · ".join(f"{f['form']} {_md(f['filed'])}" for f in bad), "next": "공시 원문"})
    return out


def signals(conn, t: str, n: int = 12) -> list[dict]:
    """이 종목에 난 우리 신호와 결과(🏆 pred_outcomes) — 최신순."""
    try:
        import scoreboard
        names = {k: v[0] for k, v in scoreboard.SOURCES.items()}
    except Exception:  # noqa: BLE001
        names = {}
    rows = _q(conn, "SELECT source, date, entry, max_up, max_down, status FROM pred_outcomes WHERE ticker=? ORDER BY date DESC LIMIT ?", t.upper(), n)
    for r in rows:
        r["name"] = names.get(r["source"], r["source"])
    return rows


def history(conn, t: str, days: int = 60, n: int = 14) -> list[dict]:
    """상태 변화 [{date, text, kind}] 최신순 — Reg SHO 등재/해제 · 공식 잔고 · 큰 등락·거래량 · 핵심 공시 · ⭐ 순위."""
    t = t.upper()
    since = (date.today() - timedelta(days=days)).isoformat()
    ev = []
    try:
        files = [r["date"] for r in conn.execute("SELECT date FROM regsho_files WHERE status='ok' AND date >= ? ORDER BY date", (since,))]
        on = {r["date"] for r in conn.execute("SELECT date FROM regsho_list WHERE symbol=? AND date >= ?", (t, since))}
        prev = None
        for d in files:
            cur = d in on
            if prev is not None and cur != prev:
                ev.append({"date": d, "text": "Reg SHO 등재" if cur else "Reg SHO 해제", "kind": "sho"})
            prev = cur
    except Exception:  # noqa: BLE001
        pass
    si = _q(conn, "SELECT date, si_pct, short_shares FROM cx_short_interest WHERE ticker=? AND reported=1 AND date >= ? ORDER BY date", t, (date.today() - timedelta(days=days + 20)).isoformat())
    import chartex
    for a, b in zip(si, si[1:]):
        if a["si_pct"] is not None and b["si_pct"] is not None and abs(b["si_pct"] - a["si_pct"]) >= max(2.0, a["si_pct"] * 0.2):
            sh = f"잔고 주식 {_sh(a.get('short_shares'))} → {_sh(b.get('short_shares'))}주" if a.get("short_shares") and b.get("short_shares") else ""
            j = chartex.basis_jump(a, b)   # 2026-11-01 점검: 분모(유통주식)가 바뀐 것을 잔고 급변처럼 보이던 것(최근 200일 이력의 12%)
            if j:
                ev.append({"date": b["date"], "text": f"유통주식 기준 바뀜({_sh(j[0])} → {_sh(j[1])}주 · 증자·병합·자료 갱신) — 잔고 % {a['si_pct']:.1f} → {b['si_pct']:.1f} 는 비교 불가 · {sh}",
                           "kind": "si_basis"})
            else:
                ev.append({"date": b["date"], "text": f"공식 잔고 {a['si_pct']:.1f}% → {b['si_pct']:.1f}%(결제일 기준" + (f" · {sh})" if sh else ")"), "kind": "si"})
    bs = bars(conn, t, days + 20)
    for i in range(20, len(bs)):
        p, x = bs[i - 1]["close"], bs[i]
        if not p or not x["close"] or x["date"] < since:
            continue
        r = (x["close"] / p - 1) * 100
        avg = sum((y["volume"] or 0) for y in bs[i - 20:i]) / 20
        vol_x = (x["volume"] or 0) / avg if avg else 0
        if abs(r) >= 30 or vol_x >= 10:
            ev.append({"date": x["date"], "text": f"{r:+.0f}% (${p:.2f} → ${x['close']:.2f})" + (f" · 거래량 평소의 {vol_x:.0f}배" if vol_x >= 10 else ""), "kind": "move"})
    key = {"3.01": "상장 기준 미달 통지", "2.03": "부채", "3.02": "사모 발행", "5.03": "정관 변경(병합 등)", "1.01": "중요 계약"}
    for f in filings(conn, t, days):
        fm = f["form"].upper()
        if fm.startswith("8-K"):
            hit = [v for k, v in key.items() if k in f["items"]]
            if hit:
                ev.append({"date": f["filed"], "text": f"8-K {' · '.join(hit)}", "kind": "filing"})
        elif fm in RAISE_REG or fm.startswith(("424B", "EFFECT")):
            ev.append({"date": f["filed"], "text": f"{f['form']} 조달 서류", "kind": "filing"})
    for r in _q(conn, "SELECT date, tier, hold FROM s3_tier_signals WHERE ticker=? AND date >= ?", t, since) or \
            _q(conn, "SELECT date, tier FROM s3_tier_signals WHERE ticker=? AND date >= ?", t, since):
        ev.append({"date": r["date"], "text": f"⭐ 검증 {r['tier']}순위" + (f" ⏸ 보류({r['hold']})" if r.get("hold") else ""), "kind": "tier"})
    ev.sort(key=lambda e: e["date"], reverse=True)
    return ev[:n]


def headline(conn, t: str) -> dict:
    """서랍 머리: 지표 6개 + 칩 + 한 줄."""
    t = t.upper()
    snap = (_q(conn, "SELECT price, day_change_pct, float_shares, dilution_status, date FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", t) or [{}])[0]
    b = bars(conn, t, 30)
    px = b[-1]["close"] if b else snap.get("price")
    chg = (b[-1]["close"] / b[-2]["close"] - 1) * 100 if len(b) >= 2 and b[-2]["close"] else snap.get("day_change_pct")
    si = (_q(conn, "SELECT date, si_pct, dtc, short_shares FROM cx_short_interest WHERE ticker=? AND reported=1 ORDER BY date DESC LIMIT 1", t) or
          _q(conn, "SELECT si_date AS date, si_pct, dtc, shares_short AS short_shares FROM short_interest WHERE ticker=? ORDER BY date DESC LIMIT 1", t) or [{}])[0]
    import chartex   # 2026-11-01 점검: 같은 잔고(WKHS 966,750주)가 출처마다 9.9%·22.5% — 분모(유통주식) 정의가 달라서 → 분모를 같이 보여 줌
    si_float = chartex.implied_float(si.get("si_pct"), si.get("short_shares"))
    ib = (_q(conn, "SELECT fee, available, as_of FROM ibkr_borrow WHERE symbol=?", t) or [{}])[0]
    sho = None
    try:
        import regsho
        sho = regsho.streaks(conn).get(t)
    except Exception:  # noqa: BLE001
        pass
    n_sig = len(_q(conn, "SELECT 1 FROM pred_outcomes WHERE ticker=? AND date >= ?", t, (date.today() - timedelta(days=30)).isoformat()))
    hi = max((x["high"] or x["close"]) for x in b) if b else None
    lst = [f for f in filings(conn, t, 180) if f["form"].upper().startswith("8-K") and "3.01" in f["items"]]
    try:
        import rsplit
        rs_soon = rsplit.soon(conn, t)   # 병합 시행 7일 안(2년 10일 기대값 −3.9~−8.8% — 저금통·매매 진입에서 뺌)
    except Exception:  # noqa: BLE001
        rs_soon = None
    return {"rs_soon": rs_soon, "price": px, "chg": chg, "asof": b[-1]["date"] if b else snap.get("date"), "float": snap.get("float_shares"), "dil": snap.get("dilution_status"),
            "si": si.get("si_pct"), "si_date": si.get("date"), "si_float": si_float, "si_shares": si.get("short_shares"), "dtc": si.get("dtc"), "fee": ib.get("fee"), "avail": ib.get("available"), "ib_asof": ib.get("as_of"),
            "sho": sho, "n_sig": n_sig, "hi30": hi, "listing": bool(lst)}
