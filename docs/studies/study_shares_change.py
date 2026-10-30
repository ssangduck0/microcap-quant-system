"""🐷 ⑥ 규칙 검증: SEC 분기 표지로 잰 '직전 분기 대비 주식수 변동률' 과 그 보고서 제출일 **이후** 20·60거래일 수익률의 관계.
사용: python study_shares_change.py <dir> <shares_hist.csv> [out.md]
  <dir>/yahoo_px.pkl : {ticker: DataFrame[Close, Volume, Stock Splits]}  (yahoo_dl.py)
컨닝 금지: 진입일 = 표지가 실린 보고서 제출일(filed) 이후 첫 거래일. 분할은 야후 Stock Splits(새/옛 비율)로 옛 표지에 반영."""
import os, sys, pickle
from datetime import date
import numpy as np
import pandas as pd

MIN_GAP, MAX_GAP = 75, 200          # shares.change 와 같은 '직전 분기' 정의
H1, H2 = 20, 60                     # 이후 거래일
BUCKETS = [(-np.inf, 0, "≤0%"), (0, 10, "0~10%"), (10, 20, "10~20%"), (20, 50, "20~50%"), (50, 100, "50~100%"), (100, np.inf, ">100%")]


def build_pairs(hist: pd.DataFrame, px: dict) -> pd.DataFrame:
    """종목별 표지 쌍(d0→d1) + 분할 반영 변동률 + 이후 수익률. 역분할 누락 의심(반영 뒤에도 ≤-50%)은 제외."""
    rows, dropped = [], {"no_px": 0, "rs_missing": 0, "no_entry": 0}
    for t, g in hist.groupby("ticker"):
        d = px.get(t)
        if d is None or len(d) < 80:
            dropped["no_px"] += 1
            continue
        d = d[~d.index.duplicated()].sort_index()
        close = d["Close"].astype(float)
        idx = close.index.tz_localize(None) if getattr(close.index, "tz", None) is not None else close.index
        close.index = idx
        splits = d["Stock Splits"].astype(float)
        splits = splits[splits > 0]
        splits.index = idx[d["Stock Splits"].astype(float).values > 0]
        g = g.sort_values("asof").drop_duplicates("asof")
        pts = g.to_dict("records")
        for i in range(1, len(pts)):
            p1 = pts[i]
            d1 = pd.Timestamp(p1["asof"])
            prev = [p for p in pts[:i] if MIN_GAP <= (d1 - pd.Timestamp(p["asof"])).days <= MAX_GAP]
            if not prev:
                continue
            p0 = prev[-1]
            d0 = pd.Timestamp(p0["asof"])
            s0, s1 = float(p0["shares"] or 0), float(p1["shares"] or 0)
            if s0 <= 0 or s1 <= 0:
                continue
            sp = splits[(splits.index > d0) & (splits.index <= d1)]
            mult = float(np.prod(sp.values)) if len(sp) else 1.0
            pct = (s1 / (s0 * mult) - 1) * 100
            if pct <= -50:
                dropped["rs_missing"] += 1
                continue
            filed = pd.Timestamp(p1["filed"]) if isinstance(p1.get("filed"), str) and p1["filed"] else d1 + pd.Timedelta(days=5)
            entry = max(filed, d1)
            pos = close.index.searchsorted(entry)
            if pos >= len(close) - H1:
                dropped["no_entry"] += 1
                continue
            c0 = close.iloc[pos]
            if not c0 or c0 <= 0:
                continue
            r20 = close.iloc[pos + H1] / c0 - 1
            seg60 = close.iloc[pos + 1: pos + H2 + 1]
            r60 = (close.iloc[pos + H2] / c0 - 1) if pos + H2 < len(close) else np.nan
            # 야후 종가는 '그 뒤 분할' 까지 반영된 값(2020년 $0.5 가 뒤에 1:600 병합되면 $300 으로 보임) → 당시 실제 가격 = 종가 × 그 뒤 분할 비율의 곱
            after = splits[splits.index > close.index[pos]]
            c0_raw = c0 * float(np.prod(after.values)) if len(after) else c0
            rows.append({"ticker": t, "d0": d0.date(), "d1": d1.date(), "entry": close.index[pos].date(), "form": p1.get("form"),
                         "pct": pct, "splits": len(sp), "c0": c0, "c0_raw": c0_raw, "r20": r20 * 100, "r60": r60 * 100,
                         "max60": (seg60.max() / c0 - 1) * 100 if len(seg60) else np.nan,
                         "min60": (seg60.min() / c0 - 1) * 100 if len(seg60) else np.nan})
    df = pd.DataFrame(rows)
    glitch = (df["r60"] > 5000) | (df["max60"] > 10000)      # 60일에 50배·고가 100배 = 야후 분할 미반영 오류(PPCB 4,166,566% 등)
    dropped["glitch"] = int(glitch.sum())
    df = df[~glitch].reset_index(drop=True)
    df.attrs["dropped"] = dropped
    return df


def bucket(pct: float) -> str:
    for lo, hi, name in BUCKETS:
        if lo < pct <= hi if lo != -np.inf else pct <= hi:
            return name
    return "?"


def tmean(s: pd.Series, cut: float = 0.05) -> float:
    """상·하위 cut 비율을 깎은 평균(극단값 영향 제거)."""
    s = s.dropna().sort_values()
    k = int(len(s) * cut)
    return float(s.iloc[k: len(s) - k].mean()) if len(s) > 2 * k else float(s.mean())


def table_by_bucket(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(b=df["pct"].map(bucket))
    order = [b[2] for b in BUCKETS]
    out = df.groupby("b").agg(n=("pct", "size"), tickers=("ticker", "nunique"),
                               med20=("r20", "median"), med60=("r60", "median"), tmean60=("r60", tmean),
                               spike30=("max60", lambda s: (s >= 30).mean() * 100), crash30=("min60", lambda s: (s <= -30).mean() * 100),
                               win60=("r60", lambda s: (s > 0).mean() * 100), flat=("r60", lambda s: (s == 0).mean() * 100))
    out["spike/crash"] = out["spike30"] / out["crash30"].replace(0, np.nan)
    return out.reindex([b for b in order if b in out.index])


def table_by_threshold(df: pd.DataFrame, ths=(10, 20, 30, 50, 100)) -> pd.DataFrame:
    rows = []
    for T in ths:
        for name, m in (("✅ ≤T", df["pct"] <= T), ("❌ >T", df["pct"] > T)):
            s = df[m]
            rows.append({"T": f"+{T}%", "group": name, "n": len(s), "med60": s["r60"].median(), "tmean60": tmean(s["r60"]),
                         "spike30": (s["max60"] >= 30).mean() * 100, "crash30": (s["min60"] <= -30).mean() * 100, "win60": (s["r60"] > 0).mean() * 100})
    return pd.DataFrame(rows)


def fmt(df: pd.DataFrame) -> str:
    try:
        return df.round(1).to_markdown()
    except Exception:  # noqa: BLE001  (tabulate 없음)
        return "```\n" + df.round(1).to_string() + "\n```"


def main():
    D, csv = sys.argv[1], sys.argv[2]
    out_md = sys.argv[3] if len(sys.argv) > 3 else None
    hist = pd.read_csv(csv, dtype={"ticker": str, "asof": str, "filed": str, "form": str})
    px = pickle.load(open(os.path.join(D, "yahoo_px.pkl"), "rb"))
    df = build_pairs(hist, px)
    lines = []
    P = lines.append
    P(f"# 🐷 ⑥ 규칙 검증 — 주식수 변동률 vs 이후 수익률 ({date.today()})")
    P(f"- 표지 {len(hist):,}개 · 종목 {hist['ticker'].nunique():,} → 분기 쌍 {len(df):,}개 · 종목 {df['ticker'].nunique():,} · 진입일 {df['entry'].min()}~{df['entry'].max()}")
    P(f"- 제외: 주가 없음 {df.attrs['dropped']['no_px']}종목 · 역분할 누락 의심(≤-50%) {df.attrs['dropped']['rs_missing']}쌍 · 진입 뒤 20거래일 안 됨 {df.attrs['dropped']['no_entry']}쌍 · 야후 가격 오류(60일 50배↑) {df.attrs['dropped']['glitch']}쌍")
    P("- 주의: 표본은 **지금 상장돼 있는** 순위 우주 종목(최근 120일)이라 희석 끝에 상장폐지된 회사는 빠져 있음 → 희석의 해악이 실제보다 **작게** 잡힘(생존 편향)")
    P(f"- 변동률 분포: 중앙값 {df['pct'].median():+.1f}% · +20% 초과 {(df['pct'] > 20).mean()*100:.0f}% · 분할 반영 쌍 {(df['splits'] > 0).sum():,}")
    P("")
    P("## 전체 — 구간별 (med20·med60 = 20·60거래일 뒤 수익률 중앙값 % · tmean60 = 상하위 5% 깎은 평균 · spike30 = 60일 안 +30% 터치 비율 · crash30 = 60일 안 -30% 터치 비율 · win60 = 60일 뒤 플러스 비율 · flat = 60일 수익률 정확히 0(거래 없는 주식·SPAC) 비율)")
    P(fmt(table_by_bucket(df)))
    P("")
    low = df[(df["c0_raw"] < 5) & (df["r60"] != 0)]
    P(f"## 진입 당시 실제 주가 $5 미만 · 거래 있는 종목만 (우리 대상 영역, n={len(low):,} · 종목 {low['ticker'].nunique():,})")
    P(fmt(table_by_bucket(low)))
    P("")
    P("### 같은 조건, 기준선 T 별 (✅ ≤T vs ❌ >T)")
    P(fmt(table_by_threshold(low)))
    P("")
    for lo, hi, label in ((2024, 2027, "2024~2026 진입"), (2016, 2024, "2016~2023 진입")):
        s = low[(pd.to_datetime(low["entry"]).dt.year >= lo) & (pd.to_datetime(low["entry"]).dt.year < hi)]
        if len(s):
            P(f"### $5 미만 · {label} (n={len(s):,})")
            P(fmt(table_by_bucket(s)))
            P("")
    P(f"### $5 미만 · 분할 있었던 쌍만 (역분할 뒤 대량 발행 유형, n={(low['splits'] > 0).sum():,})")
    P(fmt(table_by_bucket(low[low["splits"] > 0])))
    P("")
    P(f"### 당시 $1 미만만 (n={(low['c0_raw'] < 1).sum():,})")
    P(fmt(table_by_bucket(low[low["c0_raw"] < 1])))
    P("")
    P("## 자료 점검 — 60일 수익률 극단값 상위 8 (남긴 것)")
    top = df.sort_values("r60", ascending=False).head(8)[["ticker", "d0", "d1", "entry", "pct", "c0", "c0_raw", "r20", "r60", "max60"]]
    P(fmt(top.reset_index(drop=True)))
    P("")
    txt = "\n".join(lines)
    print(txt)
    if out_md:
        open(out_md, "w", encoding="utf-8", newline="\n").write(txt + "\n")
        df.to_csv(os.path.join(D, "pairs.csv"), index=False)


if __name__ == "__main__":
    main()
