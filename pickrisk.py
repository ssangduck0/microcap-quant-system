"""🎯 PICK '과거 비슷한 사례' — 목표 먼저 · −30% 먼저 · 60거래일 뒤(2026-11-01 · docs/pick_reach_check_2026-11-01.md, 김곰 E '종목별 도달 범위' 검증 결과).

PICK 의 실제 목표(baby shelf 탈출가 = $7,500만 ÷ SEC 표지 주식 수 · $1 상장 유지)를 지난 일봉으로 '그날까지 제출된 표지'만 써서 다시 만들고
(pick30 과 같은 조건: 가장 가까운 목표 · +30~150% · 20일 고가 < 목표 · 직전 분기 주식 +20% 초과 탈락 · 같은 종목·목표 30일에 한 번),
60거래일 안 '목표가 먼저 닿았나 / −30% 가 먼저 닿았나(같은 날이면 −30% 먼저로 — 보수적)'를 세어
목표 종류 × 60일 변동성(30%↓ · 30~50% · 50%↑) × 목표까지 거리(+30~60 · 60~100 · 100~150%) 표로 저장한다(칸이 50건 미만이면 종류 × 변동성 줄).
검증(운영 DB 사본 2024-01~2026-08 · 5,191건): '닿을 확률'이 높은 종목은 변동성이 커서 −30% 도 먼저 더 많이 맞는다
(baby shelf 확률 20%↑ −30% 먼저 44% · 60일 중앙 −12% vs 10% 미만 23% · −3%) → 탈락 기준으로 쓰지 않고 양쪽을 같이 보여 준다.
정렬 점수 = 목표 먼저 − −30% 먼저(2024~25 표로 2026 사건 정렬: 위 1/3 목표 먼저 27% · −30% 먼저 38% vs 아래 1/3 8% · 56% — 단 60일 평균 수익은 같음).
어느 묶음도 60일 뒤 중앙값이 플러스가 아니다 = 매수 신호가 아니라 '지켜볼 목록'의 위험 순서. 워런트·시총 목표는 과거 재생 자료가 없어 표시하지 않는다.
"""
from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date, timedelta

import numpy as np
import pandas as pd

H = 60                 # 거래일(🏆 PICK 과 같은 기간)
STOP = 30.0            # −30% 먼저 = 실패
VB = (0.30, 0.50)      # 60일 변동성(일간 로그수익 표준편차 × √60) 경계
DB = (60.0, 100.0)     # 목표까지 거리(%) 경계 — 아래 +30, 위 +150 은 PICK 조건
MIN_CELL = 50          # 칸 표본이 이보다 적으면 종류 × 변동성 줄로
HIGH_VOL = 0.50        # ⚠️ 급락 위험 배지(과거 비슷한 PICK 의 절반 넘게 −30% 먼저)
BS_LIMIT = 75e6        # baby shelf: 공개유통시총 $7,500만 미만
MIN_DV = 50_000        # 20일 평균 거래대금(달러) — 거래가 거의 없는 날은 뺌
YEARS = 3              # 재생에 쓰는 일봉 기간
VB_NAME = ("변동성 30%↓", "변동성 30~50%", "변동성 50%↑")
DB_NAME = ("+30~60%", "+60~100%", "+100~150%")
DDL = """CREATE TABLE IF NOT EXISTS pick_risk (kind TEXT NOT NULL, vb INTEGER NOT NULL, db INTEGER NOT NULL, n INTEGER, tf REAL, sf REAL, med REAL,
         built TEXT, PRIMARY KEY (kind, vb, db))"""   # db = -1 은 종류 × 변동성 줄(작은 칸 대신)


def ensure(conn) -> None:
    conn.execute(DDL)


def kind_of(target_name: str | None) -> str | None:
    n = target_name or ""
    if "baby shelf" in n:
        return "baby shelf"
    if n.startswith("$1"):
        return "$1"
    return None


def vband(sv: float) -> int:
    return int(np.digitize(sv, VB))


def dband(pct: float) -> int:
    return int(np.digitize(pct, DB))


def _splits(conn) -> dict[str, dict[str, float]]:
    """종목별 {분할일: 주식 수에 곱할 비율}(1:10 병합 = 0.1) — shares.splits_after 와 같은 두 곳(🔁 병합 기록 · 리포트 회사 정보)."""
    sp: dict[str, dict[str, float]] = {}
    try:
        for t, d, r in conn.execute("SELECT ticker, date, ratio FROM rs_events WHERE ratio > 0"):
            sp.setdefault(t, {})[d] = float(r)
    except Exception:  # noqa: BLE001 (표 없음)
        pass
    try:
        for t, p in conn.execute("SELECT ticker, payload FROM reports"):
            try:
                for s in (json.loads(p).get("company") or {}).get("splits") or []:
                    if s.get("date") and s.get("ratio"):
                        sp.setdefault(t, {}).setdefault(s["date"], float(s["ratio"]))
            except (ValueError, TypeError, AttributeError):
                continue
    except Exception:  # noqa: BLE001
        pass
    return sp


def _mult(sp: dict, d0: str, d1: str = "9999") -> float:
    m = 1.0
    for d, r in sp.items():
        if d0 < d <= d1:
            m *= r
    return m


def events(conn, today: date | None = None) -> pd.DataFrame:
    """지난 PICK 목표 사건(그날 정보만) → t, d, kind, pct, sv, hit, tfirst, sfirst, ret60. 결과(60거래일)가 끝난 사건만."""
    today = today or date.today()
    since = (today - timedelta(days=int(YEARS * 365) + 120)).isoformat()
    cols = ["t", "d", "kind", "pct", "sv", "hit", "tfirst", "sfirst", "ret60"]
    try:
        sh = pd.read_sql("SELECT ticker, asof, filed, shares FROM shares_hist WHERE shares > 0 ORDER BY ticker, filed", conn)
        px = pd.read_sql("SELECT ticker, date, high, low, close, volume FROM daily_prices WHERE date >= ? AND date <= ? AND close > 0 AND high > 0 AND low > 0 "
                         "AND ticker IN (SELECT DISTINCT ticker FROM shares_hist) ORDER BY ticker, date", conn, params=(since, today.isoformat()))
    except Exception:  # noqa: BLE001 (표 없음)
        return pd.DataFrame(columns=cols)
    splits = _splits(conn)
    shg = {t: g for t, g in sh.groupby("ticker")}
    rows = []
    for t, g in px.groupby("ticker", sort=False):
        if t not in shg or len(g) < 2 * H + 20:
            continue
        sp = splits.get(t, {})
        hi, lo, cl, vol = (g[c].to_numpy(float) for c in ("high", "low", "close", "volume"))
        dates = g["date"].tolist()
        n = len(g)
        r = cl[1:] / cl[:-1]
        jump = np.zeros(n, bool)
        jump[1:] = (r >= 3) | (r <= 1 / 3)   # 하루 ×3↑ 계단(빠진 병합 환산 또는 극단 급등) — 그 창은 결과를 못 믿어 뺌
        cut = -1   # 알려진 병합일 근처(±3일)에 계단이 남아 있으면 그 전 일봉은 단위가 다름
        for d in sp:
            j = bisect_right(dates, d)
            if 0 < j < n and jump[max(1, j - 3):min(n, j + 4)].any():
                cut = max(cut, j + 3)
        s = shg[t]
        filed, asof, shares = s["filed"].tolist(), s["asof"].tolist(), s["shares"].to_numpy(float)
        adj = np.array([shares[j] * _mult(sp, asof[j]) for j in range(len(asof))])   # 지금 단위 주식 수(일봉이 지금 단위)
        lr = np.diff(np.log(cl), prepend=np.nan)
        last: dict[str, date] = {}
        for i in range(max(H, cut + 1), n - H):
            d = dates[i]
            k = bisect_right(filed, d) - 1   # 그날까지 '제출된' 표지만(컨닝 금지)
            if k < 0:
                continue
            dd = date.fromisoformat(d)
            if (dd - date.fromisoformat(asof[k])).days > 400 or np.nanmean(cl[i - 19:i + 1] * vol[i - 19:i + 1]) < MIN_DV:
                continue
            p, sh_adj = cl[i], adj[k]
            cands = []
            if sh_adj * cl[i - 59:i + 1].max() < BS_LIMIT:   # 규정: 최근 60일 최고가 기준(pressure 와 같음)
                cands.append(("baby shelf", BS_LIMIT / sh_adj))
            raw = p * _mult(sp, d)   # 그날 실제 가격(병합 환산 전)
            if raw < 1:
                cands.append(("$1", p / raw))
            above = sorted([x for x in cands if x[1] > p], key=lambda x: x[1])
            if not above:
                continue
            kind, tgt = above[0]
            pct = (tgt / p - 1) * 100
            if not (30 <= pct <= 150) or hi[i - 19:i + 1].max() >= tgt:
                continue
            d1 = date.fromisoformat(asof[k])   # ⑥ 직전 분기 주식 +20% 초과면 PICK 탈락(그날까지 제출된 표지 둘)
            prev = [j for j in range(k) if 75 <= (d1 - date.fromisoformat(asof[j])).days <= 200]
            if prev:
                j = prev[-1]
                s0 = shares[j] * _mult(sp, asof[j], asof[k])
                if s0 > 0 and shares[k] / s0 - 1 > 0.20:
                    continue
            if kind in last and (dd - last[kind]).days < 30:
                continue
            if jump[i + 1:i + H + 1].any():
                continue
            # 빠진 병합 의심: 1년 안 다른 표지가 (알려진 병합을 반영해도) 절반 아래/2배 위 → 목표가 단위를 못 믿음
            near = [j for j in range(len(asof)) if j != k and abs((date.fromisoformat(asof[j]) - dd).days) <= 365]
            if any(adj[j] < 0.5 * sh_adj for j in near if asof[j] > d) or any(adj[j] > 2 * sh_adj for j in near if asof[j] <= d):
                continue
            last[kind] = dd
            up = hi[i + 1:i + H + 1] >= tgt
            down = lo[i + 1:i + H + 1] <= p * (1 - STOP / 100)
            dh = int(np.argmax(up)) if up.any() else None
            ds = int(np.argmax(down)) if down.any() else None
            rows.append((t, d, kind, pct, float(np.nanstd(lr[i - 59:i + 1]) * np.sqrt(60)), bool(up.any()),
                         dh is not None and (ds is None or dh < ds), ds is not None and (dh is None or ds <= dh), cl[i + H] / p - 1))
    return pd.DataFrame(rows, columns=cols)


def build(conn, today: date | None = None, out=print) -> dict:
    """사건을 다시 세어 표를 새로 쓴다(우리가 만든 표 pick_risk 만 바꿈)."""
    today = today or date.today()
    ev = events(conn, today)
    ensure(conn)
    if ev.empty:
        out("🎯 PICK 과거 사례 표: 사건 없음(표지·일봉 부족) — 그대로 둠")
        return {"events": 0, "cells": 0}
    ev["vb"] = [vband(x) for x in ev["sv"]]
    ev["db"] = [dband(x) for x in ev["pct"]]
    rows = []
    for keys, grp in list(ev.groupby(["kind", "vb", "db"])) + [((k, v, -1), g) for (k, v), g in ev.groupby(["kind", "vb"])]:
        rows.append((keys[0], int(keys[1]), int(keys[2]), len(grp), float(grp["tfirst"].mean() * 100), float(grp["sfirst"].mean() * 100),
                     float(grp["ret60"].median() * 100), today.isoformat()))
    conn.execute("DELETE FROM pick_risk")
    conn.executemany("INSERT INTO pick_risk VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    by = ev.groupby("kind").agg(n=("hit", "size"), tf=("tfirst", "mean"), sf=("sfirst", "mean"))
    out("🎯 PICK 과거 사례 표: " + " · ".join(f"{k} {int(r.n):,}건(목표 먼저 {r.tf * 100:.0f}% · −30% 먼저 {r.sf * 100:.0f}%)" for k, r in by.iterrows())
        + f" · {ev['d'].min()}~{ev['d'].max()}")
    return {"events": int(len(ev)), "cells": len(rows), "first": ev["d"].min(), "last": ev["d"].max()}


def maybe_build(conn, today: date | None = None, out=print) -> dict | None:
    """토요일(하루 한 번) 또는 표가 비었으면 다시 만든다(서버 1~2분)."""
    today = today or date.today()
    ensure(conn)
    r = conn.execute("SELECT MAX(built) FROM pick_risk").fetchone()
    built = r[0] if r else None
    if built and not (today.weekday() == 5 and built < today.isoformat()):
        return None
    return build(conn, today, out)


def table(conn) -> dict:
    """{(종류, 변동성 칸, 거리 칸 또는 -1): {n, tf, sf, med, built}} — 없으면 {}."""
    try:
        return {(k, v, d): {"n": n, "tf": tf, "sf": sf, "med": med, "built": b}
                for k, v, d, n, tf, sf, med, b in conn.execute("SELECT kind, vb, db, n, tf, sf, med, built FROM pick_risk")}
    except Exception:  # noqa: BLE001 (표 없음)
        return {}


def vol60(conn, t: str) -> float | None:
    cl = np.array([r[0] for r in conn.execute("SELECT close FROM daily_prices WHERE ticker=? AND close > 0 ORDER BY date DESC LIMIT 61", (t,))], float)[::-1]
    if len(cl) < 30:
        return None
    v = float(np.nanstd(np.diff(np.log(cl))) * np.sqrt(60))
    return v if v > 0 else None


def lookup(tab: dict, kind: str | None, sv: float | None, pct: float | None) -> dict | None:
    """목표 종류·변동성·거리 → 과거 비슷한 PICK 결과(%). 표·자료가 없거나 PICK 범위 밖이면 None."""
    if not tab or kind is None or sv is None or pct is None or not (30 <= pct <= 150):
        return None
    vb, db_ = vband(sv), dband(pct)
    c = tab.get((kind, vb, db_))
    coarse = c is None or (c["n"] or 0) < MIN_CELL
    if coarse:
        c = tab.get((kind, vb, -1))
    if not c or not c["n"]:
        return None
    return {"tf": c["tf"], "sf": c["sf"], "med": c["med"], "n": int(c["n"]), "score": c["tf"] - c["sf"], "vol": sv * 100,
            "high_vol": sv >= HIGH_VOL, "group": f"{kind} · {VB_NAME[vb]}" + ("" if coarse else f" · {DB_NAME[db_]}"), "built": c.get("built")}


def for_row(conn, t: str, target_name: str | None, pct: float | None, tab: dict | None = None) -> dict | None:
    kind = kind_of(target_name)
    if kind is None or pct is None or not (30 <= pct <= 150):   # PICK 범위 밖이면 일봉을 읽지 않음(스캔이 등록 종목 전부를 돎)
        return None
    tab = table(conn) if tab is None else tab
    if not tab:
        return None
    return lookup(tab, kind, vol60(conn, t), pct)


def chip(rk: dict | None) -> str:
    """칩 한 줄(짧게): '🎯15 · 📉15' (+ ⚠️)."""
    if not rk:
        return ""
    return f"🎯{rk['tf']:.0f} · 📉{rk['sf']:.0f}" + (" ⚠️" if rk["high_vol"] else "")


def label(rk: dict | None) -> str:
    if not rk:
        return ""
    return (f"과거 비슷한 PICK {rk['n']:,}건({rk['group']}): 목표 먼저 {rk['tf']:.0f}% · −30% 먼저 {rk['sf']:.0f}% · 60일 뒤 중앙 {rk['med']:+.0f}%"
            + (" · ⚠️ 급락 위험(변동성 50%↑)" if rk["high_vol"] else ""))
