"""📐 차트 관점 엔진 — 래빗스탁 차트 고수(키쟈키라 · ANO) 규칙을 숫자로 (2026-10-27, 근거: docs/chart_masters.md)

입력은 전부 가격표(일봉 · 60분봉 · 5분봉: Open High Low Close Volume, 시간 인덱스) → 순수 계산. 인터넷은 fetch() 에서만.
키쟈키라: 기준봉(거래 터진 급등 마디) → 채널(발·무릎·허리·어깨·머리·보라) → 허리·되돌림 단계 → 매물대 진함/공백 → 지지 반복 횟수
          → 일봉 5/20 골크·50일·1년선 → 60분봉 5·20 정배열·200선 돌파 지지 → 5분봉 이평 수렴·5·20 꺾임·200선·VWAP → 파라볼릭 접촉 시점 · 볼린저 수축
ANO:      50/200 SMA 교차·이격도 → 다이버전스(주가↓ 거래량↓ MACD↑) → 고점 'ㅗ' 캔들·긴 밑꼬리 → 3~5일 연속 하락 뒤 전환 → 유통주식 회전율
컨닝 금지: analyze() 는 받은 표의 마지막 봉까지만 쓴다(과거 판정은 표를 그날까지 잘라서 넣으면 된다).
"""
from __future__ import annotations

import json
import math
from contextlib import closing
from datetime import date, datetime

import numpy as np
import pandas as pd

import db

# ---------------------------------------------------------------- 기준(출발값 — 관리 모드에서 바꾸기 전엔 여기)
BASE_LOOKBACK = 120     # 기준봉을 찾는 일봉 수
BASE_VOL_X = 3.0        # 기준봉: 거래량이 직전 20일 평균의 몇 배
BASE_GAIN = 0.25        # 기준봉: 고가가 전일 종가 대비 몇 % 이상(+25%)
HEAD_DAYS = 10          # 기준봉 뒤 며칠 안의 최고가를 '머리'(1파 고점)로
OVERSHOOT = 1.20        # 보라돌이 = 머리 × 1.2 (오버슈팅)
RETRACE = ((0.25, 0.38), (0.40, 0.50), (0.60, 0.80))   # 되돌림 단계(머리 대비 내림폭)
STAGE_KO = {0: "아직 얕음(−25% 안)", 1: "1차(−25~−40%)", 2: "2차(−40~−60%)", 3: "3차(−60~−80%)", 4: "−80% 넘음(전고 회복 어려움)"}
PROFILE_BINS = 24       # 매물대 칸 수
THICK_X, GAP_X = 1.5, 0.4   # 매물대 '진함' = 평균 × 1.5↑ · '공백' = 평균 × 0.4↓
TOUCH_TOL = 0.03        # 지지 터치 허용 오차(±3%)
WEAK_TOUCHES = 4        # 같은 자리 4차 지지부터 '약해짐'
BB_SQUEEZE_PCT = 20     # 볼린저 폭이 최근 120봉 중 하위 20% 안이면 수축
CONVERGE_PCT = 2.0      # 5분봉 이평(5·20·60) 폭이 현재가의 2% 안이면 수렴
SAR_AF, SAR_MAX = 0.02, 0.20

SIGNALS = {  # 코드: (이름, 방향 +1 오름/-1 내림/0 참고, 목표 %, 기간 거래일, 설명)
    "pullback": ("📐 급등 후 눌림 타점(무릎~허리 지지)", 1, 10.0, 5, "기준봉 뒤 무릎~허리까지 눌렸고 5분봉 이평 수렴·파라볼릭 접근·밑꼬리 중 하나 — 지지 확인 뒤 진입(키쟈키라 단타 6단계)"),
    "h60_200": ("📐 60분봉 200선 돌파 지지", 1, 20.0, 10, "60분봉 200선을 넘고 3봉 이상 지킴 = 초기 파동 시작(공매 똥줄 구간)"),
    "gc520": ("📐 일봉 5/20 골든크로스", 1, 20.0, 10, "일봉 5일선이 20일선을 3일 안에 골든크로스(급등 전조) · 50일선 위면 세력 주도"),
    "turn3": ("📐 연속 하락 뒤 전환(ANO 비급)", 1, 10.0, 5, "3~5일 연속 하락(시가 < 전일 종가) 뒤 전일 시가를 넘김 — 지수 편입주에 통함, 소형주는 참고만"),
    "retrace1": ("📐 1차 되돌림 반등선(−25~−38%)", 0, 10.0, 5, "머리 대비 −25~−38% 구간에서 버팀 — 여기서 지지하면 대성, 깨지면 2차(−40~−50%)"),
    "sar_due": ("📐 파라볼릭 접촉 임박", 0, None, 0, "일봉 점도표가 2봉 안에 캔들과 만남 — 수급이 붙으면 파동 가능"),
    "life_break": ("📐 생명선 이탈(기준봉 시작가)", -1, 0.0, 5, "기준봉 시작가 아래 마감 — 상승 추세 사망(휩쏘인지 거래량 확인)"),
    "waist_break": ("📐 허리 이탈", -1, 0.0, 5, "채널 허리(50%) 아래 마감 — 아래 채널로 이동"),
    "m5_break": ("📐 5분봉 5·20 모두 꺾임", -1, 0.0, 1, "5분봉 5·20일선이 함께 내려가고 가격이 둘 아래 — 투매 신호(보유 종목 경고)"),
    "top_candle": ("📐 고점 'ㅗ' 캔들", -1, 0.0, 5, "20일 고점 부근에서 윗꼬리가 몸통 2배 — 매도 승률 좋은 자리(ANO)"),
}
WARN_CODES = ("life_break", "waist_break", "m5_break", "top_candle")
MORNING_CODES = tuple(k for k in SIGNALS if k != "m5_break")   # 아침 점검은 5분봉 꺾임(장중용)은 기록하지 않는다
DDL = """CREATE TABLE IF NOT EXISTS chart_signals (date TEXT NOT NULL, ticker TEXT NOT NULL, kind TEXT NOT NULL, price REAL, note TEXT, at TEXT,
         PRIMARY KEY (date, ticker, kind))"""


# ---------------------------------------------------------------- 기본 계산
def _ohlcv(df: pd.DataFrame | None, min_rows: int = 5) -> pd.DataFrame | None:
    if df is None or len(df) < min_rows or "Close" not in df:
        return None
    d = df.copy()
    for c in ("Open", "High", "Low"):
        if c not in d:
            d[c] = d["Close"]
    if "Volume" not in d:
        d["Volume"] = 0.0
    d = d[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    d = d.dropna(subset=["Close"])
    d = d[d["Close"] > 0]
    return d if len(d) >= min_rows else None


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def parabolic_sar(high: np.ndarray, low: np.ndarray, af0: float = SAR_AF, af_max: float = SAR_MAX) -> tuple[np.ndarray, np.ndarray]:
    """표준 파라볼릭 SAR. 반환 (sar 값, 방향: +1 상승 추세(점이 아래) / -1 하락 추세(점이 위))."""
    n = len(high)
    sar, trend = np.zeros(n), np.zeros(n)
    if n < 2:
        return sar, trend
    up = high[1] >= high[0]
    ep = high[0] if up else low[0]
    s = low[0] if up else high[0]
    af = af0
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
            if low[i] < s:   # 추세 전환
                up, s, ep, af = False, ep, low[i], af0
            elif high[i] > ep:
                ep, af = high[i], min(af + af0, af_max)
        else:
            s = max(s, high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
            if high[i] > s:
                up, s, ep, af = True, ep, high[i], af0
            elif low[i] < ep:
                ep, af = low[i], min(af + af0, af_max)
        sar[i], trend[i] = s, 1 if up else -1
    return sar, trend


def sar_state(d: pd.DataFrame | None, horizon: int = 30) -> dict | None:
    """점도표 위치와 '가격이 지금 자리에 머문다면' 몇 봉 뒤 캔들과 만나는지(키쟈키라의 접촉 시점 계산)."""
    d = _ohlcv(d, 10)
    if d is None:
        return None
    h, l, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    sar, tr = parabolic_sar(h, l)
    pos = "below" if tr[-1] > 0 else "above"
    px = float(c[-1])
    eta = None
    h2, l2 = list(h), list(l)
    for k in range(1, horizon + 1):   # 가격이 그대로라고 가정하고 앞으로 그려 본다
        h2.append(px)
        l2.append(px)
        s2, t2 = parabolic_sar(np.array(h2[-(len(h) + k):]), np.array(l2[-(len(h) + k):]))
        if t2[-1] != tr[-1] or abs(s2[-1] - px) <= px * 0.002:   # 점이 캔들에 닿음(가격이 그대로면 점은 캔들 값에서 멈춘다)
            eta = k
            break
    return {"pos": pos, "value": float(sar[-1]), "eta": eta, "gap_pct": (float(sar[-1]) / px - 1) * 100}


def bollinger(d: pd.DataFrame | None, n: int = 20, lookback: int = 120) -> dict | None:
    d = _ohlcv(d, n + 5)
    if d is None:
        return None
    c = d["Close"]
    mid, sd = sma(c, n), c.rolling(n).std()
    width = ((4 * sd) / mid * 100).dropna()
    if width.empty:
        return None
    w = width.tail(lookback)
    pct = float((w < w.iloc[-1]).mean() * 100)
    up, lo = float(mid.iloc[-1] + 2 * sd.iloc[-1]), float(mid.iloc[-1] - 2 * sd.iloc[-1])
    return {"width_pct": float(w.iloc[-1]), "pctile": pct, "squeeze": pct <= BB_SQUEEZE_PCT, "upper": up, "lower": lo, "mid": float(mid.iloc[-1]),
            "pos": "above" if c.iloc[-1] > up else ("below" if c.iloc[-1] < lo else "in")}


# ---------------------------------------------------------------- 기준봉 · 채널 · 되돌림
def base_candle(d: pd.DataFrame | None, lookback: int = BASE_LOOKBACK, vol_x: float = BASE_VOL_X, gain: float = BASE_GAIN) -> dict | None:
    """가장 최근 기준봉(거래 터진 급등 마디). 반환 {idx, date, open, low, vol, head, head_date, foot, ...} 없으면 None."""
    d = _ohlcv(d, 25)
    if d is None:
        return None
    o, h, l, c, v = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close", "Volume"))
    n = len(c)
    v20 = pd.Series(v).shift(1).rolling(20, min_periods=10).median().to_numpy()   # 중앙값: 급등 중 며칠이 평균을 끌어올리지 않게
    start = max(20, n - lookback)
    cands = [i for i in range(start, n) if v20[i] > 0 and v[i] >= vol_x * v20[i] and (h[i] / c[i - 1] - 1) >= gain]
    if not cands:
        return None
    j = len(cands) - 1
    while j > 0 and cands[j] - cands[j - 1] <= 3:   # 연달아(3일 안) 터진 날들은 한 마디 → 마디의 첫날이 기준봉
        j -= 1
    i = cands[j]
    j_end = min(n, i + HEAD_DAYS + 1)
    j = i + int(np.argmax(h[i:j_end]))
    head, foot, life = float(h[j]), float(min(l[i], o[i])), float(o[i])
    if head <= foot:
        return None
    return {"idx": i, "date": d.index[i].strftime("%Y-%m-%d"), "open": float(o[i]), "low": float(l[i]), "vol": float(v[i]), "vol_x": float(v[i] / v20[i]),
            "gain_pct": (h[i] / c[i - 1] - 1) * 100, "head": head, "head_idx": j, "head_date": d.index[j].strftime("%Y-%m-%d"), "foot": foot, "life": life,
            "days_since": n - 1 - i}


def channel_levels(base: dict) -> dict:
    """발·무릎·허리·어깨·머리·보라돌이(오버슈팅) 가격."""
    f, hd = base["foot"], base["head"]
    r = hd - f
    return {"발": f, "무릎": f + 0.25 * r, "허리": f + 0.5 * r, "어깨": f + 0.75 * r, "머리": hd, "보라돌이": hd * OVERSHOOT, "생명선": base["life"]}


def retrace_state(d: pd.DataFrame, base: dict) -> dict:
    """머리 대비 지금 내림폭 · 되돌림 단계(1: −25~−40 · 2: −40~−60 · 3: −60~−80 · 4: −80 넘음) · 머리 뒤 최저 종가가 어디서 버텼는지(유형 A/B/C)."""
    c = d["Close"].to_numpy()
    lv = channel_levels(base)
    px = float(c[-1])
    dd = px / base["head"] - 1
    low_after = float(c[base["head_idx"]:].min())
    typ = "A(어깨 위 버팀)" if low_after >= lv["어깨"] else ("B(허리 위 버팀)" if low_after >= lv["허리"] else ("C(무릎 위 버팀)" if low_after >= lv["무릎"] else "붕괴(무릎 아래)"))
    stage = 0 if dd > -RETRACE[0][0] else (1 if dd > -RETRACE[1][0] else (2 if dd > -RETRACE[2][0] else (3 if dd > -RETRACE[2][1] else 4)))
    zone = "허리 위" if px >= lv["허리"] else ("무릎~허리" if px >= lv["무릎"] else ("발~무릎" if px >= lv["발"] else "발 아래"))
    return {"dd_pct": dd * 100, "stage": stage, "type": typ, "zone": zone, "above_life": px >= lv["생명선"], "above_waist": px >= lv["허리"],
            "r1": base["head"] * (1 - 0.37), "r2": base["head"] * 0.5, "r3": base["head"] * 0.3, "low_after": low_after}


# ---------------------------------------------------------------- 매물대 · 지지 반복
def volume_profile(d: pd.DataFrame | None, bins: int = PROFILE_BINS, lookback: int = BASE_LOOKBACK) -> pd.DataFrame | None:
    """가격 칸마다 쌓인 거래량(하루 거래량을 그날 저가~고가에 고르게 나눔). 열: lo, hi, vol, share, kind(진함/보통/공백)."""
    d = _ohlcv(d, 20)
    if d is None:
        return None
    d = d.tail(lookback)
    lo_all, hi_all = float(d["Low"].min()), float(d["High"].max())
    if hi_all <= lo_all:
        return None
    edges = np.linspace(lo_all, hi_all, bins + 1)
    vol = np.zeros(bins)
    for _, r in d.iterrows():
        a, b, v = float(r["Low"]), float(r["High"]), float(r["Volume"])
        if v <= 0:
            continue
        if b <= a:
            k = min(bins - 1, int(np.searchsorted(edges, a, side="right") - 1))
            vol[max(0, k)] += v
            continue
        for k in range(bins):
            ov = min(b, edges[k + 1]) - max(a, edges[k])
            if ov > 0:
                vol[k] += v * ov / (b - a)
    tot = vol.sum()
    if tot <= 0:
        return None
    share = vol / tot
    avg = 1.0 / bins
    kind = np.where(share >= THICK_X * avg, "진함", np.where(share <= GAP_X * avg, "공백", "보통"))
    return pd.DataFrame({"lo": edges[:-1], "hi": edges[1:], "vol": vol, "share": share * 100, "kind": kind})


def profile_summary(prof: pd.DataFrame | None, px: float) -> dict | None:
    """현재가 기준: 위 첫 진한 매물(저항) · 위 공백(빠르게 통과) · 아래 첫 진한 매물(지지) · 아래가 얇은지(주르륵 위험)."""
    if prof is None or not px:
        return None
    above, below = prof[prof["lo"] >= px], prof[prof["hi"] <= px]
    cur = prof[(prof["lo"] <= px) & (prof["hi"] > px)]
    thick_above = above[above["kind"] == "진함"].head(1)
    gap_above = above[above["kind"] == "공백"].head(1)
    thick_below = below[below["kind"] == "진함"].tail(1)
    below_share = float(below["share"].sum()) if not below.empty else 0.0
    above_share = float(above["share"].sum()) if not above.empty else 0.0
    return {"here": None if cur.empty else str(cur["kind"].iloc[0]), "here_share": None if cur.empty else float(cur["share"].iloc[0]),
            "res": None if thick_above.empty else float(thick_above["lo"].iloc[0]), "res_share": None if thick_above.empty else float(thick_above["share"].iloc[0]),
            "gap_up": None if gap_above.empty else float(gap_above["lo"].iloc[0]),
            "sup": None if thick_below.empty else float(thick_below["hi"].iloc[0]), "sup_share": None if thick_below.empty else float(thick_below["share"].iloc[0]),
            "below_share": below_share, "above_share": above_share, "thin_below": below_share < 15.0 and above_share > 50.0}


def touch_count(d: pd.DataFrame | None, level: float | None, tol: float = TOUCH_TOL, lookback: int = 60) -> int:
    """어떤 가격 자리를 저가가 몇 번(따로 떨어진 봉 묶음으로) 건드렸는지 — 반복될수록 약해진다."""
    d = _ohlcv(d, 5)
    if d is None or not level:
        return 0
    lo = d["Low"].tail(lookback).to_numpy()
    hit = np.abs(lo / level - 1) <= tol
    n, prev = 0, False
    for x in hit:
        if x and not prev:
            n += 1
        prev = x
    return n


# ---------------------------------------------------------------- 이동평균 상태(시간대별)
def ma_daily(d: pd.DataFrame | None) -> dict | None:
    d = _ohlcv(d, 25)
    if d is None:
        return None
    c = d["Close"]
    out = {"px": float(c.iloc[-1])}
    for n in (5, 20, 50, 100, 200, 250):
        s = sma(c, n)
        out[f"ma{n}"] = None if len(c) < n or pd.isna(s.iloc[-1]) else float(s.iloc[-1])
    m5, m20 = sma(c, 5), sma(c, 20)
    diff = (m5 - m20).to_numpy()
    out["gc_days"] = out["dc_days"] = None
    for k in range(1, min(16, len(diff))):   # 최근 15일 안 교차
        a, b = diff[-k - 1], diff[-k]
        if not (np.isnan(a) or np.isnan(b)):
            if a <= 0 < b and out["gc_days"] is None:
                out["gc_days"] = k - 1
            if a >= 0 > b and out["dc_days"] is None:
                out["dc_days"] = k - 1
    out["slope20"] = None if len(c) < 25 or pd.isna(m20.iloc[-6]) else (float(m20.iloc[-1]) / float(m20.iloc[-6]) - 1) * 100
    out["gap50_200"] = None if not (out["ma50"] and out["ma200"]) else (out["ma50"] / out["ma200"] - 1) * 100
    m50, m200 = sma(c, 50), sma(c, 200)
    out["cross50_200"] = None
    if out["ma50"] and out["ma200"]:
        dd = (m50 - m200).dropna().to_numpy()
        out["cross50_200"] = "골든" if dd[-1] > 0 else "데드"
        out["cross50_200_days"] = None
        for k in range(1, min(21, len(dd))):
            if np.sign(dd[-k - 1]) != np.sign(dd[-k]):
                out["cross50_200_days"] = k - 1
                break
    out["above"] = {n: (out[f"ma{n}"] is not None and out["px"] >= out[f"ma{n}"]) for n in (5, 20, 50, 100, 200, 250)}
    return out


def ma_intraday(df: pd.DataFrame | None, kind: str) -> dict | None:
    """60분봉(kind='h60'): 5·20·50·200 정배열·200선 돌파 지지 · 5분봉(kind='m5'): 5·20·60 수렴 · 5·20 꺾임 · 200선 · 오늘 VWAP."""
    d = _ohlcv(df, 25)
    if d is None:
        return None
    c, v = d["Close"], d["Volume"]
    px = float(c.iloc[-1])
    out = {"px": px, "bars": len(d)}
    for n in (5, 20, 50, 60, 200):
        s = sma(c, n)
        out[f"ma{n}"] = None if len(c) < n or pd.isna(s.iloc[-1]) else float(s.iloc[-1])

    def rising(n, k=3):
        s = sma(c, n)
        return None if len(c) < n + k or pd.isna(s.iloc[-1 - k]) else bool(s.iloc[-1] > s.iloc[-1 - k])
    out["up5"], out["up20"] = rising(5), rising(20)
    if kind == "h60":
        out["aligned"] = bool(out["ma5"] and out["ma20"] and out["ma50"] and out["ma5"] > out["ma20"] > out["ma50"] and out["up5"] and out["up20"])
        out["alive"] = bool(out["ma5"] and out["ma20"] and px >= out["ma20"] and out["up20"])
        out["dist200"] = None if not out["ma200"] else (px / out["ma200"] - 1) * 100
        out["break200"] = None
        if out["ma200"]:
            m200 = sma(c, 200).to_numpy()
            cc = c.to_numpy()
            above = cc > m200
            if above[-3:].all() and len(above) > 40:
                k = next((i for i in range(1, 41) if not above[-1 - i]), None)   # 몇 봉 전부터 위에 있나
                out["break200"] = k if k is not None else 40
    else:
        mas = [out[k] for k in ("ma5", "ma20", "ma60") if out[k]]
        out["converge_pct"] = None if len(mas) < 2 else (max(mas) - min(mas)) / px * 100
        out["converged"] = bool(out["converge_pct"] is not None and out["converge_pct"] <= CONVERGE_PCT)
        out["broken"] = bool(out["ma5"] and out["ma20"] and out["up5"] is False and out["up20"] is False and px < out["ma5"] and px < out["ma20"])
        out["riding5"] = bool(out["ma5"] and out["ma20"] and px >= out["ma5"] > out["ma20"] and out["up5"])
        out["dist200"] = None if not out["ma200"] else (px / out["ma200"] - 1) * 100
        last_day = d.index[-1].date() if hasattr(d.index[-1], "date") else None
        today = d[[i.date() == last_day for i in d.index]] if last_day else d.tail(78)
        tv = float(today["Volume"].sum())
        out["vwap"] = None if tv <= 0 else float((today["Close"] * today["Volume"]).sum() / tv)
        out["dist_vwap"] = None if not out["vwap"] else (px / out["vwap"] - 1) * 100
    return out


# ---------------------------------------------------------------- 다이버전스 · 캔들 · 회전율
def divergence(d: pd.DataFrame | None, n: int = 20) -> dict | None:
    d = _ohlcv(d, n + 30)
    if d is None:
        return None
    import ta
    c, v = d["Close"], d["Volume"]
    m = ta.macd(c)
    line = m["macd"] if "macd" in m else m.iloc[:, 0]
    price_chg = float(c.iloc[-1] / c.iloc[-n] - 1) * 100
    v_recent, v_prior = float(v.tail(5).mean()), float(v.iloc[-n:-5].mean()) if len(v) >= n else float(v.mean())
    vol_ratio = None if v_prior <= 0 else v_recent / v_prior
    macd_up = bool(line.iloc[-1] > line.iloc[-n])
    hh = float(c.tail(5).max()) > float(c.iloc[-n:-5].max())
    bull = price_chg <= -10 and macd_up and (vol_ratio is None or vol_ratio < 1.0)
    bear = hh and vol_ratio is not None and vol_ratio < 0.8
    return {"price_chg": price_chg, "vol_ratio": vol_ratio, "macd_up": macd_up, "bull": bull, "bear": bear}


def candles(d: pd.DataFrame | None) -> dict | None:
    d = _ohlcv(d, 25)
    if d is None:
        return None
    o, h, l, c = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    body, rng = abs(c[-1] - o[-1]), h[-1] - l[-1]
    upper, lower = h[-1] - max(o[-1], c[-1]), min(o[-1], c[-1]) - l[-1]
    near_high = h[-1] >= float(h[-20:].max()) * 0.9
    top = bool(rng > 0 and upper >= 2 * max(body, rng * 0.05) and upper >= 0.5 * rng and near_high)
    hammer = bool(rng > 0 and lower >= 2 * max(body, rng * 0.05) and lower >= 0.5 * rng)
    run = 0   # 연속 하락(시가 < 전일 종가 & 종가 < 전일 종가) — 어제까지
    for k in range(2, min(8, len(c))):
        if c[-k] < c[-k - 1] and o[-k] < c[-k - 1]:
            run += 1
        else:
            break
    turn = bool(3 <= run <= 5 and c[-1] > o[-2])          # 오늘이 마지막 하락일(어제)의 시가를 넘김
    waiting = bool(3 <= run <= 5 and not turn)
    return {"top": top, "hammer": hammer, "down_run": run, "turn": turn, "turn_waiting": waiting,
            "upper_pct": upper / c[-1] * 100, "lower_pct": lower / c[-1] * 100}


def turnover(d: pd.DataFrame | None, float_shares: float | None) -> float | None:
    d = _ohlcv(d, 1)
    if d is None or not float_shares or float_shares <= 0:
        return None
    return float(d["Volume"].iloc[-1]) / float(float_shares)


# ---------------------------------------------------------------- 종합
def analyze(daily: pd.DataFrame | None, h60: pd.DataFrame | None = None, m5: pd.DataFrame | None = None, float_shares: float | None = None) -> dict | None:
    """한 종목의 차트 관점 전부. 일봉이 25봉 미만이면 None."""
    d = _ohlcv(daily, 25)
    if d is None:
        return None
    px = float(d["Close"].iloc[-1])
    base = base_candle(d)
    out = {"px": px, "prev_px": float(d["Close"].iloc[-2]), "date": d.index[-1].strftime("%Y-%m-%d"), "base": base, "levels": channel_levels(base) if base else None,
           "retrace": retrace_state(d, base) if base else None, "ma_d": ma_daily(d), "ma_60": ma_intraday(h60, "h60"), "ma_5": ma_intraday(m5, "m5"),
           "sar_d": sar_state(d), "sar_60": sar_state(h60), "sar_5": sar_state(m5), "bb": bollinger(d), "div": divergence(d), "candle": candles(d),
           "turnover": turnover(d, float_shares)}
    prof = volume_profile(d)
    out["profile"] = prof
    out["prof"] = profile_summary(prof, px)
    sup_level = None
    if out["prof"] and out["prof"]["sup"]:
        sup_level = out["prof"]["sup"]
    if out["levels"]:
        below = [v for k, v in out["levels"].items() if k in ("발", "무릎", "허리", "어깨") and v <= px]
        if below and (sup_level is None or max(below) > sup_level):
            sup_level = max(below)
    out["support"] = {"level": sup_level, "touches": touch_count(d, sup_level), "dist_pct": None if not sup_level else (px / sup_level - 1) * 100}
    out["checks"] = checklist(out)
    out["signals"] = signals(out)
    out["verdict"] = verdict(out)
    return out


def _st(ok: bool | None, warn: bool = False) -> str:
    return "none" if ok is None else ("warn" if warn else ("good" if ok else "bad"))


def checklist(a: dict) -> list[dict]:
    """두 고수의 체크리스트: [{who, name, status(good/warn/bad/none), detail}]."""
    L, r, md, m60, m5, sar, bb, dv, cd, pr, sp = (a.get(k) for k in ("levels", "retrace", "ma_d", "ma_60", "ma_5", "sar_d", "bb", "div", "candle", "prof", "support"))
    px = a["px"]
    k = []
    if a["base"] and L and r:
        b = a["base"]
        k.append({"who": "키쟈", "name": "기준봉·생명선", "status": _st(r["above_life"]), "detail": f"{b['date']} 거래 {b['vol_x']:.1f}배·+{b['gain_pct']:.0f}% · 생명선 ${L['생명선']:.4f}({'위' if r['above_life'] else '아래 ❗'})"})
        k.append({"who": "키쟈", "name": "허리(50%)", "status": _st(r["above_waist"]), "detail": f"허리 ${L['허리']:.4f} · 지금 {r['zone']} · 머리 대비 {r['dd_pct']:+.0f}%"})
        k.append({"who": "키쟈", "name": "되돌림 단계·유형", "status": "good" if r["stage"] <= 1 else ("warn" if r["stage"] == 2 else "bad"),
                  "detail": STAGE_KO[r["stage"]] + f" · 유형 {r['type']} · 1차 반등선 ${r['r1']:.4f}"})
    else:
        k.append({"who": "키쟈", "name": "기준봉", "status": "none", "detail": f"최근 {BASE_LOOKBACK}일 안 거래 {BASE_VOL_X:g}배·+{BASE_GAIN * 100:.0f}% 급등 마디 없음"})
    if pr:
        k.append({"who": "키쟈", "name": "위 매물(저항)", "status": "warn" if pr["res"] and pr["res"] / px - 1 < 0.15 else ("good" if pr["res"] is None or pr["gap_up"] and pr["gap_up"] < (pr["res"] or 1e18) else "none"),
                  "detail": (f"첫 진한 매물 ${pr['res']:.4f}(+{(pr['res'] / px - 1) * 100:.0f}%, {pr['res_share']:.0f}%)" if pr["res"] else "위에 진한 매물 없음") + (f" · 공백 ${pr['gap_up']:.4f}부터" if pr["gap_up"] else "")})
        k.append({"who": "키쟈", "name": "아래 매물(지지)", "status": "bad" if pr["thin_below"] else ("good" if pr["sup"] else "none"),
                  "detail": (f"진한 지지 ${pr['sup']:.4f}({(pr['sup'] / px - 1) * 100:+.0f}%)" if pr["sup"] else "아래 진한 매물 없음") + (" · 아래가 얇아 깨지면 주르륵" if pr["thin_below"] else "")})
    if sp and sp["level"]:
        k.append({"who": "키쟈", "name": "지지 반복 횟수", "status": "bad" if sp["touches"] >= WEAK_TOUCHES else ("good" if sp["touches"] <= 2 else "warn"),
                  "detail": f"${sp['level']:.4f} 를 60일 안 {sp['touches']}차 지지" + (" — 반복될수록 약해짐 ❗" if sp["touches"] >= WEAK_TOUCHES else "")})
    if md:
        gc = md["gc_days"]
        k.append({"who": "키쟈", "name": "일봉 5/20 골크", "status": "good" if gc is not None and gc <= 5 else ("bad" if md["dc_days"] is not None and md["dc_days"] <= 5 else "none"),
                  "detail": (f"골든크로스 {gc}일 전" if gc is not None else (f"데드크로스 {md['dc_days']}일 전" if md["dc_days"] is not None else "15일 안 교차 없음")) + (f" · 20일선 기울기 {md['slope20']:+.1f}%" if md["slope20"] is not None else "")})
        k.append({"who": "키쟈", "name": "일봉 50·200·1년선", "status": "good" if md["above"][50] and md["above"].get(200, True) else ("warn" if md["above"][50] else "bad"),
                  "detail": " · ".join(f"{n}일선 {'위' if md['above'][n] else '아래'}" for n in (50, 100, 200, 250) if md[f"ma{n}"]) or "자료 부족"})
    if m60:
        k.append({"who": "키쟈", "name": "60분봉 5·20 정배열", "status": _st(m60["aligned"]) if m60["ma50"] else "none", "detail": "정배열 확장(시세 확장)" if m60["aligned"] else ("20선 위·우상향(라인 살아 있음)" if m60["alive"] else "정배열 아님")})
        k.append({"who": "키쟈", "name": "60분봉 200선", "status": "good" if m60["break200"] else ("warn" if m60["ma200"] and m60["dist200"] is not None and abs(m60["dist200"]) < 3 else ("none" if not m60["ma200"] else "bad")),
                  "detail": (f"돌파 뒤 {m60['break200']}봉째 지지" if m60["break200"] else (f"200선 대비 {m60['dist200']:+.1f}%" if m60["dist200"] is not None else "자료 부족(60분봉 200봉 필요)"))})
    if m5:
        k.append({"who": "키쟈", "name": "5분봉 이평", "status": "bad" if m5["broken"] else ("good" if m5["converged"] or m5["riding5"] else "none"),
                  "detail": ("5·20 모두 꺾임 — 투매 신호 ❗" if m5["broken"] else ("5·20·60 수렴(힘 응축)" if m5["converged"] else ("5일선 타고 상승 중" if m5["riding5"] else "특이 없음"))) + (f" · 폭 {m5['converge_pct']:.1f}%" if m5["converge_pct"] is not None else "")})
        k.append({"who": "키쟈", "name": "5분봉 200선·VWAP", "status": "good" if m5["dist200"] is not None and -2 <= m5["dist200"] <= 3 else "none",
                  "detail": (f"200선 대비 {m5['dist200']:+.1f}%" if m5["dist200"] is not None else "200선 자료 부족") + (f" · VWAP 대비 {m5['dist_vwap']:+.1f}%" if m5["dist_vwap"] is not None else "")})
    if sar:
        k.append({"who": "키쟈", "name": "파라볼릭(일봉)", "status": "good" if sar["pos"] == "below" else ("warn" if sar["eta"] and sar["eta"] <= 3 else "bad"),
                  "detail": ("점이 아래(매수 우위)" if sar["pos"] == "below" else "점이 위(매도 우위)") + (f" · 가격 그대로면 {sar['eta']}봉 뒤 접촉" if sar["eta"] else "")})
    if bb:
        k.append({"who": "키쟈", "name": "볼린저 수축", "status": "good" if bb["squeeze"] else "none", "detail": f"폭 {bb['width_pct']:.1f}%(하위 {bb['pctile']:.0f}%)" + (" — 수축, 튈 준비" if bb["squeeze"] else "")})
    if md and md["cross50_200"]:
        k.append({"who": "ANO", "name": "50/200 SMA", "status": "good" if md["cross50_200"] == "골든" else "bad",
                  "detail": f"{md['cross50_200']}크로스" + (f" {md['cross50_200_days']}일 전" if md.get("cross50_200_days") is not None else "") + (f" · 이격 {md['gap50_200']:+.0f}%" if md["gap50_200"] is not None else "")})
    if dv:
        k.append({"who": "ANO", "name": "다이버전스", "status": "good" if dv["bull"] else ("bad" if dv["bear"] else "none"),
                  "detail": ("주가↓ 거래량↓ MACD↑ = 매도세 약화" if dv["bull"] else ("고점 높이는데 거래량↓ = 하락 다이버전스 ❗" if dv["bear"] else f"20일 {dv['price_chg']:+.0f}% · 거래량 비 {dv['vol_ratio']:.2f}" if dv["vol_ratio"] else "특이 없음"))})
    if cd:
        k.append({"who": "ANO", "name": "캔들", "status": "bad" if cd["top"] else ("good" if cd["hammer"] or cd["turn"] else ("warn" if cd["turn_waiting"] else "none")),
                  "detail": ("고점 'ㅗ' 윗꼬리 — 매도 자리" if cd["top"] else ("긴 밑꼬리 — 매수 자리" if cd["hammer"] else (f"{cd['down_run']}일 연속 하락 뒤 전일 시가 돌파 — 전환" if cd["turn"] else (f"{cd['down_run']}일 연속 하락 — 전일 시가 돌파 대기" if cd["turn_waiting"] else "특이 없음"))))})
    if a.get("turnover") is not None:
        tv = a["turnover"]
        k.append({"who": "ANO", "name": "유통주식 회전율", "status": "warn" if tv >= 1.0 else "none", "detail": f"오늘 거래량 = 유통주식의 {tv:.2f}배" + (" — 1바퀴 넘음(수익실현 끝 or 매물대 밀집, 거래량 추이로 구분)" if tv >= 1 else "")})
    return k


def signals(a: dict) -> list[dict]:
    """신호 코드 목록 [{code, name, dir, note}] — SIGNALS 표 참고."""
    out = []
    r, L, m60, m5, md, sar, cd, bb, b = (a.get(k) for k in ("retrace", "levels", "ma_60", "ma_5", "ma_d", "sar_d", "candle", "bb", "base"))
    px = a["px"]

    def add(code, note):
        out.append({"code": code, "name": SIGNALS[code][0], "dir": SIGNALS[code][1], "note": note})
    if b and r and L:
        trigger = (m5 and (m5["converged"] or m5["riding5"])) or (sar and sar["eta"] and sar["eta"] <= 3) or (cd and cd["hammer"]) or (bb and bb["squeeze"])
        if b["days_since"] >= 2 and r["zone"] in ("무릎~허리",) and r["above_life"] and trigger:
            add("pullback", f"{r['zone']} · 허리 ${L['허리']:.4f} · 무릎 ${L['무릎']:.4f} · 유형 {r['type']}")
        if r["stage"] == 1 and r["above_life"]:
            add("retrace1", f"머리 대비 {r['dd_pct']:+.0f}% · 반등선 ${r['r1']:.4f}")
        if not r["above_life"] and b["days_since"] >= 1 and a.get("prev_px") and a["prev_px"] >= L["생명선"]:   # 오늘 처음 깬 날만(이미 밑에 있는 종목은 매일 울리지 않게)
            add("life_break", f"생명선 ${L['생명선']:.4f} 아래 ${px:.4f}")
        elif not r["above_waist"] and b["days_since"] >= 1 and a.get("prev_px") and a["prev_px"] >= L["허리"]:   # 어제는 허리 위 → 오늘 아래
            add("waist_break", f"허리 ${L['허리']:.4f} 아래 ${px:.4f}")
    if m60 and m60["break200"] and m60["break200"] <= 10:
        add("h60_200", f"200선 ${m60['ma200']:.4f} 돌파 뒤 {m60['break200']}봉")
    if md and md["gc_days"] is not None and md["gc_days"] <= 3:
        add("gc520", f"{md['gc_days']}일 전 골크" + (" · 50일선 위" if md["above"][50] else " · 50일선 아래(세력 주도 돌파 필요)"))
    if cd and cd["turn"]:
        add("turn3", f"{cd['down_run']}일 연속 하락 뒤 전환")
    if cd and cd["top"]:
        add("top_candle", f"윗꼬리 {cd['upper_pct']:.1f}%")
    if sar and sar["pos"] == "above" and sar["eta"] and sar["eta"] <= 2:
        add("sar_due", f"{sar['eta']}봉 뒤 접촉 · 점 ${sar['value']:.4f}")
    if m5 and m5["broken"]:
        add("m5_break", f"5분 5선 ${m5['ma5']:.4f} · 20선 ${m5['ma20']:.4f} 아래")
    return out


def verdict(a: dict) -> str:
    """한 줄 판독(화면·알림용)."""
    parts = []
    r, L, b = a.get("retrace"), a.get("levels"), a.get("base")
    if b and r and L:
        parts.append(f"기준봉 {b['date']} 뒤 {r['zone']}(머리 대비 {r['dd_pct']:+.0f}%)" + ("" if r["above_life"] else " · 생명선 이탈 ❗"))
    else:
        parts.append("급등 마디 없음(기준봉 없음)")
    md = a.get("ma_d")
    if md:
        if md["gc_days"] is not None and md["gc_days"] <= 5:
            parts.append(f"일봉 5/20 골크 {md['gc_days']}일 전")
        parts.append("50일선 " + ("위" if md["above"][50] else "아래"))
    m60 = a.get("ma_60")
    if m60:
        parts.append("60분 정배열" if m60["aligned"] else ("60분 200선 지지" if m60["break200"] else "60분 추세 약함"))
    m5 = a.get("ma_5")
    if m5:
        parts.append("5분 5·20 꺾임 ❗" if m5["broken"] else ("5분 이평 수렴" if m5["converged"] else ""))
    pr = a.get("prof")
    if pr and pr["res"]:
        parts.append(f"위 매물 ${pr['res']:.2f}(+{(pr['res'] / a['px'] - 1) * 100:.0f}%)")
    return " · ".join(p for p in parts if p)


def chip(a: dict | None) -> tuple[str, str] | None:
    """🏢 종목 헤더용 짧은 칩 (문구, 색)."""
    if not a or not a.get("retrace") or not a.get("levels"):
        return None
    r, L = a["retrace"], a["levels"]
    if not r["above_life"]:
        return (f"📐 생명선 ${L['생명선']:.2f} 이탈", "red")
    col = "green" if r["above_waist"] else ("orange" if r["zone"] == "무릎~허리" else "red")
    return (f"📐 {r['zone']} · 허리 ${L['허리']:.2f}({(a['px'] / L['허리'] - 1) * 100:+.0f}%)", col)


# ---------------------------------------------------------------- 자료 받기(인터넷) · 기록
def fetch_intraday(tickers: list[str], want60: bool = True, want5: bool = True) -> tuple[dict, dict]:
    """60분봉(60일) · 5분봉(5일, 시간외 포함) — 야후 무료. 실패하면 빈 dict."""
    import market
    h60 = market._download(list(tickers), chunk_size=25, period="60d", interval="60m") if want60 and tickers else {}
    m5 = market._download(list(tickers), chunk_size=25, period="5d", interval="5m", prepost=True) if want5 and tickers else {}
    return h60 or {}, m5 or {}


def ensure(conn) -> None:
    conn.execute(DDL)


def record(conn, day: str, ticker: str, sigs: list[dict], price: float, only: tuple | None = None) -> int:
    """신호를 하루 한 번씩 기록(같은 날·같은 종류는 한 번). 반환 새로 기록한 수."""
    ensure(conn)
    n = 0
    now = db.utcnow_iso()
    for s in sigs:
        if only and s["code"] not in only:
            continue
        cur = conn.execute("INSERT OR IGNORE INTO chart_signals VALUES (?,?,?,?,?,?)", (day, ticker.upper(), s["code"], float(price), s.get("note"), now))
        n += cur.rowcount
    return n


def scan(conn, prices: dict, tickers: list[str], day: str | None = None, h60: dict | None = None, m5: dict | None = None, floats: dict | None = None,
         only: tuple | None = MORNING_CODES) -> list[dict]:
    """여러 종목 분석 + 신호 기록(only 에 든 종류만, 기본 = 아침용). prices = {티커: 일봉}. 반환 [{ticker, verdict, signals, chip}] (기록한 신호 있는 것만)."""
    day = day or date.today().isoformat()
    out = []
    for t in tickers:
        try:
            a = analyze(prices.get(t), (h60 or {}).get(t), (m5 or {}).get(t), (floats or {}).get(t))
        except Exception:  # noqa: BLE001
            a = None
        if not a:
            continue
        sigs = [s for s in a["signals"] if only is None or s["code"] in only]
        if not sigs:
            continue
        record(conn, day, t, sigs, a["px"])
        out.append({"ticker": t, "verdict": a["verdict"], "signals": sigs, "chip": chip(a), "px": a["px"]})
    conn.commit()
    return out


def recent(conn, days: int = 7, kinds: tuple | None = None) -> pd.DataFrame:
    ensure(conn)
    q = "SELECT date, ticker, kind, price, note FROM chart_signals WHERE date >= date('now', ?)"
    rows = conn.execute(q, (f"-{days} day",)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows], columns=["date", "ticker", "kind", "price", "note"])
    if kinds is not None and not df.empty:
        df = df[df["kind"].isin(kinds)]
    if not df.empty:
        df["name"] = df["kind"].map(lambda k: SIGNALS.get(k, (k,))[0])
    return df.sort_values(["date", "ticker"], ascending=[False, True]) if not df.empty else df


def candidates(conn, limit: int = 80) -> list[str]:
    """아침 점검 대상: 종합 순위 상위 · 급상승 · 저금통 · 가상매매 보유 · 워치."""
    out: list[str] = []

    def add(xs):
        for x in xs:
            if x and x not in out:
                out.append(x.upper())
    try:
        add(r[0] for r in conn.execute("SELECT ticker FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots) ORDER BY win_score DESC LIMIT 40"))
    except Exception:  # noqa: BLE001
        pass
    try:
        import piggy
        add(piggy.tickers_all())
    except Exception:  # noqa: BLE001
        pass
    try:
        import papertrade
        add(papertrade.open_tickers())
    except Exception:  # noqa: BLE001
        pass
    try:
        import mover
        add(r["ticker"] for r in mover.latest(conn, "up")[1][:20])
    except Exception:  # noqa: BLE001
        pass
    try:
        import watch
        add(watch.scanner_priority())
    except Exception:  # noqa: BLE001
        pass
    try:
        import tradable
        act = tradable.active()
        if act:
            out = [t for t in out if t in act]
    except Exception:  # noqa: BLE001
        pass
    return out[:limit]


def morning(out=print, limit: int = 80, fetch=None) -> dict:
    """아침 작업: 후보군 일봉·60분·5분 받아 분석 → 신호 기록 → 요약. fetch 로 가짜 자료 주입 가능(테스트)."""
    import market
    with closing(db.connect()) as conn:
        ensure(conn)
        ticks = candidates(conn, limit)
        if not ticks:
            out("📐 차트 관점: 후보 없음")
            return {"n": 0, "signals": []}
        if fetch:
            prices, h60, m5 = fetch(ticks)
        else:
            prices = market.download_daily(ticks, period="1y")
            h60, m5 = fetch_intraday(ticks)
        floats = {}
        try:
            import chartex
            for t in ticks:
                f = chartex.float_of(conn, t)
                if f and f.get("shares_float"):
                    floats[t] = f["shares_float"]
        except Exception:  # noqa: BLE001
            pass
        res = scan(conn, prices, ticks, h60=h60, m5=m5, floats=floats)
    n_sig = sum(len(r["signals"]) for r in res)
    out(f"📐 차트 관점: {len(ticks)}종목 점검 · 신호 {n_sig}건({len(res)}종목)")
    for r in res[:30]:
        out("  " + r["ticker"] + " · " + " / ".join(s["name"] for s in r["signals"]) + " · " + r["verdict"])
    return {"n": len(ticks), "signals": res}


# ---------------------------------------------------------------- 스캐너(장중) 경고 · 타임머신 깃발
LIVE_CODES = ("m5_break", "life_break", "waist_break", "pullback", "h60_200")


def live_check(conn, daily: dict, m5: dict, tickers: list[str], h60: dict | None = None, send=None, day: str | None = None) -> list[str]:
    """스캐너용: 보유·저금통 종목의 5분봉 꺾임 · 생명선/허리 이탈 · 눌림 타점을 보고 처음 난 것만 텔레그램. 반환 보낸 메시지들."""
    import config
    day = day or date.today().isoformat()
    sent = []
    for t in tickers:
        try:
            a = analyze(daily.get(t), (h60 or {}).get(t), m5.get(t))
        except Exception:  # noqa: BLE001
            a = None
        if not a or not a["signals"]:
            continue
        ensure(conn)
        now = db.utcnow_iso()
        for s in a["signals"]:
            if s["code"] not in LIVE_CODES:
                continue
            cur = conn.execute("INSERT OR IGNORE INTO chart_signals VALUES (?,?,?,?,?,?)", (day, t.upper(), s["code"], float(a["px"]), s.get("note"), now))
            conn.commit()   # 2026-10-30: 텔레그램 보내기 전에 확정(전송하는 동안 쓰기 잠금을 쥐지 않게)
            if cur.rowcount and getattr(config, "CHART_ALERTS", True):
                kind = "경고" if s["dir"] < 0 else "참고"
                msg = f"{s['name']} — {t} ${a['px']:.4f}\n{s.get('note') or ''}\n{a['verdict']} (스승 관점 {kind} · 매수·매도 권유 아님)"
                try:
                    (send or _send)(msg)
                    sent.append(msg)
                except Exception:  # noqa: BLE001
                    pass
    conn.commit()
    return sent


def _send(msg: str) -> None:
    import notify
    notify.send_telegram(msg)


def tm_flags(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """🕰 타임머신용 날짜별 깃발(그날까지 자료만): gc3 = 일봉 5/20 골든크로스 3일 안 · pb = 기준봉 뒤 무릎~허리 눌림(생명선 위, 40일 안)."""
    n = len(c)
    gc3, pb = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    if n < 25:
        return gc3, pb
    s = pd.Series(c)
    diff = (s.rolling(5).mean() - s.rolling(20).mean()).to_numpy()
    last_gc = -99
    for i in range(1, n):
        if not (np.isnan(diff[i - 1]) or np.isnan(diff[i])) and diff[i - 1] <= 0 < diff[i]:
            last_gc = i
        gc3[i] = 0 <= i - last_gc <= 3
    v20 = pd.Series(v).shift(1).rolling(20, min_periods=10).median().to_numpy()
    anchor, head = None, 0.0
    for i in range(20, n):
        is_c = v20[i] > 0 and v[i] >= BASE_VOL_X * v20[i] and c[i - 1] > 0 and (h[i] / c[i - 1] - 1) >= BASE_GAIN
        if is_c and (anchor is None or i - anchor > 3):     # 3일 안에 연달아 터지면 같은 마디
            anchor, head = i, h[i]
        elif is_c:
            head = max(head, h[i])
        if anchor is None:
            continue
        if i - anchor <= HEAD_DAYS:
            head = max(head, h[i])
        foot, life = min(l[anchor], o[anchor]), o[anchor]
        if head <= foot or i - anchor < 2 or i - anchor > 40:
            continue
        knee, waist = foot + 0.25 * (head - foot), foot + 0.5 * (head - foot)
        pb[i] = bool(knee <= c[i] < waist and c[i] >= life)
    return gc3, pb


if __name__ == "__main__":
    morning()
