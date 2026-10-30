"""공매도 데이터 — 무료 원 출처 (키 불필요). Fintel 은 .env 에 키가 있을 때만 보조로 사용.

FINRA 일별 공매도 거래량 (공식, 무료)
  https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt   (Consolidated NMS, 장 마감 후 동부시간 18시까지 게시)
  형식: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market (첫 줄 머리글, 마지막 줄 건수)
  ※ 장외(TRF·ADF) 보고분만 집계 — 거래소 체결은 빠져 있어 비율이 실제보다 높게 보일 수 있음(Fintel 의 '공매도 거래량'도 같은 데이터)
IBKR 대차(공개 FTP, 무료·계좌 불필요)
  ftp2.interactivebrokers.com, 사용자 shortstock, 비밀번호 없음, 파일 usa.txt
  형식: #SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|... (AVAILABLE 은 '>10000000' 처럼 올 수 있음)
  ※ IBKR 이 빌려줄 수 있는 물량 기준 — 시장 전체 수치는 아님. 장중 여러 번 갱신 → 15분마다 다시 받음
요약 키는 fintel.summary 와 같다: sv_date, sv_short, sv_total, sv_ratio, sv_avg5_ratio, borrow_fee, borrow_avail, borrow_date
추가: borrow_rebate, borrow_avail_open(오늘 처음 본 대차 가능 수량), borrow_avail_chg_pct(그 대비 변화 %), short_src(출처 문구)
"""
from __future__ import annotations

import json

import ftplib
import io
import logging
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

import db

log = logging.getLogger("shortdata")
ET = ZoneInfo("America/New_York")
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d}.txt"
IBKR_HOST, IBKR_USER, IBKR_FILE = "ftp2.interactivebrokers.com", "shortstock", "usa.txt"
UA = "Mozilla/5.0 (quant-system short data)"
IBKR_TTL = 15 * 60          # 대차 파일 재수신 간격(초)
FINRA_MISS_RETRY = 3600     # 아직 안 올라온 날짜 파일 재시도 간격(초)
FINRA_KEEP_DAYS = 5         # 5일 평균용(한 번에 받는 파일 수)
HISTORY_DAYS = 60           # 추이 차트용 보관 기간(FINRA 일별 공매도 · IBKR 일별 대차)
DDL = [
    "CREATE TABLE IF NOT EXISTS finra_shvol (date TEXT NOT NULL, symbol TEXT NOT NULL, short REAL, exempt REAL, total REAL, PRIMARY KEY (date, symbol))",
    "CREATE TABLE IF NOT EXISTS finra_files (date TEXT PRIMARY KEY, status TEXT, n INTEGER, fetched_at REAL)",
    "CREATE TABLE IF NOT EXISTS ibkr_borrow (symbol TEXT PRIMARY KEY, fee REAL, rebate REAL, available REAL, avail_capped INTEGER, as_of TEXT)",
    "CREATE TABLE IF NOT EXISTS ibkr_borrow_day (date TEXT NOT NULL, symbol TEXT NOT NULL, open_avail REAL, min_avail REAL, max_fee REAL, PRIMARY KEY (date, symbol))",
    "CREATE TABLE IF NOT EXISTS shortdata_meta (k TEXT PRIMARY KEY, v TEXT, t REAL)",
]


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


# ---------------------------------------------------------------- 파싱 (순수 함수)
def _num(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip().replace(",", "")
    if not v or v.upper() in ("NA", "N/A", "NAN", "-"):
        return None
    try:
        return float(v.lstrip(">"))
    except ValueError:
        return None


def parse_finra(text: str) -> dict[str, tuple[float, float, float]]:
    """FINRA 파일 → {종목: (공매도, 공매도 예외, 전체)}. 머리글·건수 줄·형식이 다른 줄은 건너뜀."""
    out = {}
    for line in text.splitlines():
        p = line.strip().split("|")
        if len(p) < 5 or not (p[0].isdigit() and len(p[0]) == 8):
            continue
        s, e, t = _num(p[2]), _num(p[3]), _num(p[4])
        if p[1] and s is not None and t is not None:
            out[p[1].strip().upper()] = (s, e or 0.0, t)
    return out


def parse_ibkr(text: str) -> tuple[dict[str, dict], str | None]:
    """IBKR usa.txt → ({종목: {fee, rebate, available, capped}}, 파일 시각). 머리글(#SYM)로 열 위치를 찾는다."""
    cols, as_of, out = None, None, {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#BOF"):
            p = line.split("|")
            as_of = " ".join(x for x in p[1:3] if x) or None
            continue
        if line.startswith("#SYM"):
            cols = [c.strip().lstrip("#").upper() for c in line.split("|")]
            continue
        if line.startswith("#") or cols is None:
            continue
        p = line.split("|")
        row = dict(zip(cols, p))
        sym = (row.get("SYM") or "").strip().upper()
        if not sym:
            continue
        cur = (row.get("CUR") or "").strip().upper()
        if sym in out and out[sym].get("cur") == "USD" and cur != "USD":
            continue  # 같은 티커가 USD·EUR 로 둘 다 있으면 미국(USD) 줄을 우선
        av_raw = (row.get("AVAILABLE") or "").strip()
        out[sym] = {"fee": _num(row.get("FEERATE")), "rebate": _num(row.get("REBATERATE")), "available": _num(av_raw), "capped": av_raw.startswith(">"), "cur": cur}
    if cols is None:
        raise ValueError("IBKR 파일에 #SYM 머리글이 없습니다(형식 변경?)")
    return out, as_of


def finra_candidates(now_et: datetime, n_days: int = 10) -> list[date]:
    """최근 거래일 후보(주말 제외), 최신순. 오늘 파일은 동부시간 18:30 이후에만 후보."""
    d = now_et.date() if now_et.hour * 60 + now_et.minute >= 18 * 60 + 30 else now_et.date() - timedelta(days=1)
    out = []
    while len(out) < n_days:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


# ---------------------------------------------------------------- 수집 (네트워크; 테스트에서는 바꿔 끼움)
def _http_get_text(url: str, session=None, timeout: float = 30.0) -> tuple[int, str]:
    r = (session or requests).get(url, headers={"User-Agent": UA}, timeout=timeout)
    return r.status_code, (r.text if r.status_code == 200 else "")


def _ftp_get_text(timeout: float = 60.0) -> str:
    buf = io.BytesIO()
    with ftplib.FTP(IBKR_HOST, timeout=timeout) as f:
        f.login(IBKR_USER, "")
        f.retrbinary(f"RETR {IBKR_FILE}", buf.write)
    return buf.getvalue().decode("utf-8", errors="replace")


class ShortClient:
    """무료 공매도 데이터(FINRA + IBKR) + 선택적 Fintel. summary() 는 fintel.FintelClient.summary 와 같은 키를 돌려준다."""

    def __init__(self, fintel_client=None, http_get=None, ftp_get=None, now=None):
        self.fintel = fintel_client
        self.http_get = http_get or _http_get_text
        self.ftp_get = ftp_get or _ftp_get_text
        self._now = now  # 테스트용: () -> datetime(UTC)
        self.errors: dict[str, str] = {}

    @classmethod
    def from_config(cls):
        import config
        import fintel
        return cls(fintel.FintelClient(config.FINTEL_API_KEY) if config.FINTEL_API_KEY else None)

    def now(self) -> datetime:
        return self._now() if self._now else datetime.now(timezone.utc)

    @property
    def label(self) -> str:
        return "FINRA·IBKR" + (" + Fintel" if self.fintel else "")

    # ---- FINRA
    def refresh_finra(self, conn) -> None:
        ensure_tables(conn)
        now_s = self.now().timestamp()
        have = {r["date"]: dict(r) for r in conn.execute("SELECT date, status, fetched_at FROM finra_files")}
        got = 0
        for d in finra_candidates(self.now().astimezone(ET)):
            key = d.isoformat()
            h = have.get(key)
            if h and h["status"] == "ok":
                got += 1
            elif not (h and h["status"] == "missing" and now_s - (h["fetched_at"] or 0) < FINRA_MISS_RETRY):
                try:
                    code, text = self.http_get(FINRA_URL.format(d=d.strftime("%Y%m%d")))
                except Exception as e:  # noqa: BLE001
                    self.errors["finra"] = f"FINRA 파일 수신 실패: {type(e).__name__}"
                    break
                rows = parse_finra(text) if code == 200 else {}
                if rows:
                    conn.execute("DELETE FROM finra_shvol WHERE date=?", (key,))
                    conn.executemany("INSERT INTO finra_shvol (date,symbol,short,exempt,total) VALUES (?,?,?,?,?)",
                                     [(key, s, *v) for s, v in rows.items()])
                    conn.execute("INSERT OR REPLACE INTO finra_files (date,status,n,fetched_at) VALUES (?,?,?,?)", (key, "ok", len(rows), now_s))
                    got += 1
                    self.errors.pop("finra", None)
                else:  # 휴장일·아직 미게시(403/404) — 1시간 뒤 재시도
                    conn.execute("INSERT OR REPLACE INTO finra_files (date,status,n,fetched_at) VALUES (?,?,?,?)", (key, "missing", 0, now_s))
                conn.commit()
            if got >= FINRA_KEEP_DAYS:
                break
        oldest = (self.now().astimezone(ET).date() - timedelta(days=20)).isoformat()
        conn.execute("DELETE FROM finra_shvol WHERE date < ?", ((date.today() - timedelta(days=HISTORY_DAYS + 10)).isoformat(),))
        conn.execute("DELETE FROM finra_files WHERE date < ?", (oldest,))
        conn.commit()

    @staticmethod
    def finra_for(conn, symbol: str) -> dict | None:
        rows = conn.execute("SELECT date, short, total FROM finra_shvol WHERE symbol=? AND total > 0 ORDER BY date DESC LIMIT ?",
                            (symbol, FINRA_KEEP_DAYS)).fetchall()
        if not rows:
            return None
        d, s, t = rows[0]["date"], rows[0]["short"], rows[0]["total"]
        return {"sv_date": d, "sv_short": s, "sv_total": t, "sv_ratio": s / t * 100,
                "sv_avg5_ratio": sum(r["short"] for r in rows) / sum(r["total"] for r in rows) * 100}

    # ---- IBKR
    def refresh_ibkr(self, conn) -> None:
        ensure_tables(conn)
        now = self.now()
        m = conn.execute("SELECT t FROM shortdata_meta WHERE k='ibkr_fetched'").fetchone()
        if m and now.timestamp() - (m["t"] or 0) < IBKR_TTL:
            return
        try:
            data, as_of = parse_ibkr(self.ftp_get())
        except Exception as e:  # noqa: BLE001
            self.errors["ibkr"] = f"IBKR 대차 파일 수신 실패: {type(e).__name__} (회사·공유기 방화벽이 FTP 를 막으면 실패할 수 있음)"
            conn.execute("INSERT OR REPLACE INTO shortdata_meta (k,v,t) VALUES (?,?,?)", ("ibkr_fetched", "fail", now.timestamp() - IBKR_TTL + 300))  # 5분 뒤 재시도
            conn.commit()
            return
        day = now.astimezone(ET).date().isoformat()
        stamp = as_of or now.isoformat(timespec="seconds")
        conn.executemany("INSERT OR REPLACE INTO ibkr_borrow (symbol,fee,rebate,available,avail_capped,as_of) VALUES (?,?,?,?,?,?)",
                         [(s, v["fee"], v["rebate"], v["available"], int(v["capped"]), stamp) for s, v in data.items()])
        conn.executemany("""INSERT INTO ibkr_borrow_day (date,symbol,open_avail,min_avail,max_fee) VALUES (?,?,?,?,?)
                            ON CONFLICT(date, symbol) DO UPDATE SET
                              min_avail = CASE WHEN excluded.min_avail IS NOT NULL AND (ibkr_borrow_day.min_avail IS NULL OR excluded.min_avail < ibkr_borrow_day.min_avail)
                                               THEN excluded.min_avail ELSE ibkr_borrow_day.min_avail END,
                              max_fee = CASE WHEN excluded.max_fee IS NOT NULL AND (ibkr_borrow_day.max_fee IS NULL OR excluded.max_fee > ibkr_borrow_day.max_fee)
                                             THEN excluded.max_fee ELSE ibkr_borrow_day.max_fee END""",
                         [(day, s, v["available"], v["available"], v["fee"]) for s, v in data.items()])
        conn.execute("DELETE FROM ibkr_borrow_day WHERE date < ?", ((now.astimezone(ET).date() - timedelta(days=HISTORY_DAYS)).isoformat(),))
        try:  # 감시 종목(스퀴즈 상위·Reg SHO·워치리스트·저금통)은 15분마다 가용주식·수수료를 기록(장중 추이)
            tracked = set(json.loads((conn.execute("SELECT v FROM shortdata_meta WHERE k='tracked'").fetchone() or ["[]"])[0] or "[]"))
            conn.execute("CREATE TABLE IF NOT EXISTS ibkr_avail_hist (symbol TEXT NOT NULL, ts TEXT NOT NULL, avail REAL, fee REAL, PRIMARY KEY (symbol, ts))")
            conn.executemany("INSERT OR IGNORE INTO ibkr_avail_hist VALUES (?,?,?,?)", [(sy, stamp, data[sy]["available"], data[sy]["fee"]) for sy in tracked if sy in data])
            conn.execute("DELETE FROM ibkr_avail_hist WHERE ts < ?", ((now - timedelta(days=14)).isoformat(),))
        except Exception:  # noqa: BLE001
            pass
        conn.execute("INSERT OR REPLACE INTO shortdata_meta (k,v,t) VALUES (?,?,?)", ("ibkr_fetched", stamp, now.timestamp()))
        conn.commit()
        self.errors.pop("ibkr", None)

    def ibkr_for(self, conn, symbol: str) -> dict | None:
        r = conn.execute("SELECT fee, rebate, available, avail_capped, as_of FROM ibkr_borrow WHERE symbol=?", (symbol,)).fetchone()
        if not r:
            return None
        out = {"borrow_fee": r["fee"], "borrow_rebate": r["rebate"], "borrow_avail": r["available"], "borrow_avail_capped": bool(r["avail_capped"]),
               "borrow_date": r["as_of"]}
        m = conn.execute("SELECT v FROM shortdata_meta WHERE k='ibkr_fetched'").fetchone()
        latest = m["v"] if m and m["v"] and m["v"] != "fail" else None
        if latest and r["as_of"] != latest:
            # 최신 파일에 이 종목이 없음 — IBKR 은 빌려줄 물량이 없어진 종목을 목록에서 빼는 것으로 보임. 옛 값을 지금 값처럼 쓰지 않는다
            out["borrow_stale"] = True
            out["borrow_note"] = f"최신 IBKR 파일({latest})에 없음 — 대여 가능 물량이 바닥났을 가능성(표시 값은 {r['as_of']} 기준)"
            return out
        d = conn.execute("SELECT open_avail, min_avail, max_fee FROM ibkr_borrow_day WHERE date=? AND symbol=?",
                         (self.now().astimezone(ET).date().isoformat(), symbol)).fetchone()
        if d and d["open_avail"] and r["available"] is not None:
            out["borrow_avail_open"] = d["open_avail"]
            out["borrow_avail_chg_pct"] = (r["available"] / d["open_avail"] - 1) * 100
            out["borrow_fee_max_today"] = d["max_fee"]
        return out

    # ---- 요약
    def refresh(self, conn) -> None:
        self.refresh_finra(conn)
        self.refresh_ibkr(conn)

    def summary(self, symbol: str, include_fintel: bool = True) -> dict:
        symbol = symbol.upper()
        out: dict = {"errors": []}
        with closing(db.connect()) as conn:
            ensure_tables(conn)
            try:
                self.refresh(conn)
            except Exception as e:  # noqa: BLE001
                self.errors["refresh"] = f"공매도 파일 갱신 실패: {type(e).__name__}"
            fv = self.finra_for(conn, symbol)
            if fv:
                out.update(fv)
            iv = self.ibkr_for(conn, symbol)
            if iv:
                out.update(iv)
        out["errors"] = list(self.errors.values())
        out["short_src"] = "FINRA(공매도 거래량)·IBKR(대차)"
        if include_fintel and self.fintel is not None:
            try:
                f = self.fintel.summary(symbol)
                for k, v in f.items():  # 무료 출처 값이 우선. Fintel 은 공매도 잔고(si_*) 등 빈 항목만 채움
                    if k == "errors":
                        out["errors"] += [f"Fintel: {x}" for x in v]
                    elif out.get(k) is None:
                        out[k] = v
                out["short_src"] += " + Fintel"
            except Exception as e:  # noqa: BLE001
                out["errors"].append(f"Fintel 조회 실패: {type(e).__name__}")
        return out
