"""📡 ChartExchange API (2026-10-27) — 과거 누적 숏 데이터: 공매도 잔고 일별 시계열 · FTD(결제 실패) · 거래소별 공매도 거래량 · 발행/유통 주식수 · 대차 수수료 이력.

python chartex.py collect            매일 아침(quant-chartex.timer 06:40 KST): 후보 종목의 새 자료만 받기(종목당 1~3회 요청)
python chartex.py backfill [--n 700] 처음 한 번: 2년치 소급(시간이 걸림)
python chartex.py status

키는 .env 의 CHARTEXCHANGE_API_KEY 만 읽는다(없으면 모든 기능 꺼짐 → 야후·FINRA 로 동작). 요청은 분당 CHARTEXCHANGE_RPM(기본 55, Tier 1 = 60) 이하.
심볼 표기 US:TICKER · 응답은 최신순 + 페이지(page_size ≤ 1000, next) · 날짜 필터 파라미터는 없어서 필요한 날짜까지만 페이지를 넘긴다.
응답 필드(2026-10-27 실제 호출로 확인):
  short-interest-daily / short-interest: date, short_interest(유통 대비 %), short_position(주), days_to_cover, change_number, change_percent
  failure-to-deliver: date(결제일), fails(주), price, t(거래일), t_35(강제 매수 기한), noti(금액 $), change
  short-volume: date, rt(전체), st(공매도 합계), lt(일반), fs(FINRA 장외 공매도), fse(장외 면제), 거래소별(xnas xnys arcx …) — 래빗스탁 '숏볼륨' = st(장외+거래소 합)
  shares: date, shares_out, shares_float, free_float(%)   borrow-fee/ib: timestamp, available, fee, rebate
받은 공매도 잔고는 기존 short_interest 표에도 넣어(src='chartexchange') 스퀴즈 랭크·AI PICK·공매도 상세가 그대로 쓴다(야후보다 매일 값이고 전 종목).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta

import pandas as pd

import db

log = logging.getLogger("chartex")
BASE = "https://chartexchange.com/api/v1/"
EXCH_COLS = ("xnas", "xphl", "xnys", "arcx", "xcis", "xase", "xchi", "edgx", "bats", "edga", "baty")
DDL = [
    """CREATE TABLE IF NOT EXISTS cx_short_interest (ticker TEXT NOT NULL, date TEXT NOT NULL, si_pct REAL, short_shares REAL, dtc REAL, change_shares REAL, change_pct REAL,
       reported INTEGER DEFAULT 0, PRIMARY KEY (ticker, date))""",
    """CREATE TABLE IF NOT EXISTS cx_ftd (ticker TEXT NOT NULL, settle_date TEXT NOT NULL, trade_date TEXT, fails REAL, price REAL, notional REAL, t35 TEXT, change REAL,
       PRIMARY KEY (ticker, settle_date))""",
    """CREATE TABLE IF NOT EXISTS cx_short_volume (ticker TEXT NOT NULL, date TEXT NOT NULL, total REAL, short_total REAL, long_total REAL, finra_short REAL, finra_exempt REAL,
       exch_short REAL, short_pct REAL, PRIMARY KEY (ticker, date))""",
    "CREATE TABLE IF NOT EXISTS cx_shares (ticker TEXT NOT NULL, date TEXT NOT NULL, shares_out REAL, shares_float REAL, free_float REAL, PRIMARY KEY (ticker, date))",
    "CREATE TABLE IF NOT EXISTS cx_borrow (ticker TEXT NOT NULL, ts TEXT NOT NULL, available REAL, fee REAL, rebate REAL, PRIMARY KEY (ticker, ts))",
    "CREATE TABLE IF NOT EXISTS cx_progress (ticker TEXT NOT NULL, kind TEXT NOT NULL, last_date TEXT, updated TEXT, PRIMARY KEY (ticker, kind))",
    "CREATE TABLE IF NOT EXISTS cx_signals (date TEXT NOT NULL, ticker TEXT NOT NULL, kind TEXT NOT NULL, value REAL, note TEXT, PRIMARY KEY (date, ticker, kind))",
]
KINDS = ("si", "ftd", "sv", "shares")
BACKFILL_DAYS = 730
SI_UP_PCT = 30.0      # 🏆 신호: 보고된 공매도 잔고가 직전 보고 대비 +30% 이상
FTD_SPIKE_X = 3.0     # 🏆 신호: FTD 가 최근 20일 평균의 3배 이상(1만 주 이상)
FTD_MIN = 10_000


def ensure(conn) -> None:
    for d in DDL:
        conn.execute(d)
    have = {r[1] for r in conn.execute("PRAGMA table_info(short_interest)")}
    if have and "src" not in have:
        conn.execute("ALTER TABLE short_interest ADD COLUMN src TEXT")
    conn.commit()


def api_key() -> str:
    return os.environ.get("CHARTEXCHANGE_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def _f(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


class Client:
    """요청 속도 제한(분당 rpm) · 429 면 1분 쉬고 한 번 더 · JSON 아니면 오류."""

    def __init__(self, key: str | None = None, rpm: int | None = None, http_get=None):
        import config
        self.key = key or api_key()
        self.rpm = int(rpm or getattr(config, "CHARTEXCHANGE_RPM", 55))
        self.http_get = http_get
        self._last = 0.0
        self.calls = 0

    def _wait(self) -> None:
        gap = 60.0 / max(self.rpm, 1)
        d = time.monotonic() - self._last
        if d < gap:
            time.sleep(gap - d)
        self._last = time.monotonic()

    def get(self, endpoint: str, **params) -> dict:
        if not self.key:
            raise RuntimeError("CHARTEXCHANGE_API_KEY 없음")
        url = BASE + endpoint.lstrip("/")
        q = {**params, "api_key": self.key}
        for attempt in range(2):
            self._wait()
            self.calls += 1
            if self.http_get is not None:
                status, body = self.http_get(url, q)
            else:
                import requests
                r = requests.get(url, params=q, headers={"User-Agent": "quant-dashboard"}, timeout=40)
                status, body = r.status_code, r.text
            if status == 429 and attempt == 0:
                time.sleep(61)
                continue
            if status != 200:
                raise RuntimeError(f"HTTP {status} {endpoint}")
            import json
            try:
                j = json.loads(body)
            except ValueError as e:
                raise RuntimeError(f"JSON 아님 {endpoint}") from e
            return j if isinstance(j, dict) else {"results": j}
        raise RuntimeError(f"429 반복 {endpoint}")

    def rows(self, endpoint: str, symbol: str, since: str | None = None, date_key: str = "date", page_size: int = 1000, max_pages: int = 3) -> list[dict]:
        """최신순 페이지를 since 날짜에 닿을 때까지 받는다(날짜 필터 파라미터가 없음)."""
        out: list[dict] = []
        page = 1
        while page <= max_pages:
            j = self.get(endpoint, symbol=f"US:{symbol.upper()}", page_size=page_size, page=page)
            res = j.get("results") or []
            if not res:
                break
            for r in res:
                if since and str(r.get(date_key) or "") < since:
                    return out
                out.append(r)
            if not j.get("next") or len(res) < page_size:
                break
            page += 1
        return out


# ---------------------------------------------------------------- 저장
def _since(conn, t: str, kind: str, backfill: bool) -> str:
    if backfill:
        return (date.today() - timedelta(days=BACKFILL_DAYS)).isoformat()
    r = conn.execute("SELECT last_date FROM cx_progress WHERE ticker=? AND kind=?", (t, kind)).fetchone()
    return r[0] if r and r[0] else (date.today() - timedelta(days=BACKFILL_DAYS)).isoformat()


def _mark(conn, t: str, kind: str, rows: list[dict], date_key: str = "date") -> None:
    last = max((str(r.get(date_key) or "") for r in rows), default=None)
    if last:
        conn.execute("INSERT OR REPLACE INTO cx_progress VALUES (?,?,?,?)", (t, kind, last, db.utcnow_iso()))


def save_si(conn, t: str, rows: list[dict], reported: bool) -> int:
    n = 0
    for r in rows:
        if not r.get("date"):
            continue
        conn.execute("INSERT OR REPLACE INTO cx_short_interest VALUES (?,?,?,?,?,?,?,?)",
                     (t, r["date"], _f(r.get("short_interest")), _f(r.get("short_position")), _f(r.get("days_to_cover")), _f(r.get("change_number")), _f(r.get("change_percent")), 1 if reported else 0))
        n += 1
    return n


def save_ftd(conn, t: str, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        if not r.get("date"):
            continue
        conn.execute("INSERT OR REPLACE INTO cx_ftd VALUES (?,?,?,?,?,?,?,?)",
                     (t, r["date"], r.get("t"), _f(r.get("fails")), _f(r.get("price")), _f(r.get("noti")), r.get("t_35"), _f(r.get("change"))))
        n += 1
    return n


def save_sv(conn, t: str, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        if not r.get("date"):
            continue
        tot, st_ = _f(r.get("rt")), _f(r.get("st"))
        ex = sum(_f(r.get(c)) or 0 for c in EXCH_COLS)
        conn.execute("INSERT OR REPLACE INTO cx_short_volume VALUES (?,?,?,?,?,?,?,?,?)",
                     (t, r["date"], tot, st_, _f(r.get("lt")), _f(r.get("fs")), _f(r.get("fse")), ex, None if not tot or st_ is None else st_ / tot * 100))
        n += 1
    return n


def save_shares(conn, t: str, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        if not r.get("date"):
            continue
        conn.execute("INSERT OR REPLACE INTO cx_shares VALUES (?,?,?,?,?)", (t, r["date"], _f(r.get("shares_out")), _f(r.get("shares_float")), _f(r.get("free_float"))))
        n += 1
    return n


def mirror_short_interest(conn, t: str, day: str | None = None) -> bool:
    """최신 일별 잔고를 기존 short_interest 표에 넣는다(src='chartexchange') → 스퀴즈 랭크·AI PICK·공매도 상세가 그대로 씀."""
    r = conn.execute("SELECT date, si_pct, short_shares, dtc, change_shares FROM cx_short_interest WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
    if not r:
        return False
    sh = conn.execute("SELECT shares_float FROM cx_shares WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
    day = day or date.today().isoformat()
    prior = None if r[2] is None or r[4] is None else r[2] - r[4]
    conn.execute("INSERT OR REPLACE INTO short_interest (ticker, date, shares_short, prior, si_pct, dtc, si_date, float_sh, src) VALUES (?,?,?,?,?,?,?,?,?)",
                 (t, day, r[2], prior, r[1], r[3], r[0], sh[0] if sh else None, "chartexchange"))
    return True


def pull(conn, client: Client, t: str, kinds=KINDS, backfill: bool = False, shares_ok: dict | None = None) -> dict:
    """종목 하나: 종류별로 새 자료만 받아 저장. 반환 {kind: 건수}."""
    t = t.upper()
    out = {}
    if "si" in kinds:
        since = _since(conn, t, "si", backfill)
        rows = client.rows("data/stocks/short-interest-daily/", t, since)
        out["si"] = save_si(conn, t, rows, reported=False)
        if backfill or not rows:
            rep = client.rows("data/stocks/short-interest/", t, since, page_size=200)
            out["si"] += save_si(conn, t, rep, reported=True)
        else:   # 보고값 표시: 일별 행 중 change_number != 0 인 날이 보고일
            conn.execute("UPDATE cx_short_interest SET reported=1 WHERE ticker=? AND change_shares IS NOT NULL AND change_shares != 0", (t,))
        _mark(conn, t, "si", rows)
    if "ftd" in kinds:
        since = _since(conn, t, "ftd", backfill)
        rows = client.rows("data/stocks/failure-to-deliver/", t, since)
        out["ftd"] = save_ftd(conn, t, rows)
        _mark(conn, t, "ftd", rows)
    if "sv" in kinds:
        since = _since(conn, t, "sv", backfill)
        rows = client.rows("data/stocks/short-volume/", t, since)
        out["sv"] = save_sv(conn, t, rows)
        _mark(conn, t, "sv", rows)
    if "shares" in kinds and (shares_ok is None or shares_ok.get("ok", True)):
        try:
            rows = client.rows("data/stocks/shares/", t, None, page_size=5, max_pages=1)
            out["shares"] = save_shares(conn, t, rows)
            _mark(conn, t, "shares", rows)
        except RuntimeError as e:   # Tier 1 이면 403 → 이번 실행 동안 건너뜀
            if shares_ok is not None and "403" in str(e):
                shares_ok["ok"] = False
            out["shares"] = 0
    if "si" in kinds:   # 유통 주식수까지 받은 뒤 기존 short_interest 표에 거울
        mirror_short_interest(conn, t)
    conn.commit()
    return out


# ---------------------------------------------------------------- 대상 고르기 · 아침 작업
def targets(conn, n_si: int = 700, n_ftd: int = 250, n_sv: int = 300) -> dict[str, list[str]]:
    """종류별 대상: 잔고 = 스퀴즈 후보 우선순위 · FTD = Reg SHO 명단 + 스퀴즈 상위 · 숏볼륨 = 워치·저금통·Reg SHO·다크풀 상위·급상승 상위."""
    si: list[str] = []
    try:
        import shortint
        si = shortint.priority(n_si)
    except Exception:  # noqa: BLE001
        pass
    sho: list[str] = []
    try:
        import regsho
        sho = sorted(regsho.streaks(conn), key=lambda s: -regsho.streaks(conn)[s])
    except Exception:  # noqa: BLE001
        pass
    ftd = list(dict.fromkeys(sho + si))[:n_ftd]
    sv: list[str] = []
    try:
        import piggy
        import watch
        sv += watch.scanner_priority() + piggy.tickers_all()
    except Exception:  # noqa: BLE001
        pass
    sv += sho
    try:
        import darkpool
        sv += list(darkpool.top(conn, n=30)[1]["ticker"])
    except Exception:  # noqa: BLE001
        pass
    try:
        sv += [r[0] for r in conn.execute("SELECT ticker FROM toss_rank WHERE kind='up' ORDER BY date DESC, rank LIMIT 50")]
    except Exception:  # noqa: BLE001
        pass
    sv = list(dict.fromkeys(x.upper() for x in sv if x))[:n_sv]
    return {"si": si, "ftd": ftd, "sv": sv}


def collect(client: Client | None = None, out=print, budget_s: float = 25 * 60, backfill: bool = False, tg: dict | None = None) -> dict:
    """아침: 대상 종목의 새 자료 받기(시간 예산 안에서) → 🏆 신호 기록. 반환 {종목 수, 요청 수, 종류별 건수}."""
    if not enabled() and client is None:
        out("ChartExchange: 키 없음(.env CHARTEXCHANGE_API_KEY) — 건너뜀")
        return {}
    client = client or Client()
    t0 = time.monotonic()
    n = {"si": 0, "ftd": 0, "sv": 0, "shares": 0, "tickers": 0, "errors": 0}
    shares_ok = {"ok": True}
    with closing(db.connect()) as conn:
        ensure(conn)
        tg = tg or targets(conn)
        kinds_of: dict[str, set] = {}
        for k, lst in tg.items():
            for t in lst:
                kinds_of.setdefault(t, set()).add(k)
        for t, ks in kinds_of.items():
            if time.monotonic() - t0 > budget_s:
                out(f"ChartExchange: 시간 예산({budget_s / 60:.0f}분) 소진 — 나머지는 내일")
                break
            ks = set(ks) | ({"shares"} if "si" in ks else set())
            try:
                r = pull(conn, client, t, kinds=tuple(k for k in KINDS if k in ks), backfill=backfill, shares_ok=shares_ok)
            except Exception as e:  # noqa: BLE001
                n["errors"] += 1
                log.warning("ChartExchange %s 실패: %s", t, e)
                continue
            for k, v in r.items():
                n[k] += v
            n["tickers"] += 1
        try:
            n["signals"] = record_signals(conn)
        except Exception as e:  # noqa: BLE001
            log.warning("ChartExchange 신호 기록 실패: %s", e)
    n["calls"] = client.calls
    out(f"ChartExchange: {n['tickers']}종목 · 요청 {n['calls']}회 · 잔고 {n['si']} · FTD {n['ftd']} · 숏볼륨 {n['sv']} · 주식수 {n['shares']} · 신호 {n.get('signals', 0)} · 실패 {n['errors']}"
        + ("" if shares_ok["ok"] else " · 주식수 엔드포인트 권한 없음(Tier 1)"))
    return n


# ---------------------------------------------------------------- 🏆 성과 공표 신호 (오늘 알게 된 자료 기준 — 컨닝 없음)
def record_signals(conn, today: str | None = None) -> int:
    today = today or date.today().isoformat()
    n = 0
    # ① 보고된 잔고가 직전 보고 대비 +30% 이상(최근 14일 안 보고일) — 신호일 = 오늘(자료를 받은 날)
    for r in conn.execute("""SELECT ticker, date, change_pct, si_pct FROM cx_short_interest WHERE reported=1 AND date >= date(?, '-14 day') AND change_pct >= ?""", (today, SI_UP_PCT)):
        cur = conn.execute("INSERT OR IGNORE INTO cx_signals VALUES (?,?,?,?,?)", (today, r[0], "si_up", r[2], f"보고일 {r[1]} 잔고 {r[2]:+.0f}% · 유통 대비 {r[3] or 0:.1f}%"))
        n += cur.rowcount
    # ② FTD 급증: 최신 결제일 FTD ≥ 1만 주이고 최근 20건 평균의 3배 이상
    for t, in conn.execute("SELECT DISTINCT ticker FROM cx_ftd WHERE settle_date >= date(?, '-45 day')", (today,)):
        rows = [x[0] or 0 for x in conn.execute("SELECT fails FROM cx_ftd WHERE ticker=? ORDER BY settle_date DESC LIMIT 21", (t,))]
        if len(rows) >= 6 and rows[0] >= FTD_MIN:
            avg = sum(rows[1:]) / len(rows[1:])
            if avg > 0 and rows[0] >= FTD_SPIKE_X * avg:
                cur = conn.execute("INSERT OR IGNORE INTO cx_signals VALUES (?,?,?,?,?)", (today, t, "ftd_spike", rows[0] / avg, f"FTD {rows[0]:,.0f}주 · 20일 평균의 {rows[0] / avg:.1f}배"))
                n += cur.rowcount
    conn.commit()
    return n


# ---------------------------------------------------------------- 조회(화면용)
def ftd_summary(conn, t: str, days: int = 60) -> dict | None:
    rows = [dict(r) for r in conn.execute("SELECT * FROM cx_ftd WHERE ticker=? ORDER BY settle_date DESC LIMIT 60", (t.upper(),))]
    if not rows:
        return None
    last = rows[0]
    mx = max(rows, key=lambda r: r["fails"] or 0)
    return {"last": last, "max": mx, "n": len(rows), "total": sum(r["fails"] or 0 for r in rows), "notional": sum(r["notional"] or 0 for r in rows)}


def si_series(conn, t: str, days: int = 180) -> pd.DataFrame:
    return db.read_df("SELECT date, si_pct, short_shares, dtc, reported FROM cx_short_interest WHERE ticker=? AND date >= date('now', ?) ORDER BY date", (t.upper(), f"-{days} day"))


def sv_latest(conn, t: str, n: int = 10) -> pd.DataFrame:
    return db.read_df("SELECT date, total, short_total, finra_short, finra_exempt, exch_short, short_pct FROM cx_short_volume WHERE ticker=? ORDER BY date DESC LIMIT ?", (t.upper(), n))


def ftd_map(conn) -> dict[str, dict]:
    try:
        return {r["ticker"]: dict(r) for r in conn.execute("SELECT ticker, settle_date, fails, notional FROM cx_ftd WHERE (ticker, settle_date) IN (SELECT ticker, MAX(settle_date) FROM cx_ftd GROUP BY ticker)")}
    except Exception:  # noqa: BLE001
        return {}


def float_of(conn, t: str) -> dict | None:
    try:
        r = conn.execute("SELECT date, shares_out, shares_float, free_float FROM cx_shares WHERE ticker=? ORDER BY date DESC LIMIT 1", (t.upper(),)).fetchone()
        return dict(r) if r else None
    except Exception:  # noqa: BLE001
        return None


def borrow_recent(conn, client: Client | None, t: str, max_age_h: float = 24) -> pd.DataFrame:
    """대차 수수료 15분 이력(최근 1,000건 ≈ 10일) — 종목 화면에서 열 때 하루 한 번 받아 캐시."""
    t = t.upper()
    ensure(conn)
    r = conn.execute("SELECT updated FROM cx_progress WHERE ticker=? AND kind='borrow'", (t,)).fetchone()
    fresh = r and r[0] and (datetime.now(datetime.fromisoformat(r[0]).tzinfo) - datetime.fromisoformat(r[0])).total_seconds() < max_age_h * 3600
    if not fresh and client is not None and client.key:
        try:
            rows = client.rows("data/stocks/borrow-fee/ib/", t, None, date_key="timestamp", page_size=1000, max_pages=1)
            for x in rows:
                conn.execute("INSERT OR REPLACE INTO cx_borrow VALUES (?,?,?,?,?)", (t, x.get("timestamp"), _f(x.get("available")), _f(x.get("fee")), _f(x.get("rebate"))))
            conn.execute("INSERT OR REPLACE INTO cx_progress VALUES (?,?,?,?)", (t, "borrow", rows[0].get("timestamp") if rows else None, db.utcnow_iso()))
            conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("대차 이력 실패 %s: %s", t, e)
    return db.read_df("SELECT ts, available, fee, rebate FROM cx_borrow WHERE ticker=? ORDER BY ts", (t,))


def status(conn) -> dict:
    ensure(conn)
    out = {}
    for tb, col in (("cx_short_interest", "date"), ("cx_ftd", "settle_date"), ("cx_short_volume", "date"), ("cx_shares", "date"), ("cx_signals", "date")):
        r = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT ticker), MAX({col}) FROM {tb}").fetchone()
        out[tb] = {"rows": r[0], "tickers": r[1], "latest": r[2]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "backfill", "status"])
    ap.add_argument("--n", type=int, default=700)
    ap.add_argument("--budget", type=float, default=25.0, help="분")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.cmd == "status":
        with closing(db.connect()) as conn:
            for k, v in status(conn).items():
                print(k, v)
        return 0
    if not enabled():
        print("CHARTEXCHANGE_API_KEY 가 .env 에 없습니다.")
        return 1
    with closing(db.connect()) as conn:
        ensure(conn)
        tg = targets(conn, n_si=a.n, n_ftd=min(a.n, 250), n_sv=min(a.n, 300))
    collect(out=print, budget_s=a.budget * 60, backfill=(a.cmd == "backfill"), tg=tg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
