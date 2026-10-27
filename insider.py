"""👤 내부자 매수 — SEC Form 4(내부자 거래) 원문 XML 에서 장내 매수(거래 코드 P)를 골라 저장한다.

거래 코드: P 장내 매수 · S 장내 매도 · A 보상 지급 · M 옵션 행사 · F 세금 원천징수 · G 증여 등. 매수 신호는 P 만 본다(보상·행사는 제외).
스캐너가 매 사이클 SEC 실시간 공시 피드(type=4)를 받아 우리 종목(발행회사 기준)만 원문을 읽는다(사이클당 상한).
"""
from __future__ import annotations

import re
from contextlib import closing
from datetime import date, timedelta
from xml.etree import ElementTree as ET

import pandas as pd

import db
import secfeed

CODES = {"P": "장내 매수", "S": "장내 매도", "A": "보상 지급", "M": "옵션 행사", "F": "세금 원천징수", "G": "증여", "C": "전환", "X": "옵션 행사"}
DDL = ["""CREATE TABLE IF NOT EXISTS insider_tx (accession TEXT NOT NULL, seq INTEGER NOT NULL, ticker TEXT, owner TEXT, title TEXT, date TEXT, code TEXT,
          shares REAL, price REAL, value REAL, after_shares REAL, url TEXT, PRIMARY KEY (accession, seq))""",
       "CREATE TABLE IF NOT EXISTS insider_seen (accession TEXT PRIMARY KEY, ticker TEXT, url TEXT, done INTEGER DEFAULT 0, at TEXT)"]


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def _v(el, path):
    x = el.find(path)
    return None if x is None or x.text is None else x.text.strip()


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except ValueError:
        return None


def parse_form4(xml: str) -> list[dict]:
    """Form 4 XML → 비파생 거래 목록 [{owner, title, date, code, shares, price, ad, after}]"""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    owner = _v(root, "reportingOwner/reportingOwnerId/rptOwnerName") or ""
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    roles = []
    if rel is not None:
        if (_v(rel, "isDirector") or "") in ("1", "true"):
            roles.append("이사")
        if (_v(rel, "isOfficer") or "") in ("1", "true"):
            roles.append(_v(rel, "officerTitle") or "임원")
        if (_v(rel, "isTenPercentOwner") or "") in ("1", "true"):
            roles.append("10% 주주")
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        out.append({"owner": owner, "title": " · ".join(roles), "date": (_v(tx, "transactionDate/value") or "")[:10], "code": _v(tx, "transactionCoding/transactionCode") or "",
                    "shares": _f(_v(tx, "transactionAmounts/transactionShares/value")), "price": _f(_v(tx, "transactionAmounts/transactionPricePerShare/value")),
                    "ad": _v(tx, "transactionAmounts/transactionAcquiredDisposedCode/value") or "",
                    "after": _f(_v(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"))})
    return out


def poll(client, tickers_by_cik: dict[int, str]) -> int:
    """Form 4 피드에서 발행회사(Issuer)가 우리 종목인 공시를 대기열에 넣는다."""
    try:
        xml = client._get(secfeed.FEED.format(t="4"), headers={"Accept": "application/atom+xml"}).text
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        for e in ET.fromstring(xml).findall("a:entry", secfeed.NS) if xml.strip().startswith("<") else []:
            title = e.findtext("a:title", "", secfeed.NS) or ""
            m = re.match(r"4(?:/A)? - (.+?) \((\d{6,10})\) \((Issuer|Reporting)\)", title)
            acc = re.search(r"accession-number=([\d-]+)", e.findtext("a:id", "", secfeed.NS) or "")
            if not m or not acc or m.group(3) != "Issuer":
                continue
            t = tickers_by_cik.get(int(m.group(2)))
            link = e.find("a:link", secfeed.NS)
            if t and link is not None:
                n += conn.execute("INSERT OR IGNORE INTO insider_seen (accession, ticker, url, done, at) VALUES (?,?,?,0,?)", (acc.group(1), t, link.get("href"), db.utcnow_iso())).rowcount
        conn.commit()
    return n


def enrich(client, limit: int = 20) -> int:
    """대기 중인 Form 4 원문(XML)을 읽어 거래 저장."""
    done = 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        for r in conn.execute("SELECT accession, ticker, url FROM insider_seen WHERE done=0 ORDER BY at DESC LIMIT ?", (limit,)).fetchall():
            txs = []
            try:
                idx = client._get(r["url"]).text
                m = re.search(r'href="(/Archives/edgar/data/[^"]+?\.xml)"', idx)
                cand = [h for h in re.findall(r'href="(/Archives/edgar/data/[^"]+?\.xml)"', idx) if "xsl" not in h.lower()]
                if cand or m:
                    txs = parse_form4(client._get("https://www.sec.gov" + (cand[0] if cand else m.group(1))).text)
            except Exception:  # noqa: BLE001
                pass
            for i, x in enumerate(txs):
                val = (x["shares"] or 0) * (x["price"] or 0) if x["shares"] and x["price"] else None
                conn.execute("INSERT OR REPLACE INTO insider_tx VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (r["accession"], i, r["ticker"], x["owner"], x["title"], x["date"], x["code"], x["shares"], x["price"], val, x["after"], r["url"]))
            conn.execute("UPDATE insider_seen SET done=1 WHERE accession=?", (r["accession"],))
            done += 1
        conn.commit()
    return done


def buys(days: int = 30) -> pd.DataFrame:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
    return db.read_df("SELECT * FROM insider_tx WHERE code='P' AND date >= ? ORDER BY date DESC", ((date.today() - timedelta(days=days)).isoformat(),))


def summary_by_ticker(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    g = df.groupby("ticker").agg(총매수액=("value", "sum"), 주식수=("shares", "sum"), 건수=("accession", "nunique"), 내부자수=("owner", "nunique"),
                                 최근=("date", "max"), 직책=("title", lambda x: ", ".join(sorted({t for t in x if t}))[:60]))
    g["평단"] = g["총매수액"] / g["주식수"]
    return g.reset_index().sort_values(["최근", "총매수액"], ascending=[False, False])
