"""🧭 종합 판단 카드(2026-10-31 · 김곰 워치리스트의 '최종 판단 · 공시 흐름 · 주가를 올려야 하는 이유 · 현금조달 가능성'을 우리 식으로).
김곰은 종목마다 Claude 가 쓴 긴 분석 문서에서 판단을 꺼낸다 — 월 예산으론 전 종목에 못 쓰고, 분석 뒤 금방 낡아 '재분석 필요'가 계속 붙는다.
우리는 매일 갱신되는 데이터로 규칙 판단(비용 0 · 모든 종목)을 만들고, 🧾 공시분석이 있는 종목은 그 한 줄 결론을 같이 보여 준다.
· 🎯 올려야 하는 이유: company.purposes(현금 조달 · 상장 유지 · 물량 출회 · 부채 주식결제) + 워런트 행사 유도
· 🏦 현금조달 가능성: 런웨이 · 열린 조달 수단(ATM·ELOC·전환사채) · 최근 등록·공모 서류 · 1년 조달 횟수 · **급등 뒤 7일 안 조달 이력**(실제 공시로 잼)
   → 높음/중간/낮음 + 이유. 아침마다 기록(fin_verdict)해 30일 안 실제 조달(공모 424B · 등록 S-1/S-3 · 8-K 3.02)과 맞춰 본다(검증)
· 📰 공시 흐름: 최근 14일 공시의 호재·희석·악재 · 종목 뉴스 · 주총(위임장·결과·예정)
· 한 줄 종합: 위 셋을 묶은 규칙 문장(예측이 아니라 지금 자료의 정리)."""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, timedelta

import db

RAISE_FORMS = ("424B1", "424B2", "424B4", "424B5", "424B7", "S-1", "S-3", "F-1", "F-3")   # 회사 조달(424B3 재판매는 빼고)
REG_FORMS = ("S-1", "S-3", "F-1", "F-3", "S-1/A", "S-3/A", "F-1/A", "F-3/A")
DIL_FORMS = ("424B", "S-1", "S-3", "F-1", "F-3", "EFFECT", "S-8", "POS AM", "144")
DIL_TAGS = ("희석 위험", "ATM/ELOC", "유상증자", "공모", "사모")
OPEN_DIL = ("ATM", "ELOC", "CB", "SHELF", "선반", "전환")
PUMP_CLOSE, PUMP_HIGH, WINDOW = 1.5, 2.0, 7
FIN_DDL = "CREATE TABLE IF NOT EXISTS fin_verdict (date TEXT NOT NULL, ticker TEXT NOT NULL, level TEXT, score INTEGER, reasons TEXT, PRIMARY KEY (date, ticker))"


def _is_raise(form: str, items: str | None) -> bool:
    f = str(form or "").upper()
    return f in RAISE_FORMS or (f.startswith("8-K") and "3.02" in (items or ""))


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def pump_raise(conn, t: str, years: int = 3, today: date | None = None) -> dict:
    """급등(종가 +50% · 고가 +100%) 뒤 7일 안 회사 조달 공시 비율. 알려진 병합 ±5일은 뺌(병합 경계 착시). 7일 안 연달은 급등은 한 번.
    base = 이 종목이 아무 날이나 7일 안에 조달 공시를 낼 확률(상습 발행사인지 비교용)."""
    today = today or date.today()
    since = (today - timedelta(days=365 * years)).isoformat()
    t = t.upper()
    try:
        bars = conn.execute("SELECT date, close, high FROM daily_prices WHERE ticker=? AND date >= ? AND close > 0 ORDER BY date", (t, since)).fetchall()
        fil = conn.execute("SELECT filed, form, items FROM sec_hist WHERE ticker=? AND filed >= ?", (t, since)).fetchall()
    except Exception:  # noqa: BLE001
        return {"pumps": 0, "raised": 0, "examples": [], "base": None}
    splits = []
    for sql in ("SELECT date FROM rs_events WHERE ticker=?", "SELECT date FROM events WHERE ticker=? AND kind='역분할 시행'"):
        try:
            splits += [x for (x,) in conn.execute(sql, (t,)) if _d(x)]
        except Exception:  # noqa: BLE001
            pass
    sd = [_d(x) for x in splits]
    pumps: list[date] = []
    for i in range(1, len(bars)):
        pc, c, h = bars[i - 1][1], bars[i][1], bars[i][2] or bars[i][1]
        if not pc or pc <= 0 or not (c / pc >= PUMP_CLOSE or h / pc >= PUMP_HIGH):
            continue
        d = _d(bars[i][0])
        if d is None or any(abs((d - s).days) <= 5 for s in sd):
            continue
        if pumps and (d - pumps[-1]).days <= WINDOW:
            continue
        pumps.append(d)
    rd = sorted({(_d(f), str(fm)) for f, fm, it in fil if _is_raise(fm, it) and _d(f)})
    ex = []
    for p in pumps:
        hit = next(((x, fm) for x, fm in rd if 0 <= (x - p).days <= WINDOW), None)
        if hit:
            ex.append((p.isoformat(), hit[1], hit[0].isoformat()))
    base = None
    if bars:
        start = _d(bars[0][0])
        days = max(1, (today - start).days)
        cov = {x - timedelta(days=k) for x, _ in rd for k in range(WINDOW + 1)}   # 그날부터 7일 안에 조달 공시가 있는 날들
        base = round(sum(1 for c in cov if start <= c < today) / days * 100)
    return {"pumps": len(pumps), "raised": len(ex), "examples": ex[-4:], "base": base}


def financing(conn, t: str, runway: dict | None = None, dilution: str | None = None, pr: dict | None = None, today: date | None = None) -> dict:
    """현금조달 가능성 {level: 높음|중간|낮음, score, reasons: [(+점, 이유)], pump: pump_raise}."""
    today = today or date.today()
    t = t.upper()
    if dilution is None:
        try:
            r = conn.execute("SELECT dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
            dilution = r[0] if r else None
        except Exception:  # noqa: BLE001
            dilution = None
    if runway is None:
        try:
            import company
            runway = company.runway(t)
        except Exception:  # noqa: BLE001
            runway = {}
    rs: list[tuple[int, str]] = []
    m = (runway or {}).get("months")
    if m is not None:
        if m < 3:
            rs.append((3, f"런웨이 {m:.1f}개월 — 곧 현금이 떨어짐"))
        elif m < 6:
            rs.append((2, f"런웨이 {m:.1f}개월"))
        elif m < 12:
            rs.append((1, f"런웨이 {m:.1f}개월"))
        elif m >= 24:
            rs.append((-2, f"현금 넉넉(런웨이 {m:.0f}개월)"))
    if dilution and any(k in str(dilution).upper() for k in OPEN_DIL):
        rs.append((2, f"{dilution} 열림 — 주가를 안 올려도 시장에 팔 수 있음"))
    try:
        fil = conn.execute("SELECT filed, form, items FROM sec_hist WHERE ticker=? AND filed >= ?", (t, (today - timedelta(days=365)).isoformat())).fetchall()
    except Exception:  # noqa: BLE001
        fil = []
    d90, d60, d30 = (today - timedelta(days=n) for n in (90, 60, 30))
    reg = [f for f, fm, _ in fil if str(fm).upper() in REG_FORMS and (_d(f) or date.min) >= d90]
    if reg:
        rs.append((1, f"등록 서류(S-1·S-3 등) 90일 안 {len(reg)}건"))
    eff = [f for f, fm, _ in fil if str(fm).upper() == "EFFECT" and (_d(f) or date.min) >= d30]
    if eff:
        rs.append((1, f"등록 효력(EFFECT) {max(eff)} — 바로 팔 준비"))
    off = [f for f, fm, it in fil if _is_raise(fm, it) and str(fm).upper().startswith("424B") and (_d(f) or date.min) >= d60]
    if off:
        rs.append((1, f"최근 60일 공모·발행 {len(off)}번"))
    yr = [f for f, fm, it in fil if _is_raise(fm, it)]
    if len(yr) >= 4:
        rs.append((1, f"1년 조달·등록 서류 {len(yr)}번(상습)"))
    pu = pump_raise(conn, t, today=today)
    if pu["pumps"] >= 2:
        ratio = pu["raised"] / pu["pumps"]
        if ratio >= 0.5:
            rs.append((2, f"급등 뒤 7일 안 조달 {pu['raised']}/{pu['pumps']}번"))
        elif ratio >= 0.25:
            rs.append((1, f"급등 뒤 7일 안 조달 {pu['raised']}/{pu['pumps']}번"))
    sc = sum(p for p, _ in rs)
    lv = "높음" if sc >= 5 else ("중간" if sc >= 3 else "낮음")
    return {"level": lv, "score": sc, "reasons": sorted(rs, key=lambda x: -x[0]), "pump": pu}


def _kind(form: str, items: str | None, tags: list, sentiment: str | None) -> str:
    f = str(form or "").upper()
    if f.startswith(DIL_FORMS) or "3.02" in (items or "") or any(any(k in str(x) for k in DIL_TAGS) for x in tags):
        return "희석"
    if sentiment in ("호재", "약한 호재"):
        return "호재"
    if sentiment in ("악재", "주의"):
        return "악재"
    return "중립"


def flow(conn, t: str, days: int = 14, today: date | None = None) -> dict:
    """최근 days 일 공시·뉴스 흐름 + 주총."""
    today = today or date.today()
    t = t.upper()
    since = (today - timedelta(days=days)).isoformat()
    items = []
    try:
        for r in conn.execute("SELECT COALESCE(filed, substr(updated,1,10)) AS d, form, items, tags, sentiment, url FROM sec_feed WHERE ticker=? "
                              "AND COALESCE(filed, substr(updated,1,10)) >= ? ORDER BY d DESC", (t, since)):
            tags = json.loads(r["tags"] or "[]") if r["tags"] else []
            items.append({"date": r["d"], "form": r["form"], "kind": _kind(r["form"], r["items"], tags, r["sentiment"]), "tags": tags[:3], "url": r["url"]})
    except Exception:  # noqa: BLE001
        pass
    cnt = {k: sum(1 for x in items if x["kind"] == k) for k in ("호재", "희석", "악재", "중립")}
    try:
        news = conn.execute("SELECT COUNT(*) FROM news WHERE ticker=? AND fetched >= ?", (t, since)).fetchone()[0]
    except Exception:  # noqa: BLE001
        news = 0
    agm = []
    try:
        s150 = (today - timedelta(days=150)).isoformat()
        prox = conn.execute("SELECT MAX(filed), form FROM sec_hist WHERE ticker=? AND filed >= ? AND (form LIKE 'DEF 14%' OR form LIKE 'PRE 14%')", (t, s150)).fetchone()
        if prox and prox[0]:
            agm.append(f"위임장({prox[1]}) {prox[0]}")
        res = conn.execute("SELECT MAX(filed) FROM sec_hist WHERE ticker=? AND filed >= ? AND form LIKE '8-K%' AND items LIKE '%5.07%'", (t, s150)).fetchone()
        if res and res[0]:
            agm.append(f"주총 결과(8-K 5.07) {res[0]}")
        up = conn.execute("SELECT date, kind FROM events WHERE ticker=? AND date >= ? AND kind IN ('주총','임시주총') ORDER BY date LIMIT 1", (t, today.isoformat())).fetchone()
        if up:
            agm.append(f"{up[1]} 예정 {up[0]}(D-{(date.fromisoformat(up[0]) - today).days})")
    except Exception:  # noqa: BLE001
        pass
    if not items:
        verdict = f"조용함 — {days}일 공시 없음"
    elif cnt["희석"] >= 2 and cnt["희석"] > cnt["호재"]:
        verdict = "희석 공시 우세"
    elif cnt["호재"] >= 2 and cnt["호재"] > cnt["희석"] + cnt["악재"]:
        verdict = "호재 공시 우세"
    elif cnt["악재"] >= 2 and cnt["악재"] > cnt["호재"]:
        verdict = "악재 공시 우세"
    else:
        verdict = "섞임"
    return {"days": days, "count": cnt, "items": items[:6], "news": news, "agm": agm, "verdict": verdict}


def warrant_purpose(fsa: dict | None, price: float | None) -> dict | None:
    """현재가보다 높은 워런트(+150% 안)가 있으면 '워런트 행사 유도' 목적 — 주가가 행사가 위로 가면 회사가 현금을 받음."""
    if not (fsa and price):
        return None
    ws = [w for w in fsa.get("warrants") or [] if w.get("price") and price < w["price"] <= price * 2.5 and w.get("qty")]
    if not ws:
        return None
    lo = min(w["price"] for w in ws)
    qty = sum(w["qty"] for w in ws if w["price"] == lo)
    return {"title": "워런트 행사 유도", "urgency": "가능", "need": lo, "need_pct": (lo / price - 1) * 100, "deadline": None,
            "why": f"행사가 ${lo:.4f} 워런트 {qty / 1e6:,.2f}M주 — 주가가 이 위면 회사가 약 ${lo * qty / 1e6:,.2f}M 현금을 받음"}


STRONG = ("급함", "기한 있음")


def summary(purposes: list[dict], fin: dict, fl: dict) -> dict:
    """한 줄 종합 {label, color, text}. 예측이 아니라 지금 자료의 정리."""
    soon = [p for p in purposes if p.get("urgency") in STRONG or (p.get("deadline") and _d(p["deadline"]) and (_d(p["deadline"]) - date.today()).days <= 60)]
    lv = fin["level"]
    if soon and lv == "높음":
        label, color = "⚠️ 올릴 이유는 있지만 조달 가능성 큼 — 급등은 짧게 볼 것", "#F76B15"
    elif soon and lv != "높음":
        label, color = "🎯 올릴 이유가 있고 조달 수단은 적음 — 상승 시나리오에 우호적", "#30A46C"
    elif not purposes and lv == "높음":
        label, color = "🔻 올릴 이유 약하고 희석 위험 큼", "#E5484D"
    elif purposes:
        label, color = "➖ 올릴 이유는 있으나 급하지 않음", "#888888"
    else:
        label, color = "➖ 뚜렷한 방향 없음", "#888888"
    bits = []
    if purposes:
        p0 = sorted(purposes, key=lambda p: (p.get("urgency") not in STRONG, p.get("deadline") or "9999"))[0]
        bits.append("올릴 이유: " + p0["title"] + (f"(D-{(_d(p0['deadline']) - date.today()).days})" if p0.get("deadline") and _d(p0["deadline"]) else "")
                    + (f" 목표 +{p0['need_pct']:.0f}%" if p0.get("need_pct") and p0["need_pct"] > 0 else "") + (f" 외 {len(purposes) - 1}개" if len(purposes) > 1 else ""))
    else:
        bits.append("올릴 이유: 뚜렷한 것 없음")
    bits.append(f"현금조달 가능성 {lv}" + (f"({fin['reasons'][0][1].split(' — ')[0]})" if fin["reasons"] and fin["reasons"][0][0] > 0 else ""))
    c = fl["count"]
    bits.append(f"공시 흐름: {fl['verdict']}" + (f"(호재 {c['호재']} · 희석 {c['희석']} · 악재 {c['악재']})" if fl["items"] else ""))
    return {"label": label, "color": color, "text": " · ".join(bits)}


def build(t: str, b: dict | None = None, conn=None) -> dict:
    """카드 재료. b = company.build(t) 결과(없으면 새로)."""
    import company
    t = t.upper()
    b = b or company.build(t)
    own = conn is None
    conn = conn or db.connect()
    try:
        try:
            import fundscan
            fsa = fundscan.analyze(t, conn)
        except Exception:  # noqa: BLE001
            fsa = None
        purposes = list(b.get("purposes") or [])
        wp = warrant_purpose(fsa, b.get("price"))
        if wp and not any(p["title"] == wp["title"] for p in purposes):
            purposes.append(wp)
        snap = None
        try:
            snap = conn.execute("SELECT dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        except Exception:  # noqa: BLE001
            pass
        fin = financing(conn, t, b.get("runway"), snap[0] if snap else None, b.get("pressure"))
        fl = flow(conn, t)
        try:
            import forensic_ai
            fs = forensic_ai.summary_latest(conn, t)
        except Exception:  # noqa: BLE001
            fs = None
        try:
            stats = json.loads((db.get_meta("fin_stats") or {}).get("value") or "{}")
        except ValueError:
            stats = {}
        try:   # 🧾 재분석 필요(리포트 뒤 새 물량·공시)
            import reanalyze
            r0 = conn.execute("SELECT MAX(created_at) FROM forensic_reports WHERE ticker=?", (t,)).fetchone()
            rean = reanalyze.need(conn, t, str(r0[0])[:10] if r0 and r0[0] else None)
        except Exception:  # noqa: BLE001
            rean = {"level": None}
    finally:
        if own:
            conn.close()
    return {"ticker": t, "purposes": purposes, "fin": fin, "flow": fl, "summary": summary(purposes, fin, fl),
            "forensic": ({"one_liner": fs.get("one_liner"), "as_of": fs.get("as_of")} if fs and fs.get("one_liner") else None), "fin_stats": stats,
            "reanalyze": rean}


# ---------------------------------------------------------------- 검증: 아침마다 기록 → 30일 안 실제 조달과 맞춰 봄
def log_daily(conn, tickers: list[str] | None = None, today: date | None = None, out=print) -> int:
    today = today or date.today()
    conn.execute(FIN_DDL)
    if tickers is None:
        tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots)")]
    rows = []
    for t in tickers:
        try:
            f = financing(conn, t, today=today)
        except Exception:  # noqa: BLE001
            continue
        rows.append((today.isoformat(), t, f["level"], f["score"], json.dumps([r for _, r in f["reasons"]], ensure_ascii=False)))
    conn.executemany("INSERT OR REPLACE INTO fin_verdict VALUES (?,?,?,?,?)", rows)
    conn.commit()
    lv = {k: sum(1 for r in rows if r[2] == k) for k in ("높음", "중간", "낮음")}
    st = fin_stats(conn, today=today)
    db.set_meta("fin_stats", json.dumps(st, ensure_ascii=False))   # 카드는 이 값을 읽음(화면에서 매번 다시 세지 않게)
    out(f"🏦 현금조달 가능성 기록: {len(rows)}종목 · 높음 {lv['높음']} · 중간 {lv['중간']} · 낮음 {lv['낮음']}"
        + ("" if not st else " · 30일 뒤 실제 조달 " + " · ".join(f"{k} {v[1]}%({v[0]}건)" for k, v in st.items())))
    return len(rows)


def fin_stats(conn, horizon: int = 30, today: date | None = None) -> dict:
    """판정별 '그 뒤 horizon 일 안 실제 조달' 비율 — 판정 날짜가 horizon 일 넘게 지난 것만(컨닝 없음). {level: (건수, 조달 %)}"""
    today = today or date.today()
    cut = (today - timedelta(days=horizon)).isoformat()
    try:
        vs = conn.execute("SELECT date, ticker, level FROM fin_verdict WHERE date <= ?", (cut,)).fetchall()
    except Exception:  # noqa: BLE001
        return {}
    out: dict = {}
    for lv in ("높음", "중간", "낮음"):
        sub = [(d, t) for d, t, l in vs if l == lv]
        if not sub:
            continue
        hit = 0
        for d, t in sub:
            end = (date.fromisoformat(d) + timedelta(days=horizon)).isoformat()
            rows = conn.execute("SELECT form, items FROM sec_hist WHERE ticker=? AND filed > ? AND filed <= ?", (t, d, end)).fetchall()
            hit += any(_is_raise(fm, it) for fm, it in rows)
        out[lv] = (len(sub), round(hit / len(sub) * 100))
    return out


def text(v: dict) -> str:
    """📋 메신저용 복사 글(김곰 '근거 / -> 해설·판단 / 종합 판단' 간략판 참고)."""
    sm, f, fl = v["summary"], v["fin"], v["flow"]
    lines = [f"[{v['ticker']}] 🧭 {sm['label']}", "근거"]
    for p in v["purposes"]:
        need = "" if not p.get("need") else f" 필요 주가 ${p['need']:.4f}" + (f"(+{p['need_pct']:.0f}%)" if p.get("need_pct") and p["need_pct"] > 0 else "")
        lines.append(f"- 올릴 이유: {p['title']}" + (f" {p['deadline']}" if p.get("deadline") else "") + need + f" — {p.get('why') or ''}")
    if not v["purposes"]:
        lines.append("- 올릴 이유: 뚜렷한 것 없음")
    lines.append(f"- 현금조달 가능성 {f['level']}({f['score']}점): " + (" · ".join(r for _, r in f["reasons"]) or "특별한 신호 없음"))
    pu = f["pump"]
    if pu["pumps"]:
        lines.append(f"- 최근 3년 급등 {pu['pumps']}번 중 7일 안 조달 {pu['raised']}번" + (f"(평소 {pu['base']}%)" if pu.get("base") is not None else ""))
    c = fl["count"]
    lines.append(f"- 공시 흐름({fl['days']}일): {fl['verdict']} · 호재 {c['호재']} · 희석 {c['희석']} · 악재 {c['악재']}" + (f" · 주총: {' · '.join(fl['agm'])}" if fl["agm"] else ""))
    if v.get("forensic"):
        lines.append(f"- 공시분석({v['forensic']['as_of']}): {v['forensic']['one_liner']}")
    lines.append(f"-> 종합: {sm['text']}")
    lines.append("(규칙 기반 정리 · 공시·시세 추정 · 투자 권유 아님)")
    return "\n".join(lines)
