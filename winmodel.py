"""승률 점수(승률 모델).

  python winmodel.py fit [--test-months 24]   # 과거 사례(case_events)로 학습·검증하고 DB에 저장
  python winmodel.py show                     # 저장된 모델의 검증 결과

무엇을 하나
  전일 종가 대비 -10% 이하 급락 사건의 '결과'(다음날 고가가 +N% 이상 / 다음날 종가가 +N% 이상)를 예측하는 로지스틱 회귀입니다.
  입력값은 스냅샷(스캐너)에서도 과거 사건(일봉)과 같은 정의로 계산되는 것만 씁니다.
     v1(4개): 오늘 등락률, 거래량 배수, 전일까지 20일 낙폭, 20일 평균 거래대금
     v2(9개): v1 + 시가 갭, 종가 위치(고저 범위 중 어디서 마감), 그날 변동폭, 직전 20일 평균 변동폭, 시장 급락 종목 비율
  v2 는 과거 사례 DB 에 새 입력이 채워져 있을 때(= `python cases.py build --rebuild` 이후) 자동으로 선택됩니다.
  선형 모델과 '입력 간 상호작용을 허용하는 2차 모델' 중 더 나은 쪽을 **학습 구간 안의 검증 구간**에서 골라 씁니다(표본 외 구간은 선택에 쓰지 않음).
  승률 점수 = (희석 상태 가정 배수를 곱한) 예상 확률이 과거 사건 분포에서 몇 번째 백분위인가 (0~100).

검증 방식 (과적합 방지)
  - 시간 분할: 최근 N개월(기본 24)은 학습에 쓰지 않고 '표본 외(OOS)' 검증에만 씁니다.
  - 보고하는 숫자: OOS AUC, 기준 성공률, 점수 구간별 OOS 성공률·표본 수, 다음날 종가 수익률(거래 가능한 대리 지표), 확률 보정표.
  - 점수 임계값을 여러 번 바꿔가며 최고 승률만 고르면 과적합입니다. OOS 표에서 한 번 정하고 라이브 데이터로 확인하세요.

한계
  - 과거 사건 시점의 희석 공시를 재현하지 못해, 희석 상태는 학습되지 않고 '가정 배수'로만 반영됩니다.
  - 사건들은 시장 급락일에 몰려 있어 독립적이지 않고, 상장폐지 종목이 거의 없어 성공률이 낙관적입니다.
  - 학습 입력은 장 마감 기준 값이므로, 점수는 마감 직전 스캔 값이 가장 의미 있습니다(장중엔 거래량이 덜 쌓여 낮게 나옴).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import config
import db

FEATURES_V1 = ["drop", "vol", "pre", "dv"]
FEATURES_V2 = FEATURES_V1 + ["gap", "loc", "rng", "prng", "mkt"]
FEATURES = FEATURES_V1  # (이전 버전 호환)
FEATURE_KO = {"drop": "오늘 등락률(%)", "vol": "거래량 배수(log2)", "pre": "전일까지 20일 낙폭(%)", "dv": "20일 평균 거래대금(log10 $)",
              "gap": "시가 갭(%)", "loc": "종가 위치(0=저가,1=고가)", "rng": "그날 변동폭(log)", "prng": "직전 20일 평균 변동폭(log)",
              "mkt": "시장 급락 종목 비율(log)"}
LABELS = {"high": ("next_high_pct", "다음날 고가"), "close": ("next_close_pct", "다음날 종가")}
DEFAULT_MODELS = [("high", 5.0), ("high", 10.0), ("high", 20.0), ("close", 0.0), ("close", 5.0)]
SCORE_CUTS = [50, 60, 70, 80, 90, 95]
L2 = {False: 1.0, True: 30.0}  # 선형 / 2차(입력이 54개로 늘어 규제를 세게)
EV_SQL = ("SELECT ticker, date, drop_pct, vol_mult, pre_dd_pct, avg_dollar_vol, gap_pct, close_loc, range_pct, prior_range_pct, "
          "next_open_pct, next_high_pct, next_close_pct FROM case_events")


def model_name(label: str, target: float) -> str:
    return f"{label}_{target:g}"


# ---------------------------------------------------------------- 입력값
def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(df[name], errors="coerce") if name in df else pd.Series(np.nan, index=df.index)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """원천 컬럼(drop_pct, vol_mult, pre_dd_pct, avg_dollar_vol, gap_pct, close_loc, range_pct, prior_range_pct, mkt_down_frac)을
    모델 입력으로 변환. 없는 값은 NaN(해당 행은 점수 계산 불가)."""
    f = pd.DataFrame(index=df.index)
    f["drop"] = _col(df, "drop_pct").clip(-99, -10)
    f["vol"] = np.log2(_col(df, "vol_mult").clip(lower=1e-3)).clip(-6, 8)
    f["pre"] = _col(df, "pre_dd_pct").clip(-99, 5)
    f["dv"] = np.log10(_col(df, "avg_dollar_vol").clip(lower=1)).clip(3, 10)
    f["gap"] = _col(df, "gap_pct").clip(-60, 100)
    f["loc"] = _col(df, "close_loc").clip(0, 1)
    f["rng"] = np.log1p(_col(df, "range_pct").clip(0, 400))
    f["prng"] = np.log1p(_col(df, "prior_range_pct").clip(0, 100))
    f["mkt"] = np.log1p(100 * _col(df, "mkt_down_frac").clip(0, 1))
    return f.replace([np.inf, -np.inf], np.nan)


def market_frac(dates: pd.Series, prog: pd.DataFrame, min_tickers: int = 500) -> np.ndarray:
    """사건일마다 '그날 -10% 이하로 빠진 종목 수 / 그날 데이터가 있던 종목 수'. 분모는 종목별 데이터 시작·끝 날짜(case_progress)로 계산."""
    if prog.empty or len(dates) == 0:
        return np.full(len(dates), np.nan)
    d = pd.to_datetime(dates).to_numpy("datetime64[D]")
    firsts = np.sort(pd.to_datetime(prog["first_date"]).to_numpy("datetime64[D]"))
    lasts = np.sort(pd.to_datetime(prog["last_date"]).to_numpy("datetime64[D]"))
    n_tickers = np.searchsorted(firsts, d, "right") - np.searchsorted(lasts, d, "left")
    s = pd.Series(dates.to_numpy())
    counts = s.map(s.value_counts()).to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = counts / n_tickers
    frac[n_tickers < min_tickers] = np.nan
    return frac


def load_training_events() -> pd.DataFrame:
    ev = db.read_df(EV_SQL)
    prog = db.read_df("SELECT first_date, last_date FROM case_progress WHERE status='done' AND first_date IS NOT NULL AND last_date IS NOT NULL")
    ev["mkt_down_frac"] = market_frac(ev["date"], prog)
    return ev


def v2_coverage(ev: pd.DataFrame) -> float:
    return float(build_features(ev)[FEATURES_V2].notna().all(axis=1).mean()) if len(ev) else 0.0


# ---------------------------------------------------------------- 로지스틱 회귀 (numpy, L2)
def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 60) -> np.ndarray:
    n, k = X.shape
    Xb = np.c_[np.ones(n), X]
    w = np.zeros(k + 1)
    pen = np.r_[0.0, np.ones(k)]
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(Xb @ w, -30, 30)))
        g = Xb.T @ (p - y) + l2 * pen * w
        h = Xb.T @ (Xb * (p * (1 - p))[:, None]) + l2 * np.diag(pen)
        step = np.linalg.solve(h + 1e-9 * np.eye(k + 1), g)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def predict_raw(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(np.c_[np.ones(len(X)), X] @ w, -30, 30)))


def auc(score: np.ndarray, y: np.ndarray) -> float | None:
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return None
    r = pd.Series(score).rank().to_numpy()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def expand_quad(Z: np.ndarray) -> np.ndarray:
    """표준화된 입력에 제곱항과 모든 쌍의 곱(상호작용)을 붙인다."""
    k = Z.shape[1]
    cols = [Z, Z ** 2] + [(Z[:, i] * Z[:, j])[:, None] for i in range(k) for j in range(i + 1, k)]
    return np.hstack(cols)


def _fit_pipe(X: pd.DataFrame, y: np.ndarray, quad: bool) -> dict:
    mu, sd = X.mean(), X.std().replace(0, 1.0)
    Z = ((X - mu) / sd).to_numpy()
    emu = esd = None
    if quad:
        Z = expand_quad(Z)
        emu, esd = Z.mean(axis=0), Z.std(axis=0)
        esd[esd == 0] = 1.0
        Z = (Z - emu) / esd
    w = fit_logistic(Z, y, L2[quad])
    return {"mean": mu.tolist(), "std": sd.tolist(), "quad": quad, "weights": w.tolist(),
            "emean": None if emu is None else emu.tolist(), "estd": None if esd is None else esd.tolist()}


def _pred_pipe(P: dict, X: pd.DataFrame) -> np.ndarray:
    Z = ((X - pd.Series(P["mean"], index=X.columns)) / pd.Series(P["std"], index=X.columns)).to_numpy()
    if P.get("quad"):
        Z = (expand_quad(Z) - np.array(P["emean"])) / np.array(P["estd"])
    return predict_raw(np.array(P["weights"]), Z)


def _pipe_of(model: dict) -> dict:
    return model.get("pipe") or {"mean": model["mean"], "std": model["std"], "quad": False, "weights": model["weights"]}  # 이전 버전 모델 호환


def pick_quad(X: pd.DataFrame, y: np.ndarray, dates: pd.Series) -> tuple[bool, dict]:
    """학습 구간 안에서 마지막 12개월을 검증 구간으로 떼어 선형/2차 중 고른다(표본 외 구간은 쓰지 않음)."""
    cut = (pd.to_datetime(dates.max()) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
    a = (dates < cut).to_numpy()
    b = ~a
    if a.sum() < 3000 or b.sum() < 1000:
        return False, {"note": "선택용 표본 부족 — 선형 모델 사용"}
    res = {}
    for quad in (False, True):
        res[quad] = auc(_pred_pipe(_fit_pipe(X[a], y[a], quad), X[b]), y[b])
    pick = bool(res[True] is not None and res[False] is not None and res[True] > res[False] + 0.002)
    return pick, {"val_auc_linear": res[False], "val_auc_quad": res[True], "val_from": cut}


def close_stats(nc: np.ndarray) -> dict | None:
    """다음날 종가 수익률(사건일 종가 대비) 요약: 중앙값, 평균(±극단값 제한), 상승 비율. 초소형주는 극단값이 많아 평균은 -50~+100% 로 제한한다."""
    nc = np.asarray(nc, float)
    nc = nc[~np.isnan(nc)]
    if len(nc) == 0:
        return None
    return {"median": float(np.median(nc)), "mean": float(np.clip(nc, -50, 100).mean()), "up": float((nc > 0).mean() * 100)}


def tp_stats(o, h, c, target: float) -> dict | None:
    """'목표가 청산' 시뮬레이션: 사건일 종가에 사서, 다음날 +target% 지정가 매도를 걸고, 못 팔면 다음날 종가에 정리.
      시가가 이미 목표 이상(갭 상승)이면 시가에 체결, 아니면 고가가 목표에 닿았을 때 target 에 체결, 못 닿으면 종가.
    손절 없이 목표가만 걸므로 장중 고가/저가의 순서를 몰라도 계산된다. 체결 수량·호가 공백·거래정지·수수료는 반영되지 않아 낙관적이다."""
    o, h, c = (np.asarray(x, float) for x in (o, h, c))
    ok = ~(np.isnan(h) | np.isnan(c))
    o, h, c = o[ok], h[ok], c[ok]
    if len(c) == 0:
        return None
    gap_fill = ~np.isnan(o) & (o >= target)
    ret = np.where(gap_fill, o, np.where(h >= target, target, c))
    return {"hit": float(((h >= target) | gap_fill).mean() * 100), "mean": float(np.clip(ret, -50, 100).mean()),
            "median": float(np.median(ret)), "win": float((ret > 0).mean() * 100), "tail": float((ret <= -20).mean() * 100)}


# ---------------------------------------------------------------- 학습/검증
def fit_model(ev: pd.DataFrame, label: str, target: float, test_months: int = 24, feature_set: str | None = None) -> dict:
    ev = ev.reset_index(drop=True)
    col = LABELS[label][0]
    F_all = build_features(ev)
    if feature_set is None:
        feature_set = "v2" if v2_coverage(ev) >= 0.9 else "v1"
    feats = FEATURES_V2 if feature_set == "v2" else FEATURES_V1
    ok = (F_all[feats].notna().all(axis=1) & ev[col].notna()).to_numpy()
    X = F_all.loc[ok, feats].reset_index(drop=True)
    y = (ev.loc[ok, col] >= target).astype(float).to_numpy()
    dates = ev.loc[ok, "date"].reset_index(drop=True)
    nc_all = ev.loc[ok, "next_close_pct"].to_numpy(float)
    nh_all = ev.loc[ok, "next_high_pct"].to_numpy(float)
    no_all = ev.loc[ok, "next_open_pct"].to_numpy(float) if "next_open_pct" in ev else np.full(len(nc_all), np.nan)
    use_tp = label == "high"  # 목표가 청산 시뮬레이션은 고가 기준 모델에서만 의미가 있다
    if len(X) < 300:
        raise ValueError(f"학습할 사건이 부족합니다({len(X)}건). 먼저 `python cases.py build` 를 실행하세요.")
    cut = (pd.to_datetime(dates.max()) - pd.DateOffset(months=test_months)).strftime("%Y-%m-%d")
    tr = (dates < cut).to_numpy()
    te = ~tr
    metrics: dict = {"test_months": test_months, "test_from": cut, "n_all": int(len(X)), "feature_set": feature_set}
    quad = False

    if tr.sum() >= 500 and te.sum() >= 200:  # 표본 외 검증
        quad, pick = pick_quad(X[tr], y[tr], dates[tr])
        metrics["quad_pick"] = pick
        P = _fit_pipe(X[tr], y[tr], quad)
        p_tr, p_te = _pred_pipe(P, X[tr]), _pred_pipe(P, X[te])
        yt, nc_te, nh_te, no_te = y[te], nc_all[te], nh_all[te], no_all[te]
        base = float(yt.mean())
        metrics.update(n_train=int(tr.sum()), n_test=int(te.sum()), base_rate_test=base * 100, base_rate_train=float(y[tr].mean()) * 100,
                       auc_train=auc(p_tr, y[tr]), auc_test=auc(p_te, yt),
                       brier_test=float(np.mean((p_te - yt) ** 2)), brier_base=float(np.mean((base - yt) ** 2)))
        if quad:  # 참고: 선형 모델의 표본 외 AUC
            metrics["auc_linear_test"] = auc(_pred_pipe(_fit_pipe(X[tr], y[tr], False), X[te]), yt)
        order = np.argsort(p_te)
        k = max(1, int(len(p_te) * 0.2))
        top = order[-k:]
        metrics["lift_top20"] = float(yt[top].mean() / base) if base > 0 else None
        metrics["rate_top20"] = float(yt[top].mean()) * 100
        metrics["base_close"] = close_stats(nc_te)
        metrics["top20_close"] = close_stats(nc_te[top])
        if use_tp:
            metrics["base_tp"] = tp_stats(no_te, nh_te, nc_te, target)
            metrics["top20_tp"] = tp_stats(no_te[top], nh_te[top], nc_te[top], target)
        q = pd.qcut(pd.Series(p_te), 10, labels=False, duplicates="drop")
        metrics["deciles"] = [{"bin": int(b) + 1, "pred": float(p_te[(q == b).to_numpy()].mean()) * 100,
                               "actual": float(yt[(q == b).to_numpy()].mean()) * 100, "n": int((q == b).sum())} for b in sorted(q.unique())]
        ref_tr = np.quantile(p_tr, np.linspace(0, 1, 201))
        rows = []
        for s_cut in SCORE_CUTS:
            cutoff = float(np.interp(s_cut, np.linspace(0, 100, 201), ref_tr))
            sel = p_te >= cutoff
            cs = close_stats(nc_te[sel]) if sel.sum() else None
            tp = tp_stats(no_te[sel], nh_te[sel], nc_te[sel], target) if (use_tp and sel.sum()) else None
            rows.append({"score": s_cut, "n": int(sel.sum()), "success": float(yt[sel].mean()) * 100 if sel.sum() else None,
                         "lift": float(yt[sel].mean() / base) if sel.sum() and base > 0 else None,
                         "close_median": cs["median"] if cs else None, "close_mean": cs["mean"] if cs else None, "close_up": cs["up"] if cs else None,
                         "tp_mean": tp["mean"] if tp else None, "tp_median": tp["median"] if tp else None,
                         "tp_win": tp["win"] if tp else None, "tp_tail": tp["tail"] if tp else None})
        metrics["thresholds"] = rows
    else:
        metrics["note"] = "표본이 부족해 표본 외 검증을 하지 못했습니다."

    P_all = _fit_pipe(X, y, quad)  # 실제 점수 계산용 최종 모델은 전체 사건으로 학습
    p_all = _pred_pipe(P_all, X)
    w_lin = _fit_pipe(X, y, False)["weights"]  # 화면에 보여줄 계수는 선형 모델 기준
    return {
        "name": model_name(label, target), "label": label, "target": target, "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "features": feats, "feature_set": feature_set, "quad": quad, "pipe": P_all,
        "ref": np.quantile(p_all, np.linspace(0, 1, 201)).tolist(), "base_rate_all": float(y.mean()) * 100, "metrics": metrics,
        "coefs": [{"feature": f, "label": FEATURE_KO[f], "std_coef": float(c)} for f, c in zip(feats, w_lin[1:])],
    }


# ---------------------------------------------------------------- 점수 계산
def load_model(name: str | None = None) -> dict | None:
    try:
        return db.get_model(name or config.WIN_MODEL)
    except Exception:  # noqa: BLE001
        return None


def score_frame(model: dict, df: pd.DataFrame, dilution_status=None) -> pd.DataFrame:
    """df: 원천 컬럼(drop_pct, vol_mult, pre_dd_pct, avg_dollar_vol, gap_pct, close_loc, range_pct, prior_range_pct, mkt_down_frac).
    반환: win_p(0~1, 희석 보정 전), win_score(0~100). 입력이 부족하거나 오늘 등락률이 -10% 보다 덜 빠졌으면 NaN."""
    feats = model["features"]
    F = build_features(df)[feats]
    drop = _col(df, "drop_pct").to_numpy(float)
    ok = (F.notna().all(axis=1).to_numpy()) & (drop <= -10)
    p = np.full(len(F), np.nan)
    if ok.any():
        p[ok] = _pred_pipe(_pipe_of(model), F[ok])
    p_adj = p.copy()
    if config.DILUTION_ADJUST and dilution_status is not None:
        p_adj = p * pd.Series(dilution_status).map(config.DILUTION_MULT).fillna(1.0).to_numpy()
    ref = np.array(model["ref"])
    score = np.interp(p_adj, ref, np.linspace(0, 100, len(ref)))
    score[np.isnan(p_adj)] = np.nan
    return pd.DataFrame({"win_p": p, "win_score": score})


def metrics_to_source(m: dict) -> dict:
    """스캐너의 compute_metrics 결과를 모델 원천 컬럼 이름으로 바꾼다."""
    return {"drop_pct": m.get("day_change_pct"), "vol_mult": m.get("volume_mult"), "pre_dd_pct": m.get("pre_dd_pct"),
            "avg_dollar_vol": m.get("avg_dollar_vol"), "gap_pct": m.get("gap_pct"), "close_loc": m.get("close_loc"),
            "range_pct": m.get("range_pct"), "prior_range_pct": m.get("prior_range_pct"), "mkt_down_frac": m.get("mkt_down_frac")}


def score_one(model: dict | None, m: dict, status: str) -> tuple[float | None, float | None]:
    """스캐너용: compute_metrics 결과 하나를 점수로. 계산 불가면 (None, None)."""
    if not model:
        return None, None
    r = score_frame(model, pd.DataFrame([metrics_to_source(m)]), [status]).iloc[0]
    if pd.isna(r["win_p"]):
        return None, None
    return float(r["win_p"]), float(r["win_score"])


# ---------------------------------------------------------------- CLI
def fit_all(test_months: int = 24, out=print) -> list[dict]:
    ev = load_training_events()
    cov = v2_coverage(ev)
    out(f"학습 데이터: 사건 {len(ev):,}건 · 확장 입력(갭·종가 위치·변동폭·시장 비율) 보유율 {cov * 100:.0f}%")
    if cov < 0.9:
        out("  ※ 확장 입력이 아직 부족해 기본 4개 입력으로 학습합니다. `python cases.py build --years 10 --rebuild` 후 다시 fit 하세요.")
    res = []
    for label, target in DEFAULT_MODELS:
        try:
            md = fit_model(ev, label, target, test_months)
        except ValueError as e:
            out(f"  {model_name(label, target)}: {e}")
            continue
        db.save_model(md["name"], md)
        res.append(md)
        out("  " + summary(md))
    return res


def summary(md: dict) -> str:
    m = md["metrics"]
    tag = f"[입력 {len(md['features'])}개{'·2차' if md.get('quad') else ''}]"
    if "auc_test" not in m:
        return f"{md['name']} {tag}: {m.get('note', '검증 없음')}"
    lin = f" (선형 {m['auc_linear_test']:.3f})" if m.get("auc_linear_test") is not None else ""
    return (f"{md['name']} {tag} ({LABELS[md['label']][1]} ≥ {md['target']:g}%): OOS AUC {m['auc_test']:.3f}{lin}"
            f" · 기준 성공률 {m['base_rate_test']:.1f}% → 상위 20% 점수 {m['rate_top20']:.1f}% (×{m['lift_top20']:.2f})"
            + (f" · 상위 20% 다음날 종가 중앙값 {m['top20_close']['median']:+.1f}% (전체 {m['base_close']['median']:+.1f}%)"
               if m.get("top20_close") and m.get("base_close") else "")
            + (f" · 목표가 청산 평균 {m['top20_tp']['mean']:+.1f}% (전체 {m['base_tp']['mean']:+.1f}%)"
               if m.get("top20_tp") and m.get("base_tp") else "")
            + f" · 검증 구간 {m['test_from']} 이후 {m['n_test']:,}건")


def main() -> int:
    ap = argparse.ArgumentParser(description="승률 점수 모델")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--test-months", type=int, default=24)
    sub.add_parser("show")
    args = ap.parse_args()
    db.init_db()
    if args.cmd == "fit":
        res = fit_all(args.test_months)
        if res:
            print("\n해석: AUC 0.5 는 무작위, 0.6 이상이면 의미 있는 신호입니다. '상위 20% 점수 성공률'이 '기준 성공률'보다 충분히 높아야 쓸모가 있고, "
                  "고가 기준 성공률이 올라도 '다음날 종가 중앙값'이 함께 오르지 않으면 변동성만 맞히는 것입니다.")
    else:
        for md in db.list_models():
            print(summary(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
