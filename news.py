"""📰 뉴스 모음 — 보도자료 배포사(PR Newswire 등) 공식 RSS·Atom 피드를 받아 '(Nasdaq: ABCD)' 표기로 종목을 찾고 호재·악재 키워드를 붙인다.

크롤링이 아니라 공식 피드만 쓴다(최근 글만 제공). 과거 1~3년치는 SEC 8-K·6-K 첨부 보도자료(EX-99.1)로 모으는 것이 정확하고 안전하다(다음 단계).
피드 주소는 관리 모드에서 바꾸거나 추가할 수 있다(meta 'news_feeds').
"""
from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import db

# 10-23 점검: GlobeNewswire 는 주소 형식과 상관없이 프로그램 접속을 막음(HTTP 403) → PR Newswire 로 교체(200 확인)
DEFAULT_FEEDS = [
    "https://www.prnewswire.com/rss/news-releases-list.rss",
    "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
    "https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss",  # 소형 바이오 보도자료
]
BLOCKED_HOSTS = ("globenewswire.com",)  # 예전 기본값 — 저장된 목록에 이것만 있으면 새 기본값으로
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TICKER_RE = re.compile(r"\((?:[^()]*?;\s*)?(NASDAQ|Nasdaq|NasdaqCM|NasdaqGM|NasdaqGS|NYSE American|NYSE)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b")
GOOD = [r"\bFDA (?:approval|clearance|approves|grants)|breakthrough designation|orphan drug", r"\b(?:contract|purchase order|award)\b", r"partnership|collaboration|license agreement",
        r"record (?:revenue|quarter)|revenue (?:growth|increase)", r"\bpatent\b", r"to be acquired|definitive agreement to be acquired|merger agreement", r"uplist"]
BAD = [r"public offering|registered direct|private placement|priced (?:its|an) offering|at-the-market|ATM program", r"reverse (?:stock )?split", r"delist|Nasdaq notice|minimum bid|deficiency",
       r"going concern|bankruptcy|Chapter 11", r"warrant (?:inducement|exercise)"]
DDL = """CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY, ticker TEXT, exchange TEXT, title TEXT, summary TEXT, published TEXT, link TEXT, feed TEXT, tags TEXT,
         sentiment TEXT, fetched TEXT)"""


def feeds() -> list[str]:
    m = db.get_meta("news_feeds")
    try:
        v = json.loads(m["value"]) if m and m.get("value") else None
    except (TypeError, ValueError):
        v = None
    if v and all(any(h in u for h in BLOCKED_HOSTS) for u in v):  # 막힌 예전 기본 피드만 저장돼 있으면 새 기본값
        return list(DEFAULT_FEEDS)
    return v or list(DEFAULT_FEEDS)


def set_feeds(urls: list[str]) -> None:
    db.set_meta("news_feeds", json.dumps([u.strip() for u in urls if u.strip()]))


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()


def _when(s: str | None) -> str:
    if not s:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        try:
            return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            return datetime.now(timezone.utc).isoformat()


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 · Atom 모두 → [{id, title, summary, published, link}]"""
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall(".//a:entry", ns):
        link = e.find("a:link", ns)
        out.append({"id": (e.findtext("a:id", default="", namespaces=ns) or (link.get("href") if link is not None else "")).strip(),
                    "title": _clean(e.findtext("a:title", default="", namespaces=ns)), "summary": _clean(e.findtext("a:summary", default="", namespaces=ns) or e.findtext("a:content", default="", namespaces=ns)),
                    "published": _when(e.findtext("a:published", default="", namespaces=ns) or e.findtext("a:updated", default="", namespaces=ns)),
                    "link": link.get("href") if link is not None else ""})
    for it in root.findall(".//item"):
        out.append({"id": (it.findtext("guid") or it.findtext("link") or "").strip(), "title": _clean(it.findtext("title")), "summary": _clean(it.findtext("description")),
                    "published": _when(it.findtext("pubDate")), "link": (it.findtext("link") or "").strip()})
    return [x for x in out if x["id"] and x["title"]]


# 📢 법무법인 집단소송 광고("Class Action Lawsuit ... Application Deadline", "investors who lost ...") — 투자 판단에 쓸모없고 피드를 덮음
LAWSUIT_AD = re.compile(r"class action|lead plaintiff|application deadline|securities (?:fraud )?(?:class action|lawsuit|litigation)|shareholder (?:alert|rights law)"
                        r"|investors who (?:lost|purchased|acquired)|on behalf of (?:investors|shareholders)|law (?:firm|offices)\b.{0,60}(?:investigat|remind)"
                        r"|investigation (?:of|into) .{0,40}(?:on behalf|for investors)|rosen law|pomerantz|levi & korsinsky|bragar eagel|kahn swick|faruqi|robbins geller|bronstein",
                        re.I)


def is_lawsuit_ad(title: str, summary: str = "") -> bool:
    return bool(LAWSUIT_AD.search(f"{title or ''} {(summary or '')[:400]}"))


def classify(text: str) -> tuple[list[str], str]:
    if LAWSUIT_AD.search(text or ""):  # 소송 광고는 다른 키워드(‘acquisition’ 등)로 호재가 붙지 않게 따로
        return ["📢 소송 광고"], "중립"
    tags = []
    for pat, tag in zip(GOOD, ["FDA", "계약·수주", "제휴·라이선스", "실적 호조", "특허", "피인수·합병", "상장 이전(상향)"]):
        if re.search(pat, text, re.I):
            tags.append(tag)
    bad = []
    for pat, tag in zip(BAD, ["공모·사모(희석)", "주식 병합", "상장유지 위험", "존속 위험", "워런트 행사 유도"]):
        if re.search(pat, text, re.I):
            bad.append(tag)
    sent = "혼재" if tags and bad else ("호재" if tags else ("악재" if bad else "중립"))
    return tags + bad, sent


# 🔗 회사 이름으로 종목 연결: 피드 요약이 짧아 '(NASDAQ: ABCD)' 표기가 잘린 글도 우리 종목에 붙임(SEC 회사 이름 = 🏷 테마의 ticker_meta)
SUFFIX = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "llc", "lp", "plc", "sa", "nv", "ag", "se", "spa", "the",
          "holding", "holdings", "group", "class", "a", "b", "ordinary", "shares", "common", "stock", "adr", "ads", "de", "md", "new"}
COMMON = {"global", "international", "american", "national", "energy", "therapeutics", "pharmaceuticals", "technologies", "technology", "biosciences",
          "solutions", "industries", "resources", "partners", "capital", "financial", "health", "medical", "systems", "digital", "network", "networks",
          "brands", "foods", "entertainment", "communications", "holdings", "acquisition", "ventures", "minerals", "mining", "genetics", "power"}


def _norm(name: str) -> str:
    w = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and ")).split()
    while w and w[-1] in SUFFIX:  # 꼬리말 떼기(앞쪽 'the' 도)
        w.pop()
    while w and w[0] == "the":
        w.pop(0)
    return " ".join(w)


def name_index(conn) -> dict:
    """{정규화된 회사 이름: (티커, 거래소)} — 너무 흔하거나 짧은 한 단어 이름은 뺌."""
    try:
        rows = conn.execute("SELECT ticker, name FROM ticker_meta WHERE name IS NOT NULL AND name != ''").fetchall()
    except Exception:  # noqa: BLE001  (테마를 아직 안 만든 DB)
        return {}
    try:
        ex = {r[0]: r[1] for r in conn.execute("SELECT ticker, exchange FROM daily_snapshots GROUP BY ticker")}
    except Exception:  # noqa: BLE001
        ex = {}
    idx = {}
    for t, nm in rows:
        k = _norm(nm)
        words = k.split()
        if not words or (len(words) == 1 and (len(k) < 7 or k in COMMON)) or all(x in COMMON for x in words):
            continue
        idx[k] = (t, (ex.get(t) or "").upper() or None)
    return idx


def match_name(title: str, summary: str, idx: dict) -> tuple[str, str | None] | None:
    """제목·요약 앞부분에서 회사 이름 찾기(가장 긴 이름). 한 단어 이름은 제목이 그 이름으로 시작할 때만."""
    if not idx:
        return None
    nt = " " + _norm(title) + " "
    ns = " " + _norm((summary or "")[:300]) + " "
    best = None
    for k, v in idx.items():
        one = " " not in k
        hit = nt.startswith(" " + k + " ") if one else (f" {k} " in nt or f" {k} " in ns)
        if hit and (best is None or len(k) > len(best[0])):
            best = (k, v)
    return best[1] if best else None


def ingest(items: list[dict], feed: str) -> int:
    n = 0
    with closing(db.connect()) as conn:
        conn.execute(DDL)
        idx = name_index(conn)
        for x in items:
            m = TICKER_RE.search(x["title"] + " " + x["summary"])
            tags, sent = classify(x["title"] + " " + x["summary"])
            tk = ex = None
            if m:
                tk, ex = m.group(2), m.group(1).upper().replace("NASDAQGS", "NASDAQ").replace("NASDAQGM", "NASDAQ").replace("NASDAQCM", "NASDAQ")
            else:
                hit = match_name(x["title"], x["summary"], idx)
                if hit:
                    tk, ex = hit
                    tags = tags + ["🔗이름 연결"]
            # 열 이름을 꼭 적을 것 — 10/25~29 translate.ensure 가 열 5개(title_ko…)를 더한 뒤 "VALUES 11개" 가 OperationalError 로 실패해 닷새 동안 뉴스가 한 건도 안 들어왔음
            cur = conn.execute("INSERT OR IGNORE INTO news (id, ticker, exchange, title, summary, published, link, feed, tags, sentiment, fetched) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (x["id"], tk, ex, x["title"], x["summary"][:1500], x["published"], x["link"], feed, json.dumps(tags, ensure_ascii=False), sent,
                                datetime.now(timezone.utc).isoformat()))
            n += cur.rowcount
        relink(conn, idx)
        conn.execute("DELETE FROM news WHERE published < ?", ((datetime.now(timezone.utc) - timedelta(days=120)).isoformat(),))
        conn.commit()
    return n


def relink(conn, idx: dict | None = None, days: int = 7) -> int:
    """최근 글 중 종목이 비어 있는 것을 회사 이름으로 다시 연결(새로 받은 회사 이름이 생겼을 때도)."""
    idx = idx if idx is not None else name_index(conn)
    if not idx:
        return 0
    n = 0
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    for r in conn.execute("SELECT id, title, summary, tags FROM news WHERE ticker IS NULL AND published >= ?", (since,)).fetchall():
        hit = match_name(r[1], r[2], idx)
        if hit:
            tags = (json.loads(r[3]) if r[3] else []) + ["🔗이름 연결"]
            conn.execute("UPDATE news SET ticker=?, exchange=?, tags=? WHERE id=?", (hit[0], hit[1], json.dumps(tags, ensure_ascii=False), r[0]))
            n += 1
    return n


def refresh(http_get=None, ttl_min: int = 10, force: bool = False) -> dict:
    """피드마다 받기(10분 주기). {피드: 새 글 수 또는 오류}"""
    m = db.get_meta("news_last")
    if not force and m and m.get("value") and datetime.now(timezone.utc) - datetime.fromisoformat(m["value"]) < timedelta(minutes=ttl_min):
        return {}
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": UA, "Accept": "application/atom+xml, application/rss+xml, application/xml"}, timeout=20))
    res = {}
    for f in feeds():
        try:
            r = get(f)
            if getattr(r, "status_code", 200) >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            res[f] = ingest(parse_feed(r.text), f)
        except Exception as e:  # noqa: BLE001
            res[f] = f"오류: {type(e).__name__} {str(e)[:60]}".strip()  # HTTP 번호(403 차단 / 404 주소 틀림)가 보이게
    db.set_meta("news_last", datetime.now(timezone.utc).isoformat())
    db.set_meta("news_status", json.dumps(res, ensure_ascii=False))
    return res


def recent(days: int = 7):
    with closing(db.connect()) as conn:
        conn.execute(DDL)
    return db.read_df("SELECT * FROM news WHERE published >= ? ORDER BY published DESC", ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),))
