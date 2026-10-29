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
import zlib
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
import db

H = 40                    # 저장하는 '그 뒤' 봉 수(최대 기간)
RECENT_REDO = 5           # 최근 H+5 봉 안에 시작한 사건은 n 과 상관없이 매번 다시 씀 — 2026-10-29 22:52 KST(09:52 ET, 장중) 수동 실행 때 진행 중인 오늘 봉이
                          # 103개 사건의 40번째 봉으로 굳은 것을 보고 추가(장중 봉 제외와 함께 자가 치유 · 자료 정정도 반영). 비용: 아침마다 약 1만 행 재작성(수 초)
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
COIN_GAP, COIN_EV = 10.0, 1.0       # (2겹만 있을 때의 옛 판정) 🪙: |익절% − 손절%| < 10%p 이고 |기대값| < 1%
# 2026-10-30 기준 대비 우위 판정(docs/presim_methods_survey_2026-10.md 5절 A·B·D·F): 같은 계획을 '기준(아무 날)' 사건에도 적용해 기대값 차이(우위)로 판정.
# 표본이 적으면 우위를 n_eff/(n_eff+SHRINK_K) 만큼 깎음(empirical Bayes 식 수축) · n_eff = 같은 종목의 겹치는 사건(±60일)을 1/(1+k) 로 덜 센 유효 표본.
SHRINK_K = 100.0          # 수축 가짜 표본 수: n_eff 100 이면 우위의 절반만 인정
EDGE_MIN = 1.0            # 🟢/🔴 문턱(%p, 보정 뒤)
EFF_MIN = 50.0            # 판정에 필요한 최소 유효 표본(수축이 이미 표본 크기를 벌하므로 MIN_EP 의 절반 — 10/30 복사본 시험에서 저금통+희석 없음 134건·유효 73이 우위 +2.4 인데 🪙 로 막힌 것을 보고)
RECENT_DAYS = 180         # '최근 창' = 최근 180일(≈120거래일) 사건만의 성적을 따로(쇠퇴 감지, OddsMaker 식)
OVERLAP_DAYS = 60         # 겹침 가중 창(달력일 ≈ H 거래일)
EP_VERSION = "3"         # 사건 표 버전 — 바뀌면 다음 아침에 전체를 한 번 다시 씀(v2: 🐷 저금통 재생 키 + sl_pct/tp_pct 열 · v3 2026-10-30: 🩹 pricefix 가 병합 종목 일봉을 환산한 뒤 다시 씀 — 같은 아침에 pricefix 가 먼저 돈다)
F = {"ovs": 1, "ovs25": 2, "ovs20": 4, "dil": 8, "strong": 16, "money": 32, "base": 64, "pick": 256, "rank": 512, "piggy": 1024}
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
    # 🐷 저금통 규칙 재생(2026-10-30, docs/TASK_presim.md 11절): 1,000원 미만 · 안정성 ≥60 · 반등 ≥2 · 폭 15~80% · 거래대금 · 최근 이탈 없음 을 그날까지 60봉으로 재생해
    # 🟢 저점 구간(박스 아래 20%)에 처음 들어온 날. 손절·목표는 사건마다 '그날의 박스'(하단×0.95 / 상단)를 sl_pct·tp_pct 열에 저장 → outcomes 가 사건별로 적용
    "piggy": ("🐷 저금통 규칙 + 저점 구간 진입(그날 박스 손절·목표)", F["piggy"], F["piggy"]),
    "piggy_nd": ("🐷 저금통 규칙 + 저점 진입 + 희석 없음", F["piggy"] | F["dil"], F["piggy"]),
}
BOX_KEYS = ("piggy_nd", "piggy")   # 사건별 박스 손절·목표를 가진 키(희석 없음 쪽을 먼저)
COND_ORDER = ("t1", "t2", "t3", "ovs", "strong", "base")
SOURCE_HORIZON = {"close": 5, "after": 5}   # 그 밖(저금통·PICK·순위·스크리너·직접)은 40
EP_DDL = """CREATE TABLE IF NOT EXISTS presim_ep (ticker TEXT NOT NULL, date TEXT NOT NULL, px REAL, flags INTEGER, onset INTEGER, n INTEGER,
            hi BLOB, lo BLOB, cl BLOB, PRIMARY KEY (ticker, date))"""
EP_ADD = (("sl_pct", "REAL"), ("tp_pct", "REAL"))                                                       # v2: 사건별 계획(🐷 키만, 나머지 NULL)
LOG_ADD = (("edge", "REAL"), ("edge_raw", "REAL"), ("ev_base", "REAL"), ("n_eff", "REAL"), ("p0", "REAL"), ("recent_n", "INTEGER"), ("recent_ev", "REAL"), ("plan", "TEXT"))
LOG_DDL = """CREATE TABLE IF NOT EXISTS presim_log (day TEXT NOT NULL, ticker TEXT NOT NULL, source TEXT NOT NULL, key TEXT, entry REAL, sl REAL, tp REAL, horizon INTEGER,
             p_tp REAL, p_tp_opt REAL, p_sl REAL, p_none REAL, both_pct REAL, ev_pct REAL, n_ep INTEGER, own_p_tp REAL, own_p_sl REAL, own_ev REAL, own_n INTEGER,
             verdict TEXT, detail TEXT, created_at TEXT, PRIMARY KEY (day, ticker, source))"""
VERDICT_TEXT = {"🟢": "기준보다 유리 — 같은 신호의 과거 기대값이 '아무 날'보다 뚜렷이 높았어요",
                "🪙": "기준과 비슷(동전 던지기) — 안 사는 것도 좋은 매매예요",
                "🔴": "기준보다 불리 — 손절·목표를 다시 보거나 패스"}
VERDICT_TEXT_ABS = {"🟢": "유리한 편(이 종목 최근 250일만) — 목표가 먼저 닿은 쪽이 뚜렷이 많았어요",
                    "🪙": "거의 동전 던지기(이 종목 최근 250일만) — 안 사는 것도 좋은 매매예요",
                    "🔴": "불리(이 종목 최근 250일만) — 손절·목표를 다시 보거나 패스"}
BASE_TEXT = "같은 신호 정보 없음 — '아무 날'과 같은 통계라 우위를 잴 수 없어요(기준 숫자만 참고)"
WARN = "과거 움직임의 통계일 뿐이에요. 증자 공시·병합·실적 같은 사건은 반영 못 해요."


def ensure(conn) -> None:
    conn.execute(EP_DDL)
    conn.execute(LOG_DDL)
    for tbl, cols in (("presim_ep", EP_ADD), ("presim_log", LOG_ADD)):   # 기존 표 보존 — 열만 더함
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
        for c, t in cols:
            if c not in have:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {c} {t}")


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


def piggy_flags(d: pd.DataFrame, fx: float | None = None, rules: dict | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """🐷 저금통 규칙 재생(그날까지 60봉만 → 컨닝 없음): 날짜별 (규칙 통과 + 🟢 저점 구간, 처음 들어온 날, 손절 %, 목표 %).
    규칙 = piggy.rules()(관리 모드 값: 1,000원 미만 · 안정성 ≥60 · 반등 ≥2 · 폭 AUTO_WIDTH · 거래대금 ≥$2만 · 최근 이탈 없음) — ⑥ 주식수는 과거 재생이 안 돼 뺌.
    손절 = 박스 하단×0.95 · 목표 = 박스 상단(가상매매 open_piggy 와 같음). 환율은 지금 값(과거 환율 차이는 무시)."""
    import piggy
    fx = fx or _fx()
    r = rules or piggy.rules()
    n = len(d)
    zone = np.zeros(n, dtype=bool)
    sl = np.full(n, np.nan)
    tp = np.full(n, np.nan)
    if n < 61:
        return zone, zone.copy(), sl, tp
    close = d["Close"].astype(float).to_numpy()
    cheap = close * fx < r["max_krw"]
    for i in range(60, n):
        if not cheap[i]:
            continue
        m = piggy.box_metrics(d.iloc[i - 59:i + 1])
        if not m:
            continue
        ok = (m["score"] >= r["score"] and m["bounces"] >= r["bounces"] and piggy.AUTO_WIDTH[0] <= m["width_pct"] <= piggy.AUTO_WIDTH[1]
              and m["dollar_vol"] >= r["dvol"] and not m["recent_break"])
        if not ok:
            continue
        sup, res = m["support"], m["resistance"]
        if close[i] >= sup * 0.95 and (close[i] - sup) / (res - sup) <= piggy.BAND:
            zone[i] = True
            sl[i] = max(1.0, (1 - sup * 0.95 / close[i]) * 100)
            tp[i] = (res / close[i] - 1) * 100
    on = zone & ~np.concatenate([[False], zone[:-1]])
    return zone, on, sl, tp


def _load_bars(conn, tickers: list[str], since: str, now: datetime | None = None) -> dict[str, pd.DataFrame]:
    """daily_prices 에서 일봉 읽기. 미국 정규장이 끝나기 전(16:20 ET 이전)에 돌리면 스캐너가 쓰는 '오늘' 봉은 진행 중(고가·저가·종가 미확정)이라 뺀다
    (cases.drop_incomplete_last_bar 와 같은 규칙 · 아침 작업 07:30 KST 는 장 마감 뒤라 영향 없음). 2026-10-29 장중 수동 실행 때 진행 중 봉이 매수가·2겹·사건 표에 섞인 것을 보고 추가."""
    if not tickers:
        return {}
    import cases
    q = ",".join("?" * len(tickers))
    df = pd.read_sql_query(f"SELECT ticker, date, open, high, low, close, volume FROM daily_prices WHERE date >= ? AND ticker IN ({q}) ORDER BY date", conn, params=[since, *tickers])
    res = {}
    for t, g in df.groupby("ticker"):
        d = g.set_index(pd.to_datetime(g["date"])).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
        d = cases.drop_incomplete_last_bar(d, now)
        if d is not None and len(d):
            res[t] = d
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
    ver = (db.get_meta("presim_ep_ver") or {}).get("value")
    rebuild_all = ver != EP_VERSION   # 표 버전이 바뀌면(키·열 추가) 한 번 전체를 다시 씀
    if rebuild_all:
        out(f"🎲 사건 표 버전 {ver or '없음'} → {EP_VERSION}: 전체를 다시 씁니다(한 번, 수 분)")
    if rebuild_all:   # 파생 표(일봉에서 언제든 다시 만듦)라 옛 행을 비우고 새로 씀 — 안 비우면 기준 표본 날짜가 바뀐 옛 행이 남아 두 배로 셈
        conn.execute("DELETE FROM presim_ep")
        conn.commit()
    have = {} if rebuild_all else {(r[0], r[1]): r[2] for r in conn.execute("SELECT ticker, date, n FROM presim_ep")}
    fx_now = _fx()
    try:
        import piggy as _pg
        pg_rules = _pg.rules()
    except Exception:  # noqa: BLE001
        pg_rules = None
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
                try:
                    pz, pon, psl, ptp = piggy_flags(d, fx_now, pg_rules)   # 🐷 저금통 규칙 재생(1,000원 미만인 날만 계산)
                except Exception as e:  # noqa: BLE001
                    out(f"presim 저금통 재생 실패 {t}: {e}")
                    pz = pon = np.zeros(len(d), dtype=bool); psl = ptp = np.full(len(d), np.nan)
                days = [x.strftime("%Y-%m-%d") for x in d.index]
                t_hash = zlib.crc32(t.encode()) % BASE_EVERY   # 기준 표본 날짜를 종목·날짜로 고정(시작일 카운터면 시작일이 하루 밀릴 때마다 표본이 전부 바뀜 — 10/30 발견)
                for i, day in enumerate(days):
                    if day < start or i + 1 >= len(d) or not bool(ff["elig"].iloc[i]):
                        continue
                    fl, on = int(ff["flags"].iloc[i]), int(ff["onset"].iloc[i])
                    if (date.fromisoformat(day).toordinal() + t_hash) % BASE_EVERY == 0:
                        fl |= F["base"]
                    fl |= extra.get((t, day), 0)
                    if pz[i]:
                        fl |= F["piggy"]
                    if pon[i]:
                        on |= F["piggy"]
                    if not on and not (fl & (F["base"] | F["pick"] | F["rank"])):
                        continue
                    prev_n = have.get((t, day))
                    if prev_n is not None and prev_n >= H and i < len(d) - (H + RECENT_REDO):
                        continue        # 오래된 사건은 40봉 다 찼으면 그대로 · 최근 H+5 봉 안의 사건은 매번 다시 씀(RECENT_REDO 주석)
                    hi, lo, cl, m = _paths(d, i)
                    if m == 0:
                        continue
                    rows.append((t, day, float(d["Close"].iloc[i]), fl, on, m, hi.tobytes(), lo.tobytes(), cl.tobytes(),
                                 None if np.isnan(psl[i]) else float(psl[i]), None if np.isnan(ptp[i]) else float(ptp[i])))
                    res["new" if prev_n is None else "updated"] += 1
            except Exception as e:  # noqa: BLE001
                out(f"presim 사건 만들기 실패 {t}: {e}")
        if rows:
            conn.executemany("INSERT OR REPLACE INTO presim_ep (ticker, date, px, flags, onset, n, hi, lo, cl, sl_pct, tp_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)   # 열 이름 명시(6절 교훈)
            conn.commit()
        if len(tickers) > 300:
            out(f"🎲 사건 표: {min(k + 300, len(tickers))}/{len(tickers)}종목")
    res["rows"] = conn.execute("SELECT COUNT(*) FROM presim_ep").fetchone()[0]
    try:
        db.set_meta("presim_ep_ver", EP_VERSION)
    except Exception:  # noqa: BLE001
        pass
    out(f"🎲 사건 표(presim_ep): 종목 {res['tickers']} · 새로 {res['new']} · 갱신 {res['updated']} · 전체 {res['rows']:,}건")
    return res


def _overlap_weights(tickers, dates) -> np.ndarray:
    """겹침 가중(보강 D): 같은 종목의 사건이 ±OVERLAP_DAYS 안에 k개 더 있으면 1/(1+k) — 겹치는 40봉 창은 독립 표본이 아니라서(López de Prado 'uniqueness' 의 간단판)."""
    w = np.ones(len(tickers))
    if len(tickers) < 2:
        return w
    ords = np.array([date.fromisoformat(str(x)[:10]).toordinal() for x in dates])
    df = pd.DataFrame({"t": list(tickers), "o": ords, "i": np.arange(len(tickers))})
    for _, g in df.groupby("t"):
        if len(g) < 2:
            continue
        order = np.argsort(g["o"].to_numpy())
        o = g["o"].to_numpy()[order]
        idx = g["i"].to_numpy()[order]
        k = np.searchsorted(o, o + OVERLAP_DAYS, "right") - np.searchsorted(o, o - OVERLAP_DAYS, "left") - 1
        w[idx] = 1.0 / (1.0 + k)
    return w


def episodes(conn, key: str) -> dict:
    """키에 맞는 사건들의 경로 배열. {"hi","lo","cl": (E×H), "bars": (E,), "sl","tp": 사건별 계획 %(없으면 NaN), "w": 겹침 가중, "dates", "meta": DataFrame(ticker, date, px)}"""
    ensure(conn)
    name, need, need_on = KEYS[key]
    sql = "SELECT ticker, date, px, n, hi, lo, cl, sl_pct, tp_pct FROM presim_ep WHERE (flags & ?) = ?" + (" AND (onset & ?) = ?" if need_on else "")
    args = [need, need] + ([need_on, need_on] if need_on else [])
    rows = conn.execute(sql, args).fetchall()
    if not rows:
        return {"key": key, "name": name, "n": 0}
    hi = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
    lo = np.stack([np.frombuffer(r[5], dtype=np.float32) for r in rows])
    cl = np.stack([np.frombuffer(r[6], dtype=np.float32) for r in rows])
    meta = pd.DataFrame([(r[0], r[1], r[2]) for r in rows], columns=["ticker", "date", "px"])
    sl = np.array([np.nan if r[7] is None else float(r[7]) for r in rows])
    tp = np.array([np.nan if r[8] is None else float(r[8]) for r in rows])
    dates = np.array([str(r[1]) for r in rows])
    return {"key": key, "name": name, "n": len(rows), "hi": hi, "lo": lo, "cl": cl, "bars": np.array([r[3] for r in rows]), "meta": meta,
            "sl": sl, "tp": tp, "dates": dates, "w": _overlap_weights(meta["ticker"].tolist(), dates)}


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
def outcomes(hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, sl_pct, tp_pct, horizon: int, bars: np.ndarray | None = None, w: np.ndarray | None = None) -> dict:
    """경로(E×≥horizon, % 단위)에 손절 −sl_pct% · 목표 +tp_pct% 적용. 같은 날 둘 다면 보수적=손절(p_tp) · 낙관적=익절(p_tp_opt).
    sl_pct·tp_pct 는 숫자 하나(모든 사건 같은 계획) 또는 사건별 배열(🐷 그날 박스). w = 겹침 가중(없으면 1) → 비율·기대값은 가중 평균, n_eff = 가중 합.
    기간 안에 못 닿고 봉도 모자란 사건(미완)과 계획이 없는(NaN) 사건은 뺌. p0 = 기대값 0 기준 익절 확률 = 손절폭/(손절폭+목표폭)(중앙값 계획 기준)."""
    E0 = int(hi.shape[0])
    h = int(max(1, min(horizon, hi.shape[1]))) if E0 else int(max(1, horizon))
    r = {"n": 0, "n_eff": 0.0, "p_tp": None, "p_tp_opt": None, "p_sl": None, "p_none": None, "both_pct": None, "ev_pct": None, "ev_opt": None, "none_avg": None,
         "horizon": h, "sl_pct": None, "tp_pct": None, "p0": None}
    if E0 == 0:
        return r
    sl_a = np.abs(np.broadcast_to(np.asarray(sl_pct, dtype=float), (E0,))).astype(float)
    tp_a = np.abs(np.broadcast_to(np.asarray(tp_pct, dtype=float), (E0,))).astype(float)
    ww = np.ones(E0) if w is None else np.asarray(w, dtype=float)
    hi_, lo_, cl_ = hi[:, :h], lo[:, :h], cl[:, :h]
    sl_hit = np.nan_to_num(lo_, nan=np.inf) <= -sl_a[:, None]
    tp_hit = np.nan_to_num(hi_, nan=-np.inf) >= tp_a[:, None]
    big = h + 1
    i_sl = np.where(sl_hit.any(1), sl_hit.argmax(1), big)
    i_tp = np.where(tp_hit.any(1), tp_hit.argmax(1), big)
    avail = (bars if bars is not None else (~np.isnan(cl_)).sum(1))
    complete = np.asarray(avail) >= h
    none_mask = (i_sl >= big) & (i_tp >= big)
    valid = np.isfinite(sl_a) & np.isfinite(tp_a) & (tp_a > 0)
    counted = ~(none_mask & ~complete) & valid
    E = int(counted.sum())
    r["n"] = E
    if E == 0:
        return r
    W = float(ww[counted].sum())
    sl_first = (i_sl < i_tp) & counted
    tp_first = (i_tp < i_sl) & counted
    both = (i_sl == i_tp) & (i_sl < big) & counted
    none = none_mask & counted
    last_close = np.nan_to_num(cl_[:, h - 1], nan=0.0)
    pct = lambda m: round(float(ww[m].sum()) / W * 100, 1)  # noqa: E731
    r.update(p_tp=pct(tp_first), p_tp_opt=pct(tp_first | both), p_sl=pct(sl_first | both), p_none=pct(none), both_pct=pct(both), n_eff=round(W, 1))
    out_cons = np.where(tp_first, tp_a, np.where(sl_first | both, -sl_a, last_close))
    out_opt = np.where(tp_first | both, tp_a, np.where(sl_first, -sl_a, last_close))
    r["ev_pct"] = round(float((out_cons[counted] * ww[counted]).sum() / W), 2)
    r["ev_opt"] = round(float((out_opt[counted] * ww[counted]).sum() / W), 2)
    r["none_avg"] = round(float((last_close[none] * ww[none]).sum() / ww[none].sum()), 2) if none.any() else None
    sl_med, tp_med = float(np.median(sl_a[counted])), float(np.median(tp_a[counted]))
    r.update(sl_pct=round(sl_med, 2), tp_pct=round(tp_med, 2), p0=round(sl_med / (sl_med + tp_med) * 100, 1) if sl_med + tp_med > 0 else None)
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
    """옛 절대 판정 — 1겹 표본이 없어 2겹(이 종목 250일)만 있을 때만 씀."""
    if p_tp is None or p_sl is None or ev is None:
        return "❔", "자료 부족"
    if p_tp - p_sl >= COIN_GAP and ev > COIN_EV:
        return "🟢", VERDICT_TEXT_ABS["🟢"]
    if p_sl - p_tp >= COIN_GAP and ev < -COIN_EV:
        return "🔴", VERDICT_TEXT_ABS["🔴"]
    return "🪙", VERDICT_TEXT_ABS["🪙"]


def shrink(edge_raw: float, n_eff: float, k: float = SHRINK_K) -> float:
    """소표본 보정(보강 A): 우위 × n_eff/(n_eff+k). 표본 24건으로 +13.9%p 같은 숫자가 그대로 판정이 되지 않게."""
    n_eff = max(0.0, float(n_eff or 0))
    return float(edge_raw) * n_eff / (n_eff + k)


def verdict_edge(ev, ev_base, n_eff) -> tuple[str, str, float | None, float | None]:
    """기준 대비 우위 판정(보강 A): edge_raw = 같은 계획의 기대값 − 기준(아무 날) 기대값 → 보정 edge. 🟢 edge ≥ +EDGE_MIN · 🔴 ≤ −EDGE_MIN(둘 다 유효 표본 ≥ EFF_MIN) · 그 밖 🪙.
    돌려주는 것: (이모지, 설명, 보정 우위, 보정 전 우위)."""
    if ev is None or ev_base is None or not n_eff:
        return "❔", "자료 부족", None, None
    raw = float(ev) - float(ev_base)
    edge = shrink(raw, n_eff)
    if n_eff >= EFF_MIN and edge >= EDGE_MIN:
        return "🟢", VERDICT_TEXT["🟢"], round(edge, 2), round(raw, 2)
    if n_eff >= EFF_MIN and edge <= -EDGE_MIN:
        return "🔴", VERDICT_TEXT["🔴"], round(edge, 2), round(raw, 2)
    return "🪙", VERDICT_TEXT["🪙"], round(edge, 2), round(raw, 2)


def recent_slice(ep: dict, day: str, days: int = RECENT_DAYS) -> dict | None:
    """최근 창(보강 B): 사건 표에서 day 기준 최근 days 일 안에 시작한 사건만 골라 같은 모양으로 돌려줌(없으면 None)."""
    if not ep or not ep.get("n"):
        return None
    cut = (date.fromisoformat(str(day)[:10]) - timedelta(days=days)).isoformat()
    m = ep["dates"] >= cut
    if not m.any():
        return None
    return {k: (v[m] if isinstance(v, np.ndarray) and len(v) == len(m) else v) for k, v in ep.items() if k != "meta"} | {"n": int(m.sum())}


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
    """오늘 이 종목의 조건으로 쓸 1겹 키 — 저금통 출처면 🐷 재생 키(희석 없음이면 piggy_nd) → 출처 키(pick·rank) → 조건 키(⭐1 → 2 → 3 → 과매도 → 강한 유입 → 기준) 중 사건이 MIN_EP 이상인 첫 번째."""
    order = (list(BOX_KEYS) if source == "piggy" else []) + ([source] if source in ("pick", "rank") else []) + list(COND_ORDER)
    for k in order:
        name, need, need_on = KEYS[k]
        if k in BOX_KEYS:
            has = (k == "piggy") or bool(flags_now & F["dil"])
        else:
            has = (k == "base") or (k in ("pick", "rank")) or ((flags_now & need) == need)
        if has and counts.get(k, 0) >= MIN_EP:
            return k
    return "base"


def run_one(conn, ticker: str, df: pd.DataFrame, source: str = "scr", day: str | None = None, *, entry: float | None = None, sl: float | None = None,
            tp: float | None = None, horizon: int | None = None, box=None, n_sim: int = N_SIM, seed: int | None = None, dil_dates: list[str] | None = None,
            covered: bool = True, counts: dict | None = None, cache: dict | None = None, save: bool = True, now: datetime | None = None) -> dict:
    """한 종목 한 번: 기본값 채우기 → 1겹(같은 신호 전체 과거 · 🐷 키는 사건별 그날 박스) → 기준(아무 날) 같은 계획 → 최근 창 → 2겹(이 종목 250일) → 수량 → 기준 대비 우위 판정 → presim_log."""
    ensure(conn)
    d = _norm(df)
    if len(d) < MIN_BARS:
        return {"ok": False, "ticker": ticker, "why": f"일봉 {len(d)}일 < {MIN_BARS}일 — 자료 부족"}
    plan_given = sl is not None or tp is not None          # 사용자가 손절·목표를 정했으면 고정 % 계획
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
    box_plan = key in BOX_KEYS and not plan_given          # 🐷: 사건마다 그날 박스로(사용자가 손절·목표를 바꾸면 고정 %)
    if ep.get("n"):
        l1 = outcomes(ep["hi"], ep["lo"], ep["cl"], ep["sl"] if box_plan else sl_pct, ep["tp"] if box_plan else tp_pct, hz, bars=ep["bars"], w=ep.get("w"))
    else:
        l1 = {"n": 0, "n_eff": 0.0}
    l1["key"], l1["name"], l1["plan"] = key, KEYS[key][0], ("box" if box_plan else "fixed")
    # 기준(아무 날)에 같은 계획(🐷 박스 계획이면 그 중앙값) 적용 → 우위
    epb = cache.get("base") or episodes(conn, "base")
    cache["base"] = epb
    b_sl, b_tp = (l1.get("sl_pct") or sl_pct, l1.get("tp_pct") or tp_pct) if box_plan else (sl_pct, tp_pct)
    lb = outcomes(epb["hi"], epb["lo"], epb["cl"], b_sl, b_tp, hz, bars=epb["bars"], w=epb.get("w")) if epb.get("n") else {"n": 0}
    # 최근 창(최근 180일 사건만)
    rec_ep = recent_slice(ep, day) if ep.get("n") else None
    rec = outcomes(rec_ep["hi"], rec_ep["lo"], rec_ep["cl"], rec_ep["sl"] if box_plan else sl_pct, rec_ep["tp"] if box_plan else tp_pct, hz, bars=rec_ep["bars"], w=rec_ep.get("w")) if rec_ep else {"n": 0}
    own = simulate(d, entry, sl, tp, hz, n=n_sim, seed=seed)
    st = _settings()
    sz = size(entry, sl, st["account_krw"], st["max_loss_krw"], _fx(), adv20)
    p0 = l1.get("p0") if l1.get("n") else round(sl_pct / (sl_pct + tp_pct) * 100, 1)
    edge = edge_raw = None
    if l1.get("n", 0) >= MIN_EP and key != "base" and lb.get("n"):
        vd, txt, edge, edge_raw = verdict_edge(l1["ev_pct"], lb["ev_pct"], l1.get("n_eff"))
        basis = "같은 신호 전체 과거 vs 기준(아무 날) · 같은 계획"
    elif l1.get("n", 0) >= MIN_EP and key == "base":
        vd, txt, edge, edge_raw, basis = "🪙", BASE_TEXT, 0.0, 0.0, "기준(아무 날)뿐 — 우위 없음"
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
    if rec.get("n", 0) >= 20 and l1.get("ev_pct") is not None and rec.get("ev_pct") is not None and abs(rec["ev_pct"] - l1["ev_pct"]) >= 2:
        notes.append(f"최근 6개월({rec['n']}건)은 기대값 {rec['ev_pct']:+.1f}% 로 2년 평균({l1['ev_pct']:+.1f}%)과 달라요 — 효과가 변하는 중일 수 있어요")
    res = {"ok": True, "ticker": ticker, "source": source, "day": day, "entry": entry, "sl": sl, "tp": tp, "horizon": hz, "sl_pct": round(sl_pct, 2), "tp_pct": round(tp_pct, 2),
           "key": key, "plan": l1["plan"], "layer1": l1, "base": lb, "recent": rec, "own": own, "size": sz, "verdict": vd, "verdict_text": txt, "basis": basis,
           "edge": edge, "edge_raw": edge_raw, "p0": p0, "n_eff": l1.get("n_eff"), "notes": notes, "warn": WARN, "flags_now": flags_now}
    if save:
        detail = json.dumps({"layer1": {k: v for k, v in l1.items() if k not in ("meta",)}, "base": lb, "recent": rec, "own": own, "size": sz, "basis": basis, "notes": notes,
                             "sl_pct": res["sl_pct"], "tp_pct": res["tp_pct"], "plan": l1["plan"], "p0": p0}, ensure_ascii=False, default=float)
        conn.execute("INSERT OR REPLACE INTO presim_log (day, ticker, source, key, entry, sl, tp, horizon, p_tp, p_tp_opt, p_sl, p_none, both_pct, ev_pct, n_ep, own_p_tp, own_p_sl, own_ev, own_n, "
                     "verdict, detail, created_at, edge, edge_raw, ev_base, n_eff, p0, recent_n, recent_ev, plan) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (day, ticker, source, key, entry, sl, tp, hz, l1.get("p_tp"), l1.get("p_tp_opt"), l1.get("p_sl"), l1.get("p_none"), l1.get("both_pct"), l1.get("ev_pct"), l1.get("n", 0),
                      own.get("p_tp"), own.get("p_sl"), own.get("ev_pct"), own.get("n_days"), vd, detail, (now or datetime.now(timezone.utc)).isoformat(),
                      edge, edge_raw, lb.get("ev_pct"), l1.get("n_eff"), p0, rec.get("n", 0), rec.get("ev_pct"), l1["plan"]))
        conn.commit()
    return res


def candidates(conn, top_n: int | None = None) -> list[dict]:
    """저금통 전체 + 오늘 PICK 유력(pick_hist 최신 날) + 종합 순위 상위 N(rank_hist 최신 날). 같은 종목은 저금통 > PICK > 순위 순으로 한 번."""
    top_n = _settings()["top_n"] if top_n is None else int(top_n)
    out: dict[str, dict] = {}
    try:
        import piggy
        it = piggy.items()
        try:
            mm = piggy.metrics_map()   # 직접 정한 박스가 없으면 최근 분석의 지지·저항(가상매매 open_piggy 와 같은 piggy.box_of) — 2026-10-30 수정(전엔 빈 칸만 봐서 레벨 맵으로 떨어짐)
        except Exception:  # noqa: BLE001
            mm = {}
        for r in it.to_dict("records"):
            t = str(r["ticker"])
            try:
                lo_b, hi_b, _src = piggy.box_of(r, mm.get(t))
            except Exception:  # noqa: BLE001
                lo_b, hi_b = r.get("box_low"), r.get("box_high")
            out.setdefault(t, {"ticker": t, "source": "piggy", "box": (lo_b, hi_b)})
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
