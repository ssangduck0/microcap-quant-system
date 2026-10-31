"""🧾 공시분석 '재분석 필요' 배지(2026-10-31 · 김곰 워치리스트 v743·v808 참고).
분석일 뒤에 들어온 공시로 리포트가 낡았는지: 🔴 새 물량(공모 424B · 등록 효력 EFFECT · 미등록 발행 8-K 3.02) = 사실 구조가 바뀜 → 재분석 권장 ·
🟡 그 밖 중요한 공시(등록 서류 · 계약 · 주총 결과 · 상장유지 · 실적 · 분기/연간 보고서 · 144) = 참고.
자동 대기열(forensic_ai.auto_enqueue)은 🔴 종목을 새 종목보다 먼저 넣는다 — 하루 3종목 AI 예산을 바뀐 종목에."""
from __future__ import annotations

from datetime import date, timedelta

RED_FORMS = ("424B1", "424B2", "424B4", "424B5", "424B7", "EFFECT")
YELLOW_FORMS = ("S-1", "S-3", "F-1", "F-3", "S-1/A", "S-3/A", "F-1/A", "F-3/A", "10-Q", "10-K", "20-F", "6-K", "144", "DEF 14A", "PRE 14A")
YELLOW_ITEMS = ("1.01", "2.02", "3.01", "5.07", "1.03", "4.02")


def kind_of(form: str, items: str | None) -> str | None:
    f = str(form or "").upper()
    it = items or ""
    if f in RED_FORMS or (f.startswith("8-K") and "3.02" in it):
        return "red"
    if f in YELLOW_FORMS or (f.startswith("8-K") and any(x in it for x in YELLOW_ITEMS)):
        return "yellow"
    return None


def need(conn, t: str, as_of: str | None) -> dict:
    """{level: red|yellow|None, red: [(날짜, 서식)], yellow: [...], as_of}. 분석일 '다음 날'부터(같은 날 공시는 분석에 들어갔을 수 있음)."""
    out = {"level": None, "red": [], "yellow": [], "as_of": as_of}
    if not as_of:
        return out
    seen = set()
    rows = []
    for sql in ("SELECT filed, form, items, accession FROM sec_hist WHERE ticker=? AND filed > ?",
                "SELECT COALESCE(filed, substr(updated,1,10)), form, items, accession FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) > ?"):
        try:
            rows += [tuple(r) for r in conn.execute(sql, (t.upper(), str(as_of)[:10])).fetchall()]
        except Exception:  # noqa: BLE001
            pass
    for d, f, it, acc in sorted(rows):
        if acc in seen:
            continue
        seen.add(acc)
        k = kind_of(f, it)
        if k:
            out[k].append((str(d)[:10], str(f) + (f" {it}" if it and str(f).upper().startswith("8-K") else "")))
    out["level"] = "red" if out["red"] else ("yellow" if out["yellow"] else None)
    return out


def stale(conn, limit: int = 2, max_age: int = 120, today: date | None = None) -> list[str]:
    """최근 max_age 일 안 리포트가 있는데 그 뒤 🔴 새 물량 공시가 온 종목(많은 순)."""
    today = today or date.today()
    try:
        import forensic
        dates = forensic.latest_dates()
    except Exception:  # noqa: BLE001
        return []
    cut = (today - timedelta(days=max_age)).isoformat()
    cand = []
    for t, d in dates.items():
        if d < cut:
            continue
        n = need(conn, t, d)
        if n["red"]:
            cand.append((-len(n["red"]), d, t))
    return [t for _, _, t in sorted(cand)[:limit]]


def badge(n: dict) -> str:
    if n.get("level") == "red":
        return f"🔴 분석({n['as_of']}) 뒤 새 물량 공시 {len(n['red'])}건(" + ", ".join(f"{d} {f}" for d, f in n["red"][:3]) + ") — 재분석 권장"
    if n.get("level") == "yellow":
        return f"🟡 분석({n['as_of']}) 뒤 새 공시 {len(n['yellow'])}건 — 참고"
    return ""
