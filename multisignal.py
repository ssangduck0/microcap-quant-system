"""멀티 시그널 — 한 종목이 우리 도구 몇 개에 동시에 걸렸는지(최근 기록 기준). 많이 겹칠수록 눈여겨볼 종목."""
from contextlib import closing
from datetime import date, timedelta

import db


def _q(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001
        return []


def collect(days: int = 5) -> dict[str, list[str]]:
    """{티커: [걸린 도구 이름...]} — 최근 days일 안의 신호."""
    since = (date.today() - timedelta(days=days)).isoformat()
    out: dict[str, set] = {}

    def add(t, name):
        if t:
            out.setdefault(str(t).upper(), set()).add(name)
    with closing(db.connect()) as conn:
        try:
            import regsho
            for t in regsho.streaks(conn):
                add(t, "Reg SHO")
        except Exception:  # noqa: BLE001
            pass
        for r in _q(conn, "SELECT ticker FROM shortflow_events WHERE date >= ?", (since,)):
            add(r[0], "공매도 흐름")
        for r in _q(conn, "SELECT ticker, kind FROM flowread_events WHERE date >= ?", (since,)):
            add(r[0], "털기" if r[1].startswith("🔺") or r[1].startswith("✅") else "분산 경고")
        for r in _q(conn, "SELECT ticker, data FROM setup_cache"):
            if '"verdict": "강한 셋업"' in (r[1] or ""):
                add(r[0], "세력·셋업")
        for r in _q(conn, "SELECT ticker FROM rs_current"):
            add(r[0], "병합 후")
        import access
        for r in ([] if access.is_guest() else _q(conn, "SELECT ticker FROM piggy_events WHERE date >= ?", (since,))):
            add(r[0], "저금통 저점")
        for r in _q(conn, "SELECT ticker FROM after_signals WHERE date >= ?", (since,)):
            add(r[0], "애프터 진입")
        for r in _q(conn, "SELECT ticker FROM close_watchlist WHERE kind='frozen' AND date >= ?", (since,)):
            add(r[0], "장마감 고정")
        for r in _q(conn, "SELECT ticker FROM insider_tx WHERE code='P' AND date >= ?", (since,)):
            add(r[0], "내부자 매수")
        for r in _q(conn, "SELECT ticker FROM daily_snapshots WHERE date >= ? AND win_score >= 70", (since,)):
            add(r[0], "승률 점수 70↑")
    return {k: sorted(v) for k, v in out.items()}


def label(names: list[str] | None) -> str:
    return "" if not names else f"{len(names)}개"
