"""⚠️ 대폭 할인 전환(악성 자금조달) 패턴 (2026-10-27, 스승님 꿀팁 'OMH 패턴')

패턴: 병합 → 50% 할인 전환사채·선급주식매입(prepaid forward) 계약 → 초기 양전(할인 전환 뒤 차익 실현) → 주가 70~80% 폭락 → 바닥에서 반등(RETO·WFF·SXTC).
감지(규칙, 공시 본문): "conversion price … N% of the lowest (VWAP|closing|trading) price" (할인 = 100−N) · "N% discount to the (lowest|market|VWAP)" · prepaid advance/forward/stock purchase.
등급: 할인 ≥ 40% = 악성(폭락 경로) · 20~40% = 주의 · 20% 미만(ELOC 의 95% 등)은 기록만.
'폭락 경로' = 악성 할인 계약 + 계약 전 180일 안 병합 이력.
🏆 성과 공표: toxic_drop(계약일 뒤 60거래일 안 저가가 −50% 닿는지 · 내림 예측) · toxic_bottom(계약일 종가 대비 −70% 에 처음 닿은 날 → 20거래일 안 +30% 반등 · 오름 예측).
"""
from __future__ import annotations

import re
from contextlib import closing
from datetime import date, timedelta

import db

DDL = """CREATE TABLE IF NOT EXISTS toxic_deals (accession TEXT PRIMARY KEY, ticker TEXT, filed TEXT, form TEXT, kind TEXT, discount_pct REAL, level TEXT,
         note TEXT, url TEXT, created_at TEXT)"""
BAD_PCT = 40.0     # 악성(폭락 경로)
WARN_PCT = 20.0    # 주의
PRE_SPLIT_DAYS = 180
_REF = r"(?:lowest|average|closing|market|trading|daily|vwap|volume[- ]weighted)"
PATS = [
    # conversion price equal to 50% of the lowest VWAP / closing price …
    ("전환사채", re.compile(r"conversion\s+price[^.]{0,220}?(?:equal\s+to|at|of|be)\s+(\d{2,3})\s*%\s+of\s+(?:the\s+)?(?:\w+\s+){0,3}?" + _REF, re.I), "pct_of"),
    # … at a 50% discount to the lowest closing price
    ("전환사채", re.compile(r"(\d{2,3})\s*%\s+discount\s+(?:to|of|from)\s+(?:the\s+)?(?:\w+\s+){0,3}?" + _REF, re.I), "discount"),
    # conversion price … discount of 50%
    ("전환사채", re.compile(r"conversion\s+price[^.]{0,220}?discount\s+of\s+(\d{2,3})\s*%", re.I), "discount"),
    # prepaid advance / prepaid forward / prepaid stock purchase (보통 큰 할인 + 선지급)
    ("선급주식매입", re.compile(r"pre-?paid\s+(?:advance|forward|equity\s+forward|share\s+purchase|stock\s+purchase|purchase)\s+(?:agreement|transaction|contract)?", re.I), "flag"),
    # 2026-10-30 WHLR 식: '전환가 … 재조정 … representing a 45% discount to $4.96' · 10-Q 각주 'volume weighted average … less a discount of 45 %'(기준어 없이 달러 값에 할인)
    ("전환사채", re.compile(r"conversion\s+price.{0,300}?representing\s+an?\s+(\d{2,3})\s*%\s+discount", re.I | re.S), "discount"),
    ("전환사채", re.compile(r"(?:volume[- ]weighted|vwap)[^.]{0,220}?less\s+a\s+discount\s+of\s+(\d{2,3})\s*%", re.I), "discount"),
    # 일반 할인 발행(ELOC 의 'purchase price = 95% of the lowest VWAP' 등) — 할인이 작으면 '기록'만
    ("할인 발행", re.compile(r"(\d{2,3})\s*%\s+of\s+(?:the\s+)?(?:\w+\s+){0,3}?" + _REF, re.I), "pct_of"),
]
KIND_HINT = re.compile(r"convertible\s+(?:promissory\s+)?(?:note|debenture)|senior\s+secured\s+convertible", re.I)


def level_of(discount: float | None, kind: str) -> str:
    if discount is not None and discount >= BAD_PCT:
        return "악성"
    if kind == "선급주식매입":   # 선급(prepaid) 구조는 할인이 작아도 주의, 40%↑ 면 악성
        return "악성" if (discount or 0) >= BAD_PCT else "주의"
    if discount is not None and discount >= WARN_PCT:
        return "주의"
    return "기록"


def detect(text: str, form: str = "") -> dict | None:
    """본문 → {"kind", "discount_pct", "level", "note"} 또는 None(할인 전환·선급 문구 없음)."""
    t = re.sub(r"\s+", " ", text or "")
    if not t:
        return None
    best: dict | None = None
    for kind, pat, mode in PATS:
        for m in pat.finditer(t):
            if mode == "flag":
                disc = None
                m2 = re.search(r"(\d{2,3})\s*%\s+(?:of|discount)", t[m.start():m.start() + 400], re.I)
                if m2:
                    v = float(m2.group(1))
                    disc = (100 - v) if "of" in m2.group(0).lower() else v
            else:
                v = float(m.group(1))
                disc = (100 - v) if mode == "pct_of" else v
            if disc is not None and not (0 < disc <= 95):
                continue
            cand = {"kind": kind if kind != "전환사채" or KIND_HINT.search(t) or "convertible" in t.lower() else "할인 발행",
                    "discount_pct": disc, "note": t[max(0, m.start() - 60):m.end() + 60].strip()[:220]}
            cand["level"] = level_of(disc, cand["kind"])
            rank = {"악성": 3, "주의": 2, "기록": 1}[cand["level"]]
            if best is None or rank > {"악성": 3, "주의": 2, "기록": 1}[best["level"]] or (rank == 3 and (disc or 0) > (best.get("discount_pct") or 0)):
                best = cand
    return best


def ensure(conn) -> None:
    conn.execute(DDL)


def record(conn, ticker: str, accession: str, filed: str, form: str, url: str, info: dict) -> bool:
    ensure(conn)
    cur = conn.execute("INSERT OR IGNORE INTO toxic_deals VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (accession, ticker.upper(), filed, form, info["kind"], info.get("discount_pct"), info["level"], info.get("note"), url, db.utcnow_iso()))
    return cur.rowcount > 0


def scan_and_record(conn, ticker: str, accession: str, filed: str, form: str, url: str, text: str) -> dict | None:
    """스캐너(secfeed.enrich)용: 8-K·424B·S-1 등 본문에서 감지되면 기록. 반환 info."""
    if not (form or "").upper().startswith(("8-K", "6-K", "424B", "S-1", "S-3", "F-1", "F-3")):
        return None
    info = detect(text, form)
    if info and info["level"] in ("악성", "주의"):
        record(conn, ticker, accession, filed or date.today().isoformat(), form, url, info)
        return info
    return None


def had_split_before(conn, ticker: str, filed: str, days: int = PRE_SPLIT_DAYS) -> str | None:
    """계약 전 days 일 안 병합 이력(rs_events) → 병합일 또는 None."""
    try:
        r = conn.execute("SELECT date FROM rs_events WHERE ticker=? AND date <= ? AND date >= date(?, ?) ORDER BY date DESC LIMIT 1",
                         (ticker.upper(), filed, filed, f"-{days} day")).fetchone()
        return r[0] if r else None
    except Exception:  # noqa: BLE001
        return None


def status(conn, ticker: str, days: int = 365) -> dict | None:
    """종목 헤더용: 최근 1년 안 가장 센 할인 계약 + 병합 이력 → {"level","kind","discount_pct","filed","split_date","path"}."""
    try:
        ensure(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM toxic_deals WHERE ticker=? AND filed >= date('now', ?) AND level IN ('악성','주의') ORDER BY filed DESC",
                                              (ticker.upper(), f"-{days} day"))]
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    r = sorted(rows, key=lambda x: ({"악성": 2, "주의": 1}[x["level"]], x["discount_pct"] or 0, x["filed"]), reverse=True)[0]
    sp = had_split_before(conn, ticker, r["filed"])
    return {**r, "split_date": sp, "path": bool(sp) and r["level"] == "악성"}


def badge(ticker: str) -> tuple[str, str] | None:
    """(문구, 색) — company_ui 헤더."""
    with closing(db.connect()) as conn:
        s = status(conn, ticker)
    if not s:
        return None
    d = "" if s["discount_pct"] is None else f" {s['discount_pct']:.0f}%"
    if s["path"]:
        return (f"⚠️ 폭락 경로: 병합({s['split_date']}) 뒤 할인 {s['kind']}{d} ({s['filed']})", "red")
    if s["level"] == "악성":
        return (f"⚠️ 대폭 할인 {s['kind']}{d} ({s['filed']})", "red")
    return (f"할인 {s['kind']}{d} 주의 ({s['filed']})", "orange")


def bottom_signals(conn, drop_pct: float = 70.0) -> list[dict]:
    """🏆 toxic_bottom: 악성 계약일 종가 대비 −drop% 에 처음 닿은 날(그날 종가 기준 · 그날 알 수 있는 정보만)."""
    out = []
    try:
        ensure(conn)
        deals = [dict(r) for r in conn.execute("SELECT ticker, filed, discount_pct FROM toxic_deals WHERE level='악성'")]
    except Exception:  # noqa: BLE001
        return out
    for d in deals:
        rows = conn.execute("SELECT date, close FROM daily_prices WHERE ticker=? AND date >= ? ORDER BY date", (d["ticker"], d["filed"])).fetchall()
        if not rows:
            continue
        base = next((float(c) for _, c in rows if c), None)
        if not base:
            continue
        for dt, c in rows:
            if c and float(c) <= base * (1 - drop_pct / 100):
                out.append({"ticker": d["ticker"], "date": dt, "price": float(c), "note": f"할인 계약 {d['filed']} 종가 ${base:.4f} 대비 −{drop_pct:.0f}% 도달"})
                break
    return out


def backfill(client, tickers: list[str], days: int = 400, out=print) -> dict:
    """소급: sec_feed·sec_hist 의 8-K/424B/6-K 본문을 읽어 감지(종목당 최대 20건)."""
    import rsplit
    n_doc = n_hit = 0
    hits = []
    with closing(db.connect()) as conn:
        ensure(conn)
        since = (date.today() - timedelta(days=days)).isoformat()
        for t in tickers:
            t = t.upper()
            rows = []
            try:
                rows += [dict(r) for r in conn.execute("SELECT accession, form, COALESCE(filed, substr(updated,1,10)) filed, url FROM sec_feed WHERE ticker=? AND filed >= ?", (t, since))]
            except Exception:  # noqa: BLE001
                pass
            try:
                cik = client.cik_for(t)
                for r in conn.execute("SELECT accession, form, filed FROM sec_hist WHERE ticker=? AND filed >= ?", (t, since)):
                    rows.append({"accession": r[0], "form": r[1], "filed": r[2], "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{r[0].replace('-', '')}/{r[0]}-index.htm" if cik else ""})
            except Exception:  # noqa: BLE001
                pass
            seen = set()
            rows = [r for r in rows if (r["form"] or "").upper().startswith(("8-K", "6-K", "424B", "S-1", "S-3", "F-1", "F-3")) and r["url"] and not (r["accession"] in seen or seen.add(r["accession"]))]
            rows.sort(key=lambda r: r["filed"] or "", reverse=True)
            for r in rows[:20]:
                try:
                    text = rsplit.filing_text(client, r["url"])
                except Exception:  # noqa: BLE001
                    continue
                n_doc += 1
                info = scan_and_record(conn, t, r["accession"], r["filed"], r["form"], r["url"], text)
                if info:
                    n_hit += 1
                    hits.append((t, r["filed"], r["form"], info["kind"], info["discount_pct"], info["level"]))
        conn.commit()
    out(f"할인 전환 소급: 문서 {n_doc}건 읽음 · 감지 {n_hit}건")
    for h in hits:
        out("  " + " · ".join(str(x) for x in h))
    return {"docs": n_doc, "hits": n_hit, "list": hits}


if __name__ == "__main__":
    import argparse
    import config
    import sec
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--days", type=int, default=400)
    a = ap.parse_args()
    backfill(sec.SecClient(config.SEC_USER_AGENT), a.tickers, days=a.days)
