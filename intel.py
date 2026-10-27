"""종목 공통 인텔 — 모든 화면(퀀트 스냅샷·종목 상세·종목 리포트·장마감 체크리스트)이 같은 값을 쓰도록 한곳에서 계산·저장한다.

  체결강도: 토스 실시간 웹소켓(체결가를 그 순간의 호가와 비교 = 토스 호가창 방식). 구독 못 한 종목은 토스 1분봉 방향으로 추정(표시됨)
  거래정지: 업킷 API(실패 시 나스닥 RSS) — 하킷·상킷(LULD 방향은 정지 직전 1분봉 가격과 밴드 가격 비교)
  공매도:   FINRA 일별 공매도 거래량 + IBKR 대차 수수료·가능 수량(무료, shortdata.py). Fintel 키가 있으면 공매도 잔고 등을 보탬
  공시:     SEC 키워드 — 오늘 장중 희석 공시, 최근 7일 자금조달 유형과 출회 제한 여부, 최근 7일 워런트 (원문 확인 필요)
스캐너가 사이클마다 그 사이클에 저장한 모든 종목(장마감 후보가 앞쪽)을 계산해 ticker_intel 에 저장한다.
SEC 는 종목당 10분, (선택) Fintel 은 종목당 20분마다 다시 확인하고 사이클당 종목 수에 상한을 둔다(나머지는 직전 값 유지).
장마감 체크리스트의 고유 판정(과대 낙폭·거래량 폭발→감소·체강 상승 추세·호가 얇아짐·매도벽·공급 제한·등급)은 closewatch 에만 있다.
"""
from __future__ import annotations

import json
import logging
import time as _time
from contextlib import closing
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import closewatch as cw
import db
import halts

log = logging.getLogger("intel")
ET = ZoneInfo("America/New_York")
DDL = "CREATE TABLE IF NOT EXISTS ticker_intel (date TEXT NOT NULL, ticker TEXT NOT NULL, data TEXT, updated_at TEXT, PRIMARY KEY (date, ticker))"
SEC_TTL = 600.0
FINTEL_TTL = 1200.0
NO_FINTEL = "공매도 데이터 미연결"
_SEC_AT: dict = {}
_FIN_AT: dict = {}


def ensure_table(conn=None) -> None:
    if conn is None:
        with closing(db.connect()) as c:
            ensure_table(c)
        return
    conn.execute(DDL)
    conn.commit()
    cw.ensure_tables(conn)  # 체결강도 집계(close_flow)·공시 캐시 테이블도 필요(장마감 체크리스트가 한 번도 안 돈 새 DB 대비)


def get(conn, day: str, ticker: str) -> dict | None:
    ensure_table(conn)
    r = conn.execute("SELECT data FROM ticker_intel WHERE date=? AND ticker=?", (day, ticker)).fetchone()
    return json.loads(r["data"]) if r else None


def latest(conn, ticker: str) -> tuple[str, dict, str] | None:
    """가장 최근 날짜의 (날짜, 데이터, 갱신 시각)."""
    ensure_table(conn)
    r = conn.execute("SELECT date, data, updated_at FROM ticker_intel WHERE ticker=? ORDER BY date DESC LIMIT 1", (ticker,)).fetchone()
    return (r["date"], json.loads(r["data"]), r["updated_at"]) if r else None


def save(conn, day: str, ticker: str, data: dict) -> None:
    ensure_table(conn)
    conn.execute("INSERT OR REPLACE INTO ticker_intel (date,ticker,data,updated_at) VALUES (?,?,?,?)",
                 (day, ticker, json.dumps(data, ensure_ascii=False, default=str), db.utcnow_iso()))
    conn.commit()


def cs_of(conn, day: str, ticker: str, frame) -> dict | None:
    """체결강도: 실시간(웹소켓) 집계가 있으면 그것, 없으면 토스 1분봉 방향 추정."""
    f = cw.flow_stats(conn, day, ticker)
    if f and (f.get("cs_late") is not None or f.get("cs_cum") is not None):
        return {"late": f["cs_late"], "prior": f["cs_prior"], "cum": f["cs_cum"], "source": "토스 실시간(체결가↔호가)",
                "first": f["flow_first"], "trades": f["flow_trades"]}
    if frame is not None and len(frame) >= 10:
        bs = cw.buy_stats(frame)
        late, prior = cw.buy_ratio_to_cs(bs["buy_late"]), cw.buy_ratio_to_cs(bs["buy_prior"])
        if late is not None or prior is not None:
            return {"late": late, "prior": prior, "cum": None, "source": "1분봉 추정(실시간 미수신)"}
    return None


def sec_due(ticker: str, now_s: float) -> bool:
    return now_s - _SEC_AT.get(ticker, 0.0) >= SEC_TTL


def compute(conn, client, tickers: list[str], frames: dict | None = None, halts_list: list | None = None, fintel_client=None, daily: dict | None = None,
            sec_budget: int = 60, fintel_budget: int = 20, now: datetime | None = None) -> dict[str, dict]:
    """tickers(우선순위 순서)의 인텔을 계산해 저장하고 {티커: 데이터} 를 돌려준다."""
    ensure_table(conn)
    frames = frames or {}
    now = now or datetime.now(timezone.utc)
    now_s = now.timestamp()
    out: dict[str, dict] = {}
    for t in dict.fromkeys(tickers):
        try:
            frame = frames.get(t)
            d = frame.index[-1].astimezone(ET).date() if frame is not None and len(frame) else now.astimezone(ET).date()
            day = d.isoformat()
            prev = get(conn, day, t) or {}
            data = {"day": day, "cs": cs_of(conn, day, t, frame) or prev.get("cs"),
                    "spark": spark_of(frame) or prev.get("spark"), "cs_spark": cs_spark_of(conn, day, t) or prev.get("cs_spark")}
            if halts_list is not None:
                data["halt"] = {**halts.summarize(halts_list, t, d, cw.regular(frame) if frame is not None else None), "src": halts.last_source}
            else:
                data["halt"] = prev.get("halt")
            if sec_budget > 0 and sec_due(t, now_s):
                sec_budget -= 1
                _SEC_AT[t] = now_s
                try:
                    data["sec"] = cw.sec_context(client, conn, t, d)
                except Exception as e:  # noqa: BLE001
                    log.warning("%s SEC 장중 공시 확인 실패: %s", t, e)
                    data["sec"] = {"error": f"SEC 조회 실패: {type(e).__name__}"}
                data["sec_at"] = now.isoformat(timespec="seconds")
            else:
                data["sec"], data["sec_at"] = prev.get("sec"), prev.get("sec_at")
            if fintel_client is None:
                data["short"], data["short_note"], data["short_at"] = None, NO_FINTEL, None
            elif hasattr(fintel_client, "fintel"):  # 무료 출처(shortdata.ShortClient): 매 사이클 모든 종목. Fintel 부분만 한도·주기 적용
                use_fin = fintel_client.fintel is not None and fintel_budget > 0 and now_s - _FIN_AT.get(t, 0.0) >= FINTEL_TTL
                if use_fin:
                    fintel_budget -= 1
                    _FIN_AT[t] = now_s
                try:
                    s = fintel_client.summary(t, include_fintel=use_fin)
                    if not use_fin and prev.get("short"):  # 이번에 Fintel 을 안 불렀으면 직전 공매도 잔고(si_*)를 유지
                        for k in ("si_date", "si_shares", "si_pct_float", "si_dtc"):
                            if s.get(k) is None and prev["short"].get(k) is not None:
                                s[k] = prev["short"][k]
                    data["short"] = s if any(s.get(k) is not None for k in ("sv_ratio", "borrow_fee", "borrow_avail", "si_shares")) else None
                    data["short_note"] = "; ".join(s.get("errors") or []) or None
                except Exception as e:  # noqa: BLE001
                    log.warning("%s 공매도 데이터 조회 실패: %s", t, e)
                    data["short"], data["short_note"] = prev.get("short"), f"공매도 데이터 조회 실패: {type(e).__name__}"
                data["short_at"] = now.isoformat(timespec="seconds")
            elif fintel_budget > 0 and now_s - _FIN_AT.get(t, 0.0) >= FINTEL_TTL:
                fintel_budget -= 1
                _FIN_AT[t] = now_s
                try:
                    s = fintel_client.summary(t)
                    data["short"] = s if any(k in s for k in ("sv_ratio", "borrow_fee", "si_shares")) else None
                    data["short_note"] = "; ".join(s.get("errors") or []) or None
                except Exception as e:  # noqa: BLE001
                    log.warning("%s Fintel 조회 실패: %s", t, e)
                    data["short"], data["short_note"] = prev.get("short"), f"Fintel 조회 실패: {type(e).__name__}"
                data["short_at"] = now.isoformat(timespec="seconds")
            else:
                data["short"], data["short_note"], data["short_at"] = prev.get("short"), prev.get("short_note"), prev.get("short_at")
            save(conn, day, t, data)
            out[t] = data
        except Exception:  # noqa: BLE001
            log.exception("%s 공통 인텔 계산 실패", t)
    return out


def on_demand(conn, client, ticker: str, fintel_client=None, halts_list: list | None = None, today: date | None = None) -> dict:
    """대시보드에서 버튼으로 즉시 조회(토스는 쓰지 않음 — 스캐너의 토스 토큰과 충돌하지 않도록). 체결강도는 기존 값을 유지."""
    today = today or datetime.now(ET).date()
    day = today.isoformat()
    prev = get(conn, day, ticker) or (latest(conn, ticker) or (None, {}, None))[1]
    data = {"day": day, "cs": prev.get("cs")}
    try:
        data["sec"] = cw.sec_context(client, conn, ticker, today)
    except Exception as e:  # noqa: BLE001
        data["sec"] = {"error": f"SEC 조회 실패: {type(e).__name__}"}
    data["sec_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["halt"] = {**halts.summarize(halts_list, ticker, today, None), "src": halts.last_source} if halts_list is not None else prev.get("halt")
    if fintel_client is not None:
        try:
            s = fintel_client.summary(ticker)
            data["short"] = s if any(s.get(k) is not None for k in ("sv_ratio", "borrow_fee", "borrow_avail", "si_shares")) else None
            data["short_note"] = "; ".join(s.get("errors") or []) or None
        except Exception as e:  # noqa: BLE001
            data["short"], data["short_note"] = prev.get("short"), f"공매도 데이터 조회 실패: {type(e).__name__}"
        data["short_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        data["short"], data["short_note"], data["short_at"] = None, NO_FINTEL, None
    save(conn, day, ticker, data)
    return data


# ---------------------------------------------------------------- 화면용 요약(여러 화면이 같은 문구를 쓰도록)
def spark_of(frame, minutes: int = 120, points: int = 40) -> list[float] | None:
    """표 안 미니 차트용: 최근 minutes분 1분봉 종가를 points개로 줄인 값."""
    if frame is None or getattr(frame, "empty", True):
        return None
    c = frame["Close"].dropna().tail(minutes)
    if len(c) < 5:
        return None
    step = max(1, len(c) // points)
    return [round(float(x), 6) for x in c.iloc[::step].tolist()[-points:]]


def cs_spark_of(conn, day: str, ticker: str, minutes: int = 30) -> list[float] | None:
    """표 안 미니 차트용: 최근 minutes분 분당 체결강도(매수 체결 / 매도 체결 × 100, 토스 실시간)."""
    try:
        rows = conn.execute("SELECT buy_sh, sell_sh FROM close_flow WHERE date=? AND ticker=? ORDER BY minute DESC LIMIT ?", (day, ticker, minutes)).fetchall()
    except Exception:  # noqa: BLE001
        return None
    vals = [min(round(r["buy_sh"] / r["sell_sh"] * 100, 1), 500.0) for r in reversed(rows) if r["sell_sh"] and r["buy_sh"] is not None]
    return vals if len(vals) >= 3 else None


def summary_cells(data: dict | None) -> dict:
    """표 한 줄에 넣을 요약 값."""
    if not data:
        return {"체결강도(%)": None, "체강 출처": "", "거래정지": "확인 전", "공매도(전일%)": None, "대차수수료(%)": None, "대차가능 변화(%)": None,
                "장중 희석": "확인 전", "자금조달(7일)": "확인 전", "워런트(7일)": "확인 전", "가격 흐름(2시간)": None, "체결강도(30분)": None}
    cs = data.get("cs") or {}
    h = data.get("halt")
    if h is None:
        halt_txt = "확인 불가"
    elif not h.get("halts"):
        halt_txt = ""
    else:
        halt_txt = f"하킷 {h.get('halt_down', 0)} · 상킷 {h.get('halt_up', 0)}" + (f" · 기타 {h['halt_other']}" if h.get("halt_other") else "") + (" · 🔴정지 중" if h.get("halt_active") else "")
    s = data.get("sec")
    if s is None:
        intr, fin, war = "확인 전", "확인 전", "확인 전"
    elif "error" in s:
        intr = fin = war = "확인 불가"
    else:
        hits = [x for x in s.get("intraday") or [] if [t for t in x.get("tags", []) if t != "WARRANT"]]
        intr = f"❌ {len(hits)}건" if hits else "✅ 없음"
        f = s.get("financing")
        fin = "없음" if not f else f"{f['type']} · {f['label']}"
        w = s.get("warrants") or []
        war = f"⚠️ {len(w)}건" if w else "없음"
    sh = data.get("short") or {}
    return {"체결강도(%)": cs.get("late") if cs.get("late") is not None else cs.get("cum"),
            "체강 출처": ("실시간" if str(cs.get("source", "")).startswith("토스 실시간") else ("추정" if cs else "")),
            "거래정지": halt_txt, "공매도(전일%)": sh.get("sv_ratio"), "대차수수료(%)": sh.get("borrow_fee"), "대차가능 변화(%)": None if sh.get("borrow_stale") else sh.get("borrow_avail_chg_pct"),
            "장중 희석": intr, "자금조달(7일)": fin, "워런트(7일)": war,
            "가격 흐름(2시간)": data.get("spark"), "체결강도(30분)": data.get("cs_spark")}
