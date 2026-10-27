"""신호 이후 성과(forward return) 통계.

기준가는 스냅샷 가격이 아니라 daily_prices 의 같은 날 종가입니다. 그래야 이후 종가와 같은 데이터 계열이라
역분할(reverse split)로 인한 가격 왜곡이 섞이지 않습니다. (장중 신호가 아니라 '그날 종가 진입' 가정의 통계)
"""
import numpy as np
import pandas as pd

import db

HORIZONS = (1, 3, 5, 10)


def forward_returns(horizons=HORIZONS) -> pd.DataFrame:
    snaps = db.read_df("SELECT date,ticker,drawdown_pct,quant_score,pump_score,dilution_status,excluded FROM daily_snapshots")
    px = db.read_df("SELECT ticker,date,close FROM daily_prices ORDER BY ticker,date")
    cols = [f"fwd_{h}d" for h in horizons]
    for c in cols:
        snaps[c] = np.nan
    if snaps.empty or px.empty:
        return snaps
    series = {t: g.reset_index(drop=True) for t, g in px.groupby("ticker")}
    for i, row in snaps.iterrows():
        g = series.get(row["ticker"])
        if g is None:
            continue
        idx = int(g["date"].searchsorted(row["date"]))
        if idx >= len(g) or g["date"].iloc[idx] != row["date"]:
            continue
        base = g["close"].iloc[idx]
        if not base or pd.isna(base):
            continue
        for h, c in zip(horizons, cols):
            if idx + h < len(g):
                snaps.at[i, c] = (g["close"].iloc[idx + h] / base - 1) * 100
    return snaps


def summarize(df: pd.DataFrame, by: str, horizons=HORIZONS) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(by, observed=True):
        row = {by: key, "신호 수": len(g)}
        for h in horizons:
            s = g[f"fwd_{h}d"].dropna()
            row[f"{h}일 평균(%)"] = s.mean() if len(s) else np.nan
            row[f"{h}일 중앙값(%)"] = s.median() if len(s) else np.nan
            row[f"{h}일 승률(%)"] = (s > 0).mean() * 100 if len(s) else np.nan
            row[f"{h}일 표본"] = len(s)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 과거 사례(case_events) 요약
def case_summary(df: pd.DataFrame, success_pct: float, by: str | None = None, bins=None, labels=None) -> pd.DataFrame:
    """사건 집합의 결과 요약. '성공' = 다음날 고가가 사건일 종가 대비 +success_pct% 이상 도달(일봉이라 도달 순서는 알 수 없음)."""
    def one(g: pd.DataFrame, name) -> dict:
        known = g["next_high_pct"].dropna()
        row = {"구분": name, "사건 수": len(g), "다음날 결과 확인": len(known),
               f"성공률(다음날 고가 ≥ +{success_pct:g}%)": (known >= success_pct).mean() * 100 if len(known) else np.nan}
        for col, nm in (("next_open_pct", "다음날 시가"), ("next_high_pct", "다음날 고가"), ("next_close_pct", "다음날 종가"),
                        ("fwd_5d", "5일 후 종가"), ("max_down_5d", "5일 내 최저가")):
            s = g[col].dropna()
            row[f"{nm} 중앙값(%)"] = s.median() if len(s) else np.nan
        return row
    if by is None:
        return pd.DataFrame([one(df, "전체")])
    grp = pd.cut(df[by], bins, labels=labels) if bins is not None else df[by]
    return pd.DataFrame([one(g, k) for k, g in df.groupby(grp, observed=True)])
