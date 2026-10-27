"""🏛 상장유지 통지 재해석(1회 작업) — listing_notices 에 저장된 통지를 새 규칙(Item 3.01 구간만 검사, listing.section_301)으로 다시 읽는다.

예전 규칙은 8-K 본문 전체를 검사해서 끝의 상용구(Form 10-K 참조·감사위원회·연례 주총)까지 통지 종류로 잡혔다(2026-10-26 스크리너 카드 보완).
    python listing_reparse.py            # 미리 보기: 바뀌는 것만 표시, DB 안 건드림
    python listing_reparse.py --apply    # 적용: 바뀐 통지는 덮어쓰고(INSERT OR REPLACE), 예전 자동 일정('상장유지 기한')은 새 것으로 교체
새 규칙으로 '통지 아님'이 되는 건(거래소 이전·SPAC 정리·회복 완료 등) 지우지 않고 void=1 표시 → 화면·판정에서 빠지고, 그 자동 일정만 지운다.
"""
from __future__ import annotations

import json
import re
import sys
from contextlib import closing
from datetime import date, timedelta

import config
import db
import listing
import sec


def doc_text(client, url: str) -> str:
    """저장된 url 이 공시 목록 페이지(-index.htm)면 첫 본문 문서를 찾아 읽고, 아니면 그 문서를 바로 읽는다."""
    if not url:
        return ""
    if re.search(r"-index\.html?$", url):
        doc = listing.main_doc(client._get(url).text)
        return client.fetch_text("https://www.sec.gov" + doc, limit=200_000) if doc else ""
    return client.fetch_text(url, limit=200_000)


def main(apply: bool, days: int = 365, out=print, client=None) -> dict:
    client = client or sec.SecClient(config.SEC_USER_AGENT)
    since = (date.today() - timedelta(days=days)).isoformat()
    with closing(db.connect()) as conn:
        listing.ensure(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM listing_notices WHERE filed >= ? ORDER BY filed DESC", (since,))]
    n = {"total": len(rows), "same": 0, "changed": 0, "none": 0, "fail": 0}
    for r in rows:
        old = json.loads(r["kinds"] or "[]")
        try:
            text = doc_text(client, r.get("url") or "")
        except Exception as e:  # noqa: BLE001
            n["fail"] += 1
            out(f"  ⚠️ {r['ticker']} {r['filed'][:10]} 원문 못 읽음: {str(e)[:80]}")
            continue
        p = listing.parse(text, r["filed"][:10]) if text else None
        if p is None:
            if r.get("void"):
                n["same"] += 1
                continue
            n["none"] += 1
            out(f"  ❓ {r['ticker']} {r['filed'][:10]} 새 규칙으론 통지 아님 → void 표시 — 예전: {', '.join(old)}")
            if apply:
                with closing(db.connect()) as conn:
                    conn.execute("UPDATE listing_notices SET void=1 WHERE accession=?", (r["accession"],))
                    conn.execute("DELETE FROM events WHERE ticker=? AND kind='상장유지 기한' AND origin='자동' AND date=? AND title LIKE ?",
                                 (r["ticker"], r["deadline"], (old[0] if old else "") + " 회복 기한%"))
                    conn.commit()
            continue
        if r.get("void"):
            out(f"  ↩️ {r['ticker']} {r['filed'][:10]} 다시 통지로 인정 — {', '.join(p['kinds'])}")
        if p["kinds"] == old and p["deadline"] == r["deadline"] and p["threshold"] == r["threshold"]:
            n["same"] += 1
            continue
        n["changed"] += 1
        out(f"  ✏️ {r['ticker']} {r['filed'][:10]}: {', '.join(old)} · {r['threshold']} · 기한 {r['deadline']}  →  {', '.join(p['kinds'])} · {p['threshold']} · 기한 {p['deadline']}")
        if apply:
            with closing(db.connect()) as conn:  # 예전 자동 일정은 지우고(새 기한·새 이름으로 다시 들어감)
                conn.execute("DELETE FROM events WHERE ticker=? AND kind='상장유지 기한' AND origin='자동' AND date=? AND title LIKE ?",
                             (r["ticker"], r["deadline"], (old[0] if old else "") + " 회복 기한%"))
                conn.commit()
            listing.save(r["ticker"], r["accession"], r["filed"][:10], r.get("url") or "", p)
    out(f"총 {n['total']}건 · 그대로 {n['same']} · 바뀜 {n['changed']}{'(적용함)' if apply else '(미리 보기)'} · 통지 아님(void) {n['none']} · 원문 실패 {n['fail']}")
    return n


if __name__ == "__main__":
    main("--apply" in sys.argv)
