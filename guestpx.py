"""👥 방문객용 가격 — 토스 데이터 정책 A안(2026-10-30, `docs/toss_data_policy_audit_2026-10.md` 7절).

스캐너는 토스 1분봉이 있으면 그 마지막 값을 `daily_snapshots.price`(당일 현재가·오늘 등락)로 저장한다. 토스 FAQ 가 "본인 매매 목적 · 제3자 배포 금지"라서
방문객 화면에서는 그 당일 숫자 대신 **전일 종가(야후 일봉 `daily_prices` 의 마지막 확정 봉)** 를 보여 준다. 확정 봉 = 미국 16:20 ET 전이면 오늘 봉 제외
(`cases.drop_incomplete_last_bar` 와 같은 규칙). 주인 화면·스캐너·판정 기준은 이 모듈을 쓰지 않는다.
"""
from __future__ import annotations

import time
from contextlib import closing
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import db

LABEL = "전일 종가"
NOTE = "👥 방문객 화면의 가격·등락은 전일 종가(야후 일봉 확정값) 기준이에요 — 토스증권 Open API 자료(당일 현재가·1분봉)는 데이터 이용 정책에 따라 주인 화면에서만 봅니다."
HIDE_COLS = ["거래량 배수", "52주 저점 대비(%)", "예상 다음날 고가(원)", "5일 내 기대 최고(원)", "진입참고($)", "손절참고($)", "목표참고($)", "매수체결 비중(%)"]   # 당일 값(토스 1분봉)으로 계산한 열
TTL = 120
_CACHE: dict = {}


def _skip_day(now: datetime | None = None) -> str | None:
    """미국 정규장이 끝나기 전(16:20 ET 전)이면 '오늘(ET)' 날짜 — 그 날짜 봉은 진행 중이라 뺀다."""
    now = now or datetime.now(ZoneInfo("America/New_York"))
    return now.strftime("%Y-%m-%d") if (now.hour, now.minute) < (16, 20) else None


def prev_close(tickers, now: datetime | None = None, conn=None) -> dict[str, dict]:
    """{티커: {"close": 마지막 확정 봉 종가, "chg": 그 전 봉 대비 %(없으면 None), "date": 봉 날짜}} — 자료 없는 종목은 빠짐. now 는 테스트용(ET)."""
    tk = sorted({str(t).upper() for t in tickers if t})
    if not tk:
        return {}
    skip = _skip_day(now)
    key = (tuple(tk), skip)
    hit = _CACHE.get(key)
    if now is None and hit and time.time() - hit[0] < TTL:
        return dict(hit[1])
    since = (date.today() - timedelta(days=21)).isoformat()
    rows: dict[str, list[tuple[str, float]]] = {}

    def run(c) -> None:
        q = ",".join("?" * len(tk))
        for t, d, cl in c.execute(f"SELECT ticker, date, close FROM daily_prices WHERE ticker IN ({q}) AND date >= ? AND close IS NOT NULL ORDER BY ticker, date", [*tk, since]):
            if skip and d >= skip:
                continue
            rows.setdefault(t, []).append((d, float(cl)))

    if conn is not None:
        run(conn)
    else:
        with closing(db.connect()) as c:
            run(c)
    out = {}
    for t, lst in rows.items():
        d, c0 = lst[-1]
        prev = lst[-2][1] if len(lst) >= 2 and lst[-2][1] > 0 else None
        out[t] = {"close": c0, "chg": None if prev is None else (c0 / prev - 1) * 100, "date": d}
    if now is None:
        _CACHE[key] = (time.time(), dict(out))
    return out


def one(ticker: str, now: datetime | None = None, conn=None) -> dict | None:
    return prev_close([ticker], now, conn).get(str(ticker).upper())


def clear() -> None:
    _CACHE.clear()
