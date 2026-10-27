"""토스증권 바로가기 — 티커를 누르면 토스증권 웹(WTS)의 그 종목 주문 화면으로.

토스증권 미국 주식 주소는 티커가 아니라 토스 자체 상품 코드를 쓴다: https://tossinvest.com/stocks/{코드}/order (예: US20220803004, NAS0240124005)
스캐너가 토스 Open API 종목 정보(/api/v1/stocks)에서 코드를 찾아 저장하고(필드 이름이 바뀌어도 값 모양으로 찾음),
못 찾은 종목은 사용자가 토스증권 웹 주소를 한 번 붙여넣으면 저장한다. 코드가 없으면 티커로 주소를 만든다(열리지 않을 수 있음).
점검: python tosslink.py RUBI XXII   (토스 종목 정보에서 코드를 찾는지 확인)
"""
from __future__ import annotations

import re
import sys
from contextlib import closing

import db

CODE_RE = re.compile(r"^(?:US\d{11}|[A-Z]{3}\d{10})$")  # 13자리: US+11자리(US20220803004) 또는 영문 3+10자리(NAS0240124005). ISIN(12자리)과 구분
URL_RE = re.compile(r"tossinvest\.com/stocks/(US\d{11}|[A-Z]{3}\d{10})", re.I)
KEYS = ("productCode", "stockCode", "code", "tossCode", "shortCode", "itemCode", "securityCode")
DDL = "CREATE TABLE IF NOT EXISTS toss_codes (ticker TEXT PRIMARY KEY, code TEXT, source TEXT, at TEXT)"


def _conn():
    c = db.connect()
    c.execute(DDL)
    c.commit()
    return c


def extract_code(info: dict | None) -> str | None:
    if not info:
        return None
    for k in KEYS:
        v = info.get(k)
        if isinstance(v, str) and CODE_RE.match(v.strip().upper()):
            return v.strip().upper()
    for v in info.values():  # 필드 이름이 달라도 값 모양(예: US20220803004)으로 찾는다
        if isinstance(v, str) and CODE_RE.match(v.strip().upper()):
            return v.strip().upper()
    return None


def from_url(text: str) -> str | None:
    m = URL_RE.search(text or "")
    return m.group(1).upper() if m else None


def save(ticker: str, code: str, source: str = "토스 API") -> None:
    with closing(_conn()) as c:
        c.execute("INSERT OR REPLACE INTO toss_codes (ticker, code, source, at) VALUES (?,?,?,?)", (ticker.upper(), code.upper(), source, db.utcnow_iso()))
        c.commit()


def codes() -> dict[str, str]:
    with closing(_conn()) as c:
        return {r["ticker"]: r["code"] for r in c.execute("SELECT ticker, code FROM toss_codes")}


def url(ticker: str, cmap: dict | None = None) -> str:
    t = str(ticker or "").upper()
    code = (cmap if cmap is not None else codes()).get(t)
    return f"https://tossinvest.com/stocks/{code or t}/order"


def refresh(tc, tickers: list[str]) -> int:
    """코드가 없는 종목만 토스 종목 정보에서 찾아 저장(200개씩 한 번). 저장한 개수."""
    have = codes()
    miss = [t.upper() for t in dict.fromkeys(tickers) if t and t.upper() not in have]
    n = 0
    for i in range(0, len(miss), 200):
        for info in tc.stocks(miss[i:i + 200]) or []:
            sym, code = str(info.get("symbol") or "").upper(), extract_code(info)
            if sym and code:
                save(sym, code)
                n += 1
    return n


def main() -> int:
    import config
    import toss
    db.init_db()
    syms = [s.upper() for s in sys.argv[1:]] or ["AAPL"]
    tc = toss.TossClient(config.TOSS_CLIENT_ID, config.TOSS_CLIENT_SECRET, config.TOSS_BASE_URL)
    for info in tc.stocks(syms):
        code = extract_code(info)
        print(f"{info.get('symbol')}: 코드 {code or '못 찾음'} · 종목 정보 필드: {', '.join(sorted(info))}")
        if code:
            save(info.get("symbol"), code)
            print("   →", url(info.get("symbol")))
    print("\n못 찾은 종목은 대시보드 종목 상세의 '토스 주소 붙여넣기'에 토스증권 웹 주소를 한 번 넣으면 저장됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
