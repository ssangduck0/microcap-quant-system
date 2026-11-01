"""🛰 스캐너 1단계 빠른 모드(2026-11-01): 전 종목 '오늘 값'은 야후 일괄 시세(400종목씩), '어제까지'는 하루 한 번 받아 둔 일봉(스캐너 메모리).

왜: 서버에서 1단계(3,300종목 2개월 일봉, 100종목씩 34번)가 약 9분 → 한 주기 약 12분. 야후가 서버 IP 의 연속 요청량을 조절하는 것으로 보임
  (PC 는 3분 · 서버 150종목 동시 4개 30초 / 16개 26초 · CPU 3~6초뿐). 10/30 비교: 1단계 통과 797 vs 796(겹침 99.9%) ·
  정밀 분석 상위 100 중 98개 같음 · 가격 차이 중앙 0.000%.
어떻게:
  - 지난 일봉 = 메모리(CACHE). 재시작 때와 매 거래일 동부 STAGE1_SETTLE_HOUR_ET 시 뒤 첫 사이클에 전 종목을 지금 방식으로 다시 받음.
    DB(daily_prices)에는 지금처럼 최근 3일만 저장 — 2개월치를 전 종목 덮어쓰면 야후가 아직 환산 안 한 병합 전 봉이 🩹 pricefix 수리를 되돌릴 수 있어서.
  - 오늘 봉 = 일괄 시세(시가·고가·저가·현재가·거래량)를 지난 일봉 뒤에 붙임 → 지금과 같은 모양의 일봉 dict →
    1단계 거르기와 하류(🩳 공매도 흐름 · 📈 분산·털기 · 🕶 다크풀 · 📐 차트 관점 · 급상승 후보 · 최근 3일 저장)가 그대로.
  - 시세의 전일 종가 ≠ 저장 어제 종가(±STAGE1_SPLIT_TOL↑ — 병합 당일 등) · 새 종목 · 시세 없는 종목 → 그 종목만 야후 일봉(받으면 메모리도 갱신).
  - 정밀 분석 대상 중 오늘 봉이 시세에서 온 종목은 야후 일봉으로 다시 받아 2단계 계산은 지금과 똑같이(refresh).
  - 일괄 시세 실패·결과가 너무 적음 → 이번 사이클은 지금 방식(되돌림).
  - 점검: shadow 는 매 사이클, fast 는 하루 한 번(지난 일봉을 다시 받는 사이클) 두 방식의 1단계 결과를 비교해 stage1_runs 에 기록.
    fast 에서 겹침이 기준(STAGE1_CHECK_MIN_PASS·PICK) 아래면 텔레그램 + 다음 점검까지 지금 방식으로(+ 비교 기록).
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import config
import db
import market

log = logging.getLogger("stage1fast")
ET = ZoneInfo("America/New_York")
COLS = ["Open", "High", "Low", "Close", "Volume"]
MIN_QUOTE_SHARE = 0.8   # 일괄 시세가 지난 일봉 종목의 이 비율도 안 오면 이번 사이클은 지금 방식으로
MIN_FULL_SHARE = 0.5    # 전체 받기 결과가 전체 종목의 이 비율 미만이면 메모리로 쓰지 않음(다음 사이클에 다시)
MODES = ("full", "shadow", "fast")


def last_settle(now: datetime | None = None) -> datetime:
    """now 이전 가장 최근 '평일 동부 STAGE1_SETTLE_HOUR_ET 시' — 그날 일봉이 마감값으로 굳은 시각(공휴일은 한 번 더 받을 뿐 해 없음)."""
    n = (now or datetime.now(timezone.utc)).astimezone(ET)
    t = n.replace(hour=int(config.STAGE1_SETTLE_HOUR_ET), minute=0, second=0, microsecond=0)
    if t > n:
        t -= timedelta(days=1)
    while t.weekday() >= 5:
        t -= timedelta(days=1)
    return t


def _norm(d: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 날짜(시간대 없음) 인덱스 + 다섯 칸."""
    d = d[[c for c in COLS if c in d.columns]].dropna(subset=["Close"]).copy()
    idx = pd.DatetimeIndex(d.index)
    if idx.tz is not None:
        idx = idx.tz_convert(ET).tz_localize(None)
    d.index = idx.normalize()
    return d


class Cache:
    """지난 일봉(메모리). frames: 종목 → 일봉 · dead: 다시 받아 봐도 일봉이 없던 종목(다음 전체 받기 때까지 건너뜀)."""

    def __init__(self):
        self.frames: dict[str, pd.DataFrame] = {}
        self.dead: set[str] = set()
        self.fetched_at: datetime | None = None

    def due(self, now: datetime | None = None) -> bool:
        return not self.frames or self.fetched_at is None or self.fetched_at < last_settle(now)

    def settled_day(self):
        """메모리 일봉이 마감값으로 굳어 있는 마지막 거래일."""
        return last_settle(self.fetched_at).date() if self.fetched_at else None

    def set(self, daily: dict, now: datetime | None = None) -> bool:
        frames = {t: _norm(d) for t, d in (daily or {}).items() if d is not None and not getattr(d, "empty", True)}
        if not frames:
            return False
        self.frames, self.dead, self.fetched_at = frames, set(), now or datetime.now(timezone.utc)
        return True

    def put(self, daily: dict) -> None:
        for t, d in (daily or {}).items():
            if d is not None and not getattr(d, "empty", True):
                self.frames[t] = _norm(d)
                self.dead.discard(t)


CACHE = Cache()


def quote_bar(x: dict | None):
    """일괄 시세 한 종목 → (거래일, 오늘 봉 dict). 값이 없으면 None."""
    try:
        px, ts = float(x["regularMarketPrice"]), int(x["regularMarketTime"])
    except (KeyError, TypeError, ValueError):
        return None
    if px <= 0:
        return None

    def f(k):
        try:
            return float(x[k]) if x.get(k) not in (None, "") else None
        except (TypeError, ValueError):
            return None
    hi, lo, op, vol = f("regularMarketDayHigh"), f("regularMarketDayLow"), f("regularMarketOpen"), f("regularMarketVolume")
    day = pd.Timestamp(market.et_trade_date(pd.Timestamp(ts, unit="s", tz="UTC")))
    return day, {"Open": op or px, "High": max(hi or px, px), "Low": min(lo or px, px), "Close": px, "Volume": vol or 0.0}


def build(tickers: list[str], quotes: dict, cache: Cache | None = None):
    """지난 일봉(메모리) + 일괄 시세 → 일봉 dict. 반환 (일봉, need=야후 일봉이 필요한 종목, mismatch=병합 의심, from_quote=오늘 봉이 시세인 종목)."""
    cache = cache or CACHE
    settled = cache.settled_day()
    out, need, mismatch, from_quote = {}, [], [], set()
    for t in tickers:
        h = cache.frames.get(t)
        qb = quote_bar(quotes.get(t)) if quotes.get(t) else None
        if h is None or h.empty:
            if t not in cache.dead and qb is not None:
                need.append(t)  # 새 종목·전체 받기 때 빠진 종목: 한 번 받아 보고 없으면 dead
            continue
        if qb is None:
            need.append(t)
            continue
        day, bar = qb
        last = h.index[-1]
        if day < last or (day == last and settled is not None and day.date() <= settled):
            out[t] = h  # 시세가 저장 일봉보다 새롭지 않음(장 시작 전·주말) → 마감값으로 굳은 저장 일봉 그대로
            continue
        prev = h[h.index < day]
        if prev.empty:
            need.append(t)
            continue
        c0 = float(prev["Close"].iloc[-1])
        try:
            pc = float(quotes[t].get("regularMarketPreviousClose") or 0)
        except (TypeError, ValueError):
            pc = 0.0
        if pc > 0 and c0 > 0 and abs(pc / c0 - 1) > float(config.STAGE1_SPLIT_TOL):
            mismatch.append(t)  # 병합 당일 등: 저장 일봉은 옛 단위 → 거래량 배수·낙폭이 틀어지므로 야후 일봉으로
            need.append(t)
            continue
        out[t] = pd.concat([prev, pd.DataFrame([bar], index=pd.DatetimeIndex([day]))])
        from_quote.add(t)
    return out, need, mismatch, from_quote


def mode_now(now: datetime | None = None) -> str:
    m = str(getattr(config, "STAGE1_MODE", "full") or "full").lower()
    m = m if m in MODES else "full"
    if m == "fast" and blocked(now):
        return "shadow"  # 매일 점검 실패 뒤 다음 점검까지: 지금 방식으로 돌리며 비교만
    return m


def blocked(now: datetime | None = None) -> bool:
    try:
        m = db.get_meta("stage1_block")
        until = json.loads(m["value"]).get("until") if m and m.get("value") else None
        return bool(until) and (now or datetime.now(timezone.utc)) < datetime.fromisoformat(until)
    except Exception:  # noqa: BLE001
        return False


def daily_for(tickers: list[str], now: datetime | None = None, download=None, quotes_fn=None) -> tuple[dict, dict]:
    """1단계 일봉 dict(지금 방식과 같은 모양)와 정보.
    정보: mode(설정) · used(full/refresh/fast/fallback) · sec · quotes · need · mismatch · from_quote · fast(비교용 빠른 모드 일봉) · kind(shadow/daily)."""
    download = download or (lambda tk: market.download_daily(tk, period="2mo", chunk=config.DAILY_CHUNK))
    quotes_fn = quotes_fn or market.bulk_quotes
    mode = mode_now(now)
    t0 = time.time()
    s1: dict = {"mode": mode, "n": len(tickers), "quotes": None, "need": 0, "mismatch": 0, "from_quote": set(), "fast": None, "kind": None}
    if mode == "full":
        daily = download(tickers)
        s1.update(used="full", sec=time.time() - t0)
        return daily, s1

    def fast_from(cache: Cache, base: dict):
        """비교용: base(지금 방식 일봉)와 같은 조건의 빠른 모드 일봉 — 야후 일봉이 필요한 종목은 base 값을 씀(빠른 모드에서도 받으니까)."""
        q = quotes_fn(tickers)
        s1["quotes"] = len(q)
        if len(q) < MIN_QUOTE_SHARE * max(1, len([t for t in tickers if t in cache.frames])):
            return None
        fd, need, mis, _ = build(tickers, q, cache)
        fd.update({t: base[t] for t in need if t in base})
        s1["need"], s1["mismatch"] = len(need), len(mis)
        return fd

    due = CACHE.due(now)
    if mode == "shadow" or due:
        daily = download(tickers)
        try:
            if due and CACHE.frames:
                s1["fast"], s1["kind"] = fast_from(CACHE, daily), "daily"  # 매일 점검: 어제 받아 둔 일봉 + 지금 시세 vs 방금 받은 일봉
            elif not due:
                s1["fast"], s1["kind"] = fast_from(CACHE, daily), "shadow"
        except Exception:  # noqa: BLE001
            log.exception("1단계 빠른 모드 비교 실패")
        if s1["fast"] is None:
            s1["kind"] = None
        if due and len(daily) >= MIN_FULL_SHARE * len(tickers):
            CACHE.set(daily, now)
        s1.update(used="refresh" if mode == "fast" else "full", sec=time.time() - t0)
        return daily, s1

    q = quotes_fn(tickers)
    s1["quotes"] = len(q)
    if len(q) < MIN_QUOTE_SHARE * max(1, len([t for t in tickers if t in CACHE.frames])):
        log.warning("야후 일괄 시세가 적음(%d/%d) → 이번 사이클은 지금 방식", len(q), len(tickers))
        daily = download(tickers)
        s1.update(used="fallback", sec=time.time() - t0)
        return daily, s1
    daily, need, mis, fq = build(tickers, q, CACHE)
    if need:
        got = download(need)
        daily.update(got)
        CACHE.put(got)
        CACHE.dead |= set(need) - set(got)
    s1.update(used="fast", need=len(need), mismatch=len(mis), from_quote=fq, sec=time.time() - t0)
    return daily, s1


def refresh(daily: dict, picked: list[str], s1: dict, download=None) -> int:
    """빠른 모드: 정밀 분석 대상 중 오늘 봉이 시세에서 온 종목을 야후 일봉으로 다시 받아 2단계는 지금과 같은 일봉으로. 받은 수."""
    if s1.get("used") != "fast":
        return 0
    want = [t for t in picked if t in s1.get("from_quote", ())]
    if not want:
        return 0
    download = download or (lambda tk: market.download_daily(tk, period="2mo", chunk=config.DAILY_CHUNK))
    t0 = time.time()
    got = download(want)
    daily.update(got)
    CACHE.put(got)
    s1["refresh"], s1["sec"] = len(got), s1.get("sec", 0) + time.time() - t0
    return len(got)


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS stage1_runs (
        at TEXT, mode TEXT, used TEXT, sec REAL, n INTEGER, quotes INTEGER, need INTEGER, mismatch INTEGER, refresh INTEGER,
        kind TEXT, pass_full INTEGER, pass_fast INTEGER, pass_overlap REAL, pick_full INTEGER, pick_overlap REAL)""")


def check_failed(cmp: dict | None) -> bool:
    return bool(cmp) and (cmp["pass_overlap"] < float(config.STAGE1_CHECK_MIN_PASS) or cmp["pick_overlap"] < float(config.STAGE1_CHECK_MIN_PICK))


def record(s1: dict, cmp: dict | None = None, now: datetime | None = None, send=None) -> None:
    """사이클 기록(stage1_runs) + fast 모드 매일 점검이 기준 아래면 텔레그램·다음 점검까지 지금 방식으로."""
    now = now or datetime.now(timezone.utc)
    cmp = cmp or {}
    try:
        with closing(db.connect()) as conn:
            ensure(conn)
            conn.execute("INSERT INTO stage1_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                now.isoformat(timespec="seconds"), s1.get("mode"), s1.get("used"), round(float(s1.get("sec") or 0), 1), s1.get("n"),
                s1.get("quotes"), s1.get("need"), s1.get("mismatch"), s1.get("refresh"), s1.get("kind") if cmp else None,
                cmp.get("pass_full"), cmp.get("pass_fast"), cmp.get("pass_overlap"), cmp.get("pick_full"), cmp.get("pick_overlap")))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("1단계 기록 실패: %s", e)
    if s1.get("kind") == "daily" and str(getattr(config, "STAGE1_MODE", "")).lower() == "fast" and check_failed(cmp):
        until = (last_settle(now) + timedelta(days=1, minutes=1)).astimezone(timezone.utc)
        while until.astimezone(ET).weekday() >= 5:
            until += timedelta(days=1)
        try:
            db.set_meta("stage1_block", json.dumps({"until": until.isoformat(timespec="seconds"), "at": now.isoformat(timespec="seconds"),
                                                    "pass": cmp["pass_overlap"], "pick": cmp["pick_overlap"]}))
        except Exception as e:  # noqa: BLE001
            log.warning("1단계 멈춤 기록 실패: %s", e)
        text = (f"🛰 스캐너 1단계 빠른 모드 점검 실패 — 1단계 통과 겹침 {cmp['pass_overlap']:.1f}% · 정밀 분석 대상 겹침 {cmp['pick_overlap']:.1f}% "
                f"(기준 {config.STAGE1_CHECK_MIN_PASS:g}% · {config.STAGE1_CHECK_MIN_PICK:g}%)\n다음 점검(동부 {config.STAGE1_SETTLE_HOUR_ET}시)까지 지금 방식으로 돌립니다.")
        log.warning(text)
        try:
            if send is None:
                import notify
                send = notify.send_telegram
            send(text)
        except Exception:  # noqa: BLE001
            pass


def label(s1: dict, cmp: dict | None = None) -> str:
    """로그 한 줄."""
    used = {"full": "지금 방식", "refresh": "지난 일봉 다시 받기", "fast": "빠른 모드", "fallback": "되돌림(지금 방식)"}.get(s1.get("used"), s1.get("used"))
    s = f"1단계 일봉: {used}(설정 {s1.get('mode')}) {float(s1.get('sec') or 0):.0f}초"
    if s1.get("quotes") is not None:
        s += f" · 일괄 시세 {s1['quotes']} · 야후 일봉 {s1.get('need') or 0}(병합 의심 {s1.get('mismatch') or 0}) · 대상 다시 받기 {s1.get('refresh') or 0}"
    if cmp:
        s += (f" · 비교({s1.get('kind')}): 통과 {cmp['pass_full']} vs {cmp['pass_fast']} 겹침 {cmp['pass_overlap']:.1f}% · "
              f"정밀 분석 대상 겹침 {cmp['pick_overlap']:.1f}%")
    return s
