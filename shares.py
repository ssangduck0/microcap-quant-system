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
HIST_DDL = "CREATE TABLE IF NOT EXISTS shares_hist (ticker TEXT NOT NULL, asof TEXT NOT NULL, filed TEXT, form TEXT, shares REAL NOT NULL, PRIMARY KEY (ticker, asof))"  # 🐷 ⑥ 표지 발행주식 이력(2026-10-28)


def _points(cf: dict) -> tuple[str, list[dict]]:
    """표지 발행주식수 이력 — 기준일(end)마다 한 점: 같은 기준일은 가장 늦게 낸 서류의 값, 여러 종류 주식(Class A/B)은 합산.
    dei:EntityCommonStockSharesOutstanding 이 있으면 그것만, 없으면 us-gaap CommonStockSharesOutstanding. 반환 (출처 문자열, [{asof, filed, form, shares}] 기준일 순)."""
    for tax, name in (("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "CommonStockSharesOutstanding")):
        rows = (((cf.get("facts") or {}).get(tax) or {}).get(name) or {}).get("units", {}).get("shares") or []
        if not rows:
            continue
        out = []
        for end in sorted({r["end"] for r in rows}):
            same = [r for r in rows if r["end"] == end]
            last_filed = max(r.get("filed", "") for r in same)
            same = [r for r in same if r.get("filed", "") == last_filed]
            total = sum(float(r["val"]) for r in {(r.get("accn"), r.get("frame"), r["val"]): r for r in same}.values())
            out.append({"asof": end, "filed": last_filed, "form": same[0].get("form"), "shares": total})
        return f"SEC {tax}:{name}", out
    return "", []


def cover_shares(cf: dict) -> dict | None:
    """가장 최근 표지의 발행주식 수(기준일 포함) — _points 의 마지막 점."""
    src, pts = _points(cf)
    if not pts:
        return None
    p = pts[-1]
    return {"shares": p["shares"], "asof": p["asof"], "filed": p["filed"], "form": p["form"], "src": src}


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
    cf = client.companyfacts(cik)
    c = cover_shares(cf)
    if not c:
        return None
    with closing(db.connect()) as conn:
        conn.execute(DDL)
        save_history(conn, t, _points(cf)[1])   # 🐷 ⑥ 주식수 변동용 표지 이력(2026-10-28) — 같은 자료라 추가 요청 없음
        sp = splits_after(t, c["asof"], conn)
        mult = 1.0
        for s in sp:
            mult *= s["ratio"]
        iss = issuance_after(t, c["asof"], conn)
        d = {**c, "splits_after": sp, "adjusted": c["shares"] * mult, "issuance_after": iss[:8], "warn": bool(iss)}
        conn.execute("INSERT OR REPLACE INTO shares_info VALUES (?,?,?)", (t, json.dumps(d, ensure_ascii=False), db.utcnow_iso()))
        conn.commit()
    return d


def get(t: str, conn=None) -> dict | None:
    """conn 을 주면 그 연결을 쓴다(순위 계산처럼 수천 번 부를 때 연결을 새로 열지 않게 — 2026-10-28)."""
    if conn is None:
        with closing(db.connect()) as c:
            return get(t, c)
    conn.execute(DDL)
    r = conn.execute("SELECT data, updated FROM shares_info WHERE ticker=?", (t.upper(),)).fetchone()
    return None if not r else {**json.loads(r[0]), "_updated": r[1]}


def best(t: str, yahoo_float: float | None = None, conn=None) -> tuple[float | None, str]:
    """(주식 수, 출처 설명) — SEC 추정이 있으면 그것, 없으면 야후 유통주식(정확도 낮음). conn 을 주면 그 연결로."""
    s = get(t, conn)
    if s and s.get("adjusted"):
        tag = f"SEC 표지 {s['asof']} 기준" + (" · 이후 분할 반영" if s.get("splits_after") else "") + (" · ⚠️ 이후 발행 미반영 가능" if s.get("warn") else "")
        return float(s["adjusted"]), tag
    if yahoo_float:
        return float(yahoo_float), "야후 유통주식(병합·발행 직후엔 틀릴 수 있음)"
    return None, "주식 수 정보 없음"


def build_missing(client, tickers: list[str], limit: int = 60, out=print, force: bool = False, max_age: int = 7) -> int:
    """추정이 없거나 max_age 일(기본 7) 지난 종목만(아침 작업·상한). force 면 전부 다시(서버 소급 — 🐷 ⑥ 표지 이력 채우기).
    max_age=30: 스캐너 우주 전체를 한 달 주기로 돌아가며 갱신(⑥ 를 순위·PICK 에도 쓰므로, 2026-10-28)."""
    n, tried = 0, 0
    max_tries = max(limit * 3, 30)   # 2026-10-28: 성공이 없어도(SEC 자료 없는 종목·장애) 목록 끝까지 가지 않게 — 아침 작업 시간 상한
    cut = (date.today() - timedelta(days=max_age)).isoformat()
    with closing(db.connect()) as conn:   # 수천 종목을 훑을 때 연결 하나로
        for t in tickers:
            if n >= limit or tried >= max_tries:
                break
            s = get(t, conn)
            if not force and s and str(s.get("_updated", ""))[:10] >= cut:
                continue
            tried += 1
            try:
                if estimate(t, client):
                    n += 1
            except Exception:  # noqa: BLE001
                continue
    out(f"발행주식 수 추정 {n}종목 갱신" + (f"(시도 {tried}, 상한 {max_tries})" if tried >= max_tries else ""))
    return n


def turnover(t: str, volume: float | None = None, yahoo_float: float | None = None, conn=None) -> dict | None:
    """회전율(%) = 거래량 ÷ 주식 수 × 100. 100% 넘으면 하루에 주식 전체가 한 번 넘게 손바뀜. 거래량이 없으면 가장 최근 저장분. conn 을 주면 그 연결로(순위 계산용)."""
    if volume is None:
        try:
            sql = "SELECT vol, date FROM daily_move WHERE ticker=? AND vol IS NOT NULL ORDER BY date DESC LIMIT 1"
            if conn is not None:
                row = conn.execute(sql, (t.upper(),)).fetchone()
            else:
                with closing(db.connect()) as c:
                    row = c.execute(sql, (t.upper(),)).fetchone()
            if not row:
                return None
            volume, day = float(row[0]), row[1]
        except Exception:  # noqa: BLE001
            return None
    else:
        day = None
    sh, tag = best(t, yahoo_float, conn)
    if not sh or not volume:
        return None
    return {"pct": volume / sh * 100, "volume": volume, "shares": sh, "tag": tag, "date": day}


# ---------------------------------------------------------------- 🐷 ⑥ 주식수 변동(2026-10-28): 표지 이력 → 직전 두 분기 사이 변동률
def save_history(conn, t: str, points: list[dict]) -> int:
    """표지 발행주식 이력 저장(기준일마다 한 줄, 같은 기준일은 덮어씀)."""
    conn.execute(HIST_DDL)
    rows = [(t.upper(), p["asof"], p.get("filed"), p.get("form"), float(p["shares"])) for p in points if p.get("asof") and p.get("shares")]
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", rows)
    return len(rows)


def history(t: str, conn=None) -> list[dict]:
    """저장된 표지 이력(기준일 순). 없으면 []."""
    if conn is None:
        with closing(db.connect()) as c:
            return history(t, c)
    conn.execute(HIST_DDL)
    return [dict(r) for r in conn.execute("SELECT asof, filed, form, shares FROM shares_hist WHERE ticker=? ORDER BY asof", (t.upper(),))]


def change(t: str, conn=None, min_gap: int = 75, max_gap: int = 200, max_age: int = 200) -> dict | None:
    """🐷 ⑥ 용: 가장 최근 표지(s1·d1)와 그 전 분기 표지(d1 보다 min_gap~max_gap 일 전 중 가장 최근, s0·d0)의 발행주식 변동률. 두 표지 사이 분할(역분할)은 s0 에 반영.
    분기 보고(10-Q/10-K)는 약 90일 간격이라 '직전 두 분기 사이' 변동이다(최신 표지는 최대 석 달 전일 수 있음 — ChartExchange 일별 이력(유료)보다 느리지만 공식 숫자).
    None(판정 보류): 표지 2개 미만 · 연 1회 보고(20-F, 간격 365일 > max_gap) · 최신 표지가 max_age 일 넘게 오래됨(보고 중단)."""
    if conn is None:
        with closing(db.connect()) as c:
            return change(t, c, min_gap, max_gap, max_age)
    pts = history(t, conn)
    if len(pts) < 2:
        return None
    p1 = pts[-1]
    try:
        d1 = date.fromisoformat(p1["asof"])
    except ValueError:
        return None
    if (date.today() - d1).days > max_age:
        return None
    prev = []
    for p in pts[:-1]:
        try:
            gap = (d1 - date.fromisoformat(p["asof"])).days
        except ValueError:
            continue
        if min_gap <= gap <= max_gap:
            prev.append(p)
    if not prev:
        return None
    p0 = prev[-1]
    mult, n_sp = 1.0, 0
    for s in splits_after(t.upper(), p0["asof"], conn):
        if s["date"] <= p1["asof"]:
            mult *= s["ratio"]
            n_sp += 1
    s0 = float(p0["shares"]) * mult
    if s0 <= 0 or not p1["shares"]:
        return None
    return {"pct": (float(p1["shares"]) / s0 - 1) * 100, "d0": p0["asof"], "d1": p1["asof"], "from": s0, "to": float(p1["shares"]), "src": "SEC 표지", "splits": n_sp}


def hold_reason(t: str, conn=None, min_gap: int = 75, max_gap: int = 200, max_age: int = 200) -> str:
    """change() 가 None(판정 보류) 인 이유를 한 줄로(🐷 ⑥ 화면 값). 2026-10-28 서버 소급 결과 ➖ 143종목 중 82가 20-F 연 1회 보고라
    '표지 2개 미만' 한 문구로는 틀려서 이유별로 나눔: 표지 없음 · 1개 · 최신 표지 오래됨 · 연 1회 보고 · 직전 분기 표지 없음."""
    if conn is None:
        with closing(db.connect()) as c:
            return hold_reason(t, c, min_gap, max_gap, max_age)
    pts = history(t, conn)
    if not pts:
        return "SEC 표지 없음(XBRL 미제출·CIK 없음) · ChartExchange 없음"
    p1 = pts[-1]
    form = str(p1.get("form") or "")
    try:
        d1 = date.fromisoformat(p1["asof"])
        age = (date.today() - d1).days
        gap = (d1 - date.fromisoformat(pts[-2]["asof"])).days if len(pts) >= 2 else None
    except ValueError:
        return "SEC 표지 날짜 이상"
    if form.upper().startswith(("20-F", "40-F")):   # 연 1회 보고는 표지가 300일 됐어도 정상(10/28 서버: 42종목이 '중단' 으로 잘못 나옴) — 1년 반 넘으면 지연
        if age > 540:
            return f"연 1회 보고({form}) 인데 최신 표지가 {age}일 전({p1['asof']}) — 보고 지연·중단"
        return f"연 1회 보고({form} · 최신 표지 {p1['asof']}) — 분기 변동 판정 불가"
    if len(pts) == 1:
        return f"SEC 표지 1개뿐({p1['asof']} {form}) — 다음 분기 보고 뒤 판정"
    if age > max_age:
        return f"SEC 최신 표지가 {age}일 전({p1['asof']} {form}) — 보고 중단·지연"
    if gap > max_gap:
        return f"연 1회 보고({form} · 표지 간격 {gap}일) — 분기 변동 판정 불가"
    if gap < min_gap:
        return f"직전 분기 표지 없음(최근 두 표지 간격 {gap}일)"
    return "표지 값 이상(0 또는 음수)"
