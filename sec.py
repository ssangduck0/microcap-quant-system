"""SEC EDGAR 기반 희석(dilution) 판별.

기존 방식(atom 피드 제목에서 'ATM' 단어 찾기)은 제목에 서류 종류(8-K, 424B5...)만 있어서 거의 작동하지 않았습니다.
이 모듈은 다음 순서로 판별합니다.

  1) data.sec.gov/submissions 로 최근 공시 목록(서류 종류, 8-K Item 번호 포함)을 받는다.
  2) 희석과 관련된 서류(424B*, 8-K의 Item 1.01/2.03/3.02/8.01, 해외기업 6-K)만 골라 본문을 읽고 키워드를 찾는다.
  3) 본문 검사 결과는 accession 번호로 캐시해서 같은 공시를 다시 열지 않는다.
  4) 확인에 실패하면 '희석 없음'이 아니라 UNKNOWN(확인 불가)으로 표시한다.

주의: 키워드 검출은 '단서'이지 확정이 아닙니다. 대시보드에서 원문 링크로 반드시 확인하세요.
      ATM이 검출돼도 '잔여 한도'는 알 수 없습니다(공시 본문에서 별도 확인 필요).
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import date

import requests

import db

log = logging.getLogger("sec")

S = re.S | re.I
TAG_PATTERNS: dict[str, list[re.Pattern]] = {
    "ATM": [re.compile(p, S) for p in (
        r"at[- ]the[- ]market", r"equity distribution agreement", r"controlled equity offering",
        r"open market sale agreement", r"sales agreement.{0,300}?agent")],
    "ELOC": [re.compile(p, S) for p in (
        r"equity line", r"equity purchase agreement", r"standby equity", r"committed equity",
        r"put notice", r"reserve equity financing")],
    "CB": [re.compile(p, S) for p in (
        r"convertible (?:promissory |secured |senior )*(?:notes?|debentures?)",
        r"senior (?:secured )?convertible", r"convertible preferred")],
    "WARRANT": [re.compile(p, S) for p in (r"(?:pre-funded|common|series [a-z]) warrants?", r"warrants? to purchase")],
    "OFFERING": [re.compile(p, S) for p in (
        r"registered direct offering", r"public offering", r"private placement", r"placement agent")],
    "REVERSE_SPLIT": [re.compile(r"reverse (?:stock )?split", S)],
    "GOING_CONCERN": [re.compile(r"substantial doubt", S)],
}
# 태그별 유효 기간(일). 이 기간 안에 공시된 것만 현재 상태에 반영한다.
TAG_WINDOW_DAYS = {"ATM": 730, "ELOC": 365, "CB": 365, "WARRANT": 120, "OFFERING": 120,
                   "REVERSE_SPLIT": 365, "GOING_CONCERN": 365}
STATUS_PRIORITY = ["ATM", "CB", "ELOC", "OFFERING"]
RELEVANT_8K_ITEMS = {"1.01", "2.03", "3.02", "8.01"}
HEAD_CHARS = 15000  # 424B 는 표지(앞부분)만 본다: 본문 위험요인에 나오는 일반 문구로 인한 오탐 방지
SHELF_FORMS = {"S-3", "S-3/A", "S-3ASR", "F-3", "F-3/A"}


# ------------------------------------------------------------------ HTTP client
class SecClient:
    def __init__(self, user_agent: str):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self._last = 0.0
        self._map: dict[str, int] | None = None
        self._map_at = 0.0
        self._subs: dict[int, tuple[float, dict]] = {}  # 같은 사이클 안의 중복 요청 방지(희석 판정 + 공통 인텔이 같은 회사를 볼 때)

    def _throttle(self):  # SEC 한도: 초당 10회 이하
        wait = 0.12 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _get(self, url: str, **kw):
        self._throttle()
        r = self.s.get(url, timeout=20, **kw)
        r.raise_for_status()
        return r

    def cik_for(self, ticker: str) -> int | None:
        if self._map is None or time.time() - self._map_at > 86400:
            data = self._get("https://www.sec.gov/files/company_tickers.json").json()
            self._map = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
            self._map_at = time.time()
        return self._map.get(ticker.upper())

    SUBMISSIONS_TTL = 120.0  # 초. 새 공시 반영이 최대 2분 늦어질 수 있음

    def submissions(self, cik: int) -> dict:
        hit = self._subs.get(cik)
        if hit and time.time() - hit[0] < self.SUBMISSIONS_TTL:
            return hit[1]
        j = self._get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
        if len(self._subs) > 2000:
            self._subs.clear()
        self._subs[cik] = (time.time(), j)
        return j

    def companyfacts(self, cik: int) -> dict:
        return self._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()

    def fetch_text(self, url: str, limit: int = 600_000) -> str:
        return html_to_text(self.fetch_raw(url, limit))

    def fetch_raw(self, url: str, limit: int = 600_000) -> str:
        self._throttle()
        with self.s.get(url, timeout=25, stream=True) as r:
            r.raise_for_status()
            buf = b""
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) >= limit:
                    break
        return buf.decode("utf-8", errors="ignore")


# ------------------------------------------------------------------ text helpers
def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", raw)
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    txt = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(txt)).lower()


def scan_text(text: str, form: str) -> list[str]:
    head = text[:HEAD_CHARS] if form.startswith("424B") else text
    tags = []
    for tag, pats in TAG_PATTERNS.items():
        src = text if tag == "GOING_CONCERN" else head
        if any(p.search(src) for p in pats):
            tags.append(tag)
    return tags


def recent_filings(sub: dict, cik: int) -> list[dict]:
    r = sub.get("filings", {}).get("recent", {})
    out = []
    for i, acc in enumerate(r.get("accessionNumber", [])):
        doc = r["primaryDocument"][i]
        out.append({
            "accession": acc,
            "form": r["form"][i],
            "filed": r["filingDate"][i],
            "items": r.get("items", [""] * len(r["form"]))[i] or "",
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}",
        })
    return out  # SEC가 최신순으로 내려준다


def _age(f: dict, today: date) -> int:
    return (today - date.fromisoformat(f["filed"])).days


def select_candidates(filings: list[dict], today: date) -> list[dict]:
    c424 = [f for f in filings if f["form"].startswith("424B") and _age(f, today) <= 730][:8]
    c8k = [f for f in filings if f["form"] in ("8-K", "8-K/A") and _age(f, today) <= 365
           and RELEVANT_8K_ITEMS & {x.strip() for x in f["items"].split(",")}][:8]
    c6k = [f for f in filings if f["form"] == "6-K" and _age(f, today) <= 365][:8]  # 해외기업(FPI)
    return c424 + c8k + c6k


# ------------------------------------------------------------------ assessment
def assess(client: SecClient, conn, ticker: str, today: date | None = None) -> dict:
    today = today or date.today()
    res = {"ticker": ticker, "cik": None, "status": "UNKNOWN", "flags": {}, "evidence": [], "error": None}
    try:
        cik = client.cik_for(ticker)
        if not cik:
            res["error"] = "SEC CIK 없음 (ETF/ADR/신규상장/티커변경 가능성)"
            return res
        res["cik"] = cik
        filings = recent_filings(client.submissions(cik), cik)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"공시 목록 조회 실패: {e}"
        log.warning("%s: %s", ticker, res["error"])
        return res

    errors = 0
    scanned: list[tuple[dict, list[str]]] = []
    for f in select_candidates(filings, today):
        cached = db.get_filing(conn, f["accession"])
        if cached:
            tags = json.loads(cached["tags"] or "[]")
        else:
            try:
                tags = scan_text(client.fetch_text(f["url"]), f["form"])
                db.save_filing(conn, ticker, cik, f, tags)
            except Exception as e:  # noqa: BLE001
                errors += 1
                log.warning("%s %s 본문 확인 실패: %s", ticker, f["accession"], e)
                continue
        scanned.append((f, tags))

    # 서류 종류만으로 알 수 있는 단서
    form_tags: list[tuple[dict, list[str]]] = []
    for f in filings:
        age = _age(f, today)
        if f["form"] == "424B4" and age <= TAG_WINDOW_DAYS["OFFERING"]:
            form_tags.append((f, ["OFFERING"]))
        elif f["form"] in ("S-1", "S-1/A", "F-1", "F-1/A") and age <= TAG_WINDOW_DAYS["OFFERING"]:
            form_tags.append((f, ["OFFERING"]))

    flags = {t: False for t in TAG_PATTERNS}
    evidence = []
    for f, tags in scanned + form_tags:
        active = [t for t in tags if _age(f, today) <= TAG_WINDOW_DAYS[t]]
        for t in active:
            flags[t] = True
        if active:
            evidence.append({"accession": f["accession"], "form": f["form"], "filed": f["filed"],
                             "url": f["url"], "tags": active})
    flags["SHELF_S3"] = any(f["form"] in SHELF_FORMS and _age(f, today) <= 1095 for f in filings)
    flags["FOREIGN_FILER"] = any(f["form"] in ("6-K", "20-F") for f in filings[:50])
    flags["PARTIAL_CHECK"] = errors > 0

    status = next((s for s in STATUS_PRIORITY if flags.get(s) or (s == "OFFERING" and flags.get("WARRANT"))), None)
    if status is None:
        status = "UNKNOWN" if errors > 0 else "CLEAN"
    res.update(status=status, flags=flags, evidence=evidence)
    if errors:
        res["error"] = f"공시 {errors}건 본문 확인 실패 (일부만 검사됨)"
    return res


def get_dilution(conn, client: SecClient, ticker: str, refresh_hours: float, retry_hours: float) -> dict:
    row = db.get_dilution(conn, ticker)
    if row:
        limit = retry_hours if row["status"] == "UNKNOWN" else refresh_hours
        if db.is_fresh(row["checked_at"], limit):
            return row
    res = assess(client, conn, ticker)
    db.save_dilution(conn, res)
    return res
