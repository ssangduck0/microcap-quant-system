"""📈 보조지표 — RSI(바닥 반등) · MACD(골든·데드크로스) · 이동평균(2~3개) · 일목균형표(구름 두께 %) 계산과 신호 판정."""
from __future__ import annotations

import pandas as pd

DEFAULTS = {"ma": [5, 20, 60], "rsi_n": 14, "rsi_low": 30, "macd": [12, 26, 9], "ichi": [9, 26, 52], "cloud_thin": 3.0, "cross_days": 5, "lookback": 180}


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).where(ad != 0, 100.0)


def macd(c: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.DataFrame:
    m = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    s = m.ewm(span=sig, adjust=False).mean()
    return pd.DataFrame({"macd": m, "signal": s, "hist": m - s})


def ichimoku(df: pd.DataFrame, t: int = 9, k: int = 26, s: int = 52) -> pd.DataFrame:
    h, l = df["High"], df["Low"]
    ten = (h.rolling(t).max() + l.rolling(t).min()) / 2
    kij = (h.rolling(k).max() + l.rolling(k).min()) / 2
    a = ((ten + kij) / 2).shift(k)
    b = ((h.rolling(s).max() + l.rolling(s).min()) / 2).shift(k)
    return pd.DataFrame({"tenkan": ten, "kijun": kij, "span_a": a, "span_b": b, "chikou": df["Close"].shift(-k)})


def compute(df: pd.DataFrame, p: dict | None = None) -> pd.DataFrame:
    p = {**DEFAULTS, **(p or {})}
    out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    for n in p["ma"]:
        out[f"MA{n}"] = out["Close"].rolling(int(n)).mean()
    out["RSI"] = rsi(out["Close"], int(p["rsi_n"]))
    out = out.join(macd(out["Close"], *map(int, p["macd"])))
    out = out.join(ichimoku(out, *map(int, p["ichi"])))
    out["cloud_thick_pct"] = (out["span_a"] - out["span_b"]).abs() / out["Close"] * 100
    return out


def signals(x: pd.DataFrame, p: dict | None = None) -> dict:
    """마지막 날 기준 신호. 반환: {"items": [(이름, 설명, 좋음/나쁨/중립)], "values": {...}}"""
    p = {**DEFAULTS, **(p or {})}
    x = x.dropna(subset=["Close"])
    if len(x) < 30:
        return {"items": [], "values": {}}
    last, items, k = x.iloc[-1], [], int(p["cross_days"])
    r = x["RSI"].dropna()
    if len(r) > 5:
        low5 = r.tail(5).min()
        if low5 < p["rsi_low"] and r.iloc[-1] > low5 + 2:
            items.append(("RSI 바닥 반등", f"최근 5일 최저 {low5:.0f}(기준 {p['rsi_low']}) → 지금 {r.iloc[-1]:.0f}", "good"))
        elif r.iloc[-1] < p["rsi_low"]:
            items.append(("RSI 과매도", f"RSI {r.iloc[-1]:.0f} — 바닥 확인 전(반등 아직)", "neutral"))
        elif r.iloc[-1] > 70:
            items.append(("RSI 과매수", f"RSI {r.iloc[-1]:.0f}", "bad"))
    d = (x["macd"] - x["signal"]).dropna()
    cross_up = [i for i in range(max(1, len(d) - k), len(d)) if d.iloc[i - 1] <= 0 < d.iloc[i]]
    cross_dn = [i for i in range(max(1, len(d) - k), len(d)) if d.iloc[i - 1] >= 0 > d.iloc[i]]
    if cross_up:
        ri = x["RSI"].reindex(d.index).iloc[cross_up[-1]]
        items.append(("MACD 골든크로스" + (" + RSI 저점" if ri < 50 else ""), f"{d.index[cross_up[-1]]:%m-%d} · 그날 RSI {ri:.0f}", "good"))
    if cross_dn:
        items.append(("MACD 데드크로스", f"{d.index[cross_dn[-1]]:%m-%d}", "bad"))
    mas = [f"MA{n}" for n in p["ma"] if f"MA{n}" in x and pd.notna(last.get(f"MA{n}"))]
    if len(mas) >= 2:
        vals = [last[m] for m in mas]
        if all(a > b for a, b in zip(vals, vals[1:])) and last["Close"] > vals[0]:
            items.append(("이평선 정배열", " > ".join(mas) + " · 주가가 가장 짧은 선 위", "good"))
        elif all(a < b for a, b in zip(vals, vals[1:])):
            items.append(("이평선 역배열", " < ".join(mas), "bad"))
    a, b, th = last.get("span_a"), last.get("span_b"), last.get("cloud_thick_pct")
    if pd.notna(a) and pd.notna(b):
        top, bot = max(a, b), min(a, b)
        pos = "구름 위" if last["Close"] > top else ("구름 아래" if last["Close"] < bot else "구름 안")
        thin = pd.notna(th) and th <= p["cloud_thin"]
        items.append((f"일목 {pos}", f"구름 두께 {th:.1f}%(기준 {p['cloud_thin']}% 이하 = 얇음)" + (" — 얇아서 돌파·이탈이 쉬움" if thin else ""),
                      "good" if pos == "구름 위" else ("bad" if pos == "구름 아래" and not thin else "neutral")))
    return {"items": items, "values": {"rsi": None if r.empty else float(r.iloc[-1]), "cloud_thick_pct": None if pd.isna(th) else float(th),
                                       "macd_hist": float(d.iloc[-1]) if len(d) else None}}
