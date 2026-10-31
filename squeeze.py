"""🧨 숏스퀴즈 점수 v2 — 공매도 잔고(Float Short %)·청산 소요일(Days to Cover)을 중심으로.

점수(100) = Float Short % 30(40%↑ 만점) + 청산 소요일 20(10일↑ 만점) + 대차 수수료 15(100%↑ 만점) + 대차 가용 10(0주=빌릴 주식 없음 만점, 1만 주 이하 5)
          + Reg SHO 10(13일↑ 만점) + FINRA 공매도 거래 비중 5(60%↑ 만점, 40% 이하 0) + 유통주식 5(500만 주↓ 5, 2,000만 주↓ 2.5) + 1개월 상승 5(+30%↑ 만점).
공매도 잔고는 Yahoo(FINRA 격주 공시 기반)라 며칠 늦다. 압박이 쌓였다는 뜻이지 급등을 보장하지 않는다.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date

import db


def clip01(x):
    return 0.0 if x is None else max(0.0, min(1.0, float(x)))


def score(si_pct=None, dtc=None, fee=None, avail=None, avail_stale=False, sho_days=None, sv_ratio=None, float_sh=None, r30=None) -> dict:
    parts = {"공매도 비율": clip01((si_pct or 0) / 40) * 30, "청산 소요일": clip01((dtc or 0) / 10) * 20, "대차 수수료": clip01((fee or 0) / 100) * 15,
             "대차 가용": 10.0 if (avail_stale or avail == 0) else (5.0 if avail is not None and avail <= 10_000 else 0.0),
             "Reg SHO": clip01((sho_days or 0) / 13) * 10, "공매도 거래 비중": clip01(((sv_ratio or 0) - 40) / 20) * 5,
             "유통주식": 5.0 if float_sh and float_sh <= 5e6 else (2.5 if float_sh and float_sh <= 20e6 else 0.0), "1개월 상승": clip01((r30 or 0) / 30) * 5}
    return {"parts": parts, "score": round(sum(parts.values()), 1)}


def universe(conn) -> list[str]:
    out: set[str] = set()
    for sql in ("SELECT DISTINCT ticker FROM daily_snapshots WHERE date >= date('now','-10 day')", "SELECT symbol FROM ibkr_borrow WHERE fee >= 20",   # C단계: 수수료 50→20
                "SELECT DISTINCT ticker FROM toss_rank WHERE date >= date('now','-3 day')",                                                              # 급상승/급하락 100
                "SELECT symbol FROM finra_shvol WHERE date=(SELECT MAX(date) FROM finra_shvol) AND total >= 200000 AND short >= total*0.6"):         # 장외 공매도 비중 60%↑
        try:
            out |= {r[0] for r in conn.execute(sql)}
        except Exception:  # noqa: BLE001
            pass
    try:
        import piggy
        import regsho
        import watch
        out |= set(regsho.streaks(conn)) | set(watch.scanner_priority()) | set(piggy.tickers())
    except Exception:  # noqa: BLE001
        pass
    try:  # P1: 토스 거래 가능 보통주만(ETF·상폐 제외) — 목록이 없으면 그대로
        import tradable
        act = tradable.active(conn)
        if act:
            out = {t for t in out if t in act}
    except Exception:  # noqa: BLE001
        pass
    return sorted(out)


def rows(r30: dict | None = None) -> list[dict]:
    """후보 전체의 점수(높은 순)."""
    import regsho
    import shortint
    si = shortint.latest_map()
    with closing(db.connect()) as conn:
        uni = universe(conn)
        sho = regsho.streaks(conn)
        intel = {}
        try:
            intel = {r["ticker"]: json.loads(r["data"]) for r in conn.execute(
                "SELECT ticker, data FROM ticker_intel WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM ticker_intel GROUP BY ticker)")}
        except Exception:  # noqa: BLE001
            pass
        ib = {}
        try:
            ib = {r["symbol"]: dict(r) for r in conn.execute("SELECT symbol, fee, available, avail_capped FROM ibkr_borrow")}
        except Exception:  # noqa: BLE001
            pass
        fl = {r[0]: r[1] for r in conn.execute("SELECT ticker, float_shares FROM daily_snapshots WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM daily_snapshots GROUP BY ticker)")}
    out = []
    for t in uni:
        sh = (intel.get(t) or {}).get("short") or {}
        s, b = si.get(t) or {}, ib.get(t)
        fee = sh.get("borrow_fee") if sh.get("borrow_fee") is not None else (b or {}).get("fee")
        avail = sh.get("borrow_avail") if sh.get("borrow_avail") is not None else (b or {}).get("available")
        stale = bool(sh.get("borrow_stale")) or (b is None and t in ib)
        fs = s.get("float_sh") or fl.get(t)
        sc = score(s.get("si_pct"), s.get("dtc"), fee, avail, stale, sho.get(t), sh.get("sv_ratio"), fs, (r30 or {}).get(t))
        out.append({"ticker": t, **sc, "si_pct": s.get("si_pct"), "dtc": s.get("dtc"), "si_date": s.get("si_date"), "fee": fee, "avail": avail, "stale": stale,
                    "sho": sho.get(t), "sv_ratio": sh.get("sv_ratio"), "float_sh": fs, "r30": (r30 or {}).get(t)})
    return sorted(out, key=lambda x: -x["score"])


def save_ranks(rs: list[dict], day: str | None = None, track_from: list[dict] | None = None) -> dict[str, int | None]:
    """오늘 순위를 저장하고 전날 대비 변화(↑ 양수)를 돌려준다. track_from: 감시 목록을 고를 전체 순위(없으면 rs — 상위 100만 저장할 때도 감시는 150)."""
    day = day or date.today().isoformat()
    with closing(db.connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS squeeze_rank (date TEXT NOT NULL, ticker TEXT NOT NULL, rank INTEGER, score REAL, PRIMARY KEY (date, ticker))")
        conn.executemany("INSERT OR REPLACE INTO squeeze_rank VALUES (?,?,?,?)", [(day, r["ticker"], i, r["score"]) for i, r in enumerate(rs, 1)])
        prev_day = conn.execute("SELECT MAX(date) FROM squeeze_rank WHERE date < ?", (day,)).fetchone()[0]
        prev = {r[0]: r[1] for r in conn.execute("SELECT ticker, rank FROM squeeze_rank WHERE date=?", (prev_day,))} if prev_day else {}
        conn.execute("INSERT OR REPLACE INTO shortdata_meta (k, v, t) VALUES ('tracked', ?, 0)", (json.dumps(tracked(conn, track_from or rs)),)) if conn.execute(
            "SELECT name FROM sqlite_master WHERE name='shortdata_meta'").fetchone() else None
        conn.commit()
    return {r["ticker"]: (prev[r["ticker"]] - i if r["ticker"] in prev else None) for i, r in enumerate(rs, 1)}


def tracked(conn, rs: list[dict]) -> list[str]:
    """15분마다 대차 가용주식·수수료를 기록할 감시 목록 = 스퀴즈 상위 150 + Reg SHO 연속 + 워치리스트(스캐너 우선) + 저금통.
    2026-10-31: 예전엔 스퀴즈 상위만 넣어 shortdata 주석('스퀴즈 상위·Reg SHO·워치리스트·저금통')과 달랐음."""
    out = [r["ticker"] for r in rs[:150]]
    extra: list = []
    for src in (lambda: __import__("regsho").streaks(conn), lambda: __import__("watch").scanner_priority(),
                lambda: __import__("piggy").tickers_all()):   # 저금통은 방문객 가림 없는 전체(아침 작업용) · 하나가 실패해도 나머지는 넣음
        try:
            extra += list(src())
        except Exception:  # noqa: BLE001
            pass
    return list(dict.fromkeys(out + [str(t).upper() for t in extra if t]))


def daily(out=print, day: str | None = None) -> int:
    """아침 작업: 오늘 순위·감시 목록 저장. 2026-10-31: 예전엔 🧨 스퀴즈 랭크 화면을 열 때만 저장해 10/26 뒤로 멈춤 —
    '전날 대비 순위 변화'가 어제가 아니라 마지막으로 연 날 대비였고, 15분 대차 기록의 감시 목록도 10/26 그대로였음."""
    rs = rows()
    if not rs:
        return 0
    save_ranks(rs[:100], day, track_from=rs)
    out(f"🧨 스퀴즈 순위 저장: 후보 {len(rs)}종목 · 1위 {rs[0]['ticker']}({rs[0]['score']:.0f}점)")
    return len(rs)
