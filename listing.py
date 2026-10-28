"""🏛 상장유지 미달 통지 해석 — 8-K 3.01 본문에서 어떤 기준인지(주가 $1 · 상장증권 시가총액 · 자기자본 · 정기보고서 지연 …)와 회복 기한을 뽑는다.

기한 문구('until March 22, 2027' 등)가 있으면 그 날짜, 없으면 공시일 + 180일(추정). 뽑은 기한은 🗓 일정('상장유지 기한')에 넣어 회사 압박·종합 순위가 쓴다.
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta

import db

KINDS = [  # (정규식, 이름, 기본 기준)
    (r"minimum bid price|bid price requirement|closing bid price", "주가 $1 기준", "$1.00"),
    (r"market value of listed securities|\bMVLS\b", "상장증권 시가총액 기준", "$35M"),
    (r"stockholders['’]? equity|shareholders['’]? equity", "자기자본 기준", "$2.5M"),
    (r"market value of publicly held shares|\bMVPHS\b", "유통주식 시가총액 기준", "$1M"),
    (r"publicly held shares|round lot holders", "유통주식 수·주주 수 기준", ""),
    # 아래 셋은 8-K 끝의 상용구('자세한 위험은 Form 10-K 참조', '감사위원회가 검토')에도 걸리던 말이라 '미달·지연' 맥락이 있을 때만 잡는다
    (r"5250\(c\)|(?:fail\w*|not|delinquen\w*|late)[^.]{0,60}\b(?:timely\s+)?fil\w*[^.]{0,40}(?:Form 10-[QK]|Form 20-F|periodic|annual report|quarterly report)"
     r"|(?:Form 10-[QK]|Form 20-F|periodic (?:report|filing)|annual report|quarterly report)[^.]{0,60}(?:not (?:been )?(?:timely )?filed|delinquen|late filing|past due)", "정기보고서 지연", ""),
    (r"5620\(a\)|(?:fail\w*|not|did not)[^.]{0,40}hold[^.]{0,40}annual (?:shareholders['’]? |stockholders['’]? )?meeting"
     r"|annual (?:shareholders['’]? |stockholders['’]? )?meeting[^.]{0,80}(?:requirement|not (?:been )?held|deficien)", "연례 주총 미개최", ""),
    (r"5605|audit committee (?:requirement|composition|rule)|independent director requirement|majority of independent directors|board of directors composition", "이사회 구성 기준", ""),
    (r"5635|shareholder approval (?:requirement|rule)|without (?:prior )?(?:shareholder|stockholder) approval", "주주 승인 규정 위반", ""),
    # 통지문엔 늘 '불이행 시 상장폐지 통지를 받고 청문을 신청할 수 있다'는 가정 문구가 있어 '실제 결정·청문 신청' 표현만 잡는다. 주 통지로는 안 올림(아래 parse)
    (r"(?:staff|delist(?:ing)?) determination|determin\w+ to delist|will be delisted|delisted from|suspend(?:ed|ing)? trading in|(?:intends? to|has|have) request(?:ed)? a hearing"
     r"|Hearings Panel (?:granted|denied|determined|has|issued)", "상장폐지 결정·청문", ""),
]
SECONDARY = ("상장폐지 결정·청문",)  # 기준 금액이 없는 '상태' 종류 — 다른 기준이 있으면 뒤로
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DDL = """CREATE TABLE IF NOT EXISTS listing_notices (accession TEXT PRIMARY KEY, ticker TEXT, filed TEXT, kinds TEXT, threshold TEXT, deadline TEXT, deadline_est INTEGER,
          url TEXT, snippet TEXT)"""
VOID_COL = "ALTER TABLE listing_notices ADD COLUMN void INTEGER DEFAULT 0"  # 1 = 재해석 결과 미달 통지가 아님(거래소 이전·SPAC 정리·회복 완료 등). 기존 데이터 보존


def ensure(conn) -> None:
    conn.execute(DDL)
    try:
        conn.execute(VOID_COL)
    except Exception:  # noqa: BLE001  — 이미 있음
        pass


HEADING = re.compile(r"item\s+3\.01\.?\s*notice of delisting or failure to satisfy a continued listing rule or standard;?\s*transfer of listing\.?", re.I)


def main_doc(index_html: str) -> str | None:
    """공시 목록 페이지(-index.htm)에서 **본문 8-K 문서** 경로. 종류(Type) 칸이 8-K·6-K 인 줄의 링크를 고르고, 없으면 첫 .htm 링크.
    본문이 iXBRL 이면 링크가 '/ix?doc=/Archives/…' 꼴이라 예전 규칙(/Archives 로 시작)에 안 걸려 첨부(계약서·정관·보도자료)를 읽던 문제."""
    link = r'href="(?:/ix\?doc=)?(/Archives/edgar/data/[^"]+?\.(?:htm|html|txt))"'
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", index_html or "", re.I | re.S):
        if re.search(r"<td[^>]*>\s*(?:8-K|6-K)(?:/A)?\s*</td>", row, re.I):
            m = re.search(link, row, re.I)
            if m:
                return m.group(1)
    m = re.search(link, index_html or "", re.I)
    return m.group(1) if m else None


def section_301(text: str) -> str:
    """8-K 본문에서 **Item 3.01 구간만** 꺼낸다(다음 Item 또는 SIGNATURE 까지). 구간 제목이 없는 글(보도자료·요약)은 'Nasdaq/NYSE·notice·letter' 가 있는 문장 주변만.
    본문 전체를 검사하면 끝에 붙는 상용구(Form 10-K 참조·감사위원회·연례 주총)까지 '통지 종류'로 잘못 잡힌다(2026-10 스크리너 카드 보완)."""
    t = re.sub(r"\s+", " ", text or "")
    secs = [m.group(0) for m in re.finditer(r"Item\s+3\.01\b.*?(?=Item\s+\d\.\d\d\b|SIGNATURES?\b|$)", t, re.I | re.S)]
    body = " ".join(secs)
    if len(HEADING.sub(" ", body).strip()) > 300:
        return body
    # 구간이 없거나 '다른 항목의 내용을 여기 포함' 한 줄뿐 → 통지 문장('Nasdaq/NYSE·notice·letter') 주변만
    out, last = [], -1
    for m in re.finditer(r"Nasdaq|NYSE|notice|notif|letter", t, re.I):
        a, b = max(0, m.start() - 600), min(len(t), m.end() + 600)
        if a > last:
            out.append(t[a:b])
        else:
            out[-1] = out[-1] + t[last:b]
        last = b
    return " ".join(out)


RESOLVED = re.compile(r"(?<!not )(?<!not yet )regained compliance|(?:this )?matter is (?:now )?closed|back in compliance", re.I)
STILL_OPEN = re.compile(r"(?:new|second|additional|another|further) (?:letter|notice|notification|staff determination)|hearings? panel|delist", re.I)


def parse(text: str, filed: str) -> dict | None:
    t = HEADING.sub(" ", section_301(text))  # 항목 제목의 'delisting' 은 판단에서 뺀다
    if RESOLVED.search(t) and not STILL_OPEN.search(t):  # '기준을 회복했다'는 8-K(3.01 항목으로 올라옴)는 미달 통지가 아니다
        return None
    found = []
    for pat, n, th in KINDS:
        m = re.search(pat, t, re.I)
        if m:
            found.append((m.start(), n, th))
    kinds = [(n, th) for _, n, th in sorted(found)]  # 글에서 먼저 나온 기준이 '주 통지'(뒤에 '예전에 받은 통지'를 언급하는 경우가 많다)
    kinds = [k for k in kinds if k[0] not in SECONDARY] + [k for k in kinds if k[0] in SECONDARY]
    if not kinds:
        return None
    thr = ""
    if kinds[0][0] in ("상장증권 시가총액 기준", "자기자본 기준", "유통주식 시가총액 기준"):
        # 기준 금액 = 'minimum / at least / requirement' 바로 근처의 금액(회사의 현재 금액을 기준으로 잘못 읽어 '$0M' 이 되던 문제)
        m = re.search(r"(?:minimum|at least|requirement|required|requires)[^$.]{0,60}\$\s?(\d+(?:\.\d+)?)\s*(million|M)\b", t, re.I)
        if m and float(m.group(1)) > 0:
            thr = f"${float(m.group(1)):g}M"
    dates = []
    for s in re.findall(rf"(?:until|through|by|on or before|no later than)\s+({MONTH}\s+\d{{1,2}},\s+\d{{4}})", t, re.I):
        try:
            d = datetime.strptime(s.title(), "%B %d, %Y").date().isoformat()
            if d > filed:
                dates.append(d)
        except ValueError:
            pass
    est = not dates
    deadline = max(dates) if dates else (date.fromisoformat(filed) + timedelta(days=180)).isoformat()
    sn = re.search(r"[^.]{0,200}(?:Nasdaq|NYSE)[^.]{0,300}\.", t, re.I)
    return {"kinds": [k for k, _ in kinds], "threshold": thr or kinds[0][1], "deadline": deadline, "deadline_est": est, "snippet": (sn.group(0) if sn else t[:300]).strip()[:400]}


def save(ticker: str, accession: str, filed: str, url: str, p: dict) -> None:
    with closing(db.connect()) as conn:
        ensure(conn)
        conn.execute("INSERT OR REPLACE INTO listing_notices (accession, ticker, filed, kinds, threshold, deadline, deadline_est, url, snippet, void) VALUES (?,?,?,?,?,?,?,?,?,0)",
                     (accession, ticker.upper(), filed, json.dumps(p["kinds"], ensure_ascii=False), p["threshold"], p["deadline"], 1 if p["deadline_est"] else 0, url, p["snippet"]))
        conn.commit()
    if p["deadline"] >= date.today().isoformat():
        try:
            import watch
            watch.add_event(ticker.upper(), p["deadline"], "상장유지 기한", f"{p['kinds'][0]} 회복 기한" + (" (추정 180일)" if p["deadline_est"] else ""), origin="자동")
        except Exception:  # noqa: BLE001
            pass


def latest(ticker: str, days: int = 365, conn=None) -> dict | None:
    """conn 을 주면 그 연결로(순위 계산이 종목마다 부름 — 연결을 새로 안 열기, 2026-10-28)."""
    if conn is None:
        with closing(db.connect()) as c:
            return latest(ticker, days, c)
    ensure(conn)
    r = conn.execute("SELECT * FROM listing_notices WHERE ticker=? AND filed >= ? AND COALESCE(void,0)=0 ORDER BY filed DESC LIMIT 1",
                     (ticker.upper(), (date.today() - timedelta(days=days)).isoformat())).fetchone()
    return None if not r else {**dict(r), "kinds": json.loads(r["kinds"])}


def backfill(client, limit: int = 30, days: int = 365, out=print) -> int:
    """과거 공시 기록(sec_hist)의 8-K 3.01 중 아직 해석 안 한 것(아침 작업·상한)."""
    since = (date.today() - timedelta(days=days)).isoformat()
    with closing(db.connect()) as conn:
        ensure(conn)
        done = {r[0] for r in conn.execute("SELECT accession FROM listing_notices")}
        try:
            rows = [dict(r) for r in conn.execute("SELECT accession, ticker, filed FROM sec_hist WHERE form LIKE '8-K%' AND items LIKE '%3.01%' AND filed >= ? ORDER BY filed DESC", (since,))]
        except Exception:  # noqa: BLE001
            rows = []
    n = 0
    for r in rows:
        if n >= limit or r["accession"] in done:
            continue
        try:
            cik = client.cik_for(r["ticker"])
            idx = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{r['accession'].replace('-', '')}/{r['accession']}-index.htm"
            doc = main_doc(client._get(idx).text)
            text = client.fetch_text("https://www.sec.gov" + doc, limit=200_000) if doc else ""
            p = parse(text, r["filed"])
            if p:
                save(r["ticker"], r["accession"], r["filed"], idx, p)
                n += 1
        except Exception:  # noqa: BLE001
            continue
    out(f"상장유지 통지 해석 {n}건")
    return n
