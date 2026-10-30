"""Reg SHO 기준 미달 종목(Threshold List) — 나스닥 공식 무료 파일, 매일.

https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{YYYYMMDD}.txt  (나스닥 상장 종목)
기준 미달 종목: 결제 불이행(주식을 제때 넘기지 못한 물량)이 5결제일 연속 1만 주 이상이면서 발행주식의 0.5% 이상인 종목.
목록에 오래 있으면 공매도 상환 압박(숏 스퀴즈) 신호로 보는 사람이 많다(확정 신호는 아님).
python regsho.py check   최근 파일을 받아 보고 목록 수·예시 종목을 보여 준다.
"""
from __future__ import annotations

import sys
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import logging
import requests

import db

log = logging.getLogger("regsho")

ET = ZoneInfo("America/New_York")
URL = "https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{d}.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# 데이터센터(서버) IP 에서 '크롬인 척하는' 이름표는 나스닥 보안에 걸려 명단 대신 다른 페이지가 옴 → 짧은 이름표 먼저, 안 되면 크롬 이름표
UAS = ("Mozilla/5.0", UA)


def fetch(url: str, timeout: float = 30) -> tuple[int, str]:
    """(HTTP 코드, 본문). 이름표를 바꿔 가며 명단(머리글 Symbol|)이 올 때까지 시도."""
    code, text = 0, ""
    for ua in UAS:
        r = requests.get(url, headers={"User-Agent": ua}, timeout=timeout)
        code, text = r.status_code, (r.text if r.status_code == 200 else "")
        if code == 200 and "symbol|" in text.lower()[:400]:
            return code, text
        if code == 404:
            return code, ""  # 그날 파일이 아직 없음(휴장·미게시) — 다른 이름표로 해도 같음
    return code, text
import re as _re
SYMBOL_RE = _re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MISS_RETRY = 3600
DDL = ["CREATE TABLE IF NOT EXISTS regsho_list (date TEXT NOT NULL, symbol TEXT NOT NULL, name TEXT, PRIMARY KEY (date, symbol))",
       "CREATE TABLE IF NOT EXISTS regsho_files (date TEXT PRIMARY KEY, status TEXT, n INTEGER, fetched_at REAL)"]


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def parse(text: str) -> dict[str, str]:
    """{종목: 이름}. 첫 줄 머리글(Symbol|Security Name|...)과 마지막 줄(파일 생성 시각)은 건너뜀.
    머리글이 없으면(웹페이지·봇 확인 화면 등) 빈 결과 — 종목 코드 모양이 아닌 줄도 버림."""
    if "symbol|" not in (text or "").lower()[:400]:
        return {}
    out = {}
    for line in text.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) < 3 or p[0].lower() == "symbol" or not p[0] or " " in p[0]:
            continue
        if SYMBOL_RE.match(p[0].upper()):
            out[p[0].upper()] = p[1]
    return out


def candidates(now_et: datetime, n: int = 40) -> list[date]:
    """최근 평일(오늘 파일은 동부시간 저녁에 올라오므로 20시 이후에만)."""
    d = now_et.date() if now_et.hour >= 20 else now_et.date() - timedelta(days=1)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def cleanup(conn) -> int:
    """예전에 웹페이지를 목록으로 잘못 읽어 저장한 줄 정리(종목 코드 모양이 아닌 것) — 그날 파일은 다시 받게 표시."""
    bad = [(d, s) for d, s in conn.execute("SELECT date, symbol FROM regsho_list") if not SYMBOL_RE.match(str(s))]
    for d, s in bad:
        conn.execute("DELETE FROM regsho_list WHERE date=? AND symbol=?", (d, s))
    for d in {d for d, _ in bad}:
        if not conn.execute("SELECT 1 FROM regsho_list WHERE date=? LIMIT 1", (d,)).fetchone():
            conn.execute("DELETE FROM regsho_files WHERE date=?", (d,))
    conn.commit()
    return len(bad)


def refresh(conn, http_get=None, now: datetime | None = None, days: int = 40) -> int:
    """아직 없는 날짜 파일을 받는다(휴장일·미게시는 1시간 뒤 다시). 새로 받은 파일 수."""
    ensure_tables(conn)
    cleanup(conn)
    get = http_get or fetch
    now = now or datetime.now(timezone.utc)
    have = {r["date"]: dict(r) for r in conn.execute("SELECT date, status, fetched_at FROM regsho_files")}
    got = 0
    for d in candidates(now.astimezone(ET), days):
        k = d.isoformat()
        h = have.get(k)
        if h and (h["status"] == "ok" or now.timestamp() - (h["fetched_at"] or 0) < MISS_RETRY):
            continue
        try:
            code, text = get(URL.format(d=d.strftime("%Y%m%d")))
        except Exception as e:  # noqa: BLE001  — 2026-10-28: 네트워크 오류(연결 끊김·오프라인 테스트)가 그날 갱신 전체를 터뜨리지 않게. 이번 라운드는 여기서 멈추고 다음 주기에 다시
            log.warning("Reg SHO %s 받기 실패(%s) — 이번 라운드 중단", k, str(e)[:120])
            conn.execute("INSERT OR REPLACE INTO regsho_files (date, status, n, fetched_at) VALUES (?,?,?,?)", (k, "error", 0, now.timestamp()))
            conn.commit()
            break
        rows = parse(text) if code == 200 else {}
        if rows:
            conn.execute("DELETE FROM regsho_list WHERE date=?", (k,))
            conn.executemany("INSERT INTO regsho_list (date, symbol, name) VALUES (?,?,?)", [(k, s, nm) for s, nm in rows.items()])
            got += 1
        conn.execute("INSERT OR REPLACE INTO regsho_files (date, status, n, fetched_at) VALUES (?,?,?,?)", (k, "ok" if rows else "missing", len(rows), now.timestamp()))
        conn.commit()
    return got


def streaks(conn) -> dict[str, int]:
    """{종목: 최신 파일까지 연속으로 목록에 있던 거래일 수} — 받은 파일들 기준."""
    ensure_tables(conn)
    dates = [r["date"] for r in conn.execute("SELECT date FROM regsho_files WHERE status='ok' ORDER BY date DESC")]
    if not dates:
        return {}
    by = {}
    for r in conn.execute("SELECT date, symbol FROM regsho_list"):
        by.setdefault(r["symbol"], set()).add(r["date"])
    out = {}
    for s, ds in by.items():
        n = 0
        for d in dates:
            if d in ds:
                n += 1
            else:
                break
        if n:
            out[s] = n
    return out


def latest_date(conn) -> str | None:
    ensure_tables(conn)
    r = conn.execute("SELECT MAX(date) AS d FROM regsho_files WHERE status='ok'").fetchone()
    return r["d"] if r else None


def label(n: int | None) -> str:
    return "" if not n else f"📛 {n}일째"


def main() -> int:
    db.init_db()
    with closing(db.connect()) as conn:
        got = refresh(conn)
        d = latest_date(conn)
        st = streaks(conn)
    if not d:
        print("❌ Reg SHO 파일을 하나도 받지 못했습니다(인터넷·방화벽 확인).")
        return 2
    top = sorted(st.items(), key=lambda x: -x[1])[:10]
    print(f"✅ 최신 {d} · 새로 받은 파일 {got}개 · 목록 {sum(1 for v in st.values() if v):,}종목")
    print("오래 있는 종목:", ", ".join(f"{s}({n}일)" for s, n in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------- 날짜별 조회(Reg SHO 감시 화면)
HIGH_DAYS, RISK_DAYS = 13, 5  # 13결제일 연속이면 Reg SHO 203(b)(3) 강제 상환 대상 → 고위험, 5~12일 위험, 오늘 처음이면 신규


def dates(conn) -> list[str]:
    ensure_tables(conn)
    return [r["date"] for r in conn.execute("SELECT date FROM regsho_files WHERE status='ok' ORDER BY date DESC")]


def streaks_at(conn, day: str) -> dict[str, int]:
    """day 기준 연속 일수(받아 둔 파일 기준)."""
    ds = [d for d in dates(conn) if d <= day]
    by: dict[str, set] = {}
    for r in conn.execute("SELECT date, symbol FROM regsho_list WHERE date <= ?", (day,)):
        by.setdefault(r["symbol"], set()).add(r["date"])
    out = {}
    for s, have in by.items():
        if day not in have:
            continue
        n = 0
        for d in ds:
            if d in have:
                n += 1
            else:
                break
        out[s] = n
    return out


def names_at(conn, day: str) -> dict[str, str]:
    return {r["symbol"]: r["name"] for r in conn.execute("SELECT symbol, name FROM regsho_list WHERE date=?", (day,))}


def history(conn, symbol: str) -> list[str]:
    return [r["date"] for r in conn.execute("SELECT date FROM regsho_list WHERE symbol=? ORDER BY date DESC", (symbol.upper(),))]


def level(n: int) -> str:
    return "고위험" if n >= HIGH_DAYS else ("위험" if n >= RISK_DAYS else ("신규" if n == 1 else "주의"))


def summary(conn, day: str) -> dict:
    """{등록, 고위험, 위험, 신규} 와 전일 대비."""
    def count(d):
        st = streaks_at(conn, d)
        return {"등록": len(st), "고위험": sum(v >= HIGH_DAYS for v in st.values()), "위험": sum(RISK_DAYS <= v < HIGH_DAYS for v in st.values()),
                "신규": sum(v == 1 for v in st.values())}
    ds = dates(conn)
    cur = count(day)
    prev_days = [d for d in ds if d < day]
    prev = count(prev_days[0]) if prev_days else None
    return {"cur": cur, "delta": {k: cur[k] - prev[k] for k in cur} if prev else {k: None for k in cur}}
