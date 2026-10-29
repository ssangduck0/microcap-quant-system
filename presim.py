"""🎲 매매 전 시뮬레이션(presim) — "지금 이 매매(이 손절·이 목표)가 동전 던지기인가?"를 사기 전에 숫자로.

2026-10-29 설계(docs/TASK_presim.md · 방구석 프로 RSC-04 / day-trader-skill 의 타임머신 아이디어를 초소형주·스윙 신호에 맞게 두 겹으로):
· 1겹(주 판정) **같은 신호의 전체 과거 재생**: 2년 × 3,000종목에서 같은 신호(⭐ 1순위 · 2순위 · 3순위 · 과매도 · 강한 유입 · PICK 유력 · 순위 10위 안 · 기준=아무 날)가
  난 모든 날(신호가 **처음 켜진 날**만)의 '그 뒤 40거래일 고가·저가·종가 %'를 `presim_ep` 에 저장해 두고, 내 손절 %·목표 %·기간을 한 번에 적용 →
  익절 먼저 % · 손절 먼저 % · 결판 안 남 % · 기대값. 표본이 수천 건의 **진짜 사건**이라 종목 하나 250일 섞기보다 믿을 만함
· 2겹(보조) **이 종목 최근 250일 부트스트랩**: 하루 묶음(갭·고가·저가·종가 %)을 3~5일 블록으로 뽑아 1만 번 — "이 종목은 요즘 더 거칠다/약하다"
· 같은 날 익절·손절 둘 다 닿으면 보수적으로 손절(p_tp) · 낙관적으로 익절(p_tp_opt) → **범위**로 보여 줌
· 수량 = 최대 손실 ÷ (매수가 − 손절가), 상한 계좌 10% · 20일 평균 거래량 1% · 판정 🟢/🪙/🔴 · 기록 `presim_log` → 🏆 성과 공표가 검증
· 컨닝 없음: 신호 판정은 그날까지 자료(희석은 그날 '전' 접수 서류)만, 결과는 그 뒤 봉만 · AI 비용 0
"""
from __future__ import annotations

import json
import math
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
import db

H = 40                    # 저장하는 '그 뒤' 봉 수(최대 기간)
MIN_BARS = 120            # 2겹·오늘 판정에 필요한 최소 일봉
LOOKBACK = 250            # 2겹 부트스트랩 재료 일수
N_SIM = 10000
BLOCK = (3, 5)            # 블록 길이(거래일)
MIN_EP = 100              # 1겹 판정에 필요한 최소 사건 수
BASE_EVERY = 20           # '기준(아무 날)' 표본: 적격일 20일마다 하나
EP_YEARS = 2.0
MAX_PRICE, MIN_DV = 20.0, 50_000.0   # 타임머신과 같은 적격 조건(초소형주 · 20일 평균 거래대금 $5만↑)
N_RECENT, N_PRIOR, OBV_MIN, VOL_UP, RSI_OVS, DIL_DAYS = 10, 20, 0.20, 1.3, 30.0, 90   # setup3 와 같은 기준
STAY_TOP = 10
COIN_GAP, COIN_EV = 10.0, 1.0       # 🪙: |익절% − 손절%| < 10%p 이고 |기대값| < 1%
F = {"ovs": 1, "ovs25": 2, "ovs20": 4, "dil": 8, "strong": 16, "money": 32, "base": 64, "pick": 256, "rank": 512}
# 키: (이름, flags 에 모두 있어야 하는 비트, onset 에 있어야 하는 비트) — onset = 그 신호가 '처음 켜진 날'(같은 구간을 여러 번 세지 않게)
KEYS = {
    "t1": ("⭐ 1순위 · RSI≤20 + 희석 없음", F["ovs20"] | F["dil"], F["ovs20"]),
    "t2": ("2순위 · RSI≤25 + 희석 없음", F["ovs25"] | F["dil"], F["ovs25"]),
    "t3": ("3순위 · 과매도 + 희석 없음", F["ovs"] | F["dil"], F["ovs"]),
    "ovs": ("과매도(RSI≤30 · 볼린저 하단)", F["ovs"], F["ovs"]),
    "strong": ("💰 강한 유입(거래량+OBV)", F["strong"], F["strong"]),
    "pick": ("🎯 PICK 유력", F["pick"], 0),
    "rank": (f"🏁 종합 순위 {STAY_TOP}위 안", F["rank"], 0),
    "base": ("전체(기준 · 아무 날)", F["base"], 0),
}
COND_ORDER = ("t1", "t2", "t3", "ovs", "strong", "base")
SOURCE_HORIZON = {"close": 5, "after": 5}   # 그 밖(저금통·PICK·순위·스크리너·직접)은 40
EP_DDL = """CREATE TABLE IF NOT EXISTS presim_ep (ticker TEXT NOT NULL, date TEXT NOT NULL, px REAL, flags INTEGER, onset INTEGER, n INTEGER,
            hi BLOB, lo BLOB, cl BLOB, PRIMARY KEY (ticker, date))"""
LOG_DDL = """CREATE TABLE IF NOT EXISTS presim_log (day TEXT NOT NULL, ticker TEXT NOT NULL, source TEXT NOT NULL, key TEXT, entry REAL, sl REAL, tp REAL, horizon INTEGER,
             p_tp REAL, p_tp_opt REAL, p_sl REAL, p_none REAL, both_pct REAL, ev_pct REAL, n_ep INTEGER, own_p_tp REAL, own_p_sl REAL, own_ev REAL, own_n INTEGER,
             verdict TEXT, detail TEXT, created_at TEXT, PRIMARY KEY (day, ticker, source))"""
VERDICT_TEXT = {"🟢": "유리한 편 — 같은 신호의 과거에서 목표가 먼저 닿은 쪽이 뚜렷이 많았어요",
                "🪙": "거의 동전 던지기 — 안 사는 것도 좋은 매매예요",
                "🔴": "불리 — 손절·목표를 다시 보거나 패스"}
WARN = "과거 움직임의 통계일 뿐이에요. 증자 공시·병합·실적 같은 사건은 반영 못 해요."


def ensure(conn) -> None:
    conn.execute(EP_DDL)
    conn.execute(LOG_DDL)


def _settings() -> dict:
    return {"account_krw": float(getattr(config, "PRESIM_ACCOUNT_KRW", 5_000_000.0)), "max_loss_krw": float(getattr(config, "PRESIM_MAX_LOSS_KRW", 50_000.0)),
            "top_n": int(getattr(config, "PRESIM_TOP_N", 10))}


def _fx() -> float:
    try:
        m = db.get_meta("usdkrw")
        return float((m or {}).get("value") or 1350.0)
    except Exception:  # noqa: BLE001
        return 1350.0


# ---------------------------------------------------------------- 신호 깃발(그날까지 자료만)
def _norm(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    d = d[~d.index.duplicated(keep="last")].sort_index()
    cols = {c.lower(): c for c in d.columns}
    ren = {cols[k]: k.capitalize() for k in ("open", "high", "low", "close", "volume") if k in cols}
    d = d.rename(columns=ren)
    if "Volume" not in d:
        d["Volume"] = 0.0
    return d.dropna(subset=["Close"])


def flags_frame(df: pd.DataFrame, dil_dates: list[str] | None = None, covered: bool = True) -> pd.DataFrame:
    """날짜별 깃발(ovs·ovs25·ovs20·strong·money·dil·eligible) + onset 비트. setup3·타임머신과 같은 기준, 전부 그날까지 자료만."""
    d = _norm(df)
    n = len(d)
    out = pd.DataFrame(index=d.index)
    if n < 35:
        return out
    c = d["Close"].astype(float).to_numpy()
    v = d["Volume"].fillna(0).astype(float).to_numpy()
    import ta
    rsi = ta.rsi(pd.Series(c), 14).to_numpy()
    mid = pd.Series(c).rolling(20).mean().to_numpy()
    sd = pd.Series(c).rolling(20).std().to_numpy()
    dv20 = pd.Series(c * v).rolling(20).mean().to_numpy()
    ob = np.cumsum(np.sign(np.diff(c, prepend=c[0])) * v)
    cs_v = np.concatenate([[0.0], np.cumsum(v)])
    rv = cs_v[N_RECENT:] - cs_v[:-N_RECENT]                                          # 최근 10봉 거래량 합(끝 인덱스 i → rv[i-9])
    rv_full = np.full(n, np.nan); rv_full[N_RECENT - 1:] = rv
    ob_prev = np.full(n, np.nan); ob_prev[N_RECENT:] = ob[:-N_RECENT]
    obv_ratio = np.where(rv_full > 0, (ob - ob_prev) / np.where(rv_full > 0, rv_full, 1), np.nan)
    rec_mean = rv_full / N_RECENT
    base_sum = np.full(n, np.nan)
    k = N_RECENT + N_PRIOR
    base_sum[k - 1:] = cs_v[k:] - cs_v[:-k]
    base_mean = (base_sum - rv_full) / N_PRIOR
    vol_ratio = np.where(base_mean > 0, rec_mean / np.where(base_mean > 0, base_mean, 1), np.nan)
    money = np.nan_to_num(obv_ratio, nan=-9) >= OBV_MIN
    strong = money & (np.nan_to_num(vol_ratio, nan=0) >= VOL_UP)
    ovs = (np.nan_to_num(rsi, nan=99) <= RSI_OVS) | (c < np.nan_to_num(mid - 2 * sd, nan=-1))
    ovs25 = np.nan_to_num(rsi, nan=99) <= 25
    ovs20 = np.nan_to_num(rsi, nan=99) <= 20
    days = np.array([x.strftime("%Y-%m-%d") for x in d.index])
    dil_ok = np.ones(n, dtype=bool)
    if dil_dates:
        fd = np.array(sorted(str(x)[:10] for x in dil_dates))
        d0 = np.array([(date.fromisoformat(x) - timedelta(days=DIL_DAYS)).isoformat() for x in days])
        lo_i, hi_i = np.searchsorted(fd, d0, side="left"), np.searchsorted(fd, days, side="left")   # d0 <= f < day
        dil_ok = (hi_i - lo_i) == 0
    dil_ok = dil_ok & bool(covered)
    elig = (c > 0) & (c < MAX_PRICE) & (np.nan_to_num(dv20, nan=0) >= MIN_DV) & (np.arange(n) >= max(k, 30))
    def onset(a):
        return a & ~np.concatenate([[False], a[:-1]])
    flags = (ovs * F["ovs"] + ovs25 * F["ovs25"] + ovs20 * F["ovs20"] + dil_ok * F["dil"] + strong * F["strong"] + money * F["money"]).astype(int)
    on = (onset(ovs) * F["ovs"] + onset(ovs25) * F["ovs25"] + onset(ovs20) * F["ovs20"] + onset(strong) * F["strong"]).astype(int)
    out["flags"], out["onset"], out["elig"], out["rsi"], out["close"] = flags, on, elig, rsi, c
    out["dv20"] = dv20
    out["adv20"] = pd.Series(v).rolling(20).mean().to_numpy()
    return out


def _paths(d: pd.DataFrame, i: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """i 번째 봉 뒤 H 봉의 고가·저가·종가 %(i 종가 대비), 모자라면 NaN."""
    c0 = float(d["Close"].iloc[i])
    hi = np.full(H, np.nan, dtype=np.float32); lo = hi.copy(); cl = hi.copy()
    seg = d.iloc[i + 1:i + 1 + H]
    m = len(seg)
    if m and c0 > 0:
        hi[:m] = (seg["High"].astype(float).to_numpy() / c0 - 1) * 100
        lo[:m] = (seg["Low"].astype(float).to_numpy() / c0 - 1) * 100
        cl[:m] = (seg["Close"].astype(float).to_numpy() / c0 - 1) * 100
    return hi, lo, cl, m


def _extra_flags(conn) -> dict[tuple[str, str], int]:
    """PICK 유력 · 종합 순위 10위 안 — 이력 표에서(2026-10 부터 쌓임)."""
    out: dict[tuple[str, str], int] = {}
    for sql, bit in (("SELECT ticker, date FROM pick_hist WHERE status='유력' AND COALESCE(weak,0)=0", F["pick"]),
                     (f"SELECT ticker, date FROM rank_hist WHERE rank <= {STAY_TOP}", F["rank"])):
        try:
            for t, d in conn.execute(sql):
                out[(t, d)] = out.get((t, d), 0) | bit
        except Exception:  # noqa: BLE001
            pass
    return out


def _load_bars(conn, tickers: list[str], since: str) -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    q = ",".join("?" * len(tickers))
    df = pd.read_sql_query(f"SELECT ticker, date, open, high, low, close, volume FROM daily_prices WHERE date >= ? AND ticker IN ({q}) ORDER BY date", conn, params=[since, *tickers])
    res = {}
    for t, g in df.groupby("ticker"):
        res[t] = g.set_index(pd.to_datetime(g["date"])).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    return res


def build_episodes(conn, years: float = EP_YEARS, out=print, tickers: list[str] | None = None, bars: dict | None = None, today: date | None = None) -> dict:
    """1겹 재료: 종목마다 신호가 처음 켜진 날(+ 기준 표본 · PICK · 순위)의 '그 뒤 40봉' 경로를 presim_ep 에 저장. 이어하기: 이미 40봉 다 있는 날은 건너뜀."""
    ensure(conn)
    today = today or date.today()
    start = (today - timedelta(days=int(365 * years))).isoformat()
    since = (date.fromisoformat(start) - timedelta(days=200)).isoformat()
    if tickers is None:
        if bars is not None:
            tickers = sorted(bars)
        else:
            tickers = [r[0] for r in conn.execute("SELECT ticker FROM daily_prices WHERE date >= ? GROUP BY ticker HAVING COUNT(*) >= ? ORDER BY ticker", (since, MIN_BARS))]
    import timemachine as tm
    dil = tm._dil_dates(conn, set(tickers))
    cov = tm._covered(conn)
    extra = _extra_flags(conn)
    have = {(r[0], r[1]): r[2] for r in conn.execute("SELECT ticker, date, n FROM presim_ep")}
    res = {"tickers": len(tickers), "new": 0, "updated": 0, "rows": 0}
    for k in range(0, len(tickers), 300):
        part = tickers[k:k + 300]
        data = {t: bars[t] for t in part if t in bars} if bars is not None else _load_bars(conn, part, since)
        rows = []
        for t, df in data.items():
            try:
                d = _norm(df)
                if len(d) < 35:
                    continue
                ff = flags_frame(d, dil.get(t, []), covered=t in cov)
                if ff.empty:
                    continue
                days = [x.strftime("%Y-%m-%d") for x in d.index]
                base_ctr = 0
                for i, day in enumerate(days):
                    if day < start or i + 1 >= len(d) or not bool(ff["elig"].iloc[i]):
                        continue
                    fl, on = int(ff["flags"].iloc[i]), int(ff["onset"].iloc[i])
                    base_ctr += 1
                    if base_ctr % BASE_EVERY == 0:
                        fl |= F["base"]
                    fl |= extra.get((t, day), 0)
                    if not on and not (fl & (F["base"] | F["pick"] | F["rank"])):
                        continue
                    prev_n = have.get((t, day))
                    if prev_n is not None and prev_n >= H:
                        continue
                    hi, lo, cl, m = _paths(d, i)
                    if m == 0:
                        continue
                    rows.append((t, day, float(d["Close"].iloc[i]), fl, on, m, hi.tobytes(), lo.tobytes(), cl.tobytes()))
                    res["new" if prev_n is None else "updated"] += 1
            except Exception as e:  # noqa: BLE001
                out(f"presim 사건 만들기 실패 {t}: {e}")
        if rows:
            conn.executemany("INSERT OR REPLACE INTO presim_ep VALUES (?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
        if len(tickers) > 300:
            out(f"🎲 사건 표: {min(k + 300, len(tickers))}/{len(tickers)}종목")
    res["rows"] = conn.execute("SELECT COUNT(*) FROM presim_ep").fetchone()[0]
    out(f"🎲 사건 표(presim_ep): 종목 {res['tickers']} · 새로 {res['new']} · 갱신 {res['updated']} · 전체 {res['rows']:,}건")
    return res


def episodes(conn, key: str) -> dict:
    """키에 맞는 사건들의 경로 배열. {"hi","lo","cl": (E×H), "n": (E,), "meta": DataFrame(ticker, date, px)}"""
    ensure(conn)
    name, need, need_on = KEYS[key]
    sql = "SELECT ticker, date, px, n, hi, lo, cl FROM presim_ep WHERE (flags & ?) = ?" + (" AND (onset & ?) = ?" if need_on else "")
    args = [need, need] + ([need_on, need_on] if need_on else [])
    rows = conn.execute(sql, args).fetchall()
    if not rows:
        return {"key": key, "name": name, "n": 0}
    hi = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
    lo = np.stack([np.frombuffer(r[5], dtype=np.float32) for r in rows])
    cl = np.stack([np.frombuffer(r[6], dtype=np.float32) for r in rows])
    meta = pd.DataFrame([(r[0], r[1], r[2]) for r in rows], columns=["ticker", "date", "px"])
    return {"key": key, "name": name, "n": len(rows), "hi": hi, "lo": lo, "cl": cl, "bars": np.array([r[3] for r in rows]), "meta": meta}


def ep_counts(conn) -> dict[str, int]:
    out = {}
    for k in KEYS:
        name, need, need_on = KEYS[k]
        sql = "SELECT COUNT(*) FROM presim_ep WHERE (flags & ?) = ?" + (" AND (onset & ?) = ?" if need_on else "")
        try:
            out[k] = conn.execute(sql, [need, need] + ([need_on, need_on] if need_on else [])).fetchone()[0]
        except Exception:  # noqa: BLE001
            out[k] = 0
    return out


# ---------------------------------------------------------------- 결과 계산(1겹·2겹 공통)
def outcomes(hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, sl_pct: float, tp_pct: float, horizon: int, bars: np.ndarray | None = None) -> dict:
    """경로(E×≥horizon, % 단위)에 손절 −sl_pct% · 목표 +tp_pct% 적용. 같은 날 둘 다면 보수적=손절(p_tp) · 낙관적=익절(p_tp_opt).
    기간 안에 못 닿고 봉도 모자란 사건(미완)은 뺌."""
    h = int(max(1, min(horizon, hi.shape[1])))
    hi_, lo_, cl_ = hi[:, :h], lo[:, :h], cl[:, :h]
    sl_hit = np.nan_to_num(lo_, nan=np.inf) <= -abs(sl_pct)
    tp_hit = np.nan_to_num(hi_, nan=-np.inf) >= abs(tp_pct)
    big = h + 1
    i_sl = np.where(sl_hit.any(1), sl_hit.argmax(1), big)
    i_tp = np.where(tp_hit.any(1), tp_hit.argmax(1), big)
    avail = (bars if bars is not None else (~np.isnan(cl_)).sum(1))
    complete = np.asarray(avail) >= h
    none_mask = (i_sl >= big) & (i_tp >= big)
    counted = ~(none_mask & ~complete)
    E = int(counted.sum())
    r = {"n": E, "p_tp": None, "p_tp_opt": None, "p_sl": None, "p_none": None, "both_pct": None, "ev_pct": None, "ev_opt": None, "none_avg": None, "horizon": h}
    if E == 0:
        return r
    sl_first = (i_sl < i_tp) & counted
    tp_first = (i_tp < i_sl) & counted
    both = (i_sl == i_tp) & (i_sl < big) & counted
    none = none_mask & counted
    last_close = np.nan_to_num(cl_[:, h - 1], nan=0.0)
    pct = lambda m: round(float(m.sum()) / E * 100, 1)  # noqa: E731
    r.update(p_tp=pct(tp_first), p_tp_opt=pct(tp_first | both), p_sl=pct(sl_first | both), p_none=pct(none), both_pct=pct(both))
    out_cons = np.where(tp_first, abs(tp_pct), np.where(sl_first | both, -abs(sl_pct), last_close))
    out_opt = np.where(tp_first | both, abs(tp_pct), np.where(sl_first, -abs(sl_pct), last_close))
    r["ev_pct"] = round(float(out_cons[counted].mean()), 2)
    r["ev_opt"] = round(float(out_opt[counted].mean()), 2)
    r["none_avg"] = round(float(last_close[none].mean()), 2) if none.any() else None
    return r


def simulate(df: pd.DataFrame, entry: float, sl: float, tp: float, horizon: int, n: int = N_SIM, block: tuple[int, int] = BLOCK, seed: int | None = None,
             lookback: int = LOOKBACK) -> dict:
    """2겹: 이 종목 최근 lookback 일의 하루 묶음(전일 종가 대비 고가·저가·종가 %)을 블록으로 뽑아 n 번 돌림 → outcomes 와 같은 결과 + n_days."""
    d = _norm(df)
    if len(d) < MIN_BARS or not entry or entry <= 0 or sl is None or tp is None:
        return {"ok": False, "n_days": int(len(d)), "why": f"일봉 {len(d)}일 < {MIN_BARS}일" if len(d) < MIN_BARS else "입력 부족"}
    d = d.tail(lookback + 1)
    c = d["Close"].astype(float).to_numpy()
    prev = c[:-1]
    h_ = d["High"].astype(float).to_numpy()[1:] / prev - 1
    l_ = d["Low"].astype(float).to_numpy()[1:] / prev - 1
    c_ = c[1:] / prev - 1
    ok = np.isfinite(h_) & np.isfinite(l_) & np.isfinite(c_) & (prev > 0)
    h_, l_, c_ = h_[ok], l_[ok], c_[ok]
    m = len(c_)
    if m < 60:
        return {"ok": False, "n_days": m, "why": "쓸 수 있는 하루 묶음이 60개 미만"}
    rng = np.random.default_rng(seed)
    hz = int(max(1, horizon))
    idx = np.empty((n, hz), dtype=np.int64)
    filled = 0
    while filled < hz:
        L = int(rng.integers(block[0], block[1] + 1))
        L = min(L, hz - filled)
        starts = rng.integers(0, m - L + 1, size=n)
        idx[:, filled:filled + L] = starts[:, None] + np.arange(L)[None, :]
        filled += L
    sl_pct, tp_pct = (1 - sl / entry) * 100, (tp / entry - 1) * 100
    # 경로: 종가 누적 × (1+%) — 하루 고가·저가는 전일 종가 기준 %
    close_path = np.cumprod(1 + c_[idx], axis=1)                      # entry 대비 배수
    prev_path = np.concatenate([np.ones((n, 1)), close_path[:, :-1]], axis=1)
    hi = (prev_path * (1 + h_[idx]) - 1) * 100
    lo = (prev_path * (1 + l_[idx]) - 1) * 100
    cl = (close_path - 1) * 100
    r = outcomes(hi.astype(np.float32), lo.astype(np.float32), cl.astype(np.float32), sl_pct, tp_pct, hz, bars=np.full(n, hz))
    r.update(ok=True, n_days=m, sl_pct=round(sl_pct, 2), tp_pct=round(tp_pct, 2))
    return r


def size(entry: float, sl: float, account_krw: float, max_loss_krw: float, fx: float, adv20: float | None = None, cap_pct: float = 10.0, adv_pct: float = 1.0) -> dict:
    """수량: 최대 손실(달러) ÷ (매수가 − 손절가). 상한 = 계좌의 cap_pct% · 20일 평균 거래량의 adv_pct%."""
    fx = fx or 1350.0
    acc_usd, loss_usd = float(account_krw) / fx, float(max_loss_krw) / fx
    r = {"shares": 0, "cost_usd": 0.0, "cost_krw": 0.0, "risk_usd": 0.0, "max_loss_usd": round(loss_usd, 2), "account_usd": round(acc_usd, 2), "caps": [], "why": ""}
    if not entry or entry <= 0 or sl is None or sl >= entry:
        r["why"] = "손절가가 매수가보다 낮아야 수량을 셀 수 있어요"
        return r
    per = entry - sl
    base = math.floor(loss_usd / per)
    shares = base
    cap_acc = math.floor(acc_usd * cap_pct / 100 / entry)
    if shares > cap_acc:
        shares = cap_acc
        r["caps"].append(f"계좌의 {cap_pct:g}% 상한({cap_acc:,}주)")
    if adv20 and adv20 > 0:
        cap_adv = math.floor(adv20 * adv_pct / 100)
        if shares > cap_adv:
            shares = cap_adv
            r["caps"].append(f"20일 평균 거래량의 {adv_pct:g}% 상한({cap_adv:,}주)")
    shares = max(0, int(shares))
    r.update(shares=shares, cost_usd=round(shares * entry, 2), cost_krw=round(shares * entry * fx), risk_usd=round(shares * per, 2), base_shares=int(base))
    r["why"] = (f"최대 손실 ${loss_usd:,.0f} ÷ 리스크 폭 ${per:.4g} = {base:,}주" + (" → " + " · ".join(r["caps"]) if r["caps"] else ""))
    return r


def verdict(p_tp, p_sl, ev) -> tuple[str, str]:
    if p_tp is None or p_sl is None or ev is None:
        return "❔", "자료 부족"
    if p_tp - p_sl >= COIN_GAP and ev > COIN_EV:
        return "🟢", VERDICT_TEXT["🟢"]
    if p_sl - p_tp >= COIN_GAP and ev < -COIN_EV:
        return "🔴", VERDICT_TEXT["🔴"]
    return "🪙", VERDICT_TEXT["🪙"]


# ---------------------------------------------------------------- 기본값 · 오늘 판정
def defaults(df: pd.DataFrame, source: str = "scr", box: tuple[float | None, float | None] | None = None) -> dict:
    """매수가 = 최근 종가 · 손절 = 레벨 맵 1차 지지 하단(저금통은 박스 하단×0.95, 없으면 −10%) · 목표 = 1차 저항(저금통은 박스 상단, 없으면 +30%) · 기간."""
    d = _norm(df)
    entry = float(d["Close"].iloc[-1])
    sl = tp = None
    lo_b, hi_b = (box or (None, None))
    if source == "piggy" and lo_b:
        sl = float(lo_b) * 0.95
    if source == "piggy" and hi_b:
        tp = float(hi_b)
    if sl is None or tp is None:
        try:
            import screener
            px = pd.DataFrame({"date": [x.strftime("%Y-%m-%d") for x in d.index], "open": d["Open"].astype(float).to_numpy() if "Open" in d else d["Close"].to_numpy(),
                               "high": d["High"].astype(float).to_numpy(), "low": d["Low"].astype(float).to_numpy(), "close": d["Close"].astype(float).to_numpy()})
            lv = screener.levels(px)
            if sl is None and lv.get("support") and lv["support"][0] and lv["support"][0] < entry:
                sl = float(lv["support"][0])
            if tp is None and lv.get("resistance1") and lv["resistance1"] > entry * 1.02:
                tp = float(lv["resistance1"])
        except Exception:  # noqa: BLE001
            pass
    if sl is None or sl >= entry:
        sl = entry * 0.9
    if tp is None or tp <= entry:
        tp = entry * 1.3
    return {"entry": entry, "sl": round(sl, 4), "tp": round(tp, 4), "horizon": SOURCE_HORIZON.get(source, 40)}


def pick_key(flags_now: int, source: str, counts: dict[str, int]) -> str:
    """오늘 이 종목의 조건으로 쓸 1겹 키 — 출처 키(pick·rank)가 사건 MIN_EP 이상이면 그것, 아니면 조건 키(⭐1 → 2 → 3 → 과매도 → 강한 유입 → 기준) 중 첫 번째."""
    order = ([source] if source in ("pick", "rank") else []) + list(COND_ORDER)
    for k in order:
        name, need, need_on = KEYS[k]
        has = (k == "base") or (k in ("pick", "rank")) or ((flags_now & need) == need)
        if has and counts.get(k, 0) >= MIN_EP:
            return k
    return "base"


def run_one(conn, ticker: str, df: pd.DataFrame, source: str = "scr", day: str | None = None, *, entry: float | None = None, sl: float | None = None,
            tp: float | None = None, horizon: int | None = None, box=None, n_sim: int = N_SIM, seed: int | None = None, dil_dates: list[str] | None = None,
            covered: bool = True, counts: dict | None = None, cache: dict | None = None, save: bool = True, now: datetime | None = None) -> dict:
    """한 종목 한 번: 기본값 채우기 → 1겹(같은 신호 전체 과거) → 2겹(이 종목 250일) → 수량 → 판정 → presim_log."""
    ensure(conn)
    d = _norm(df)
    if len(d) < MIN_BARS:
        return {"ok": False, "ticker": ticker, "why": f"일봉 {len(d)}일 < {MIN_BARS}일 — 자료 부족"}
    base = defaults(d, source, box)
    entry = float(entry or base["entry"]); sl = float(sl if sl is not None else base["sl"]); tp = float(tp if tp is not None else base["tp"])
    hz = int(horizon or base["horizon"])
    day = day or d.index[-1].strftime("%Y-%m-%d")
    if not (0 < sl < entry < tp):
        return {"ok": False, "ticker": ticker, "why": "손절가 < 매수가 < 목표가 여야 해요"}
    sl_pct, tp_pct = (1 - sl / entry) * 100, (tp / entry - 1) * 100
    ff = flags_frame(d, dil_dates or [], covered=covered)
    flags_now = int(ff["flags"].iloc[-1]) if len(ff) else 0
    adv20 = float(ff["adv20"].iloc[-1]) if len(ff) and not pd.isna(ff["adv20"].iloc[-1]) else None
    counts = counts if counts is not None else ep_counts(conn)
    key = pick_key(flags_now, source, counts)
    cache = cache if cache is not None else {}
    ep = cache.get(key) or episodes(conn, key)
    cache[key] = ep
    l1 = outcomes(ep["hi"], ep["lo"], ep["cl"], sl_pct, tp_pct, hz, bars=ep["bars"]) if ep.get("n") else {"n": 0}
    l1["key"], l1["name"] = key, KEYS[key][0]
    own = simulate(d, entry, sl, tp, hz, n=n_sim, seed=seed)
    st = _settings()
    sz = size(entry, sl, st["account_krw"], st["max_loss_krw"], _fx(), adv20)
    if l1.get("n", 0) >= MIN_EP:
        vd, txt = verdict(l1["p_tp"], l1["p_sl"], l1["ev_pct"])
        basis = "같은 신호 전체 과거"
    elif own.get("ok"):
        vd, txt = verdict(own["p_tp"], own["p_sl"], own["ev_pct"])
        basis = "이 종목 최근 250일(같은 신호 표본 부족 ⚠️)"
    else:
        vd, txt, basis = "❔", "자료 부족", "없음"
    notes = []
    if l1.get("n", 0) >= MIN_EP and own.get("ok") and own["p_tp"] is not None and l1["p_tp"] is not None and abs(own["p_tp"] - l1["p_tp"]) >= 15:
        notes.append(f"⚠️ 이 종목 최근 성격(익절 {own['p_tp']:.0f}%)이 같은 신호 평균(익절 {l1['p_tp']:.0f}%)과 많이 달라요")
    if l1.get("both_pct") and l1["both_pct"] >= 10:
        notes.append(f"같은 날 익절·손절 둘 다 닿은 날이 {l1['both_pct']:.0f}% — 범위(보수 {l1['p_tp']:.0f}% ~ 낙관 {l1['p_tp_opt']:.0f}%)로 보세요")
    res = {"ok": True, "ticker": ticker, "source": source, "day": day, "entry": entry, "sl": sl, "tp": tp, "horizon": hz, "sl_pct": round(sl_pct, 2), "tp_pct": round(tp_pct, 2),
           "key": key, "layer1": l1, "own": own, "size": sz, "verdict": vd, "verdict_text": txt, "basis": basis, "notes": notes, "warn": WARN, "flags_now": flags_now}
    if save:
        detail = json.dumps({"layer1": {k: v for k, v in l1.items() if k not in ("meta",)}, "own": own, "size": sz, "basis": basis, "notes": notes, "sl_pct": res["sl_pct"], "tp_pct": res["tp_pct"]},
                            ensure_ascii=False, default=float)
        conn.execute("INSERT OR REPLACE INTO presim_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (day, ticker, source, key, entry, sl, tp, hz, l1.get("p_tp"), l1.get("p_tp_opt"), l1.get("p_sl"), l1.get("p_none"), l1.get("both_pct"), l1.get("ev_pct"), l1.get("n", 0),
                      own.get("p_tp"), own.get("p_sl"), own.get("ev_pct"), own.get("n_days"), vd, detail, (now or datetime.now(timezone.utc)).isoformat()))
        conn.commit()
    return res


# ---------------------------------------------------------------- 아침 자동 실행 · 읽기
def candidates(conn, top_n: int | None = None) -> list[dict]:
    """저금통 전체 + 오늘 PICK 유력(pick_hist 최신 날) + 종합 순위 상위 N(rank_hist 최신 날). 같은 종목은 저금통 > PICK > 순위 순으로 한 번."""
    top_n = _settings()["top_n"] if top_n is None else int(top_n)
    out: dict[str, dict] = {}
    try:
        import piggy
        it = piggy.items()
        for r in it.to_dict("records"):
            out.setdefault(str(r["ticker"]), {"ticker": str(r["ticker"]), "source": "piggy", "box": (r.get("box_low"), r.get("box_high"))})
    except Exception:  # noqa: BLE001
        pass
    try:
        last = conn.execute("SELECT MAX(date) FROM pick_hist").fetchone()[0]
        if last:
            for (t,) in conn.execute("SELECT ticker FROM pick_hist WHERE date=? AND status='유력' AND COALESCE(weak,0)=0 ORDER BY rank", (last,)):
                out.setdefault(t, {"ticker": t, "source": "pick", "box": None})
    except Exception:  # noqa: BLE001
        pass
    if top_n > 0:
        try:
            last = conn.execute("SELECT MAX(date) FROM rank_hist").fetchone()[0]
            if last:
                for (t,) in conn.execute("SELECT ticker FROM rank_hist WHERE date=? AND rank<=? ORDER BY rank", (last, top_n)):
                    out.setdefault(t, {"ticker": t, "source": "rank", "box": None})
        except Exception:  # noqa: BLE001
            pass
    return list(out.values())


def morning(conn, out=print, now: datetime | None = None, bars: dict | None = None, build: bool = True, top_n: int | None = None, n_sim: int = N_SIM) -> dict:
    """아침 작업: (이어하기) 사건 표 갱신 → 후보마다 기본값으로 실행 → presim_log. 종목마다 try/except, 총 시간 로그."""
    import time
    t0 = time.time()
    ensure(conn)
    if build:
        try:
            build_episodes(conn, out=out, bars=bars)
        except Exception as e:  # noqa: BLE001
            out(f"🎲 사건 표 갱신 실패(지난 표로 계속): {e}")
    cands = candidates(conn, top_n)
    res = {"n": len(cands), "done": 0, "skip": 0, "verdicts": {"🟢": 0, "🪙": 0, "🔴": 0, "❔": 0}, "sec": 0.0}
    if not cands:
        out("🎲 매매 전 시뮬레이션: 후보 없음")
        return res
    tickers = sorted({c["ticker"] for c in cands})
    since = (date.today() - timedelta(days=420)).isoformat()
    data = {t: bars[t] for t in tickers if t in bars} if bars is not None else _load_bars(conn, tickers, since)
    import timemachine as tm
    dil = tm._dil_dates(conn, set(tickers))
    cov = tm._covered(conn)
    counts = ep_counts(conn)
    cache: dict = {}
    for c in cands:
        t = c["ticker"]
        df = data.get(t)
        if df is None or len(df) < MIN_BARS:
            res["skip"] += 1
            continue
        try:
            r = run_one(conn, t, df, c["source"], box=c.get("box"), n_sim=n_sim, dil_dates=dil.get(t, []), covered=t in cov, counts=counts, cache=cache, now=now, seed=7)
            if r.get("ok"):
                res["done"] += 1
                res["verdicts"][r["verdict"]] = res["verdicts"].get(r["verdict"], 0) + 1
            else:
                res["skip"] += 1
        except Exception as e:  # noqa: BLE001
            res["skip"] += 1
            out(f"🎲 {t} 실패: {e}")
    res["sec"] = round(time.time() - t0, 1)
    v = res["verdicts"]
    out(f"🎲 매매 전 시뮬레이션: {res['done']}종목 · 🟢{v['🟢']} 🪙{v['🪙']} 🔴{v['🔴']} · 자료 부족 {res['skip']} · {res['sec']}초")
    return res


def latest(conn, ticker: str, days: int = 3) -> dict | None:
    """카드 배지용: 최근 days 일 안 가장 새 기록 한 줄(없으면 None)."""
    try:
        ensure(conn)
        since = (date.today() - timedelta(days=days)).isoformat()
        r = conn.execute("SELECT * FROM presim_log WHERE ticker=? AND day>=? ORDER BY day DESC, created_at DESC LIMIT 1", (ticker, since)).fetchone()
        return dict(r) if r else None
    except Exception:  # noqa: BLE001
        return None


def latest_map(conn, tickers, days: int = 3) -> dict[str, dict]:
    tickers = [t for t in dict.fromkeys(tickers) if t]
    if not tickers:
        return {}
    try:
        ensure(conn)
        since = (date.today() - timedelta(days=days)).isoformat()
        q = ",".join("?" * len(tickers))
        rows = conn.execute(f"SELECT * FROM presim_log WHERE ticker IN ({q}) AND day>=? ORDER BY day, created_at", [*tickers, since]).fetchall()
        return {r["ticker"]: dict(r) for r in rows}     # 나중 행이 덮어씀 = 가장 새 것
    except Exception:  # noqa: BLE001
        return {}


def log_rows(conn, days: int = 120) -> pd.DataFrame:
    ensure(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    return pd.read_sql_query("SELECT * FROM presim_log WHERE day >= ? ORDER BY day DESC, ticker", conn, params=[since])
