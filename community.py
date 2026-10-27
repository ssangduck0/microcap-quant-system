"""💬 커뮤니티 심리(참고용) — 스톡트윗츠 최근 메시지의 강세·약세 비율. 점수에는 넣지 않는다(커뮤니티 열기는 고점 신호일 때도 많음).

스톡트윗츠는 외부 접근을 자주 막아서 실패하면 '확인 불가'. 30분 캐시.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import db

URL = "https://api.stocktwits.com/api/2/streams/symbol/{t}.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def fetch(t: str, http_get=None, ttl_min: int = 30) -> dict:
    t = t.upper()
    key = f"community_{t}"
    m = db.get_meta(key)
    if m and m.get("value"):
        old = json.loads(m["value"])
        if datetime.now(timezone.utc) - datetime.fromisoformat(old["_at"]) < timedelta(minutes=ttl_min):
            return old
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=10))
    try:
        r = get(URL.format(t=t))
        j = r.json()
        msgs = j.get("messages") or []
        s = [((m.get("entities") or {}).get("sentiment") or {}).get("basic") for m in msgs]
        bull, bear = s.count("Bullish"), s.count("Bearish")
        out = {"ok": True, "n": len(msgs), "bull": bull, "bear": bear, "bull_pct": None if bull + bear == 0 else bull / (bull + bear) * 100,
               "watchers": (j.get("symbol") or {}).get("watchlist_count"), "last": (msgs[0].get("created_at") if msgs else None)}
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "err": type(e).__name__}
    out["_at"] = datetime.now(timezone.utc).isoformat()
    db.set_meta(key, json.dumps(out, ensure_ascii=False))
    return out
