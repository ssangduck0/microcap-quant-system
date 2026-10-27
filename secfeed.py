"""🔔 공시 알림 — SEC 실시간 공시 피드(EDGAR '최근 공시' Atom)를 받아 우리 종목 공시만 남기고, 8-K 항목·본문 키워드로 호재/악재·태그를 붙인다.

규칙 기반 판정(AI 요약 아님): 항목 번호와 키워드로 점수 → 호재(+2↑) / 약한 호재(+1) / 중립(0) / 주의(-1) / 악재(-2↓), 둘 다 있으면 '혼재'.
요약 문장이 필요하면 🧾 공시분석(Cowork 덕구 스캔)으로 보완한다. 모두 원문 확인 필요.
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import pandas as pd

import db

FEED = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={t}&company=&dateb=&owner=include&start=0&count=100&output=atom"
TYPES = ["8-K", "6-K", "424B", "S-1", "F-1", "EFFECT", "SCHEDULE 13D", "SCHEDULE 13G", "SC 13D", "SC 13G"]   # 2026-10-27: EDGAR 새 양식명 SCHEDULE 13D/G 추가(옛 SC 13D/G 는 호환용)
NS = {"a": "http://www.w3.org/2005/Atom"}
ITEMS = {  # 8-K 항목: (한글 이름, 점수, 태그)
    "1.01": ("중요 계약 체결", 0, "계약"), "1.02": ("중요 계약 해지", -1, "계약 해지"), "1.03": ("파산·회생", -3, "파산"),
    "2.01": ("인수·처분 완료", 0, "인수합병"), "2.02": ("실적 발표", 0, "실적"), "2.03": ("채무 발생", -1, "채무"),
    "2.04": ("채무 조기상환 사유", -2, "채무 가속"), "2.05": ("구조조정 비용", -1, "구조조정"), "2.06": ("자산 손상", -2, "손상"),
    "3.01": ("상장유지 미달·이전 통지", -2, "상장유지"), "3.02": ("미등록 증권 판매", -2, "희석 위험"), "3.03": ("주주 권리 변경", -1, "권리 변경"),
    "4.01": ("감사인 교체", -1, "감사인 교체"), "4.02": ("재무제표 신뢰 불가(정정)", -3, "재무 정정"),
    "5.01": ("지배권 변경", 0, "지배권 변경"), "5.02": ("임원·이사 변경", 0, "경영진 변경"), "5.03": ("정관 변경(병합·수권 등)", -1, "정관 변경"),
    "5.07": ("주총 결과", 0, "주총"), "7.01": ("공정공시(Reg FD)", 0, None), "8.01": ("기타 중요 사항", 0, None), "9.01": ("재무제표·첨부", 0, None),
}
FORMS = {"424B": (-2, "희석 위험", "공모·발행 투자설명서"), "S-1": (-2, "희석 위험", "증권 등록(S-1)"), "F-1": (-2, "희석 위험", "증권 등록(F-1)"),
         "EFFECT": (-2, "희석 임박", "등록 효력 발생"), "SC 13D": (0, "대량보유", "5% 이상 보유(13D)"), "SC 13G": (0, "대량보유", "5% 이상 보유(13G)"),
         "SCHEDULE 13D": (0, "대량보유", "5% 이상 보유(13D)"), "SCHEDULE 13G": (0, "대량보유", "5% 이상 보유(13G)"),
         "6-K": (0, None, "외국 기업 수시 공시(6-K)"), "8-K": (0, None, "수시 공시(8-K)")}
KEYWORDS = [  # (정규식, 태그, 점수)
    (r"reverse (?:stock |share )?split|share consolidation", "주식 병합", -1),
    (r"repurchase (?:program|plan)|share buyback|stock buyback", "자사주매입", 2),
    (r"\bFDA\b[^.]{0,80}(?:approv|clearance|cleared|grant)", "FDA 승인", 2),
    (r"(?:strategic )?partnership|collaboration agreement|distribution agreement|license agreement|joint venture", "파트너십·계약", 1),
    (r"purchase order|contract award|awarded a contract", "수주", 1),
    (r"private placement|registered direct|public offering|underwritten offering|securities purchase agreement|pre-funded warrant", "희석 위험", -2),
    (r"at[- ]the[- ]market|equity line|equity purchase agreement|sales agreement", "ATM/ELOC", -2),
    (r"going concern", "계속기업 의문", -2),
    (r"\d{2,3}\s*%\s+of\s+(?:the\s+)?(?:\w+\s+){0,3}?(?:lowest|average|closing|vwap|volume[- ]weighted)|\d{2,3}\s*%\s+discount\s+(?:to|of|from)|pre-?paid\s+(?:advance|forward|equity\s+forward|stock\s+purchase)", "할인 전환", -3),   # ⚠️ 대폭 할인 전환(OMH 패턴)
    (r"deficiency (?:letter|notice)|minimum bid price|delist", "상장유지", -1),
    (r"merger agreement|definitive agreement to acquire|business combination", "인수합병", 0),
    (r"name change|change its name|changed its name", "사명 변경", 0),
    (r"record revenue|revenue increased|net income of", "실적 개선", 1),
]
DDL = """CREATE TABLE IF NOT EXISTS sec_feed (accession TEXT PRIMARY KEY, ticker TEXT, cik INTEGER, form TEXT, company TEXT, filed TEXT, updated TEXT,
          items TEXT, url TEXT, tags TEXT, score INTEGER, sentiment TEXT, enriched INTEGER DEFAULT 0, created_at TEXT)"""


def ensure_tables(conn) -> None:
    conn.execute(DDL)
    if "lead" not in {r[1] for r in conn.execute("PRAGMA table_info(sec_feed)")}:
        conn.execute("ALTER TABLE sec_feed ADD COLUMN lead TEXT")  # 원문 핵심 문장(영문 발췌)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_feed_t ON sec_feed (ticker, updated)")
    conn.commit()


def parse_atom(xml: str) -> list[dict]:
    """EDGAR Atom → [{accession, cik, form, company, filed, updated, items:[...], url}]"""
    out = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for e in root.findall("a:entry", NS):
        title = (e.findtext("a:title", "", NS) or "").strip()
        m = re.match(r"(.+?) - (.+?) \((\d{6,10})\)", title)
        if not m:
            continue
        summ = e.findtext("a:summary", "", NS) or ""
        link = e.find("a:link", NS)
        acc = re.search(r"accession-number=([\d-]+)", e.findtext("a:id", "", NS) or "") or re.search(r"AccNo:\s*</b>\s*([\d-]+)", summ)
        filed = re.search(r"Filed:\s*</b>\s*(\d{4}-\d{2}-\d{2})", summ)
        out.append({"form": m.group(1).strip(), "company": m.group(2).strip(), "cik": int(m.group(3)), "accession": acc.group(1) if acc else None,
                    "filed": filed.group(1) if filed else None, "updated": e.findtext("a:updated", "", NS), "url": link.get("href") if link is not None else "",
                    "items": sorted(set(re.findall(r"Item (\d\.\d\d)", summ)))})
    return [x for x in out if x["accession"]]


def classify(form: str, items: list[str], text: str = "") -> tuple[int, list[str], str]:
    """(점수, 태그, 판정)."""
    score, tags, plus, minus = 0, [], False, False

    def add(s, t):
        nonlocal score, plus, minus
        score += s
        plus |= s > 0
        minus |= s < 0
        if t and t not in tags:
            tags.append(t)
    base = next((v for k, v in FORMS.items() if form.upper().startswith(k)), None)
    if base:
        add(base[0], base[1])
    for it in items:
        if it in ITEMS:
            add(ITEMS[it][1], ITEMS[it][2])
    t = re.sub(r"\s+", " ", text or "")[:80_000]
    for pat, tag, s in KEYWORDS:
        if re.search(pat, t, re.I):
            add(s, tag)
    sent = "혼재" if plus and minus else ("호재" if score >= 2 else "약한 호재" if score == 1 else "악재" if score <= -2 else "주의" if score == -1 else "중립")
    return score, tags, sent


def poll(client, tickers_by_cik: dict[int, str], types: list[str] | None = None) -> int:
    """피드를 받아 우리 종목 공시만 저장. 새로 저장한 건수."""
    n = 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        for ty in types or TYPES:
            try:
                xml = client._get(FEED.format(t=ty.replace(" ", "+")), headers={"Accept": "application/atom+xml"}).text
            except Exception:  # noqa: BLE001
                continue
            for f in parse_atom(xml):
                tk = tickers_by_cik.get(f["cik"])
                if not tk:
                    continue
                sc, tags, sent = classify(f["form"], f["items"])
                cur = conn.execute("""INSERT OR IGNORE INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at)
                                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
                                   (f["accession"], tk, f["cik"], f["form"], f["company"], f["filed"], f["updated"], ",".join(f["items"]), f["url"],
                                    json.dumps(tags, ensure_ascii=False), sc, sent, db.utcnow_iso()))
                n += cur.rowcount
        conn.commit()
    return n


_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"


def lead_of(text: str, max_chars: int = 520) -> str:
    """공시 본문에서 핵심 문장 발췌: 'On October 16, 2026, …' 처럼 사건을 설명하는 첫 문장부터 2~3문장. 없으면 Item 제목 뒤 첫 문장."""
    t = re.sub(r"\s+", " ", text or "")
    m = re.search(rf"\b(On {_MONTH} \d{{1,2}}, \d{{4}},? .{{30,}}?)(?=\s+Item \d\.\d\d|\s+SIGNATURE|$)", t)
    if not m:
        m = re.search(r"Item \d\.\d\d[^.]{0,120}?\.?\s+((?:The Company|The Registrant|[A-Z][A-Za-z&.,' -]{2,60} \(the \"Company\"\)).{30,}?)(?=\s+Item \d\.\d\d|\s+SIGNATURE|$)", t)
    if not m:
        return ""
    body = m.group(1)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", body)
    out = ""
    for x in sents[:3]:
        if len(out) + len(x) > max_chars:
            break
        out += (" " if out else "") + x
    return out or body[:max_chars]


def enrich(client, limit: int = 15) -> int:
    """본문 키워드로 다시 판정(공시 목록 페이지 → 주 문서). 아직 안 본 최근 공시부터 limit건."""
    done = 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        rows = conn.execute("SELECT accession, form, items, url FROM sec_feed WHERE enriched=0 ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        for r in rows:
            text = ""
            try:
                idx = client._get(r["url"]).text
                m = re.search(r'href="(/Archives/edgar/data/[^"]+\.(?:htm|html|txt))"', idx, re.I)
                if m and "-index" not in m.group(1):
                    text = client.fetch_text("https://www.sec.gov" + m.group(1), limit=200_000)
            except Exception:  # noqa: BLE001
                pass
            if text and len(text) < 4000 and r["form"].upper().startswith("6-K"):   # 6-K 표지뿐이면 첨부(보도자료)까지 읽어 태그·병합 판정(C단계)
                try:
                    import rsplit
                    text = rsplit.filing_text(client, r["url"]) or text
                except Exception:  # noqa: BLE001
                    pass
            sc, tags, sent = classify(r["form"], [x for x in (r["items"] or "").split(",") if x], text)
            conn.execute("UPDATE sec_feed SET tags=?, score=?, sentiment=?, lead=?, enriched=1 WHERE accession=?",
                         (json.dumps(tags, ensure_ascii=False), sc, sent, lead_of(text), r["accession"]))
            try:  # 💰 펀드스캔: 실시간 자금조달 공시는 바로 해석
                import fundscan
                if text and fundscan.is_deal(r["form"], r["items"] or ""):
                    tk2 = conn.execute("SELECT ticker, COALESCE(filed, substr(updated,1,10)) AS f FROM sec_feed WHERE accession=?", (r["accession"],)).fetchone()
                    fundscan.save_deal(conn, tk2["ticker"], r["accession"], tk2["f"], r["form"], r["items"] or "", r["url"], fundscan.parse_deal(text, r["form"]))
            except Exception:  # noqa: BLE001
                pass
            if text:  # ⚠️ 대폭 할인 전환·선급주식매입(OMH 패턴) 감지 → toxic_deals
                try:
                    import toxic
                    tk4 = conn.execute("SELECT ticker, filed FROM sec_feed WHERE accession=?", (r["accession"],)).fetchone()
                    toxic.scan_and_record(conn, tk4["ticker"], r["accession"], tk4["filed"] or date.today().isoformat(), r["form"], r["url"], text)
                except Exception:  # noqa: BLE001
                    pass
            if text and r["form"].upper().startswith(("8-K", "6-K", "424B", "DEF 14", "PRE 14")):  # 📅 병합 예정(C단계·P3): 역분할 시행일·비율 → 🗓 일정 '역분할 시행' (설명서·주총 서류 포함)
                try:
                    import rsplit
                    info = rsplit.upcoming_from_text(text)
                    if not info and len(text) < 4000:   # 6-K 표지만 있고 내용은 EX-99 보도자료인 경우
                        info = rsplit.upcoming_from_text(rsplit.filing_text(client, r["url"]))
                    if info:
                        tk3 = conn.execute("SELECT ticker, filed FROM sec_feed WHERE accession=?", (r["accession"],)).fetchone()
                        rsplit.record_upcoming(conn, tk3["ticker"], info, f"{r['form']} {tk3['filed'] or ''} {r['url']}".strip())
                except Exception:  # noqa: BLE001
                    pass
            if "3.01" in (r["items"] or "") and text:  # 🏛 상장유지 미달 통지: 기준 종류·회복 기한
                try:
                    import listing
                    tk = conn.execute("SELECT ticker, filed FROM sec_feed WHERE accession=?", (r["accession"],)).fetchone()
                    pl = listing.parse(text, tk["filed"] or date.today().isoformat())
                    if pl:
                        listing.save(tk["ticker"], r["accession"], tk["filed"] or date.today().isoformat(), r["url"], pl)
                except Exception:  # noqa: BLE001
                    pass
            done += 1
        conn.commit()
    return done


def feed(days: int = 7) -> pd.DataFrame:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
    df = db.read_df("SELECT * FROM sec_feed WHERE COALESCE(filed, substr(updated,1,10)) >= ? ORDER BY updated DESC", ((date.today() - timedelta(days=days)).isoformat(),))
    if df.empty:
        return df
    df["tags"] = df["tags"].map(lambda s: json.loads(s) if s else [])
    cnt = df.groupby("ticker")["accession"].transform("count")
    df["repeat"] = cnt >= 3  # 같은 종목 공시가 기간 안에 3건 이상 = 반복 공시
    return df


def item_names(items: str) -> list[str]:
    return [ITEMS[i][0] for i in (items or "").split(",") if i in ITEMS]


_MAP_CACHE: dict = {"at": 0.0, "map": {}}


def universe_map(client, ttl: float = 3600) -> dict[int, str]:
    """{CIK: 티커} — 우리가 보는 종목(과거 사례 대상·스캐너 기록·워치리스트·저금통)만. 1시간 캐시."""
    import time as _t
    if _MAP_CACHE["map"] and _t.time() - _MAP_CACHE["at"] < ttl:
        return _MAP_CACHE["map"]
    client.cik_for("AAPL")  # 티커 지도 불러오기
    tickers: set[str] = set()
    for sql in ("SELECT ticker FROM case_progress WHERE status='done'", "SELECT DISTINCT ticker FROM daily_snapshots"):
        try:
            tickers |= set(db.read_df(sql)["ticker"])
        except Exception:  # noqa: BLE001
            pass
    try:
        import piggy
        import watch
        tickers |= set(watch.scanner_priority()) | set(piggy.tickers())
    except Exception:  # noqa: BLE001
        pass
    m = {}
    for t in tickers:
        cik = (client._map or {}).get(str(t).upper())
        if cik and cik not in m:
            m[cik] = str(t).upper()
    _MAP_CACHE.update(at=_t.time(), map=m)
    return m


def new_rows_since(ts: str, tickers: set[str]) -> list[dict]:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM sec_feed WHERE created_at >= ? ORDER BY updated", (ts,)) if r["ticker"] in tickers]
