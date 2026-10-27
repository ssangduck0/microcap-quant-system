"""'비슷한 과거 사례': case_events(전일 종가 대비 -10% 이하 급락 사건) 중 지금 종목과 조건이 비슷한 것을 찾아 결과를 요약한다.

비교 기준
  - 오늘 등락률(전일 종가 대비)  <->  사건의 drop_pct          (±band %p 이내)
  - 거래량 배수                  <->  사건일 거래량 / 직전 20일 평균 (×/÷factor 이내, 선택)
  - 가격                         <->  사건일 종가(분할 보정값)     (×/÷2 이내, 선택 — 오래된 사건은 역분할로 부정확)
  - 비교 시점 이후의 사건은 제외(미래 정보가 섞이지 않도록)
'성공' = 다음날 고가가 사건일 종가 대비 +N% 이상 도달 (일봉이라 도달 순서는 알 수 없음).

이 모듈은 '분석해야 할 종목의 폭을 줄이는' 참고 지표일 뿐이며, 과거 성과가 앞으로를 보장하지 않습니다.
생존편향(상장폐지 종목 부재) 때문에 성공률은 실제보다 낙관적으로 나옵니다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import db

COLS = ["ticker", "date", "close", "drop_pct", "vol_mult", "next_open_pct", "next_high_pct",
        "next_low_pct", "next_close_pct", "fwd_5d", "max_down_5d", "max_up_5d"]
VOL_FACTORS = {"제한 없음": None, "×/÷1.5": 1.5, "×/÷2": 2.0, "×/÷3": 3.0, "×/÷5": 5.0}
MIN_DROP = -10.0  # 과거 사례 DB 의 사건 기준


def load_events() -> pd.DataFrame:
    try:
        return db.read_df(f"SELECT {','.join(COLS)} FROM case_events")
    except Exception:  # noqa: BLE001  (테이블이 아직 없는 경우 등)
        return pd.DataFrame(columns=COLS)


def select(ev: pd.DataFrame, drop: float, band: float = 5.0, vol_mult: float | None = None, vol_factor: float | None = None,
           price: float | None = None, price_factor: float | None = None, before: str | None = None) -> pd.DataFrame:
    m = (ev["drop_pct"] >= drop - band) & (ev["drop_pct"] <= drop + band)
    if vol_factor and vol_mult and vol_mult > 0:
        m &= ev["vol_mult"].between(vol_mult / vol_factor, vol_mult * vol_factor)
    if price_factor and price:
        m &= ev["close"].between(price / price_factor, price * price_factor)
    if before:
        m &= ev["date"] < before
    return ev[m]


def stats(sub: pd.DataFrame, target: float) -> dict:
    known = sub["next_high_pct"].dropna()
    med = lambda col: float(sub[col].median()) if sub[col].notna().any() else None  # noqa: E731
    return {"n": int(len(sub)), "known": int(len(known)),
            "success": float((known >= target).mean() * 100) if len(known) else None,
            "next_open": med("next_open_pct"), "next_high": med("next_high_pct"), "next_close": med("next_close_pct"),
            "fwd_5d": med("fwd_5d"), "max_down_5d": med("max_down_5d")}


def nearest(sub: pd.DataFrame, drop: float, vol_mult: float | None, k: int = 10) -> pd.DataFrame:
    """등락률 차이(5%p = 1)와 거래량 배수 차이(2배 = 1)를 합친 거리로 가장 비슷한 사건 k개."""
    d = ((sub["drop_pct"] - drop) / 5.0) ** 2
    if vol_mult and vol_mult > 0:
        d = d + np.log2(sub["vol_mult"].clip(lower=1e-6) / vol_mult) ** 2   # 거래량 정보가 없는 사건은 거리가 NaN -> 뒤로 밀림
    return sub.assign(distance=np.sqrt(d)).sort_values("distance").head(k)


def annotate(snaps: pd.DataFrame, ev: pd.DataFrame, target: float, band: float = 5.0, vol_factor: float | None = 2.0) -> pd.DataFrame:
    """스냅샷 각 행에 유사 사례 수(sim_n)와 성공률(sim_success)을 붙인다. 오늘 등락률이 -10% 이하인 행만 계산."""
    out = snaps.copy()
    n = np.full(len(out), np.nan)
    succ = np.full(len(out), np.nan)
    q25, q75, up5 = (np.full(len(out), np.nan) for _ in range(3))
    if ev.empty or "day_change_pct" not in out:
        return out.assign(sim_n=n, sim_success=succ, sim_hi_q25=q25, sim_hi_q75=q75, sim_up5_med=up5)
    u5 = ev["max_up_5d"].to_numpy(float) if "max_up_5d" in ev else np.full(len(ev), np.nan)
    d = ev["drop_pct"].to_numpy(float)
    v = ev["vol_mult"].to_numpy(float)
    nh = ev["next_high_pct"].to_numpy(float)
    dates = pd.to_datetime(ev["date"]).to_numpy()
    for j, (chg, vm, date) in enumerate(zip(out["day_change_pct"], out["volume_mult"], out["date"])):
        if chg is None or pd.isna(chg) or chg > MIN_DROP:
            continue
        m = (d >= chg - band) & (d <= chg + band) & (dates < np.datetime64(date))
        if vol_factor and vm is not None and not pd.isna(vm) and vm > 0:
            m &= (v >= vm / vol_factor) & (v <= vm * vol_factor)
        n[j] = int(m.sum())
        k = nh[m]
        k = k[~np.isnan(k)]
        if len(k):
            succ[j] = float((k >= target).mean() * 100)
            q25[j], q75[j] = float(np.percentile(k, 25)), float(np.percentile(k, 75))  # 예상 다음날 고가 범위(중간 50%)
        u = u5[m]
        u = u[~np.isnan(u)]
        if len(u):
            up5[j] = float(np.median(u))
    return out.assign(sim_n=n, sim_success=succ, sim_hi_q25=q25, sim_hi_q75=q75, sim_up5_med=up5)
