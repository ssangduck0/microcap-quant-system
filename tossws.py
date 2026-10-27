"""토스 실시간 웹소켓(체결·호가) 수집기 — 토스 호가창과 같은 방식의 '체결강도'를 직접 계산한다.

토스 체결 프레임에는 매수/매도 구분이 없다(공식 명세). 그래서 체결가를 '그 순간의 호가'와 비교해 나눈다:
  체결가 ≥ 최우선 매도호가 → 매수 체결 / 체결가 ≤ 최우선 매수호가 → 매도 체결 / 호가 사이 → 직전 체결가 대비 방향(틱 규칙)
체결강도(%) = 매수 체결량 / 매도 체결량 × 100  (100% = 균형, 토스 화면의 체결강도와 같은 정의)
  - 시세는 LOSSY(유실 가능)이고 구독을 시작한 시점부터만 집계되므로 토스 화면의 '당일 누적' 값과 정확히 같지는 않은 추정치다.
1분 단위 집계(매수/매도/미분류 체결량, 매도 호가 깊이)를 close_flow 테이블에 기록하고, closewatch 가 읽어서 판정한다.
연결: wss://openapi-ws.tossinvest.com/ws/v1 (Authorization: Bearer), 선언형 full-replace 구독, 연결당 구독 100건(체결+호가 = 종목당 2건 → 최대 50종목),
      PING 60초 간격, 끊기면 지수 백오프로 재연결(재연결 전에 이전 연결을 먼저 닫음).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import closewatch
import db

log = logging.getLogger("tossws")
WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"
MAX_SYMBOLS = 50  # 연결당 구독 100건 / (체결 + 호가)
ET = ZoneInfo("America/New_York")


def classify_trade(price: float, quote: dict | None, prev_quote: dict | None, last_price: float | None, last_dir: int) -> tuple[str, int]:
    """체결 한 건을 매수/매도/미분류로 나눈다. 반환: (side, 방향 +1/-1/0). 최신 호가 → 직전 호가 → 틱 규칙 순."""
    for q in (quote, prev_quote):  # 체결 직후 호가가 갱신되며 최우선 호가가 소진되는 경우를 위해 직전 호가도 본다
        if not q:
            continue
        if q.get("ask") is not None and price >= q["ask"]:
            return "buy", 1
        if q.get("bid") is not None and price <= q["bid"]:
            return "sell", -1
    if last_price is not None:
        if price > last_price:
            return "buy", 1
        if price < last_price:
            return "sell", -1
        if last_dir:
            return ("buy" if last_dir > 0 else "sell"), last_dir
    return "mid", 0


def _parse_ts(s: str | None) -> datetime:
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc) if s else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


class FlowCollector:
    def __init__(self, token_fn, url: str = WS_URL, flush_s: float = 20.0, ping_s: float = 60.0, backoff_start: float = 1.0, backoff_max: float = 30.0):
        self.token_fn, self.url, self.flush_s, self.ping_s, self.backoff_start, self.backoff_max = token_fn, url, flush_s, ping_s, backoff_start, backoff_max
        self._symbols: list[str] = []
        self._dirty = False
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}
        self._buckets: dict[tuple[str, str], dict] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = False
        self.stats = {"frames": 0, "trades": 0, "books": 0, "reconnects": 0, "rejected": [], "errors": []}

    # ---- 외부 API (스캐너 스레드에서 호출)
    def set_symbols(self, symbols: list[str]) -> None:
        picked = list(dict.fromkeys(s.upper() for s in symbols))[:MAX_SYMBOLS]  # 우선순위(앞쪽) 순서대로 자른 뒤
        new = sorted(picked)                                                      # 같은 구성이면 재선언하지 않도록 정렬해 비교
        with self._lock:
            if new != self._symbols:
                self._symbols, self._dirty = new, True

    def start(self) -> bool:
        try:
            import websockets  # noqa: F401
        except ImportError:
            log.warning("websockets 패키지가 없어 토스 실시간 체결강도를 쓰지 않습니다 (pip install websockets). 분봉 기반 추정으로 대체됩니다.")
            return False
        closewatch.ensure_tables()
        self._stop.clear()
        self._thread = threading.Thread(target=lambda: asyncio.run(self._main()), name="tossws", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ---- 연결 루프
    async def _connect(self):
        try:
            from websockets.asyncio.client import connect
        except ImportError:  # websockets < 13
            from websockets import connect
        headers = {"Authorization": f"Bearer {self.token_fn()}"}
        try:
            return await connect(self.url, additional_headers=headers, open_timeout=15, ping_interval=None, max_size=2 ** 22)
        except TypeError:
            return await connect(self.url, extra_headers=headers, open_timeout=15, ping_interval=None, max_size=2 ** 22)

    async def _main(self) -> None:
        backoff = self.backoff_start
        while not self._stop.is_set():
            ws = None
            try:
                ws = await self._connect()
                self.connected, backoff = True, self.backoff_start
                with self._lock:
                    self._dirty = True  # 재연결 후에는 구독을 다시 선언
                await self._session(ws)
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] = (self.stats["errors"] + [f"{type(e).__name__}: {e}"])[-5:]
                log.warning("토스 웹소켓 끊김/실패: %s", e)
            finally:
                self.connected = False
                if ws is not None:
                    try:
                        await ws.close()  # 다시 연결하기 전에 이전 연결을 먼저 닫는다(동시 연결 한도 때문)
                    except Exception:  # noqa: BLE001
                        pass
                self._flush()
            if self._stop.is_set():
                break
            self.stats["reconnects"] += 1
            await asyncio.sleep(backoff + random.random() * 0.5)
            backoff = min(backoff * 2, self.backoff_max)

    async def _session(self, ws) -> None:
        last_ping = last_flush = time.monotonic()
        last_decl, n_decl = 0.0, 0
        while not self._stop.is_set():
            with self._lock:
                dirty, syms = self._dirty, list(self._symbols)
            if dirty and time.monotonic() - last_decl >= 0.3:  # 선언은 초당 5회까지
                n_decl += 1
                decl = ([{"id": f"d{n_decl}"}, {"type": "trade:us", "codes": syms}, {"type": "orderbook:us", "codes": syms}] if syms else [])
                await ws.send(json.dumps(decl))
                with self._lock:
                    if self._symbols == syms:
                        self._dirty = False
                last_decl = time.monotonic()
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                self._on_frame(raw)
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            if now - last_ping >= self.ping_s:  # 수신이 아니라 '송신'이 180초 타이머를 리셋한다
                await ws.send("PING")
                last_ping = now
            if now - last_flush >= self.flush_s:
                self._flush()
                last_flush = now

    # ---- 프레임 처리
    def _on_frame(self, raw) -> None:
        self.stats["frames"] += 1
        try:
            f = json.loads(raw)
        except (TypeError, ValueError):
            return
        t = f.get("type")
        if t == "message":
            parts = str(f.get("topic", "")).split(":", 2)
            if len(parts) == 3:
                handler = {"trade": self._on_trade, "orderbook": self._on_book}.get(parts[0])
                try:
                    if handler:
                        handler(parts[2].upper(), f.get("data") or {})
                except (KeyError, TypeError, ValueError) as e:
                    log.debug("프레임 해석 실패 %s: %s", f.get("topic"), e)
        elif t == "subscriptions":
            self.stats["rejected"] = f.get("rejected") or []
            if self.stats["rejected"]:
                log.warning("토스 구독 거부: %s", self.stats["rejected"])
        elif t == "error":
            code = (f.get("error") or {}).get("code")
            log.warning("토스 웹소켓 에러 프레임: %s", f.get("error"))
            if code == "rate-limit-exceeded":
                with self._lock:
                    self._dirty = True  # 잠시 뒤 다시 선언(선언 간격 제한이 이를 보장)
            elif code == "server-shutdown":
                raise ConnectionError("server-shutdown")

    def _bucket(self, sym: str, ts: datetime) -> dict:
        minute = ts.replace(second=0, microsecond=0).isoformat()
        return self._buckets.setdefault((sym, minute), {"buy": 0.0, "sell": 0.0, "mid": 0.0, "n": 0, "ask_sum": 0.0, "ask_n": 0, "ask_last": None})

    def _on_trade(self, sym: str, d: dict) -> None:
        price, vol = float(d["price"]), float(d["volume"])
        st = self._state.setdefault(sym, {"quote": None, "prev_quote": None, "last_price": None, "last_dir": 0})
        side, direction = classify_trade(price, st["quote"], st["prev_quote"], st["last_price"], st["last_dir"])
        st["last_price"] = price
        if direction:
            st["last_dir"] = direction
        b = self._bucket(sym, _parse_ts(d.get("timestamp")))
        b[side] += vol
        b["n"] += 1
        import flowsize   # P2 2026-10-27: 체결 금액 구간(XL/L/M/S)별 매수·매도 집계(래빗스탁·오르텍스 식 매매강도)
        usd = price * vol
        z = b.setdefault("sz", {}).setdefault(flowsize.bucket_of(usd), {"buy": 0.0, "sell": 0.0, "mid": 0.0, "buy_n": 0, "sell_n": 0, "buy_sh": 0.0, "sell_sh": 0.0})
        z[side] += usd
        if side in ("buy", "sell"):
            z[side + "_n"] += 1
            z[side + "_sh"] += vol
        self.stats["trades"] += 1

    def _on_book(self, sym: str, d: dict) -> None:
        asks = [(float(x["price"]), float(x["volume"])) for x in d.get("asks") or []]
        bids = [(float(x["price"]), float(x["volume"])) for x in d.get("bids") or []]
        st = self._state.setdefault(sym, {"quote": None, "prev_quote": None, "last_price": None, "last_dir": 0})
        st["prev_quote"] = st["quote"]
        st["quote"] = {"ask": min((p for p, _ in asks), default=None), "bid": max((p for p, _ in bids), default=None)}
        if asks:
            b = self._bucket(sym, _parse_ts(d.get("timestamp")))
            usd = sum(p * v for p, v in asks)
            b["ask_sum"] += usd
            b["ask_n"] += 1
            b["ask_last"] = usd
        self.stats["books"] += 1

    # ---- DB 기록 (1분 단위 합계를 통째로 덮어쓴다)
    def _flush(self) -> None:
        if not self._buckets:
            return
        now_min = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        rows, rows_sz = [], []
        for (sym, minute), b in list(self._buckets.items()):
            ts = datetime.fromisoformat(minute)
            day = ts.astimezone(ET).date().isoformat()
            rows.append((minute, sym, day, b["buy"], b["sell"], b["mid"], b["n"],
                         b["ask_sum"] / b["ask_n"] if b["ask_n"] else None, b["ask_last"], b["ask_n"]))
            for size, z in (b.get("sz") or {}).items():
                rows_sz.append((minute, sym, day, size, z["buy"], z["sell"], z["mid"], z["buy_n"], z["sell_n"], z["buy_sh"], z["sell_sh"]))
        import time as _time
        for i, wait in enumerate((0.5, 1.0, 2.0, None)):   # P1 2026-10-27: 'database is locked'(하루 20건) → BEGIN IMMEDIATE + 재시도
            try:
                with closing(db.connect()) as conn:
                    import flowsize
                    flowsize.ensure(conn)
                    conn.execute("BEGIN IMMEDIATE")
                    conn.executemany(
                        "INSERT OR REPLACE INTO close_flow (minute,ticker,date,buy_sh,sell_sh,mid_sh,n_trades,ask_usd_avg,ask_usd_last,n_books) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                    if rows_sz:
                        conn.executemany("INSERT OR REPLACE INTO close_flow_size (minute,ticker,date,size,buy_usd,sell_usd,mid_usd,buy_n,sell_n,buy_sh,sell_sh) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows_sz)
                    conn.commit()
                break
            except Exception as e:  # noqa: BLE001
                if wait is None or "locked" not in str(e).lower():
                    log.exception("close_flow 기록 실패")
                    return
                _time.sleep(wait)
        for k in [k for k in self._buckets if datetime.fromisoformat(k[1]) < now_min - timedelta(minutes=3)]:
            self._buckets.pop(k, None)  # 3분이 지난 분은 이미 완결 상태로 기록됨
