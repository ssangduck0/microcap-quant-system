"""스승님 꿀팁 — 애프터마켓 스캘핑.

① 거래대금 10억 원 이상 ② 분봉 캔들이 제대로 만들어짐('ㅡ' 없음, 수급 연속) ③ 급등 종목 ④ 급등 후 이동평균선(50/200) 근처에서 진입
⑤ +5~7%(많게는 20%) 익절, -5% 손절, 애프터 종료 10분 전(서머타임 KST 08:50, 11월~ 09:50)까지 매도.
이동평균은 '분봉 기준 50·200'으로 해석했다(스캘핑·분봉 판단). 스캐너가 애프터 시간대에 판정·차트용 분봉을 저장하고(대시보드는 토스를 직접 부르지 않음),
진입 구간 신호의 결과(+5% 먼저 / -5% 먼저 / 마감 직전 가격)를 기록해 '체감 승률 70%'를 검증한다.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import db

TIP_TITLE = "스승님 꿀팁 — 애프터마켓 스캘핑"
TIP_TEXT = """애프터마켓 스켈핑
1. 거래대금 10억 이상
2. 분봉 캔들이 만들어지는 차트 ( 'ㅡ' 모양 없음)
3. 보조지표는 50/200일 선 하나만 사용
-> 간단, 급등 후 이동평균선 근처에서 진입
-> 08시 50분 전에 매도 (적당한 구간에서...)
애프터에서 5% ~ 7%, 많게는 20% 수익 얻을 수 있고...
이동평균선 근처에서 진입했다면 손절도 깔끔하게 -5% 잡으면 됩니다.
데이마켓은 또 다른 방법이 있고, 데이 -> 프리 넘어갈 때의 방법도 있어요.
보통 이틀에 한번 꼴로 차트 깔끔한 종목이 나오고 승률은 체감상 70%
제대로 된 급등 종목 없으면 아예 안하는 날도 있었어요.
분봉을 잘 봐야하는데, 수급이 연속적인 종목이여야 합니다."""
DEFAULTS = {"min_value_krw": 1e9, "candle_ok": 0.8, "max_gap": 3, "window": 60, "spike_pct": 15.0,
            "ma_band": 2.0, "target": 5.0, "stop": 5.0, "exit_min": 10}
STAGE_IN, STAGE_WATCH = "🌙 진입 구간", "👀 관찰 — 급등·수급 OK, 이동평균선 대기"
DDL = ["CREATE TABLE IF NOT EXISTS after_state (date TEXT NOT NULL, ticker TEXT NOT NULL, at TEXT, data TEXT, PRIMARY KEY (date, ticker))",
       """CREATE TABLE IF NOT EXISTS after_signals (date TEXT NOT NULL, ticker TEXT NOT NULL, at TEXT, price REAL, max_up REAL, max_down REAL,
          first_hit TEXT, exit_price REAL, updated_at TEXT, PRIMARY KEY (date, ticker))"""]


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def analyze(df: pd.DataFrame | None, after_start: datetime, now: datetime, fx: float, params: dict | None = None) -> dict | None:
    """df: 오늘 1분봉(토스, 동부시간 인덱스, 프리마켓부터). 애프터 시작 후 5분 이상 지나야 판정."""
    p = {**DEFAULTS, **(params or {})}
    if df is None or df.empty:
        return None
    d = df[df.index <= now]
    ah = d[d.index >= after_start]
    if len(ah) < 5:
        return None
    value_krw = float((ah["Close"] * ah["Volume"]).sum() * fx)
    w0 = max(after_start, now - timedelta(minutes=p["window"]))
    expected = max(1, int((now - w0).total_seconds() // 60))
    win = ah[ah.index >= w0]
    good = win[(win["Volume"] > 0) & (win["High"] > win["Low"])]
    flat = int(((win["High"] <= win["Low"]) | (win["Volume"] <= 0)).sum()) + max(0, expected - len(win))
    candle_ratio = min(1.0, len(good) / expected)
    marks = sorted({ts.floor("min") for ts in good.index})  # 거래가 있는 분들 사이의 최대 공백(분)
    pts = [w0.astimezone(good.index.tz) if good.index.tz else w0, *marks, now.astimezone(good.index.tz) if good.index.tz else now] if len(marks) else [w0, now]
    max_gap = int(max((b - a).total_seconds() // 60 - 1 for a, b in zip(pts, pts[1:]))) if len(pts) > 1 else expected
    lb = d  # 오늘(프리마켓부터) 전체: 급등이 앞에서 났고 지금은 이동평균선까지 눌린 경우가 바로 진입 구간이라 최근 몇 시간만 보면 놓친다
    hi_ts = lb["High"].idxmax()
    lo_before = float(lb.loc[:hi_ts, "Low"].min())
    hi = float(lb["High"].max())
    spike = (hi / lo_before - 1) * 100 if lo_before > 0 else 0.0
    price = float(d["Close"].iloc[-1])
    closes = d["Close"]
    ma50 = float(closes.tail(50).mean()) if len(closes) >= 50 else None
    ma200 = float(closes.tail(200).mean()) if len(closes) >= 200 else None
    dist = {k: None if m is None else (price / m - 1) * 100 for k, m in (("ma50", ma50), ("ma200", ma200))}
    near = [k for k, v in dist.items() if v is not None and abs(v) <= p["ma_band"]]
    pulled_back = price <= hi * 0.97
    ok = {"value": value_krw >= p["min_value_krw"], "candle": candle_ratio >= p["candle_ok"] and max_gap <= p["max_gap"],
          "spike": spike >= p["spike_pct"], "ma": bool(near) and pulled_back}
    stage = STAGE_IN if all(ok.values()) else STAGE_WATCH if ok["value"] and ok["candle"] and ok["spike"] else "–"
    items = [
        {"항목": f"① 애프터 거래대금 ≥ {p['min_value_krw'] / 1e8:g}억 원", "값": f"{value_krw / 1e8:,.1f}억 원", "결과": ok["value"]},
        {"항목": f"② 분봉 캔들(최근 {p['window']}분: 거래 있고 고가≠저가 ≥ {p['candle_ok']:.0%}, 공백 ≤ {p['max_gap']}분)",
         "값": f"{candle_ratio:.0%} · 'ㅡ'/빈 분 {flat}개 · 최대 공백 {max_gap}분", "결과": ok["candle"]},
        {"항목": f"③ 급등(오늘 고점 전 저점 → 고점 ≥ +{p['spike_pct']:g}%)", "값": f"+{spike:.0f}% (고점 ${hi:.4f})", "결과": ok["spike"]},
        {"항목": f"④ 급등 후 이동평균선(분봉 50·200) ±{p['ma_band']:g}% 근처", "값": " · ".join(
            f"{k.upper()} {'-' if dist[k] is None else f'{dist[k]:+.1f}%'}" for k in ("ma50", "ma200")) + ("" if pulled_back else " (아직 고점 근처)"), "결과": ok["ma"]},
    ]
    return {"stage": stage, "ok": ok, "items": items, "price": price, "value_krw": value_krw, "candle_ratio": candle_ratio, "max_gap": max_gap, "flat": flat,
            "spike_pct": spike, "high": hi, "ma50": ma50, "ma200": ma200, "dist_ma50": dist["ma50"], "dist_ma200": dist["ma200"],
            "plan": {"entry": price, "target": price * (1 + p["target"] / 100), "target7": price * 1.07, "target20": price * 1.20, "stop": price * (1 - p["stop"] / 100)}}


def outcome(df: pd.DataFrame | None, signal_at: datetime, price: float, deadline: datetime, params: dict | None = None) -> dict:
    """신호 뒤 ~ 매도 마감까지: 최고·최저(%), 목표(+5%)와 손절(-5%) 중 먼저 닿은 쪽, 마감 직전 가격."""
    p = {**DEFAULTS, **(params or {})}
    if df is None or df.empty or not price:
        return {}
    a = df[(df.index > signal_at) & (df.index <= deadline)]
    if a.empty:
        return {"first_hit": None}
    tgt, stp = price * (1 + p["target"] / 100), price * (1 - p["stop"] / 100)
    first = None
    for _, r in a.iterrows():
        up, dn = r["High"] >= tgt, r["Low"] <= stp
        if up and dn:
            first = "동시(판정 불가)"
            break
        if up or dn:
            first = "목표 +%g%%" % p["target"] if up else "손절 -%g%%" % p["stop"]
            break
    return {"max_up": float((a["High"].max() / price - 1) * 100), "max_down": float((a["Low"].min() / price - 1) * 100), "first_hit": first,
            "exit_price": float(a["Close"].iloc[-1])}


def deadline_of(after_end: datetime, params: dict | None = None) -> datetime:
    p = {**DEFAULTS, **(params or {})}
    return after_end - timedelta(minutes=p["exit_min"])


def chart_series(df: pd.DataFrame, n: int = 240) -> dict:
    d = df.tail(n + 200)
    ma50, ma200 = d["Close"].rolling(50).mean(), d["Close"].rolling(200).mean()
    d = d.tail(n)
    return {"t": [x.isoformat() for x in d.index], "close": d["Close"].round(6).tolist(),
            "ma50": [None if np.isnan(x) else round(float(x), 6) for x in ma50.tail(n)], "ma200": [None if np.isnan(x) else round(float(x), 6) for x in ma200.tail(n)]}


def save_state(conn, day: str, ticker: str, data: dict) -> None:
    ensure_tables(conn)
    conn.execute("INSERT OR REPLACE INTO after_state (date, ticker, at, data) VALUES (?,?,?,?)", (day, ticker, datetime.now(timezone.utc).isoformat(), json.dumps(data, ensure_ascii=False)))
    conn.commit()


def record_signal(conn, day: str, ticker: str, at: datetime, price: float) -> bool:
    ensure_tables(conn)
    cur = conn.execute("INSERT OR IGNORE INTO after_signals (date, ticker, at, price, updated_at) VALUES (?,?,?,?,?)", (day, ticker, at.isoformat(), price, db.utcnow_iso()))
    conn.commit()
    return cur.rowcount > 0


def update_outcome(conn, day: str, ticker: str, oc: dict) -> None:
    if not oc:
        return
    conn.execute("UPDATE after_signals SET max_up=?, max_down=?, first_hit=?, exit_price=?, updated_at=? WHERE date=? AND ticker=?",
                 (oc.get("max_up"), oc.get("max_down"), oc.get("first_hit"), oc.get("exit_price"), db.utcnow_iso(), day, ticker))
    conn.commit()


def signals() -> pd.DataFrame:
    with closing(db.connect()) as c:
        ensure_tables(c)
    return db.read_df("SELECT date, ticker, at, price, max_up, max_down, first_hit, exit_price FROM after_signals ORDER BY date DESC, at DESC")


def states(day: str) -> list[tuple[str, str, dict]]:
    with closing(db.connect()) as c:
        ensure_tables(c)
        return [(r["ticker"], r["at"], json.loads(r["data"])) for r in c.execute("SELECT ticker, at, data FROM after_state WHERE date=?", (day,))]
