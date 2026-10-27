"""🪪 토스 거래 가능 종목 목록 (P1 2026-10-27) — 스캐너가 하루 한 번 토스 종목 정보(NASDAQ·AMEX·NYSE, ACTIVE)를 `toss_active` 에 저장한다.

왜: 다크풀·Reg SHO·스퀴즈 표에 ETF·상장폐지·토스 미지원 종목(LQTI 등)이 섞였다. FINRA·IBKR 자료는 미국 전체 종목을 담고 있어서
우리 쪽에서 '토스에서 실제로 살 수 있는 보통주'만 남겨야 한다. 표가 비어 있으면(PC·첫 실행) 각 화면은 예전 규칙으로 돌아간다.
"""
from __future__ import annotations

from contextlib import closing

import db

DDL = """CREATE TABLE IF NOT EXISTS toss_active (symbol TEXT PRIMARY KEY, name TEXT, market TEXT, security_type TEXT, is_common INTEGER, status TEXT, updated TEXT)"""
EXCLUDED_TYPES = {"ETF", "FOREIGN_ETF", "ETN", "STOCK_WARRANTS", "INFRASTRUCTURE_FUND"}
MARKETS = ("NASDAQ", "AMEX", "NYSE")
_CACHE: dict = {"at": 0.0, "set": None}


def ensure(conn) -> None:
    conn.execute(DDL)


def refresh(conn, tc, markets=MARKETS, out=None) -> int:
    """토스 종목 정보를 통째로 다시 저장(시장별 실패는 건너뜀). 반환 저장 건수."""
    ensure(conn)
    rows = []
    for m in markets:
        try:
            items = tc.stocks_all(m) or []
        except Exception as e:  # noqa: BLE001
            if out:
                out(f"토스 종목 목록({m}) 실패: {e}")
            continue
        for it in items:
            sym = str(it.get("symbol") or "").strip().upper()
            if not sym:
                continue
            rows.append((sym, (it.get("name") or it.get("companyName") or "")[:80], m, it.get("securityType") or "", 0 if it.get("isCommonShare") is False else 1,
                         it.get("status") or "ACTIVE", db.utcnow_iso()))
    if not rows:
        return 0
    conn.execute("DELETE FROM toss_active")
    conn.executemany("INSERT OR REPLACE INTO toss_active VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    _CACHE["set"] = None
    return len(rows)


def refresh_daily(conn, tc, out=None) -> int:
    """하루 한 번만(meta toss_active_day)."""
    from datetime import date
    today = date.today().isoformat()
    m = db.get_meta("toss_active_day")
    if m and m.get("value") == today:
        return 0
    n = refresh(conn, tc, out=out)
    if n:
        db.set_meta("toss_active_day", today)
    return n


def active(conn=None, ttl: float = 600) -> set[str]:
    """토스에서 지금 살 수 있는 보통주(ETF·워런트·우선주·상폐 제외). 표가 없거나 비면 빈 집합(→ 예전 규칙으로)."""
    import time
    if _CACHE["set"] is not None and time.time() - _CACHE["at"] < ttl:
        return _CACHE["set"]

    def _run(c):
        try:
            ensure(c)
            q = ",".join("?" * len(EXCLUDED_TYPES))
            return {r[0] for r in c.execute(f"SELECT symbol FROM toss_active WHERE status='ACTIVE' AND is_common=1 AND security_type NOT IN ({q})", tuple(EXCLUDED_TYPES))}
        except Exception:  # noqa: BLE001
            return set()
    s = _run(conn) if conn is not None else None
    if s is None:
        with closing(db.connect()) as c:
            s = _run(c)
    _CACHE.update({"set": s, "at": time.time()})
    return s


def info(symbol: str, conn=None) -> dict | None:
    def _run(c):
        try:
            ensure(c)
            r = c.execute("SELECT * FROM toss_active WHERE symbol=?", (symbol.upper(),)).fetchone()
            return dict(r) if r else None
        except Exception:  # noqa: BLE001
            return None
    if conn is not None:
        return _run(conn)
    with closing(db.connect()) as c:
        return _run(c)


def label(symbol: str, act: set[str] | None = None) -> str:
    """헤더 배지용: '' (거래 가능) · '토스 미지원'(목록에 없음·상폐) · 'ETF·펀드' 등."""
    act = active() if act is None else act
    if not act:
        return ""
    if symbol.upper() in act:
        return ""
    i = info(symbol)
    if not i:
        return "토스 미지원"
    if i.get("status") != "ACTIVE":
        return "토스 상장폐지·거래정지"
    if i.get("security_type") in EXCLUDED_TYPES:
        return "ETF·펀드·워런트"
    if not i.get("is_common"):
        return "보통주 아님"
    return "토스 미지원"
