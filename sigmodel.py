"""🧠 신호 승률 모델 — 우리만의 AI 2단계(2026-10-28, A안: 사전학습 + 확률 표시 + 보고서. 판정 기준은 바꾸지 않음)

무엇: 신호(🏆 모든 '오름' 출처)마다 "10거래일 안 최고가 +30% 갈 확률(p30)" 과 "5거래일 안 +10% 갈 확률(p10)" 을 붙인다.
학습: 타임머신과 같은 2년치 일봉(daily_prices, 종목당 60일 이상 · 20일 거래대금 $5만↑ · $20 이하) — 날짜마다 **그날까지 정보**로 특징 21개를 벡터 계산,
      정답은 그 뒤 H 거래일 최고가. 5거래일 간격 표본. 시간순 분리: 마지막 6개월 = 검증(표본 외). 표본 20만 행 상한(무작위).
모델: sklearn 없이 winmodel 의 numpy 로지스틱 회귀(표준화 + 제곱항, L2). AUC · 확률 10분위별 실제 적중률 · 표준화 가중치를 보고서로.
적용: 아침 작업이 그날 새 신호에 확률을 붙여 `sig_prob` 에 저장 → 🏆 성과 공표 표 'AI 확률' 열 · 🔍 부검 탭 '🧠 모델' 구역. 월 1회(토요일) 재학습.
컨닝 금지: 특징은 as_of 까지의 봉만(검증 test_sigmodel 에서 미래 봉을 바꿔도 특징이 같은지 확인). 비용 0원.
"""
from __future__ import annotations

import json
import math
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

import db

MODEL_NAME = "sigmodel"
H_BIG, TGT_BIG = 10, 30.0      # p30: 10거래일 안 최고가 +30%
H_SMALL, TGT_SMALL = 5, 10.0   # p10: 5거래일 안 최고가 +10%
MIN_DV, MAX_PRICE = 50_000.0, 20.0
STEP = 5                       # 표본 간격(거래일) — 이웃 날은 거의 같은 표본이라
MIN_HIST = 60                  # 특징을 만들려면 최소 60봉
MIN_BARS = 120                 # 학습 종목: 2년 안 일봉 120개 이상
TEST_MONTHS = 6
MAX_ROWS = 200_000
L2 = 2.0
DIL_DAYS = 90
REFIT_DAYS = 30
ZCLIP = 4.0                    # 표준화 값 상·하한(±4σ)
FEATURES = ["logpx", "sub1", "chg1", "dd20", "vol_x", "ldvol20", "rsi", "obv_r", "ma5_over20", "gc3", "above50", "above200", "sar_up", "bb_ratio",
            "zone", "stage", "base_days", "head_size", "low20_dist", "dil_bad", "dil_unknown"]
FEAT_KO = {"logpx": "가격(log)", "sub1": "$1 미만", "chg1": "1일 등락(%)", "dd20": "20일 낙폭(%)", "vol_x": "거래량 배수(20일 중앙값 대비)", "ldvol20": "20일 거래대금(log)",
           "rsi": "RSI14", "obv_r": "OBV 10일 유입 비율", "ma5_over20": "5일선 > 20일선", "gc3": "5/20 골크 3일 안", "above50": "50일선 위", "above200": "200일선 위",
           "sar_up": "파라볼릭 상승(점 아래)", "bb_ratio": "볼린저 폭 ÷ 120일 중앙값", "zone": "📐 채널 위치(0 없음·1 발 아래·2 발~무릎·3 무릎~허리·4 허리 위)",
           "stage": "📐 되돌림 단계(0~4)", "base_days": "기준봉 뒤 경과일(없으면 99)", "head_size": "기준봉 마디 크기(머리/발, 배)", "low20_dist": "20일 저가 대비(%)",
           "dil_bad": "90일 안 희석 공시", "dil_unknown": "공시 이력 없음(희석 모름)"}
DDL = """CREATE TABLE IF NOT EXISTS sig_prob (source TEXT NOT NULL, date TEXT NOT NULL, ticker TEXT NOT NULL, p30 REAL, p10 REAL, model_at TEXT, created_at TEXT,
         PRIMARY KEY (source, date, ticker))"""


def ensure(conn) -> None:
    conn.execute(DDL)


# ---------------------------------------------------------------- 특징(그날까지 정보만) · 정답
def _channel_arrays(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """📐 기준봉 채널을 날짜마다(그날까지 자료): zone(0 없음·1 발 아래·2 발~무릎·3 무릎~허리·4 허리 위) · stage(0~4) · base_days(없으면 99) · head_size(머리/발)."""
    import chartview as cv
    n = len(c)
    zone, stage, bdays, hsize = np.zeros(n), np.zeros(n), np.full(n, 99.0), np.ones(n)
    if n < 25:
        return zone, stage, bdays, hsize
    v20 = pd.Series(v).shift(1).rolling(20, min_periods=10).median().to_numpy()
    anchor, head = None, 0.0
    for i in range(20, n):
        is_c = v20[i] > 0 and v[i] >= cv.BASE_VOL_X * v20[i] and c[i - 1] > 0 and (h[i] / c[i - 1] - 1) >= cv.BASE_GAIN
        if is_c and (anchor is None or i - anchor > 3):
            anchor, head = i, h[i]
        elif is_c:
            head = max(head, h[i])
        if anchor is None:
            continue
        if i - anchor <= cv.HEAD_DAYS:
            head = max(head, h[i])
        foot, life = min(l[anchor], o[anchor]), o[anchor]
        if head <= foot or i - anchor > 120:
            continue
        r = head - foot
        knee, waist = foot + 0.25 * r, foot + 0.5 * r
        px = c[i]
        zone[i] = 4 if px >= waist else (3 if px >= knee else (2 if px >= foot else 1))
        dd = px / head - 1
        stage[i] = 0 if dd > -0.25 else (1 if dd > -0.40 else (2 if dd > -0.60 else (3 if dd > -0.80 else 4)))
        bdays[i] = i - anchor
        hsize[i] = head / foot
    return zone, stage, bdays, hsize


def daily_features(df: pd.DataFrame, dil_dates: list[str] | None = None, covered: bool = True) -> pd.DataFrame:
    """일봉 → 날짜별 특징(FEATURES) + 정답(y30·y10, 미래가 없으면 NaN) + 표본 자격(ok). 모든 특징은 그 행의 날짜까지 봉만 쓴다."""
    d = df.dropna(subset=["Close"]).sort_index()
    d = d[d["Close"] > 0]
    n = len(d)
    if n < 25:
        return pd.DataFrame()
    import ta
    import chartview as cv
    c = d["Close"].astype(float)
    h = d["High"].astype(float) if "High" in d else c
    l = d["Low"].astype(float) if "Low" in d else c
    o = d["Open"].astype(float) if "Open" in d else c.shift(1).fillna(c)
    v = d["Volume"].fillna(0).astype(float) if "Volume" in d else pd.Series(0.0, index=d.index)
    F = pd.DataFrame(index=d.index)
    F["logpx"] = np.log10(c)
    F["sub1"] = (c < 1).astype(float)
    F["chg1"] = c.pct_change() * 100
    F["dd20"] = (c / h.shift(1).rolling(20).max() - 1) * 100
    vmed = v.shift(1).rolling(20, min_periods=10).median()
    F["vol_x"] = (v / vmed.replace(0, np.nan)).clip(upper=100)
    F["ldvol20"] = np.log10((c * v).rolling(20).mean() + 1)
    F["rsi"] = ta.rsi(c, 14)
    obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
    F["obv_r"] = ((obv - obv.shift(10)) / v.rolling(10).sum().replace(0, np.nan)).clip(-1, 1)
    ma5, ma20, ma50, ma200 = c.rolling(5).mean(), c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200, min_periods=120).mean()
    F["ma5_over20"] = (ma5 > ma20).astype(float)
    dsp = ma5 - ma20
    cross = ((dsp > 0) & (dsp.shift(1) <= 0)).astype(float)
    F["gc3"] = cross.rolling(4, min_periods=1).max()
    F["above50"] = (c > ma50).astype(float)
    F["above200"] = (c > ma200).astype(float)
    _, trend = cv.parabolic_sar(h.to_numpy(), l.to_numpy())
    F["sar_up"] = (trend > 0).astype(float)
    sd20 = c.rolling(20).std()
    width = 4 * sd20 / ma20 * 100
    F["bb_ratio"] = (width / width.rolling(120, min_periods=40).median()).clip(upper=5)
    zone, stage, bdays, hsize = _channel_arrays(o.to_numpy(), h.to_numpy(), l.to_numpy(), c.to_numpy(), v.to_numpy())
    F["zone"], F["stage"], F["base_days"], F["head_size"] = zone, stage, np.minimum(bdays, 99), np.minimum(hsize, 20)
    F["low20_dist"] = (c / l.shift(1).rolling(20).min() - 1) * 100
    dates = np.array([x.strftime("%Y-%m-%d") for x in d.index])
    bad = np.zeros(n)
    if dil_dates:
        dd_ = np.array(sorted(set(str(x)[:10] for x in dil_dates)))
        idx = np.searchsorted(dd_, dates, side="right")
        for i in range(n):
            if idx[i] > 0:
                last = date.fromisoformat(dd_[idx[i] - 1])
                if (date.fromisoformat(dates[i]) - last).days <= DIL_DAYS:
                    bad[i] = 1.0
    F["dil_bad"] = bad
    F["dil_unknown"] = 0.0 if covered else 1.0
    # 정답(미래) — 특징과 분리해 두고 학습 표본에서만 쓴다
    fut10 = h[::-1].rolling(H_BIG, min_periods=H_BIG).max()[::-1].shift(-1)
    fut5 = h[::-1].rolling(H_SMALL, min_periods=H_SMALL).max()[::-1].shift(-1)
    F["y30"] = ((fut10 / c - 1) * 100 >= TGT_BIG).astype(float).where(fut10.notna())
    F["y10"] = ((fut5 / c - 1) * 100 >= TGT_SMALL).astype(float).where(fut5.notna())
    dv20 = (c * v).rolling(20).mean()
    F["ok"] = (dv20 >= MIN_DV) & (c <= MAX_PRICE) & (np.arange(n) >= MIN_HIST)
    F["date"] = dates
    return F.replace([np.inf, -np.inf], np.nan)


def features_asof(df: pd.DataFrame, asof: str, dil_dates=None, covered: bool = True) -> pd.Series | None:
    """신호일(as_of) 기준 특징 한 줄 — as_of 이후 봉은 버리고 계산(컨닝 없음)."""
    d = df[df.index <= pd.Timestamp(asof)]
    if len(d) < MIN_HIST:
        return None
    F = daily_features(d, dil_dates, covered)
    if F.empty:
        return None
    return F.iloc[-1]


# ---------------------------------------------------------------- 학습 자료
def _load_prices(conn, tickers: list[str], since: str) -> dict[str, pd.DataFrame]:
    q = db.read_df(f"SELECT ticker, date, open, high, low, close, volume FROM daily_prices WHERE date >= ? AND ticker IN ({','.join('?' * len(tickers))})", (since, *tickers))
    out = {}
    for t, g in q.groupby("ticker"):
        out[t] = g.set_index(pd.to_datetime(g["date"])).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    return out


def build_dataset(conn, years: float = 2.0, max_tickers: int = 3000, step: int = STEP, out=print, load=None) -> pd.DataFrame:
    """2년치 일봉으로 표본(특징 + 정답). load(tickers, since) → {ticker: df} 로 가짜 자료 주입 가능."""
    import timemachine as tm
    end = (date.today() - timedelta(days=21)).isoformat()
    start = (date.today() - timedelta(days=int(365 * years))).isoformat()
    since = (date.fromisoformat(start) - timedelta(days=300)).isoformat()
    tick = [r[0] for r in conn.execute("SELECT ticker FROM daily_prices WHERE date >= ? GROUP BY ticker HAVING COUNT(*) >= ? LIMIT ?", (since, MIN_BARS, max_tickers))]
    if not tick:
        return pd.DataFrame()
    dil = tm._dil_dates(conn, set(tick))
    cov = tm._covered(conn)
    load = load or (lambda ts, sc: _load_prices(conn, ts, sc))
    parts = []
    for k in range(0, len(tick), 300):
        for t, df in load(tick[k:k + 300], since).items():
            try:
                F = daily_features(df, dil.get(t), t in cov)
            except Exception:  # noqa: BLE001
                continue
            if F.empty:
                continue
            F = F[F["ok"] & F["y30"].notna() & (F["date"] >= start) & (F["date"] <= end)]
            if F.empty:
                continue
            F = F.iloc[::step].copy()
            F["ticker"] = t
            parts.append(F)
        out(f"신호 승률 모델 자료: {min(k + 300, len(tick))}/{len(tick)}종목")
    if not parts:
        return pd.DataFrame()
    X = pd.concat(parts, ignore_index=True)
    if len(X) > MAX_ROWS:
        X = X.sample(MAX_ROWS, random_state=7).sort_values("date")
    return X.reset_index(drop=True)


# ---------------------------------------------------------------- 학습 · 평가
def _prep(X: pd.DataFrame) -> pd.DataFrame:
    return X[FEATURES].astype(float).fillna(X[FEATURES].astype(float).median()).fillna(0.0)


def _fit(X: pd.DataFrame, y: np.ndarray) -> dict:
    import winmodel as wm
    mu, sd = X.mean(), X.std().replace(0, 1.0)
    Z = np.clip(((X - mu) / sd).to_numpy(), -ZCLIP, ZCLIP)   # 극단값(거래량 수백 배 등)이 제곱항으로 확률을 0.99 까지 밀지 않게
    Z2 = np.hstack([Z, Z ** 2])
    emu, esd = Z2.mean(axis=0), Z2.std(axis=0)
    esd[esd == 0] = 1.0
    w = wm.fit_logistic((Z2 - emu) / esd, y, L2)
    return {"mean": mu.tolist(), "std": sd.tolist(), "emean": emu.tolist(), "estd": esd.tolist(), "weights": w.tolist(), "features": list(X.columns)}


def _predict(P: dict, X: pd.DataFrame) -> np.ndarray:
    import winmodel as wm
    cols = P["features"]
    Z = np.clip(((X[cols] - pd.Series(P["mean"], index=cols)) / pd.Series(P["std"], index=cols)).to_numpy(), -ZCLIP, ZCLIP)
    Z2 = (np.hstack([Z, Z ** 2]) - np.array(P["emean"])) / np.array(P["estd"])
    return wm.predict_raw(np.array(P["weights"]), Z2)


def _deciles(p: np.ndarray, y: np.ndarray) -> list[dict]:
    if len(p) < 20:
        return []
    q = pd.qcut(pd.Series(p).rank(method="first"), 10, labels=False)
    out = []
    for k in range(10):
        m = (q == k).to_numpy()
        if m.sum() == 0:
            continue
        out.append({"분위": k + 1, "표본": int(m.sum()), "예측 확률(%)": float(p[m].mean() * 100), "실제 적중(%)": float(y[m].mean() * 100)})
    return out


def _weights_table(P: dict) -> list[dict]:
    k = len(P["features"])
    w = np.array(P["weights"])[1:1 + k]   # 선형 부분(표준화 뒤) — 방향·크기 해석용
    rows = [{"특징": FEAT_KO.get(f, f), "key": f, "가중치": float(x)} for f, x in zip(P["features"], w)]
    return sorted(rows, key=lambda r: -abs(r["가중치"]))


def fit(X: pd.DataFrame, test_months: int = TEST_MONTHS) -> dict:
    """시간순 분리로 두 목표(p30·p10)를 학습·검증. 반환 = 저장할 모델 딕셔너리."""
    X = X.dropna(subset=["y30"]).copy()
    cut = (pd.to_datetime(X["date"].max()) - pd.DateOffset(months=test_months)).strftime("%Y-%m-%d")
    tr, te = (X["date"] < cut).to_numpy(), (X["date"] >= cut).to_numpy()
    if tr.sum() < 500 or te.sum() < 100:
        raise ValueError(f"표본 부족(학습 {int(tr.sum())} · 검증 {int(te.sum())})")
    F = _prep(X)
    model = {"name": MODEL_NAME, "features": FEATURES, "fitted_at": db.utcnow_iso(), "cutoff": cut, "n_train": int(tr.sum()), "n_test": int(te.sum()),
             "n_tickers": int(X["ticker"].nunique()) if "ticker" in X else None, "from": str(X["date"].min()), "to": str(X["date"].max()), "targets": {}}
    import winmodel as wm
    for key, ycol, h, tgt in (("p30", "y30", H_BIG, TGT_BIG), ("p10", "y10", H_SMALL, TGT_SMALL)):
        y = X[ycol].fillna(0).to_numpy().astype(float)
        P = _fit(F[tr], y[tr])
        p_tr, p_te = _predict(P, F[tr]), _predict(P, F[te])
        dec = _deciles(p_te, y[te])
        top = dec[-1]["실제 적중(%)"] if dec else None
        base = float(y[te].mean() * 100)
        model["targets"][key] = {"horizon": h, "target_pct": tgt, "pipe": P, "auc_train": wm.auc(p_tr, y[tr]), "auc_test": wm.auc(p_te, y[te]), "base_rate_test": base,
                                 "base_rate_train": float(y[tr].mean() * 100), "deciles": dec, "lift_top": (top / base) if (top is not None and base > 0) else None,
                                 "weights": _weights_table(P)}
    return model


def save(model: dict) -> None:
    db.save_model(MODEL_NAME, model)


def load() -> dict | None:
    try:
        return db.get_model(MODEL_NAME)
    except Exception:  # noqa: BLE001
        return None


def fit_all(conn=None, out=print, load_prices=None, years: float = 2.0, max_tickers: int = 3000) -> dict:
    if conn is None:
        with closing(db.connect()) as c:
            return fit_all(c, out, load_prices, years, max_tickers)
    X = build_dataset(conn, years, max_tickers, out=out, load=load_prices)
    if X.empty:
        out("신호 승률 모델: 과거 일봉이 부족해 학습하지 않음(타임머신 `--fill` 로 과거 일봉을 채우면 됨)")
        return {"status": "no_data"}
    m = fit(X)
    save(m)
    out(summary(m))
    return {"status": "ok", **{k: v for k, v in m.items() if k != "targets"}, "auc_test_p30": m["targets"]["p30"]["auc_test"], "auc_test_p10": m["targets"]["p10"]["auc_test"]}


def summary(m: dict) -> str:
    t30, t10 = m["targets"]["p30"], m["targets"]["p10"]
    f = lambda x: "-" if x is None else f"{x:.3f}"
    return (f"🧠 신호 승률 모델: 표본 학습 {m['n_train']:,} · 검증 {m['n_test']:,}(검증 시작 {m['cutoff']}) · 종목 {m.get('n_tickers') or '-'} · "
            f"p30 AUC 학습 {f(t30['auc_train'])}/검증 {f(t30['auc_test'])} · 기준 적중 {t30['base_rate_test']:.1f}% · 상위 10% 적중 {(t30['deciles'][-1]['실제 적중(%)'] if t30['deciles'] else 0):.1f}% · "
            f"p10 AUC 검증 {f(t10['auc_test'])}")


def maybe_refit(conn, out=print, today: date | None = None) -> dict | None:
    """월 1회(토요일 아침 작업) 또는 모델이 없을 때 학습."""
    today = today or date.today()
    m = load()
    if m:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(m["fitted_at"]).replace(tzinfo=timezone.utc)).days
        except Exception:  # noqa: BLE001
            age = 999
        if age < REFIT_DAYS or today.weekday() != 5:
            return None
    return fit_all(conn, out)


# ---------------------------------------------------------------- 신호에 확률 붙이기
def predict_rows(model: dict, F: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    X = F[FEATURES].astype(float).fillna(0.0)
    return _predict(model["targets"]["p30"]["pipe"], X), _predict(model["targets"]["p10"]["pipe"], X)


def score_signals(conn, days: int = 3, out=print, download=None, model: dict | None = None) -> int:
    """최근 days 일의 '오름' 신호 중 아직 확률이 없는 것에 p30·p10 을 붙여 sig_prob 에 저장. download(ticker) → 일봉(테스트는 가짜)."""
    ensure(conn)
    model = model or load()
    if not model:
        return 0
    import scoreboard as sb
    import timemachine as tm
    sig = sb.collect(conn)
    if sig.empty:
        return 0
    since = (date.today() - timedelta(days=days)).isoformat()
    sig = sig[(sig["direction"] > 0) & (sig["date"] >= since)][["source", "date", "ticker"]].drop_duplicates()
    have = {tuple(r) for r in conn.execute("SELECT source, date, ticker FROM sig_prob WHERE date >= ?", (since,))}
    sig = sig[[tuple(x) not in have for x in sig.itertuples(index=False, name=None)]]
    if sig.empty:
        return 0
    ticks = sorted(set(sig["ticker"]))
    hist_since = (date.today() - timedelta(days=420)).isoformat()
    prices = _load_prices(conn, ticks, hist_since)
    for t in ticks:
        if (t not in prices or len(prices[t]) < 200) and download is not None:
            try:
                df = download(t)
                if df is not None and len(df):
                    db.upsert_daily_prices(conn, t, df)
                    prices[t] = df
            except Exception:  # noqa: BLE001
                pass
    dil = tm._dil_dates(conn, set(ticks))
    cov = tm._covered(conn)
    n = 0
    now = db.utcnow_iso()
    rows = []
    for r in sig.itertuples(index=False):
        df = prices.get(r.ticker)
        if df is None:
            continue
        f = features_asof(df, r.date, dil.get(r.ticker), r.ticker in cov)
        if f is None:
            continue
        rows.append((r.source, r.date, r.ticker, f))
    if rows:
        F = pd.DataFrame([x[3] for x in rows])
        p30, p10 = predict_rows(model, F)
        for (s, d0, t, _), a, b in zip(rows, p30, p10):
            conn.execute("INSERT OR REPLACE INTO sig_prob VALUES (?,?,?,?,?,?,?)", (s, d0, t, float(a), float(b), model.get("fitted_at"), now))
            n += 1
        conn.commit()
    out(f"🧠 신호 승률: {n}건에 확률 붙임(대상 {len(sig)}건)")
    return n


def probs(conn, days: int = 120) -> pd.DataFrame:
    ensure(conn)
    return pd.read_sql_query("SELECT source, date, ticker, p30, p10 FROM sig_prob WHERE date >= date('now', ?)", conn, params=(f"-{days} day",))


if __name__ == "__main__":
    import sys
    if "fit" in sys.argv:
        print(fit_all())
    else:
        with closing(db.connect()) as conn:
            print(score_signals(conn))
