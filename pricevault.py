"""🗄 주가 보관소 — 우리가 신호를 낸 종목의 일봉을 우리 DB에 보관한다(작은 버전).

왜: yfinance·토스 모두 상장폐지 종목의 과거 주가를 주지 않는다. 고른 종목이 사라지면 🏆 성과 공표·🧪 가상매매 결과가
     영원히 '대기'로 남거나 빠져서 성적이 실제보다 좋아 보인다(생존 편향). 사라지기 전 주가를 남겨 두고, 끊기면 마지막 가격으로 확정한다.
대상: 성과 공표에서 결과를 기다리는 신호(PICK 포함) + 가상매매 보유·최근 거래 종목. 평가 기간이 끝나면 대상에서 빠진다.
매일 아침(가상매매·성과 공표 바로 앞): 대상 종목 최근 3개월 일봉을 받아 저장(꺼져 있던 날의 빈칸도 채움).
병합: yfinance 는 병합 뒤 과거 가격을 다시 조정한다 → 겹치는 날짜의 가격 비율로 예전 보관분을 같은 단위로 맞춘다.
끊김: 연속 3번 못 받거나 10거래일 넘게 새 봉이 없으면 '끊김(상장폐지·거래정지 추정)'. 다시 거래되면 해제.
     다운로드가 대부분 실패한 날(인터넷 문제)은 끊김 판정을 하지 않는다.
"""
from __future__ import annotations

import json
import math
from contextlib import closing
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import db

DDL = [
    """CREATE TABLE IF NOT EXISTS px_vault (ticker TEXT NOT NULL, date TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL, saved_at TEXT,
       PRIMARY KEY (ticker, date))""",
    "CREATE TABLE IF NOT EXISTS px_watch (ticker TEXT PRIMARY KEY, reasons TEXT, first_added TEXT, keep_until TEXT, misses INTEGER DEFAULT 0, last_ok TEXT)",
    "CREATE TABLE IF NOT EXISTS px_gone (ticker TEXT PRIMARY KEY, last_date TEXT, last_close REAL, detected TEXT, reason TEXT)",
    "CREATE TABLE IF NOT EXISTS px_adjust (ticker TEXT NOT NULL, at TEXT NOT NULL, factor REAL, rows INTEGER, PRIMARY KEY (ticker, at))",
]
MISS_LIMIT = 3          # 연속 이만큼 못 받으면 끊김
STALE_BDAYS = 10        # 마지막 봉이 이 거래일 수보다 오래 멈추면 끊김(거래정지)
SPLIT_TOL = 0.02        # 겹치는 날 가격 비율이 1에서 이만큼 넘게 벗어나면 단위가 바뀐 것(병합·분할)
MIN_OVERLAP = 3         # 단위 변화 판단에 필요한 겹치는 날 수
OUTAGE_SHARE = 0.5      # 받은 종목이 요청의 이 비율보다 적으면 인터넷 문제로 보고 끊김 판정 안 함
MAX_TICKERS = 1500      # 하루 최대 대상(넘으면 우선순위 순으로 자름)
GONE_GRACE_DAYS = 7     # 끊김을 알아챈 뒤 이만큼 지나도 그대로일 때만 결과 확정(거래정지가 풀릴 수 있음)
KEEP_EXTRA_DAYS = 30    # 평가 기간 뒤 여유
COLS = ["Open", "High", "Low", "Close", "Volume"]


def ensure(conn) -> None:
    for d in DDL:
        conn.execute(d)


# ------------------------------------------------------------------ 대상 고르기
def targets(conn, today: date | None = None) -> dict[str, dict]:
    """{티커: {"reasons": set, "keep_until": 'YYYY-MM-DD', "prio": int}} — prio 작을수록 먼저(가상매매 보유 0 · 대기 신호 1 · 최근 끝난 신호 2)."""
    today = today or date.today()
    out: dict[str, dict] = {}

    def add(t, reason, keep, prio):
        if not t:
            return
        x = out.setdefault(t.upper(), {"reasons": set(), "keep_until": keep, "prio": prio})
        x["reasons"].add(reason)
        x["keep_until"] = max(x["keep_until"], keep)
        x["prio"] = min(x["prio"], prio)

    try:  # 🧪 가상매매: 보유 중 + 최근 30일 거래
        for t, st, d in conn.execute("SELECT ticker, status, day FROM pt_trades WHERE status='open' OR day >= ?", ((today - timedelta(days=30)).isoformat(),)):
            add(t, "🧪 가상매매", (today + timedelta(days=KEEP_EXTRA_DAYS)).isoformat(), 0 if st == "open" else 2)
    except Exception:  # noqa: BLE001
        pass
    try:  # 🏆 성과 공표 신호(PICK 포함): 신호일 + 평가 기간(거래일 → 달력일 ×1.5) + 여유 까지
        import scoreboard as sb
        p = sb.collect(conn)
        if not p.empty:
            p = p[p["date"] >= (today - timedelta(days=200)).isoformat()]
            for r in p.itertuples(index=False):
                if r.source == "after":  # 애프터 진입 구간은 분봉으로 판정(일봉 불필요)
                    continue
                keep = (date.fromisoformat(r.date) + timedelta(days=int(math.ceil(r.horizon * 1.5)) + KEEP_EXTRA_DAYS)).isoformat()
                if keep >= today.isoformat():
                    add(r.ticker, sb.SOURCES.get(r.source, (r.source,))[0], keep, 1)
    except Exception:  # noqa: BLE001
        pass
    return out


def refresh_watch(conn, tg: dict, today: date | None = None) -> list[str]:
    """보관 대상 표 갱신 → 오늘 받을 종목(우선순위 순, 최대 MAX_TICKERS)."""
    today = today or date.today()
    ensure(conn)
    old = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT ticker, reasons, first_added, keep_until FROM px_watch")}
    for t, x in tg.items():
        prev = old.get(t)
        reasons = set(json.loads(prev[0])) if prev and prev[0] else set()
        keep = max(x["keep_until"], prev[2] or "") if prev else x["keep_until"]
        conn.execute("""INSERT INTO px_watch (ticker, reasons, first_added, keep_until, misses, last_ok) VALUES (?,?,?,?,0,NULL)
                        ON CONFLICT(ticker) DO UPDATE SET reasons=excluded.reasons, keep_until=excluded.keep_until""",
                     (t, json.dumps(sorted(reasons | x["reasons"]), ensure_ascii=False), prev[1] if prev else today.isoformat(), keep))
    live = [r[0] for r in conn.execute("SELECT ticker FROM px_watch WHERE keep_until >= ?", (today.isoformat(),))]
    live.sort(key=lambda t: (tg.get(t, {}).get("prio", 3), t))
    return live[:MAX_TICKERS]


# ------------------------------------------------------------------ 저장(병합 단위 맞추기)
def _clean(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize() if getattr(d.index, "tz", None) is not None else pd.to_datetime(d.index).normalize()
    d = d[[c for c in COLS if c in d.columns]].dropna(subset=["Close"])
    d = d[d["Close"] > 0]
    return d[~d.index.duplicated(keep="last")].sort_index()


def save_bars(conn, t: str, df: pd.DataFrame) -> dict:
    """새 일봉 저장. 겹치는 날짜로 단위가 바뀌었는지(병합·분할) 보고, 바뀌었으면 예전 보관분을 새 단위로 맞춘 뒤 덮어쓴다."""
    ensure(conn)
    new = _clean(df)
    if new.empty:
        return {"saved": 0, "factor": 1.0}
    t = t.upper()
    first = new.index[0].strftime("%Y-%m-%d")
    old = dict(conn.execute("SELECT date, close FROM px_vault WHERE ticker=? AND date >= ?", (t, first)).fetchall())
    ratios = [float(new.loc[pd.Timestamp(d), "Close"]) / c for d, c in old.items() if c and pd.Timestamp(d) in new.index]
    factor = 1.0
    if len(ratios) >= MIN_OVERLAP:
        med = float(np.median(ratios))
        spread = float(np.median([abs(r / med - 1) for r in ratios]))
        if abs(med - 1) > SPLIT_TOL and spread < 0.01:  # 겹치는 날들이 한결같이 같은 비율 → 단위 변화(우연한 오류는 제외)
            factor = med
            n = conn.execute("""UPDATE px_vault SET open=open*?, high=high*?, low=low*?, close=close*?, volume=volume/? WHERE ticker=? AND date < ?""",
                             (factor, factor, factor, factor, factor, t, first)).rowcount
            conn.execute("INSERT OR REPLACE INTO px_adjust VALUES (?,?,?,?)", (t, datetime.now().isoformat(timespec="seconds"), factor, n))
    now = db.utcnow_iso()
    rows = [(t, i.strftime("%Y-%m-%d"), *[None if pd.isna(r.get(c)) else float(r.get(c)) for c in COLS], now) for i, r in new.iterrows()]
    conn.executemany("INSERT OR REPLACE INTO px_vault VALUES (?,?,?,?,?,?,?,?)", rows)
    return {"saved": len(rows), "factor": factor}


# ------------------------------------------------------------------ 꺼내 쓰기
def bars(t: str, conn=None) -> pd.DataFrame | None:
    """보관된 일봉(yfinance 와 같은 모양: Open·High·Low·Close·Volume, 날짜 인덱스). 없으면 None."""
    def _read(c):
        try:
            return c.execute("SELECT date, open, high, low, close, volume FROM px_vault WHERE ticker=? ORDER BY date", (t.upper(),)).fetchall()
        except Exception:  # noqa: BLE001
            return []
    rows = _read(conn) if conn is not None else None
    if rows is None:
        with closing(db.connect()) as c:
            rows = _read(c)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date"] + COLS)
    df.index = pd.to_datetime(df.pop("date"))
    return df


def fill(data: dict, tickers: list[str], conn=None) -> list[str]:
    """다운로드에서 빠진 종목을 보관소 일봉으로 채움. 채운 티커 목록."""
    filled = []
    for t in tickers:
        d = data.get(t)
        if d is None or getattr(d, "empty", True):
            b = bars(t, conn)
            if b is not None and len(b):
                data[t] = b
                filled.append(t)
    return filled


def gone(conn=None) -> dict[str, dict]:
    """끊긴 종목 {티커: {last_date, last_close, detected, reason}}."""
    def _read(c):
        try:
            ensure(c)
            return {r[0]: {"last_date": r[1], "last_close": r[2], "detected": r[3], "reason": r[4]} for r in c.execute("SELECT * FROM px_gone")}
        except Exception:  # noqa: BLE001
            return {}
    if conn is not None:
        return _read(conn)
    with closing(db.connect()) as c:
        return _read(c)


# ------------------------------------------------------------------ 진입가 병합 보정
_SPLITS: dict[str, tuple[float, list[dict]]] = {}   # 종목별 병합 기록(1시간 보관) — 성과 공표가 신호 수천 건마다 리포트를 다시 읽지 않게
_SPLITS_TTL = 3600.0


def _splits(t: str, conn) -> list[dict]:
    import time
    hit = _SPLITS.get(t)
    if hit and time.time() - hit[0] < _SPLITS_TTL:
        return hit[1]
    try:
        import shares
        sp = shares.splits_after(t, "0000-00-00", conn)
    except Exception:  # noqa: BLE001
        sp = []
    _SPLITS[t] = (time.time(), sp)
    return sp


def split_factor(t: str, day: str, conn) -> float:
    """신호일 뒤 병합·분할 기록으로 본 가격 조정 배수(1:10 병합 → 10). 기록 없으면 1."""
    f = 1.0
    for s in _splits(t, conn):
        if s.get("ratio") and day < s["date"] <= date.today().isoformat():
            f /= float(s["ratio"])
    return f


def fix_entry(t: str, day: str, entry: float | None, df: pd.DataFrame | None, conn=None) -> tuple[float | None, str]:
    """기록된 진입가(신호 때 실제 가격)를 지금 일봉과 같은 단위로. (보정된 진입가, 설명)
    yfinance 는 병합 뒤 과거 가격을 다시 조정하므로, 그대로 비교하면 1:10 병합 종목이 +900% '성공'으로 잡힌다."""
    if entry is None or (isinstance(entry, float) and math.isnan(entry)) or entry <= 0 or df is None or df.empty:
        return entry, ""
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize() if getattr(d.index, "tz", None) is not None else pd.to_datetime(d.index).normalize()
    on = d[(d.index <= pd.Timestamp(day)) & (d.index >= pd.Timestamp(day) - pd.Timedelta(days=5))].dropna(subset=["Close"])
    ref = float(on["Close"].iloc[-1]) if len(on) else None
    f = split_factor(t, day, conn) if conn is not None else 1.0
    if ref is None:  # 신호일 근처 봉이 없으면 기록만 믿음
        return (entry * f, f"병합 기록으로 진입가 ×{f:g}") if abs(f - 1) > 1e-9 else (entry, "")
    gap = lambda e: abs(math.log(ref / e))  # noqa: E731  신호일 종가와 얼마나 먼가(로그)
    if abs(f - 1) > 1e-9 and gap(entry * f) < gap(entry):  # 기록이 있고, 맞추면 신호일 종가와 더 가까워짐(아직 조정 안 된 데이터면 그대로)
        return entry * f, f"병합 기록으로 진입가 ×{f:g}"
    r = ref / entry
    if r >= 3 or r <= 1 / 3:  # 기록은 없지만 신호일 종가와 3배 넘게 차이 → 단위가 바뀐 것으로 보고 신호일 종가 기준
        return ref, f"신호일 종가와 {r:.1f}배 차이 → 병합 추정, 신호일 종가로 진입가 맞춤"
    return entry, ""


# ------------------------------------------------------------------ 매일 아침
def _bdays_since(last: str, today: date) -> int:
    return int(np.busday_count(date.fromisoformat(last), today))


def daily(download=None, today: date | None = None, out=print) -> dict:
    today = today or date.today()
    with closing(db.connect()) as conn:
        ensure(conn)
        tick = refresh_watch(conn, targets(conn, today), today)
        conn.commit()
    if not tick:
        out("주가 보관소: 대상 없음")
        return {"targets": 0, "saved": 0, "gone": 0}
    if download is None:
        import market
        download = lambda ts: market.download_daily(ts, period="3mo")  # noqa: E731
    data = download(tick) or {}
    data = {t: _clean(df) for t, df in data.items() if df is not None and not df.empty}  # 전부 빈 값인 일봉은 '못 받음'으로
    data = {t: df for t, df in data.items() if not df.empty}
    got = [t for t in tick if t in data]
    outage = len(tick) >= 5 and len(got) < len(tick) * OUTAGE_SHARE
    saved, new_gone, back, adj = 0, [], [], []
    with closing(db.connect()) as conn:
        ensure(conn)
        cur_gone = gone(conn)
        for t in tick:
            df = data.get(t)
            if df is not None and not df.empty:
                r = save_bars(conn, t, df)
                saved += r["saved"]
                if r["factor"] != 1.0:
                    adj.append(f"{t}×{r['factor']:.3g}")
                conn.execute("UPDATE px_watch SET misses=0, last_ok=? WHERE ticker=?", (today.isoformat(), t))
                last = df.index[-1].strftime("%Y-%m-%d")
                if _bdays_since(last, today) > STALE_BDAYS:  # 받기는 되는데 새 봉이 없음 → 거래정지·상폐 추정
                    if t not in cur_gone:
                        lc = float(df["Close"].iloc[-1])
                        conn.execute("INSERT OR REPLACE INTO px_gone VALUES (?,?,?,?,?)",
                                     (t, last, lc, today.isoformat(), f"{STALE_BDAYS}거래일 넘게 새 봉 없음(거래정지·상폐 추정)"))
                        new_gone.append(t)
                elif t in cur_gone:  # 다시 거래됨
                    conn.execute("DELETE FROM px_gone WHERE ticker=?", (t,))
                    back.append(t)
            elif not outage:
                conn.execute("UPDATE px_watch SET misses=COALESCE(misses,0)+1 WHERE ticker=?", (t,))
                m = conn.execute("SELECT misses FROM px_watch WHERE ticker=?", (t,)).fetchone()[0]
                last = conn.execute("SELECT date, close FROM px_vault WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
                if m >= MISS_LIMIT and t not in cur_gone:
                    conn.execute("INSERT OR REPLACE INTO px_gone VALUES (?,?,?,?,?)",
                                 (t, last[0] if last else None, last[1] if last else None, today.isoformat(),
                                  f"연속 {MISS_LIMIT}번 주가 못 받음(상장폐지·티커 변경 추정)" + ("" if last else " · 보관된 가격 없음")))
                    new_gone.append(t)
        conn.commit()
    msg = f"주가 보관소: 대상 {len(tick):,} · 받음 {len(got):,} · 저장 {saved:,}줄"
    if outage:
        msg += " · ⚠️ 다운로드 대부분 실패 → 오늘은 끊김 판정 안 함"
    if new_gone:
        msg += f" · 새로 끊김 {', '.join(new_gone[:10])}"
    if back:
        msg += f" · 다시 거래 {', '.join(back[:10])}"
    if adj:
        msg += f" · 단위 맞춤(병합) {', '.join(adj[:10])}"
    out(msg)
    return {"targets": len(tick), "got": len(got), "saved": saved, "gone": new_gone, "back": back, "adjusted": adj, "outage": outage}


def summary(conn=None) -> dict:
    def _read(c):
        ensure(c)
        n = c.execute("SELECT COUNT(DISTINCT ticker), COUNT(*), MIN(date), MAX(date) FROM px_vault").fetchone()
        w = c.execute("SELECT COUNT(*) FROM px_watch WHERE keep_until >= ?", (date.today().isoformat(),)).fetchone()[0]
        return {"tickers": n[0] or 0, "rows": n[1] or 0, "first": n[2], "last": n[3], "watch": w, "gone": len(gone(c))}
    if conn is not None:
        return _read(conn)
    with closing(db.connect()) as c:
        return _read(c)
