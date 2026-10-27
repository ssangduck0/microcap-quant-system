"""📌 이벤트 한 줄 타임라인 — 최근 공시·병합·상장유지 통지·내부자 매수·앞으로의 일정을 '10/13 사외이사 선임'처럼 한 줄씩."""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, timedelta

import db

FORM_KO = [("424B", "공모·발행 가격 확정(424B)"), ("S-1", "증권 등록 신청(S-1)"), ("F-1", "증권 등록 신청(F-1)"), ("S-3", "증권 등록(S-3 선반)"), ("F-3", "증권 등록(F-3 선반)"),
           ("EFFECT", "등록 효력 발생 — 희석 임박"), ("DEF 14A", "주총 안건(위임장 확정)"), ("PRE 14A", "주총 안건(예비 위임장)"), ("10-Q", "분기 보고서"), ("10-K", "연간 보고서"),
           ("20-F", "연간 보고서(외국 기업)"), ("6-K", "수시 공시(외국 기업)"), ("SC 13D", "5% 이상 대량보유(13D)"), ("SC 13G", "5% 이상 대량보유(13G)"),
           ("SCHEDULE 13D", "5% 이상 대량보유(13D)"), ("SCHEDULE 13G", "5% 이상 대량보유(13G)")]
SKIP = ("4", "3", "5", "144", "SC 13G/A", "S-8")


def _form_text(form: str, items: str) -> str | None:
    import secfeed
    f = (form or "").upper()
    if f.startswith("8-K"):
        names = [secfeed.ITEMS[i][0] for i in (items or "").split(",") if i in secfeed.ITEMS and i not in ("9.01",)]
        return " · ".join(names) or "수시 공시(8-K)"
    if f in SKIP or f.startswith("4/"):
        return None
    for k, v in FORM_KO:
        if f.startswith(k):
            return v
    return None


def build(t: str, days: int = 120, ahead: int = 120) -> list[dict]:
    """[{date, icon, text, url}] 최신순(앞으로의 일정은 맨 위)."""
    t = t.upper()
    since, until = (date.today() - timedelta(days=days)).isoformat(), (date.today() + timedelta(days=ahead)).isoformat()
    rows, seen = [], set()
    with closing(db.connect()) as conn:
        def q(sql, params):
            try:
                return [dict(r) for r in conn.execute(sql, params)]
            except Exception:  # noqa: BLE001
                return []
        for r in q("SELECT accession, COALESCE(filed, substr(updated,1,10)) AS d, form, items, lead, url, tags FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) >= ?", (t, since)):
            txt = _form_text(r["form"], r["items"])
            if not txt:
                continue
            tags = json.loads(r["tags"] or "[]")
            lead = (r["lead"] or "").strip()
            rows.append({"date": r["d"], "icon": "📄", "text": txt + (f" — {', '.join(tags[:3])}" if tags else "") + (f" · “{lead[:110]}…”" if lead else ""), "url": r["url"]})
            seen.add(r["accession"])
        for r in q("SELECT accession, filed AS d, form, items FROM sec_hist WHERE ticker=? AND filed >= ?", (t, since)):
            if r["accession"] in seen:
                continue
            txt = _form_text(r["form"], r["items"])
            if txt:
                rows.append({"date": r["d"], "icon": "📄", "text": txt, "url": ""})
        for r in q("SELECT date, ratio FROM rs_events WHERE ticker=? AND date >= ?", (t, since)):
            rows.append({"date": r["date"], "icon": "🔁", "text": f"1:{round(1 / r['ratio']):g} 역분할(병합) 실행", "url": ""})
        for r in q("SELECT filed, kinds, deadline, deadline_est, url FROM listing_notices WHERE ticker=? AND filed >= ? AND COALESCE(void,0)=0", (t, since)):  # void = 통지 아님(재해석)
            rows.append({"date": r["filed"], "icon": "🏛", "text": f"나스닥 {json.loads(r['kinds'])[0]} 미달 통지 — 회복 기한 {r['deadline']}" + (" (추정)" if r["deadline_est"] else ""), "url": r["url"]})
        for r in q("SELECT date, owner, title, SUM(value) AS v FROM insider_tx WHERE ticker=? AND code='P' AND date >= ? GROUP BY date, owner", (t, since)):
            rows.append({"date": r["date"], "icon": "👤", "text": f"내부자 장내 매수 — {r['owner']}({r['title'] or '-'}) ${(r['v'] or 0):,.0f}", "url": ""})
        far = (date.today() + timedelta(days=365)).isoformat()  # 상장유지 기한은 멀어도(최대 1년) 보여 줌
        for r in q("SELECT date, kind, title FROM events WHERE ticker=? AND date >= ? AND (date <= ? OR (kind='상장유지 기한' AND date <= ?))",
                   (t, date.today().isoformat(), until, far)):
            rows.append({"date": r["date"], "icon": "🗓", "text": f"[예정] {r['kind']} — {r['title']}", "url": ""})
    rows.sort(key=lambda x: x["date"], reverse=True)
    return rows
