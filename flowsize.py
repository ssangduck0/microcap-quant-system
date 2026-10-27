"""📊 매매강도 — 체결 금액 구간별 매수/매도 (P2 2026-10-27, 래빗스탁·오르텍스 식)

토스 실시간 체결(tossws, 구독 최대 50종목)을 한 건씩 금액으로 나눈다: XL ≥ $100K(초대형 기관) · L $10K~100K(기관) · M $1K~10K(중형) · S < $1K(소액 개인).
분 단위로 구간별 매수·매도 금액·건수·주식 수를 `close_flow_size` 에 저장 → 종목 화면 '매매강도' 카드(비중·구간별 도넛·누적 순매수 타임라인).
한계: 스캐너가 구독 중인 종목(장마감 후보·다크풀 상위·워치리스트·저금통 등 ≤50)만, 구독을 시작한 뒤부터. 전 종목 하루치는 유료 틱 데이터가 있어야 한다.
매수/매도 판정은 tossws.classify_trade(호가 기준 → 틱 규칙)와 같다.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

import db

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")
SIZES = ("XL", "L", "M", "S")
SIZE_LABEL = {"XL": "초대형 기관 $100K+", "L": "기관투자자 $10K~$100K", "M": "중형 투자자 $1K~$10K", "S": "소액 개인 <$1K"}
DDL = """CREATE TABLE IF NOT EXISTS close_flow_size (minute TEXT NOT NULL, ticker TEXT NOT NULL, date TEXT, size TEXT NOT NULL,
         buy_usd REAL, sell_usd REAL, mid_usd REAL, buy_n INTEGER, sell_n INTEGER, buy_sh REAL, sell_sh REAL, PRIMARY KEY (minute, ticker, size))"""


def ensure(conn) -> None:
    conn.execute(DDL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cfs ON close_flow_size (ticker, date)")


def bucket_of(usd: float) -> str:
    if usd >= 100_000:
        return "XL"
    if usd >= 10_000:
        return "L"
    if usd >= 1_000:
        return "M"
    return "S"


def days(conn, t: str, n: int = 5) -> list[str]:
    try:
        ensure(conn)
        return [r[0] for r in conn.execute("SELECT DISTINCT date FROM close_flow_size WHERE ticker=? ORDER BY date DESC LIMIT ?", (t.upper(), n))]
    except Exception:  # noqa: BLE001
        return []


def summary(conn, t: str, day: str) -> dict | None:
    """그날 구간별 합계 + 전체 비중. {"by": {size: {buy, sell, buy_n, sell_n, net}}, "buy", "sell", "buy_pct", "verdict", "first", "last"}"""
    try:
        ensure(conn)
        rows = [dict(r) for r in conn.execute("SELECT size, SUM(buy_usd) b, SUM(sell_usd) s, SUM(buy_n) bn, SUM(sell_n) sn, SUM(buy_sh) bsh, SUM(sell_sh) ssh, MIN(minute) f, MAX(minute) l "
                                              "FROM close_flow_size WHERE ticker=? AND date=? GROUP BY size", (t.upper(), day))]
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    by = {z: {"buy": 0.0, "sell": 0.0, "buy_n": 0, "sell_n": 0, "buy_sh": 0.0, "sell_sh": 0.0, "net": 0.0} for z in SIZES}
    first = last = None
    for r in rows:
        if r["size"] in by:
            by[r["size"]] = {"buy": float(r["b"] or 0), "sell": float(r["s"] or 0), "buy_n": int(r["bn"] or 0), "sell_n": int(r["sn"] or 0),
                             "buy_sh": float(r["bsh"] or 0), "sell_sh": float(r["ssh"] or 0), "net": float(r["b"] or 0) - float(r["s"] or 0)}
        first = min(first or r["f"], r["f"])
        last = max(last or r["l"], r["l"])
    buy, sell = sum(v["buy"] for v in by.values()), sum(v["sell"] for v in by.values())
    tot = buy + sell
    pct = None if tot <= 0 else buy / tot * 100
    verdict = "체결 없음" if pct is None else ("매수세 우세" if pct >= 60 else "매도세 우세" if pct <= 40 else "매수·매도 균형")
    return {"by": by, "buy": buy, "sell": sell, "net": buy - sell, "buy_pct": pct, "verdict": verdict, "first": first, "last": last}


def timeline(conn, t: str, day: str) -> pd.DataFrame:
    """분 단위 누적 순매수($)와 분 거래대금 — 가로축 KST."""
    try:
        ensure(conn)
        df = db.read_df("SELECT minute, SUM(buy_usd) b, SUM(sell_usd) s FROM close_flow_size WHERE ticker=? AND date=? GROUP BY minute ORDER BY minute", (t.upper(), day))
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    if df.empty:
        return df
    ts = pd.to_datetime(df["minute"], utc=True).dt.tz_convert(KST)
    out = pd.DataFrame({"누적 순매수($)": (df["b"].fillna(0) - df["s"].fillna(0)).cumsum().values, "분 거래대금($)": (df["b"].fillna(0) + df["s"].fillna(0)).values},
                       index=ts.dt.strftime("%H:%M").values)
    out.index.name = "시각(KST)"
    return out


def basic(conn, t: str, day: str) -> dict | None:
    """구간별 기록이 없을 때 대체: close_flow(주식 수 기준) 매수/매도 비중."""
    try:
        r = conn.execute("SELECT SUM(buy_sh), SUM(sell_sh), SUM(n_trades), MIN(minute), MAX(minute) FROM close_flow WHERE ticker=? AND date=?", (t.upper(), day)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not r or not (r[0] or r[1]):
        return None
    b, s = float(r[0] or 0), float(r[1] or 0)
    return {"buy_sh": b, "sell_sh": s, "n": int(r[2] or 0), "buy_pct": None if b + s <= 0 else b / (b + s) * 100, "first": r[3], "last": r[4]}
