"""💰 펀드스캔 — 워런트 행사가 · 현금 런웨이로 '회사가 주가를 띄울 이유'를 계산한다(래빗스탁 펀드스캔 방식).

자료: ① 자금조달 공시(424B·8-K 1.01/3.02) '표지 부분'에서 판매가·조달액·주식·워런트(수량·행사가)·프리펀디드·주관사를 규칙으로 추출(선택: AI 정밀 추출)
      ② SEC 재무(XBRL): 워런트 총수·가중평균 행사가, 표지 주식 수 이력  ③ 종목 리포트 런웨이(현금·월 소진)  ④ 분할 이력(병합 환산)
펌핑 유인: 추정 현재 런웨이 4개월 이하 + 주가가 최저 행사가보다 20~100% 아래(필요 상승 +20~+100%). 조건 충족 여부이지 예측이 아니다.
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, timedelta

import db

XBRL_FRESH_DAYS = 400   # SEC 재무(XBRL) 워런트 자료를 믿는 기간
ODD_STRIKE_X = 50       # 행사가가 현재가의 이 배수를 넘으면 병합 미반영으로 봄
DDL = ["""CREATE TABLE IF NOT EXISTS fs_deals (accession TEXT PRIMARY KEY, ticker TEXT, filed TEXT, form TEXT, kind TEXT, proceeds REAL, unit_price REAL, shares REAL, pfw REAL,
          warrants TEXT, agent TEXT, resale INTEGER, source TEXT, url TEXT, parsed_at TEXT)""",
       "CREATE TABLE IF NOT EXISTS fs_xbrl (ticker TEXT PRIMARY KEY, data TEXT, updated TEXT)"]
DEAL_FORMS = ("424B", "S-1", "S-3", "F-1", "F-3")   # C단계 2026-10-27: 등록서류(S-1/S-3/F-1/F-3)도 — 워런트 행사가·PFW 가 여기 먼저 나옴(래빗스탁 펀드스캔 추적 360종목 수준으로)


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def _num(s: str | None) -> float | None:
    try:
        return float(str(s).replace(",", "")) if s else None
    except ValueError:
        return None


def parse_deal(text: str, form: str = "") -> dict:
    """공시 표지(앞부분)에서 딜 조건 추출 — 찾지 못한 값은 None."""
    t = re.sub(r"\s+", " ", (text or "")[:20000])
    out = {"proceeds": None, "unit_price": None, "shares": None, "pfw": None, "warrants": [], "agent": None, "resale": "selling stockholder" in t.lower()}
    m = re.search(r"gross proceeds[^$]{0,80}\$\s?([\d,.]+)\s*(million|billion)?", t, re.I)
    if m:
        v = _num(m.group(1))
        out["proceeds"] = None if v is None else v * (1e6 if (m.group(2) or "").lower() == "million" else 1e9 if (m.group(2) or "").lower() == "billion" else 1)
    m = re.search(r"(?:combined )?(?:public )?offering price (?:of|is|per share (?:and accompanying warrant )?(?:of|is))?\s*\$\s?(\d+(?:\.\d+)?)(?: per (?:share|unit))?"
                  r"|at a (?:purchase |combined )?price of \$\s?(\d+(?:\.\d+)?) per|purchase price of \$\s?(\d+(?:\.\d+)?) per (?:share|unit)", t, re.I)
    if m:
        out["unit_price"] = _num(m.group(1) or m.group(2) or m.group(3))
    m = re.search(r"(?:offering|issue|sell|sale) (?:of )?(?:up to )?(?:an aggregate of )?([\d,]{4,}) shares of (?:our )?common stock", t, re.I)
    if m:
        out["shares"] = _num(m.group(1))
    m = re.search(r"pre-funded warrants? to purchase (?:up to )?(?:an aggregate of )?([\d,]{3,}) shares", t, re.I)
    if m:
        out["pfw"] = _num(m.group(1))
    seen = set()
    for m in re.finditer(r"(?<!pre-funded )(?:(Series [A-Z][\w-]*|common|placement agent) )?warrants? to purchase (?:up to )?(?:an aggregate of )?([\d,]{3,}) shares[^$]{0,400}?"
                         r"(?:exercise price|exercisable)[^$]{0,80}?\$\s?(\d+(?:\.\d+)?)", t, re.I):   # '행사가 ... $X' 사이 표현이 다양해 80자 안에서 첫 $ 값
        q, p = _num(m.group(2)), _num(m.group(3))
        if q and p and (q, p) not in seen and "pre-funded" not in t[max(0, m.start() - 20):m.start()].lower():
            seen.add((q, p))
            out["warrants"].append({"name": (m.group(1) or "Warrants").strip().title(), "qty": q, "price": p})
    try:
        import pumpsetup
        for n in pumpsetup.COUNTERPARTIES:
            if n.lower() in t.lower():
                out["agent"] = n
                break
    except Exception:  # noqa: BLE001
        pass
    return out


def kind_of(form: str, items: str = "") -> str:
    f = (form or "").upper()
    if f.startswith("424B3"):
        return "재판매 등록"
    if f.startswith("424B"):
        return "공모"
    if f.startswith("8-K") and ("3.02" in (items or "") or "1.01" in (items or "")):
        return "사모·PIPE 계약"
    if f.startswith(("S-1", "F-1")):
        return "증권 등록(S-1/F-1)"
    if f.startswith(("S-3", "F-3")):
        return "선반 등록(S-3/F-3)"
    return "기타"


def save_deal(conn, ticker: str, accession: str, filed: str, form: str, items: str, url: str, d: dict, source: str = "규칙") -> None:
    ensure_tables(conn)
    conn.execute("INSERT OR REPLACE INTO fs_deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (accession, ticker.upper(), filed, form, kind_of(form, items), d.get("proceeds"), d.get("unit_price"), d.get("shares"), d.get("pfw"),
                  json.dumps(d.get("warrants") or [], ensure_ascii=False), d.get("agent"), 1 if d.get("resale") else 0, source, url, db.utcnow_iso()))
    conn.commit()


def is_deal(form: str, items: str) -> bool:
    f = (form or "").upper()
    return f.startswith(DEAL_FORMS) or (f.startswith("8-K") and ("3.02" in (items or "") or "1.01" in (items or "")))


def xbrl(cf: dict) -> dict:
    """워런트 총수·가중평균 행사가(최신 기준일) + 표지 주식 수 이력."""
    facts = (cf.get("facts") or {})

    def latest(tax, name, unit):
        rows = ((facts.get(tax) or {}).get(name) or {}).get("units", {}).get(unit) or []
        if not rows:
            return None
        r = max(rows, key=lambda x: (x["end"], x.get("filed", "")))
        return {"val": float(r["val"]), "end": r["end"]}
    w = latest("us-gaap", "ClassOfWarrantOrRightOutstanding", "shares")
    p = latest("us-gaap", "ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights1", "USD/shares")
    rows = ((facts.get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares") or []
    hist = {}
    for end in {r["end"] for r in rows}:
        same = [r for r in rows if r["end"] == end]
        last = max(r.get("filed", "") for r in same)
        uniq = {(r.get("accn"), r.get("frame"), r["val"]): r for r in same if r.get("filed", "") == last}
        hist[end] = sum(float(r["val"]) for r in uniq.values())  # 같은 기준일·같은 공시의 여러 종류 주식은 합산
    return {"warrants": w, "wavg_price": p, "shares_hist": sorted(hist.items())}


def _split_factor(t: str, since: str, conn) -> float:
    """since 이후 분할 곱(역분할 0.2 = 5:1 병합) — 딜 당시 수량·가격을 지금 기준으로 환산할 때 씀."""
    import shares
    f = 1.0
    for s in shares.splits_after(t, since, conn):
        f *= s["ratio"]
    return f


def analyze(t: str, conn=None) -> dict | None:
    import shares
    t = t.upper()
    own = conn is None
    conn = conn or db.connect()
    try:
        ensure_tables(conn)
        deals = [dict(r) for r in conn.execute("SELECT * FROM fs_deals WHERE ticker=? AND filed >= ? ORDER BY filed DESC", (t, (date.today() - timedelta(days=400)).isoformat()))]
        if not deals:
            return None
        snap = conn.execute("SELECT price, float_shares, dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        mv = None
        try:
            mv = conn.execute("SELECT price, vol FROM daily_move WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        except Exception:  # noqa: BLE001
            pass
        price = (snap["price"] if snap else None) or (mv["price"] if mv else None)
        sh_now, sh_tag = shares.best(t, snap["float_shares"] if snap else None)
        xr = conn.execute("SELECT data FROM fs_xbrl WHERE ticker=?", (t,)).fetchone()
        xb = json.loads(xr[0]) if xr else {}
        warrants, pfw, adj_note = [], 0.0, []
        for d in deals:
            f = _split_factor(t, d["filed"], conn)
            if f != 1:
                adj_note.append(f"{d['filed']} 딜 이후 분할 {round(1 / f) if f < 1 else f:g}배 환산")
            for w in json.loads(d["warrants"] or "[]"):
                warrants.append({"name": w.get("name") or "Warrants", "qty": w["qty"] * f, "price": w["price"] / f, "deal": d["filed"], "form": d["form"]})
            pfw += (d["pfw"] or 0) * f
        src = "공시 딜"
        xb_fresh = bool(xb.get("warrants")) and xb["warrants"]["end"] >= (date.today() - timedelta(days=XBRL_FRESH_DAYS)).isoformat()
        if not warrants and xb.get("warrants") and xb.get("wavg_price") and xb_fresh:  # 1년 넘은 재무의 워런트는 그 뒤 병합·행사가 반영 안 됐을 수 있어 안 씀
            f = _split_factor(t, xb["warrants"]["end"], conn)
            warrants.append({"name": "공시 재무 워런트 합계(가중평균 행사가)", "qty": xb["warrants"]["val"] * f, "price": xb["wavg_price"]["val"] / f, "deal": xb["warrants"]["end"], "form": "10-Q/10-K"})
            src = "SEC 재무(XBRL)"
        import runway as _rwm  # 🪙 리포트가 없어도 SEC 재무 저장소로(예전엔 리포트 있는 종목만)
        rn = _rwm.now(t, conn, deals) or {}
        if rn.get("stale"):  # 재무가 200일 넘게 오래됨 → '지금 추정 현금'을 믿기 어려움(예전엔 런웨이 0.0개월·현금 음수로 보였음)
            rn = {**rn, "cash_now": None, "runway_now": None, "floor": None}
        cash, burn, asof = rn.get("cash"), rn.get("monthly_burn"), rn.get("cash_asof")
        cash_now, runway_now, months_elapsed, raised_after = rn.get("cash_now"), rn.get("runway_now"), rn.get("months_elapsed"), rn.get("raised_after")
        floor = rn.get("floor")
        rw = {"runway_months": rn.get("runway_report")}
        cash_w = [w for w in warrants if w["price"]]
        odd = [w for w in cash_w if price and w["price"] / price > ODD_STRIKE_X]  # 현재가의 50배 넘는 행사가 = 병합 미반영 추정 → 필요 상승 계산에서 뺌
        for w in odd:
            w["odd"] = True
            adj_note.append(f"{w['name']} 행사가 ${w['price']:,.2f} 는 현재가의 {w['price'] / price:,.0f}배 — 병합 미반영 추정, 계산에서 뺌")
        cash_w = [w for w in cash_w if not w.get("odd")]
        min_ex = min((w["price"] for w in cash_w), default=None)
        need = None if not (min_ex and price) else (min_ex / price - 1) * 100
        money_in = sum(w["qty"] * w["price"] for w in cash_w)
        overhang = sum(w["qty"] for w in warrants) + pfw
        dil_pct = None if not sh_now else overhang / sh_now * 100
        vol = mv["vol"] if mv and mv["vol"] else None
        cond = runway_now is not None and runway_now <= 4 and need is not None and 20 <= need <= 100
        score = 0
        if runway_now is not None:
            score += 50 if runway_now <= 1 else 40 if runway_now <= 2 else 30 if runway_now <= 3 else 20 if runway_now <= 4 else 0
        if need is not None:
            score += 40 if 20 <= need <= 60 else 25 if 60 < need <= 100 else 10 if (10 <= need < 20 or 100 < need <= 150) else 0
        if cash_now is not None and money_in >= 2 * max(cash_now, 1):
            score += 10
        atm = (snap["dilution_status"] if snap else None) in ("ATM", "ELOC")
        label = ("양면 신호" if (atm or (dil_pct or 0) >= 50) else "펌핑 유인") if cond else "관망"
        pressure = None if runway_now is None else ("매우 높음" if runway_now <= 1.5 else "높음" if runway_now <= 3 else "보통" if runway_now <= 6 else "낮음")
        grade = "A" if (runway_now is not None and src == "공시 딜" and price) else ("B" if runway_now is not None and warrants else "C")
        rs = bool(shares.splits_after(t, (date.today() - timedelta(days=365)).isoformat(), conn))
        hist = xb.get("shares_hist") or []
        first_deal = deals[-1]["filed"]
        before = next((v for e, v in reversed(hist) if e < first_deal), None)
        latest = hist[-1] if hist else None
        chg = None
        if before and latest:
            f = _split_factor(t, first_deal, conn)
            inc = latest[1] - before * (f if latest[0] > first_deal else 1)
            explained = sum((d["shares"] or 0) * _split_factor(t, d["filed"], conn) for d in deals if d["filed"] <= latest[0])
            unknown = max(0.0, inc - explained)
            chg = {"before": before, "before_asof": next(e for e, v in reversed(hist) if e < first_deal), "latest": latest[1], "latest_asof": latest[0], "increase": inc,
                   "explained": explained, "unknown": unknown, "rate": None if inc <= 0 else min(100.0, explained / inc * 100)}
        sentence = ""
        if runway_now is not None and min_ex:
            sentence = (f"현금이 약 {runway_now:.1f}개월치. 주가가 ${min_ex:.4f}를 넘으면 워런트 행사로 약 ${money_in / 1e6:,.1f}M 이 들어올 수 있다"
                        + (" — 회사가 주가를 띄울 이유가 구조적으로 있는 구간." if cond else "."))
        return {"ticker": t, "price": price, "shares": sh_now, "shares_tag": sh_tag, "deals": deals, "latest_deal": deals[0], "warrants": warrants, "warrant_src": src, "pfw": pfw,
                "adj_note": adj_note, "cash": cash, "burn": burn, "asof": asof, "months_elapsed": months_elapsed, "raised_after": raised_after, "cash_now": cash_now,
                "runway_report": rw.get("runway_months"), "runway_now": runway_now, "floor": floor, "runway_info": rn or None,
                "raise_window": None if not floor else ((date.fromisoformat(floor) - timedelta(days=90)).isoformat(), (date.fromisoformat(floor) - timedelta(days=45)).isoformat()),
                "min_ex": min_ex, "need": need, "money_in": money_in, "overhang": overhang, "dil_pct": dil_pct, "vol": vol,
                "overhang_days": None if not (vol and overhang) else overhang / vol, "cond": cond, "score": score, "label": label, "pressure": pressure, "grade": grade, "rs": rs,
                "atm": atm, "share_change": chg, "sentence": sentence}
    finally:
        if own:
            conn.close()


def scan() -> list[dict]:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM fs_deals WHERE filed >= ?", ((date.today() - timedelta(days=400)).isoformat(),))]
        out = [a for a in (analyze(t, conn) for t in tickers) if a]
    return sorted(out, key=lambda a: (-a["score"], a["ticker"]))


def _doc_text(client, url: str) -> str:
    idx = client._get(url).text
    m = re.search(r'href="(/Archives/edgar/data/[^"]+\.(?:htm|html|txt))"', idx, re.I)
    return client.fetch_text("https://www.sec.gov" + m.group(1), limit=120_000) if m else ""


def _needs_ai(form: str, d: dict, text: str) -> bool:
    """규칙이 행사가(워런트)도 발행가도 못 찾았는데 본문은 긴 딜 공시 → AI 로 다시 읽을 후보."""
    return bool(text) and len(text) > 1500 and not d.get("warrants") and d.get("unit_price") is None and (form or "").upper().startswith(("424B", "8-K", "S-1", "S-3", "F-1", "F-3"))


def ai_fallback(conn, client, items: list[dict], cap: int, http_post=None) -> int:
    """규칙이 못 읽은 딜을 Haiku 로 다시 읽어 덮어씀(하루 cap 건 · 🤖 AI 월 예산 지갑 안에서 · 예산 부족이면 멈춤)."""
    import os
    if cap <= 0 or not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return 0
    import aisummary
    done = 0
    for it in items[:cap]:
        try:
            raw, _i, _o = aisummary.call(AI_SYSTEM, it["text"][:12000], max_tokens=800, http_post=http_post)
            j = aisummary._json(raw)
            if not isinstance(j.get("warrants"), list):
                j["warrants"] = []
            if j.get("warrants") or j.get("unit_price") is not None:
                save_deal(conn, it["ticker"], it["accession"], it["filed"], it["form"], it["items"], it["url"], j, source="AI")
                done += 1
        except RuntimeError:   # 예산 부족
            break
        except Exception:  # noqa: BLE001
            continue
    return done


def run(client, limit: int = 150, xbrl_limit: int = 80, out=print, ai_cap: int | None = None, http_post=None) -> dict:
    """아직 해석 안 한 최근 1년 자금조달 공시(424B·S-1/S-3/F-1/F-3·8-K 1.01/3.02)를 해석하고, 추적 종목의 SEC 재무 워런트·주식 수 이력을 갱신(하루 상한).
    C단계 2026-10-27: 하루 60 → 150건 · 규칙이 못 읽은 딜은 Haiku 로 다시(FUNDSCAN_AI_PER_DAY, 기본 20건)."""
    import config as _cfg
    since = (date.today() - timedelta(days=365)).isoformat()
    n_deal = n_x = 0
    ai_items: list[dict] = []
    if ai_cap is None:
        ai_cap = int(getattr(_cfg, "FUNDSCAN_AI_PER_DAY", 20))
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        done = {r[0] for r in conn.execute("SELECT accession FROM fs_deals")}
        cand = []
        for sql in ("SELECT accession, ticker, filed, form, items, '' AS url FROM sec_hist WHERE filed >= ?",
                    "SELECT accession, ticker, COALESCE(filed, substr(updated,1,10)) AS filed, form, items, url FROM sec_feed WHERE COALESCE(filed, substr(updated,1,10)) >= ?"):
            try:
                cand += [dict(r) for r in conn.execute(sql, (since,)) if is_deal(r["form"], r["items"]) and r["accession"] not in done]
            except Exception:  # noqa: BLE001
                pass
        cand.sort(key=lambda r: r["filed"], reverse=True)
        for r in cand[:limit]:
            try:
                url = r["url"] or f"https://www.sec.gov/Archives/edgar/data/{int(client.cik_for(r['ticker']))}/{r['accession'].replace('-', '')}/{r['accession']}-index.htm"
                text = _doc_text(client, url)
                d = parse_deal(text, r["form"])
                save_deal(conn, r["ticker"], r["accession"], r["filed"], r["form"], r["items"] or "", url, d)
                n_deal += 1
                if _needs_ai(r["form"], d, text) and len(ai_items) < ai_cap:
                    ai_items.append({"ticker": r["ticker"], "accession": r["accession"], "filed": r["filed"], "form": r["form"], "items": r["items"] or "", "url": url, "text": text})
            except Exception:  # noqa: BLE001
                continue
        tickers = [x[0] for x in conn.execute("SELECT DISTINCT ticker FROM fs_deals")]
        fresh = {x[0] for x in conn.execute("SELECT ticker FROM fs_xbrl WHERE updated >= ?", ((date.today() - timedelta(days=7)).isoformat(),))}
        for t in [x for x in tickers if x not in fresh][:xbrl_limit]:
            try:
                cik = client.cik_for(t)
                if cik:
                    cf = client.companyfacts(cik)
                    conn.execute("INSERT OR REPLACE INTO fs_xbrl VALUES (?,?,?)", (t, json.dumps(xbrl(cf)), db.utcnow_iso()))
                    try:  # 🪙 같은 재무 원본에서 런웨이(현금·월 소모량)도 저장 — 인터넷 조회 추가 없음
                        import report as _rp
                        import runway as _rwm
                        _rwm.save(conn, t, _rp.runway_from_facts(cf))
                    except Exception:  # noqa: BLE001
                        pass
                    n_x += 1
            except Exception:  # noqa: BLE001
                continue
        conn.commit()
        n_ai = ai_fallback(conn, client, ai_items, ai_cap, http_post=http_post)
    out(f"펀드스캔: 공시 {n_deal}건 해석(AI 보조 {n_ai}건) · 재무 {n_x}종목 갱신")
    return {"deals": n_deal, "xbrl": n_x, "ai": n_ai}


AI_SYSTEM = ("너는 SEC 자금조달 공시 표지에서 딜 조건만 뽑는 추출기다. 본문에 있는 숫자만 쓰고 없으면 null. JSON 하나만 출력: "
             '{"proceeds": 달러 숫자, "unit_price": 숫자, "shares": 숫자, "pfw": 숫자, "warrants": [{"name": "...", "qty": 숫자, "price": 숫자}], "agent": "이름", "resale": true/false}')


def ai_extract(t: str, client, n: int = 3, http_post=None) -> int:
    """정밀 추출(선택): 최근 딜 n건의 표지(앞 1.2만 자)만 AI 로 — 관리 모드 AI 예산 안에서."""
    import aisummary
    done = 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        for d in [dict(r) for r in conn.execute("SELECT * FROM fs_deals WHERE ticker=? ORDER BY filed DESC LIMIT ?", (t.upper(), n))]:
            text = _doc_text(client, d["url"])[:12000]
            if not text:
                continue
            raw, _i, _o = aisummary.call(AI_SYSTEM, text, max_tokens=800, http_post=http_post)
            j = aisummary._json(raw)
            if not isinstance(j.get("warrants"), list):
                j["warrants"] = []
            save_deal(conn, t, d["accession"], d["filed"], d["form"], "", d["url"], j, source="AI")
            done += 1
    return done
