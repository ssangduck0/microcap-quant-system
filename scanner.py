"""스캐너: 일정 주기로 종목을 훑어 SQLite 에 누적합니다.

  python scanner.py          # 계속 실행
  python scanner.py --once   # 한 사이클만 실행(테스트용)

저장 방식
  daily_snapshots : (거래일, 티커)당 1행. 같은 날 여러 번 포착되면 최신값으로 갱신 -> 중복이 쌓이지 않음
  signals         : 처음 포착 / 희석 상태 변경 / 직전 신호 대비 +-5% 이상 변동 때만 기록하는 이벤트 로그
  daily_prices    : 감시 종목의 일봉을 계속 누적 (통계·백테스트용)
"""
from __future__ import annotations

import argparse
import json
import os
import logging
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import quiet  # noqa: F401  (Streamlit 경고 줄이 로그에 쌓이지 않게 — 가장 먼저)
import afterscalp
import closewatch
import config
import macro
import insider
import secfeed
import regsho
import tosslink
import flowread
import pumpsetup
import shortflow
import papertrade
import piggy
import forensic
import intel
import shortdata
import db
import fintel
import halts
import market
import notify
import scoring
import sec
import toss
import tossws
import universe
import winmodel

log = logging.getLogger("scanner")


def get_fundamentals(conn, ticker: str, budget: dict) -> dict:
    cached = db.get_fundamentals(conn, ticker)
    if cached and db.is_fresh(cached["updated_at"], config.FUNDAMENTALS_REFRESH_HOURS):
        return cached
    if budget["fund"] <= 0:
        return cached or {}  # 이번 사이클 조회 한도 초과: 다음 사이클에 채워짐
    budget["fund"] -= 1
    fresh = market.fetch_fundamentals(ticker)
    if fresh:
        db.save_fundamentals(conn, ticker, fresh)
        return fresh
    return cached or {}


def dilution_for(conn, client: sec.SecClient, ticker: str, budget: dict):
    """캐시가 신선하면 그대로, 아니면 한도 안에서만 새로 검사. 한도 초과 + 기록 없음이면 None(다음 사이클로)."""
    row = db.get_dilution(conn, ticker)
    if row:
        limit = config.DILUTION_RETRY_HOURS if row["status"] == "UNKNOWN" else config.DILUTION_REFRESH_HOURS
        if db.is_fresh(row["checked_at"], limit):
            return row
    if budget["sec"] <= 0:
        return row  # 오래된 기록이라도 있으면 사용, 없으면 None
    budget["sec"] -= 1
    return sec.get_dilution(conn, client, ticker, config.DILUTION_REFRESH_HOURS, config.DILUTION_RETRY_HOURS)


def fetch_shares(tc, symbols: list[str]) -> dict[str, float]:
    return {x["symbol"]: float(x["sharesOutstanding"]) for x in tc.stocks(symbols) if x.get("sharesOutstanding")}


def market_down_frac(bars: list[tuple[str, float | None]], min_tickers: int = 500) -> float | None:
    """bars: (마지막 봉 날짜, 전일 대비 등락률%). 가장 많은 종목이 공유하는 날짜 기준으로 -10% 이하 비율을 계산. 표본이 작으면 None."""
    from collections import Counter
    cnt = Counter(d for d, _ in bars)
    if not cnt:
        return None
    day, n = cnt.most_common(1)[0]
    if n < min_tickers:
        return None
    return sum(1 for d, c in bars if d == day and c is not None and c <= -10.0) / n


def stage1(all_tickers: list[str], priority: set[str], tc=None, manual: frozenset | set = frozenset()):
    """1단계: 전체 종목 일봉(싼 호출)으로 후보를 거른다. 반환: (후보 티커 순서 목록, 일봉 dict, 발행주식수 dict).

    시총 필터는 '거래량 급증 상위 N개'를 고르기 *전에* 적용한다 — 나중에 걸러내면 대형주가 차지한 자리만큼 초소형주가 밀려난다.
    """
    daily = market.download_daily(all_tickers, period="2mo", chunk=config.DAILY_CHUNK)
    prio, others, px, bars = [], [], {}, []
    for t, d in daily.items():
        q = market.quick_screen(d)
        if q is None:
            continue
        bars.append((q["last_date"], q["day_chg_pct"]))
        px[t] = q["price"]
        if t in priority:
            prio.append(t)
            continue
        if not (config.MIN_PRICE_USD <= q["price"] <= config.MAX_PRICE_USD):
            continue
        if q["avg_dollar_vol"] < config.MIN_AVG_DOLLAR_VOL:
            continue
        if q["drawdown_pct"] > config.MIN_DRAWDOWN_PCT + config.STAGE1_MARGIN_PCT:
            continue
        others.append((q["vol_mult"], t))

    shares: dict[str, float] = {}
    if tc is not None and config.MAX_MARKET_CAP_USD:
        try:
            shares = fetch_shares(tc, prio + [t for _, t in others])
        except Exception as e:  # noqa: BLE001
            log.warning("토스 종목 정보 조회 실패(1단계 시총 필터 건너뜀): %s", e)
        small = lambda t: t not in shares or shares[t] * px[t] <= config.MAX_MARKET_CAP_USD  # noqa: E731
        n0 = len(prio) + len(others)
        prio = [t for t in prio if t in manual or small(t)]
        others = [(v, t) for v, t in others if small(t)]
        if n0 - len(prio) - len(others):
            log.info("1단계 시총 필터(>$%sM)로 제외: %d개", f"{config.MAX_MARKET_CAP_USD / 1e6:,.0f}", n0 - len(prio) - len(others))

    # 시장 전체 스트레스: 가장 최근 거래일 기준 전체 종목 중 -10% 이하로 빠진 종목의 비율 (모델 입력, 과거 사건 쪽과 같은 정의)
    mkt = market_down_frac(bars)

    others.sort(reverse=True)  # 오늘 거래량이 평소 대비 많이 늘어난 순
    picked = prio + [t for _, t in others[:config.MAX_CANDIDATES]]
    beat("정밀 분석 중")
    log.info("1단계: 일봉 확보 %d/%d → 필터 통과 %d → 정밀 분석 대상 %d (우선종목 %d)",
             len(daily), len(all_tickers), len(others), len(picked), len(prio))
    return picked, daily, shares, mkt


def signal_reason(prev_signal, snap_exists: bool, price: float, status: str) -> str | None:
    if not snap_exists and prev_signal is None:
        return "최초 포착"
    if not snap_exists:
        return "신규 거래일 포착"
    if prev_signal is None:
        return "최초 포착"
    if prev_signal["dilution_status"] != status:
        return f"희석 상태 변경 {prev_signal['dilution_status']}→{status}"
    if prev_signal["price"] and abs(price / prev_signal["price"] - 1) * 100 >= config.SIGNAL_MIN_MOVE_PCT:
        return "가격 변동"
    return None


def is_regular_session(now: datetime | None = None) -> bool:
    """미국 정규장(동부시간 09:30~16:00, 평일)인지. 점수는 학습 데이터와 같은 조건(정규장 값)일 때만 기록한다."""
    now = now or datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0)


def refresh_meta(tc) -> None:
    """환율과 미국장 세션을 DB에 기록 (대시보드가 읽음 — 토큰 충돌을 피하려고 대시보드는 토스를 직접 호출하지 않는다)."""
    try:
        db.set_meta("usdkrw", f"{tc.exchange_rate():.4f}")
    except Exception as e:  # noqa: BLE001
        log.warning("토스 환율 조회 실패: %s", e)
    try:
        cal = tc.us_calendar()
        db.set_meta("us_session", toss.us_session(cal))
        end = toss.regular_end(cal)
        if end:
            db.set_meta("us_regular_end", end.isoformat())  # 장마감 체크리스트 '마감 1시간 전' 기준(조기 폐장 반영)
        now_ = datetime.now(timezone.utc)
        for key in ("previousBusinessDay", "today", "nextBusinessDay"):  # 애프터마켓 시작·종료(애프터 스캘핑 매도 마감 계산, 조기 폐장 반영)
            am = (cal.get(key) or {}).get("afterMarket") or {}
            if am.get("startTime") and am.get("endTime") and datetime.fromisoformat(am["endTime"]) > now_:
                db.set_meta("us_after_start", am["startTime"])
                db.set_meta("us_after_end", am["endTime"])
                break
    except Exception as e:  # noqa: BLE001
        log.warning("토스 장 캘린더 조회 실패: %s", e)


def get_intraday(cands: list[str], tc):
    """반환: (분봉 dict, 종목별 하루 누적 거래량 dict 또는 None).

    가격·봉(낙폭, 매수체결 비중)은 토스 우선, 없으면 yfinance. 거래량은 기본(VOLUME_SOURCE=yahoo)에서 yfinance 1분봉 합을 쓴다 —
    분모가 yfinance 일봉 평균이라 같은 출처여야 배수가 왜곡되지 않는다.
    """
    use_yahoo_volume = tc is None or config.VOLUME_SOURCE != "toss"
    toss_frames = toss.fetch_intraday_many(tc, cands) if (tc is not None and cands) else {}
    need = cands if use_yahoo_volume else [t for t in cands if t not in toss_frames]
    yf_frames = market.download_intraday(need) if need else {}
    intra = dict(toss_frames)
    for t, f in yf_frames.items():
        intra.setdefault(t, f)
    vols = {t: float(f["Volume"].fillna(0).sum()) for t, f in yf_frames.items()} if use_yahoo_volume else None
    log.info("1분봉: 토스 %d / yfinance %d / 없음 %d · 거래량 출처 %s", len(toss_frames), len(yf_frames),
             len([t for t in cands if t not in intra]), "yfinance" if use_yahoo_volume else "토스(분봉 합)")
    return intra, vols, toss_frames


def filter_by_market_cap(tc, passing: list, keep: set, known_shares: dict | None = None) -> tuple[list, list]:
    """토스 발행주식수 x 현재가(실시간)로 시총을 근사해 초소형주가 아닌 종목을 SEC 검사 전에 제외(1단계 필터의 안전망).
    manual_tickers.txt 종목은 항상 유지."""
    try:
        shares = dict(known_shares or {})
        missing = [t for t, _ in passing if t not in shares]
        if missing:
            shares.update(fetch_shares(tc, missing))
    except Exception as e:  # noqa: BLE001
        log.warning("토스 종목 정보 조회 실패(시총 필터 건너뜀): %s", e)
        return passing, []
    kept, cut = [], []
    for t, m in passing:
        sh = shares.get(t)
        if t in keep or sh is None or sh * m["price"] <= config.MAX_MARKET_CAP_USD:
            kept.append((t, m))
        else:
            cut.append((t, sh * m["price"]))
    return kept, cut


def after_scalp_cycle(conn, tc, frames0: dict) -> None:
    """🌙 애프터마켓 스캘핑(스승님 꿀팁): 실시간 거래량 상위(+급상승, 워치리스트·저금통) 종목의 오늘 분봉으로 판정 → 저장·진입 신호 알림·결과 추적·매도 마감 알림."""
    a_start = datetime.fromisoformat(db.get_meta("us_after_start")["value"])
    a_end = datetime.fromisoformat(db.get_meta("us_after_end")["value"])
    now = datetime.now(timezone.utc)
    if not (a_start <= now < a_end):
        return
    deadline = afterscalp.deadline_of(a_end)
    day = a_start.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    fx = float((db.get_meta("usdkrw") or {}).get("value") or 1350.0)
    rows, _ = closewatch.ranked_top(tc, "MARKET_TRADING_VOLUME", "realtime", config.AFTER_TOP_N)
    try:
        g, _ = closewatch.ranked_top(tc, "TOP_GAINERS", "1d", 20)
        rows += g
    except Exception:  # noqa: BLE001  (순위 종류가 없으면 거래량 상위만)
        pass
    syms = list(dict.fromkeys([r["ticker"] for r in rows] + universe.from_watchlist()))
    afterscalp.ensure_tables(conn)
    today_sig = [dict(r) for r in conn.execute("SELECT ticker, at, price FROM after_signals WHERE date=?", (day,))]
    need = [t for t in dict.fromkeys(syms + [x["ticker"] for x in today_sig]) if t not in frames0]
    frames = {**frames0, **toss.fetch_intraday_many(tc, need, deadline_sec=90)}
    n_in = 0
    kst = deadline.astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M")
    for t in syms:
        df = frames.get(t)
        r = afterscalp.analyze(df, a_start, now, fx)
        if not r:
            continue
        afterscalp.save_state(conn, day, t, {**r, "chart": afterscalp.chart_series(df)})
        if r["stage"] == afterscalp.STAGE_IN:
            n_in += 1
            if now < deadline and afterscalp.record_signal(conn, day, t, now, r["price"]):
                try:  # 🧪 가상매매 '애프터 스캘핑' 전략: 진입 신호 가격으로 가상 매수
                    papertrade.open_after(conn, day, t, r["price"], now)
                except Exception as e:  # noqa: BLE001
                    log.warning("가상매매 애프터 매수 실패: %s", e)
            if now < deadline and config.AFTER_ALERTS and conn.execute("SELECT 1 FROM after_signals WHERE date=? AND ticker=? AND at=?", (day, t, now.isoformat())).fetchone():
                pl = r["plan"]
                notify.send_telegram(f"🌙 {t} 애프터 진입 구간 ${r['price']:.4f}\n목표 +5% ${pl['target']:.4f} · +7% ${pl['target7']:.4f} · 손절 -5% ${pl['stop']:.4f}\n"
                                     f"매도 마감 {kst} KST · 거래대금 {r['value_krw'] / 1e8:,.0f}억 원 · 급등 +{r['spike_pct']:.0f}% (스승님 꿀팁: 애프터 스캘핑)")
    for sgl in today_sig + [dict(r) for r in conn.execute("SELECT ticker, at, price FROM after_signals WHERE date=? AND max_up IS NULL", (day,))]:
        oc = afterscalp.outcome(frames.get(sgl["ticker"]), datetime.fromisoformat(sgl["at"]), sgl["price"], deadline)
        afterscalp.update_outcome(conn, day, sgl["ticker"], oc)
    remind = db.get_meta("after_deadline_reminded")
    if config.AFTER_ALERTS and deadline - timedelta(minutes=5) <= now < a_end and (remind or {}).get("value") != day and today_sig:
        notify.send_telegram(f"⏰ 애프터 매도 마감 {kst} KST 입니다. 오늘 진입 신호 {len(today_sig)}종목 — 보유 중이면 정리하세요(스승님 꿀팁).")
        db.set_meta("after_deadline_reminded", day)
    try:  # 🧪 가상매매: 애프터 분봉으로 열린 포지션 판정(매도 마감이 지나면 마감 가격으로 정리)
        papertrade.live_check(conn, frames, now)
    except Exception as e:  # noqa: BLE001
        log.warning("가상매매 애프터 판정 실패: %s", e)
    log.info("애프터 스캘핑: %d종목 판정 · 진입 구간 %d · 매도 마감 %s KST", len(syms), n_in, kst)


def run_cycle(conn, client: sec.SecClient, tc=None, collector=None, fintel_client=None) -> int:
    config.apply_overrides()  # ⚙️ 관리 모드에서 바꾼 설정을 이번 사이클부터
    if tc is not None:
        refresh_meta(tc)
    all_tickers, priority = universe.get_universe(tc)
    log.info("전체 감시 대상 %d개 (모드: %s, 우선종목 %d)", len(all_tickers), config.SCAN_UNIVERSE, len(priority))
    if tc is not None:
        try:  # 🪪 토스 거래 가능 종목 목록(하루 1회): 다크풀·Reg SHO·스퀴즈 표에서 ETF·상폐·미지원 종목을 거르는 기준
            import tradable
            n_ta = tradable.refresh_daily(conn, tc, out=log.warning)
            if n_ta:
                log.info("토스 종목 목록 저장: %d건", n_ta)
        except Exception as e:  # noqa: BLE001
            log.warning("토스 종목 목록 저장 실패: %s", e)
    manual = set(universe.from_manual())
    model = winmodel.load_model()
    regular = is_regular_session()
    if model is None:
        log.info("승률 점수 모델 없음(`python winmodel.py fit` 으로 학습하면 점수가 기록됩니다)")
    cands, daily, shares0, mkt_frac = stage1(all_tickers, priority, tc, manual)
    try:  # 전 종목 최근 3일 일봉 저장(2026-10-27): 후보가 아닌 종목도 어제 거래량이 마감값으로 — 🕶 다크풀 비중·거래량 배수가 정확해짐
        n_bars = db.upsert_recent_bars(conn, daily, n=3)
        log.info("최근 3일 일봉 저장: %d행", n_bars)
    except Exception as e:  # noqa: BLE001
        log.warning("최근 일봉 저장 실패: %s", e)
    intra, vols, toss_frames = get_intraday(cands, tc)
    try:  # 🌙 세션별(데이마켓·프리·정규·애프터) 고점 기록 — 일봉 고가는 정규장만이라 시간외 급등이 빠지던 문제
        import exthilo
        exthilo.record(conn, intra)
    except Exception as e:  # noqa: BLE001
        log.warning("세션별 고점 기록 실패: %s", e)
    try:  # 🧪 가상매매: 열린 포지션을 1분봉(모든 세션)으로 익절·손절 중 먼저 닿은 쪽 판정
        n_pt = papertrade.live_check(conn, {**intra, **toss_frames})
        if n_pt:
            log.info("가상매매 실시간 청산: %d건", n_pt)
    except Exception as e:  # noqa: BLE001
        log.warning("가상매매 실시간 판정 실패: %s", e)
    try:  # 📐 스승 관점(2026-10-27): CHART_SCAN_MIN 분마다 보유·저금통 종목 5분봉을 받아 5분 5·20 꺾임·생명선/허리 이탈·눌림 타점을 보고 처음 난 것만 텔레그램
        import chartview
        _last = (db.get_meta("chart_live_at") or {}).get("value") or ""
        _due = not _last or (datetime.now(timezone.utc) - datetime.fromisoformat(_last)).total_seconds() >= config.CHART_SCAN_MIN * 60
        if _due:
            import piggy
            _watch = [t for t in dict.fromkeys(papertrade.open_tickers() + piggy.tickers_all()) if t in daily][:40]
            if _watch:
                _, _m5 = chartview.fetch_intraday(_watch, want60=False)
                _sent = chartview.live_check(conn, daily, _m5, _watch)
                if _sent:
                    log.info("차트 관점 알림 %d건", len(_sent))
            db.set_meta("chart_live_at", datetime.now(timezone.utc).isoformat())
    except Exception as e:  # noqa: BLE001
        log.warning("차트 관점 점검 실패: %s", e)
    if config.EXT_ALERTS:
        try:  # 🌙 관심 종목이 시간외에서 +N% 찍으면 텔레그램(급등의 약 40%가 프리·애프터에서만 나옴)
            import extalert
            sent_ext = extalert.check(conn, intra, config.EXT_ALERT_PCT)
            if sent_ext:
                log.info("시간외 급등 알림: %s", ", ".join(sent_ext))
        except Exception as e:  # noqa: BLE001
            log.warning("시간외 급등 알림 실패: %s", e)
    now = db.utcnow_iso()
    budget = {"fund": config.MAX_NEW_FUNDAMENTALS_PER_CYCLE, "sec": config.MAX_SEC_CHECKS_PER_CYCLE}
    saved = deferred = 0
    saved_tickers: list[str] = []

    passing = []  # 낙폭 조건을 통과한 종목 (가격 기반의 싼 계산만 한 상태)
    for ticker in cands:
        try:
            d = daily[ticker]
            db.upsert_daily_prices(conn, ticker, d)
            if vols is None:
                dv = market.AUTO
            elif ticker in vols:
                dv = vols[ticker]
            elif ticker in intra:
                dv = None  # 가격 봉은 있는데 기준 거래량 출처가 없음 -> 배수를 틀리게 계산하지 않고 '확인 불가'로 둔다
            else:
                dv = market.AUTO
            m = market.compute_metrics(d, intra.get(ticker), dv)
            if m is not None and m["drawdown_pct"] <= config.MIN_DRAWDOWN_PCT:
                m["mkt_down_frac"] = mkt_frac
                passing.append((ticker, m))
        except Exception:  # noqa: BLE001
            log.exception("%s 처리 실패", ticker)

    if tc is not None and config.MAX_MARKET_CAP_USD and passing:
        passing, cut = filter_by_market_cap(tc, passing, manual, shares0)
        if cut:
            eg = ", ".join(f"{t} ${c / 1e6:,.0f}M" for t, c in sorted(cut, key=lambda x: -x[1])[:5])
            log.info("시총 필터(>$%sM)로 제외: %d개 (예: %s)", f"{config.MAX_MARKET_CAP_USD / 1e6:,.0f}", len(cut), eg)

    for ticker, m in passing:
        try:
            dil = dilution_for(conn, client, ticker, budget)
            if dil is None:
                deferred += 1  # SEC 검사 한도 초과: 검사 없이 '희석 없음'으로 기록하지 않고 다음 사이클로 미룸
                continue
            fund = get_fundamentals(conn, ticker, budget)
            status, flags = dil["status"], dil.get("flags", {})
            fs = fund.get("float_shares")

            q_score, q_detail = scoring.quant_score(m, fs, status, flags)
            p_score, p_detail, excluded = scoring.pump_checklist(m, fs, status, flags)
            entry, stop, target = scoring.reference_levels(m["price"], m["atr14"])

            win_p, win_score = winmodel.score_one(model, m, status) if regular else (None, None)
            existing = db.get_snapshot(conn, m["trade_date"], ticker)
            prev_sig = db.last_signal(conn, ticker)
            db.upsert_snapshot(conn, {
                "date": m["trade_date"], "ticker": ticker, "exchange": fund.get("exchange"),
                "first_seen": existing["first_seen"] if existing else now, "last_seen": now,
                "price": m["price"], "high_20d": m["high_20d"], "low_20d": m["low_20d"],
                "drawdown_pct": m["drawdown_pct"], "day_change_pct": m["day_change_pct"], "pre_dd_pct": m["pre_dd_pct"],
                "avg_dollar_vol": m["avg_dollar_vol"], "volume_mult": m["volume_mult"],
                "gap_pct": m["gap_pct"], "close_loc": m["close_loc"], "range_pct": m["range_pct"],
                "prior_range_pct": m["prior_range_pct"], "mkt_down_frac": m["mkt_down_frac"],
                "buy_pressure": m["buy_pressure"], "float_shares": fs, "atr14": m["atr14"],
                "entry_ref": entry, "stop_ref": stop, "target_ref": target,
                "quant_score": q_score, "quant_detail": _json(q_detail),
                "pump_score": p_score, "pump_detail": _json(p_detail),
                "dilution_status": status, "excluded": int(excluded),
                "win_p": win_p, "win_score": win_score, "win_model": model["name"] if win_score is not None else None,
            })
            saved += 1
            saved_tickers.append(ticker)

            reason = signal_reason(prev_sig, existing is not None, m["price"], status)
            if reason:
                db.insert_signal(conn, {"date": m["trade_date"], "ticker": ticker, "price": m["price"],
                                        "drawdown_pct": m["drawdown_pct"], "quant_score": q_score,
                                        "pump_score": p_score, "dilution_status": status, "reason": reason})
                if not excluded and p_score >= config.ALERT_MIN_PUMP_SCORE:
                    notify.send_telegram(
                        f"[{ticker}] 펌핑점수 {p_score} | 낙폭 {m['drawdown_pct']:.1f}% | "
                        f"{scoring.STATUS_LABEL.get(status, status)} | {reason}")
            why = f" ({dil.get('error')})" if status == "UNKNOWN" and dil.get("error") else ""
            log.info("%s 낙폭 %.1f%% 퀀트 %.1f 펌핑 %s 희석=%s%s%s", ticker, m["drawdown_pct"], q_score,
                     "제외" if excluded else p_score, status, why,
                     f" 종합 {win_score:.0f}(확률 {win_p * 100:.0f}%)" if win_score is not None else "")
        except Exception:  # noqa: BLE001
            log.exception("%s 처리 실패", ticker)  # 조용히 삼키지 않고 원인을 남긴다
    if deferred:
        log.info("SEC 검사 한도로 다음 사이클로 미룬 종목: %d개", deferred)
    # ---- 공통 인텔(체결강도·거래정지·공매도·SEC 장중 공시): 이번 사이클에 저장한 모든 종목. 장마감 후보가 앞쪽 ----
    # 장마감 체크리스트 대상: 토스 급하락 순위 1~N위(정규장 중 매 사이클 '현재 순위' 기록) → 마감 M분 전이 지난 첫 사이클에 그날 대상으로 고정
    short: list[str] = []
    focus: list[str] = []
    if tc is not None and regular:
        try:
            now_utc = closewatch._now()
            today_et = now_utc.astimezone(closewatch.ET).date()
            live, n_ex = closewatch.losers_top(tc, config.CLOSE_WATCH_TOP_N)
            if live:
                closewatch.save_list(conn, today_et.isoformat(), "live", live, now_utc)
            frozen = closewatch.load_list(conn, today_et.isoformat(), "frozen")
            end = closewatch.regular_end_for(today_et)
            if not frozen and live and closewatch.freeze_due(now_utc, end, config.CLOSE_WATCH_FREEZE_MIN):
                closewatch.save_list(conn, today_et.isoformat(), "frozen", live, now_utc)
                frozen = live
                log.info("장마감 체크리스트 대상 고정: 토스 급하락 1~%d위 → %d종목 (ETF·워런트 등 %d개 제외) · 정규장 마감 %s ET 의 %d분 전",
                         config.CLOSE_WATCH_TOP_N, len(live), n_ex, end.astimezone(closewatch.ET).strftime("%H:%M"), config.CLOSE_WATCH_FREEZE_MIN)
            short = [x["ticker"] for x in frozen]
            focus = short or [x["ticker"] for x in live]  # 고정 전에는 현재 순위 종목을 실시간 체결강도 구독 맨 앞에(고정 시점에 비교할 기록 확보)
        except Exception:  # noqa: BLE001
            log.exception("토스 급하락 순위 조회 실패")
    if tc is not None:
        try:  # 📈 급상승/급하락 100(B단계 2026-10-27): 토스 1일 순위를 사이클마다 저장(세션 상관없이)
            import mover
            _mv = mover.capture(conn, tc)
            log.info("급상승/급하락 순위 저장: 상승 %d · 하락 %d", _mv.get("up", 0), _mv.get("down", 0))
        except Exception as e:  # noqa: BLE001
            log.warning("급상승/급하락 순위 저장 실패: %s", e)
    dchg = {t: (m.get("day_change_pct") if m.get("day_change_pct") is not None else 0.0) for t, m in passing}
    try:  # P2: 🕶 다크풀 상위 15도 실시간 체결 구독(매매강도 카드가 쌓이게) — 장마감 후보 다음 순서
        import darkpool
        _dp_top = list(darkpool.top(conn, n=15)[1]["ticker"])
    except Exception:  # noqa: BLE001
        _dp_top = []
    order = list(dict.fromkeys(focus + _dp_top + sorted(saved_tickers, key=lambda t: dchg.get(t, 0.0))))
    if config.PIGGY_ALERTS:  # 🐷 저금통: 저점·고점·이탈 구간 진입 알림(같은 날 같은 구간은 한 번)
        try:
            pset = set(piggy.tickers())
            for msg in piggy.alerts({t: m["price"] for t, m in passing if t in pset and m.get("price")}):
                notify.send_telegram(msg)
                log.info("저금통 알림: %s", msg.splitlines()[0])
        except Exception as e:  # noqa: BLE001
            log.warning("저금통 알림 실패: %s", e)
    try:  # Cowork 자동 공시분석 결과(inbox) 가져오기
        fx = forensic.import_inbox()
        if fx.get("imported") and config.AI_AUTO_CHECK and os.environ.get("ANTHROPIC_API_KEY", "").strip():
            import aisummary
            for _t in fx["imported"]:
                try:
                    res = aisummary.cross_check(_t)
                    bad = aisummary.conflicts(res)
                    if bad or (res.get("일치율") or 100) < 60:
                        notify.send_telegram(f"🔀 {_t} 교차검증: 일치율 {res.get('일치율')}% · 어긋난 항목 {', '.join(x.get('이름', '') for x in bad) or '-'} — 원문 확인 필요")
                except Exception as e:  # noqa: BLE001
                    log.warning("%s 자동 교차검증 실패: %s", _t, e)
        if fx["imported"] or fx["errors"]:
            log.info("공시분석(Cowork) 자동 저장: %s · 실패: %s", ", ".join(fx["imported"]) or "-", ", ".join(t for t, _ in fx["errors"]) or "-")
    except Exception as e:  # noqa: BLE001
        log.warning("공시분석 inbox 가져오기 실패: %s", e)
    if collector is not None:
        collector.set_symbols(order)  # 체결강도는 모든 세션에서 수집(토스 실시간은 프리·정규·애프터·데이마켓 제공). 최대 50종목, 앞쪽 우선
    halts_list = None
    if config.HALTS_ENABLED:
        try:
            halts_list = halts.fetch()
        except Exception as e:  # noqa: BLE001
            log.warning("거래정지(업킷·나스닥) 조회 실패: %s", e)
    imap: dict = {}
    if order:
        try:
            frames = {t: f for t, f in intra.items()}
            frames.update(toss_frames)  # 토스 1분봉 우선
            imap = intel.compute(conn, client, order, frames=frames, halts_list=halts_list, fintel_client=fintel_client,
                                 sec_budget=config.INTEL_SEC_MAX_PER_CYCLE, fintel_budget=config.INTEL_FINTEL_MAX_PER_CYCLE)
            log.info("공통 인텔(체결강도·거래정지·공매도·장중 공시) 갱신: %d종목 · 실시간 체결강도 %s · 거래정지 출처 %s", len(imap),
                     "연결됨" if collector is not None and collector.connected else "꺼짐/끊김(1분봉 추정)", halts.last_source or "-")
        except Exception:  # noqa: BLE001
            log.exception("공통 인텔 갱신 실패")
    try:  # 🩳 공매도 흐름(스승님 꿀팁): 워치리스트·저금통 종목이 ②③④ 단계에 처음 들어가면 기록·알림
        watched = list(dict.fromkeys(universe.from_watchlist()))
        mmap = {t: m for t, m in passing}
        day = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        for t in watched:
            r = shortflow.analyze(daily.get(t), live=mmap.get(t), short=(imap.get(t) or {}).get("short"))
            if r and r["stage"] in shortflow.ALERT_STAGES and shortflow.record(conn, t, day, r["stage"], r["price"]):
                log.info("공매도 흐름 신호: %s %s", t, r["stage"])
                if config.SHORTFLOW_ALERTS:
                    notify.send_telegram(f"🩳 {t} {r['stage']}\n현재 ${r['price']:.4f} · 반복 {r['cycles']}회 · 얇은 양봉 {r['cover_run']}개 (스승님 꿀팁: 공매도 흐름)")
    except Exception as e:  # noqa: BLE001
        log.warning("공매도 흐름 판정 실패: %s", e)
    if tc is not None and config.AFTER_SCALP_ENABLED and (db.get_meta("us_session") or {}).get("value") == "애프터마켓":
        try:
            after_scalp_cycle(conn, tc, toss_frames)
        except Exception as e:  # noqa: BLE001
            log.warning("애프터 스캘핑 판정 실패: %s", e)
    if config.SECFEED_ENABLED:  # 🔔 공시 알림: SEC 실시간 공시 피드 → 우리 종목만 저장·판정, 관심 종목은 텔레그램
        try:
            t0 = db.utcnow_iso()
            n_new = secfeed.poll(client, secfeed.universe_map(client))
            secfeed.enrich(client, config.SECFEED_ENRICH_PER_CYCLE)
            if config.SEC_DIGEST:
                try:  # 📝 공시 한국어 요약(병합 일정·13D/13G 도 같이)
                    import secdigest
                    secdigest.run(client=client, out=log.info)
                except Exception as e:  # noqa: BLE001
                    log.warning("공시 요약 실패: %s", e)
            insider.poll(client, secfeed.universe_map(client))   # 👤 내부자 매수(Form 4)
            insider.enrich(client, config.INSIDER_PER_CYCLE)
            if n_new:
                log.info("공시 알림: 새 공시 %d건", n_new)
            if config.SECFEED_ALERTS:
                mine = set(universe.from_watchlist())
                for r in secfeed.new_rows_since(t0, mine):
                    notify.send_telegram(f"🔔 {r['ticker']} {r['form']} · {r['sentiment']}\n{r['company']}\n태그: {', '.join(json.loads(r['tags'] or '[]')) or '-'}\n{r['url']}")
        except Exception as e:  # noqa: BLE001
            log.warning("공시 알림 피드 실패: %s", e)
    try:  # 📰 뉴스 모음(보도자료 피드, 10분 주기)
        import news
        news.refresh()
    except Exception as e:  # noqa: BLE001
        log.warning("뉴스 피드 받기 실패: %s", e)
    if config.NEWS_TRANSLATE:
        try:  # 🌐 받은 뉴스를 한국어로(한 번 번역하면 다시 안 함)
            import translate
            translate.run(out=log.info)
        except Exception as e:  # noqa: BLE001
            log.warning("뉴스 번역 실패: %s", e)
    try:  # 🌎 시장 지표(VIX 15분 · 공포·탐욕 30분 · 수입물가지수 하루) — 주기가 지난 것만
        macro.refresh()
    except Exception as e:  # noqa: BLE001
        log.warning("시장 지표 받기 실패: %s", e)
    try:  # 🚦 소형주 장세 신호등(30분, 2026-10-27)
        import regime
        regime.refresh()
    except Exception as e:  # noqa: BLE001
        log.warning("장세 신호등 받기 실패: %s", e)
    try:  # Reg SHO 기준 미달 목록(나스닥 공식, 하루 한 번 저녁에 게시 — 없는 날짜만 받음)
        n = regsho.refresh(conn)
        if n:
            log.info("Reg SHO 목록 %d일치 새로 받음", n)
    except Exception as e:  # noqa: BLE001
        log.warning("Reg SHO 목록 받기 실패: %s", e)
    if tc is not None:  # 📲 토스증권 바로가기용 종목 코드(없는 종목만, 200개씩 한 번)
        try:
            n = tosslink.refresh(tc, [t for t, _ in passing] + universe.from_watchlist() + short)
            if n:
                log.info("토스 바로가기 코드 %d종목 저장", n)
        except Exception as e:  # noqa: BLE001
            log.warning("토스 바로가기 코드 조회 실패: %s", e)
    try:  # 📈 분산·털기(스승님 꿀팁): 워치리스트·저금통 종목의 완성된 일봉에서 처음 잡힌 신호를 기록·알림
        for t in list(dict.fromkeys(universe.from_watchlist())):
            tb = flowread.classify(daily.get(t))
            if tb.empty or not tb.iloc[-1]["판정"]:
                continue
            last = tb.iloc[-1]
            if flowread.record(conn, t, last["날짜"], last["판정"], float(last["종가"])):
                log.info("분산·털기 신호: %s %s %s", t, last["날짜"], last["판정"])
                if config.FLOWREAD_ALERTS:
                    notify.send_telegram(f"📈 {t} {last['판정']} ({last['날짜']})\n등락 {last['등락(%)']:+.1f}% · 거래량 전일 대비 {last['전일 대비 거래량(배)']:.1f}배 (스승님 꿀팁: 분산·털기)")
    except Exception as e:  # noqa: BLE001
        log.warning("분산·털기 판정 실패: %s", e)
    try:  # 🕵️ 세력·셋업(스승님 꿀팁): 워치리스트·저금통·오늘 장마감 고정 종목을 하루 한 번(사이클당 상한)
        budget = config.SETUP_MAX_PER_CYCLE
        mmap = {t: m for t, m in passing}
        for t in list(dict.fromkeys(universe.from_watchlist() + short)):
            if budget <= 0:
                break
            got = pumpsetup.cached(conn, t)
            if got and (datetime.now(timezone.utc) - datetime.fromisoformat(got[0])).total_seconds() < 86400:
                continue
            m = mmap.get(t) or {}
            res = pumpsetup.analyze(client, conn, t, shares_out=m.get("float_shares"), dark=pumpsetup.dark_stats(conn, t, daily.get(t)),
                                    short=(imap.get(t) or {}).get("short"), dilution_status=(db.get_dilution(conn, t) or {}).get("status"))
            pumpsetup.save(conn, t, res, m.get("price"))
            budget -= 1
            if "error" not in res:
                log.info("세력·셋업: %s %s (+%d/−%d)", t, res["verdict"], res["plus"], res["minus"])
    except Exception as e:  # noqa: BLE001
        log.warning("세력·셋업 분석 실패: %s", e)
    if short:  # 장마감 펌핑 체크리스트(토스 기준): 정규장 중에만. 공통 인텔 값을 그대로 쓰고 고유 판정만 추가
        try:
            done = closewatch.update(conn, tc, client, short, frames=toss_frames, halts_list=halts_list, fintel_client=fintel_client, intel_map=imap)
            log.info("장마감 체크리스트(토스 기준) 갱신: %d/%d종목", done, len(short))
            try:  # 🧪 가상매매 '장마감 체크리스트' 전략: 지금 BEST·후보인 종목을 지금 가격으로 가상 매수(하루 한도 n)
                _now = closewatch._now()
                b_pt = papertrade.scan_close(conn, _now.astimezone(closewatch.ET).date().isoformat(), short, _now)
                if b_pt:
                    log.info("가상매매 장마감 매수: %s", ", ".join(b_pt))
            except Exception as e:  # noqa: BLE001
                log.warning("가상매매 장마감 매수 실패: %s", e)
        except Exception:  # noqa: BLE001
            log.exception("장마감 체크리스트 갱신 실패")
    return saved


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def beat(phase: str, next_in: float | None = None) -> None:
    """💓 스캐너가 지금 무엇을 하는지 남김(홈 '스캐너' 카드용). 한 회차가 10분을 넘겨도 '멈춤'으로 잘못 보이지 않게."""
    try:
        now = datetime.now(timezone.utc)
        db.set_meta("scanner_beat", json.dumps({"at": now.isoformat(timespec="seconds"), "phase": phase,
                                                "next": (now + timedelta(seconds=next_in)).isoformat(timespec="seconds") if next_in else None},
                                               ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # 상폐 종목 경고 도배 방지

    client = sec.SecClient(config.require_sec_user_agent())
    tc = toss.TossClient(config.TOSS_CLIENT_ID, config.TOSS_CLIENT_SECRET, config.TOSS_BASE_URL) if config.TOSS_ENABLED else None
    log.info("토스 Open API: %s", "사용" if tc else "미사용 (TOSS_CLIENT_ID/SECRET 없음)")
    db.init_db()
    collector = None
    if tc is not None and config.TOSS_WS_ENABLED:
        collector = tossws.FlowCollector(tc._token)
        collector = collector if collector.start() else None
    fintel_client = shortdata.ShortClient.from_config()  # 공매도: FINRA·IBKR(무료) + Fintel(키가 있을 때만)
    log.info("토스 실시간(체결강도): %s · 공매도: %s · 거래정지(업킷, 백업 나스닥): %s", "사용" if collector else "미사용", fintel_client.label,
             "사용" if config.HALTS_ENABLED else "미사용")
    log.info("스캐너 시작 (DB: %s)", config.DB_PATH)
    while True:
        t0 = time.time()
        beat("일봉 받는 중")
        try:
            with closing(db.connect()) as conn:
                n = run_cycle(conn, client, tc, collector, fintel_client)
            log.info("사이클 완료: %d종목 저장", n)
        except Exception:  # noqa: BLE001
            log.exception("사이클 실패")
        if args.once:
            break
        wait = max(5, config.SCAN_INTERVAL_SEC - (time.time() - t0))
        beat("쉬는 중", next_in=wait)
        time.sleep(wait)


if __name__ == "__main__":
    main()
