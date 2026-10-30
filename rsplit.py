"""🔁 병합(역분할) 후 반등 레이더 — 과거 10년 역분할 사건으로 '병합 후 N일째, 이만큼 빠진 종목이 그 뒤 어떻게 됐는지'를 본다.

python rsplit.py build [--years 10]   전체 종목의 분할 기록(yfinance 'Stock Splits') + 병합 후 경로를 한 번에 저장(수 분~수십 분)
python rsplit.py update               최근 1년만 다시 받아 최근 병합 종목(레이더)과 경로 갱신 — 매일 아침 갱신 작업에 포함
경로(rs_paths): 병합 후 k거래일째(1~120) 종가 기준, 병합일 종가 대비 등락(dd), 다음 10거래일 최고·최저·10일 뒤 종가(%), 최고까지 걸린 날.
※ yfinance 가격은 분할이 반영된 값이라 병합 전후 수익률이 일관된다. 상장폐지 종목은 빠져 있어(생존편향) 실제보다 낙관적일 수 있다.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from contextlib import closing
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import db

log = logging.getLogger("rsplit")
MAX_K, H, RADAR_DAYS = 120, 10, 250
DDL = ["CREATE TABLE IF NOT EXISTS rs_events (ticker TEXT NOT NULL, date TEXT NOT NULL, ratio REAL, split_close REAL, PRIMARY KEY (ticker, date))",
       """CREATE TABLE IF NOT EXISTS rs_paths (ticker TEXT NOT NULL, split_date TEXT NOT NULL, k INTEGER NOT NULL, dd REAL, fwd_max REAL, fwd_min REAL,
          fwd_close REAL, days_to_max INTEGER, PRIMARY KEY (ticker, split_date, k))""",
       "CREATE INDEX IF NOT EXISTS idx_rs_paths_k ON rs_paths (k)",
       "CREATE TABLE IF NOT EXISTS rs_current (ticker TEXT PRIMARY KEY, split_date TEXT, ratio REAL, k INTEGER, price REAL, dd REAL, at TEXT)",
       "CREATE TABLE IF NOT EXISTS rs_signals (date TEXT NOT NULL, ticker TEXT NOT NULL, price REAL, success_pct REAL, n INTEGER, exp_high REAL, at TEXT, PRIMARY KEY (date, ticker))"]


# ---------------------------------------------------------------- 📅 병합 예정 (C단계 2026-10-27) — 8-K/6-K 본문에서 시행일·비율을 규칙으로 뽑아 🗓 일정 '역분할 시행'에 기록
# (예전엔 Haiku 공시 요약(secdigest)이 하루 12건만 읽어 거의 안 잡혔음. 이제 스캐너가 본문을 읽는 모든 8-K/6-K 에서 바로 뽑는다 · 비용 0)
_RS_MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
_RS_DATE = rf"({_RS_MONTHS}\s+\d{{1,2}},\s+\d{{4}})"
RS_KEY = r"(?:reverse\s+(?:stock\s+|share\s+)?split|share\s+consolidation|consolidation\s+of\s+(?:its|the|our)\s+(?:ordinary|common)\s+shares)"
_TRADE_DATE = (r"(?:split-adjusted|post-consolidation|post-split|consolidated|adjusted)\s+basis[^.]{0,140}?(?:on|beginning|as\s+of|commencing|from)\s+"
               r"(?:(?:when\s+)?the\s+(?:market\s+)?open(?:s|ing)?\s+(?:of\s+trading\s+)?on\s+)?(?:\w+day,\s+)?" + _RS_DATE)
_ON = r"(?:on\s+or\s+about|on\s+or\s+around|on|as\s+of|at|from)\s+"
RS_DATE_PATS = [   # 순서 = 우선순위: ① 분할 반영 거래 시작일(투자자가 보는 날) ② 효력일 ③ 효력일이 앞에 나오는 문장 ④ '효력 예정'만 있는 문장(문서에 병합 문구가 있을 때)
    re.compile(_TRADE_DATE, re.I),
    re.compile(RS_KEY + r"[^.]{0,250}?(?:effective|effectiveness|take\s+effect)[^.]{0,60}?" + _ON + r"(?:\d{1,2}:\d{2}\s*[ap]\.?m\.?[^,]{0,25},?\s+(?:on\s+)?)?(?:\w+day,\s+)?" + _RS_DATE, re.I),
    re.compile(r"(?:effective|effectiveness)[^.]{0,60}?" + _ON + r"(?:\w+day,\s+)?" + _RS_DATE + r"[^.]{0,200}?" + RS_KEY, re.I),
    re.compile(r"(?:expected\s+to\s+(?:be|become)\s+effective|will\s+(?:be|become)\s+effective|effective\s+(?:date|time)[^.]{0,40}?(?:is|will\s+be|of))\s*" + _ON + r"(?:\w+day,\s+)?" + _RS_DATE, re.I),
]
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
          "seventy": 70, "seventy-five": 75, "eighty": 80, "ninety": 90, "hundred": 100, "one hundred": 100, "two hundred": 200}
_NUM = r"(\d{1,4}|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_PNUM = r"(?:\w+\s*)?\((\d{1,4})\)"   # 'ten (10)' 처럼 괄호 숫자
RS_RATIO_PATS = [   # 순서 = 우선순위(승인받은 '범위' 1-for-5 ~ 1-for-50 보다 확정 비율 문구가 먼저)
    re.compile(r"ratio\s+of\s+" + _PNUM + r"\s*[- ]?for[- ]\s*(?:one|1)\b", re.I),                    # ratio of ten (10)-for-one (1)
    re.compile(r"ratio\s+of\s+(?:one|1)\s*(?:\(1\)\s*)?[- ]?for[- ]\s*" + _PNUM, re.I),           # ratio of one (1)-for-ten (10)
    re.compile(r"every\s+" + _PNUM + r"\s+(?:issued\s+and\s+outstanding\s+)?(?:class\s+[ab]\s+)?(?:ordinary|common|outstanding)?\s*shares", re.I),   # every ten (10) class a ordinary shares
    re.compile(r"ratio\s+of\s+(?:one|1)\s*(?:\(1\)\s*)?[- ]?for[- ]\s*" + _NUM + r"\b(?!\s*(?:to|through|and up to|up to)\b)", re.I),
    re.compile(r"\b(?:one|1)[- ]for[- ]" + _NUM + r"\s+(?:reverse|share\s+consolidation)", re.I),
    re.compile(r"every\s+" + _NUM + r"\s+(?:\(\d+\)\s+)?(?:issued\s+and\s+outstanding\s+)?(?:ordinary|common|outstanding)?\s*shares[^.]{0,80}?(?:combined|converted|consolidated|reclassified)\s+(?:and\s+\w+\s+)?into\s+(?:one|1)\b", re.I),
    re.compile(r"\b" + _NUM + r"[- ]for[- ](?:one|1)\s+(?:reverse|share\s+consolidation|consolidation)", re.I),
    re.compile(r"\b(?:one|1)[- ]for[- ]" + _NUM + r"\b(?!\s*(?:to|through|and up to|up to)\b)", re.I),
    re.compile(r"\b1:(\d{1,4})\b", re.I),
]


def _ratio_num(s: str):
    s = s.lower().strip()
    if s.isdigit():
        return int(s)
    return _WORDS.get(s)


def _rs_date(s: str):
    s = s.replace("Sept.", "Sep").replace("Sept", "Sep").replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def upcoming_from_text(text: str) -> dict | None:
    """공시 본문 → {"date": 시행일, "ratio": N(1:N)} 또는 None. 역분할 문구 + 시행일(효력일·split-adjusted 거래 시작일)이 있을 때만."""
    t = re.sub(r"\s+", " ", text or "")
    if not re.search(RS_KEY, t, re.I):
        return None
    floor = date.today() - timedelta(days=7)
    d = None
    for p in RS_DATE_PATS:            # 우선순위 순서대로, 지난 날짜('이미 시행한' 병합)는 건너뜀
        for m in p.finditer(t):
            x = _rs_date(m.group(1))
            if x and x >= floor:
                d = x
                break
        if d:
            break
    if not d:
        return None
    ratio = None
    for p in RS_RATIO_PATS:
        for m in p.finditer(t):
            ctx = t[max(0, m.start() - 160):m.start()].lower()
            if "previously effected" in ctx or "previously implemented" in ctx or re.search(r"effected\s+(?:a|an|the)\s*$", ctx):
                continue   # 예전에 이미 한 병합 비율
            n = _ratio_num(m.group(1))
            if n and 2 <= n <= 5000:
                ratio = n
                break
        if ratio:
            break
    return {"date": d.isoformat(), "ratio": ratio}


def filing_text(client, index_url: str, min_main: int = 4000) -> str:
    """공시 목록 페이지 → 주 문서 본문. 주 문서가 짧으면(6-K 표지 등) EX-99 첨부(보도자료)도 이어 붙인다."""
    idx = client._get(index_url).text
    links = [m.group(1) for m in re.finditer(r'href="(?:/ix\?doc=)?(/Archives/edgar/data/[^"]+?\.(?:htm|html|txt))"', idx, re.I) if "-index" not in m.group(1)]
    if not links:
        return ""
    text = client.fetch_text("https://www.sec.gov" + links[0], limit=200_000) or ""
    if len(text) < min_main:
        for ln in [x for x in links[1:4] if re.search(r"ex[-_]?99|ex99|press", x, re.I)][:2]:
            try:
                text += " " + (client.fetch_text("https://www.sec.gov" + ln, limit=200_000) or "")
            except Exception:  # noqa: BLE001
                continue
    return text


def record_upcoming(conn, ticker: str, info: dict, source: str, origin: str = "secfeed") -> bool:
    """🗓 일정에 '역분할 시행' 기록(같은 종목·같은 날은 한 번). 지난 날(7일 넘음)은 기록 안 함."""
    if not info or not info.get("date") or info["date"] < (date.today() - timedelta(days=7)).isoformat():
        return False
    try:
        title = f"역분할 1:{info['ratio']} 시행" if info.get("ratio") else "역분할 시행(비율 미확인)"
        t = ticker.upper()
        same = conn.execute("SELECT id, title FROM events WHERE ticker=? AND kind='역분할 시행' AND date=?", (t, info["date"])).fetchone()
        if same:
            if info.get("ratio") and same[1] != title:   # 비율이 틀리게 적혀 있던 것은 고쳐 씀
                conn.execute("UPDATE events SET title=?, source=? WHERE id=?", (title, source, same[0]))
                return True
            return False
        # 자동 기록(secfeed)으로 같은 종목에 ±10일 안 다른 날짜가 있으면 새 추출(거래 시작일 우선)로 바꿔 끼움
        conn.execute("DELETE FROM events WHERE ticker=? AND kind='역분할 시행' AND origin=? AND date BETWEEN date(?, '-10 day') AND date(?, '+10 day')",
                     (t, origin, info["date"], info["date"]))
        conn.execute("INSERT OR IGNORE INTO events (ticker, date, kind, title, source, origin, created_at) VALUES (?,?,?,?,?,?,?)",
                     (t, info["date"], "역분할 시행", title, source, origin, db.utcnow_iso()))
        return True
    except Exception:  # noqa: BLE001 (events 표 없음)
        return False


def backfill_upcoming(client, days: int = 30, limit: int = 400, out=print) -> dict:
    """1회 소급: 최근 days 일 공시 피드의 8-K/6-K 중 '주식 병합' 태그·5.03 항목이 있는 것의 본문을 다시 읽어 시행일을 기록(스캐너는 새 공시부터 자동)."""
    import json as _json
    import re as _re
    since = (date.today() - timedelta(days=days)).isoformat()
    n_read = n_new = 0
    with closing(db.connect()) as conn:
        rows = [dict(r) for r in conn.execute("""SELECT accession, ticker, form, filed, items, url, tags FROM sec_feed
                                                 WHERE COALESCE(filed, substr(updated,1,10)) >= ? AND (form LIKE '8-K%' OR form LIKE '6-K%' OR form LIKE '424B%' OR form LIKE 'DEF 14%' OR form LIKE 'PRE 14%')
                                                 ORDER BY filed DESC""", (since,))]
        rows = [r for r in rows if r["form"].upper().startswith("6-K") or "5.03" in (r["items"] or "") or "8.01" in (r["items"] or "") or "주식 병합" in (r["tags"] or "")][:limit]   # 6-K 는 항목·태그가 없어 전부 · 424B/주총 서류는 '주식 병합' 태그 있는 것만
        for r in rows:
            try:
                text = filing_text(client, r["url"])
            except Exception:  # noqa: BLE001
                continue
            if not text:
                continue
            n_read += 1
            info = upcoming_from_text(text)
            if info and record_upcoming(conn, r["ticker"], info, f"{r['form']} {r['filed'] or ''} {r['url']}".strip()):
                n_new += 1
        conn.commit()
    out(f"병합 예정 소급: 공시 {n_read}건 읽음 · 새 시행일 {n_new}건")
    return {"read": n_read, "new": n_new}


def upcoming(conn) -> pd.DataFrame:
    """병합 예정 표: 티커 · 시행일 · D-day · 비율 · 현재가 · 병합 환산가(현재가×비율, 예측 아님) · 병합 후 주식 수 · 근거."""
    try:
        rows = [dict(r) for r in conn.execute("SELECT ticker, date, title, source FROM events WHERE kind='역분할 시행' AND date >= ? ORDER BY date", (date.today().isoformat(),))]
    except Exception:  # noqa: BLE001
        rows = []
    out = []
    for r in rows:
        m = re.search(r"1:(\d+)", r["title"] or "")
        ratio = int(m.group(1)) if m else None
        px = sh = None
        for sql in ("SELECT price FROM daily_move WHERE ticker=? ORDER BY date DESC LIMIT 1", "SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 1"):
            try:
                p = conn.execute(sql, (r["ticker"],)).fetchone()
                if p and p[0]:
                    px = float(p[0])
                    break
            except Exception:  # noqa: BLE001 (표 없음)
                continue
        try:
            f = conn.execute("SELECT shares_out FROM fundamentals WHERE ticker=?", (r["ticker"],)).fetchone()
            sh = float(f[0]) if f and f[0] else None
        except Exception:  # noqa: BLE001
            pass
        dd = (date.fromisoformat(r["date"]) - date.today()).days
        out.append({"티커": r["ticker"], "시행일": r["date"], "D-day": "오늘" if dd == 0 else f"D-{dd}", "비율": None if not ratio else f"1:{ratio}",
                    "현재가($)": px, "병합 환산가($)": None if not (px and ratio) else px * ratio, "병합 후 주식 수(만주)": None if not (sh and ratio) else sh / ratio / 1e4,
                    "근거": r["source"] or ""})
    return pd.DataFrame(out)


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def split_base(c: np.ndarray, s: int, ratio: float) -> float:
    """병합일 기준 종가. yfinance 가 병합 당일 값만 조정하지 않고 남기는 경우가 있어(병합 전 단위 = 1/ratio 배 큼),
    병합일 종가가 바로 뒤 3거래일 중앙값의 (1/ratio)의 절반 이상 크면 병합 전 단위로 보고 × ratio 로 맞춘다."""
    nxt = c[s + 1:s + 4]
    nxt = nxt[nxt > 0]
    if len(nxt) == 0 or not (0 < ratio < 1):
        return float(c[s])
    jump = c[s] / float(np.median(nxt))
    return float(c[s] * ratio) if jump >= 0.5 / ratio else float(c[s])


def analyze_frame(df: pd.DataFrame | None, max_k: int = MAX_K, h: int = H) -> tuple[list[dict], list[dict], dict | None]:
    """(역분할 사건, 경로 행, 최근 병합 정보). 'Stock Splits' 가 0~1 사이면 역분할(예: 0.1 = 10주→1주)."""
    if df is None or df.empty or "Stock Splits" not in df:
        return [], [], None
    d = df.dropna(subset=["High", "Low", "Close"])
    sp = d["Stock Splits"].fillna(0).to_numpy(float)
    c, hi, lo = (d[k].to_numpy(float) for k in ("Close", "High", "Low"))
    events, paths, current = [], [], None
    for s in np.where((sp > 0) & (sp < 1))[0]:
        if c[s] <= 0:
            continue
        base = split_base(c, s, float(sp[s]))  # 병합일 종가가 병합 전 단위로 남아 있으면 맞춤(예전엔 −98%·−99% 같은 착시)
        sd = d.index[s].strftime("%Y-%m-%d")
        events.append({"date": sd, "ratio": float(sp[s]), "split_close": float(base)})
        for k in range(1, max_k + 1):
            i = s + k
            if i + h >= len(c):
                break
            w_hi, w_lo = hi[i + 1:i + 1 + h], lo[i + 1:i + 1 + h]
            paths.append({"split_date": sd, "k": k, "dd": (c[i] / base - 1) * 100, "fwd_max": (w_hi.max() / c[i] - 1) * 100,
                          "fwd_min": (w_lo.min() / c[i] - 1) * 100, "fwd_close": (c[i + h] / c[i] - 1) * 100, "days_to_max": int(w_hi.argmax()) + 1})
        k_now = len(c) - 1 - s
        if 0 < k_now <= RADAR_DAYS:
            current = {"split_date": sd, "ratio": float(sp[s]), "k": int(k_now), "price": float(c[-1]), "dd": (c[-1] / base - 1) * 100}
    return events, paths, current


def _store(conn, t: str, ev: list[dict], paths: list[dict], cur: dict | None) -> None:
    conn.executemany("INSERT OR REPLACE INTO rs_events (ticker, date, ratio, split_close) VALUES (?,?,?,?)", [(t, e["date"], e["ratio"], e["split_close"]) for e in ev])
    conn.executemany("INSERT OR REPLACE INTO rs_paths (ticker, split_date, k, dd, fwd_max, fwd_min, fwd_close, days_to_max) VALUES (?,?,?,?,?,?,?,?)",
                     [(t, p["split_date"], p["k"], p["dd"], p["fwd_max"], p["fwd_min"], p["fwd_close"], p["days_to_max"]) for p in paths])
    if cur:
        conn.execute("INSERT OR REPLACE INTO rs_current (ticker, split_date, ratio, k, price, dd, at) VALUES (?,?,?,?,?,?,?)",
                     (t, cur["split_date"], cur["ratio"], cur["k"], cur["price"], cur["dd"], db.utcnow_iso()))
    else:
        conn.execute("DELETE FROM rs_current WHERE ticker=?", (t,))


def run(tickers: list[str], period: str, chunk: int = 100, out=print, progress=None) -> dict:
    import market
    n_ev = n_cur = 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        for i in range(0, len(tickers), chunk):
            part = tickers[i:i + chunk]
            data = market._download(part, chunk_size=chunk, period=period, interval="1d", actions=True)
            for t in part:
                ev, paths, cur = analyze_frame(data.get(t))
                _store(conn, t, ev, paths, cur)
                n_ev += len(ev)
                n_cur += bool(cur)
            conn.commit()
            msg = f"분할 기록 {min(i + chunk, len(tickers)):,}/{len(tickers):,} · 역분할 {n_ev:,}건 · 최근 병합 {n_cur}종목"
            out(msg)
            if progress:
                progress(min(1.0, (i + chunk) / max(len(tickers), 1)), msg)
    return {"events": n_ev, "current": n_cur}


def universe() -> list[str]:
    try:
        return sorted(db.read_df("SELECT ticker FROM case_progress WHERE status='done'")["ticker"])
    except Exception:  # noqa: BLE001
        return []


def similar(paths: pd.DataFrame, k0: int, dd0: float, band_k: int = 10, band_dd: float = 10.0, exclude: tuple | None = None) -> pd.DataFrame:
    m = paths["k"].between(k0 - band_k, k0 + band_k) & paths["dd"].between(dd0 - band_dd, dd0 + band_dd)
    if exclude:
        m &= ~((paths["ticker"] == exclude[0]) & (paths["split_date"] == exclude[1]))
    return paths[m]


def expect(rows: pd.DataFrame, price: float, target: float = 20.0) -> dict:
    """유사 사례로: 성공률(10일 내 최고 ≥ +target%), 예상 반등 출발가(가격 × (1+최저 중앙값)), 예상 장중 고가(× (1+최고 중앙값)), 반등 소요(중앙값 일)."""
    if rows.empty:
        return {"n": 0}
    q = rows["fwd_max"].quantile([0.25, 0.5, 0.75])
    lo = float(rows["fwd_min"].median())
    return {"n": int(len(rows)), "events": int(rows[["ticker", "split_date"]].drop_duplicates().shape[0]),
            "success": float((rows["fwd_max"] >= target).mean() * 100), "max_q25": float(q.loc[0.25]), "max_med": float(q.loc[0.5]), "max_q75": float(q.loc[0.75]),
            "min_med": lo, "close_med": float(rows["fwd_close"].median()), "days_med": float(rows["days_to_max"].median()),
            "start_price": price * (1 + lo / 100), "exp_high": price * (1 + float(q.loc[0.5]) / 100), "exp_high_q75": price * (1 + float(q.loc[0.75]) / 100)}


def _expect_arr(fmax: np.ndarray, fmin: np.ndarray, fcl: np.ndarray, dmax: np.ndarray, codes: np.ndarray, price: float, target: float) -> dict:
    """expect() 와 같은 결과를 넘파이 배열로(판다스 quantile·median 처럼 빈 값은 빼고, 성공률은 전체 행 기준)."""
    n = len(fmax)
    if n == 0:
        return {"n": 0}
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        q25, q50, q75 = (float(x) for x in np.nanpercentile(fmax, [25, 50, 75]))
        lo = float(np.nanmedian(fmin))
        close_med = float(np.nanmedian(fcl))
        days_med = float(np.nanmedian(dmax))
    succ = float(np.mean(np.nan_to_num(fmax, nan=-np.inf) >= target) * 100)
    return {"n": int(n), "events": int(np.unique(codes).size), "success": succ, "max_q25": q25, "max_med": q50, "max_q75": q75,
            "min_med": lo, "close_med": close_med, "days_med": days_med,
            "start_price": price * (1 + lo / 100), "exp_high": price * (1 + q50 / 100), "exp_high_q75": price * (1 + q75 / 100)}


def radar(conn, target: float = 20.0, band_k: int = 10, band_dd: float = 10.0) -> pd.DataFrame:
    """최근 병합 종목마다 유사 과거 사례 기대치.
    2026-10-30: 예전엔 최근 병합 419종목마다 경로 20만 줄 전체를 판다스로 다시 훑어(문자열 비교 포함) 화면이 볼 때마다 9초 →
    경로를 '병합 후 거래일(k)' 순으로 정렬해 두고 종목마다 k 구간만 잘라 넘파이로 계산(결과는 similar()+expect() 와 같음 — tests/test_speed_fixes.py)."""
    ensure_tables(conn)
    cur = db.read_df("SELECT * FROM rs_current")
    if cur.empty:
        return cur
    P = db.read_df("SELECT ticker, split_date, k, dd, fwd_max, fwd_min, fwd_close, days_to_max FROM rs_paths")
    if P.empty:
        return pd.DataFrame([{**r, "n": 0} for r in cur.to_dict("records")])
    P = P.sort_values("k", kind="stable").reset_index(drop=True)
    kk = P["k"].to_numpy(dtype=float)
    dd = P["dd"].to_numpy(dtype=float)
    codes, uniq = pd.factorize(P["ticker"].astype(str) + "\x00" + P["split_date"].astype(str))
    pos = {u: i for i, u in enumerate(uniq)}
    cols = [P[c].to_numpy(dtype=float) for c in ("fwd_max", "fwd_min", "fwd_close", "days_to_max")]
    rows = []
    for r in cur.to_dict("records"):
        k0, d0 = int(r["k"]), float(r["dd"])
        a, b = np.searchsorted(kk, k0 - band_k, "left"), np.searchsorted(kk, k0 + band_k, "right")
        m = (dd[a:b] >= d0 - band_dd) & (dd[a:b] <= d0 + band_dd)
        ex = pos.get(f"{r['ticker']}\x00{r['split_date']}")
        if ex is not None:
            m &= codes[a:b] != ex
        e = _expect_arr(*(c[a:b][m] for c in cols), codes[a:b][m], float(r["price"]), target)
        rows.append({**r, **e})
    return pd.DataFrame(rows)


def record_daily(conn, day: str, target: float = 20.0, min_success: float = 50.0, min_n: int = 20) -> int:
    """성과 공표용: 유사 사례가 충분하고 성공률이 높은 최근 병합 종목을 그날의 예측으로 기록."""
    rd = radar(conn, target)
    n = 0
    for r in rd.to_dict("records") if not rd.empty else []:
        if (r.get("n") or 0) >= min_n and (r.get("success") or 0) >= min_success:
            n += record_signal(conn, day, r["ticker"], r["price"], r)
    return n


def record_signal(conn, day: str, ticker: str, price: float, e: dict) -> bool:
    ensure_tables(conn)
    cur = conn.execute("INSERT OR IGNORE INTO rs_signals (date, ticker, price, success_pct, n, exp_high, at) VALUES (?,?,?,?,?,?,?)",
                       (day, ticker, price, e.get("success"), e.get("n"), e.get("exp_high"), db.utcnow_iso()))
    conn.commit()
    return cur.rowcount > 0


def main() -> int:
    ap = argparse.ArgumentParser(description="병합(역분할) 후 반등 레이더 데이터")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--years", type=int, default=10)
    sub.add_parser("update")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.init_db()
    uni = universe()
    if not uni:
        print("종목 목록이 없습니다. 먼저 python cases.py build --years 10 을 실행하세요.")
        return 2
    r = run(uni, f"{a.years}y" if a.cmd == "build" else "1y")
    print(f"끝: 역분할 {r['events']:,}건 · 최근 병합 종목 {r['current']}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
