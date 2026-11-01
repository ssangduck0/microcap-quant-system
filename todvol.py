"""🔊 시각 맞춘 거래량(2026-11-01 · docs/rvol_check_2026-11-01.md, 스캐너 점검의 '나중 후보').

거래량 배수(오늘 누적 ÷ 20일 평균 정규장 거래량)는 장 초반엔 하루치가 덜 쌓여 늘 낮다 → 소형주 5분봉(최근 60일)으로
'거래량 많은 날(마감 배수 2배↑)에 그 시각까지 하루 거래량의 몇 %가 차는지' 곡선 g(t)를 만들고, 시각마다
'보정 배수(배수 ÷ g) ≥ 문턱이면 마감 때 k배↑' 판정이 과거에 85%↑ 맞는 가장 낮은 문턱을 정해 둔다(k = 1.5 · 2 · 3).
재생(앞 절반으로 정하고 뒤 절반 확인): 10:00 에 '마감 2배↑ 날'을 28% → 55% 알아보며 맞음 81% · 12:00 73% / 89%.
종목별 곡선(TradingView 식)은 더 낫지 않았음(큰 거래량 날은 평소와 달리 아침에 몰림). 프리마켓은 소형주 곡선이 0%라 판정 안 함.

쓰임: 판정·점수는 그대로. (1) 🎯 펌핑 알림·종목 화면에 문턱을 넘었을 때만 '🔊 오늘 거래량 k배↑ 가능성 높음' 한 줄(10:00~15:30)
(2) 시험 기록: 거래량 칸만 이 판정으로 매기면 펌핑 70점이 되는(지금 방식은 70점 미만) 종목을 알림 없이 🏆 '🧪 펌핑 70점 · 시각 보정으로만'에
종목·날짜당 첫 번째만 기록 → 12월 중순 지금 방식 70점과 비교해 점수에 넣을지 결정. 곡선·문턱은 아침 작업이 28일마다 다시 만든다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
TIERS = (3.0, 2.0, 1.5)          # 펌핑 점수 거래량 칸 경계(3배 20 · 2배 14 · 1.5배 8점)
PTS = {3.0: 20.0, 2.0: 14.0, 1.5: 8.0}
PRECISION = 0.85                 # 문턱: 과거에 이만큼 맞는 가장 낮은 보정 배수
MIN_FLAGS = 10                   # 문턱을 정할 때 최소 표시 수
START, END = 600, 930            # 10:00 ~ 15:30(분, 동부) — 그 밖(프리·처음 30분·마감 직전·시간외)은 판정 안 함
GRID = np.arange(240, 1201, 5)   # 04:00 ~ 20:00 — 그 시각까지 끝난 5분봉 누적
SAMPLE = 300                     # 곡선용 소형주 무작위 표본
REBUILD_DAYS = 28
DDL = """CREATE TABLE IF NOT EXISTS tod_volume (slot INTEGER PRIMARY KEY, g REAL, thr15 REAL, thr2 REAL, thr3 REAL, p15 REAL, p2 REAL, p3 REAL,
         n_days INTEGER, n_heavy INTEGER, built TEXT)"""
NOW_DDL = "CREATE TABLE IF NOT EXISTS tod_now (ticker TEXT PRIMARY KEY, date TEXT, at TEXT, tier REAL, prec REAL, vm REAL)"
SHADOW_DDL = """CREATE TABLE IF NOT EXISTS tod_shadow (date TEXT NOT NULL, ticker TEXT NOT NULL, at TEXT, price REAL, score REAL, alt_score REAL, tier REAL, vm REAL,
               PRIMARY KEY (date, ticker))"""


def ensure(conn) -> None:
    for q in (DDL, NOW_DDL, SHADOW_DDL):
        conn.execute(q)


def points(vm: float | None) -> float:
    v = vm or 0
    return 20.0 if v >= 3 else 14.0 if v >= 2 else 8.0 if v >= 1.5 else 0.0


def day_rows(frames: dict, avg20) -> list[tuple]:
    """5분봉(프리·애프터 포함) → [(종목, 날짜, 20일 평균, 정규장 거래량, 누적[GRID])]. avg20(종목, 날짜) = 그날 전 20거래일 평균. 정규장 봉 60개↑ 날만."""
    rows = []
    for t, f in frames.items():
        if f is None or f.empty or "Volume" not in f:
            continue
        idx = f.index.tz_convert(ET) if f.index.tz is not None else f.index
        g = pd.DataFrame({"v": f["Volume"].fillna(0).to_numpy(float), "d": idx.strftime("%Y-%m-%d"), "m": idx.hour * 60 + idx.minute})
        for d, x in g.groupby("d"):
            reg = x[(x.m >= 570) & (x.m < 960)]
            a = avg20(t, d)
            if len(reg) < 60 or not a or a <= 0:
                continue
            end = (x.m + 5).to_numpy()
            order = np.argsort(end)
            cum = np.concatenate([[0.0], np.cumsum(x.v.to_numpy()[order])])
            rows.append((t, d, float(a), float(reg.v.sum()), cum[np.searchsorted(end[order], GRID, side="right")]))
    return rows


def fit(rows: list[tuple]) -> dict | None:
    """곡선(큰 거래량 날 중앙) + 시각마다 문턱. 큰 거래량 날이 100개 미만이면 None."""
    heavy = [r for r in rows if r[3] > 0 and r[3] / r[2] >= 2]
    if len(heavy) < 100:
        return None
    gcur = np.median(np.array([r[4] / r[3] for r in heavy]), axis=0)
    out = {}
    for j, slot in enumerate(GRID):
        if not (START <= slot < END) or gcur[j] <= 0:
            continue
        v = np.array([r[4][j] / (r[2] * gcur[j]) for r in rows])
        row = {"g": float(gcur[j])}
        for k in TIERS:
            pos = np.array([r[3] / r[2] >= k for r in rows])
            thr = prec = None
            for t_ in np.arange(k, 40.0, 0.25):
                fl = v >= t_
                if fl.sum() >= MIN_FLAGS and (fl & pos).sum() / fl.sum() >= PRECISION:
                    thr, prec = float(t_), float((fl & pos).sum() / fl.sum())
                    break
            row[f"thr{k:g}".replace(".", "")] = thr
            row[f"p{k:g}".replace(".", "")] = prec
        out[int(slot)] = row
    return {"slots": out, "n_days": len(rows), "n_heavy": len(heavy)}


def _avg20(conn, tickers: list[str], since: str):
    """(종목, 날짜) → 그날 전 20거래일 평균 일거래량(그날 제외). 일봉 표보다 뒤 날짜(오늘 등)는 마지막 20일 평균."""
    q = f"SELECT ticker, date, volume FROM daily_prices WHERE date >= ? AND ticker IN ({','.join('?' * len(tickers))}) ORDER BY ticker, date"
    dp = pd.read_sql(q, conn, params=[since, *tickers])
    at, last, lastd = {}, {}, {}
    for t, g in dp.groupby("ticker"):
        v, d = g.volume.to_numpy(float), g.date.tolist()
        for i in range(20, len(d)):
            at[(t, d[i])] = float(v[i - 20:i].mean())
        if len(d) >= 20:
            last[t], lastd[t] = float(v[-20:].mean()), d[-1]
    return lambda t, d: at.get((t, d)) if (t, d) in at else (last.get(t) if d > lastd.get(t, "9999") else None)


def sample_tickers(conn, today: date, n: int = SAMPLE) -> list[str]:
    """소형주 무작위 표본(가격 $0.3~20 · 20일 평균 거래대금 10만 달러↑ · 달마다 다른 씨앗). 펌핑 신호 종목을 섞으면 큰 거래량 날이 많아져 문턱이 낮게(덜 엄격하게) 나와 검증과 달라짐 → 무작위만."""
    since = (today - timedelta(days=45)).isoformat()
    d = pd.read_sql("SELECT ticker, date, close, volume FROM daily_prices WHERE date >= ?", conn, params=(since,))
    if d.empty:
        return []
    g = d.assign(dv=d.close * d.volume).groupby("ticker").agg(px=("close", "last"), dv=("dv", "mean"), n=("date", "size"))
    uni = sorted(g[(g.px.between(0.3, 20)) & (g.dv >= 100_000) & (g.n >= 15)].index)
    rng = np.random.default_rng(int(today.strftime("%Y%m")))
    return sorted(rng.choice(uni, size=min(n, len(uni)), replace=False).tolist()) if uni else []


def build(conn, today: date | None = None, download=None, out=print) -> dict:
    """5분봉을 받아 곡선·문턱을 새로 쓴다(받는 동안엔 DB 에 쓰지 않음 — 잠금 교훈). 자료가 부족하면 그대로 둠."""
    today = today or date.today()
    ensure(conn)
    tickers = sample_tickers(conn, today)
    if not tickers:
        out("🔊 시각 맞춘 거래량: 표본 종목 없음 — 그대로 둠")
        return {"ok": False}
    if download is None:
        import market
        download = lambda tk: market._download(tk, chunk_size=50, period="60d", interval="5m", prepost=True)  # noqa: E731
    frames = download(tickers)
    rows = day_rows(frames, _avg20(conn, tickers, (today - timedelta(days=150)).isoformat()))
    res = fit(rows)
    if res is None:
        out(f"🔊 시각 맞춘 거래량: 큰 거래량 날 부족(종목·날짜 {len(rows)}) — 그대로 둠")
        return {"ok": False, "rows": len(rows)}
    conn.execute("DELETE FROM tod_volume")
    conn.executemany("INSERT INTO tod_volume VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     [(s, r["g"], r.get("thr15"), r.get("thr2"), r.get("thr3"), r.get("p15"), r.get("p2"), r.get("p3"), res["n_days"], res["n_heavy"], today.isoformat())
                      for s, r in sorted(res["slots"].items())])
    conn.commit()
    s10 = res["slots"].get(600, {})
    out(f"🔊 시각 맞춘 거래량: 표본 {len(frames)}종목 · 종목·날짜 {res['n_days']:,}(큰 거래량 날 {res['n_heavy']}) · 10:00 곡선 {s10.get('g', 0) * 100:.0f}% · 2배 문턱 {s10.get('thr2')}")
    return {"ok": True, "rows": res["n_days"], "heavy": res["n_heavy"], "slots": len(res["slots"])}


def maybe_build(conn, today: date | None = None, download=None, out=print) -> dict | None:
    """표가 없거나 28일 넘게 지났으면 다시(아침 작업 · 야후 5분봉 60일치 · 1~2분)."""
    today = today or date.today()
    ensure(conn)
    r = conn.execute("SELECT MAX(built) FROM tod_volume").fetchone()
    if r and r[0] and (today - date.fromisoformat(r[0])).days < REBUILD_DAYS:
        return None
    return build(conn, today, download, out)


def table(conn) -> dict:
    try:
        return {s: {"g": g, 1.5: (t15, p15), 2.0: (t2, p2), 3.0: (t3, p3)}
                for s, g, t15, t2, t3, p15, p2, p3 in conn.execute("SELECT slot, g, thr15, thr2, thr3, p15, p2, p3 FROM tod_volume")}
    except Exception:  # noqa: BLE001 (표 없음)
        return {}


def assess(vm: float | None, now: datetime | None, tab: dict) -> dict | None:
    """지금 배수 + 동부시각 → {'tier': k, 'prec': 맞음, 'adj': 보정 배수} (지금 배수가 이미 k 이상이면 그 단계는 알릴 필요 없음). 창 밖·표 없음이면 None."""
    if not tab or vm is None or vm <= 0 or now is None:
        return None
    et = now.astimezone(ET)
    m = et.hour * 60 + et.minute
    if not (START <= m < END):
        return None
    row = tab.get(m - m % 5)
    if not row or not row["g"]:
        return None
    adj = vm / row["g"]
    for k in TIERS:
        thr, prec = row[k]
        if thr is not None and adj >= thr and vm < k:
            return {"tier": k, "prec": prec, "adj": adj}
    return None


def alt_points(vm: float | None, a: dict | None) -> float:
    """시각 보정 판정으로 매긴 거래량 칸(지금 방식보다 낮게 주지는 않음)."""
    return max(points(vm), PTS[a["tier"]]) if a else points(vm)


def line(a: dict | None, vm: float | None) -> str:
    if not a:
        return ""
    return f"🔊 오늘 거래량 {a['tier']:g}배↑ 가능성 높음(지금 {vm or 0:.1f}배 · 과거 같은 시각 맞음 {a['prec'] * 100:.0f}%)"


def record(conn, ticker: str, day: str, now: datetime, price: float | None, vm: float | None, a: dict | None,
           p_score: float, p_detail: dict | None, excluded: bool) -> bool:
    """이번 사이클 결과 저장: 🔊 지금 상태(화면용 · tod_now) + 시험 기록(tod_shadow · 시각 보정으로만 70점, 종목·날짜당 첫 번째). 새 시험 기록이면 True."""
    import config
    at = now.astimezone(ET).isoformat(timespec="seconds")
    if not a:
        return False
    conn.execute("INSERT OR REPLACE INTO tod_now VALUES (?,?,?,?,?,?)", (ticker, day, at, a["tier"], a["prec"], vm))
    new = False
    if not excluded and p_detail and p_score < config.ALERT_MIN_PUMP_SCORE:
        vol_pts = float((p_detail.get("점수") or {}).get("거래량", points(vm)))
        alt = p_score - vol_pts + alt_points(vm, a)
        if alt >= config.ALERT_MIN_PUMP_SCORE:
            new = conn.execute("INSERT OR IGNORE INTO tod_shadow VALUES (?,?,?,?,?,?,?,?)", (day, ticker, at, price, p_score, alt, a["tier"], vm)).rowcount > 0
    conn.commit()
    return new


def latest(conn, ticker: str, now: datetime | None = None, max_age_min: int = 30) -> dict | None:
    """화면용: 최근 30분 안에 기록된 🔊 상태(장 마감 뒤엔 자연히 사라짐)."""
    try:
        r = conn.execute("SELECT date, at, tier, prec, vm FROM tod_now WHERE ticker=?", (ticker.upper(),)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not r or not r[1]:
        return None
    now = (now or datetime.now(ET)).astimezone(ET)
    try:
        at = datetime.fromisoformat(r[1])
    except ValueError:
        return None
    if now - at > timedelta(minutes=max_age_min):
        return None
    return {"tier": r[2], "prec": r[3], "vm": r[4], "at": at}
