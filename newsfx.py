"""📊 뉴스 반응(newsfx) — 📰 뉴스 모음의 '종목 있는 뉴스'마다 뉴스 뒤 주가가 어떻게 움직였나를 일봉으로 재서 쌓는다.

2026-10-29 사용자 제안: "뉴스 데이터도 쌓다 보면 ~호재는 시장 반응이 없고 ~호재는 반응이 좋다는 자료가 생기지 않을까?"
· 기준일 D = 뉴스가 미국 시장에 처음 반영될 거래일: 발표 시각(뉴욕)이 16:00 이후면 다음 거래일, 그 전(장전·장중)이면 그날. 주말이면 다음 월요일
· 기준가 = D 직전 일봉 종가. 재는 것: 당일 고가 % · 당일 종가 % · +1일 종가 % · +5일 종가 %(D 뒤 5번째 거래일). 봉이 D 포함 6개 쌓이면 '확정'(done)
· 일봉은 daily_prices(스캐너 우주)에서, 없으면 야후(하루 최대 DOWNLOAD_MAX 종목). 테스트는 bars 인자로 가짜 일봉
· 통계: 분류(Haiku category, 없으면 키워드 판정 호재/악재)×AI 등급별 건수 · 중앙값 · '당일 고가 +10% 이상' 비율 → 📰 화면 '📊 뉴스 반응 통계' + 카드의 '이 종류 과거 반응'(건수 MIN_N 이상일 때)
· AI 비용 0(등급·분류는 번역 때 이미 붙음). 과거 판정은 그날 이전 정보만 쓴다(기준가 = D 직전 종가)
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import db

ET = ZoneInfo("America/New_York")
DDL = """CREATE TABLE IF NOT EXISTS news_react (news_id TEXT PRIMARY KEY, ticker TEXT, day TEXT, prev_close REAL, d0_high_pct REAL, d0_close_pct REAL,
         d1_close_pct REAL, d5_close_pct REAL, bars_after INTEGER, done INTEGER DEFAULT 0, updated_at TEXT)"""
DOWNLOAD_MAX = 40     # daily_prices 에 없는 종목은 하루 이만큼만 야후에서(아침 작업 시간 보호)
LOOKBACK_DAYS = 120   # news 표 보관 기간과 같게
MIN_N = 10            # 카드에 '이 종류 과거 반응'을 보여 주는 최소 건수
HIT_PCT = 10.0        # '반응 있음' = 당일 고가가 기준가보다 이만큼 이상


def ensure(conn) -> None:
    conn.execute(DDL)


def event_day(published: str) -> str:
    """뉴스가 처음 반영될 미국 거래일(달력 기준 — 휴장일은 일봉에서 '그날 이후 첫 봉'으로 자연히 넘어감)."""
    ts = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    et = ts.astimezone(ET)
    d = et.date() + (timedelta(days=1) if et.hour >= 16 else timedelta(0))
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def outcome(df, day: str) -> dict:
    """일봉(DatetimeIndex, Open/High/Low/Close)으로 D 이후 반응. 기준가 = D 직전 종가."""
    r = {"prev_close": None, "d0_high_pct": None, "d0_close_pct": None, "d1_close_pct": None, "d5_close_pct": None, "bars_after": 0, "done": 0}
    if df is None or len(df) == 0:
        return r
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    d = d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["High", "Close"])
    ts = pd.Timestamp(day)
    before, after = d[d.index < ts], d[d.index >= ts]
    r["bars_after"] = int(len(after))
    if before.empty or after.empty or not float(before["Close"].iloc[-1]) > 0:
        return r
    prev = float(before["Close"].iloc[-1])
    pct = lambda x: round((float(x) / prev - 1) * 100, 2)  # noqa: E731
    r.update(prev_close=prev, d0_high_pct=pct(after["High"].iloc[0]), d0_close_pct=pct(after["Close"].iloc[0]))
    if len(after) >= 2:
        r["d1_close_pct"] = pct(after["Close"].iloc[1])
    if len(after) >= 6:
        r["d5_close_pct"] = pct(after["Close"].iloc[5])
        r["done"] = 1
    return r


def pending(conn, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    """종목 있는 뉴스 중 반응이 없거나 아직 확정 안 된 것."""
    ensure(conn)
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute("""SELECT n.id, n.ticker, n.published FROM news n LEFT JOIN news_react r ON r.news_id = n.id
                           WHERE n.ticker IS NOT NULL AND n.published >= ? AND (r.news_id IS NULL OR r.done = 0) ORDER BY n.published""", (since,)).fetchall()
    return [{"id": r[0], "ticker": r[1], "published": r[2], "day": event_day(r[2])} for r in rows]


def _db_bars(conn, tickers: list[str], since: str) -> dict:
    if not tickers:
        return {}
    q = ",".join("?" * len(tickers))
    df = pd.read_sql_query(f"SELECT ticker, date, open AS Open, high AS High, low AS Low, close AS Close FROM daily_prices WHERE ticker IN ({q}) AND date >= ? ORDER BY date",
                           conn, params=[*tickers, since])
    out = {}
    for t, g in df.groupby("ticker"):
        g = g.set_index(pd.to_datetime(g["date"]))[["Open", "High", "Low", "Close"]]
        if len(g):
            out[t] = g
    return out


def update(conn, bars: dict | None = None, *, now: datetime | None = None, out=print, download=None, lookback_days: int = LOOKBACK_DAYS,
           download_max: int = DOWNLOAD_MAX) -> dict:
    """아침 작업: 미확정 뉴스마다 반응을 다시 재서 저장. {"rows", "updated", "done", "open", "nodata"}"""
    ensure(conn)
    rows = pending(conn, lookback_days)
    res = {"rows": len(rows), "updated": 0, "done": 0, "open": 0, "nodata": 0}
    if not rows:
        out("뉴스 반응: 잴 뉴스 없음")
        return res
    now = now or datetime.now(timezone.utc)
    now_et = now.astimezone(ET)
    tickers = sorted({r["ticker"] for r in rows})
    since = (date.fromisoformat(min(r["day"] for r in rows)) - timedelta(days=14)).isoformat()
    data = dict(bars) if bars is not None else _db_bars(conn, tickers, since)
    missing = [t for t in tickers if t not in data]
    if missing and bars is None:
        try:
            import market
            dl = download or (lambda ts: market.download_daily(ts, period="3mo"))
            data.update({t: d for t, d in (dl(missing[:download_max]) or {}).items() if d is not None and len(d)})
        except Exception as e:  # noqa: BLE001
            out(f"뉴스 반응: 야후 일봉 받기 실패({e}) — daily_prices 에 있는 종목만")
    try:
        import cases
        drop = cases.drop_incomplete_last_bar
    except Exception:  # noqa: BLE001
        drop = None
    stamp = now.isoformat()
    for r in rows:
        df = data.get(r["ticker"])
        if df is None or len(df) == 0:
            res["nodata"] += 1
            continue
        if drop is not None:
            try:
                df = drop(df, now_et)
            except Exception:  # noqa: BLE001
                pass
        o = outcome(df, r["day"])
        if o["prev_close"] is None:        # 아직 D 봉이 없음(오늘 뉴스) 또는 기준가 없음 → 다음 아침에
            res["open"] += 1
            continue
        conn.execute("INSERT OR REPLACE INTO news_react VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (r["id"], r["ticker"], r["day"], o["prev_close"], o["d0_high_pct"], o["d0_close_pct"], o["d1_close_pct"], o["d5_close_pct"],
                      o["bars_after"], o["done"], stamp))
        res["updated"] += 1
        res["done" if o["done"] else "open"] += 1
    conn.commit()
    out(f"뉴스 반응: {res['updated']}건 갱신 · 확정 {res['done']} · 진행 {res['open']} · 일봉 없음 {res['nodata']}")
    return res


def reactions(conn, ids: list[str] | None = None) -> dict:
    """{뉴스 id: 반응 행(dict)} — 화면 카드용."""
    try:
        ensure(conn)
        q = "SELECT * FROM news_react"
        rows = conn.execute(q + (f" WHERE news_id IN ({','.join('?' * len(ids))})" if ids else ""), list(ids or [])).fetchall()
    except Exception:  # noqa: BLE001
        return {}
    return {r["news_id"]: dict(r) for r in rows}


def _label(category, sentiment) -> str:
    c = (category or "").strip()
    return c if c else f"{sentiment or '중립'}(키워드)"


def stats(conn, lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """분류×AI 등급별 반응 통계. 열: 분류 · 등급 · 건수 · 당일 고가 중앙값 · 당일 종가 중앙값 · +5일 중앙값(확정분) · +10% 비율 · 확정"""
    try:
        ensure(conn)
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        df = pd.read_sql_query("""SELECT n.category, n.sentiment, n.ai_grade, r.d0_high_pct, r.d0_close_pct, r.d5_close_pct, r.done
                                  FROM news_react r JOIN news n ON n.id = r.news_id WHERE n.published >= ? AND r.d0_high_pct IS NOT NULL""", conn, params=[since])
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    df["분류"] = [_label(c, s) for c, s in zip(df["category"], df["sentiment"])]
    df["등급"] = df["ai_grade"].fillna("-")
    rows = []
    for (cat, gr), g in df.groupby(["분류", "등급"]):
        d5 = g.loc[g["done"] == 1, "d5_close_pct"].dropna()
        rows.append({"분류": cat, "등급": gr, "건수": int(len(g)), "당일 고가 중앙값(%)": round(float(g["d0_high_pct"].median()), 1),
                     "당일 종가 중앙값(%)": round(float(g["d0_close_pct"].median()), 1), "+5일 중앙값(%)": (round(float(d5.median()), 1) if len(d5) else None),
                     "+10% 넘은 비율(%)": round(float((g["d0_high_pct"] >= HIT_PCT).mean() * 100), 0), "확정": int((g["done"] == 1).sum())})
    return pd.DataFrame(rows).sort_values(["건수", "당일 고가 중앙값(%)"], ascending=[False, False]).reset_index(drop=True)


def lookup(st: pd.DataFrame, category, sentiment, grade, min_n: int | None = None) -> dict | None:
    """카드용: 이 분류·등급의 과거 반응(건수가 min_n 이상일 때만 · 기본 MIN_N)."""
    if min_n is None:
        min_n = MIN_N
    if st is None or st.empty:
        return None
    m = st[(st["분류"] == _label(category, sentiment)) & (st["등급"] == (grade or "-")) & (st["건수"] >= min_n)]
    return m.iloc[0].to_dict() if len(m) else None
