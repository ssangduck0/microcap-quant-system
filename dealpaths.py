"""📊 펀드스캔 '비슷한 과거 딜' — 과거 자금조달 딜의 '매도 가능일' 뒤 주가가 어떻게 됐는지 분포로 보여 준다.

매도 가능일(딜 물량이 시장에 풀릴 수 있는 날):
 - 공모(424B1·4·5): 종결일 ≈ 접수 + 2거래일
 - 재판매 등록(424B3): 접수일(사모 투자자가 팔 수 있게 되는 날)
 - 사모·PIPE 계약(8-K 1.01·3.02): 그 뒤 처음 나온 재판매 등록 효력(EFFECT, 150일 안) — 없으면 6개월 뒤(규정 144)로 '추정'
결과: 매도 가능일 종가 대비 5·20·60거래일 뒤 등락 + 60거래일 안 최저·최고.
비슷한 딜: 종류 × 가격대($1 미만/$1~5/$5 이상) × 할인율(딜 가격 vs 직전 종가) — 8건 미만이면 한 단계씩 넓힌다.
⚠️ 딜이 1년치라 표본이 작고, 상장폐지된 회사는 주가가 없어 빠진다(실제는 더 나쁠 수 있음).
매일 아침 갱신이 update() 를 부른다.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta

import numpy as np
import pandas as pd

import db

DDL = """CREATE TABLE IF NOT EXISTS fs_deal_paths (accession TEXT PRIMARY KEY, ticker TEXT, kind TEXT, filed TEXT, avail TEXT, avail_note TEXT,
         base REAL, discount REAL, ret5 REAL, ret20 REAL, ret60 REAL, min60 REAL, max60 REAL, bars INTEGER, done INTEGER, updated TEXT)"""
MIN_N = 8
HORIZONS = (5, 20, 60)


def ensure(conn) -> None:
    conn.execute(DDL)


def band(price) -> str:
    if price is None or not np.isfinite(price):
        return "가격 미상"
    return "$1 미만" if price < 1 else ("$1~5" if price < 5 else "$5 이상")


def disc_band(d) -> str:
    if d is None or not np.isfinite(d):
        return "할인 미상"
    return "할인 20%↑" if d <= -20 else ("할인 5~20%" if d <= -5 else "할인 5% 미만")


def _bday(d: date, n: int) -> date:
    x = d
    while n > 0:
        x += timedelta(days=1)
        if x.weekday() < 5:
            n -= 1
    return x


def avail_date(kind: str, form: str, filed: str, effects: list[str]) -> tuple[str, str]:
    """(매도 가능일, 설명)."""
    f = date.fromisoformat(filed)
    if kind == "재판매 등록":
        return filed, "재판매 등록 접수일"
    if kind == "공모":
        return _bday(f, 2).isoformat(), "공모 종결(접수+2거래일)"
    eff = [e for e in sorted(effects) if filed < e <= (f + timedelta(days=150)).isoformat()]
    if eff:
        return eff[0], "재판매 등록 효력(EFFECT)"
    return (f + timedelta(days=182)).isoformat(), "6개월 뒤 추정(규정 144)"


def path(df: pd.DataFrame | None, avail: str, filed: str, unit_price) -> dict | None:
    """매도 가능일 기준 결과. 그날 이후 봉이 없으면 None."""
    if df is None or df.empty:
        return None
    d = df.dropna(subset=["Close"]).copy()
    d.index = pd.to_datetime(d.index).tz_localize(None) if getattr(d.index, "tz", None) is not None else pd.to_datetime(d.index)
    d = d.sort_index()
    pre = d[d.index < pd.Timestamp(filed)]
    after = d[d.index >= pd.Timestamp(avail)]
    if after.empty:
        return None
    base = float(after["Close"].iloc[0])
    if base <= 0:
        return None
    prior = float(pre["Close"].iloc[-1]) if len(pre) else None
    out = {"base": base, "discount": None if not (unit_price and prior) else (float(unit_price) / prior - 1) * 100, "bars": int(len(after) - 1)}
    c = after["Close"].to_numpy(float)
    for h in HORIZONS:
        out[f"ret{h}"] = (c[h] / base - 1) * 100 if len(c) > h else None
    w = after.iloc[1:61]
    out["min60"] = None if w.empty else (float(w["Low"].min()) / base - 1) * 100
    out["max60"] = None if w.empty else (float(w["High"].max()) / base - 1) * 100
    out["done"] = int(len(c) > 60)
    return out


def update(download=None, out=print) -> int:
    """아직 60거래일을 다 못 채운 딜의 결과를 계산·갱신."""
    import pricevault
    with closing(db.connect()) as conn:
        ensure(conn)
        deals = [dict(r) for r in conn.execute("""SELECT d.accession, d.ticker, d.form, d.kind, d.filed, d.unit_price FROM fs_deals d
                                                   LEFT JOIN fs_deal_paths p ON p.accession = d.accession WHERE COALESCE(p.done, 0) = 0""")]
        if not deals:
            out("비슷한 과거 딜: 새로 계산할 딜 없음")
            return 0
        tick = sorted({d["ticker"] for d in deals if d["ticker"]})
        try:
            eff = {}
            for t, f in conn.execute(f"SELECT ticker, filed FROM sec_hist WHERE form='EFFECT' AND ticker IN ({','.join('?' * len(tick))})", tick):
                eff.setdefault(t, []).append(f)
        except Exception:  # noqa: BLE001
            eff = {}
    if download is None:
        import market
        download = lambda ts: market.download_daily(ts, period="2y")  # noqa: E731
    data = {}
    for i in range(0, len(tick), 80):
        data.update(download(tick[i:i + 80]) or {})
    with closing(db.connect()) as conn:
        pricevault.fill(data, tick, conn)  # 상장폐지 등으로 못 받으면 보관소 일봉
        n = 0
        for d in deals:
            av, note = avail_date(d["kind"] or "", d["form"] or "", d["filed"], eff.get(d["ticker"], []))
            if av > date.today().isoformat():
                continue
            p = path(data.get(d["ticker"]), av, d["filed"], d["unit_price"])
            if not p:
                continue
            conn.execute("INSERT OR REPLACE INTO fs_deal_paths VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (d["accession"], d["ticker"], d["kind"], d["filed"], av, note, p["base"], p["discount"], p["ret5"], p["ret20"], p["ret60"],
                          p["min60"], p["max60"], p["bars"], p["done"], db.utcnow_iso()))
            n += 1
        conn.commit()
    out(f"비슷한 과거 딜: {n}건 계산")
    return n


def table(conn=None) -> pd.DataFrame:
    try:
        return db.read_df("SELECT * FROM fs_deal_paths")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def similar(kind: str, price, discount, exclude: str | None = None, df: pd.DataFrame | None = None) -> dict:
    """비슷한 과거 딜의 분포. {"level", "n", "rows", "stats": {h: {median, q25, q75, up}}, "min60", "max60"}"""
    df = table() if df is None else df
    if df.empty:
        return {"level": "자료 없음", "n": 0, "rows": df, "stats": {}}
    df = df[df["accession"] != exclude] if exclude else df
    df = df.assign(_band=[band(b) for b in df["base"]], _disc=[disc_band(x) for x in df["discount"]])
    b, dsc = band(price), disc_band(discount)
    steps = [("종류·가격대·할인율", (df["kind"] == kind) & (df["_band"] == b) & (df["_disc"] == dsc)),
             ("종류·가격대", (df["kind"] == kind) & (df["_band"] == b)),
             ("종류", df["kind"] == kind),
             ("전체 딜", pd.Series(True, index=df.index))]
    for lvl, m in steps:
        sub = df[m]
        if len(sub) >= MIN_N or lvl == "전체 딜":
            break
    st_ = {}
    for h in HORIZONS:
        x = pd.to_numeric(sub[f"ret{h}"], errors="coerce").dropna()
        st_[h] = None if x.empty else {"n": int(len(x)), "median": float(x.median()), "q25": float(x.quantile(.25)), "q75": float(x.quantile(.75)), "up": float((x > 0).mean() * 100)}
    mn = pd.to_numeric(sub["min60"], errors="coerce").dropna()
    mx = pd.to_numeric(sub["max60"], errors="coerce").dropna()
    return {"level": lvl, "n": int(len(sub)), "rows": sub.drop(columns=["_band", "_disc"]), "stats": st_,
            "min60": None if mn.empty else float(mn.median()), "max60": None if mx.empty else float(mx.median()),
            "key": f"{kind} · {b} · {dsc}"}
