"""워치리스트 · 물량 장부(희석 심층) · 일정(기한 이벤트) · 브리핑/랭크 — 대시보드 기능(PC 실시간, quant.db).

물량 장부: 워런트·전환사채·ATM·ELOC·공모 물량을 행사가/전환가와 함께 기록하고 현재가 기준으로
  '지금 출회 가능(현재가 이하 행사가)' / '위 대역(현재가 위)' / '잠김' 물량과 바로 위 물량대까지의 거리를 계산한다.
  공시 원문에서 정규식으로 '후보'를 뽑지만 키워드 추출이라 틀릴 수 있어 '확인 필요' 상태로 넣고 사용자가 확정한다.
일정: 공시에서 주총·상장유지 기한·역분할 시행·워런트 만기·락업 해제를 추출하고, EFFECT(등록 효력)·424B(발행)·8-K 3.01(상장유지 미달)을
  서류 종류로 일정에 넣는다. 사용자가 직접 추가할 수도 있다. 모두 원문 확인 필요.
"""
from __future__ import annotations

import logging
import re
from contextlib import closing
from datetime import date, datetime, timedelta

import pandas as pd

import db
import sec

log = logging.getLogger("watch")
LISTS = ["관심", "보유", "그레이", "블랙"]
STATUSES = ["활성", "잠김", "소멸", "확인 필요"]
KINDS = ["워런트", "선지급 워런트", "전환사채", "ATM", "ELOC", "공모 주식", "사모(PIPE)", "기타"]
DDL = [
    """CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT PRIMARY KEY, list TEXT DEFAULT '관심', added_at TEXT, added_price REAL,
        note TEXT DEFAULT '', updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS overhang (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, kind TEXT, qty_m REAL, price REAL,
        expiry TEXT, status TEXT, source TEXT, note TEXT, origin TEXT, filed TEXT, created_at TEXT, ukey TEXT,
        UNIQUE (ticker, ukey))""",  # 중복 방지 키: NULL 은 UNIQUE 에서 서로 다른 값으로 취급되므로 문자열 키를 따로 둔다
    """CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, date TEXT NOT NULL, kind TEXT, title TEXT,
        source TEXT, origin TEXT, created_at TEXT, UNIQUE (ticker, date, kind, title))""",
    "CREATE TABLE IF NOT EXISTS watch_scan (ticker TEXT PRIMARY KEY, scanned_at TEXT, n_docs INTEGER, errors INTEGER)",
]


def ensure_tables(conn=None) -> None:
    if conn is None:
        with closing(db.connect()) as c:
            ensure_tables(c)
        return
    for d in DDL:
        conn.execute(d)
    conn.commit()


def _conn():
    c = db.connect()
    ensure_tables(c)
    return c


# ---------------------------------------------------------------- 워치리스트
def add(ticker: str, lst: str = "관심", price: float | None = None, note: str = "") -> None:
    t = ticker.strip().upper()
    if not t:
        return
    with closing(_conn()) as c:
        c.execute("""INSERT INTO watchlist (ticker, list, added_at, added_price, note, updated_at) VALUES (?,?,?,?,?,?)
                     ON CONFLICT(ticker) DO UPDATE SET list=excluded.list, updated_at=excluded.updated_at""",
                  (t, lst if lst in LISTS else "관심", db.utcnow_iso(), price, note, db.utcnow_iso()))
        c.commit()


def update(ticker: str, **fields) -> None:
    keys = [k for k in fields if k in ("list", "note", "added_price")]
    if not keys:
        return
    with closing(_conn()) as c:
        c.execute(f"UPDATE watchlist SET {', '.join(f'{k}=?' for k in keys)}, updated_at=? WHERE ticker=?",
                  (*[fields[k] for k in keys], db.utcnow_iso(), ticker.upper()))
        c.commit()


def remove(ticker: str) -> None:
    with closing(_conn()) as c:
        c.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))
        c.commit()


def all_items() -> pd.DataFrame:
    import access
    if access.is_guest():
        return pd.DataFrame(columns=['ticker', 'list'])
    with closing(_conn()):
        pass
    return db.read_df("SELECT ticker, list, added_at, added_price, note FROM watchlist ORDER BY CASE list WHEN '보유' THEN 0 WHEN '관심' THEN 1 WHEN '그레이' THEN 2 ELSE 3 END, ticker")


def lists_map() -> dict[str, str]:
    import access
    if access.is_guest():  # 👥 방문객에게는 ⭐ 관심·보유 표시를 보이지 않음
        return {}
    df = all_items()
    return dict(zip(df["ticker"], df["list"]))


def scanner_priority() -> list[str]:
    import access
    if access.is_guest():  # 👥 방문객에게는 내 관심 종목을 보이지 않음
        return []
    """스캐너가 항상 정밀 분석할 워치리스트 종목(블랙리스트 제외). DB 가 없거나 오류면 빈 목록."""
    try:
        return [t for t, l in lists_map().items() if l != "블랙"]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- 물량 장부
def _ukey(kind, qty_m, price, source) -> str:
    return f"{kind}|{'' if qty_m is None else round(float(qty_m), 6)}|{'' if price is None else round(float(price), 6)}|{source or ''}"


def add_overhang(ticker, kind, qty_m=None, price=None, expiry=None, status="활성", source="", note="", origin="수동", filed=None) -> bool:
    with closing(_conn()) as c:
        cur = c.execute("""INSERT OR IGNORE INTO overhang (ticker,kind,qty_m,price,expiry,status,source,note,origin,filed,created_at,ukey)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (ticker.upper(), kind, qty_m, price, expiry, status, source or "", note, origin, filed,
                                                                db.utcnow_iso(), _ukey(kind, qty_m, price, source if origin != "수동" else f"수동:{db.utcnow_iso()}:{note}")))
        c.commit()
        return cur.rowcount > 0


def overhang_rows(ticker: str, conn=None) -> pd.DataFrame:
    """conn 을 주면 그 연결로(순위 계산이 종목마다 부름 — 연결을 새로 안 열기, 2026-10-28)."""
    sql = ("SELECT id, kind, qty_m, price, expiry, status, note, origin, filed, source FROM overhang WHERE ticker=? ORDER BY "
           "CASE status WHEN '활성' THEN 0 WHEN '확인 필요' THEN 1 WHEN '잠김' THEN 2 ELSE 3 END, price")
    if conn is not None:
        ensure_tables(conn)
        return pd.read_sql_query(sql, conn, params=(ticker.upper(),))
    with closing(_conn()):
        pass
    return db.read_df(sql, (ticker.upper(),))


def save_overhang_edits(ticker: str, df: pd.DataFrame) -> None:
    """data_editor 결과를 그대로 저장(행 삭제 포함). id 가 없는 행은 새로 추가."""
    with closing(_conn()) as c:
        keep = [int(i) for i in df["id"].dropna()] if "id" in df else []
        if keep:
            c.execute(f"DELETE FROM overhang WHERE ticker=? AND id NOT IN ({','.join('?' * len(keep))})", (ticker.upper(), *keep))
        else:
            c.execute("DELETE FROM overhang WHERE ticker=?", (ticker.upper(),))
        for r in df.to_dict("records"):
            vals = (r.get("kind") or "기타", _f(r.get("qty_m")), _f(r.get("price")), r.get("expiry") or None, r.get("status") or "활성", r.get("note") or "")
            if r.get("id") is not None and not pd.isna(r.get("id")):
                c.execute("UPDATE overhang SET kind=?, qty_m=?, price=?, expiry=?, status=?, note=? WHERE id=? AND ticker=?", (*vals, int(r["id"]), ticker.upper()))
            elif any(v not in (None, "") for v in vals[1:3]) or r.get("note"):
                c.execute("INSERT OR IGNORE INTO overhang (ticker,kind,qty_m,price,expiry,status,note,origin,source,created_at,ukey) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (ticker.upper(), *vals, "수동", r.get("source") or "", db.utcnow_iso(), _ukey(vals[0], vals[1], vals[2], f"수동:{db.utcnow_iso()}:{len(keep)}:{vals[5]}")))
        c.commit()


def _f(x):
    try:
        return None if x is None or (isinstance(x, float) and pd.isna(x)) or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def overhang_summary(rows: list[dict], price: float | None) -> dict:
    """활성 물량을 현재가 기준으로 나눈다. 현재가 이하 행사가 = 지금 행사·매도 가능(출회 가능), 위 = 그 가격까지 오르면 나올 물량."""
    act = [r for r in rows if r.get("status") == "활성"]
    priced = [r for r in act if _f(r.get("price")) is not None and _f(r.get("qty_m")) is not None]
    out = {"below_m": None, "above_m": None, "next_price": None, "next_kind": None, "next_dist_pct": None,
           "no_price": [f"{r['kind']}" + (f" ({r['note']})" if r.get("note") else "") for r in act if _f(r.get("price")) is None],
           "locked_m": sum(_f(r.get("qty_m")) or 0 for r in rows if r.get("status") == "잠김") or 0.0,
           "pending": sum(1 for r in rows if r.get("status") == "확인 필요"), "n_active": len(act)}
    if price and price > 0:
        out["below_m"] = sum(_f(r["qty_m"]) for r in priced if _f(r["price"]) <= price)
        above = [r for r in priced if _f(r["price"]) > price]
        out["above_m"] = sum(_f(r["qty_m"]) for r in above)
        if above:
            nxt = min(above, key=lambda r: _f(r["price"]))
            out.update(next_price=_f(nxt["price"]), next_kind=nxt["kind"], next_dist_pct=(_f(nxt["price"]) / price - 1) * 100)
    return out


# ---------------------------------------------------------------- 일정
def add_event(ticker, day: str, kind: str, title: str, source: str = "", origin: str = "수동") -> bool:
    with closing(_conn()) as c:
        cur = c.execute("INSERT OR IGNORE INTO events (ticker,date,kind,title,source,origin,created_at) VALUES (?,?,?,?,?,?,?)",
                        (ticker.upper(), day, kind, title, source, origin, db.utcnow_iso()))
        c.commit()
        return cur.rowcount > 0


def delete_event(event_id: int) -> None:
    with closing(_conn()) as c:
        c.execute("DELETE FROM events WHERE id=?", (int(event_id),))
        c.commit()


def events_df(tickers: list[str] | None = None, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    with closing(_conn()):
        pass
    q, p = "SELECT id, ticker, date, kind, title, source, origin, created_at FROM events WHERE 1=1", []
    if tickers is not None:
        if not tickers:
            return pd.DataFrame(columns=["id", "ticker", "date", "kind", "title", "source", "origin", "created_at"])
        q += f" AND ticker IN ({','.join('?' * len(tickers))})"
        p += [t.upper() for t in tickers]
    if start:
        q += " AND date >= ?"
        p.append(start)
    if end:
        q += " AND date <= ?"
        p.append(end)
    df = db.read_df(q + " ORDER BY date, ticker", tuple(p))
    return dedupe_events(df)


def dedupe_events(df: pd.DataFrame) -> pd.DataFrame:
    """자동 일정이 같은 종목·같은 날·같은 종류로 여러 서류(S-1 과 정정본 S-1/A 등)에서 들어오면 가장 최근 것 하나만.
    직접 넣은 일정(수동)은 그대로 둠. (예전엔 '상장유지 기한 11-09' 가 두 줄씩 보였음)"""
    if df is None or df.empty or "origin" not in df.columns:
        return df
    auto = df["origin"].fillna("") == "자동"
    a = df[auto].sort_values("created_at").drop_duplicates(subset=["ticker", "date", "kind"], keep="last")
    return pd.concat([a, df[~auto]]).sort_values(["date", "ticker"]).reset_index(drop=True)


def trading_days_between(a: date, b: date) -> int:
    """a 다음 날부터 b 까지의 평일 수(공휴일은 고려하지 않음)."""
    if b <= a:
        return 0
    return sum(1 for i in range(1, (b - a).days + 1) if (a + timedelta(days=i)).weekday() < 5)


def dollar_streak(df: pd.DataFrame | None) -> dict:
    """마지막 거래일부터 거꾸로 센 연속 일수: 종가 ≥ $1 (나스닥 회복 요건 10거래일) / 종가 < $1 (30거래일이면 미달 통지 대상)."""
    if df is None or df.empty:
        return {"above": None, "below": None}
    closes = df["Close"].dropna().tolist()
    up = down = 0
    for c in reversed(closes):
        if c >= 1.0 and down == 0:
            up += 1
        elif c < 1.0 and up == 0:
            down += 1
        else:
            break
    return {"above": up, "below": down}


# ---------------------------------------------------------------- 공시 원문에서 후보 추출 (정규식 — 원문 확인 필요)
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_DATE = rf"({_MONTHS}\s+\d{{1,2}},\s+\d{{4}})"
_N = r"([\d,]+(?:\.\d+)?)"


def parse_date(s: str) -> date | None:
    s = re.sub(r"\s+", " ", s.replace(".", "")).strip().replace("Sept ", "Sep ")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _qty(s: str, million: str | None = None) -> float | None:
    try:
        v = float(s.replace(",", ""))
    except ValueError:
        return None
    return v * (1e6 if million else 1)


OVERHANG_PATTERNS = [
    ("선지급 워런트", re.compile(r"pre-funded\s+warrants?\s+to\s+purchase\s+(?:up\s+to\s+)?(?:an\s+aggregate\s+of\s+)?" + _N + r"\s+shares", re.I), "qty_only"),
    ("워런트", re.compile(r"(?<!pre-funded )warrants?\s+to\s+purchase\s+(?:up\s+to\s+)?(?:an\s+aggregate\s+of\s+)?" + _N + r"\s+shares[^.]{0,250}?exercise\s+price\s+of\s+\$\s?([\d.]+)", re.I), "qty_price"),
    ("전환사채", re.compile(r"convertible\s+(?:senior\s+)?(?:promissory\s+)?notes?[^.]{0,300}?conversion\s+price\s+(?:of\s+|equal\s+to\s+)?\$\s?([\d.]+)", re.I), "price_only"),
    ("ATM", re.compile(r"(?:at[- ]the[- ]market|sales\s+agreement|equity\s+distribution\s+agreement)[^.]{0,300}?(?:aggregate\s+(?:gross\s+sales|offering)\s+price\s+of|having\s+an\s+aggregate\s+offering\s+price\s+of)\s+(?:up\s+to\s+)?\$\s?" + _N + r"\s*(million)?", re.I), "usd"),
    ("ELOC", re.compile(r"(?:equity\s+line|common\s+stock\s+purchase\s+agreement|equity\s+purchase\s+agreement)[^.]{0,300}?up\s+to\s+\$\s?" + _N + r"\s*(million)?", re.I), "usd"),
    ("공모 주식", re.compile(_N + r"\s+shares\s+of\s+(?:its\s+|our\s+)?common\s+stock\s+at\s+(?:a|an)\s+(?:public\s+)?(?:offering\s+|purchase\s+)?price\s+of\s+\$\s?([\d.]+)", re.I), "qty_price"),
]
EVENT_PATTERNS = [
    ("주총", re.compile(r"annual\s+meeting\s+of\s+(?:stockholders|shareholders)[^.]{0,200}?(?:will\s+be\s+held|to\s+be\s+held|is\s+scheduled|scheduled)[^.]{0,60}?on\s+(?:\w+day,\s+)?" + _DATE, re.I)),
    ("임시주총", re.compile(r"special\s+meeting\s+of\s+(?:stockholders|shareholders)[^.]{0,200}?(?:will\s+be\s+held|to\s+be\s+held|is\s+scheduled|scheduled)[^.]{0,60}?on\s+(?:\w+day,\s+)?" + _DATE, re.I)),
    ("상장유지 기한", re.compile(r"(?:until|through|by)\s+" + _DATE + r"[^.]{0,80}?regain\s+compliance", re.I)),
    ("상장유지 기한", re.compile(r"regain\s+compliance[^.]{0,160}?(?:until|through|by|on\s+or\s+before)\s+" + _DATE, re.I)),
    ("역분할 시행", re.compile(r"reverse\s+(?:stock\s+)?split[^.]{0,200}?effective[^.]{0,40}?(?:on|as\s+of|at)\s+(?:\d{1,2}:\d{2}\s*[ap]\.?m\.?[^,]{0,20},?\s+(?:on\s+)?)?" + _DATE, re.I)),
    ("워런트 만기", re.compile(r"warrants?[^.]{0,200}?(?:will\s+expire|expire|expiring|exercisable\s+until)[^.]{0,40}?(?:on\s+)?" + _DATE, re.I)),
]
LOCKUP = re.compile(r"lock-?up[^.]{0,200}?(\d{2,3})\s+days", re.I)
FORM_EVENTS = {"EFFECT": ("희석 임박", "등록서류 효력 발생(EFFECT) — 발행·재판매 가능"),
               "424B": ("발행", "424B 투자설명서 — 공모/발행 진행")}


def extract(text: str, form: str, filed: str, url: str) -> tuple[list[dict], list[dict]]:
    """(물량 후보, 일정 후보). 키워드 정규식 추출 — 원문 확인 필요."""
    t = re.sub(r"\s+", " ", text)
    if form.startswith("424B"):
        t = t[:sec.HEAD_CHARS * 4]  # 424B 는 앞부분(표지·발행 요약)만 — 본문 위험요인의 일반 문구 오탐 방지
    over, seen = [], set()
    for kind, pat, mode in OVERHANG_PATTERNS:
        for m in pat.finditer(t):
            qty = price = None
            note = ""
            if mode == "qty_only":
                qty, price = _qty(m.group(1)), 0.0001
            elif mode == "qty_price":
                qty, price = _qty(m.group(1)), _f(m.group(2).rstrip("."))
            elif mode == "price_only":
                price = _f(m.group(1).rstrip("."))
            elif mode == "usd":
                usd = _qty(m.group(1), m.group(2))
                note = f"한도 ${usd / 1e6:,.1f}M" if usd else ""
            key = (kind, qty, price, note)
            if key in seen or (qty is not None and qty < 1000) or (price is not None and not (0 <= price < 10000)):
                continue
            seen.add(key)
            snip = t[max(0, m.start() - 40):m.end() + 40]
            over.append({"kind": kind, "qty_m": round(qty / 1e6, 4) if qty else None, "price": price, "note": note, "filed": filed, "source": url,
                         "snippet": snip[:260]})
    evs, eseen = [], set()
    for kind, pat in EVENT_PATTERNS:
        for m in pat.finditer(t):
            d = parse_date(m.group(1))
            if d and (kind, d) not in eseen:
                eseen.add((kind, d))
                evs.append({"kind": kind, "date": d.isoformat(), "title": f"{kind} ({form} {filed} 기재)", "source": url})
    for m in LOCKUP.finditer(t):
        n = int(m.group(1))
        if 30 <= n <= 365 and ("락업", n) not in eseen:
            eseen.add(("락업", n))
            d = date.fromisoformat(filed) + timedelta(days=n)
            evs.append({"kind": "락업 해제(추정)", "date": d.isoformat(), "title": f"락업 {n}일 — 공시일 {filed} 기준 추정", "source": url})
    return over, evs


SCAN_FORMS = ("8-K", "8-K/A", "6-K", "S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-3", "DEF 14A", "PRE 14A", "DEFA14A", "10-Q", "10-K", "20-F")


def scan_ticker(client, ticker: str, days: int = 365, max_docs: int = 12, today: date | None = None) -> dict:
    """최근 공시에서 물량·일정 후보를 찾아 저장. 서류 종류만으로 아는 일정(EFFECT·424B·8-K 3.01)도 넣는다."""
    today = today or date.today()
    t = ticker.upper()
    cik = client.cik_for(t)
    if not cik:
        return {"error": "SEC CIK 없음(ETF/ADR/신규상장/티커 변경 가능성)"}
    filings = sec.recent_filings(client.submissions(cik), cik)
    cutoff = (today - timedelta(days=days)).isoformat()
    recent = [f for f in filings if f["filed"] >= cutoff]
    n_ev = n_ov = errors = 0
    for f in recent:  # 서류 종류 자체가 일정인 것
        if f["form"] == "EFFECT":
            n_ev += add_event(t, f["filed"], *FORM_EVENTS["EFFECT"], source=f["url"], origin="자동")
        elif f["form"].startswith("424B"):
            n_ev += add_event(t, f["filed"], FORM_EVENTS["424B"][0], f"{f['form']} — 공모/발행 진행", source=f["url"], origin="자동")
        elif f["form"] in ("8-K", "8-K/A") and "3.01" in {x.strip() for x in f["items"].split(",")}:
            n_ev += add_event(t, f["filed"], "상장유지 미달", "8-K 3.01 — 상장유지 요건 미달 통지", source=f["url"], origin="자동")
    docs = [f for f in recent if f["form"].startswith("424B") or f["form"] in SCAN_FORMS]
    big = [f for f in docs if f["form"] in ("10-Q", "10-K", "20-F")][:1]  # 분기·연간 보고서는 가장 최근 1건만(용량이 큼)
    docs = [f for f in docs if f["form"] not in ("10-Q", "10-K", "20-F")][:max_docs - len(big)] + big
    for f in docs:
        try:
            text = client.fetch_text(f["url"], limit=2_000_000 if f in big else 600_000)
        except Exception as e:  # noqa: BLE001
            errors += 1
            log.warning("%s %s 본문 실패: %s", t, f["url"], e)
            continue
        over, evs = extract(text, f["form"], f["filed"], f["url"])
        for o in over:
            n_ov += add_overhang(t, o["kind"], o["qty_m"], o["price"], status="확인 필요", source=o["source"], note=(o["note"] + " · " if o["note"] else "") + "원문: " + o["snippet"][:180],
                                 origin="자동 후보", filed=o["filed"])
        for e in evs:
            if e["date"] >= (today - timedelta(days=30)).isoformat():  # 이미 한참 지난 날짜는 넣지 않음
                n_ev += add_event(t, e["date"], e["kind"], e["title"], source=e["source"], origin="자동")
    with closing(_conn()) as c:
        c.execute("INSERT OR REPLACE INTO watch_scan (ticker, scanned_at, n_docs, errors) VALUES (?,?,?,?)", (t, db.utcnow_iso(), len(docs), errors))
        c.commit()
    return {"docs": len(docs), "new_overhang": n_ov, "new_events": n_ev, "errors": errors}


# ---------------------------------------------------------------- 랭크
def rank(snaps: pd.DataFrame, tracked: pd.DataFrame | None, n_days: int) -> pd.DataFrame:
    """최근 n_days 거래일(스냅샷 날짜 기준) 동안 반복해서 잡힌 종목 순위."""
    if snaps.empty:
        return pd.DataFrame()
    dates = sorted(snaps["date"].unique())[-n_days:]
    sub = snaps[snaps["date"].isin(dates)].sort_values("date")
    g = sub.groupby("ticker").agg(발견일수=("date", "nunique"), 최근일=("date", "max"), 최고승률=("win_score", "max"), 최고퀀트=("quant_score", "max"),
                                  최저등락=("day_change_pct", "min"), 최대낙폭=("drawdown_pct", "min"), 최근가=("price", "last"), 희석=("dilution_status", "last"))
    if tracked is not None and not tracked.empty:
        tr = tracked[tracked["date"].isin(dates)].groupby("ticker").agg(다음날최고=("next_high_pct", "max"), 다음날종가평균=("next_close_pct", "mean"))
        g = g.join(tr, how="left")
    g = g.reset_index().sort_values(["발견일수", "최고승률", "최고퀀트"], ascending=[False, False, False], na_position="last")
    g.insert(0, "순위", range(1, len(g) + 1))
    return g
