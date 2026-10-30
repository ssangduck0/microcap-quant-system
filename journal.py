"""📒 실제 매매 일지(2026-10-28) — 실제로 산·판 종목을 적어 두면 ① 보유/실현 손익 ② 근거 신호별 실전 성적 ③ 🧪 가상매매와의 차이를 보여 준다.
브로커 연동 없음: 숫자는 사용자가 적은 그대로. 매도는 FIFO(먼저 산 것부터 판 것으로) 로 매수와 짝을 짓는다. 현재가는 우리 일봉(daily_prices)의 마지막 종가."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd


DDL = """CREATE TABLE IF NOT EXISTS trade_journal (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, side TEXT NOT NULL, day TEXT NOT NULL,
         price REAL NOT NULL, qty REAL NOT NULL, fee REAL DEFAULT 0, signal TEXT, note TEXT, created_at TEXT)"""
SIDES = ("매수", "매도")
COLS = ["id", "ticker", "side", "day", "price", "qty", "fee", "signal", "note", "created_at"]


def ensure(conn) -> None:
    conn.execute(DDL)


def signal_options() -> list[str]:
    """입력 폼의 '근거 신호' 보기: 직접 판단 + 🏆 성과 공표의 신호 이름들."""
    try:
        import scoreboard as sb
        return ["직접 판단"] + [v[0] for v in sb.SOURCES.values()]
    except Exception:  # noqa: BLE001
        return ["직접 판단"]


def add(conn, ticker: str, side: str, day: str, price: float, qty: float, signal: str = "", note: str = "", fee: float = 0.0) -> int:
    ensure(conn)
    t = (ticker or "").strip().upper()
    if not t or side not in SIDES:
        raise ValueError("티커와 매수/매도를 적어 주세요")
    if not price or price <= 0 or not qty or qty <= 0:
        raise ValueError("가격과 수량은 0보다 커야 해요")
    date.fromisoformat(str(day)[:10])
    cur = conn.execute("INSERT INTO trade_journal (ticker, side, day, price, qty, fee, signal, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (t, side, str(day)[:10], float(price), float(qty), float(fee or 0), (signal or "").strip(), (note or "").strip(),
                        datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    return int(cur.lastrowid)


def delete(conn, rid: int) -> None:
    ensure(conn)
    conn.execute("DELETE FROM trade_journal WHERE id=?", (int(rid),))
    conn.commit()


def rows(conn) -> pd.DataFrame:
    ensure(conn)
    data = [tuple(r) for r in conn.execute(f"SELECT {', '.join(COLS)} FROM trade_journal ORDER BY day, id").fetchall()]
    return pd.DataFrame(data, columns=COLS)


def last_prices(conn, tickers) -> dict[str, dict]:
    out = {}
    for t in set(tickers):
        try:
            r = conn.execute("SELECT close, date FROM daily_prices WHERE ticker=? AND close IS NOT NULL ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        except Exception:  # noqa: BLE001
            r = None
        if r:
            out[t] = {"close": float(r[0]), "date": r[1]}
    return out


def ledger(conn, last: dict | None = None) -> dict:
    """FIFO 로 매수·매도를 짝지어 {'open': 보유 표, 'closed': 실현 표, 'summary': 숫자}."""
    df = rows(conn)
    if last is None:
        last = last_prices(conn, df["ticker"].unique()) if not df.empty else {}
    open_rows, closed = [], []
    today = date.today()
    for t, g in df.groupby("ticker", sort=True):
        lots: list[dict] = []
        for r in g.itertuples():
            if r.side == "매수":
                lots.append({"day": r.day, "price": float(r.price), "qty": float(r.qty), "signal": r.signal or ""})
                continue
            q = float(r.qty)
            while q > 1e-9 and lots:
                lot = lots[0]
                take = min(q, lot["qty"])
                closed.append({"종목": t, "매수일": lot["day"], "매도일": r.day, "수량": take, "매수가($)": lot["price"], "매도가($)": float(r.price),
                               "손익($)": (float(r.price) - lot["price"]) * take, "손익(%)": (float(r.price) / lot["price"] - 1) * 100,
                               "보유일": (date.fromisoformat(r.day) - date.fromisoformat(lot["day"])).days, "근거 신호": lot["signal"] or "직접 판단"})
                lot["qty"] -= take
                q -= take
                if lot["qty"] <= 1e-9:
                    lots.pop(0)
            if q > 1e-9:   # 매수 기록 없이 판 것(기록 누락)
                closed.append({"종목": t, "매수일": "-", "매도일": r.day, "수량": q, "매수가($)": None, "매도가($)": float(r.price), "손익($)": None, "손익(%)": None,
                               "보유일": None, "근거 신호": "(매수 기록 없음)"})
        for lot in lots:
            lp = (last.get(t) or {}).get("close")
            open_rows.append({"종목": t, "매수일": lot["day"], "수량": lot["qty"], "매수가($)": lot["price"], "현재가($)": lp,
                              "평가손익(%)": None if not lp else (lp / lot["price"] - 1) * 100, "평가손익($)": None if not lp else (lp - lot["price"]) * lot["qty"],
                              "보유일": (today - date.fromisoformat(lot["day"])).days, "근거 신호": lot["signal"] or "직접 판단", "가격 기준일": (last.get(t) or {}).get("date")})
    cl = pd.DataFrame(closed)
    op = pd.DataFrame(open_rows)
    judged = cl.dropna(subset=["손익($)"]) if not cl.empty else cl
    summary = {"n_trades": int(len(df)), "n_closed": int(len(judged)), "n_open": int(len(op)),
               "realized": float(judged["손익($)"].sum()) if len(judged) else 0.0,
               "win_rate": float((judged["손익($)"] > 0).mean() * 100) if len(judged) else None,
               "avg_pct": float(judged["손익(%)"].mean()) if len(judged) else None,
               "unrealized": float(op["평가손익($)"].dropna().sum()) if len(op) and "평가손익($)" in op else 0.0}
    return {"open": op, "closed": cl, "summary": summary}


def by_signal(closed: pd.DataFrame) -> pd.DataFrame:
    """근거 신호별 실전 성적(실현된 것만): 건수·승률·평균 %·합계 $."""
    if closed is None or closed.empty:
        return pd.DataFrame()
    j = closed.dropna(subset=["손익($)"])
    if j.empty:
        return pd.DataFrame()
    g = j.groupby("근거 신호")
    out = pd.DataFrame({"건수": g.size(), "승률(%)": g["손익($)"].apply(lambda s: (s > 0).mean() * 100), "평균 손익(%)": g["손익(%)"].mean(), "합계 손익($)": g["손익($)"].sum(),
                        "평균 보유일": g["보유일"].mean()}).sort_values("합계 손익($)", ascending=False).reset_index()
    return out


def paper_compare(conn) -> pd.DataFrame:
    """내 매수마다 🧪 가상매매도 같은 종목을 샀는지(매수일 ±2일) — 전략·진입가·결과를 나란히."""
    df = rows(conn)
    out = []
    for r in df[df["side"] == "매수"].itertuples():
        pt = None
        try:
            pt = conn.execute("SELECT day, strategy, entry, exit_day, exit, status, reason FROM pt_trades WHERE ticker=? AND day BETWEEN date(?, '-2 day') AND date(?, '+2 day') "
                              "ORDER BY ABS(julianday(day) - julianday(?)) LIMIT 1", (r.ticker, r.day, r.day, r.day)).fetchone()
        except Exception:  # noqa: BLE001
            pt = None
        res = "-"
        if pt:
            res = str(pt[5] or "")
            if pt[4] and pt[2]:
                res += f" {(pt[4] / pt[2] - 1) * 100:+.1f}%"
        out.append({"종목": r.ticker, "내 매수일": r.day, "내 매수가($)": float(r.price), "근거 신호": r.signal or "직접 판단", "가상매매": "있음" if pt else "없음",
                    "가상 전략": (pt[1] or "-") if pt else "-", "가상 진입일": pt[0] if pt else "-", "가상 진입가($)": pt[2] if pt else None, "가상 결과": res.strip() or "-",
                    "가상 사유": (pt[6] or "-") if pt else "-"})
    return pd.DataFrame(out)
