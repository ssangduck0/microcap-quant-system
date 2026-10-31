"""🧭 공매도 방향 기록(2026-11-01, docs/squeeze_validation_2026-11-01.md) — 과거로 검증할 수 없는 두 가지를 🏆 에 기록해 앞으로 검증한다. 판정·순위엔 안 씀.

① 대차 방향(IBKR, 최근 거래일 vs 5거래일 전) — Ortex '이용률'·Tapeboard '수수료 5일 변화'의 무료 대용(IBKR 일별 기록이 10/14부터라 과거 검증 불가):
   빌릴 수 있는 주식 절반↓(5일 전 1만 주↑) + 대차 수수료 1.5배↑ → 🆕 신규 숏 유입 의심 · 숏이 맞다면 10거래일 안 −20%
   빌릴 수 있는 주식 2배↑ + 대차 수수료 2/3↓(5일 전 20%↑) → 🔙 숏 커버 의심 · 10거래일 안 +30%
   (빌릴 주식이 줄어든 건 공매도가 빌려 간 것일 수도, 빌려주던 쪽이 회수한 것일 수도 있어 '의심')
② 사후 가설(2년 검증 보충에서 나중에 나눠 본 결과라 기록만): 🟡·🔴 장세 + 최근 공식 잔고 결제일 종가보다 −20%↓ + 공식 잔고(유통 대비) 10%↑
   → 2년 10거래일 기대값 +5.4%(2024-25) / +4.4%(2026) vs 같은 조건 잔고 5%↓ +4.4% / +3.3%.
같은 종목·같은 종류는 10일에 한 번만 기록. 가격 $20 미만만."""
from __future__ import annotations

from datetime import date, timedelta

DDL = "CREATE TABLE IF NOT EXISTS short_dir_signals (date TEXT, ticker TEXT, kind TEXT, price REAL, note TEXT, PRIMARY KEY (date, ticker, kind))"
DAYS = 5
IN_AVAIL, IN_FEE, IN_MIN_AVAIL = 0.5, 1.5, 10_000
CV_AVAIL, CV_FEE, CV_MIN_FEE = 2.0, 2 / 3, 20.0
FEAR_DROP, FEAR_SI, MAX_PRICE = -0.20, 10.0, 20.0
GAP_DAYS = 10
LABELS = {"ib_inflow": "🆕 신규 숏 유입 의심", "ib_cover": "🔙 숏 커버 의심", "fear_si": "🧪 장세 공포 + 숏 이익 + 잔고 10%↑"}


def ensure(conn) -> None:
    conn.execute(DDL)


def _weekdays(conn, n: int) -> list[str]:
    """ibkr_borrow_day 의 최근 평일 날짜(최신순) — 스캐너가 주말에도 돌아 주말 날짜가 섞일 수 있음."""
    try:
        ds = [r[0] for r in conn.execute("SELECT DISTINCT date FROM ibkr_borrow_day ORDER BY date DESC LIMIT ?", (n * 2 + 6,))]
    except Exception:  # noqa: BLE001
        return []
    return [d for d in ds if date.fromisoformat(d).weekday() < 5][:n]


def borrow_dir(conn, days: int = DAYS, symbol: str | None = None) -> dict[str, dict]:
    """{티커: {kind(ib_inflow·ib_cover·None), avail0, avail1, fee0, fee1, d0, d1}} — 최근 평일(d1) vs days 평일 전(d0). symbol 을 주면 그 종목만."""
    ds = _weekdays(conn, days + 1)
    if len(ds) < days + 1:
        return {}
    d1, d0 = ds[0], ds[days]
    cur: dict[str, dict] = {}
    sql, args = "SELECT symbol, date, open_avail, max_fee FROM ibkr_borrow_day WHERE date IN (?, ?)", (d0, d1)
    if symbol:
        sql, args = sql + " AND symbol=?", (d0, d1, symbol.upper())
    for sym, d, av, fee in conn.execute(sql, args):
        cur.setdefault(sym, {})["1" if d == d1 else "0"] = (av, fee)
    out = {}
    for sym, v in cur.items():
        if "0" not in v or "1" not in v:
            continue
        (a0, f0), (a1, f1) = v["0"], v["1"]
        kind = None
        if a0 is not None and a1 is not None and f0 is not None and f1 is not None:
            if a0 >= IN_MIN_AVAIL and a1 <= a0 * IN_AVAIL and f0 > 0 and f1 >= f0 * IN_FEE:
                kind = "ib_inflow"
            elif a1 >= max(a0, 1) * CV_AVAIL and f0 >= CV_MIN_FEE and f1 <= f0 * CV_FEE:
                kind = "ib_cover"
        out[sym] = {"kind": kind, "avail0": a0, "avail1": a1, "fee0": f0, "fee1": f1, "d0": d0, "d1": d1}
    return out


def _closes(conn, tickers) -> dict[str, list]:
    """{티커: [(날짜, 종가)…]} 최근 90일."""
    out: dict[str, list] = {}
    if not tickers:
        return out
    since = (date.today() - timedelta(days=90)).isoformat()
    tk = list(tickers)
    for k in range(0, len(tk), 500):
        part = tk[k:k + 500]
        for t, d, c in conn.execute(f"SELECT ticker, date, close FROM daily_prices WHERE date >= ? AND ticker IN ({','.join('?' * len(part))}) ORDER BY ticker, date", (since, *part)):
            if c:
                out.setdefault(t, []).append((d, float(c)))
    return out


def fear_si(conn, light: str | None) -> list[dict]:
    """② 사후 가설 후보: 🟡·🔴 장세일 때만. 공식 잔고는 최근 '공통 결제일'(보고 행이 가장 많은 날, 45일 안) 값."""
    if light not in ("yellow", "red"):
        return []
    try:
        r = conn.execute("""SELECT date FROM cx_short_interest WHERE reported=1 AND date >= ? GROUP BY date ORDER BY COUNT(*) DESC, date DESC LIMIT 1""",
                         ((date.today() - timedelta(days=45)).isoformat(),)).fetchone()
        if not r:
            return []
        s = r[0]
        si = {t: p for t, p in conn.execute("SELECT ticker, si_pct FROM cx_short_interest WHERE reported=1 AND date=? AND si_pct >= ?", (s, FEAR_SI))}
    except Exception:  # noqa: BLE001
        return []
    out = []
    for t, cl in _closes(conn, si).items():
        base = [c for d, c in cl if d <= s]
        if not base or cl[-1][0] <= s:
            continue
        px, b = cl[-1][1], base[-1]
        if px < MAX_PRICE and b > 0 and px / b - 1 <= FEAR_DROP:
            out.append({"ticker": t, "price": px, "note": f"{s} 결제 잔고 {si[t]:.1f}% · 결제일 뒤 {(px / b - 1) * 100:+.0f}% · 장세 {light}"})
    return out


def record(conn, rows: list[dict], kind: str, today: date | None = None) -> int:
    today = today or date.today()
    ensure(conn)
    recent = {r[0] for r in conn.execute("SELECT ticker FROM short_dir_signals WHERE kind=? AND date >= ?", (kind, (today - timedelta(days=GAP_DAYS)).isoformat()))}
    n = 0
    for r in rows:
        if r["ticker"] in recent or not r.get("price"):
            continue
        conn.execute("INSERT OR IGNORE INTO short_dir_signals (date, ticker, kind, price, note) VALUES (?,?,?,?,?)", (today.isoformat(), r["ticker"], kind, r["price"], r.get("note", "")[:200]))
        n += 1
    conn.commit()
    return n


def daily(conn, out=print, today: date | None = None, light: str | None = None) -> dict:
    """아침 작업: ① 대차 방향 두 종류 · ② 사후 가설을 기록."""
    ensure(conn)
    if light is None:
        try:
            import regime
            light = (regime.get() or {}).get("light")
        except Exception:  # noqa: BLE001
            light = None
    bd = {t: v for t, v in borrow_dir(conn).items() if v["kind"]}
    px = {t: c[-1][1] for t, c in _closes(conn, bd).items()}
    res = {}
    for kind in ("ib_inflow", "ib_cover"):
        rows = [{"ticker": t, "price": px[t], "note": f"빌릴 주식 {v['avail0']:,.0f}→{v['avail1']:,.0f} · 수수료 {v['fee0']:.1f}→{v['fee1']:.1f}% ({v['d0']}→{v['d1']})"}
                for t, v in bd.items() if v["kind"] == kind and t in px and px[t] < MAX_PRICE]
        res[kind] = record(conn, rows, kind, today)
    res["fear_si"] = record(conn, fear_si(conn, light), "fear_si", today)
    out(f"🧭 공매도 방향 기록: 신규 숏 유입 의심 {res['ib_inflow']} · 커버 의심 {res['ib_cover']} · 장세 공포 가설 {res['fear_si']}(장세 {light or '?'})")
    return res


def label(conn, t: str) -> dict | None:
    """종목 하나의 대차 방향(공매도 상세 화면용)."""
    v = borrow_dir(conn, symbol=t).get(t.upper())
    if not v:
        return None
    txt = LABELS.get(v["kind"]) or "변화 적음"
    return {**v, "label": txt}
