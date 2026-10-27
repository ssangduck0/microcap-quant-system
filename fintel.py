"""Fintel 공매도 데이터 (https://api.fintel.io/v1, 헤더 X-API-KEY, .env 의 FINTEL_API_KEY 필요 — 유료 API 키).

  /v1/securities/us/{symbol}/short-volume   일별 공매도 거래량(FINRA 장외 집계, 장 마감 후 공개) — 오늘 값은 장중에 없음
  /v1/securities/us/{symbol}/borrow-rate    대차 수수료·대차 가능 수량(장중 갱신)
  /v1/securities/us/{symbol}/short-interest 공매도 잔고(월 2회 공표)
응답 필드 이름은 공식 스펙을 직접 확인하지 못해 여러 이름(카멜/스네이크, 래퍼 객체)을 허용합니다.
`python fintel_check.py` 로 실제 응답과 파싱 결과를 확인하고, '값을 찾지 못함'이 나오면 원본을 알려 주세요(필드 이름을 맞춥니다).
결과는 DB(fintel_cache)에 항목별로 캐시합니다: 공매도 거래량 6시간, 대차 수수료 20분, 공매도 잔고 12시간.
"""
from __future__ import annotations

import json
import logging
import time as _time
from contextlib import closing

import requests

import db

log = logging.getLogger("fintel")
BASE = "https://api.fintel.io/v1"
TTL = {"short-volume": 6 * 3600, "borrow-rate": 20 * 60, "short-interest": 12 * 3600}
DDL = "CREATE TABLE IF NOT EXISTS fintel_cache (symbol TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT, fetched_at REAL, PRIMARY KEY (symbol, kind))"


# ---------------------------------------------------------------- 응답 해석 (필드 이름 변형 허용)
def _norm(k: str) -> str:
    return str(k).lower().replace("_", "").replace("-", "").replace(" ", "")


def _records(j) -> list[dict]:
    if isinstance(j, list):
        return [x for x in j if isinstance(x, dict)]
    if isinstance(j, dict):
        for key in ("data", "results", "items", "records", "history", "values"):
            if isinstance(j.get(key), list):
                return [x for x in j[key] if isinstance(x, dict)]
        return [j] if j else []
    return []


def _pick(d: dict, *names):
    nd = {_norm(k): v for k, v in d.items()}
    for n in names:
        v = nd.get(_norm(n))
        if v not in (None, ""):
            return v
    return None


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _date(r: dict) -> str | None:
    v = _pick(r, "date", "marketDate", "tradeDate", "settlementDate", "asOf", "timestamp")
    return str(v) if v is not None else None


def _latest(recs: list[dict]) -> dict | None:
    if not recs:
        return None
    dated = [r for r in recs if _date(r)]
    return max(dated, key=lambda r: _date(r)) if dated else recs[-1]


def parse_short_volume(j) -> dict | None:
    rows = []
    for r in _records(j):
        d = _date(r)
        s = _num(_pick(r, "shortVolume", "short", "shortVol"))
        t = _num(_pick(r, "totalVolume", "volume", "total", "totalVol"))
        if d and s is not None and t and t > 0:
            rows.append((d[:10], s, t))
    if not rows:
        return None
    rows.sort()
    d, s, t = rows[-1]
    last5 = rows[-5:]
    return {"sv_date": d, "sv_short": s, "sv_total": t, "sv_ratio": s / t * 100,
            "sv_avg5_ratio": sum(x[1] for x in last5) / sum(x[2] for x in last5) * 100}


def parse_borrow(j) -> dict | None:
    r = _latest(_records(j))
    if not r:
        return None
    fee = _num(_pick(r, "fee", "feeRate", "borrowFee", "borrowRate", "rate", "costToBorrow", "ctb"))
    avail = _num(_pick(r, "available", "sharesAvailable", "availableShares", "shares"))
    if fee is None and avail is None:
        return None
    return {"borrow_fee": fee, "borrow_avail": avail, "borrow_date": _date(r)}


def parse_short_interest(j) -> dict | None:
    r = _latest(_records(j))
    if not r:
        return None
    shares = _num(_pick(r, "shortInterest", "shortInterestShares", "shares", "si"))
    pct = _num(_pick(r, "percentFloat", "pctFloat", "shortInterestPercentFloat", "siPercentFloat", "percentOfFloat"))
    dtc = _num(_pick(r, "daysToCover", "dtc", "shortInterestRatio"))
    if shares is None and pct is None and dtc is None:
        return None
    d = _date(r)
    return {"si_date": d[:10] if d else None, "si_shares": shares, "si_pct_float": pct, "si_dtc": dtc}


PARSERS = {"short-volume": parse_short_volume, "borrow-rate": parse_borrow, "short-interest": parse_short_interest}


# ---------------------------------------------------------------- 클라이언트
def _status(e: Exception) -> int | None:
    code = getattr(getattr(e, "response", None), "status_code", None)
    if code:
        return int(code)
    try:
        return int(str(e).strip().split()[0])
    except (ValueError, IndexError):
        return None


class FintelClient:
    def __init__(self, key: str, session=None, timeout: float = 15.0):
        self.key = key
        self.session = session or requests.Session()
        self.timeout = timeout

    def url(self, kind: str, symbol: str) -> str:
        return f"{BASE}/securities/us/{symbol.upper()}/{kind}"

    def raw(self, kind: str, symbol: str):
        r = self.session.get(self.url(kind, symbol), headers={"X-API-KEY": self.key, "Accept": "application/json"}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _cache_get(conn, symbol: str, kind: str) -> dict | None:
        row = conn.execute("SELECT payload, fetched_at FROM fintel_cache WHERE symbol=? AND kind=?", (symbol, kind)).fetchone()
        if row and _time.time() - float(row["fetched_at"]) < TTL[kind]:
            return json.loads(row["payload"])
        return None

    def summary(self, symbol: str) -> dict:
        """세 항목을 모아 하나의 dict 로. 실패한 항목은 errors 에 사유를 남기고 나머지는 계속(키 오류면 중단)."""
        symbol = symbol.upper()
        out: dict = {"errors": []}
        with closing(db.connect()) as conn:
            conn.execute(DDL)
            for kind, parser in PARSERS.items():
                cached = self._cache_get(conn, symbol, kind)
                if cached is not None:
                    out.update(cached)
                    continue
                try:
                    j = self.raw(kind, symbol)
                except requests.HTTPError as e:
                    code = _status(e)
                    if code == 401:
                        out["errors"].append("Fintel API 키 오류(401) — .env 의 FINTEL_API_KEY 를 확인하세요")
                        break
                    out["errors"].append({403: f"{kind}: 현재 Fintel 플랜에서 제공되지 않음(403)", 404: f"{kind}: 데이터 없음(404)",
                                          429: f"{kind}: 호출 한도 초과(429) — 잠시 뒤 다시 시도"}.get(code, f"{kind}: {type(e).__name__} {e}"))
                    continue
                except Exception as e:  # noqa: BLE001 (네트워크 오류 등)
                    out["errors"].append(f"{kind}: {type(e).__name__}")
                    continue
                parsed = parser(j)
                if parsed is None:
                    out["errors"].append(f"{kind}: 응답에서 값을 찾지 못함 — python fintel_check.py 로 필드 이름 확인")
                    continue
                conn.execute("INSERT OR REPLACE INTO fintel_cache (symbol, kind, payload, fetched_at) VALUES (?,?,?,?)",
                             (symbol, kind, json.dumps(parsed), _time.time()))
                conn.commit()
                out.update(parsed)
        return out
