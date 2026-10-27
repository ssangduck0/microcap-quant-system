"""🪙 런웨이 저장소 — 종목 리포트·펀드스캔 딜이 없어도 SEC 재무(현금·영업현금흐름)로 '지금 추정 현금'과 '현금 바닥 날짜'를 계산.

예전엔 런웨이가 '종목 리포트(85종목)'와 '최근 400일 펀드스캔 딜(150종목)'이 둘 다 있는 종목만 나와 1,654종목 중 3개뿐이었다.
- 자료: 종목 리포트(30일 안이면 우선) → 이 저장소(fs_runway, SEC companyfacts) → 오래된 리포트
- 지금 추정 현금 = 재무 기준일 현금 − 월 소모량 × 지난 개월 + 그 뒤 조달액(펀드스캔 딜)
- 표시: 흑자(현금 소모 없음) · 추정 현금 소진(조달 여부 확인) · 오래된 재무(기준일 200일↑ — 분기 보고 지연일 수 있음)
매일 아침 갱신이 PICK 통과 종목 → 회사 압박 후보 순으로 하루 상한만큼 채운다. 지금 바로: python runway.py 60
"""
from __future__ import annotations

import json
import sys
from contextlib import closing
from datetime import date, timedelta

import db

DDL = "CREATE TABLE IF NOT EXISTS fs_runway (ticker TEXT PRIMARY KEY, data TEXT, updated TEXT)"
FRESH_DAYS = 14      # 이 기간 안에 받은 자료는 다시 받지 않음
STALE_DAYS = 200     # 재무 기준일이 이보다 오래되면 '오래된 재무'
REPORT_FRESH = 30    # 종목 리포트가 이보다 새것이면 리포트 값을 우선


def ensure(conn) -> None:
    conn.execute(DDL)


def save(conn, ticker: str, rw: dict) -> None:
    ensure(conn)
    conn.execute("INSERT OR REPLACE INTO fs_runway VALUES (?,?,?)", (ticker.upper(), json.dumps(rw or {}, ensure_ascii=False), db.utcnow_iso()))


def raw(t: str, conn) -> tuple[dict, str] | tuple[None, None]:
    """(런웨이 원자료, 출처). 현금과 기준일이 있는 것만."""
    t = t.upper()
    rep, rep_at = None, ""
    try:
        r = conn.execute("SELECT payload, generated_at FROM reports WHERE ticker=?", (t,)).fetchone()
        if r:
            rep, rep_at = (json.loads(r[0]) or {}).get("runway") or {}, r[1] or ""
    except Exception:  # noqa: BLE001
        pass
    ok = lambda x: bool(x) and x.get("cash") is not None and x.get("cash_asof")  # noqa: E731
    if ok(rep) and rep.get("v") == 4 and rep_at >= (date.today() - timedelta(days=REPORT_FRESH)).isoformat():  # 새 계산 방식(최근 12개월) 리포트만 우선
        return rep, "종목 리포트"
    try:
        ensure(conn)
        r = conn.execute("SELECT data FROM fs_runway WHERE ticker=?", (t,)).fetchone()
        fx = json.loads(r[0]) if r else None
    except Exception:  # noqa: BLE001
        fx = None
    if ok(fx):
        return fx, "SEC 재무"
    if ok(rep):
        return rep, "종목 리포트(오래됨)"
    return None, None


def now(t: str, conn, deals: list[dict] | None = None, today: date | None = None) -> dict | None:
    """지금 추정 런웨이. 자료가 없으면 None."""
    rw, src = raw(t, conn)
    if not rw:
        return None
    today = today or date.today()
    cash, burn, asof = float(rw["cash"]), rw.get("monthly_burn"), rw["cash_asof"]
    if deals is None:
        try:
            deals = [dict(x) for x in conn.execute("SELECT filed, proceeds FROM fs_deals WHERE ticker=? AND filed > ?", (t.upper(), asof))]
        except Exception:  # noqa: BLE001
            deals = []
    raised = sum(d.get("proceeds") or 0 for d in deals if (d.get("filed") or "") > asof)
    months = max(0.0, (today - date.fromisoformat(asof)).days / 30.4)
    out = {"source": src, "cash": cash, "cash_asof": asof, "monthly_burn": burn, "months_elapsed": months, "raised_after": raised,
           "runway_report": rw.get("runway_months"), "stale": (today - date.fromisoformat(asof)).days > STALE_DAYS,
           "profitable": burn is not None and burn <= 0, "form": ((rw.get("cash_source") or {}).get("form") or ""), "burn_basis": rw.get("burn_basis"), "cash_now": None, "runway_now": None, "floor": None, "exhausted": False}
    if burn and burn > 0:
        cash_now = cash - burn * months + raised
        out["cash_now"] = cash_now
        out["runway_now"] = max(0.0, cash_now / burn)
        out["exhausted"] = cash_now <= 0
        out["floor"] = months_to_date(today, out["runway_now"])  # 50년 넘으면 None(바닥 없음)
    return out


MAX_FLOOR_MONTHS = 600   # 런웨이가 50년을 넘으면 '현금 바닥 없음'으로 봄(월 소모량이 아주 작은 회사 → 수천 년 → 날짜 계산이 넘쳐 화면이 멈추던 문제)


def months_to_date(base: date, months) -> str | None:
    """기준일 + n개월 → 'YYYY-MM-DD'. 숫자가 아니거나(무한·NaN) 50년을 넘으면 None."""
    import math
    try:
        m = float(months)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(m) or m < 0 or m > MAX_FLOOR_MONTHS:
        return None
    try:
        return (base + timedelta(days=int(m * 30.4))).isoformat()
    except (OverflowError, ValueError):
        return None


def label(r: dict | None) -> str:
    """이유 칸에 쓰는 짧은 말."""
    if not r:
        return "런웨이 미확인"
    if r["stale"]:  # 추정이 믿기 어려움 → 판정에 안 씀
        if (r.get("form") or "").upper().startswith(("20-F", "40-F")):  # 해외 기업: 1년에 한 번 재무(지연 아님)
            return f"해외 기업 연차 재무 {r['cash_asof']} 기준(중간 재무 없음 · 원문 확인)"
        return f"재무 {r['cash_asof']} 기준(오래됨 · 분기 보고 지연 확인)"
    tail = ""
    if r["profitable"]:
        return "현금 소모 없음(영업 흑자)" + tail
    if r["exhausted"]:
        return f"추정 현금 소진(재무 {r['cash_asof']} 기준 · 그 뒤 조달 확인)"
    if r["runway_now"] is not None and r["runway_now"] > MAX_FLOOR_MONTHS:
        return "런웨이 50년 넘음(현금 소모 아주 적음)" + tail
    return f"런웨이 {r['runway_now']:.1f}개월" + tail


def refresh(client, tickers: list[str], limit: int = 80, out=print) -> dict:
    """자료가 없거나 오래된 종목만 SEC companyfacts 를 받아 저장(앞쪽 종목 우선). 자료 없는 회사도 기록해 2주간 다시 안 받음."""
    import report
    n = miss = 0
    with closing(db.connect()) as conn:
        ensure(conn)
        fresh = {r[0] for r in conn.execute("SELECT ticker FROM fs_runway WHERE updated >= ? AND data LIKE '%\"v\": 4%'",  # 예전 방식(v 없음)은 다시 받음
                                            ((date.today() - timedelta(days=FRESH_DAYS)).isoformat(),))}
        seen, todo = set(), []
        for t in tickers:
            t = (t or "").upper()
            if t and t not in seen and t not in fresh:
                seen.add(t)
                todo.append(t)
        for t in todo[:limit]:
            try:
                cik = client.cik_for(t)
                rw = report.runway_from_facts(client.companyfacts(cik)) if cik else {}
            except Exception as e:  # noqa: BLE001
                rw = {"error": str(e)[:120], "v": 4}  # 버전을 넣어야 2주간 다시 안 받음
            save(conn, t, rw)
            n += 1
            miss += 0 if rw.get("cash") is not None else 1
        conn.commit()
    out(f"런웨이 채우기: {n}종목 받음(재무 없음 {miss}) · 남은 대상 {max(0, len(todo) - limit)}")
    return {"fetched": n, "missing": miss, "left": max(0, len(todo) - limit)}


def targets(s: dict | None = None) -> list[str]:
    """채울 순서: PICK 통과 종목 → 목표가가 있는 종목 → 회사 압박 후보. s = 이미 계산한 pick30.scan() 결과(없으면 계산)."""
    import pick30
    import pressure
    s = s or pick30.scan()
    first = [r["ticker"] for r in s["pass"]] + [r["ticker"] for r in s["fail"] if r["target"]]
    with closing(db.connect()) as c:
        rest = pressure.candidates(c)
    return first + rest


if __name__ == "__main__":  # 지금 바로 채우기: python runway.py [개수]
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    import logging
    import os
    os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")  # 화면 없이 실행할 때 나오는 경고 줄 숨김
    try:
        import streamlit.logger as _stl
        _stl.set_log_level("error")
    except Exception:  # noqa: BLE001
        pass
    logging.getLogger().addFilter(lambda rec: not rec.name.startswith("streamlit"))
    import config
    config.apply_overrides()
    import sec
    if "@" not in config.SEC_USER_AGENT:
        sys.exit("SEC_USER_AGENT(.env)에 이메일이 있어야 SEC 재무를 받을 수 있어요.")
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print("대상 고르는 중(PICK 계산, 1~2분)...")
    refresh(sec.SecClient(config.SEC_USER_AGENT), targets(), limit=lim)
