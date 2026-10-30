"""공매도 잔고(Short Interest) — Yahoo(FINRA 격주 공시 기반): 공매도 주식 수 · 유통 대비 공매도 비율(Float Short %) · 청산 소요일(Days to Cover).
격주 갱신이라 며칠 늦다. 스퀴즈 후보(Reg SHO·스캐너 기록·워치리스트·저금통·대차 수수료 높은 종목)만 하루 한 번 받는다(종목당 1회 요청).
"""
from __future__ import annotations

import time
from contextlib import closing
from datetime import date

import pandas as pd

import db

DDL = """CREATE TABLE IF NOT EXISTS short_interest (ticker TEXT NOT NULL, date TEXT NOT NULL, shares_short REAL, prior REAL, si_pct REAL, dtc REAL, si_date TEXT,
          float_sh REAL, PRIMARY KEY (ticker, date))"""


def ensure_tables(conn) -> None:
    conn.execute(DDL)
    if "src" not in {r[1] for r in conn.execute("PRAGMA table_info(short_interest)")}:   # chartex 가 더하는 출처 열 — 여기서도 보장(없으면 아래 INSERT 가 깨짐)
        conn.execute("ALTER TABLE short_interest ADD COLUMN src TEXT")
    conn.commit()


def parse_info(info: dict) -> dict:
    pct = info.get("shortPercentOfFloat")
    si_date = info.get("dateShortInterest")
    if isinstance(si_date, (int, float)) and si_date > 1e8:
        si_date = pd.Timestamp(si_date, unit="s").strftime("%Y-%m-%d")
    return {"shares_short": info.get("sharesShort"), "prior": info.get("sharesShortPriorMonth"), "si_pct": None if pct is None else float(pct) * 100,  # Yahoo 는 항상 비율(0.6074 = 60.74%) — 150%↑ 종목도 그대로
            "dtc": info.get("shortRatio"), "si_date": si_date, "float_sh": info.get("floatShares")}


def refresh(tickers: list[str], max_n: int = 400, out=print, getter=None) -> int:
    import yfinance as yf
    get = getter or (lambda t: yf.Ticker(t).get_info())
    day, n = date.today().isoformat(), 0
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        have = {r[0] for r in conn.execute("SELECT ticker FROM short_interest WHERE date=?", (day,))}
        for t in [x for x in dict.fromkeys(tickers) if x not in have][:max_n]:
            try:
                r = parse_info(get(t) or {})
            except Exception:  # noqa: BLE001
                continue
            # 2026-10-30: 열 이름 명시 — chartex(10/27)가 src 열을 더한 뒤 위치 기반 INSERT 가 'has 9 columns but 8 values' 로 아침마다 실패해 야후 공매도 잔고가 사흘 끊겼음(6절 교훈)
            conn.execute("INSERT OR REPLACE INTO short_interest (ticker, date, shares_short, prior, si_pct, dtc, si_date, float_sh, src) VALUES (?,?,?,?,?,?,?,?,?)",
                         (t, day, r["shares_short"], r["prior"], r["si_pct"], r["dtc"], r["si_date"], r["float_sh"], "yahoo"))
            conn.commit()   # 2026-10-30: 종목마다 확정 — 예전엔 700종목(약 9분)을 받는 내내 쓰기 잠금을 쥐어 스캐너·수집기·화면 저장이 '잠김' 으로 실패
            n += 1
            if getter is None:
                time.sleep(0.3)
        conn.commit()
    out(f"공매도 잔고(Yahoo): {n}종목")
    return n


def priority(max_n: int = 700) -> list[str]:
    """오늘 받을 순서(C단계 2026-10-27): 예전엔 '스퀴즈 점수 상위 400'만 받아서 잔고가 없는 종목은 점수가 낮아 영영 못 받는 순환 문제가 있었음.
    ① Reg SHO 명단·대차 수수료 20%↑ 인데 7일 넘게 안 받은 종목 → ② 한 번도 안 받은 종목 → ③ 오래된 순."""
    from datetime import timedelta
    import squeeze
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        uni = squeeze.universe(conn)
        last = {r[0]: r[1] for r in conn.execute("SELECT ticker, MAX(date) FROM short_interest GROUP BY ticker")}
        try:
            import regsho
            hot = set(regsho.streaks(conn))
        except Exception:  # noqa: BLE001
            hot = set()
        try:
            hot |= {r[0] for r in conn.execute("SELECT symbol FROM ibkr_borrow WHERE fee >= 20")}
        except Exception:  # noqa: BLE001
            pass
    stale = (date.today() - timedelta(days=7)).isoformat()
    return sorted(uni, key=lambda t: (0 if (t in hot and (last.get(t) or "") < stale) else 1, last.get(t) or "", t))[:max_n]


def latest_map() -> dict[str, dict]:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        return {r["ticker"]: dict(r) for r in conn.execute(
            "SELECT * FROM short_interest WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM short_interest GROUP BY ticker)")}


def history(t: str) -> pd.DataFrame:
    return db.read_df("SELECT date, si_pct, dtc, shares_short FROM short_interest WHERE ticker=? ORDER BY date", (t.upper(),))
