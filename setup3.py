"""✅ 스승님 급등 3대 조건 — ① 돈 들어온 거래량(OBV) ② 지지선 명확 또는 과매도 ③ 희석의 부재(가장 중요).

① 돈(OBV): OBV = 오른 봉의 거래량은 더하고 내린 봉의 거래량은 빼서 쌓은 값. 최근 n봉 동안 OBV 순증가가
   그 구간 거래량의 OBV_MIN(20%) 이상이면 '돈 들어옴'. 거래량도 직전보다 VOL_UP(1.3배) 이상 늘면 '강한 유입'.
   거래량만 늘고 OBV 가 안 오르면 '사팔이(돈 없는 거래량)'. → 일봉(기본)·60분봉(장중 확인)·5분봉(장마감 체크) 공통.
② 지지·과매도: 최근 120봉의 저점(앞뒤 3봉보다 낮은 봉) 중 ±4% 안에 3번 이상 닿은 가격대가 있고 지금 가격이
   그 위 10% 안(아래로 3% 넘게 깨지지 않음)이면 '지지선', RSI(14) ≤ 30 이거나 볼린저 하단(20일·2σ) 아래면 '과매도'.
③ 희석 부재: 기준일 전 90일 안에 희석 서류(424B·S-1·S-3·F-1·F-3·EFFECT, 8-K 3.02)가 없음.
   as_of(기준일)를 주면 그날 '전에' 접수된 공시만 본다(🕰 타임머신 컨닝 방지).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

OBV_MIN = 0.20     # 최근 구간 OBV 순증가 ÷ 그 구간 거래량
VOL_UP = 1.3       # 최근 구간 평균 거래량 ÷ 그 전 구간 평균
N_RECENT = 10      # 최근 몇 봉(일봉 10일 · 60분봉 10시간 · 5분봉 50분)
N_PRIOR = 20
SUPPORT_BAND = 0.04
SUPPORT_TOUCHES = 3
SUPPORT_ABOVE = 0.10
RSI_OVERSOLD = 30.0
DIL_DAYS = 90
DIL_FORMS = ("424B", "S-1", "F-1", "S-3", "F-3", "EFFECT")


def _ohlcv(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty or "Close" not in df or "Volume" not in df:
        return None
    d = df.dropna(subset=["Close"]).copy()
    d["Volume"] = d["Volume"].fillna(0).astype(float)
    return d if len(d) >= 3 else None


def obv(df: pd.DataFrame) -> pd.Series:
    c = df["Close"].astype(float)
    step = np.sign(c.diff().fillna(0.0))
    return (step * df["Volume"].astype(float)).cumsum()


def money_flow(df: pd.DataFrame | None, n: int = N_RECENT, prior: int = N_PRIOR) -> dict:
    """① 돈 들어온 거래량. {"ok", "strong", "label", "obv_ratio", "vol_ratio"} — 봉이 부족하면 ok=None."""
    d = _ohlcv(df)
    if d is None or len(d) < n + 2:
        return {"ok": None, "strong": False, "label": "봉 부족", "obv_ratio": None, "vol_ratio": None}
    o = obv(d)
    rec_vol = float(d["Volume"].iloc[-n:].sum())
    obv_ratio = None if rec_vol <= 0 else float(o.iloc[-1] - o.iloc[-n - 1]) / rec_vol
    base = d["Volume"].iloc[-n - prior:-n]
    vol_ratio = None if base.empty or base.mean() <= 0 else float(d["Volume"].iloc[-n:].mean() / base.mean())
    up = obv_ratio is not None and obv_ratio >= OBV_MIN
    vup = vol_ratio is not None and vol_ratio >= VOL_UP
    if up and vup:
        label = "💰 강한 유입(거래량·OBV 동반 상승)"
    elif up:
        label = "💰 돈 들어옴(OBV 상승)"
    elif vup:
        label = "⚠️ 사팔이(돈 없는 거래량 — 거래량만 늘고 OBV 그대로)"
    else:
        label = "조용(거래량·OBV 변화 적음)"
    # 🕰 타임머신 검증(2년·15.7만 건): OBV만 오름 1.11배 vs 거래량+OBV 동반 상승 1.39배 → 판정(ok)은 스승님 말씀 그대로 '같이 올라야' 통과
    return {"ok": bool(up and vup), "obv_up": bool(up), "strong": bool(up and vup), "label": label, "obv_ratio": obv_ratio, "vol_ratio": vol_ratio}


def _rsi(c: pd.Series, n: int = 14) -> float | None:
    if len(c) < n + 1:
        return None
    import ta
    v = ta.rsi(c.astype(float), n).iloc[-1]
    return None if pd.isna(v) else float(v)


def support_or_oversold(df: pd.DataFrame | None, lookback: int = 120) -> dict:
    """② 지지선 명확 또는 과매도. {"ok", "support", "touches", "rsi", "oversold", "label"}"""
    d = _ohlcv(df)
    if d is None or len(d) < 30:
        return {"ok": None, "support": None, "touches": 0, "rsi": None, "oversold": False, "label": "봉 부족"}
    d = d.iloc[-lookback:]
    c = d["Close"].astype(float)
    lo = (d["Low"] if "Low" in d else c).astype(float)
    px = float(c.iloc[-1])
    rsi = _rsi(c)
    mid, sd = c.rolling(20).mean().iloc[-1], c.rolling(20).std().iloc[-1]
    below_bb = bool(not pd.isna(sd) and px < mid - 2 * sd)
    oversold = bool((rsi is not None and rsi <= RSI_OVERSOLD) or below_bb)
    # 저점(앞뒤 3봉보다 낮은 봉) — 마지막 3봉은 아직 확정 전이라 뺌
    lows = [float(lo.iloc[i]) for i in range(3, len(lo) - 3) if lo.iloc[i] == lo.iloc[i - 3:i + 4].min()]
    best, touches = None, 0
    for lv in lows:
        n = sum(1 for x in lows if abs(x / lv - 1) <= SUPPORT_BAND)
        if n > touches or (n == touches and best is not None and lv > best):
            best, touches = lv, n
    sup_ok = bool(best is not None and touches >= SUPPORT_TOUCHES and best * (1 - 0.03) <= px <= best * (1 + SUPPORT_ABOVE))
    parts = []
    if sup_ok:
        parts.append(f"🧱 지지선 ${best:.4g}({touches}번 닿음, 지금 {(px / best - 1) * 100:+.1f}%)")
    if oversold:
        parts.append("📉 과매도(" + ("RSI " + f"{rsi:.0f}" if rsi is not None and rsi <= RSI_OVERSOLD else "볼린저 하단 아래") + ")")
    # 🕰 타임머신 3회 검증: 지지선만 0.58배 · 과매도만 1.29배(INLF 급등 직전 날 48%가 과매도) → ② 판정(ok)은 과매도, 지지선은 참고 표시
    return {"ok": bool(oversold), "support": best if sup_ok else None, "touches": touches, "rsi": rsi, "oversold": oversold,
            "label": " · ".join(parts) if parts else "과매도 아님(지지선 불명확)"}


FD_RATIO_MAX = 1.5   # 🧾 공시분석의 완전희석 주식수가 기본 주식수의 1.5배 이상이면 ③ '희석 있음'


def dilution_absent(t: str, conn, as_of: str | None = None, days: int = DIL_DAYS) -> dict:
    """③ 희석 부재. as_of(YYYY-MM-DD)를 주면 그날 '전에' 접수된 공시만(컨닝 방지). {"ok", "n", "recent", "label"}"""
    end = as_of or (date.today() + timedelta(days=1)).isoformat()
    start = (date.fromisoformat(end) - timedelta(days=days)).isoformat()
    try:
        rows = conn.execute("SELECT filed, form, COALESCE(items,'') FROM sec_hist WHERE ticker=? AND filed >= ? AND filed < ? ORDER BY filed DESC",
                            (t, start, end)).fetchall()
    except Exception:  # noqa: BLE001
        return {"ok": None, "n": 0, "recent": [], "label": "공시 이력 없음(확인 불가)"}
    hit = [(f, fm) for f, fm, it in rows if str(fm).upper().startswith(DIL_FORMS) or (str(fm).upper().startswith("8-K") and "3.02" in str(it))]
    if as_of is None:  # 지금 기준이면 실시간 공시 알림(희석 태그)도 봄
        try:
            for f, fm, tg in conn.execute("SELECT COALESCE(filed, substr(updated,1,10)), form, tags FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) >= ?",
                                          (t, start)):
                if tg and any(k in tg for k in ("희석 위험", "ATM/ELOC", "희석 임박")) and (f, fm) not in hit:
                    hit.append((f, fm))
        except Exception:  # noqa: BLE001
            pass
    hit.sort(reverse=True)
    if not hit:  # 서류가 없어도 🧾 공시분석이 대기 물량(완전희석)·악성 희석·ATM 을 찾았으면 '희석 있음'(예: 워런트 10배 대기)
        try:
            import forensic_ai
            m = forensic_ai.metrics_at(conn, t, as_of)
        except Exception:  # noqa: BLE001
            m = None
        if m:
            why = []
            if m.get("fd_ratio") is not None and m["fd_ratio"] >= FD_RATIO_MAX:
                why.append(f"완전희석 {m['fd_ratio']:.1f}배")
            if m.get("toxic"):
                why.append("악성 희석")
            if m.get("atm_eloc"):
                why.append("ATM·ELOC")
            if why:
                return {"ok": False, "n": 0, "recent": [], "fd": m,
                        "label": "❌ 공시분석: " + " · ".join(why) + f"(as-of {str(m['as_of'])[:10]}) — 최근 서류는 없지만 대기 물량"}
    return {"ok": not hit, "n": len(hit), "recent": hit[:3],
            "label": "✅ 최근 90일 희석 서류 없음" if not hit else f"❌ 최근 90일 희석 서류 {len(hit)}건(" + ", ".join(f"{f[5:]} {fm}" for f, fm in hit[:3]) + ")"}


# 🕰 타임머신(3,000종목·2년) 검증 순위 — 깊을수록 좋아짐(5일 분할 매도 수익 과매도+③ +1.00% → RSI≤25+③ +1.55% → RSI≤20+③ +2.06%, 기준 +0.23%)
TIER_NAMES = {1: "⭐ 1순위 · RSI≤20 + 희석 없음", 2: "2순위 · RSI≤25 + 희석 없음", 3: "3순위 · 과매도 + 희석 없음(참고 — 비용 빼면 거의 0)"}


def tier(rsi, oversold: bool, dil_ok) -> int | None:
    """검증된 순위(1이 가장 좋음). 희석 서류가 있거나 모르면 순위 없음."""
    if dil_ok is not True:
        return None
    if rsi is not None and rsi <= 20:
        return 1
    if rsi is not None and rsi <= 25:
        return 2
    if oversold:
        return 3
    return None


def evaluate(t: str, daily: pd.DataFrame | None, conn=None, intra60: pd.DataFrame | None = None, as_of: str | None = None) -> dict:
    """세 조건 판정. as_of 를 주면 daily 는 그날까지로 잘라서 넘겨야 함(타임머신이 처리)."""
    m = money_flow(daily)
    m60 = money_flow(intra60) if intra60 is not None else None
    s = support_or_oversold(daily)
    dl = dilution_absent(t, conn, as_of) if conn is not None else {"ok": None, "n": 0, "recent": [], "label": "확인 안 함"}
    oks = [m["ok"], s["ok"], dl["ok"]]
    n_ok = sum(1 for x in oks if x)
    tr = tier(s.get("rsi"), s["oversold"], dl["ok"])
    return {"ticker": t, "money": m, "money60": m60, "support": s, "dilution": dl, "n_ok": n_ok, "tier": tr, "tier_name": TIER_NAMES.get(tr, ""),
            "all": bool(all(x for x in oks)), "verdict": "✅ 3대 조건 충족" if all(x for x in oks) else (
                "❌ 희석 있음" if dl["ok"] is False else f"{n_ok}/3 충족")}


# ---------------------------------------------------------------- 지금 후보 찾기 · 🏆 성과 공표 기록
LOG_DDL = "CREATE TABLE IF NOT EXISTS setup3_signals (date TEXT, ticker TEXT, price REAL, strong INTEGER, note TEXT, PRIMARY KEY (date, ticker))"


def candidates(conn, days: int = 7, limit: int = 400) -> list[str]:
    """스캐너가 최근 days 일에 본 종목 + 워치리스트·저금통(가격 $20 미만)."""
    since = (date.today() - timedelta(days=days)).isoformat()
    try:
        tk = [r[0] for r in conn.execute("SELECT ticker FROM daily_snapshots WHERE date >= ? AND price < 20 GROUP BY ticker ORDER BY MAX(COALESCE(win_score, quant_score, 0)) DESC LIMIT ?",
                                         (since, limit))]
    except Exception:  # noqa: BLE001
        tk = []
    try:
        import watch
        tk += [t for t in watch.scanner_priority() if t not in tk]
    except Exception:  # noqa: BLE001
        pass
    return tk[:limit]


def scan(conn, prices: dict, tickers: list[str]) -> list[dict]:
    """종목별 세 조건 판정(일봉 기준). 충족 수 많은 순 → 강한 유입 → 희석 없음."""
    out = []
    for t in tickers:
        df = prices.get(t)
        if df is None or df.empty:
            continue
        r = evaluate(t, df, conn)
        r["price"] = float(df["Close"].dropna().iloc[-1])
        out.append(r)
    out.sort(key=lambda r: (-(r["tier"] or 9), r["all"], r["n_ok"], bool(r["dilution"]["ok"]), r["money"]["strong"], r["money"]["obv_ratio"] or -9), reverse=True)
    return out


TIER_DDL = "CREATE TABLE IF NOT EXISTS s3_tier_signals (date TEXT, ticker TEXT, price REAL, tier INTEGER, rsi REAL, note TEXT, PRIMARY KEY (date, ticker))"


def record_tiers(conn, rows: list[dict], today: date | None = None) -> int:
    """검증 순위(1~3) 종목을 🏆 성과 공표용으로 기록 — 같은 종목은 10일에 한 번."""
    today = today or date.today()
    conn.execute(TIER_DDL)
    recent = {r[0] for r in conn.execute("SELECT ticker FROM s3_tier_signals WHERE date >= ?", ((today - timedelta(days=10)).isoformat(),))}
    n = 0
    for r in rows:
        if r.get("tier") and r["ticker"] not in recent and r.get("price"):
            conn.execute("INSERT OR IGNORE INTO s3_tier_signals VALUES (?,?,?,?,?,?)",
                         (today.isoformat(), r["ticker"], r["price"], r["tier"], r["support"].get("rsi"), r["dilution"]["label"][:60]))
            n += 1
    conn.commit()
    return n


def record(conn, rows: list[dict], today: date | None = None) -> int:
    """3대 조건 충족 종목을 🏆 성과 공표용으로 기록(같은 종목은 20일에 한 번)."""
    today = today or date.today()
    conn.execute(LOG_DDL)
    recent = {r[0] for r in conn.execute("SELECT ticker FROM setup3_signals WHERE date >= ?", ((today - timedelta(days=20)).isoformat(),))}
    n = 0
    for r in rows:
        if r["all"] and r["ticker"] not in recent and r.get("price"):
            conn.execute("INSERT OR IGNORE INTO setup3_signals VALUES (?,?,?,?,?)",
                         (today.isoformat(), r["ticker"], r["price"], 1 if r["money"]["strong"] else 0, f"{r['money']['label']} · {r['support']['label']}"))
            n += 1
    conn.commit()
    return n


# ---------------------------------------------------------------- 🏆 성과 공표: 신호 난 날의 조건(그날까지 정보만 — 컨닝 없음)
COND_DDL = "CREATE TABLE IF NOT EXISTS s3_cond (ticker TEXT, date TEXT, strong INTEGER, ovs INTEGER, supl INTEGER, dil INTEGER, PRIMARY KEY (ticker, date))"


def conditions_at(conn, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """[(티커, 날짜)] → {(티커, 날짜): {strong, ovs, supl, dil}} — 그날까지의 일봉(daily_prices)·그날 전에 접수된 공시만. DB 에 저장해 두고 재사용.
    일봉이 30일 미만이면 값 None."""
    conn.execute(COND_DDL)
    have = {(r[0], r[1]): {"strong": r[2], "ovs": r[3], "supl": r[4], "dil": r[5]} for r in conn.execute("SELECT * FROM s3_cond")}
    out = {}
    todo = [p for p in dict.fromkeys(pairs) if p not in have]
    by_t: dict[str, list[str]] = {}
    for t, d in todo:
        by_t.setdefault(t, []).append(d)
    for t, ds in by_t.items():
        q = conn.execute("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? AND date <= ? ORDER BY date", (t, max(ds))).fetchall()
        if not q:
            continue
        full = pd.DataFrame(q, columns=["date", "Open", "High", "Low", "Close", "Volume"]).set_index("date")
        for d in ds:
            part = full[full.index <= d].tail(160)
            if len(part) < 30:
                continue
            m, s = money_flow(part), support_or_oversold(part)
            dl = dilution_absent(t, conn, as_of=d)
            r = {"strong": int(bool(m["strong"])), "ovs": int(bool(s["oversold"])), "supl": int(bool(s["support"] is not None)), "dil": None if dl["ok"] is None else int(bool(dl["ok"]))}
            conn.execute("INSERT OR REPLACE INTO s3_cond VALUES (?,?,?,?,?,?)", (t, d, r["strong"], r["ovs"], r["supl"], r["dil"]))
            have[(t, d)] = r
    conn.commit()
    for p in pairs:
        if p in have:
            out[p] = have[p]
    return out


def condition_report(df: pd.DataFrame, conds: dict) -> pd.DataFrame:
    """판정 끝난 신호(성공·실패)를 출처 × 조건(갖춤/안 갖춤)으로 나눠 성공률 비교."""
    j = df[df["status"].isin(["성공", "실패"])].copy()
    if j.empty:
        return pd.DataFrame()
    for k in ("strong", "ovs", "dil"):
        j[k] = [conds.get((t, d), {}).get(k) for t, d in zip(j["ticker"], j["date"])]
    rows = []
    names = {"strong": "① 💰 강한 유입", "ovs": "② 과매도", "dil": "③ 희석 없음"}
    for src, g in j.groupby("출처"):
        for k, nm in names.items():
            yes, no = g[g[k] == 1], g[g[k] == 0]
            rows.append({"출처": src, "조건": nm, "갖춤 신호": len(yes), "갖춤 성공률(%)": None if yes.empty else round(float((yes["status"] == "성공").mean() * 100), 1),
                         "안 갖춤 신호": len(no), "안 갖춤 성공률(%)": None if no.empty else round(float((no["status"] == "성공").mean() * 100), 1)})
        allc = g[(g["strong"] == 1) & (g["ovs"] == 1) & (g["dil"] == 1)]
        rows.append({"출처": src, "조건": "✅ ①+②+③ 모두", "갖춤 신호": len(allc), "갖춤 성공률(%)": None if allc.empty else round(float((allc["status"] == "성공").mean() * 100), 1),
                     "안 갖춤 신호": int(len(g) - len(allc)), "안 갖춤 성공률(%)": None if len(g) == len(allc) else round(float((g.drop(allc.index)["status"] == "성공").mean() * 100), 1)})
    r = pd.DataFrame(rows)
    r["차이(%p)"] = [None if a is None or b is None or pd.isna(a) or pd.isna(b) else round(a - b, 1) for a, b in zip(r["갖춤 성공률(%)"], r["안 갖춤 성공률(%)"])]
    return r
