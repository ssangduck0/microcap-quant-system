"""📐 발행주식 수 추정 — 야후 유통주식 대신 SEC 공시 표지의 발행주식 수를 기준으로, 그 뒤 분할을 반영하고 그 뒤 발행 공시가 있으면 경고한다.

1) dei:EntityCommonStockSharesOutstanding(10-Q·10-K 표지, 기준일 포함 — 여러 종류 주식은 같은 기준일끼리 합산), 없으면 us-gaap CommonStockSharesOutstanding
2) 기준일 뒤 분할(역분할 0.04 = 1:25) 곱하기 — 종목 리포트의 분할 이력 + 분할 기록(rs_events)
3) 기준일 뒤 424B·S-1·F-1·S-3·F-3·EFFECT 또는 8-K 3.02(미등록 증권 판매)가 있으면 '최근 발행 미반영 가능' 경고
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, timedelta

import db

ISSUE_FORMS = ("424B", "S-1", "F-1", "S-3", "F-3", "EFFECT")
DDL = "CREATE TABLE IF NOT EXISTS shares_info (ticker TEXT PRIMARY KEY, data TEXT, updated TEXT)"


def cover_shares(cf: dict) -> dict | None:
    for tax, name in (("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "CommonStockSharesOutstanding")):
        rows = (((cf.get("facts") or {}).get(tax) or {}).get(name) or {}).get("units", {}).get("shares") or []
        if not rows:
            continue
        last_end = max(r["end"] for r in rows)
        same = [r for r in rows if r["end"] == last_end]
        last_filed = max(r.get("filed", "") for r in same)
        same = [r for r in same if r.get("filed", "") == last_filed]
        total = sum(float(r["val"]) for r in {(r.get("accn"), r.get("frame"), r["val"]): r for r in same}.values())
        return {"shares": total, "asof": last_end, "filed": last_filed, "form": same[0].get("form"), "src": f"SEC {tax}:{name}"}
    return None


def splits_after(t: str, asof: str, conn) -> list[dict]:
    out = {}
    rep = db.get_report(t) or {}
    for s in (rep.get("company") or {}).get("splits") or []:
        if s.get("date", "") > asof:
            out[s["date"]] = float(s["ratio"])
    try:
        for d, r in conn.execute("SELECT date, ratio FROM rs_events WHERE ticker=? AND date > ?", (t, asof)):
            out.setdefault(d, float(r))
    except Exception:  # noqa: BLE001
        pass
    return [{"date": d, "ratio": r} for d, r in sorted(out.items())]


def issuance_after(t: str, asof: str, conn) -> list[str]:
    out = []
    for sql in ("SELECT filed, form, items FROM sec_hist WHERE ticker=? AND filed > ?",
                "SELECT COALESCE(filed, substr(updated,1,10)), form, items FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) > ?"):
        try:
            for d, fm, it in conn.execute(sql, (t, asof)):
                if str(fm).upper().startswith(ISSUE_FORMS) or "3.02" in str(it or ""):
                    out.append(f"{d} {fm}" + (" (3.02 미등록 증권 판매)" if "3.02" in str(it or "") else ""))
        except Exception:  # noqa: BLE001
            pass
    return sorted(set(out))


def estimate(t: str, client) -> dict | None:
    t = t.upper()
    cik = client.cik_for(t)
    if not cik:
        return None
    c = cover_shares(client.companyfacts(cik))
    if not c:
        return None
    with closing(db.connect()) as conn:
        conn.execute(DDL)
        sp = splits_after(t, c["asof"], conn)
        mult = 1.0
        for s in sp:
            mult *= s["ratio"]
        iss = issuance_after(t, c["asof"], conn)
        d = {**c, "splits_after": sp, "adjusted": c["shares"] * mult, "issuance_after": iss[:8], "warn": bool(iss)}
        conn.execute("INSERT OR REPLACE INTO shares_info VALUES (?,?,?)", (t, json.dumps(d, ensure_ascii=False), db.utcnow_iso()))
        conn.commit()
    return d


def get(t: str) -> dict | None:
    with closing(db.connect()) as conn:
        conn.execute(DDL)
        r = conn.execute("SELECT data, updated FROM shares_info WHERE ticker=?", (t.upper(),)).fetchone()
    return None if not r else {**json.loads(r[0]), "_updated": r[1]}


def best(t: str, yahoo_float: float | None = None) -> tuple[float | None, str]:
    """(주식 수, 출처 설명) — SEC 추정이 있으면 그것, 없으면 야후 유통주식(정확도 낮음)."""
    s = get(t)
    if s and s.get("adjusted"):
        tag = f"SEC 표지 {s['asof']} 기준" + (" · 이후 분할 반영" if s.get("splits_after") else "") + (" · ⚠️ 이후 발행 미반영 가능" if s.get("warn") else "")
        return float(s["adjusted"]), tag
    if yahoo_float:
        return float(yahoo_float), "야후 유통주식(병합·발행 직후엔 틀릴 수 있음)"
    return None, "주식 수 정보 없음"


def build_missing(client, tickers: list[str], limit: int = 60, out=print) -> int:
    """추정이 없거나 7일 지난 종목만(아침 작업·상한)."""
    n = 0
    cut = (date.today() - timedelta(days=7)).isoformat()
    for t in tickers:
        if n >= limit:
            break
        s = get(t)
        if s and str(s.get("_updated", ""))[:10] >= cut:
            continue
        try:
            if estimate(t, client):
                n += 1
        except Exception:  # noqa: BLE001
            continue
    out(f"발행주식 수 추정 {n}종목 갱신")
    return n


def turnover(t: str, volume: float | None = None, yahoo_float: float | None = None) -> dict | None:
    """회전율(%) = 거래량 ÷ 주식 수 × 100. 100% 넘으면 하루에 주식 전체가 한 번 넘게 손바뀜. 거래량이 없으면 가장 최근 저장분."""
    if volume is None:
        try:
            r = db.read_df("SELECT vol, date FROM daily_move WHERE ticker=? AND vol IS NOT NULL ORDER BY date DESC LIMIT 1", (t.upper(),))
            if r.empty:
                return None
            volume, day = float(r.iloc[0]["vol"]), r.iloc[0]["date"]
        except Exception:  # noqa: BLE001
            return None
    else:
        day = None
    sh, tag = best(t, yahoo_float)
    if not sh or not volume:
        return None
    return {"pct": volume / sh * 100, "volume": volume, "shares": sh, "tag": tag, "date": day}
