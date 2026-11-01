"""🔁 병합 체크포인트 — 병합(역분할) 뒤 다시 $1 아래로 떨어질 위험(2026-11-01 · docs/rs_rebreach_check_2026-11-01.md, 김곰 레이더 비교 후보 4).

나스닥 Rule 5810(c)(3)(A)(iv)(2025-01-30~): 최근 1년 안 병합한 회사가 다시 $1 아래면 180일 유예 없이 바로 상장폐지 결정(청문 신청 가능).
우리 자료(병합 2023-11~ · 그날 실제 가격 환산 · 기간 다 지난 것): 1년 안 다시 $1 아래 43% · 6개월 29%(생존편향이라 하한).
병합일 여유(병합일 종가)만 보면 AUC 0.67 → **지금 가격 ÷ 60일 변동성**(ln(지금가/$1) ÷ 변동성·120일 환산) 0.81(병합 60~120일 뒤 0.85~0.86) ·
상습 병합(직전 3년 병합 있음)은 같은 구간에서도 더 위험(2~3 구간 23% vs 4%) → 표 = 거리÷변동성 구간 × 상습 병합 여부, 앞으로 120거래일 안 $1 아래 비율.
검색 단서(병합 전 1년 조달 서류 · 병합 뒤 증자 서류 · 병합 뒤 등락)를 다 더해도 뒤 절반 AUC 0.817 → 0.833 이라 확률엔 안 넣고 '이유 줄'로 보여 준다.
판정·🏆 은 그대로(보여 주기만). 표는 토요일 아침 작업이 최근 3년 병합으로 다시 만든다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

H = 120                          # 앞으로 120거래일(약 6개월)
KS = (5, 20, 60, 120)            # 병합 뒤 몇 거래일째에 볼지(재생)
BINS = (0.5, 1.0, 1.5, 2.0, 3.0)  # 거리÷변동성 구간 경계
MIN_N = 20                       # 칸 표본이 이보다 적으면 상습 여부를 합친 줄로
RED = 30.0                       # 이 % 이상이면 빨강
WINDOW = 365                     # 병합 뒤 1년(나스닥 '유예 없음' 기간)
YEARS = 3                        # 재생 · 상습 병합 기간
OFF_FORMS = ("424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "S-1", "S-1/A", "F-1", "F-1/A", "EFFECT")
DDL = "CREATE TABLE IF NOT EXISTS rs_risk (zb INTEGER NOT NULL, serial INTEGER NOT NULL, n INTEGER, rate REAL, built TEXT, PRIMARY KEY (zb, serial))"
RULE = "나스닥: 병합 1년 안 다시 $1 아래면 180일 유예 없이 상장폐지 결정(2025-01-30~ · 청문 신청 가능)"


def ensure(conn) -> None:
    conn.execute(DDL)


def zband(z: float) -> int:
    return int(np.digitize(z, BINS))


def _vol(cl: np.ndarray) -> float | None:
    """마지막 61개 종가의 60일 변동성(일간 로그수익 표준편차 × √60) · 하루 ×3↑ 계단(환산 빠짐)은 뺌."""
    c = cl[-61:]
    if len(c) < 30:
        return None
    r = np.diff(np.log(c))
    r = r[np.abs(r) < np.log(3)]
    v = float(np.std(r) * np.sqrt(60)) if len(r) >= 20 else None
    return v if v and v > 0 else None


def zscore(price: float, vol: float) -> float:
    return float(np.log(price) / (max(vol, 1e-3) * np.sqrt(H / 60)))


def observations(conn, today: date | None = None) -> pd.DataFrame:
    """재생: 최근 3년 병합 × 병합 뒤 5·20·60·120거래일째(그날 실제 가격 $1↑ · 앞으로 120거래일이 다 지난 것) → z · 상습 · 그 뒤 $1 아래 여부."""
    import pickrisk
    today = today or date.today()
    since = (today - timedelta(days=YEARS * 365)).isoformat()
    cols = ["t", "d", "k", "z", "serial", "y"]
    try:
        ev = pd.read_sql("SELECT ticker, date FROM rs_events WHERE ratio < 1 AND date >= ? AND date <= ? ORDER BY date", conn, params=(since, today.isoformat()))
        px = pd.read_sql("SELECT ticker, date, close FROM daily_prices WHERE close > 0 AND date >= ? AND ticker IN (SELECT DISTINCT ticker FROM rs_events WHERE ratio < 1 AND date >= ?) "
                         "ORDER BY ticker, date", conn, params=((today - timedelta(days=YEARS * 365 + 140)).isoformat(), since))
    except Exception:  # noqa: BLE001 (표 없음)
        return pd.DataFrame(columns=cols)
    if ev.empty or px.empty:
        return pd.DataFrame(columns=cols)
    sp = pickrisk._splits(conn)
    alld = sorted(px.date.unique())
    pg = {t: g for t, g in px.groupby("ticker")}
    rows = []
    for e in ev.itertuples():
        g = pg.get(e.ticker)
        if g is None:
            continue
        d, cl = g.date.tolist(), g.close.to_numpy(float)
        i = int(np.searchsorted(d, e.date))
        if i >= len(d) or i < 61:
            continue
        r = cl[1:] / cl[:-1]
        if ((r[i - 3:min(len(r), i + 250)] >= 3) | (r[i - 3:min(len(r), i + 250)] <= 1 / 3)).any():   # 일봉에 환산 빠진 계단 → 못 믿음
            continue
        s = sp.get(e.ticker, {})
        y3 = str(int(e.date[:4]) - YEARS) + e.date[4:]
        serial = int(any(y3 <= dd < e.date and s[dd] < 1 for dd in s))
        for k in KS:
            j = i + k
            if j >= len(d) or len(alld) - 1 - int(np.searchsorted(alld, d[j])) < H:   # 앞으로 120거래일이 아직 안 지남
                continue
            raw = cl[j] * pickrisk._mult(s, d[j])
            v = _vol(cl[:j + 1])
            if raw < 1 or v is None:
                continue
            fut = np.array([cl[x] * pickrisk._mult(s, d[x]) for x in range(j + 1, min(len(d), j + H + 1))])
            rows.append((e.ticker, e.date, k, zscore(raw, v), serial, bool((fut < 1).any())))
    return pd.DataFrame(rows, columns=cols)


def build(conn, today: date | None = None, out=print) -> dict:
    today = today or date.today()
    ob = observations(conn, today)
    ensure(conn)
    if len(ob) < 100:
        out(f"🔁 병합 체크포인트 표: 관측 {len(ob)} — 부족해서 그대로 둠")
        return {"obs": len(ob), "ok": False}
    ob["zb"] = [zband(z) for z in ob.z]
    rows = [(int(zb), int(se), len(g), float(g.y.mean() * 100), today.isoformat()) for (zb, se), g in ob.groupby(["zb", "serial"])]
    rows += [(int(zb), -1, len(g), float(g.y.mean() * 100), today.isoformat()) for zb, g in ob.groupby("zb")]
    conn.execute("DELETE FROM rs_risk")
    conn.executemany("INSERT INTO rs_risk VALUES (?,?,?,?,?)", rows)
    conn.commit()
    out(f"🔁 병합 체크포인트 표: 병합 {ob[['t', 'd']].drop_duplicates().shape[0]}건 · 관측 {len(ob):,} · 6개월 안 $1 아래 {ob.y.mean() * 100:.0f}%")
    return {"obs": len(ob), "ok": True, "rate": float(ob.y.mean() * 100)}


def maybe_build(conn, today: date | None = None, out=print) -> dict | None:
    """토요일(하루 한 번) 또는 표가 비었으면 다시."""
    today = today or date.today()
    ensure(conn)
    r = conn.execute("SELECT MAX(built) FROM rs_risk").fetchone()
    if r and r[0] and not (today.weekday() == 5 and r[0] < today.isoformat()):
        return None
    return build(conn, today, out)


def table(conn) -> dict:
    try:
        return {(zb, se): (n, rate) for zb, se, n, rate in conn.execute("SELECT zb, serial, n, rate FROM rs_risk")}
    except Exception:  # noqa: BLE001
        return {}


def lookup(tab: dict, z: float, serial: bool) -> float | None:
    zb = zband(z)
    c = tab.get((zb, int(bool(serial))))
    if not c or c[0] < MIN_N:
        c = tab.get((zb, -1))
    return None if not c or not c[0] else float(c[1])


def _splits_one(conn, t: str) -> dict[str, float]:
    import db
    out = {}
    try:
        for d, r in conn.execute("SELECT date, ratio FROM rs_events WHERE ticker=? AND ratio > 0", (t,)):
            out[d] = float(r)
        for s in ((db.get_report(t, conn) or {}).get("company") or {}).get("splits") or []:   # 리포트 쪽은 같은 병합이 하루쯤 다른 날짜로 있을 수 있음 → 5일 안이면 같은 병합
            if s.get("date") and s.get("ratio") and not any(abs((date.fromisoformat(s["date"][:10]) - date.fromisoformat(d0)).days) <= 5 for d0 in out):
                out[s["date"][:10]] = float(s["ratio"])
    except Exception:  # noqa: BLE001
        pass
    return out


def _closes(conn, t: str, today: date) -> tuple[list[str], np.ndarray]:
    rows = conn.execute("SELECT date, close FROM daily_prices WHERE ticker=? AND close > 0 AND date <= ? ORDER BY date DESC LIMIT 400", (t, today.isoformat())).fetchall()
    rows = rows[::-1]
    return [r[0] for r in rows], np.array([r[1] for r in rows], float)


def _reasons(conn, t: str, rs_date: str, today: date) -> dict:
    """이유 줄 재료(확률엔 안 씀): 병합 뒤 증자 서류 · 병합 전 1년 조달 서류 · 런웨이."""
    y1 = str(int(rs_date[:4]) - 1) + rs_date[4:]
    q = f"SELECT COUNT(*) FROM sec_hist WHERE ticker=? AND filed > ? AND filed <= ? AND (form IN ({','.join('?' * len(OFF_FORMS))}) OR (form='8-K' AND items LIKE '%3.02%'))"
    off_after = fin_1y = None
    try:
        off_after = conn.execute(q, (t, rs_date, today.isoformat(), *OFF_FORMS)).fetchone()[0]
        fin_1y = conn.execute(q, (t, y1, rs_date, *OFF_FORMS)).fetchone()[0]
    except Exception:  # noqa: BLE001 (sec_hist 없음)
        pass
    runway = None
    try:
        import runway as _rw
        rn = _rw.now(t, conn)
        runway = None if not rn or rn.get("stale") else rn.get("runway_now")
    except Exception:  # noqa: BLE001
        pass
    return {"off_after": off_after, "fin_1y": fin_1y, "runway": runway}


def current(conn, t: str, today: date | None = None, tab: dict | None = None) -> dict | None:
    """최근 1년 안 병합한 종목이면 {rs_date, days(거래일), price, vol, z, serial, prob(%), below, until, 이유…}, 아니면 None."""
    import pickrisk
    today = today or date.today()
    t = t.upper()
    try:
        r = conn.execute("SELECT date FROM rs_events WHERE ticker=? AND ratio < 1 AND date <= ? AND date > ? ORDER BY date DESC LIMIT 1",
                         (t, today.isoformat(), (today - timedelta(days=WINDOW)).isoformat())).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not r:
        return None
    rs_date = r[0]
    sp = _splits_one(conn, t)
    d, cl = _closes(conn, t, today)
    if len(cl) < 30:
        return None
    price = float(cl[-1] * pickrisk._mult(sp, d[-1]))
    v = _vol(cl)
    y3 = str(int(rs_date[:4]) - YEARS) + rs_date[4:]
    n_prior = sum(1 for dd, ra in sp.items() if y3 <= dd < rs_date and ra < 1)
    tab = table(conn) if tab is None else tab
    z = zscore(price, v) if (v and price >= 1) else None
    out = {"ticker": t, "rs_date": rs_date, "days": sum(1 for x in d if x > rs_date), "price": price, "vol": v, "z": z, "serial": n_prior,
           "below": price < 1, "until": (date.fromisoformat(rs_date) + timedelta(days=WINDOW)).isoformat(),
           "prob": None if z is None else lookup(tab, z, n_prior > 0)}
    out.update(_reasons(conn, t, rs_date, today))
    return out


def upcoming(conn, t: str, today: date | None = None, tab: dict | None = None) -> dict | None:
    """병합 7일 안(🗓 '역분할 시행' · 비율 1:N 이 있을 때): 병합 뒤 예상가(지금가 × N) · 지금 변동성으로 같은 확률."""
    import rsplit
    today = today or date.today()
    s = rsplit.soon(conn, t, today=today)
    if not s:
        return None
    m = re.search(r"1:(\d+)", s.get("title") or "")
    if not m:
        return None
    n = int(m.group(1))
    d, cl = _closes(conn, t.upper(), today)
    if len(cl) < 30:
        return None
    exp = float(cl[-1] * n)
    v = _vol(cl)
    y3 = (date.fromisoformat(s["date"]) - timedelta(days=YEARS * 365)).isoformat()
    sp = _splits_one(conn, t.upper())
    n_prior = sum(1 for dd, ra in sp.items() if y3 <= dd < s["date"] and ra < 1)
    tab = table(conn) if tab is None else tab
    z = zscore(exp, v) if (v and exp >= 1) else None
    return {"date": s["date"], "d": s["d"], "ratio": n, "exp_price": exp, "vol": v, "z": z, "serial": n_prior, "prob": None if z is None else lookup(tab, z, n_prior > 0)}


def reason_line(r: dict) -> str:
    parts = [f"지금가 ${r['price']:.2f}" if r.get("price") is not None else None, f"변동성 {r['vol'] * 100:.0f}%" if r.get("vol") else None,
             f"상습 병합(직전 3년 {r['serial']}번)" if r.get("serial") else None,
             f"병합 뒤 증자 서류 {r['off_after']}건" if r.get("off_after") else None, f"병합 전 1년 조달 서류 {r['fin_1y']}건" if r.get("fin_1y") else None,
             f"런웨이 {r['runway']:.1f}개월" if r.get("runway") is not None else None]
    return " · ".join(p for p in parts if p)


def _when(r: dict) -> str:
    return "병합 당일" if not r.get("days") else f"병합 {r['days']}일째"


def chip(r: dict | None) -> tuple[str, str] | None:
    """(글자, 색) — 서랍 칩용."""
    if not r:
        return None
    if r["below"]:
        return f"🔁 {_when(r)} · 이미 $1 아래", "red"
    if r.get("prob") is None:
        return f"🔁 {_when(r)}", "orange"
    return f"🔁 {_when(r)} · 6개월 안 $1 아래 약 {r['prob']:.0f}%", "red" if r["prob"] >= RED else "orange"


def short(r: dict | None) -> str:
    """PICK 이유 등 한 줄 꼬리."""
    c = chip(r)
    return "" if not c else c[0]


def upcoming_tail(u: dict | None) -> str:
    """'🚫 병합 예정' 줄 꼬리."""
    if not u or u.get("prob") is None:
        return ""
    return f" · 병합 뒤 예상 ${u['exp_price']:.2f} → 6개월 안 $1 아래 약 {u['prob']:.0f}%"
