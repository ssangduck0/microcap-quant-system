"""토스증권 공식 Open API 클라이언트 (읽기 전용).

시세·종목·랭킹·환율·장 캘린더만 호출합니다. 계좌/주문/조건주문 API는 일부러 구현하지 않았습니다.

운영상 중요한 점 (공식 문서 기준)
  - 토큰은 클라이언트당 1개만 유효: 새로 발급하면 이전 토큰이 즉시 무효화됩니다.
    -> 이 클라이언트는 '스캐너 프로세스 하나'에서만 쓰세요. 대시보드는 DB에 저장된 값을 읽습니다.
  - 허용 IP로 등록된 곳에서만 호출 가능(토스증권 WTS > 설정 > Open API > 허용 IP 관리). 아니면 403.
  - 그룹별 초당 요청 한도가 있어 호출 간격을 자동 조절하고, 429 는 Retry-After 만큼 기다려 재시도합니다.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import requests

log = logging.getLogger("toss")

ET = "America/New_York"
# 공식 문서의 초당 한도(AUTH 5, MARKET_DATA 15, MARKET_DATA_CHART 20, RANKING 5, STOCK 5, STOCK_ALL 1, MARKET_INFO 3)의 80%만 사용
MIN_INTERVAL = {"AUTH": 1 / 4, "MARKET_DATA": 1 / 12, "MARKET_DATA_CHART": 1 / 16, "RANKING": 1 / 4,
                "STOCK": 1 / 4, "STOCK_ALL": 1.25, "MARKET_INFO": 1 / 2.4}
TOKEN_RELATED = {"expired-token", "token-revoked", "invalid-token"}
BLOCK_SECONDS = 300  # 인증 실패(IP 미허용 등) 후 이 시간 동안은 재시도하지 않음 (실패 호출 폭주 방지)


class TossError(Exception):
    def __init__(self, status: int, code: str, message: str, request_id: str | None = None):
        self.status, self.code, self.message, self.request_id = status, code, message, request_id
        hint = " (허용 IP 미등록 가능성: WTS 설정 > Open API > 허용 IP 관리)" if status == 403 else ""
        super().__init__(f"[{status}] {code}: {message}{hint}" + (f" (requestId={request_id})" if request_id else ""))


class TossClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str = "https://openapi.tossinvest.com",
                 session: requests.Session | None = None, sleep=time.sleep, clock=time.time):
        self._id, self._secret = client_id, client_secret
        self.base = base_url.rstrip("/")
        self.s = session or requests.Session()
        self.sleep, self.clock = sleep, clock
        self._tok: str | None = None
        self._exp = 0.0
        self._blocked_until = 0.0
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()
        self._tok_lock = threading.RLock()

    def __repr__(self) -> str:  # 비밀값이 로그에 찍히지 않도록
        return f"<TossClient base={self.base}>"

    # ------------------------------------------------------------ 내부
    def _wait(self, group: str) -> None:
        with self._lock:
            now = self.clock()
            slot = max(now, self._next.get(group, 0.0))
            self._next[group] = slot + MIN_INTERVAL.get(group, 0.25)
        if slot > now:
            self.sleep(slot - now)

    @staticmethod
    def _error(r) -> TossError:
        try:
            j = r.json()
        except ValueError:
            j = {}
        err = j.get("error")
        if isinstance(err, dict):  # 일반 API: {"error": {"requestId","code","message"}}
            return TossError(r.status_code, err.get("code", "unknown"), err.get("message", ""), err.get("requestId"))
        # OAuth2: {"error": "invalid_client", "error_description": "..."}
        return TossError(r.status_code, str(err or "unknown"), j.get("error_description", r.text[:120]))

    def _token(self, force: bool = False) -> str:
        with self._tok_lock:
            if not force and self._tok and self._exp - self.clock() > 300:
                return self._tok
            if self.clock() < self._blocked_until:
                raise TossError(403, "auth-blocked", "직전 인증 실패로 잠시 호출을 건너뜁니다.")
            self._wait("AUTH")
            r = self.s.post(f"{self.base}/oauth2/token", timeout=15, data={
                "grant_type": "client_credentials", "client_id": self._id, "client_secret": self._secret})
            if r.status_code != 200:
                if r.status_code in (400, 401, 403):
                    self._blocked_until = self.clock() + BLOCK_SECONDS
                raise self._error(r)
            j = r.json()
            self._tok = j["access_token"]
            self._exp = self.clock() + int(j.get("expires_in", 86400))
            return self._tok

    def _get(self, group: str, path: str, params: dict | None = None):
        refreshed = False
        for attempt in range(4):
            self._wait(group)
            r = self.s.get(f"{self.base}{path}", params=params, timeout=15,
                           headers={"Authorization": f"Bearer {self._token()}"})
            if r.status_code == 200:
                return r.json().get("result")
            err = self._error(r)
            if r.status_code == 401 and err.code in TOKEN_RELATED and not refreshed:
                refreshed = True
                self._token(force=True)
                continue
            if r.status_code == 429 and attempt < 3:
                try:
                    wait = float(r.headers.get("Retry-After", 2 ** attempt))
                except ValueError:
                    wait = 2 ** attempt
                self.sleep(min(wait, 10))
                continue
            if r.status_code >= 500 and attempt < 2:
                self.sleep(1 + attempt)
                continue
            raise err
        raise TossError(429, "rate-limit-exceeded", "재시도 횟수를 초과했습니다.")

    # ------------------------------------------------------------ 시세
    def prices(self, symbols: list[str]) -> dict[str, dict]:
        """현재가 일괄 조회(1회 최대 200종목). 반환: {심볼: {"price": float, "timestamp": str}}"""
        out: dict[str, dict] = {}
        for i in range(0, len(symbols), 200):
            res = self._get("MARKET_DATA", "/api/v1/prices", {"symbols": ",".join(symbols[i:i + 200])}) or []
            for p in res:
                out[p["symbol"]] = {"price": float(p["lastPrice"]), "timestamp": p.get("timestamp")}
        return out

    def candles(self, symbol: str, interval: str = "1m", count: int = 200, before: str | None = None):
        """캔들 한 페이지. 최신순. 반환: (candles 리스트, nextBefore)"""
        params = {"symbol": symbol, "interval": interval, "count": count}
        if before:
            params["before"] = before
        res = self._get("MARKET_DATA_CHART", "/api/v1/candles", params) or {}
        return res.get("candles") or [], res.get("nextBefore")

    def orderbook(self, symbol: str) -> dict:
        """호가. 반환: {"timestamp", "asks": [(가격, 잔량)...] 낮은 가격순, "bids": [(가격, 잔량)...] 높은 가격순}. 제공되는 호가 단계 수는 종목·세션에 따라 다릅니다."""
        res = self._get("MARKET_DATA", "/api/v1/orderbook", {"symbol": symbol}) or {}
        levels = lambda lv: [(float(x["price"]), float(x["volume"])) for x in (lv or [])]  # noqa: E731
        return {"timestamp": res.get("timestamp"), "asks": levels(res.get("asks")), "bids": levels(res.get("bids"))}

    def daily_candles(self, symbol: str, count: int = 25) -> list[dict]:
        """일봉(최신순). 가장 최근 봉이 오늘(진행 중) 봉인지는 호출하는 쪽에서 가격으로 확인한다."""
        return self.candles(symbol, "1d", count)[0]

    def trades(self, symbol: str, count: int = 50) -> list[dict]:
        return self._get("MARKET_DATA", "/api/v1/trades", {"symbol": symbol, "count": count}) or []

    def intraday_frame(self, symbol: str, max_pages: int = 6) -> pd.DataFrame | None:
        """오늘(미국 동부시간 기준) 1분봉 전체를 yfinance 와 같은 컬럼(Open/High/Low/Close/Volume)으로 반환."""
        rows, before, cutoff = [], None, None
        for _ in range(max_pages):
            candles, nxt = self.candles(symbol, "1m", 200, before)
            if not candles:
                break
            rows.extend(candles)
            if cutoff is None:
                latest = pd.to_datetime(candles[0]["timestamp"], utc=True).tz_convert(ET)
                cutoff = pd.Timestamp(latest.year, latest.month, latest.day, 4, 0, tz=ET)  # 프리마켓 시작
            oldest = pd.to_datetime(candles[-1]["timestamp"], utc=True).tz_convert(ET)
            if oldest <= cutoff or not nxt:
                break
            before = nxt
        if not rows:
            return None
        df = pd.DataFrame({
            "Open": [float(c["openPrice"]) for c in rows], "High": [float(c["highPrice"]) for c in rows],
            "Low": [float(c["lowPrice"]) for c in rows], "Close": [float(c["closePrice"]) for c in rows],
            "Volume": [float(c["volume"]) for c in rows]},
            index=pd.DatetimeIndex([pd.to_datetime(c["timestamp"], utc=True).tz_convert(ET) for c in rows]))
        df = df[~df.index.duplicated(keep="first")].sort_index()  # before 가 inclusive 라 페이지 경계가 중복됨
        today = df[df.index >= cutoff]
        return today if not today.empty else df  # 새벽 데이마켓 봉만 있으면 전체를 그대로 사용

    # ------------------------------------------------------------ 종목/랭킹/시장
    def rankings(self, rank_type: str, country: str = "US", duration: str = "1d", count: int = 100) -> list[dict]:
        res = self._get("RANKING", "/api/v1/rankings",
                        {"type": rank_type, "marketCountry": country, "duration": duration, "count": count}) or {}
        return res.get("rankings") or []

    def stocks_all(self, market: str, status: str = "ACTIVE") -> list[dict]:
        return self._get("STOCK_ALL", "/api/v1/stocks/all", {"market": market, "status": status}) or []

    def stocks(self, symbols: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(symbols), 200):
            out += self._get("STOCK", "/api/v1/stocks", {"symbols": ",".join(symbols[i:i + 200])}) or []
        return out

    def exchange_rate(self, base: str = "USD", quote: str = "KRW") -> float:
        res = self._get("MARKET_INFO", "/api/v1/exchange-rate", {"baseCurrency": base, "quoteCurrency": quote})
        return float(res["rate"])

    def us_calendar(self) -> dict:
        return self._get("MARKET_INFO", "/api/v1/market-calendar/US") or {}


# ---------------------------------------------------------------- 헬퍼
def us_session(cal: dict, now: datetime | None = None) -> str:
    """장 캘린더에서 지금이 어느 세션인지 계산 (시간은 KST 오프셋 포함 ISO 문자열)."""
    now = now or datetime.now(timezone.utc)
    names = (("dayMarket", "데이마켓"), ("preMarket", "프리마켓"), ("regularMarket", "정규장"), ("afterMarket", "애프터마켓"))
    for key in ("previousBusinessDay", "today", "nextBusinessDay"):
        day = cal.get(key) or {}
        for k, ko in names:
            s = day.get(k)
            if s and s.get("startTime") and s.get("endTime"):
                if datetime.fromisoformat(s["startTime"]) <= now < datetime.fromisoformat(s["endTime"]):
                    return ko
    return "장 마감/휴장"


def regular_end(cal: dict, now: datetime | None = None) -> datetime | None:
    """지금 진행 중이거나 오늘 예정인 정규장의 종료 시각(조기 폐장 반영). 못 찾으면 None."""
    now = now or datetime.now(timezone.utc)
    upcoming = []
    for key in ("previousBusinessDay", "today", "nextBusinessDay"):
        s = (cal.get(key) or {}).get("regularMarket") or {}
        if s.get("startTime") and s.get("endTime"):
            st_, en = datetime.fromisoformat(s["startTime"]), datetime.fromisoformat(s["endTime"])
            if st_ <= now < en:
                return en
            if now < st_:
                upcoming.append(en)
    return min(upcoming) if upcoming else None


def fetch_intraday_many(tc: TossClient, symbols: list[str], workers: int = 4, deadline_sec: float = 150) -> dict[str, pd.DataFrame]:
    """여러 종목의 오늘 1분봉을 병렬로 받는다. 한도 시간을 넘기면 남은 종목은 건너뛴다(호출 쪽에서 대체 수단 사용)."""
    start = time.time()
    out: dict[str, pd.DataFrame] = {}

    def one(sym: str):
        if time.time() - start > deadline_sec:
            return sym, None
        try:
            return sym, tc.intraday_frame(sym)
        except Exception as e:  # noqa: BLE001
            log.warning("%s 토스 1분봉 실패: %s", sym, e)
            return sym, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sym, df in ex.map(one, symbols):
            if df is not None and not df.empty:
                out[sym] = df
    return out
