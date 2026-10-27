"""스승님 꿀팁 — 공매도 흐름 이용하기 (워치리스트·저금통 종목에 적용).

① 바닥 관찰: 최근 저점 근처 + 거래량 감소 + 좁은 가격 폭(횡보)
② 진입 판단: 바닥 근처에서 반등한 '반복' 횟수(섣불리 들어가지 말고 몇 번 구경)
③ 수익확정 커버: 몸통이 작은 양봉이 연속(거래량 폭발 없음) → 이후 다시 눌림 예상
④ 청산: 크게 들어올릴 때(큰 상승 + 거래량 급증) 던지고 나옴
'누가 사는지(공매도의 수익확정 매수인지)'는 데이터로 직접 확인할 수 없어 모양으로만 판정하고,
IBKR 대차 가능 수량 증가(빌린 주식 반환)·FINRA 공매도 비중 감소를 보조 신호로 보여 준다. 신호 결과는 기록해서 검증한다.
"""
from __future__ import annotations

from contextlib import closing

import numpy as np
import pandas as pd

import db

TIP_TITLE = "스승님 꿀팁 — 공매도 흐름 이용하기"
TIP_TEXT = """공매도의 흐름을 이용하기
일단 저점을 잘 보세요
거래량이 줄어들고 낮은 가격에서 횡보할 때 입니다.
섣불리 들어가면 당합니다.
바닥이 어디일지 모르거든요
몇번의 그 반복을 구경하고 있어야 합니다.
자~그러면 이제 진입했다면 차트를 봅니다.
왜냐면 공매도들이 수익 확정하느라 매수세가 들어올 때가 있거든요
이건 압박받아서 들어오는 숏커버가 아니라,
지들 수익확정 커버 입니다.
그때는 아주 얇게 양봉이 연속되어 생깁니다.
그게 수익확정 커버형태 입니다.
그러면 이따가 또 눌리겠죠?
주우우욱 들어올릴때 던지고 나옵니다.
시장가?
괜찮습니다. 이미 공매도는 매수세 밀어넣고 있으니까요.
그니까 열심히 공부하면 공매도의 흐름을 이용해서 먹을수가 있다~"""
CAVEAT = ("주의: '누가 사는지'는 데이터로 확인할 수 없어 양봉 모양으로만 판정합니다(추정). "
          "1000원 미만 종목은 급등 순간 호가 간격이 벌어져 시장가가 몇 % 밀릴 수 있으니, 거래량을 보고 지정가를 함께 고려하세요.")
DEFAULTS = {"lookback": 60, "near_pct": 15.0, "vol_drop": 0.7, "flat_pct": 20.0, "bounce_pct": 10.0, "min_cycles": 2,
            "cover_n": 3, "cover_max": 10, "body_max_pct": 3.0, "cover_vol_max": 1.5, "lift_pct": 15.0, "lift_vol": 3.0}
STAGES = ["④ 들어올림 — 청산 검토", "③ 수익확정 커버형 양봉 — 눌림 대비", "② 바닥 반복 확인 — 진입 검토", "① 바닥 횡보 관찰 중", "–"]
ALERT_STAGES = STAGES[:3]
DDL = "CREATE TABLE IF NOT EXISTS shortflow_events (date TEXT NOT NULL, ticker TEXT NOT NULL, stage TEXT NOT NULL, price REAL, at TEXT, PRIMARY KEY (date, ticker, stage))"


def analyze(df: pd.DataFrame | None, params: dict | None = None, live: dict | None = None, short: dict | None = None) -> dict | None:
    """df: 일봉(OHLCV). live: 스캐너 장중 값 {day_change_pct, volume_mult}(있으면 오늘 판정에 사용). short: 공매도 요약(보조 신호)."""
    p = {**DEFAULTS, **(params or {})}
    if df is None or df.empty:
        return None
    d = df.dropna(subset=["Open", "High", "Low", "Close"]).tail(int(p["lookback"]))
    if len(d) < 40:
        return None
    o, h, l, c = (d[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    v = d["Volume"].to_numpy(float) if "Volume" in d else np.ones(len(c))
    low = float(l.min())
    zone_top = low * (1 + p["near_pct"] / 100)
    near = bool(c[-1] <= zone_top)
    vol10, vol_prev = float(v[-10:].mean()), float(v[-30:-10].mean()) if len(v) >= 30 else float(v[:-10].mean())
    vol_ratio = vol10 / vol_prev if vol_prev > 0 else None
    rng10 = (h[-10:].max() / l[-10:].min() - 1) * 100 if l[-10:].min() > 0 else None
    base_ok = near and vol_ratio is not None and vol_ratio <= p["vol_drop"] and rng10 is not None and rng10 <= p["flat_pct"]
    cycles, i = 0, 0
    while i < len(l):  # 바닥 구간까지 내려왔다가 10거래일 안에 bounce_pct 이상 반등한 횟수
        if l[i] <= zone_top:
            j = min(len(l), i + 11)
            if i + 1 < j and h[i + 1:j].max() >= l[i] * (1 + p["bounce_pct"] / 100):
                cycles += 1
                i = j
                continue
        i += 1
    avg20 = float(v[-21:-1].mean()) if len(v) > 21 else float(v.mean())
    run = 0
    for k in range(len(c) - 1, -1, -1):  # 마지막 봉부터 거꾸로: 몸통 작은 양봉 + 거래량 폭발 없음
        body = (c[k] - o[k]) / o[k] * 100 if o[k] > 0 else 0
        if c[k] > o[k] and body <= p["body_max_pct"] and (avg20 <= 0 or v[k] <= p["cover_vol_max"] * avg20):
            run += 1
        else:
            break
    start_px = c[-run - 1] if run < len(c) else c[0]  # 양봉 연속이 시작되기 직전 가격
    # 바닥에서 진입한 뒤 나타나는 '짧은' 연속만 커버형으로 본다(꾸준한 상승 추세의 작은 양봉들을 잘못 잡지 않도록)
    cover_ok = p["cover_n"] <= run <= p.get("cover_max", 10) and start_px <= zone_top
    chg = (live or {}).get("day_change_pct")
    chg = float(chg) if chg is not None else ((c[-1] / c[-2] - 1) * 100 if len(c) >= 2 and c[-2] > 0 else None)
    vmult = (live or {}).get("volume_mult")
    vmult = float(vmult) if vmult is not None else (v[-1] / avg20 if avg20 > 0 else None)
    lift_ok = chg is not None and vmult is not None and chg >= p["lift_pct"] and vmult >= p["lift_vol"]
    hints = []
    sh = short or {}
    if sh.get("borrow_avail_chg_pct") is not None and not sh.get("borrow_stale"):
        x = sh["borrow_avail_chg_pct"]
        hints.append(f"IBKR 대차 가능 수량 오늘 {x:+.0f}%" + (" — 빌린 주식 반환(커버) 가능성" if x > 0 else " — 새 공매도 가능성"))
    if sh.get("sv_ratio") is not None and sh.get("sv_avg5_ratio") is not None:
        hints.append(f"FINRA 공매도 비중 {sh['sv_ratio']:.0f}% (5일 평균 {sh['sv_avg5_ratio']:.0f}%)" + (" — 감소" if sh["sv_ratio"] < sh["sv_avg5_ratio"] else " — 증가"))
    stage = STAGES[0] if lift_ok else STAGES[1] if cover_ok else STAGES[2] if (base_ok and cycles >= p["min_cycles"]) else STAGES[3] if base_ok else STAGES[4]
    items = [
        {"단계": "① 바닥", "항목": f"최근 {len(c)}일 저점의 +{p['near_pct']:g}% 이내", "현재 값": f"${c[-1]:.4f} (저점 ${low:.4f}, {(c[-1] / low - 1) * 100:+.0f}%)", "결과": near},
        {"단계": "① 바닥", "항목": f"거래량 감소 (최근 10일 ≤ 그 전 20일의 {p['vol_drop']:.0%})", "현재 값": "-" if vol_ratio is None else f"{vol_ratio:.0%}",
         "결과": vol_ratio is not None and vol_ratio <= p["vol_drop"]},
        {"단계": "① 바닥", "항목": f"횡보 (최근 10일 가격 폭 ≤ {p['flat_pct']:g}%)", "현재 값": "-" if rng10 is None else f"{rng10:.0f}%", "결과": rng10 is not None and rng10 <= p["flat_pct"]},
        {"단계": "② 반복", "항목": f"바닥에서 +{p['bounce_pct']:g}% 반등 {p['min_cycles']}회 이상", "현재 값": f"{cycles}회", "결과": cycles >= p["min_cycles"]},
        {"단계": "③ 커버", "항목": f"바닥에서 시작한 얇은 양봉 {p['cover_n']}~{p.get('cover_max', 10)}개 연속 (몸통 ≤ {p['body_max_pct']:g}%, 거래량 ≤ 평균 {p['cover_vol_max']:g}배)",
         "현재 값": f"{run}개 연속", "결과": cover_ok},
        {"단계": "④ 청산", "항목": f"들어올림 (오늘 +{p['lift_pct']:g}% 이상 · 거래량 {p['lift_vol']:g}배 이상)",
         "현재 값": "-" if chg is None else f"{chg:+.1f}% · {('-' if vmult is None else f'{vmult:.1f}배')}" + (" (장중)" if live and live.get("day_change_pct") is not None else ""),
         "결과": lift_ok},
    ]
    return {"stage": stage, "base_ok": base_ok, "cycles": cycles, "cover_run": run, "cover_ok": cover_ok, "lift_ok": lift_ok, "low": low,
            "price": float(c[-1]), "vol_ratio": vol_ratio, "range10_pct": rng10, "day_change_pct": chg, "volume_mult": vmult, "hints": hints, "items": items}


# ---------------------------------------------------------------- 신호 기록·검증
def record(conn, ticker: str, day: str, stage: str, price: float | None) -> bool:
    """같은 날 같은 단계는 한 번만. 새로 기록되면 True(알림 보낼 때)."""
    conn.execute(DDL)
    cur = conn.execute("INSERT OR IGNORE INTO shortflow_events (date, ticker, stage, price, at) VALUES (?,?,?,?,?)", (day, ticker, stage, price, db.utcnow_iso()))
    conn.commit()
    return cur.rowcount > 0


def events() -> pd.DataFrame:
    with closing(db.connect()) as c:
        c.execute(DDL)
    return db.read_df("SELECT date, ticker, stage, price, at FROM shortflow_events ORDER BY date DESC, ticker")


def outcome(df: pd.DataFrame | None, day: str, price: float | None, n: int = 5) -> dict:
    """신호일 다음 n거래일: 최고·최저(신호 가격 대비 %), n일 뒤 종가 %, 다음날 종가 %."""
    if df is None or df.empty or not price:
        return {}
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    after = d[d.index > pd.Timestamp(day)].head(n)
    if after.empty:
        return {"days": 0}
    return {"days": int(len(after)), "max_up": float((after["High"].max() / price - 1) * 100), "max_down": float((after["Low"].min() / price - 1) * 100),
            "next_close": float((after["Close"].iloc[0] / price - 1) * 100), "close_n": float((after["Close"].iloc[-1] / price - 1) * 100) if len(after) >= n else None}
