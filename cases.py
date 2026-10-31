"""과거 사례 DB: 전일 종가 대비 -10% 이하로 하락한 '사건'을 일봉 10년치에서 전부 찾아, 사건 이후 결과와 함께 저장합니다.

  python cases.py build --years 10     # 처음 한 번. 수십 분 걸리며 중단(Ctrl+C) 후 다시 실행하면 이어서 진행
  python cases.py update               # 매일 한 번(장 마감 후). 최근 사건 추가 + 아직 결과가 덜 쌓인 사건의 결과 보완 + 신규 상장 종목 추가
  python cases.py status               # 진행/오류 현황

사건 = (당일 종가 / 전일 종가 - 1) <= -10%. 결과는 사건일 종가 기준입니다.
  next_open/high/low/close_pct : 다음 거래일 시가·고가·저가·종가의 사건일 종가 대비 등락률
  fwd_3d/5d/10d                : N거래일 뒤 종가 수익률
  max_up_5d / max_down_5d      : 이후 5거래일 중 최고가 / 최저가의 사건일 종가 대비
'성공' 기준(예: 다음날 고가가 +N% 도달)은 저장하지 않고 대시보드에서 N을 바꿔가며 계산합니다.

한계: 일봉 기준이라 '장중에 어느 쪽이 먼저였는지(순서)'와 분 단위 결과는 알 수 없습니다.
      yfinance 가격은 분할 보정값이라 오래된 사건의 '가격' 필터는 부정확합니다(수익률에는 영향 없음).
      가격 데이터가 없는 상장폐지 종목은 'no_data'로 집계되어 대시보드에 표시됩니다(생존편향 지표).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import config
import db
import market
import universe

log = logging.getLogger("cases")
THRESHOLD = -10.0
EVENT_COLS = ["ticker", "date", "prev_close", "close", "drop_pct", "gap_pct", "intraday_rebound_pct",
              "avg_dollar_vol", "vol_mult", "pre_dd_pct", "next_open_pct", "next_high_pct", "next_low_pct",
              "next_close_pct", "fwd_3d", "fwd_5d", "fwd_10d", "max_up_5d", "max_down_5d", "bars_after", "last_bar_date",
              "max_up_3d", "max_down_3d",   # 2026-10-29: 3일 안 최고가·최저가(사용자 요청 — 하루 먹는 것과 3~5일 기다리는 것을 따로 검증)
              "range_pct", "close_loc", "prior_range_pct"]


def _pct(a, b):
    if b is None or a is None or b == 0 or np.isnan(a) or np.isnan(b):
        return None
    return float((a / b - 1) * 100)


def drop_incomplete_last_bar(df: pd.DataFrame | None, now: datetime | None = None) -> pd.DataFrame | None:
    """미국 정규장이 끝나기 전(동부시간 16:20 이전)에는 오늘 일봉이 진행 중이라 값이 확정되지 않았으므로 마지막 봉을 뺀다.
    (한국시간 새벽에 실행하면 대부분 해당) 장 마감 후 `update` 가 확정값으로 다시 계산한다."""
    if df is None or df.empty:
        return df
    now = now or datetime.now(ZoneInfo("America/New_York"))
    last = pd.Timestamp(df.index[-1]).tz_localize(None).normalize()
    if last.date() == now.date() and (now.hour, now.minute) < (16, 20):
        return df.iloc[:-1]
    return df


def find_events(ticker: str, df: pd.DataFrame, threshold: float = THRESHOLD, since: str | None = None) -> list[dict]:
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    d = d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["Open", "High", "Low", "Close"])
    n = len(d)
    if n < 12:
        return []
    o, h, l, c = (d[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    v = d["Volume"].fillna(0).to_numpy(float)
    dates = d.index.strftime("%Y-%m-%d").to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        chg = (c[1:] / c[:-1] - 1) * 100
    ok = (c[1:] > 0) & (c[:-1] > 0) & (l[1:] > 0) & (chg <= threshold) & (chg >= -99.5)  # 데이터 오류성 -100% 제외
    rows = []
    for i in np.where(ok)[0] + 1:
        if since and dates[i] < since:
            continue
        lo = max(0, i - 20)
        pv, pc, ph = v[lo:i], c[lo:i], h[lo:i]
        ctx = len(pv) >= 10
        avg_v = float(pv.mean()) if ctx else 0.0
        row = {
            "ticker": ticker, "date": dates[i], "prev_close": float(c[i - 1]), "close": float(c[i]),
            "drop_pct": float(chg[i - 1]), "gap_pct": _pct(o[i], c[i - 1]), "intraday_rebound_pct": _pct(c[i], l[i]),
            "avg_dollar_vol": float((pc * pv).mean()) if ctx else None,
            "vol_mult": float(v[i] / avg_v) if avg_v > 0 else None,
            "pre_dd_pct": _pct(c[i - 1], float(ph.max())) if ctx and ph.max() > 0 else None,
            "next_open_pct": None, "next_high_pct": None, "next_low_pct": None, "next_close_pct": None,
            "fwd_3d": None, "fwd_5d": None, "fwd_10d": None, "max_up_5d": None, "max_down_5d": None, "max_up_3d": None, "max_down_3d": None,
            "bars_after": int(n - 1 - i), "last_bar_date": dates[-1],
            "range_pct": _pct(h[i], l[i]),                                     # 그날 변동폭(고가/저가)
            "close_loc": float((c[i] - l[i]) / (h[i] - l[i])) if h[i] > l[i] else None,   # 종가 위치: 0=저가, 1=고가
            "prior_range_pct": float(np.mean(((h[lo:i] - l[lo:i]) / np.where(pc > 0, pc, np.nan)) * 100)) if ctx else None,  # 직전 20일 평균 변동폭
        }
        if i + 1 < n:
            row.update(next_open_pct=_pct(o[i + 1], c[i]), next_high_pct=_pct(h[i + 1], c[i]),
                       next_low_pct=_pct(l[i + 1], c[i]), next_close_pct=_pct(c[i + 1], c[i]))
        for k in (3, 5, 10):
            if i + k < n:
                row[f"fwd_{k}d"] = _pct(c[i + k], c[i])
        if i + 5 < n:
            row["max_up_5d"] = _pct(float(h[i + 1:i + 6].max()), c[i])
            row["max_down_5d"] = _pct(float(l[i + 1:i + 6].min()), c[i])
        if i + 3 < n:
            row["max_up_3d"] = _pct(float(h[i + 1:i + 4].max()), c[i])
            row["max_down_3d"] = _pct(float(l[i + 1:i + 4].min()), c[i])
        rows.append(row)
    return rows


def save_events(conn, rows: list[dict]) -> None:
    if rows:
        conn.executemany(f"INSERT OR REPLACE INTO case_events ({','.join(EVENT_COLS)}) VALUES ({','.join('?' * len(EVENT_COLS))})",
                         [tuple(r.get(c) for c in EVENT_COLS) for r in rows])


def backfill_3d(conn, out=print) -> dict:
    """사건의 '3일 안 최고가·최저가'(max_up_3d/max_down_3d)가 비어 있으면 daily_prices(🕰 타임머신이 모아 둔 3년 일봉)로 채운다 — 인터넷 없이 몇 초.
    2026-10-29 밤: 3일 목표가 뒤늦게 추가돼 과거 10년 사건은 비어 있다. 일봉이 있는 최근 3년치(전체의 약 절반)만 채워지고, 나머지는 `cases.py build --rebuild`(야후 재수집, 수십 분)로.
    계산은 find_events 와 같다: 사건일 종가 대비 다음 3거래일 고가 최대·저가 최소(%). 뒤 봉이 3개 안 되는 최근 사건은 다음에."""
    import bisect
    need = conn.execute("SELECT ticker, date, close FROM case_events WHERE max_up_3d IS NULL AND close IS NOT NULL ORDER BY ticker, date").fetchall()
    if not need:
        return {"filled": 0, "left": 0}
    by: dict[str, list] = {}
    for r in need:
        by.setdefault(r[0], []).append((r[1], float(r[2])))
    upd = []
    for t, evs in by.items():
        bars = conn.execute("SELECT date, high, low, close FROM daily_prices WHERE ticker=? AND date>=? ORDER BY date", (t, evs[0][0])).fetchall()
        if len(bars) < 3:
            continue
        dates = [b[0] for b in bars]
        for d, _c in evs:
            i = bisect.bisect_right(dates, d)   # 사건 다음 봉부터
            if i == 0 or dates[i - 1] != d or i + 3 > len(bars):
                continue   # 사건일 봉이 저장소에 없으면 건너뜀(기준 종가를 같은 자료에서 잡아야 역분할 보정 차이로 엉뚱한 % 가 안 나옴)
            c = bars[i - 1][3]
            if not c or c <= 0:
                continue
            seg = bars[i:i + 3]
            d0 = date.fromisoformat(d)   # 일봉이 사건보다 한참 뒤부터만 있으면(저장소는 3년치) 엉뚱한 봉을 붙이지 않게: 첫 봉은 7일 안(연휴 포함), 셋째 봉은 14일 안
            if seg[0][0] > (d0 + timedelta(days=7)).isoformat() or seg[2][0] > (d0 + timedelta(days=14)).isoformat():
                continue
            hs = [float(b[1]) for b in seg if b[1] is not None]
            ls = [float(b[2]) for b in seg if b[2] is not None]
            if len(hs) < 3 or len(ls) < 3:
                continue
            upd.append((_pct(max(hs), c), _pct(min(ls), c), t, d))
    if upd:
        conn.executemany("UPDATE case_events SET max_up_3d=?, max_down_3d=? WHERE ticker=? AND date=?", upd)
        conn.commit()
    left = conn.execute("SELECT COUNT(*) FROM case_events WHERE max_up_3d IS NULL").fetchone()[0]
    out(f"3일 목표 보완: {len(upd):,}건 채움 · 아직 빈 사건 {left:,}건(일봉 없는 옛 사건 — build --rebuild 로)")
    return {"filled": len(upd), "left": int(left)}


def mark(conn, ticker: str, status: str, df=None, n_events: int = 0, delisted: bool = False, msg: str | None = None) -> None:
    n_bars = first = last = None
    if df is not None and len(df):
        idx = pd.to_datetime(df.index)
        n_bars, first, last = int(len(df)), idx.min().strftime("%Y-%m-%d"), idx.max().strftime("%Y-%m-%d")
    conn.execute("""INSERT INTO case_progress (ticker,status,n_events,n_bars,first_date,last_date,is_delisted,msg,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET status=excluded.status, n_events=excluded.n_events, n_bars=excluded.n_bars,
                      first_date=excluded.first_date, last_date=excluded.last_date, is_delisted=excluded.is_delisted,
                      msg=excluded.msg, updated_at=excluded.updated_at""",
                 (ticker, status, n_events, n_bars, first, last, int(delisted), msg, db.utcnow_iso()))


def _eta(elapsed: float, done: int, total: int) -> str:
    if done <= 0:
        return "계산 중"
    left = elapsed / done * (total - done)
    return f"{int(left // 60)}분" if left >= 60 else f"{int(left)}초"


# ---------------------------------------------------------------- 전체 수집
def build(conn, active: list[str], delisted: list[str], years: int = 10, threshold: float = THRESHOLD, chunk: int = 25,
          rebuild: bool = False, limit: int = 0, pause: float = 1.0, out=print) -> dict:
    dset = set(delisted) - set(active)
    universe_all = sorted(set(active) | dset)
    finished = set() if rebuild else {r["ticker"] for r in conn.execute("SELECT ticker FROM case_progress WHERE status IN ('done','no_data')")}
    todo = [t for t in universe_all if t not in finished]
    if limit:
        todo = todo[:limit]
    total = len(todo)
    out(f"대상 {len(universe_all):,}종목 (상장 {len(active):,} + 상장폐지 목록 {len(dset):,}) · 이미 처리됨 {len(universe_all) - len(todo) if not limit else '-'} · 이번 처리 {total:,}")
    stat = {"ok": 0, "no_data": 0, "error": 0, "events": 0}
    t0, done = time.time(), 0
    try:
        for i in range(0, total, chunk):
            batch = todo[i:i + chunk]
            try:
                data = market.download_daily(batch, period=f"{years}y", chunk=chunk)
            except Exception as e:  # noqa: BLE001
                log.warning("다운로드 실패: %s", e)
                data = {}
            if not data:  # 묶음 전체가 비면 일시적 오류(요청 제한 등)로 보고 다음 실행에서 재시도
                for t in batch:
                    mark(conn, t, "error", delisted=t in dset, msg="다운로드 실패(일시 오류 가능)")
                stat["error"] += len(batch)
            else:
                for t in batch:
                    df = drop_incomplete_last_bar(data.get(t))
                    if df is None or len(df.dropna(subset=["Close"])) < 15:
                        mark(conn, t, "no_data", delisted=t in dset, msg="가격 데이터 없음(상장폐지/티커 변경 가능)")
                        stat["no_data"] += 1
                        continue
                    try:
                        rows = find_events(t, df, threshold)
                        conn.execute("DELETE FROM case_events WHERE ticker=?", (t,))  # 전체 이력을 다시 계산했으므로 이전 사건은 교체
                        save_events(conn, rows)
                        mark(conn, t, "done", df, len(rows), t in dset)
                        stat["ok"] += 1
                        stat["events"] += len(rows)
                    except Exception as e:  # noqa: BLE001
                        log.exception("%s 처리 실패", t)
                        mark(conn, t, "error", delisted=t in dset, msg=f"{type(e).__name__}: {e}")
                        stat["error"] += 1
            conn.commit()
            done += len(batch)
            out(f"[{done:,}/{total:,}] 사건 +{stat['events']:,} · 데이터없음 {stat['no_data']:,} · 오류 {stat['error']:,} · "
                f"경과 {int((time.time() - t0) // 60)}분 · 남은 시간 ≈ {_eta(time.time() - t0, done, total)} · 현재 {batch[-1]}")
            if pause:
                time.sleep(pause)
    except KeyboardInterrupt:
        conn.commit()
        out("\n중단했습니다. 같은 명령을 다시 실행하면 이어서 진행합니다.")
    return stat


# ---------------------------------------------------------------- 매일 갱신
def update(conn, active: list[str], delisted: list[str], days: int = 60, years: int = 10, threshold: float = THRESHOLD,
           chunk: int = 50, pause: float = 1.0, out=print) -> dict:
    try:  # 2026-10-31: 한 회사 여러 티커(WHLR·WHLRP)로 갈라 저장된 공시를 보통주 티커로 — 동기화 전에(공시 이력도 같은 티커로)
        import secfeed
        import sec as _secL
        if "@" in config.SEC_USER_AGENT:
            _n = secfeed.relabel(conn, _secL.SecClient(config.SEC_USER_AGENT))
            if _n:
                out(f"공시 티커 고침: {_n}행(한 회사 여러 티커 → 보통주 티커로)")
    except Exception as e:  # noqa: BLE001
        log.exception("공시 티커 고침 실패: %s", e)
    try:  # 2026-10-31: 병합 일정 한 번 다시 읽기 — 스캐너가 병합 공시를 첨부(EX-3.1 등)로 읽어 ATYR 1:40 같은 시행일을 놓쳤던 것(주 문서 + EX-99 로) · 🩹 계단 수리보다 먼저
        import rsplit as _rsB
        import sec as _secB
        if "@" in config.SEC_USER_AGENT and db.get_meta("rs_upcoming_refill_v2") is None:
            _rb = _rsB.backfill_upcoming(_secB.SecClient(config.SEC_USER_AGENT), days=30, out=lambda *_: None, only_tagged=True, min_main=10**9)
            db.set_meta("rs_upcoming_refill_v2", date.today().isoformat())
            out(f"병합 일정 다시 읽기(한 번): 병합 공시 {_rb['read']}건 · 새 시행일 {_rb['new']}건")
    except Exception as e:  # noqa: BLE001
        log.exception("병합 일정 다시 읽기 실패: %s", e)
    try:  # 2026-10-30: 공시 이력(sec_hist)이 10/15 백필에서 멈춰 있던 것 → 스캐너 피드(sec_feed)를 매일 합침(수집기·presim/타임머신 희석 깃발·📚 플래그가 새 공시를 보게)
        import secbackfill
        out(f"공시 이력 동기화: 피드에서 {secbackfill.sync_from_feed(conn):,}건 추가")
    except Exception as e:  # noqa: BLE001
        log.exception("공시 이력 동기화 실패: %s", e)
    since = (date.today() - timedelta(days=days)).isoformat()
    tickers = [r["ticker"] for r in conn.execute("SELECT ticker FROM case_progress WHERE status='done'")]
    out(f"최근 {days}일 사건 갱신: {len(tickers):,}종목")
    n_new = 0
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        data = market.download_daily(batch, period="6mo", chunk=chunk)
        for t in batch:
            df = drop_incomplete_last_bar(data.get(t))
            if df is None or len(df) < 40:  # 데이터가 부족하면 기존 기록을 건드리지 않음
                continue
            rows = find_events(t, df, threshold, since=since)
            conn.execute("DELETE FROM case_events WHERE ticker=? AND date>=?", (t, since))  # 임시값/기준 변경으로 사건이 아니게 된 행 제거
            save_events(conn, rows)
            n_new += len(rows)
            cnt = conn.execute("SELECT COUNT(*) FROM case_events WHERE ticker=?", (t,)).fetchone()[0]
            conn.execute("UPDATE case_progress SET n_events=?, last_date=?, updated_at=? WHERE ticker=?",
                         (cnt, pd.to_datetime(df.index).max().strftime("%Y-%m-%d"), db.utcnow_iso(), t))
        conn.commit()
        out(f"  [{min(i + chunk, len(tickers)):,}/{len(tickers):,}] 갱신 사건 {n_new:,}")
        if pause:
            time.sleep(pause)
    try:  # 3일 목표(2026-10-29 추가)가 빈 과거 사건을 저장된 일봉으로 보완(인터넷 없음, 몇 초)
        backfill_3d(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("3일 목표 보완 실패: %s", e)
    try:  # 스캐너가 발견한 종목의 결과(다음날/5일 후 등)도 같이 채운다
        import tracker
        tracker.update(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("발견 종목 추적 갱신 실패: %s", e)
    try:  # 💵 dry-run 매수 기록에 '그때 1주 샀다면' 결과(2026-10-29 아침, broker.simulate_dry — 일봉으로 익절/손절/보유일 판정, 야후 몇 종목)
        import broker
        broker.simulate_dry(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("dry-run 결과 갱신 실패: %s", e)
    try:  # 🔁 병합 후 레이더: 최근 1년 분할 기록·경로 갱신 + 오늘의 예측 기록(성과 공표용)
        import config as _cfg
        if _cfg.RSPLIT_DAILY:
            import rsplit
            from zoneinfo import ZoneInfo as _Z
            r = rsplit.run(rsplit.universe(), "1y", out=lambda *_: None)
            n = rsplit.record_daily(conn, datetime.now(_Z("America/New_York")).date().isoformat())
            out(f"병합 후 레이더: 최근 병합 {r['current']}종목 · 오늘 예측 {n}건 기록")
    except Exception as e:  # noqa: BLE001
        log.exception("병합 후 레이더 갱신 실패: %s", e)
    try:  # 🩹 병합 환산 수리(2026-10-30): 병합 종목의 저장 일봉을 야후 2년치로 다시 써서 옛 기준 봉(병합일 ×비율 점프)을 없앰 — presim·선별·모델이 가짜 급등을 보지 않게
        import pricefix
        pricefix.morning(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("병합 환산 수리 실패: %s", e)
    try:
        import config as _cfg0
        _cfg0.apply_overrides()  # ⚙️ 관리 모드 설정
    except Exception:  # noqa: BLE001
        pass
    try:  # 💰 펀드스캔: 최근 1년 자금조달 공시 해석(하루 60건) · 추적 종목 SEC 재무(워런트·주식 수 이력)
        import config as _cfgF
        if "@" in _cfgF.SEC_USER_AGENT:
            import fundscan
            import sec as _secF
            fundscan.run(_secF.SecClient(_cfgF.SEC_USER_AGENT), limit=150, xbrl_limit=80, out=out)
            try:  # 📊 비슷한 과거 딜: 매도 가능일 뒤 결과 계산(60거래일 다 채울 때까지 매일)
                import dealpaths
                dealpaths.update(out=out)
            except Exception as _e:  # noqa: BLE001
                log.warning("비슷한 과거 딜 실패: %s", _e)
    except Exception as e:  # noqa: BLE001
        log.exception("펀드스캔 갱신 실패: %s", e)
    try:  # ✅ 스승님 3대 조건: 오늘 충족 종목을 🏆 성과 공표에 기록(같은 종목 20일에 한 번) · 🕰 타임머신은 토요일마다 다시 계산
        import setup3
        from contextlib import closing as _cl3
        with _cl3(db.connect()) as _c3:
            _tk3 = setup3.candidates(_c3)
        _px3 = market.download_daily(_tk3, period="1y") if _tk3 else {}
        with _cl3(db.connect()) as _c3:
            _rows3 = setup3.scan(_c3, _px3, _tk3)
            _n3 = setup3.record(_c3, _rows3)
            _nt = setup3.record_tiers(_c3, _rows3)
        out(f"3대 조건: {len(_tk3)}종목 판정 · 새 기록 {_n3} · 검증 순위(1~3) 새 기록 {_nt}")
        import timemachine
        timemachine.fill_history(years=3.0, limit=300, out=out)  # 🕰 과거 일봉을 하루 300종목씩 채움(약 2주면 나스닥 전체)
        if date.today().weekday() == 5:
            timemachine.run(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("3대 조건·타임머신 실패: %s", e)
    try:  # ⏰ 예약 알림: 미뤄 둔 일(예: 공시 점수 두 방식 합치기)을 때가 되면 텔레그램으로 한 번
        import reminders
        reminders.check(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("예약 알림 확인 실패: %s", e)
    try:  # 🧮 과거 성과 기반 공시 점수표 다시 만들기(이벤트 수집기가 쌓은 사건으로) + 최근 1년 검증
        import evscore
        _v = evscore.build()["validation"]
        out(f"공시 점수표: {_v.get('why')}")
    except Exception as e:  # noqa: BLE001
        log.exception("공시 점수표 실패: %s", e)
    try:  # 🪙 런웨이 채우기: PICK 통과 → 목표가 있는 종목 → 회사 압박 후보 순으로 SEC 재무(현금·월 소모량), 하루 상한
        import config as _cfgR
        if "@" in _cfgR.SEC_USER_AGENT:
            import runway as _rwm
            import sec as _secR
            import pick30 as _pk
            _ps = None
            try:  # 2026-10-30: 단계마다 따로 — 10/29 아침 여기서 난 'None 형식' 오류 한 번에 보고 기한·공시분석·AI PICK·런웨이 갱신까지 통째로 건너뛰었음
                _ps = _pk.scan()
                with closing(db.connect()) as _c:  # 🏆 PICK 통과 종목을 목표 종류별로 기록
                    out(f"PICK 기록: 새 신호 {_pk.record(_c, _ps)}건 · 📊 PICK 변동 저장 {_pk.snapshot(_c, _ps, force=True)}종목")
            except Exception as _e:  # noqa: BLE001
                log.exception("PICK 스캔·기록 실패")   # cases.log 에 오류 줄 위치까지(다음엔 바로 원인을 찾게)
                out(f"PICK 스캔·기록 실패: {_e}")
            try:  # ⏰ 보고 기한 캐시 + 📰 한 장 요약 자동 대기열(A·B단계 2026-10-28) — 급상승·보유·저금통 중 요약 없는 종목
                import clock as _ck
                import config as _cfgC
                import forensic_ai as _fa0
                import sec as _secC
                with closing(db.connect()) as _c:
                    _fa0.auto_enqueue(_c, out=out)
                    _ck.refresh_due(_c, _secC.SecClient(_cfgC.SEC_USER_AGENT), _ck.due_targets(_c), out=out)
            except Exception as _e:  # noqa: BLE001
                out(f"보고 기한·요약 대기열 실패: {_e}")
            try:  # 🧾 서버 공시분석 — 대기열에서 몇 종목(PC Cowork 대신)
                import forensic_ai as _fa
                _fa.run(out=out)
            except Exception as _e:  # noqa: BLE001
                out(f"서버 공시분석 실패: {_e}")
            try:  # 🤖 AI PICK — 하루 한 번 Claude 판단(월 예산 안에서)
                import aipick as _ai
                _ai.run(scan=_ps, out=out)
            except Exception as _e:  # noqa: BLE001
                out(f"AI PICK 실패: {_e}")
            try:
                _rwm.refresh(_secR.SecClient(_cfgR.SEC_USER_AGENT), _rwm.targets(_ps), limit=80, out=out)
            except Exception as _e:  # noqa: BLE001
                log.exception("런웨이 갱신 실패")
                out(f"런웨이 갱신 실패: {_e}")
    except Exception as e:  # noqa: BLE001
        log.exception("런웨이 채우기 실패: %s", e)
    try:  # 📐 발행주식 수 추정(SEC 표지·분할 반영) · 🏛 상장유지 통지 해석 — 압박·매집·Reg SHO 후보, 하루 상한
        import config as _cfgS
        if "@" in _cfgS.SEC_USER_AGENT:
            import listing
            import pressure
            import sec as _secS
            import shares as _shS
            _cl = _secS.SecClient(_cfgS.SEC_USER_AGENT)
            with closing(db.connect()) as _c:
                _cands = pressure.candidates(_c)
            _shS.build_missing(_cl, _cands, limit=80, out=out)
            try:  # 🐷 저금통 ⑥ 주식수 변동(SEC 표지 이력, 2026-10-28): 저금통 후보도 표지 추정·이력을 받아 둔다(압박 후보 80개에 밀리지 않게 별도 상한)
                import piggy as _pg
                with closing(db.connect()) as _c:
                    _ptk = _pg.share_targets(_c)
                _shS.build_missing(_cl, _ptk, limit=60, out=lambda m: out(f"🐷 {m}"))
            except Exception as e:  # noqa: BLE001
                log.exception("저금통 주식수 이력 갱신 실패: %s", e)
            try:  # 🏁 ⑥ 를 순위·PICK 에도 쓰므로(2026-10-28) 스캐너 우주 전체의 표지 이력을 30일 주기로 돌아가며 갱신(하루 110종목 ≈ 30초, SEC 무료)
                import universe as _uv
                _uni = _uv.cached_tickers()   # 상장 종목 캐시 파일(스캐너가 매일 갱신) — DB 표가 아님(10/28 밤 수정)
                if not _uni:   # 캐시 파일이 없으면 최근 120일 스냅샷 종목으로
                    with closing(db.connect()) as _c:
                        _uni = [r[0] for r in _c.execute("SELECT DISTINCT ticker FROM daily_snapshots WHERE date >= date('now','-120 day') ORDER BY ticker")]
                if _uni:
                    _shS.build_missing(_cl, _uni, limit=110, out=lambda m: out(f"🏁 우주 {m}"), max_age=30)
            except Exception as e:  # noqa: BLE001
                log.exception("우주 주식수 이력 갱신 실패: %s", e)
            listing.backfill(_cl, limit=30, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("주식 수·상장유지 갱신 실패: %s", e)
    try:  # 🧭 회사 압박 후보 종목 리포트(런웨이 등) — 없거나 7일 지난 것만, 하루 상한
        import config as _cfg3
        if _cfg3.PRESSURE_REPORTS_PER_DAY > 0 and "@" in _cfg3.SEC_USER_AGENT:
            import pressure
            import sec as _sec
            pressure.build_missing_reports(_sec.SecClient(_cfg3.SEC_USER_AGENT), _cfg3.PRESSURE_REPORTS_PER_DAY, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("회사 압박 리포트 생성 실패: %s", e)
    try:  # 🏷 테마: 새 종목만 SEC 회사 정보(이름·업종 코드)로 테마 지정(하루 상한 400)
        import config as _cfg4
        if "@" in _cfg4.SEC_USER_AGENT:
            import sec as _sec4
            import themes
            themes.build(_sec4.SecClient(_cfg4.SEC_USER_AGENT), limit=400, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("테마 지정 실패: %s", e)
    try:  # 🧲 매집 의심(일간·주간·월간) — 전체 종목 일봉 분석
        import config as _cfg2
        if _cfg2.ACCUM_DAILY:
            import accum
            accum.run(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("매집 의심 분석 실패: %s", e)
    try:  # 🗄 주가 보관소: 신호 낸 종목의 일봉 보관 · 병합 단위 맞춤 · 끊긴 종목 기록(가상매매·성과 공표 바로 앞에)
        import pricevault
        pricevault.daily(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("주가 보관소 실패: %s", e)
    try:  # 🐷 저금통 후보 다시 찾기(매일 아침) — 저가 종목 박스 분석 → 🤖 자동 담기·빼기(가상매매 저금통 전략보다 먼저)
        import config as _cfg
        if _cfg.PIGGY_DAILY_SCAN:
            import piggy
            m = db.get_meta("usdkrw")
            fx = float((m or {}).get("value") or 1350.0)
            res = piggy.screen(piggy.universe(), fx)
            out(f"저금통 후보 분석: {len(res):,}종목")
            piggy.auto_sync(fx, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("저금통 후보 분석 실패: %s", e)
    try:  # 🕶 다크풀: 감시 대상 밖(NYSE·AMEX)·미완성 의심 종목 일봉 다시 받기(비중 = 장외 ÷ 전체가 정확해지게)
        import darkpool
        darkpool.refresh_volumes(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("다크풀 일봉 보정 실패: %s", e)
    try:  # 📐 스승 관점(2026-10-27): 후보군(종합 순위·급상승·저금통·가상매매 보유·워치) 일봉·60분·5분 → 신호 기록(🏆 검증·🧪 가상매매 '스승 눌림목' 이 씀)
        import chartview
        chartview.morning(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("차트 관점 점검 실패: %s", e)
    try:  # 🧪 가상매매: 열린 포지션 청산 판정(전략 5개) → 종합 순위·PICK·저금통 가상 매수
        import papertrade
        papertrade.daily(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("가상매매 갱신 실패: %s", e)
    try:  # 📊 뉴스 반응(2026-10-29): 종목 있는 뉴스마다 뉴스 뒤 주가(당일 고가·종가·+1일·+5일)를 일봉으로 재서 news_react 에 쌓음 — 📰 뉴스 모음 '반응 통계'
        import newsfx
        newsfx.update(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("뉴스 반응 갱신 실패: %s", e)
    try:  # 🎲 매매 전 시뮬레이션(2026-10-29): 사건 표 이어 쌓기 → 저금통·PICK 유력·순위 상위 N 을 기본 손절·목표로 자동 실행 → presim_log(카드 배지 · 🏆 성과 공표)
        import presim
        presim.morning(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("매매 전 시뮬레이션 실패: %s", e)
    try:  # 🔍 부검(2026-10-28): 어제 펌핑(놓침/잡음 + 전날 특징·촉매) · 새로 실패한 신호(원인 태그) — 🏆 성과 공표 판정이 끝난 뒤가 좋지만 어제 것은 이미 판정돼 있음
        import autopsy
        autopsy.morning(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("부검 실패: %s", e)
    try:  # 🤖 Claude 복기(3단계 2026-10-28): 주 1회(마지막 복기 뒤 6일) 놓친 펌핑·실패 신호 원인 분류 + 규칙 후보 — Haiku, 월 예산 안
        import review
        review.run(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("Claude 복기 실패: %s", e)
    try:  # 🧠 신호 승률 모델(2단계 A안 2026-10-28): 월 1회(토요일) 재학습 · 최근 3일 새 신호에 p30·p10 붙이기 (market 은 모듈 맨 위에서 이미 import — 함수 안에서 다시 import 하면 지역 이름이 돼 앞줄이 깨짐)
        import sigmodel
        with closing(db.connect()) as _c:
            sigmodel.maybe_refit(_c, out=out)
            sigmodel.score_signals(_c, out=out, download=lambda t: market.download_daily([t], period="1y").get(t))
    except Exception as e:  # noqa: BLE001
        log.exception("신호 승률 모델 실패: %s", e)
    try:  # 🧪 승률 점수 모델(winmodel): 토요일에 30일 넘게 묵었으면 재학습(2026-10-30 사용자 승인 — 전엔 수동 fit 뿐)
        import winmodel
        winmodel.maybe_refit(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("승률 점수 모델 재학습 실패: %s", e)
    try:  # 🔁 리셋 사이클(2026-10-30): reset_config 종목(WHLR)의 다음 상환일 기준가·전환가 시나리오 한 줄 로그 · D-3 안이면 텔레그램(주인 전용)
        import resetcycle
        resetcycle.morning(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("리셋 사이클 아침 메모 실패: %s", e)
    try:  # 🧨 공매도 잔고(Yahoo, FINRA 격주): 스퀴즈 후보 700종목(C단계: Reg SHO·고수수료·안 받은 종목 먼저 — 예전 '점수 상위 400'은 잔고 없는 종목을 영영 못 받았음)
        import shortint
        shortint.refresh(shortint.priority(700), max_n=700, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("공매도 잔고 받기 실패: %s", e)
    try:  # 🏢 기업 설명(2026-10-31): 워치리스트·PICK·AI PICK·급상승 중 설명 없는 종목 하루 40개(Haiku 약 1원/종목, AI 예산 안)
        import companydesc
        companydesc.morning(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("기업 설명 실패: %s", e)
    try:  # 🏦 현금조달 가능성 기록(2026-10-31) — 관심 종목(최신 스냅샷)마다 높음/중간/낮음 → 30일 뒤 실제 조달과 맞춰 보는 검증 재료
        import verdict
        verdict.log_daily(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("현금조달 가능성 기록 실패: %s", e)
    try:  # 🧨 스퀴즈 순위·대차 감시 목록 매일 저장(2026-10-31: 화면을 열 때만 저장돼 10/26 뒤로 멈춰 있었음) — 새 공매도 잔고를 받은 뒤
        import squeeze
        squeeze.daily(out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("스퀴즈 순위 저장 실패: %s", e)
    try:  # 🏆 성과 공표: 모든 예측의 결과 갱신
        import scoreboard
        scoreboard.update(conn, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("성과 공표 갱신 실패: %s", e)
    known = {r["ticker"] for r in conn.execute("SELECT ticker FROM case_progress")}
    new_listed = [t for t in active if t not in known]
    if new_listed:
        out(f"신규 종목 {len(new_listed):,}개 전체 이력 수집")
        build(conn, new_listed, [], years, threshold, 25, pause=pause, out=out)
    try:  # 🔥 화면 캐시(2026-10-28): 새 사건·공시·순위를 반영해 전부 다시 데움(quant-warm.timer 는 10분마다 오래된 것만)
        import pagecache
        pagecache.warm(force=True, out=out)
    except Exception as e:  # noqa: BLE001
        log.exception("화면 캐시 데우기 실패: %s", e)
    return {"updated_events": n_new, "new_tickers": len(new_listed)}


def status(conn, out=print) -> None:
    rows = conn.execute("SELECT status, is_delisted, COUNT(*) n FROM case_progress GROUP BY status, is_delisted").fetchall()
    ev = conn.execute("SELECT COUNT(*), SUM(next_high_pct IS NOT NULL), SUM(fwd_5d IS NOT NULL), MIN(date), MAX(date) FROM case_events").fetchone()
    out("종목 처리 현황 (상태 / 상장폐지 목록 여부 / 수): " + (", ".join(f"{r['status']}/{'폐지' if r['is_delisted'] else '상장'}/{r['n']:,}" for r in rows) or "없음"))
    out(f"사건 {ev[0]:,}건 · 다음날 결과 확인 {ev[1] or 0:,} · 5일 결과 확인 {ev[2] or 0:,} · 기간 {ev[3]} ~ {ev[4]}")
    errs = conn.execute("SELECT ticker, msg FROM case_progress WHERE status='error' LIMIT 5").fetchall()
    for e in errs:
        out(f"  오류 예: {e['ticker']} — {e['msg']}")


# ---------------------------------------------------------------- 종목 목록
def case_universe(include_delisted: bool = True) -> tuple[list[str], list[str]]:
    tc = None
    if config.TOSS_ENABLED:
        import toss
        tc = toss.TossClient(config.TOSS_CLIENT_ID, config.TOSS_CLIENT_SECRET, config.TOSS_BASE_URL)
    active = universe.load_listed_toss(tc, False) if tc else []
    if not active:
        active = universe.load_listed(include_amex=False)
    delisted: list[str] = []
    if include_delisted and tc:
        delisted = universe.load_delisted_toss(tc)
    elif include_delisted:
        print("토스 연동이 꺼져 있어 상장폐지 종목 목록을 구할 수 없습니다(생존편향이 커집니다).")
    return active, delisted


def main() -> int:
    ap = argparse.ArgumentParser(description="과거 급락 사례 DB")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="전체 이력 수집(이어하기 지원)")
    b.add_argument("--years", type=int, default=10)
    b.add_argument("--threshold", type=float, default=THRESHOLD, help="사건 기준 등락률(기본 -10)")
    b.add_argument("--no-delisted", action="store_true", help="상장폐지 목록을 쓰지 않음")
    b.add_argument("--limit", type=int, default=0, help="테스트용: 이번에 처리할 종목 수 제한")
    b.add_argument("--rebuild", action="store_true", help="처리 기록을 무시하고 처음부터 다시")
    b.add_argument("--chunk", type=int, default=25)
    u = sub.add_parser("update", help="매일 갱신")
    u.add_argument("--days", type=int, default=60)
    u.add_argument("--threshold", type=float, default=THRESHOLD)
    sub.add_parser("status", help="현황")
    sub.add_parser("backfill3d", help="3일 목표(max_up_3d)가 빈 사건을 저장된 일봉으로 보완(인터넷 없음)")
    sub.add_parser("presim", help="🎲 매매 전 시뮬레이션: 사건 표 갱신 + 오늘 후보 자동 실행(아침 작업에도 포함)")
    sub.add_parser("newsfx", help="📊 뉴스 반응: 종목 있는 뉴스마다 뉴스 뒤 주가를 일봉으로 재서 쌓기(아침 작업에도 포함)")
    sub.add_parser("drysim", help="💵 dry-run 매수 기록에 '그때 1주 샀다면' 결과 붙이기(야후 일봉)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    db.TIMEOUT = 120.0   # 2026-10-30: 다른 프로그램이 잠금을 잠깐 쥐어도 30초 만에 포기하지 않게(아침 작업은 급하지 않음)
    try:
        sys.stdout.reconfigure(line_buffering=True)   # journalctl 에 줄마다 바로(예전엔 끝날 때 한꺼번에 나와 모든 줄이 09:03:38 로 찍혔음)
    except Exception:  # noqa: BLE001
        pass
    import filelog   # 2026-10-30: 진행 줄(INFO)·실패(WARNING)를 DB 폴더 cases.log 에도 → ⚙️ 관리 모드 '⚠️ 아침 작업 경고' 상자·'로그 보기'
    filelog.attach("cases", level=logging.INFO)
    _out = filelog.out_logger("cases.out").info
    db.init_db()
    with closing(db.connect()) as conn:
        if args.cmd == "status":
            status(conn)
        elif args.cmd == "backfill3d":
            print(backfill_3d(conn))
        elif args.cmd == "drysim":
            import broker
            print(broker.simulate_dry(conn))
        elif args.cmd == "newsfx":
            import newsfx
            print(newsfx.update(conn))
        elif args.cmd == "presim":
            import presim
            print(presim.morning(conn))
        elif args.cmd == "build":
            active, delisted = case_universe(not args.no_delisted)
            if not active:
                print("종목 목록을 구하지 못했습니다.")
                return 1
            build(conn, active, delisted, args.years, args.threshold, args.chunk, args.rebuild, args.limit)
            status(conn)
        else:
            import jobs
            _t0, _ok = datetime.now(timezone.utc), False
            try:
                active, delisted = case_universe(False)
                update(conn, active, delisted, args.days, threshold=args.threshold, out=_out)
                status(conn)
                _ok = True
            finally:   # 🛠 운영 현황(2026-10-31): 📜 작업 기록 한 줄 + 🩺 점검표 숫자(실패해도 남김)
                jobs.morning_done(_t0, _ok, out=_out)
    return 0


if __name__ == "__main__":
    import quiet  # noqa: F401  (Streamlit 경고 줄 끄기)
    sys.exit(main())
