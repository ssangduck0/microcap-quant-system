"""시장 데이터(yfinance). 종목마다 따로 호출하지 않고 묶음(batch)으로 받아 요청 수와 속도 문제를 줄입니다."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import yfinance as yf

log = logging.getLogger("market")

EXCHANGE_MAP = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NASDAQ": "NASDAQ",
                "ASE": "NYSE American", "NYQ": "NYSE", "PCX": "NYSE Arca", "BTS": "Cboe BZX"}
CHUNK = 40



def et_trade_date(ts) -> str:
    """봉 시각 → 미국 거래일(YYYY-MM-DD). 시간대가 붙어 있으면 동부시간으로 바꾸고, 토·일이 나오면 직전 금요일."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("America/New_York")
    d = t.date()
    while d.weekday() >= 5:  # 5=토, 6=일
        d = d - pd.Timedelta(days=1)
    return d.isoformat()

def _split(df: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if df is None or df.empty:
        return out
    if isinstance(df.columns, pd.MultiIndex):
        level0 = set(df.columns.get_level_values(0))
        for t in tickers:
            if t in level0:
                sub = df[t].dropna(how="all")
                if not sub.empty:
                    out[t] = sub
    elif len(tickers) == 1:
        out[tickers[0]] = df.dropna(how="all")
    return out


def _download(tickers: list[str], chunk_size: int = CHUNK, **kw) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            df = yf.download(chunk, group_by="ticker", progress=False, threads=True, auto_adjust=False, **kw)
            result.update(_split(df, chunk))
        except Exception as e:  # noqa: BLE001
            log.warning("yfinance 다운로드 실패 (%s ...): %s", chunk[:3], e)
    return result


def download_daily(tickers: list[str], period: str = "3mo", chunk: int = CHUNK) -> dict[str, pd.DataFrame]:
    return _download(tickers, chunk_size=chunk, period=period, interval="1d")


def download_intraday(tickers: list[str]) -> dict[str, pd.DataFrame]:
    return _download(tickers, period="1d", interval="1m", prepost=True)


def fetch_splits(ticker: str) -> list[dict]:
    out = []
    for d, r in yf.Ticker(ticker).splits.items():
        r = float(r)
        if r <= 0 or r == 1:
            continue
        text = f"1:{round(1 / r)} 역분할" if r < 1 else f"{r:g}:1 액면분할"
        out.append({"date": pd.Timestamp(d).strftime("%Y-%m-%d"), "ratio": r, "text": text})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def quick_screen(daily: pd.DataFrame) -> dict | None:
    """1단계(일봉만으로 하는 싼 필터)에 쓰는 요약값."""
    d = daily.dropna(subset=["Close"])
    if len(d) < 15:
        return None
    price = float(d["Close"].iloc[-1])
    high20 = float(d["High"].tail(20).max())
    if high20 <= 0 or price <= 0:
        return None
    prior = d.iloc[:-1].tail(20)
    avg_vol = float(prior["Volume"].mean()) if not prior.empty else 0.0
    last_vol = float(d["Volume"].iloc[-1])
    prev = float(d["Close"].iloc[-2]) if len(d) >= 2 else 0.0
    return {
        "price": price, "last_date": pd.Timestamp(d.index[-1]).strftime("%Y-%m-%d"),
        "day_chg_pct": (price / prev - 1) * 100.0 if prev > 0 else None,
        "drawdown_pct": (price - high20) / high20 * 100.0,
        "avg_dollar_vol": float((prior["Close"] * prior["Volume"]).mean()) if not prior.empty else 0.0,
        "vol_mult": last_vol / avg_vol if avg_vol > 0 else 0.0,
    }


def fetch_fundamentals(ticker: str) -> dict | None:
    """느린 호출이므로 호출하는 쪽에서 DB에 24시간 캐시합니다."""
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:  # noqa: BLE001
        log.warning("%s info 조회 실패: %s", ticker, e)
        return None
    code = info.get("exchange")
    return {
        "name": info.get("shortName"),
        "exchange": EXCHANGE_MAP.get(code, code),
        "float_shares": info.get("floatShares"),
        "shares_out": info.get("sharesOutstanding"),
        "market_cap": info.get("marketCap"),
    }


def atr14(daily: pd.DataFrame) -> float | None:
    if len(daily) < 15:
        return None
    prev_close = daily["Close"].shift(1)
    tr = pd.concat([daily["High"] - daily["Low"], (daily["High"] - prev_close).abs(),
                    (daily["Low"] - prev_close).abs()], axis=1).max(axis=1)
    v = tr.tail(14).mean()
    return None if pd.isna(v) else float(v)


def buy_pressure(intra: pd.DataFrame | None) -> float | None:
    """1분봉 종가 방향으로 거래량을 상승/하락으로 나눈 '매수체결 비중(%)' 추정치 (0~100, 보정 없음).

    실제 체결강도(틱 단위 매수/매도 체결량)가 아니라 틱룰 기반 근사치입니다. 직전 봉과 같은 가격이면 제외합니다.
    """
    if intra is None or len(intra) < 5:
        return None
    close = intra["Close"].to_numpy(dtype=float)
    vol = intra["Volume"].fillna(0).to_numpy(dtype=float)
    diff = np.diff(close)
    v = vol[1:]
    up, down = v[diff > 0].sum(), v[diff < 0].sum()
    if up + down <= 0:
        return None
    return float(up / (up + down) * 100.0)


AUTO = object()  # compute_metrics(day_volume=AUTO): 분봉(없으면 일봉)에서 거래량을 직접 계산


def compute_metrics(daily: pd.DataFrame, intra: pd.DataFrame | None, day_volume=AUTO) -> dict | None:
    """day_volume: AUTO=분봉 합 사용 / 숫자=그 값 사용 / None=거래량 확인 불가(배수를 계산하지 않음)"""
    daily = daily.dropna(subset=["Close"])
    if daily.empty:
        return None
    has_intra = intra is not None and not intra.empty and intra["Close"].notna().any()
    if has_intra:
        intra = intra.dropna(subset=["Close"])
        price = float(intra["Close"].iloc[-1])
        trade_date = et_trade_date(intra.index[-1])  # 미국 동부시간 기준 거래일(UTC 로 오면 금요일 시간외가 토요일로 찍히던 문제)
        day_vol = float(intra["Volume"].fillna(0).sum())
    else:
        price = float(daily["Close"].iloc[-1])
        trade_date = et_trade_date(daily.index[-1])
        day_vol = float(daily["Volume"].iloc[-1])

    if day_volume is not AUTO:
        day_vol = day_volume

    last20 = daily.tail(20)
    high_20d = float(last20["High"].max())
    low_20d = float(last20["Low"].min())
    if has_intra:
        high_20d = max(high_20d, float(intra["High"].max()))
        low_20d = min(low_20d, float(intra["Low"].min()))

    prior = daily[daily.index.strftime("%Y-%m-%d") < trade_date].tail(20)  # 오늘 제외 직전 20거래일
    prev_close = float(prior["Close"].iloc[-1]) if not prior.empty else None  # 직전 거래일 종가
    gap = rng_pct = close_loc = None
    if has_intra:  # 오늘 정규장(동부시간 09:30~16:00) 봉만으로 시가·고가·저가를 계산 (과거 사건의 일봉과 같은 정의)
        idx = intra.index.tz_convert("America/New_York") if intra.index.tz is not None else intra.index
        tmin = idx.hour * 60 + idx.minute
        reg = intra[(tmin >= 570) & (tmin < 960)]
        if len(reg) >= 3:
            r_o, r_h, r_l = float(reg["Open"].iloc[0]), float(reg["High"].max()), float(reg["Low"].min())
            gap = (r_o / prev_close - 1) * 100.0 if prev_close else None
            rng_pct = (r_h / r_l - 1) * 100.0 if r_l > 0 else None
            close_loc = float(min(1.0, max(0.0, (price - r_l) / (r_h - r_l)))) if r_h > r_l else None
    prior_rng = None
    if len(prior) >= 10:
        pcl = prior["Close"].where(prior["Close"] > 0)
        prior_rng = float((((prior["High"] - prior["Low"]) / pcl) * 100).mean())
    pre_dd = avg_dollar = None
    if len(prior) >= 10 and prev_close:  # 과거 사건(cases.py)과 같은 정의: 직전 20거래일 기준
        ph = float(prior["High"].max())
        pre_dd = (prev_close / ph - 1) * 100.0 if ph > 0 else None
        avg_dollar = float((prior["Close"] * prior["Volume"]).mean())
    avg_vol = float(prior["Volume"].mean()) if not prior.empty else 0.0
    vol_mult = day_vol / avg_vol if (day_vol is not None and avg_vol > 0) else None  # 하루 누적 거래량 / 20일 평균 일거래량
    if high_20d <= 0:
        return None
    return {
        "trade_date": trade_date, "price": price, "high_20d": high_20d, "low_20d": low_20d,
        "drawdown_pct": (price - high_20d) / high_20d * 100.0, "volume_mult": vol_mult,
        "pre_dd_pct": pre_dd, "avg_dollar_vol": avg_dollar,
        "gap_pct": gap, "range_pct": rng_pct, "close_loc": close_loc, "prior_range_pct": prior_rng,
        "prev_close": prev_close, "day_change_pct": (price / prev_close - 1) * 100.0 if prev_close else None,
        "buy_pressure": buy_pressure(intra if has_intra else None), "atr14": atr14(daily),
    }
