"""🧲 매집 의심 — 큰 거래량을 소화하며 주가가 버티거나 오른 날(흡수일)이 반복되는데 뉴스·공시는 없는 종목(일간·주간·월간).

흡수일: 거래량 ≥ 20일 평균 2배 + 전일 대비 하락하지 않음. 강한 매집 의심일: 거래량 ≥ 5배 + 전일 대비 +5% 이상.
합계 점수(높을수록 의심 강함): 흡수일 수(최대 5) + 강한 날 2 + 이유 미확인(기간 안 8-K·6-K·보도 공시 없음) 1 + 최근 45일 희석 서류 없음 1
  + 30일 상승 ≥ 30% 1 + Reg SHO 0.5 + $1 근처(0.8~1.2달러, 상장유지 동기 추정) 0.5. 규칙 기반 추정이며 매수·매도 권유가 아니다.
python accum.py   전체 종목을 분석해 저장(매일 아침 갱신 작업에도 포함)
"""
from __future__ import annotations

import json
import sys
from contextlib import closing
from datetime import date, timedelta

import numpy as np
import pandas as pd

import db

PERIODS = {"일간": 1, "주간": 5, "월간": 21}
NEWS_FORMS = ("8-K", "6-K")
DILUTION_FORMS = ("424B", "S-1", "F-1", "S-3", "F-3", "EFFECT")
DDL = "CREATE TABLE IF NOT EXISTS accum (date TEXT NOT NULL, ticker TEXT NOT NULL, period TEXT NOT NULL, score REAL, data TEXT, PRIMARY KEY (date, ticker, period))"


def daily_rows(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["Close", "Volume"]).copy()
    d["avg20"] = d["Volume"].shift(1).rolling(20, min_periods=10).mean()
    d["vr"] = d["Volume"] / d["avg20"]
    d["chg"] = d["Close"].pct_change() * 100
    d["absorb"] = (d["vr"] >= 2) & (d["chg"] >= 0)
    d["strong"] = (d["vr"] >= 5) & (d["chg"] >= 5)
    return d


def analyze(df: pd.DataFrame | None, filings: list[tuple[str, str]] | None = None, regsho_days: int | None = None) -> dict | None:
    """{기간: 결과} — filings: [(날짜, 서류 종류)]."""
    if df is None or len(df) < 25:
        return None
    d = daily_rows(df)
    if d.empty:
        return None
    last = d.index[-1]
    price = float(d["Close"].iloc[-1])
    r30 = (price / float(d["Close"].iloc[-22]) - 1) * 100 if len(d) > 22 else None
    fl = [(str(x)[:10], f) for x, f in (filings or [])]
    out = {}
    for name, n in PERIODS.items():
        w = d.tail(n)
        start = w.index[0].strftime("%Y-%m-%d")
        ab = w[w["absorb"]]
        st_ = w[w["strong"]]
        news = [x for x in fl if x[0] >= start and x[1].upper().startswith(NEWS_FORMS)]
        dil = [x for x in fl if x[0] >= (last - pd.Timedelta(days=45)).strftime("%Y-%m-%d") and x[1].upper().startswith(DILUTION_FORMS)]
        if ab.empty and st_.empty:
            continue
        cum = (float(w["Close"].iloc[-1]) / float(d["Close"].shift(1).loc[w.index[0]]) - 1) * 100 if not np.isnan(d["Close"].shift(1).loc[w.index[0]]) else None
        top = (st_ if not st_.empty else ab).sort_values("vr", ascending=False).iloc[0]
        parts = {"흡수일": min(len(ab), 5), "강한 날": 2.0 if not st_.empty else 0.0, "이유 미확인": 1.0 if not news else 0.0,
                 "희석 서류 없음": 1.0 if not dil else 0.0, "30일 상승": 1.0 if r30 is not None and r30 >= 30 else 0.0,
                 "Reg SHO": 0.5 if regsho_days else 0.0, "$1 근처": 0.5 if 0.8 <= price <= 1.2 else 0.0}
        out[name] = {"score": float(sum(parts.values())), "parts": parts, "price": price, "r30": r30, "cum": cum, "n_absorb": int(len(ab)), "n_strong": int(len(st_)),
                     "absorb_days": [x.strftime("%m/%d") for x in ab.index], "top_day": top.name.strftime("%m/%d"), "top_vr": float(top["vr"]), "top_chg": float(top["chg"]),
                     "news": news[:5], "dilution": dil[:5], "regsho": regsho_days, "level": "강한 매집 의심" if not st_.empty else "매집 의심"}
    return out


def filings_map(conn, tickers: list[str], since: str) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list] = {}
    for sql in ("SELECT ticker, filed, form FROM sec_hist WHERE filed >= ?", "SELECT ticker, COALESCE(filed, substr(updated,1,10)), form FROM sec_feed WHERE COALESCE(filed, substr(updated,1,10)) >= ?"):
        try:
            for t, f, fm in conn.execute(sql, (since,)):
                out.setdefault(t, []).append((f, fm))
        except Exception:  # noqa: BLE001
            pass
    return out


def run(tickers: list[str] | None = None, chunk: int = 200, out=print, progress=None) -> int:
    import market
    import regsho
    with closing(db.connect()) as conn:
        conn.execute(DDL)
        if tickers is None:
            tickers = sorted(set(db.read_df("SELECT ticker FROM case_progress WHERE status='done'")["ticker"]))
        fmap = filings_map(conn, tickers, (date.today() - timedelta(days=90)).isoformat())
        sho = regsho.streaks(conn)
        day, n = date.today().isoformat(), 0
        for i in range(0, len(tickers), chunk):
            part = tickers[i:i + chunk]
            data = market.download_daily(part, period="3mo", chunk=chunk)
            rows = []
            moves = []
            for t in part:
                dfm = data.get(t)
                if dfm is not None and len(dfm.dropna(subset=["Close"])) > 6:  # 🏷 테마용 오늘 움직임(등락·거래량 배수·5일)
                    dr = daily_rows(dfm)
                    c = dr["Close"]
                    moves.append((t, float(c.iloc[-1]), float(dr["chg"].iloc[-1]), None if pd.isna(dr["vr"].iloc[-1]) else float(dr["vr"].iloc[-1]),
                                  (float(c.iloc[-1]) / float(c.iloc[-6]) - 1) * 100, float(dr["Volume"].iloc[-1])))
                res = analyze(data.get(t), fmap.get(t), sho.get(t))
                for per, r in (res or {}).items():
                    rows.append((day, t, per, r["score"], json.dumps(r, ensure_ascii=False)))
            import themes as _th
            _th.save_moves(conn, day, moves)
            conn.execute("DELETE FROM accum WHERE date=? AND ticker IN (%s)" % ",".join("?" * len(part)), (day, *part))
            conn.executemany("INSERT OR REPLACE INTO accum VALUES (?,?,?,?,?)", rows)
            conn.commit()
            n += len({r[1] for r in rows})
            if progress:
                progress(min(1.0, (i + chunk) / max(len(tickers), 1)), f"매집 분석 {min(i + chunk, len(tickers)):,}/{len(tickers):,}")
        conn.execute("DELETE FROM accum WHERE date < ?", ((date.today() - timedelta(days=30)).isoformat(),))
        conn.commit()
    out(f"매집 의심: {n:,}종목 기록")
    return n


def latest(period: str) -> pd.DataFrame:
    with closing(db.connect()) as conn:
        conn.execute(DDL)
    df = db.read_df("SELECT * FROM accum WHERE period=? AND date=(SELECT MAX(date) FROM accum) ORDER BY score DESC", (period,))
    if not df.empty:
        df["data"] = df["data"].map(json.loads)
    return df


if __name__ == "__main__":
    db.init_db()
    run()
    sys.exit(0)
