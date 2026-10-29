"""🔬 이벤트 연구 — 최근 3년 8-K·6-K 의 첨부 보도자료(EX-99.1) 제목·첫 문단을 모으고(수집), 공시 시각 기준으로 주가 반응을 자동 계산(라벨)해
사건 종류별 성과 통계와 🏁 순위 가중치 제안을 만든다. 크롤링이 아니라 SEC 공식 자료만 쓴다(초당 요청 제한 안에서 천천히).

python eventlab.py collect [--years 3] [--limit 0] [--tickers A,B]   공시 수집(이어받기)
python eventlab.py label                                              주가 반응 계산(일봉 3년 + IWM)
python eventlab.py run                                                하루 종일: 수집 → 라벨 → 1시간 쉬기 반복(start_collector.bat)

기준일: 접수 시각(동부) 16:00 이후 → 다음 거래일 · 09:30 전 → 그날 · 장중 → 그날(장중) · 시각 모르면 다음 거래일(보수적).
라벨: 갭(기준일 시가/전일 종가) · 당일(종가/전일 종가) · D+5 최고·최저·종가(기준일 포함 5거래일) · 거래량 배수 · IWM 대비 초과(당일·D+5).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta

import pandas as pd

import db

DDL = ["""CREATE TABLE IF NOT EXISTS ev_docs (accession TEXT PRIMARY KEY, ticker TEXT, form TEXT, items TEXT, filed TEXT, accepted TEXT, title TEXT, lead TEXT,
          types TEXT, sentiment TEXT, fetched TEXT, ok INTEGER)""",
       """CREATE TABLE IF NOT EXISTS ev_labels (accession TEXT PRIMARY KEY, ticker TEXT, day0 TEXT, timing TEXT, price REAL, gap REAL, ret0 REAL, up5 REAL, dn5 REAL, ret5 REAL,
          volx REAL, abn0 REAL, abn5 REAL)""",
       # 라벨 시도 기록: 주가 자료 없는 종목(상폐·티커 변경 추정)이 목록 앞을 계속 막던 문제 → 오래전에 시도한 종목부터 돌아가며
       "CREATE TABLE IF NOT EXISTS ev_label_try (ticker TEXT PRIMARY KEY, tried TEXT, status TEXT, n_pending INTEGER)"]
TYPES = [  # (이름, 정규식, 우선순위 낮을수록 먼저)
    ("공모·사모(희석)", r"public offering|registered direct|private placement|securities purchase agreement|at-the-market|pricing of|priced (?:an|its)", 1),
    ("주식 병합", r"reverse (?:stock )?split", 2),
    ("상장유지 통지", r"deficiency|minimum bid price|delist|listing qualifications|hearings panel", 3),
    ("파산·존속 위험", r"bankruptcy|chapter 11|going concern|wind down", 4),
    ("FDA·임상", r"\bFDA\b|clinical (?:trial|study|data)|phase [123i]+|topline|IND (?:clearance|application)|510\(k\)|breakthrough", 5),
    ("인수·합병", r"merger agreement|definitive agreement|to acquire|acquisition of|business combination|to be acquired", 6),
    ("계약·수주", r"\b(?:contract|purchase order|award(?:ed)?|supply agreement)\b", 7),
    ("제휴·라이선스", r"partnership|collaboration|license agreement|strategic alliance|memorandum of understanding|\bMOU\b", 8),
    ("실적 발표", r"(?:first|second|third|fourth) quarter|fiscal (?:year|20\d\d)|financial results|reports .{0,30}results", 9),
    ("가상자산·트레저리", r"bitcoin|crypto|digital asset|treasury strategy|token", 10),
    ("경영진·이사회", r"appoint|resign|chief executive|board of directors|named .{0,20}(?:CEO|CFO)", 11),
]
ITEM_TYPES = {"3.01": "상장유지 통지", "3.02": "공모·사모(희석)", "1.01": "계약·수주", "2.01": "인수·합병", "2.02": "실적 발표", "5.02": "경영진·이사회", "1.03": "파산·존속 위험",
              "5.03": "주식 병합"}
SKIP_LINE = re.compile(r"^(exhibit\s*99|for immediate release|press release|news release|source:|contact|investor relations|\(?nasdaq|\(?nyse|page \d)", re.I)


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def parse_index(html: str) -> dict:
    """공시 색인 페이지 → {accepted: 'YYYY-MM-DD HH:MM:SS'(동부), ex99: 보도자료 주소, main: 본문 주소}"""
    m = re.search(r"Accepted</div>\s*<div class=\"info\">\s*([\d-]+ [\d:]+)", html)
    out = {"accepted": m.group(1) if m else None, "ex99": None, "main": None}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        h = re.search(r'href="(/Archives/edgar/data/[^"]+\.(?:htm|html|txt))"', tr, re.I)
        if not h:
            continue
        typ = re.findall(r"<td[^>]*>\s*([A-Z0-9][A-Z0-9.\-/ ]{0,20})\s*</td>", tr)
        typ = " ".join(typ).upper()
        if re.search(r"\bEX-99(?:\.1|\.01)?\b", typ) and not out["ex99"]:
            out["ex99"] = "https://www.sec.gov" + h.group(1)
        elif re.search(r"\b(8-K|6-K)\b", typ) and not out["main"]:
            out["main"] = "https://www.sec.gov" + h.group(1)
    return out


def headline(text: str) -> tuple[str, str]:
    """보도자료 텍스트 → (제목, 첫 문단 ~1,200자)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    title, rest = "", []
    for i, ln in enumerate(lines[:40]):
        if SKIP_LINE.match(ln) or len(ln) < 25 or re.fullmatch(r"[\d\s,./:-]+", ln):
            continue
        title, rest = ln[:250], lines[i + 1:]
        break
    lead = re.sub(r"\s+", " ", " ".join(rest))[:1200]
    return title, lead


def classify(items: str, text: str) -> tuple[list[str], str]:
    found = {ITEM_TYPES[i] for i in (items or "").split(",") if i in ITEM_TYPES}
    for name, pat, _ in TYPES:
        if re.search(pat, text or "", re.I):
            found.add(name)
    order = {n: p for n, _, p in TYPES}
    types = sorted(found, key=lambda n: order.get(n, 99))
    bad = {"공모·사모(희석)", "주식 병합", "상장유지 통지", "파산·존속 위험"}
    good = {"FDA·임상", "인수·합병", "계약·수주", "제휴·라이선스"}
    sent = "혼재" if (set(types) & bad and set(types) & good) else ("악재" if set(types) & bad else ("호재" if set(types) & good else "중립"))
    return types or ["기타"], sent


def targets(conn, years: int = 3, tickers: list[str] | None = None) -> list[dict]:
    since = (date.today() - timedelta(days=int(365 * years))).isoformat()
    ensure_tables(conn)
    done = {r[0] for r in conn.execute("SELECT accession FROM ev_docs")}
    q = "SELECT accession, ticker, form, filed, items FROM sec_hist WHERE (form LIKE '8-K%' OR form LIKE '6-K%') AND filed >= ?"
    rows = [dict(r) for r in conn.execute(q, (since,)) if r["accession"] not in done and (not tickers or r["ticker"] in tickers)]
    try:
        live = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM daily_snapshots")}
    except Exception:  # noqa: BLE001
        live = set()
    rows.sort(key=lambda r: (r["ticker"] not in live, r["filed"]), reverse=False)
    rows.sort(key=lambda r: r["filed"], reverse=True)
    rows.sort(key=lambda r: r["ticker"] not in live)  # 지금 스캐너가 보는 종목 먼저, 그 안에서 최신 먼저
    return rows


def collect(client, years: int = 3, limit: int = 0, tickers: list[str] | None = None, out=print) -> int:
    n = 0
    with closing(db.connect()) as conn:
        todo = targets(conn, years, tickers)
        db.set_meta("ev_progress", json.dumps({"left": len(todo), "at": db.utcnow_iso()}))
        for r in todo[: limit or None]:
            ok, acc_t, title, lead, text = 0, None, "", "", ""
            try:
                cik = client.cik_for(r["ticker"])
                idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{r['accession'].replace('-', '')}/{r['accession']}-index.htm"
                ix = parse_index(client._get(idx_url).text)
                acc_t = ix["accepted"]
                doc = ix["ex99"] or ix["main"]
                if doc:
                    text = client.fetch_text(doc, limit=60_000)
                    title, lead = headline(text)
                    ok = 1
            except Exception:  # noqa: BLE001
                ok = 0
            types, sent = classify(r["items"], f"{title} {lead} {text[:6000]}")
            conn.execute("INSERT OR REPLACE INTO ev_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (r["accession"], r["ticker"], r["form"], r["items"], r["filed"], acc_t, title, lead,
                                                                                          json.dumps(types, ensure_ascii=False), sent, db.utcnow_iso(), ok))
            n += 1
            if n % 50 == 0:
                conn.commit()
                db.set_meta("ev_progress", json.dumps({"left": len(todo) - n, "at": db.utcnow_iso()}))
                out(f"  수집 {n:,}/{len(todo):,}")
        conn.commit()
    db.set_meta("ev_progress", json.dumps({"left": max(0, len(todo) - n), "at": db.utcnow_iso()}))
    out(f"이벤트 수집: {n:,}건")
    return n


def day0(accepted: str | None, filed: str, days: pd.DatetimeIndex) -> tuple[pd.Timestamp | None, str]:
    """기준 거래일과 시점(장전·장중·장후·시각 미상)."""
    if accepted:
        dt = datetime.strptime(accepted, "%Y-%m-%d %H:%M:%S")
        d, hm = pd.Timestamp(dt.date()), dt.hour * 100 + dt.minute
        timing = "장후" if hm >= 1600 else ("장전" if hm < 930 else "장중")
        cand = days[days > d] if timing == "장후" else days[days >= d]
    else:
        timing, cand = "시각 미상", days[days > pd.Timestamp(filed)]
    return (cand[0] if len(cand) else None), timing


def label_one(docs: list[dict], df: pd.DataFrame, iwm: pd.DataFrame | None) -> list[tuple]:
    df = df.dropna(subset=["Close"])
    if len(df) < 25:
        return []
    days = df.index.normalize()
    out = []
    for d in docs:
        d0, timing = day0(d["accepted"], d["filed"], days)
        if d0 is None:
            continue
        p = int(days.get_indexer([d0])[0])
        if p < 21 or p + 4 >= len(df):
            continue
        pc = float(df["Close"].iloc[p - 1])
        w = df.iloc[p:p + 5]
        if pc <= 0:
            continue
        gap = (float(df["Open"].iloc[p]) / pc - 1) * 100
        ret0 = (float(df["Close"].iloc[p]) / pc - 1) * 100
        up5 = (float(w["High"].max()) / pc - 1) * 100
        dn5 = (float(w["Low"].min()) / pc - 1) * 100
        ret5 = (float(w["Close"].iloc[-1]) / pc - 1) * 100
        base = float(df["Volume"].iloc[p - 20:p].mean() or 0)
        volx = None if not base else float(df["Volume"].iloc[p]) / base
        abn0 = abn5 = None
        if iwm is not None and not iwm.empty:
            ic = iwm["Close"].dropna()
            ic.index = ic.index.normalize()
            dd = [days[p - 1], days[p], days[p + 4]]
            if all(x in ic.index for x in dd):
                abn0 = ret0 - (ic[dd[1]] / ic[dd[0]] - 1) * 100
                abn5 = ret5 - (ic[dd[2]] / ic[dd[0]] - 1) * 100
        out.append((d["accession"], d["ticker"], d0.strftime("%Y-%m-%d"), timing, pc, gap, ret0, up5, dn5, ret5, volx, abn0, abn5))
    return out


def label(limit_tickers: int = 300, download=None, out=print) -> int:
    import market
    dl = download or (lambda ts: market.download_daily(ts, period="3y"))
    n = 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        pend = [dict(r) for r in conn.execute("""SELECT d.accession, d.ticker, d.accepted, d.filed FROM ev_docs d LEFT JOIN ev_labels l ON l.accession=d.accession
                                                 WHERE l.accession IS NULL AND d.filed <= ?""", ((date.today() - timedelta(days=8)).isoformat(),))]
        by = {}
        for r in pend:
            by.setdefault(r["ticker"], []).append(r)
        tried = {r[0]: (r[1] or "", r[2]) for r in conn.execute("SELECT ticker, tried, status FROM ev_label_try")}
        skip_before = (date.today() - timedelta(days=14)).isoformat()
        # 주가 자료가 없던 종목은 14일 동안 건너뜀 · 나머지는 한 번도 안 해 본 것 → 오래전에 해 본 것 순(같은 종목만 반복하지 않게)
        cand = [t for t in by if not (tried.get(t, ("", ""))[1] == "no_data" and tried[t][0] >= skip_before)]
        cand.sort(key=lambda t: (tried.get(t, ("", ""))[0], -len(by[t])))
        tick = cand[:limit_tickers]
        iwm = (dl(["IWM"]) or {}).get("IWM")
        for i in range(0, len(tick), 40):
            part = tick[i:i + 40]
            data = dl(part) or {}
            try:  # 🗄 yfinance 에 없으면(상장폐지 등) 주가 보관소 일봉으로 — 사라진 회사의 사건도 통계에 들어가게
                import pricevault as _pv
                _pv.fill(data, part, conn)
            except Exception:  # noqa: BLE001
                pass
            now = datetime.now().isoformat(timespec="seconds")
            for t in part:
                if data.get(t) is None or getattr(data.get(t), "empty", False):
                    conn.execute("INSERT OR REPLACE INTO ev_label_try VALUES (?,?,?,?)", (t, now, "no_data", len(by[t])))
                    continue
                try:
                    rows = label_one(by[t], data[t], iwm)
                except Exception as e:  # noqa: BLE001  (2026-10-30: 한 종목의 이상한 일봉이 40개 묶음 전체와 커밋을 날리지 않게 — HANDOFF 할 일 7)
                    out(f"이벤트 라벨 실패 {t}: {e}")
                    conn.execute("INSERT OR REPLACE INTO ev_label_try VALUES (?,?,?,?)", (t, now, "error", len(by[t])))
                    continue
                conn.executemany("INSERT OR REPLACE INTO ev_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                conn.execute("INSERT OR REPLACE INTO ev_label_try VALUES (?,?,?,?)", (t, now, "ok" if rows else "no_rows", len(by[t]) - len(rows)))
                n += len(rows)
            conn.commit()
    out(f"이벤트 라벨: {n:,}건 · 이번에 본 종목 {len(tick):,} · 남은 종목 {max(0, len(cand) - len(tick)):,}")
    return n


def table(min_price: float | None = None, max_price: float | None = None, timing: str | None = None) -> pd.DataFrame:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
    df = db.read_df("SELECT d.ticker, d.form, d.items, d.filed, d.accepted, d.title, d.types, d.sentiment, l.* FROM ev_labels l JOIN ev_docs d ON d.accession=l.accession")
    if df.empty:
        return df
    df = df.loc[:, ~df.columns.duplicated()]
    df["type"] = [json.loads(x)[0] if x else "기타" for x in df["types"]]
    if min_price is not None:
        df = df[df["price"] >= min_price]
    if max_price is not None:
        df = df[df["price"] < max_price]
    if timing:
        df = df[df["timing"] == timing]
    return df


def trimmed(x: pd.Series, q: float = 0.05) -> float:
    """양 끝 5%씩 잘라낸 평균 — 초소형주는 소수의 폭등(+500%)이 평균을 끌어올려 '악재 뒤 +54%' 같은 착시가 생김."""
    x = x.dropna()
    if x.empty:
        return float("nan")
    lo, hi = x.quantile(q), x.quantile(1 - q)
    return float(x[(x >= lo) & (x <= hi)].mean())


def stats(df: pd.DataFrame, by: str = "type", min_n: int = 5) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(by)
    s = pd.DataFrame({"건수": g.size(), "당일 평균(%)": g["ret0"].mean(), "당일 중앙값(%)": g["ret0"].median(), "당일 상승 확률(%)": g["ret0"].apply(lambda x: (x > 0).mean() * 100),
                      "D+5 최고 평균(%)": g["up5"].mean(), "+20% 이상 확률(%)": g["up5"].apply(lambda x: (x >= 20).mean() * 100), "D+5 최저 평균(%)": g["dn5"].mean(),
                      "D+5 초과수익(%)": g["abn5"].mean(), "D+5 초과 중앙값(%)": g["abn5"].median(), "D+5 초과 절사평균(%)": g["abn5"].apply(trimmed),
                      "D+5 초과>0 확률(%)": g["abn5"].apply(lambda x: (x.dropna() > 0).mean() * 100)}).reset_index()
    return s[s["건수"] >= min_n].sort_values("D+5 초과 절사평균(%)", ascending=False)  # 극단값에 덜 흔들리는 기준으로 정렬


def suggest(df: pd.DataFrame) -> list[dict]:
    """공시 호재 비중 제안 — 극단값에 흔들리지 않게 절사평균·중앙값·확률로 판단.
    '호재' 사건이 전체보다 절사평균·중앙값 둘 다 낮고 +20% 확률도 높지 않으면 낮추고, 셋 다 뚜렷이 높으면 올린다."""
    import config
    good = df[df["sentiment"] == "호재"] if not df.empty else df
    if df.empty or len(good) < 30:
        return []
    allt, goodt = trimmed(df["abn5"]), trimmed(good["abn5"])
    allm, goodm = df["abn5"].median(), good["abn5"].median()
    allp, goodp = (df["up5"] >= 20).mean() * 100, (good["up5"] >= 20).mean() * 100
    cur = float(config.RANK_W_NEWS)
    basis = (f"호재 {len(good):,}건 D+5 초과 절사평균 {goodt:+.1f}%·중앙값 {goodm:+.1f}%·+20% 확률 {goodp:.0f}% "
             f"vs 전체 {allt:+.1f}%·{allm:+.1f}%·{allp:.0f}%")
    if goodt < allt and goodm < allm and goodp <= allp + 1:
        return [{"key": "RANK_W_NEWS", "cur": cur, "new": round(max(0.0, cur / 2), 2), "why": basis + " — 평균보다 못함 → 낮춤"}]
    if goodt > allt + 1 and goodm > allm + 0.5 and goodp > allp + 3:
        return [{"key": "RANK_W_NEWS", "cur": cur, "new": round(min(0.4, cur * 1.5), 2), "why": basis + " — 뚜렷이 좋음 → 올림"}]
    return [{"key": "RANK_W_NEWS", "cur": cur, "new": cur, "why": basis + " — 비슷함 → 유지"}]


def main() -> int:
    import config
    import sec
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "label", "run"])
    ap.add_argument("--years", type=float, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tickers", default="")
    a = ap.parse_args()
    db.init_db()
    client = sec.SecClient(config.SEC_USER_AGENT)
    tk = [x.strip().upper() for x in a.tickers.split(",") if x.strip()] or None
    if a.cmd == "collect":
        collect(client, a.years, a.limit, tk)
    elif a.cmd == "label":
        label()
    else:
        while True:  # 하루 종일: 수집(한 번에 2,000건) → 라벨 → 남은 게 없으면 1시간 쉬기
            n = collect(client, a.years, 2000, tk)
            label()
            if n == 0:
                time.sleep(3600)
    return 0


if __name__ == "__main__":
    import quiet  # noqa: F401  (Streamlit 경고 줄 끄기)
    sys.exit(main())
