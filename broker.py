"""💵 broker — 4단계 소액 자동매매 1부(2026-10-29 새벽, 사용자 확정 'B안 1주 모드'). 설계: docs/broker_design_2026-10.md

원칙
  - 결정과 실행 분리: 언제 사고 팔지는 🧪 가상매매(papertrade)가 정하고, 여기서는 "낼지·몇 주·어떤 가격" 만 정한다.
  - 지정가만(시장가 금지). 매수 = 기준가 × (1 + 여유%), 매도 = × (1 − 여유%). 미국 호가 단위: $1 미만 소수 4자리, 이상 2자리(절삭).
  - 기본 dry-run: LIVE_TRADING 이 꺼져 있으면 주문 본문까지 만들고 live_orders 에 mode='dry' 로 기록만 한다(실제 호출 0번).
  - 주문은 스캐너 프로세스 안의 TossClient 로만(토큰이 클라이언트당 1개). 다른 프로세스(대시보드)는 live_requests 표에 요청만 넣는다.
  - 익절·손절은 토스 서버의 OCO 조건주문(미국은 모든 세션 발동) — 우리 서버가 죽어도 작동.
  - 킬 스위치: 하루 실현손실 한도 · 연속 거부 3회 · 403/계좌 제한 → 미체결 전부 취소 + LIVE_TRADING 끔 + 텔레그램.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import config
import db

log = logging.getLogger("broker")

DDL = [
    """CREATE TABLE IF NOT EXISTS live_orders (client_order_id TEXT PRIMARY KEY, day TEXT, strategy TEXT, ticker TEXT, side TEXT, qty REAL, limit_px REAL, ref_px REAL,
       status TEXT, mode TEXT, order_id TEXT, filled_qty REAL DEFAULT 0, avg_px REAL, code TEXT, request_id TEXT, note TEXT, pt_id INTEGER, created_at TEXT, updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS live_positions (ticker TEXT PRIMARY KEY, strategy TEXT, qty REAL, avg_px REAL, tp_px REAL, sl_px REAL, cond_id TEXT, opened_at TEXT, buy_coid TEXT)""",
    """CREATE TABLE IF NOT EXISTS live_closed (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, strategy TEXT, qty REAL, buy_px REAL, sell_px REAL, pnl_usd REAL,
       opened_at TEXT, closed_at TEXT, reason TEXT)""",
    """CREATE TABLE IF NOT EXISTS live_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ticker TEXT, note TEXT, created_at TEXT, done_at TEXT, result TEXT)""",
]
LIVE_KEYS = ("LIVE_TRADING", "LIVE_ONE_SHARE", "LIVE_STRATEGIES", "LIVE_USD_PER_TRADE", "LIVE_MAX_ORDERS_PER_DAY", "LIVE_MAX_OPEN", "LIVE_MAX_EXPOSURE_USD",
             "LIVE_MAX_PRICE", "LIVE_MIN_DOLLAR_VOL", "LIVE_LIMIT_SLIP_PCT", "LIVE_ORDER_TTL_MIN", "LIVE_DAILY_LOSS_USD", "LIVE_ACCOUNT_SEQ", "LIVE_SYNC_SEC")
_sync_lock = threading.Lock()   # sync/process_requests 가 스캐너 주기와 배경 스레드에서 동시에 돌지 않게(겹치면 체결을 두 번 반영할 수 있음)
_bg_runs = 0
OPEN_STATES = {"PENDING", "PARTIAL_FILLED", "PENDING_CANCEL", "PENDING_REPLACE"}     # 토스 OrderStatus 중 아직 끝나지 않은 것
DONE_STATES = {"FILLED", "CANCELED", "REJECTED", "REPLACED", "EXPIRED"}
BLOCK_DIL = ("ATM", "ELOC", "CB")
KILL_AFTER_FAILS = 3
OCO_DAYS = 30            # 조건주문 만료(최대 1년) — 저금통 보유는 길어야 몇 주
_fails = 0               # 연속 거부(프로세스 안)
_account: int | None = None


# ---------------------------------------------------------------- 기본
def ensure(conn) -> None:
    for d in DDL:
        conn.execute(d)


def limits() -> dict:
    return {k: getattr(config, k, None) for k in LIVE_KEYS}


def strategies() -> set[str]:
    return {s.strip() for s in str(getattr(config, "LIVE_STRATEGIES", "") or "").split(",") if s.strip()}


def _regular(now: datetime | None = None) -> bool:
    """미국 정규장(동부 09:30~16:00, 평일)인지 — scanner.is_regular_session 과 같은 규칙(순환 import 를 피해 여기 둠)."""
    from zoneinfo import ZoneInfo
    et = _now(now).astimezone(ZoneInfo("America/New_York"))
    return et.weekday() < 5 and (9, 30) <= (et.hour, et.minute) < (16, 0)


def killed() -> str | None:
    """킬 스위치가 켜져 있으면 그 이유(날짜 포함), 아니면 None."""
    m = db.get_meta("live:kill")
    return (m or {}).get("value") or None


def is_live() -> bool:
    return bool(getattr(config, "LIVE_TRADING", False)) and not killed()


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(v) -> datetime | None:
    """ISO 문자열(토스는 KST +09:00, 우리는 UTC) → UTC aware datetime. 못 읽으면 None."""
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _day(now: datetime | None = None) -> str:
    return _now(now).astimezone(timezone.utc).date().isoformat()


def round_px(px: float) -> float:
    """미국 호가 단위에 맞게 절삭: $1 미만 소수 4자리, 이상 2자리(토스 문서)."""
    d = 4 if px < 1 else 2
    return math.floor(float(px) * 10 ** d + 1e-9) / 10 ** d


def limit_price(ref_px: float, side: str) -> float:
    slip = float(getattr(config, "LIVE_LIMIT_SLIP_PCT", 1.0)) / 100
    px = ref_px * (1 + slip) if side == "BUY" else ref_px * (1 - slip)
    return round_px(px)


def quantity_for(ref_px: float) -> int:
    """1주 모드면 1주. 아니면 종목당 금액 ÷ 기준가(내림), 1주 미만이면 0(안 삼)."""
    if getattr(config, "LIVE_ONE_SHARE", True):
        return 1
    q = math.floor(float(getattr(config, "LIVE_USD_PER_TRADE", 100.0)) / float(ref_px)) if ref_px and ref_px > 0 else 0
    return int(q) if q >= 1 else 0


def coid(strategy: str, ticker: str, side: str, day: str, n: int) -> str:
    """멱등키(토스 36자 · 영숫자 - _ 만). 같은 전략·종목·날·방향·순번이면 같은 키 → 10분 안 재전송은 같은 주문."""
    t = "".join(ch if ch.isalnum() else "_" for ch in ticker.upper())
    return f"{strategy[:6]}-{t}-{day.replace('-', '')}-{side[0]}{n}"[:36]


def account(tc) -> int | None:
    """주문에 쓸 계좌(accountSeq): 설정값이 있으면 그것, 없으면 첫 BROKERAGE 계좌(한 번만 조회, ACCOUNT 한도 1/s)."""
    global _account
    v = str(getattr(config, "LIVE_ACCOUNT_SEQ", "") or "").strip()
    if v.isdigit():
        return int(v)
    if _account is None and tc is not None:
        try:
            accs = tc.accounts() or []
            pick = next((a for a in accs if a.get("accountType") in (None, "BROKERAGE")), accs[0] if accs else None)
            _account = int(pick["accountSeq"]) if pick else None
        except Exception as e:  # noqa: BLE001
            log.warning("계좌 조회 실패: %s", e)
    return _account


def _notify(text: str) -> None:
    try:
        import notify
        notify.send_telegram("💵 " + text)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 상태·한도
def positions(conn) -> list[dict]:
    ensure(conn)
    return [dict(r) for r in conn.execute("SELECT * FROM live_positions ORDER BY opened_at")]


def day_stats(conn, day: str) -> dict:
    """오늘 매수 주문 수(실주문, 거부 제외) · 보유 수 · 노출(보유 평가 + 미체결 매수) · 오늘 실현손익."""
    ensure(conn)
    buys = conn.execute("SELECT COUNT(*) FROM live_orders WHERE day=? AND side='BUY' AND mode='live' AND status NOT IN ('REJECTED','BLOCKED')", (day,)).fetchone()[0]
    pos = positions(conn)
    pend = conn.execute("SELECT COALESCE(SUM(qty*limit_px),0) FROM live_orders WHERE side='BUY' AND mode='live' AND status IN ('PENDING','PARTIAL_FILLED','PENDING_REPLACE')").fetchone()[0]
    exposure = sum(float(p["qty"]) * float(p["avg_px"] or 0) for p in pos) + float(pend or 0)
    realized = conn.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM live_closed WHERE substr(closed_at,1,10)=?", (day,)).fetchone()[0]
    return {"buys": int(buys), "open": len(pos), "exposure": round(exposure, 2), "realized": round(float(realized or 0), 2)}


def can_buy(conn, strategy: str, ticker: str, ref_px: float, qty: int, *, dilution: str | None = None, share_cls: str | None = None,
            dollar_vol: float | None = None, buying_power: float | None = None, day: str | None = None) -> tuple[bool, str]:
    """안전장치 전부. (True, "") 또는 (False, 이유)."""
    day = day or _day()
    if strategy != "probe" and strategy not in strategies():
        return False, f"전략 '{strategy}' 은 실매매 대상이 아님"
    if qty < 1:
        return False, "1주 미만"
    if ref_px is None or ref_px <= 0:
        return False, "가격 없음"
    if strategy != "probe" and ref_px > float(config.LIVE_MAX_PRICE):
        return False, f"주가 ${ref_px:.2f} > 상한 ${float(config.LIVE_MAX_PRICE):g}"
    if dilution in BLOCK_DIL:
        return False, f"희석 {dilution}"
    if share_cls == "bad":
        return False, "⑥ 주식수 +20% 초과"
    if dollar_vol is not None and dollar_vol < float(config.LIVE_MIN_DOLLAR_VOL):
        return False, f"거래대금 ${dollar_vol:,.0f} < ${float(config.LIVE_MIN_DOLLAR_VOL):,.0f}"
    k = killed()
    if k:
        return False, f"킬 스위치({k})"
    st = day_stats(conn, day)
    if st["buys"] >= int(config.LIVE_MAX_ORDERS_PER_DAY):
        return False, f"오늘 매수 {st['buys']}건 = 상한"
    if st["open"] >= int(config.LIVE_MAX_OPEN):
        return False, f"보유 {st['open']}종목 = 상한"
    need = limit_price(ref_px, "BUY") * qty
    if st["exposure"] + need > float(config.LIVE_MAX_EXPOSURE_USD):
        return False, f"노출 ${st['exposure']:.0f} + ${need:.2f} > 상한 ${float(config.LIVE_MAX_EXPOSURE_USD):g}"
    t = ticker.upper()
    if conn.execute("SELECT 1 FROM live_positions WHERE ticker=?", (t,)).fetchone():
        return False, "이미 보유"
    if conn.execute("SELECT 1 FROM live_orders WHERE ticker=? AND side='BUY' AND mode='live' AND status IN ('PENDING','PARTIAL_FILLED','PENDING_REPLACE')", (t,)).fetchone():
        return False, "미체결 매수 있음"
    if conn.execute("SELECT 1 FROM live_orders WHERE ticker=? AND day=? AND mode='live' AND status IN ('REJECTED','CANCELED','BLOCKED')", (t, day)).fetchone():
        return False, "오늘 이미 거부·취소된 종목"
    if buying_power is not None and buying_power < need:
        return False, f"매수가능 ${buying_power:.2f} < ${need:.2f}"
    return True, ""


def _record(conn, **r) -> None:
    now = _iso(_now())
    r.setdefault("created_at", now)
    r["updated_at"] = now
    cols = ["client_order_id", "day", "strategy", "ticker", "side", "qty", "limit_px", "ref_px", "status", "mode", "order_id", "filled_qty", "avg_px", "code", "request_id", "note", "pt_id", "created_at", "updated_at"]
    conn.execute(f"INSERT OR REPLACE INTO live_orders ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [r.get(c) for c in cols])


def _set(conn, coid_: str, **kv) -> None:
    kv["updated_at"] = _iso(_now())
    conn.execute(f"UPDATE live_orders SET {', '.join(f'{k}=?' for k in kv)} WHERE client_order_id=?", [*kv.values(), coid_])


# ---------------------------------------------------------------- 매수·매도
def mirror_buy(conn, tc, strategy: str, ticker: str, ref_px: float, *, tp_px: float | None = None, sl_px: float | None = None, pt_id: int | None = None,
               dilution: str | None = None, share_cls: str | None = None, dollar_vol: float | None = None, day: str | None = None, now: datetime | None = None) -> dict:
    """가상매매가 산 순간 호출. 1주(또는 금액) 지정가 매수를 내거나(라이브) 기록만 한다(dry-run). 반환 {"ok","mode","why","coid"}."""
    global _fails
    ensure(conn)
    t, day = ticker.upper(), day or _day(now)
    if strategy != "probe" and strategy not in strategies():
        return {"ok": False, "mode": "off", "why": "전략 꺼짐", "coid": None}
    qty = quantity_for(ref_px)
    lp = limit_price(ref_px, "BUY") if ref_px else None
    live = is_live()
    bp = None
    acc = account(tc) if live else None
    if live and tc is not None and acc is not None:
        try:
            bp = float((tc.buying_power(acc, "USD") or {}).get("cashBuyingPower") or 0)
        except Exception as e:  # noqa: BLE001
            log.warning("매수가능금액 조회 실패: %s", e)
    ok, why = can_buy(conn, strategy, t, ref_px, qty, dilution=dilution, share_cls=share_cls, dollar_vol=dollar_vol, buying_power=bp, day=day)
    n = conn.execute("SELECT COUNT(*) FROM live_orders WHERE ticker=? AND day=? AND side='BUY'", (t, day)).fetchone()[0] + 1
    cid = coid(strategy, t, "BUY", day, n)
    base = {"client_order_id": cid, "day": day, "strategy": strategy, "ticker": t, "side": "BUY", "qty": qty, "limit_px": lp, "ref_px": ref_px, "pt_id": pt_id,
            "note": json.dumps({"tp": tp_px, "sl": sl_px}, ensure_ascii=False), "created_at": _iso(_now(now))}   # created_at 은 호출자의 시각(TTL 계산 기준)
    if not live:
        _record(conn, **{**base, "note": base["note"] if ok else why}, status="DRY", mode="dry", code=None if ok else "blocked")
        conn.commit()
        return {"ok": ok, "mode": "dry", "why": why, "coid": cid, "qty": qty, "limit_px": lp}
    if not ok:
        _record(conn, **{**base, "note": why}, status="BLOCKED", mode="live", code="blocked")
        conn.commit()
        return {"ok": False, "mode": "live", "why": why, "coid": cid, "qty": qty, "limit_px": lp}
    if tc is None or acc is None:
        return {"ok": False, "mode": "live", "why": "토스 클라이언트·계좌 없음", "coid": cid}
    try:
        res = tc.order_create(acc, t, "BUY", qty, lp, client_order_id=cid) or {}
        _record(conn, **base, status="PENDING", mode="live", order_id=res.get("orderId"))
        conn.commit()
        _fails = 0
        _notify(f"매수 주문 {t} {qty}주 @${lp:g} ({strategy}, 기준가 ${ref_px:g})")
        return {"ok": True, "mode": "live", "why": "", "coid": cid, "qty": qty, "limit_px": lp, "order_id": res.get("orderId")}
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", type(e).__name__)
        _record(conn, **{**base, "note": str(e)[:200]}, status="REJECTED", mode="live", code=str(code), request_id=getattr(e, "request_id", None))
        conn.commit()
        _fails += 1
        _notify(f"매수 거부 {t}: {code} ({str(e)[:80]})")
        if _fails >= KILL_AFTER_FAILS or str(code) in ("ip-not-allowed", "account-restricted", "auth-blocked"):
            kill(conn, tc, f"연속 거부 {_fails}회 · 마지막 {code}", now=now)
        return {"ok": False, "mode": "live", "why": str(code), "coid": cid}


def sell(conn, tc, ticker: str, ref_px: float, reason: str, *, now: datetime | None = None, force: bool = False) -> dict:
    """보유 종목을 지정가로 판다(가상매매 청산 판정·화면 요청). 조건주문(OCO)이 걸려 있으면 먼저 취소.
    force=True(관리 화면 '지금 팔기'): 실매매가 꺼져 있거나 킬 상태여도 판다 — 보유를 줄이는 쪽은 막지 않는다(2026-10-29)."""
    ensure(conn)
    t, day = ticker.upper(), _day(now)
    pos = conn.execute("SELECT * FROM live_positions WHERE ticker=?", (t,)).fetchone()
    if not pos:
        return {"ok": False, "why": "보유 없음"}
    pos = dict(pos)
    qty, lp = float(pos["qty"]), limit_price(ref_px, "SELL")
    n = conn.execute("SELECT COUNT(*) FROM live_orders WHERE ticker=? AND day=? AND side='SELL'", (t, day)).fetchone()[0] + 1
    cid = coid(pos.get("strategy") or "live", t, "SELL", day, n)
    base = {"client_order_id": cid, "day": day, "strategy": pos.get("strategy"), "ticker": t, "side": "SELL", "qty": qty, "limit_px": lp, "ref_px": ref_px, "note": reason,
            "created_at": _iso(_now(now))}
    if not is_live() and not force:
        _record(conn, **base, status="DRY", mode="dry")
        conn.commit()
        return {"ok": True, "mode": "dry", "coid": cid}
    acc = account(tc)
    if conn.execute("SELECT 1 FROM live_orders WHERE ticker=? AND side='SELL' AND mode='live' AND status IN ('PENDING','PARTIAL_FILLED')", (t,)).fetchone():
        return {"ok": False, "why": "미체결 매도 있음"}
    try:
        if pos.get("cond_id"):
            try:
                tc.cond_cancel(acc, pos["cond_id"])
            except Exception as e:  # noqa: BLE001
                log.warning("%s 조건주문 취소 실패: %s", t, e)
            conn.execute("UPDATE live_positions SET cond_id=NULL WHERE ticker=?", (t,))
        res = tc.order_create(acc, t, "SELL", qty, lp, client_order_id=cid) or {}
        _record(conn, **base, status="PENDING", mode="live", order_id=res.get("orderId"))
        conn.commit()
        _notify(f"매도 주문 {t} {qty:g}주 @${lp:g} — {reason}")
        return {"ok": True, "mode": "live", "coid": cid, "order_id": res.get("orderId")}
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", type(e).__name__)
        _record(conn, **{**base, "note": str(e)[:200]}, status="REJECTED", mode="live", code=str(code))
        conn.commit()
        _notify(f"매도 거부 {t}: {code}")
        return {"ok": False, "mode": "live", "why": str(code), "coid": cid}


# ---------------------------------------------------------------- 익절·손절(토스 서버의 조건주문)
def oco_body(ticker: str, qty: float, tp_px: float | None, sl_px: float | None, cid: str, expire: str) -> dict | None:
    """OCO(매도 2개: 익절 지정가 · 손절 감시가 아래 지정가) 또는 SINGLE(둘 중 하나만). 둘 다 없으면 None."""
    slip = float(getattr(config, "LIVE_LIMIT_SLIP_PCT", 1.0)) / 100
    first = second = None
    if tp_px:
        first = {"orderSide": "SELL", "triggerPrice": round_px(tp_px), "orderPrice": round_px(tp_px)}
    if sl_px:
        second = {"orderSide": "SELL", "triggerPrice": round_px(sl_px), "orderPrice": round_px(sl_px * (1 - slip))}
    conds = [c for c in (first, second) if c]
    if not conds:
        return None
    body = {"symbol": ticker, "type": "OCO" if len(conds) == 2 else "SINGLE", "quantity": qty, "orderType": "LIMIT", "clientOrderId": cid, "expireDate": expire,
            "first": conds[0]}
    if len(conds) == 2:
        body["second"] = conds[1]
    return body


def arm_exit(conn, tc, pos: dict, *, now: datetime | None = None) -> str | None:
    """체결 직후 OCO 등록. 실패하면 손절 SINGLE 만이라도. 조건주문 ID 를 보유 표에 저장."""
    acc = account(tc)
    t = pos["ticker"]
    expire = (_now(now).date() + timedelta(days=OCO_DAYS)).isoformat()
    cid = coid(pos.get("strategy") or "live", t, "OCO", _day(now), 1)[:36]
    body = oco_body(t, float(pos["qty"]), pos.get("tp_px"), pos.get("sl_px"), cid, expire)
    if not body:
        return None
    for attempt, b in enumerate((body, oco_body(t, float(pos["qty"]), None, pos.get("sl_px"), cid + "s", expire))):
        if not b:
            continue
        try:
            res = tc.cond_create(acc, b) or {}
            cond_id = res.get("conditionalOrderId")
            conn.execute("UPDATE live_positions SET cond_id=? WHERE ticker=?", (cond_id, t))
            conn.commit()
            _notify(f"{t} {'익절·손절 OCO' if attempt == 0 else '손절만'} 등록 (익절 ${pos.get('tp_px') or 0:g} · 손절 ${pos.get('sl_px') or 0:g})")
            return cond_id
        except Exception as e:  # noqa: BLE001
            log.warning("%s 조건주문 등록 실패(%d): %s", t, attempt, e)
    _notify(f"⚠️ {t} 익절·손절 조건주문 등록 실패 — 손으로 걸어 주세요")
    return None


# ---------------------------------------------------------------- 동기화(주기마다 한 번)
def _journal(conn, ticker: str, side_ko: str, day: str, px: float, qty: float, strategy: str | None, note: str) -> None:
    try:
        import journal
        journal.add(conn, ticker, side_ko, day, float(px), float(qty), signal=f"자동 {strategy or ''}".strip(), note=note)
    except Exception as e:  # noqa: BLE001
        log.warning("매매 일지 기입 실패: %s", e)


def _open_position(conn, row: dict, o: dict, now: datetime) -> None:
    ex = o.get("execution") or {}
    qty = float(ex.get("filledQuantity") or row["qty"])
    px = float(ex.get("averageFilledPrice") or row["limit_px"])
    try:
        meta = json.loads(row.get("note") or "{}")
    except ValueError:
        meta = {}
    conn.execute("INSERT OR REPLACE INTO live_positions (ticker, strategy, qty, avg_px, tp_px, sl_px, cond_id, opened_at, buy_coid) VALUES (?,?,?,?,?,?,NULL,?,?)",
                 (row["ticker"], row["strategy"], qty, px, meta.get("tp"), meta.get("sl"), _iso(now), row["client_order_id"]))
    _journal(conn, row["ticker"], "매수", _day(now), px, qty, row["strategy"], f"자동 체결 · 지정가 ${row['limit_px']:g}")
    _notify(f"✅ 매수 체결 {row['ticker']} {qty:g}주 @${px:g}")


def _close_position(conn, ticker: str, sell_px: float, qty: float, reason: str, now: datetime) -> float | None:
    pos = conn.execute("SELECT * FROM live_positions WHERE ticker=?", (ticker,)).fetchone()
    if not pos:
        return None
    pos = dict(pos)
    pnl = (sell_px - float(pos["avg_px"] or 0)) * qty
    conn.execute("INSERT INTO live_closed (ticker, strategy, qty, buy_px, sell_px, pnl_usd, opened_at, closed_at, reason) VALUES (?,?,?,?,?,?,?,?,?)",
                 (ticker, pos.get("strategy"), qty, pos.get("avg_px"), sell_px, pnl, pos.get("opened_at"), _iso(now), reason))
    conn.execute("DELETE FROM live_positions WHERE ticker=?", (ticker,))
    _journal(conn, ticker, "매도", _day(now), sell_px, qty, pos.get("strategy"), f"{reason} · 손익 ${pnl:+.2f}")
    _notify(f"{'🟢' if pnl >= 0 else '🔴'} 매도 체결 {ticker} {qty:g}주 @${sell_px:g} — {reason} · ${pnl:+.2f}")
    return pnl


def sync(conn, tc, *, now: datetime | None = None) -> dict:
    """토스 주문 상태를 우리 표에 반영(체결 → 보유·일지·OCO, 취소·거부), TTL 지난 미체결 매수 취소, OCO 체결 감지, 일손실 킬 스위치.
    스캐너 주기(≈13분)와 배경 스레드(LIVE_SYNC_SEC, 기본 60초) 양쪽에서 부르며 잠금으로 겹치지 않게 한다(2026-10-29 ②)."""
    ensure(conn)
    now = _now(now)
    out = {"filled": 0, "canceled": 0, "ttl": 0, "oco_fills": 0, "kill": None}
    if tc is None:
        return out
    if not _sync_lock.acquire(blocking=False):
        return out   # 다른 쪽이 돌고 있음 — 이번엔 건너뜀
    try:
        return _sync(conn, tc, now, out)
    finally:
        _sync_lock.release()


def _sync(conn, tc, now: datetime, out: dict) -> dict:
    if tc is None:
        return out   # 2026-10-29: 실매매가 꺼져/킬 상태여도 이미 나간 주문·보유는 계속 추적(체결 반영·OCO 감지). 새 매수만 스위치가 막는다
    pending = [dict(r) for r in conn.execute("SELECT * FROM live_orders WHERE mode='live' AND status IN ('PENDING','PARTIAL_FILLED','PENDING_CANCEL','PENDING_REPLACE')")]
    pos = positions(conn)
    if not pending and not pos:
        return out   # 추적할 것이 없으면 토스를 부르지 않음(계좌 조회 포함)
    acc = account(tc)
    try:
        remote = {o["orderId"]: o for o in (tc.orders(acc, "OPEN") or [])}
        since = (now.date() - timedelta(days=2)).isoformat()
        for o in tc.orders(acc, "CLOSED", since=since) or []:
            remote.setdefault(o["orderId"], o)
    except Exception as e:  # noqa: BLE001
        log.warning("주문 조회 실패: %s", e)
        return out
    ttl = timedelta(minutes=int(config.LIVE_ORDER_TTL_MIN))
    for r in pending:
        o = remote.get(r.get("order_id") or "")
        if not o:
            continue
        stt = str(o.get("status") or "")
        ex = o.get("execution") or {}
        fq, ap = float(ex.get("filledQuantity") or 0), ex.get("averageFilledPrice")
        _set(conn, r["client_order_id"], status=stt, filled_qty=fq, avg_px=ap)
        if stt == "FILLED" or (stt in ("CANCELED", "REJECTED", "EXPIRED") and fq > 0):
            out["filled"] += 1
            if r["side"] == "BUY":
                _open_position(conn, r, o, now)
                if r.get("strategy") == "probe":   # 1주 왕복 테스트: 익절·손절 대신 체결가 −여유% 지정가로 바로 되판다
                    conn.commit()
                    sell(conn, tc, r["ticker"], float(ap or r["limit_px"]), "1주 왕복 테스트 매도", now=now)
                else:
                    p = conn.execute("SELECT * FROM live_positions WHERE ticker=?", (r["ticker"],)).fetchone()
                    if p:
                        arm_exit(conn, tc, dict(p), now=now)
            else:
                _close_position(conn, r["ticker"], float(ap or r["limit_px"]), fq or float(r["qty"]), r.get("note") or "매도", now)
        elif stt in ("CANCELED", "REJECTED", "EXPIRED"):
            out["canceled"] += 1
        elif stt in OPEN_STATES and r["side"] == "BUY":
            try:
                created = datetime.fromisoformat(r["created_at"])
            except (TypeError, ValueError):
                created = now
            if now - created > ttl and stt != "PENDING_CANCEL":
                try:
                    tc.order_cancel(acc, r["order_id"])
                    _set(conn, r["client_order_id"], status="PENDING_CANCEL", note="TTL 취소")
                    out["ttl"] += 1
                    _notify(f"⏱ {r['ticker']} 매수 {int(config.LIVE_ORDER_TTL_MIN)}분 미체결 → 취소(오늘 재시도 안 함)")
                except Exception as e:  # noqa: BLE001
                    log.warning("%s TTL 취소 실패: %s", r["ticker"], e)
    # OCO(토스 서버)로 팔린 보유 — 2026-10-29 01:15 사고: 사용자가 따로 들고 있던 POM 386주를 직접 판 기록을 우리 1주 포지션의 OCO 체결로 잘못 붙여
    # −$115 로 기록하고 킬 스위치까지 작동. 이제는 ① 조건주문이 실제 발동(ORDERED/COMPLETED)했을 때만 ② 수량이 우리 보유와 같고 ③ 보유 시작 뒤에 낸 SELL 체결만 인정
    ours = {r["order_id"] for r in conn.execute("SELECT order_id FROM live_orders WHERE order_id IS NOT NULL")}
    for p in positions(conn):
        if not p.get("cond_id"):
            continue   # 조건주문이 없으면 토스가 대신 팔았을 리 없음
        try:
            cst = str((tc.cond_order(acc, p["cond_id"]) or {}).get("status") or "")
        except Exception as e:  # noqa: BLE001
            log.warning("%s 조건주문 상태 확인 실패: %s", p["ticker"], e)
            continue
        if cst not in ("ORDERED", "COMPLETED"):
            continue
        opened = _parse_iso(p.get("opened_at"))
        for o in remote.values():
            if o.get("symbol") == p["ticker"] and str(o.get("side")) == "SELL" and str(o.get("status")) == "FILLED" and o.get("orderId") not in ours:
                ex = o.get("execution") or {}
                px, qty = float(ex.get("averageFilledPrice") or o.get("price") or 0), float(ex.get("filledQuantity") or o.get("quantity") or 0)
                ordered = _parse_iso(o.get("orderedAt"))
                if abs(qty - float(p["qty"])) > 1e-9 or (opened and ordered and ordered < opened):
                    continue   # 수량이 다르거나 보유 전 주문이면 사용자의 다른 거래
                _record(conn, client_order_id=f"oco-{o['orderId']}"[:36], day=_day(now), strategy=p.get("strategy"), ticker=p["ticker"], side="SELL", qty=qty, limit_px=o.get("price"),
                        ref_px=None, status="FILLED", mode="live", order_id=o["orderId"], filled_qty=qty, avg_px=px, note="OCO 체결")
                _close_position(conn, p["ticker"], px, qty, "익절·손절 조건주문 체결", now)
                out["oco_fills"] += 1
                break
    conn.commit()
    st = day_stats(conn, _day(now))
    if st["realized"] <= -abs(float(config.LIVE_DAILY_LOSS_USD)):
        out["kill"] = kill(conn, tc, f"오늘 실현손실 ${st['realized']:+.2f}", now=now)
    return out


# ---------------------------------------------------------------- 킬 스위치·요청 표
def kill(conn, tc, reason: str, *, now: datetime | None = None) -> str:
    """미체결 실주문 전부 취소 + LIVE_TRADING 끔(설정에 저장) + 메모 + 텔레그램. 다시 켜려면 관리 모드에서 킬 해제 후 스위치."""
    ensure(conn)
    acc = account(tc) if tc is not None else None
    n = 0
    for r in conn.execute("SELECT client_order_id, order_id, ticker FROM live_orders WHERE mode='live' AND status IN ('PENDING','PARTIAL_FILLED','PENDING_REPLACE')").fetchall():
        try:
            if tc is not None and r["order_id"]:
                tc.order_cancel(acc, r["order_id"])
            _set(conn, r["client_order_id"], status="PENDING_CANCEL", note=f"킬 스위치: {reason}")
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("킬 스위치 취소 실패 %s: %s", r["ticker"], e)
    conn.commit()
    tag = f"{_day(now)} {reason}"
    db.set_meta("live:kill", tag)
    try:
        ov = config.overrides()
        ov["LIVE_TRADING"] = False
        config.save_overrides(ov)
    except Exception as e:  # noqa: BLE001
        log.warning("LIVE_TRADING 끄기 실패: %s", e)
    config.LIVE_TRADING = False
    _notify(f"🛑 킬 스위치: {reason} — 미체결 {n}건 취소, 실매매 꺼짐(보유 종목의 OCO 는 토스에 남아 있음)")
    return tag


def unkill() -> None:
    db.set_meta("live:kill", "")


def request(conn, kind: str, ticker: str = "", note: str = "") -> int:
    """대시보드 → 스캐너 요청(sell · kill). 스캐너가 다음 주기에 process_requests 로 처리."""
    ensure(conn)
    cur = conn.execute("INSERT INTO live_requests (kind, ticker, note, created_at) VALUES (?,?,?,?)", (kind, ticker.upper(), note, _iso(_now())))
    conn.commit()
    return int(cur.lastrowid)


def process_requests(conn, tc, prices: dict | None = None, *, now: datetime | None = None) -> int:
    """화면 요청(팔기·킬·1주 왕복·계좌 확인) 처리. 가격이 없으면 토스 현재가를 받는다('지금 팔기' 가 옛 평단가 기준이 되지 않게)."""
    ensure(conn)
    if not _sync_lock.acquire(blocking=False):
        return 0
    try:
        return _process_requests(conn, tc, prices, now)
    finally:
        _sync_lock.release()


def _px_now(tc, ticker: str, prices: dict | None):
    px = (prices or {}).get(ticker)
    if isinstance(px, dict):
        px = px.get("price")
    if px is None and tc is not None:
        try:
            px = ((tc.prices([ticker]) or {}).get(ticker) or {}).get("price")
        except Exception as e:  # noqa: BLE001
            log.warning("%s 현재가 조회 실패: %s", ticker, e)
    return px


def _process_requests(conn, tc, prices: dict | None, now: datetime | None) -> int:
    n = 0
    for r in conn.execute("SELECT * FROM live_requests WHERE done_at IS NULL ORDER BY id").fetchall():
        r = dict(r)
        if r["kind"] == "kill":
            res = kill(conn, tc, r.get("note") or "화면 요청", now=now)
        elif r["kind"] == "sell":
            px = _px_now(tc, r["ticker"], prices)
            pos = conn.execute("SELECT avg_px FROM live_positions WHERE ticker=?", (r["ticker"],)).fetchone()
            res = json.dumps(sell(conn, tc, r["ticker"], float(px or (pos["avg_px"] if pos else 0) or 0), r.get("note") or "화면 요청", now=now, force=True), ensure_ascii=False)
        elif r["kind"] == "probe":   # 1주 왕복 테스트(관리 화면): 지금 가격으로 1주 매수 → 체결되면 sync 가 바로 되판다
            px = _px_now(tc, r["ticker"], prices)
            res = json.dumps(mirror_buy(conn, tc, "probe", r["ticker"], float(px), now=now), ensure_ascii=False) if px else "가격 없음"
        elif r["kind"] == "check":   # 읽기만: 계좌·달러 매수가능금액 — 키가 계좌 API 를 쓸 수 있는지(= 주문 권한의 간접 확인). 실주문이 꺼져 있어도 됨
            try:
                accs = tc.accounts() if tc is not None else []
                acc = account(tc)
                bp = tc.buying_power(acc, "USD") if (tc is not None and acc is not None) else {}
                res = json.dumps({"ok": True, "accounts": [{"accountSeq": a.get("accountSeq"), "accountNo": _mask(a.get("accountNo")), "type": a.get("accountType")} for a in accs],
                                  "usd_buying_power": bp.get("cashBuyingPower")}, ensure_ascii=False)
                _notify(f"계좌 확인 OK — 계좌 {len(accs)}개 · 달러 매수가능 ${float(bp.get('cashBuyingPower') or 0):,.2f}")
            except Exception as e:  # noqa: BLE001
                res = f"실패 {getattr(e, 'code', type(e).__name__)}: {str(e)[:150]}"
                _notify(f"계좌 확인 실패: {res[:120]}")
        else:
            res = "모르는 요청"
        conn.execute("UPDATE live_requests SET done_at=?, result=? WHERE id=?", (_iso(_now(now)), str(res)[:300], r["id"]))
        n += 1
    conn.commit()
    return n


def piggy_targets(conn) -> list[dict]:
    """🐷 저금통 종목 + 박스(가상매매 open_piggy 와 같은 계산) + 금지 목록 재료(희석 상태 · ⑥ 주식수 변동 · 20일 거래대금)."""
    import piggy
    import shares
    mm = piggy.metrics_map()
    out = []
    for r in piggy.items().to_dict("records"):
        t = r["ticker"]
        lo, hi, _src = piggy.box_of(r, mm.get(t))
        snap = conn.execute("SELECT dilution_status, avg_dollar_vol FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        cls6 = None
        try:
            sc = shares.change(t, conn)
            if sc:
                p6 = round(sc["pct"], 6)
                cls6 = "bad" if p6 > 20 else "warn" if p6 > 10 else "ok"
        except Exception:  # noqa: BLE001
            cls6 = None
        out.append({"ticker": t, "lo": lo, "hi": hi, "category": r.get("category"), "dilution": snap["dilution_status"] if snap else None,
                    "dollar_vol": snap["avg_dollar_vol"] if snap else None, "share_cls": cls6})
    return out


def scan_piggy(conn, tc, *, prices: dict | None = None, now: datetime | None = None) -> dict:
    """스캐너 주기마다(미국 정규장만): 저금통 종목이 🟢 저점 구간이면 1주 지정가 매수 — 가상매매 open_piggy 와 같은 조건, 익절 = 박스 상단 · 손절 = 박스 하단 −5%.
    종목당 하루 한 번만 시도(dry 든 live 든 live_orders 에 오늘 기록이 있으면 건너뜀). prices 가 없으면 토스 현재가를 받는다(한 번에 200종목)."""
    out = {"checked": 0, "bought": [], "dry": [], "skipped": {}}
    if "piggy" not in strategies() or not _regular(now):
        return out
    import piggy
    ensure(conn)
    tg = piggy_targets(conn)
    if not tg:
        return out
    if prices is None:
        prices = tc.prices([x["ticker"] for x in tg]) if tc is not None else {}
    day, live = _day(now), is_live()
    for x in tg:
        t = x["ticker"]
        p = prices.get(t)
        px = p.get("price") if isinstance(p, dict) else p
        if not px or not x["lo"] or not x["hi"]:
            continue
        out["checked"] += 1
        if piggy.zone(float(px), x["lo"], x["hi"]) != "🟢 저점 구간":
            continue
        if conn.execute("SELECT 1 FROM live_orders WHERE ticker=? AND day=? AND side='BUY' AND (mode='live' OR ?)", (t, day, 0 if live else 1)).fetchone():
            continue   # 하루 한 번: 실주문 기록은 항상 막고, dry 기록은 dry 일 때만 막는다(스위치를 켠 날 dry 기록 때문에 실주문을 못 내지 않게 — 10/29 첫 운영에서 발견)
        r = mirror_buy(conn, tc, "piggy", t, float(px), tp_px=x["hi"], sl_px=x["lo"] * 0.95, dilution=x["dilution"], share_cls=x["share_cls"], dollar_vol=x["dollar_vol"], day=day, now=now)
        if r.get("ok") and r.get("mode") == "live":
            out["bought"].append(t)
        elif r.get("ok") and r.get("mode") == "dry":
            out["dry"].append(t)
        else:
            out["skipped"][t] = r.get("why")
    return out


def _mask(no) -> str:
    s = str(no or "")
    return ("*" * max(0, len(s) - 4) + s[-4:]) if s else ""


def tick(conn, tc, *, now: datetime | None = None, apply: bool = True) -> dict:
    """한 번의 동기화: (관리 모드 설정 다시 읽기) → 체결 반영 → 화면 요청 처리. 스캐너 주기와 배경 스레드가 같이 쓴다."""
    if apply:
        try:
            config.apply_overrides()
        except Exception:  # noqa: BLE001
            pass
    s = sync(conn, tc, now=now)
    s["requests"] = process_requests(conn, tc, now=now)
    return s


def start_background(tc, interval: float | None = None, stop: threading.Event | None = None, apply: bool = True) -> threading.Thread:
    """스캐너 프로세스 안에서 LIVE_SYNC_SEC(기본 60초)마다 tick 을 도는 데몬 스레드(2026-10-29 ②: 정규장 스캐너 한 주기 ≈13분이라 체결·요청 반영이 늦었음).
    토스 클라이언트는 잠금이 있어 스레드에서 같이 써도 된다(tossws 수집기와 같은 방식). 반환한 스레드는 stop.set() 으로 멈춘다."""
    global _bg_runs
    stop = stop or threading.Event()
    iv = float(interval if interval is not None else getattr(config, "LIVE_SYNC_SEC", 60))

    def _loop():
        global _bg_runs
        while not stop.is_set():
            stop.wait(iv)
            if stop.is_set():
                break
            try:
                with closing(db.connect()) as conn:
                    tick(conn, tc, apply=apply)
                _bg_runs += 1
            except Exception as e:  # noqa: BLE001
                log.warning("실매매 배경 동기화 실패: %s", e)

    th = threading.Thread(target=_loop, name="broker-sync", daemon=True)
    th.stop = stop  # type: ignore[attr-defined]
    th.start()
    return th


def status(conn, *, now: datetime | None = None) -> dict:
    """관리 화면용 요약(now 를 주면 그 날짜 기준 — 테스트)."""
    ensure(conn)
    day = _day(now)
    st = day_stats(conn, day)
    pend = [dict(r) for r in conn.execute("SELECT * FROM live_orders WHERE mode='live' AND status IN ('PENDING','PARTIAL_FILLED','PENDING_CANCEL','PENDING_REPLACE') ORDER BY created_at DESC")]
    recent = [dict(r) for r in conn.execute("SELECT * FROM live_orders ORDER BY created_at DESC LIMIT 30")]
    return {"live": is_live(), "killed": killed(), "limits": limits(), "day": st, "positions": positions(conn), "pending": pend, "recent": recent}
