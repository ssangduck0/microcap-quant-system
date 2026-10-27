"""🎯 PICK +30% — 회사가 노리는 목표가(회사 압박 목표가 · 워런트 최저 행사가) 중 지금보다 위에 있는 가장 가까운 값이
+30% 이상 · +150% 이하이고, 하방 희석·매도 압력·다른 해결 방법이 없는 종목만 남긴다(김곰 PICK 방식).

고정 조건(순서대로, 탈락 수를 셈): 목표가 +30% 이상 → 도달 범위 안(+150% 이하) → 최근 미도달(20일 고가 < 목표가) → 하방 희석 없음(ATM·ELOC·전환사채)
→ 매도 압력 없음(행사가가 현재가보다 낮은 워런트가 주식 10% 이상 · 최근 60일 재판매 등록) → 다른 해결 방법 없음($1 목표인데 1년 안 병합 이력이 없으면 병합으로 해결 가능)
주총·역분할·결과 전 소송은 상승 요인으로 치지 않는다(임박도 계산에서 뺌). 상태: 유력(임박 14일↓ + 압박 5↑) · 가능(임박 45일↓ 또는 런웨이 3개월↓) · 대기.
'baby shelf 탈출'은 약한 목표: 기한이 없고, 도달하면 회사가 오히려 대량 조달(희석)할 수 있다 → '유력'이 될 수 없고 같은 상태 안에서 강한 목표(상장 유지·워런트·시총) 뒤로.
PICK 통과 종목은 매일 아침 🏆 성과 공표에 목표 종류별(강한 목표 / baby shelf)로 기록된다(같은 종목·목표는 30일에 한 번, 60거래일 안 목표가 도달 = 성공).
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta

import db

CONDS = ["목표가 있음", "목표가 +30% 이상", "목표가 도달 범위 안", "목표가 최근 미도달", "하방 희석 없음", "매도 압력 없음", "다른 해결 방법 없음"]
NOT_CATALYST = ("주총", "역분할", "병합", "소송")
WEAK_TARGETS = ("baby shelf",)  # 약한 목표: 기한 없음 · 도달 시 대량 조달 가능
LOG_DDL = """CREATE TABLE IF NOT EXISTS pick_signals (date TEXT NOT NULL, ticker TEXT NOT NULL, target_name TEXT NOT NULL, target REAL, price REAL, pct REAL,
             status TEXT, weak INTEGER, PRIMARY KEY (date, ticker, target_name))"""


def is_weak(target_name: str | None) -> bool:
    return bool(target_name) and any(k in target_name for k in WEAK_TARGETS)


def evaluate(t: str, conn, pr: dict | None, fsa: dict | None) -> dict:
    snap = conn.execute("SELECT price, high_20d, dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
    price = (snap["price"] if snap else None) or (fsa or {}).get("price")
    cands = [(n, v) for n, v, _ in (pr or {}).get("targets") or []]
    if fsa and fsa.get("min_ex"):
        cands.append(("워런트 최저 행사가", fsa["min_ex"]))
    above = sorted([(n, v) for n, v in cands if price and v > price], key=lambda x: x[1])
    tname, tval = above[0] if above else (None, None)
    pct = None if not (tval and price) else (tval / price - 1) * 100
    today = date.today()
    days = []
    ev = [dict(r) for r in conn.execute("SELECT date, kind, title FROM events WHERE ticker=? AND date >= ?", (t, today.isoformat()))] if conn.execute(
        "SELECT name FROM sqlite_master WHERE name='events'").fetchone() else []
    for e in ev:
        if not any(k in (e["kind"] + e["title"]) for k in NOT_CATALYST):
            days.append(((date.fromisoformat(e["date"]) - today).days, e["kind"]))
    n_ev = len(days)  # 📅 일정에서 온 임박 일(주총·역분할·소송 제외)
    rn = (fsa or {}).get("runway_info")
    if rn is None:  # 펀드스캔 딜이 없는 종목도 🪙 런웨이 저장소(SEC 재무)로
        try:
            import runway as _rwm
            rn = _rwm.now(t, conn)
        except Exception:  # noqa: BLE001
            rn = None
    use = bool(rn) and not rn.get("stale")  # 재무 기준일 200일↑(보고 지연)은 추정이 믿기 어려워 판정에 안 씀(이유에만 표시)
    floor = (rn or {}).get("floor") if use else (None if rn else (fsa or {}).get("floor"))
    if floor:
        days.append(((date.fromisoformat(floor) - today).days, "현금 바닥"))
    past = None
    if pr and pr.get("listing"):
        dl = (date.fromisoformat(pr["listing"]["deadline"]) - today).days
        if dl >= 0:
            days.append((dl, "상장유지 기한"))
        else:  # 이미 지난 기한은 임박으로 세지 않음(예전엔 음수라 '유력'으로 잘못 잡힐 수 있었음) — 연장·청문 여부는 원문 확인
            past = f"상장유지 기한 {-dl}일 지남(연장·청문 확인 필요)"
    runway = (rn or {}).get("runway_now") if use else None
    if runway is None and not rn:
        runway = (fsa or {}).get("runway_now")
    imm = min(days) if days else None
    fail = None
    if pct is None:
        fail = "목표가 있음"  # 회사 목표가(압박·워런트)를 아직 못 찾음
    elif pct < 30:
        fail = "목표가 +30% 이상"
    elif pct > 150:
        fail = "목표가 도달 범위 안"
    elif snap and snap["high_20d"] and tval and snap["high_20d"] >= tval:
        fail = "목표가 최근 미도달"
    elif (snap["dilution_status"] if snap else None) in ("ATM", "ELOC", "CB"):
        fail = "하방 희석 없음"
    else:
        itm = sum(w["qty"] for w in (fsa or {}).get("warrants") or [] if price and w["price"] and w["price"] < price)
        sh = (fsa or {}).get("shares") or (pr or {}).get("shares")
        resale = any(d["resale"] and d["filed"] >= (today - timedelta(days=60)).isoformat() for d in (fsa or {}).get("deals") or [])
        if (sh and itm >= 0.1 * sh) or resale:
            fail = "매도 압력 없음"
        elif tname == "$1 상장 유지":
            try:
                import shares as _sh
                split_1y = bool(_sh.splits_after(t, (today - timedelta(days=365)).isoformat(), conn))
            except Exception:  # noqa: BLE001
                split_1y = False
            if not split_1y:
                fail = "다른 해결 방법 없음"
    score = (pr or {}).get("score") or 0
    weak = is_weak(tname)
    status = "유력" if (imm is not None and imm[0] <= 14 and score >= 5 and not weak) else ("가능" if ((imm is not None and imm[0] <= 45) or (runway is not None and runway <= 3)) else "대기")
    why = reason(status, imm, score, runway, n_ev, bool(pr and pr.get("listing")), past, rn)
    return {"weak": weak, "why": why, "has_runway": runway is not None or bool(rn), "runway_info": rn, "has_listing": bool(pr and pr.get("listing")), "n_events": n_ev, "past": past,"ticker": t, "price": price, "target_name": tname, "target": tval, "pct": pct, "imm_days": None if imm is None else imm[0], "imm_kind": None if imm is None else imm[1],
            "pressure": score, "runway": runway, "status": status, "fail": fail}


def reason(status: str, imm, score, runway, n_ev: int, has_listing: bool, past: str | None, rn: dict | None = None) -> str:
    """왜 이 상태인지 한 줄(대기일 때 특히: 자료가 없어서인지, 일정이 멀어서인지)."""
    if rn:
        import runway as _rwm
        rw = _rwm.label(rn)
    else:
        rw = "런웨이 미확인" if runway is None else f"런웨이 {runway:.1f}개월"
    cash_tail = f" · {rw}" if (imm is not None and imm[1] == "현금 바닥") else ""
    if status == "유력":
        return f"{imm[1]} D-{imm[0]} · 압박 {score:g}{cash_tail}"
    if status == "가능":
        return f"{imm[1]} D-{imm[0]}{cash_tail}" if (imm is not None and imm[0] <= 45) else f"{rw}(3개월 이하)"
    if imm is None:
        out = f"임박 자료 없음 · {rw}"
    else:
        out = f"가장 가까운 {imm[1]} D-{imm[0]}(45일 넘음) · {rw}"
    return out + (f" · {past}" if past else "")


def why_stats(rows: list[dict]) -> dict:
    """통과 종목 중 '대기' 원인별 수 — 자료가 없어서인지(수집 문제) 일정이 멀어서인지(정상) 구분."""
    w = [r for r in rows if r["status"] == "대기"]
    return {"대기": len(w),
            "임박 자료 없음": sum(1 for r in w if r["imm_days"] is None),
            "일정이 45일 넘게 남음": sum(1 for r in w if r["imm_days"] is not None and r["imm_days"] > 45),
            "런웨이 미확인": sum(1 for r in w if not r["has_runway"]),
            "런웨이 3개월 넘음": sum(1 for r in w if r["runway"] is not None and r["runway"] > 3),
            "흑자(현금 소모 없음)": sum(1 for r in w if (r.get("runway_info") or {}).get("profitable")),
            "오래된 재무(200일↑)": sum(1 for r in w if (r.get("runway_info") or {}).get("stale")),
            "상장유지 통지 없음": sum(1 for r in w if not r["has_listing"]),
            "지난 상장유지 기한": sum(1 for r in w if r["past"])}


def scan() -> dict:
    import fundscan
    import pressure
    with closing(db.connect()) as conn:
        fundscan.ensure_tables(conn)
        reg = set(pressure.candidates(conn)) | {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM fs_deals")}
        rows = []
        for t in sorted(reg):
            try:
                pr = pressure.evaluate(t, conn, None, None)
            except Exception:  # noqa: BLE001
                pr = None
            try:
                fsa = fundscan.analyze(t, conn)
            except Exception:  # noqa: BLE001
                fsa = None
            rows.append(evaluate(t, conn, pr, fsa))
        try:
            acc = [r[0] for r in conn.execute("SELECT ticker FROM accum WHERE period='주간' AND date=(SELECT MAX(date) FROM accum) AND score >= 4 ORDER BY score DESC")]
        except Exception:  # noqa: BLE001
            acc = []
    funnel = {c: sum(1 for r in rows if r["fail"] == c) for c in CONDS}
    passed = [r for r in rows if not r["fail"]]
    return {"registered": len(rows), "why": why_stats(passed), "pass": passed, "fail": [r for r in rows if r["fail"]], "funnel": funnel,
            "unregistered": [t for t in acc if t not in reg]}


ORDER = {"유력": 0, "가능": 1, "대기": 2}


def sort(rows: list[dict], how: str) -> list[dict]:
    big = 10 ** 6
    if how == "임박 순":
        return sorted(rows, key=lambda r: (r["imm_days"] if r["imm_days"] is not None else big, -r["pressure"]))
    if how == "압박 순":
        return sorted(rows, key=lambda r: (-r["pressure"], r["imm_days"] if r["imm_days"] is not None else big))
    return sorted(rows, key=lambda r: (ORDER[r["status"]], bool(r.get("weak")), r["imm_days"] if r["imm_days"] is not None else big, -r["pressure"]))  # 같은 상태면 강한 목표 먼저


def record(conn, s: dict | None = None, today: date | None = None) -> int:
    """오늘 PICK 통과 종목을 🏆 성과 공표용으로 기록. 같은 종목·같은 목표는 30일에 한 번(매일 같은 신호가 쌓여 부풀지 않게)."""
    s = s or scan()
    today = today or date.today()
    conn.execute(LOG_DDL)
    recent = {(r[0], r[1]) for r in conn.execute("SELECT ticker, target_name FROM pick_signals WHERE date >= ?", ((today - timedelta(days=30)).isoformat(),))}
    n = 0
    for r in s["pass"]:
        if not (r["price"] and r["target"] and r["target_name"]) or (r["ticker"], r["target_name"]) in recent:
            continue
        conn.execute("INSERT OR IGNORE INTO pick_signals VALUES (?,?,?,?,?,?,?,?)",
                     (today.isoformat(), r["ticker"], r["target_name"], r["target"], r["price"], r["pct"], r["status"], 1 if r.get("weak") else 0))
        n += 1
    conn.commit()
    return n


# ---------------------------------------------------------------- 📊 PICK 변동: 매일 결과를 저장해 순위·상태 변화를 본다
HIST_DDL = """CREATE TABLE IF NOT EXISTS pick_hist (date TEXT NOT NULL, ticker TEXT NOT NULL, rank INTEGER, status TEXT, weak INTEGER, target_name TEXT,
              pct REAL, imm_days INTEGER, pressure REAL, price REAL, PRIMARY KEY (date, ticker))"""


def snapshot(conn, s: dict | None = None, today: date | None = None, force: bool = False) -> int:
    """오늘 PICK 통과 목록을 기본 정렬(유력·임박 순) 순위로 저장. 오늘 이미 있으면 그대로(force=True 면 다시)."""
    today = today or date.today()
    conn.execute(HIST_DDL)
    if not force and conn.execute("SELECT 1 FROM pick_hist WHERE date=? LIMIT 1", (today.isoformat(),)).fetchone():
        return 0
    s = s or scan()
    rows = sort(s["pass"], "유력·임박 순")
    conn.execute("DELETE FROM pick_hist WHERE date=?", (today.isoformat(),))
    conn.executemany("INSERT INTO pick_hist VALUES (?,?,?,?,?,?,?,?,?,?)",
                     [(today.isoformat(), r["ticker"], k, r["status"], 1 if r.get("weak") else 0, r.get("target_name"), r.get("pct"), r.get("imm_days"),
                       r.get("pressure"), r.get("price")) for k, r in enumerate(rows, 1)])
    conn.commit()
    return len(rows)


def changes(conn) -> dict:
    """가장 최근 기록 vs 그 직전 기록: 새로 들어옴 · 빠짐 · 순위 변화 · 상태 변화 · 목표 % 변화."""
    try:
        ds = [r[0] for r in conn.execute("SELECT DISTINCT date FROM pick_hist ORDER BY date DESC LIMIT 2")]
    except Exception:  # noqa: BLE001
        return {"dates": [], "rows": [], "gone": []}
    if not ds:
        return {"dates": [], "rows": [], "gone": []}
    cur = {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM pick_hist WHERE date=? ORDER BY rank", (ds[0],))}
    prev = {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM pick_hist WHERE date=? ORDER BY rank", (ds[1],))} if len(ds) > 1 else {}
    up = {"대기": 0, "가능": 1, "유력": 2}
    rows = []
    for t, r in cur.items():
        p = prev.get(t)
        mv = None if not p else p["rank"] - r["rank"]          # + = 올라감
        st_ = r["status"] if not p or p["status"] == r["status"] else f"{p['status']} → {r['status']}"
        rows.append({**r, "new": p is None and bool(prev), "move": mv, "status_change": st_ if p and p["status"] != r["status"] else None,
                     "status_up": None if not p or p["status"] == r["status"] else up.get(r["status"], 0) > up.get(p["status"], 0),
                     "pct_prev": None if not p else p["pct"]})
    gone = [dict(p) for t, p in prev.items() if t not in cur]
    return {"dates": ds, "rows": rows, "gone": gone}


def history(conn, t: str, n: int = 15) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute("SELECT date, rank, status, pct, imm_days FROM pick_hist WHERE ticker=? ORDER BY date DESC LIMIT ?", (t, n))]
    except Exception:  # noqa: BLE001
        return []
