"""🎯 회사 압박 선별 — 회사가 주가를 올리거나 자금을 구해야 할 이유가 얼마나 급한지(규칙 기반).

압박 점수: 런웨이(3개월 미만 3 · 6개월 미만 2 · 12개월 미만 1) + $1 상장유지(미달 2, 회복 기한 60일 이내 +1) + baby shelf 대상 1(공개유통시총 7,500만 달러 미만 →
  S-3 발행이 1/3 로 묶여 주가를 올려야 조달이 풀림) + 최근 90일 역분할 1 + 상습 희석(최근 1년 조달·희석 서류 2회↑) 1. 최대 10.
목표가: $1 상장유지에 필요한 상승률, baby shelf 탈출가(7,500만 달러 ÷ 유통주식)까지 상승률.
주의: ATM·ELOC 열림(주가를 안 올려도 팔 수 있음), 출회 가능 물량(물량 장부), 이미 움직임(5일 +50%↑). 매수·매도 권유가 아니다.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta

import pandas as pd

import db
from scoring import baby_shelf

DILUTION_FORMS = ("424B", "S-1", "F-1", "S-3", "F-3", "EFFECT")



def money(v) -> str:
    """$ 금액을 크기에 맞게: $1.2B · $3.4M · $56K · $789 (예전엔 작은 현금이 $0.0M 으로 보였음)."""
    if v is None:
        return "-"
    a = abs(float(v))
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:,.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:,.2f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:,.0f}K"
    return f"{sign}${a:,.0f}"

def candidates(conn) -> list[str]:
    """선별 대상: 최근 스캐너 기록 · 워치리스트 · 저금통 · Reg SHO · 매집 의심 · 최근 병합."""
    out: set[str] = set()
    for sql in ("SELECT DISTINCT ticker FROM daily_snapshots WHERE date >= date('now','-10 day')", "SELECT ticker FROM rs_current",
                "SELECT DISTINCT ticker FROM accum WHERE date=(SELECT MAX(date) FROM accum) AND score >= 5"):
        try:
            out |= {r[0] for r in conn.execute(sql)}
        except Exception:  # noqa: BLE001
            pass
    try:
        import piggy
        import regsho
        import watch
        out |= set(watch.scanner_priority()) | set(piggy.tickers()) | set(regsho.streaks(conn))
    except Exception:  # noqa: BLE001
        pass
    return sorted(out)


def evaluate(t: str, conn, price: float | None, df: pd.DataFrame | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    rep = db.get_report(t) or {}
    rw = rep.get("runway") or {}
    snap = conn.execute("SELECT float_shares, dilution_status, price FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
    import shares as _sh
    fs, fs_tag = _sh.best(t, snap["float_shares"] if snap else None)  # 📐 SEC 표지 주식 수(분할 반영) 우선, 없으면 야후
    dil = snap["dilution_status"] if snap else None
    price = price or (snap["price"] if snap else None)
    press, notes, warn, parts = [], [], [], {}
    m = rw.get("runway_months")
    if m is not None:
        parts["런웨이"] = 3 if m < 3 else 2 if m < 6 else 1 if m < 12 else 0
        press.append(("런웨이", f"{m:.1f}개월 · 현금 {money(rw.get('cash'))}({rw.get('cash_asof') or '-'}) · 월 소진 {money(rw.get('monthly_burn'))}", parts["런웨이"] >= 2))
    else:
        press.append(("런웨이", "종목 리포트 없음(매일 아침 압박 후보는 자동 생성)", False))
    below1 = 0
    if df is not None and not df.empty:
        for x in reversed(df["Close"].dropna().tolist()):
            if x < 1.0:
                below1 += 1
            else:
                break
    notices = [n for n in ((rep.get("company") or {}).get("delisting_notices") or []) if n.get("filed", "") >= (today - timedelta(days=365)).isoformat()]
    ev = [dict(r) for r in conn.execute("SELECT date, kind, title FROM events WHERE ticker=? AND kind IN ('상장유지 기한','상장유지 미달','역분할 시행')", (t,))] if conn.execute(
        "SELECT name FROM sqlite_master WHERE name='events'").fetchone() else []
    deadline = min((e["date"] for e in ev if e["kind"] == "상장유지 기한" and e["date"] >= today.isoformat()), default=None)
    if (price and price < 1) or notices:
        parts["$1 상장유지"] = 2 + (1 if deadline and (date.fromisoformat(deadline) - today).days <= 60 else 0)
        need = (1 / price - 1) * 100 if price and price < 1 else None
        press.append(("상장 유지", ("" if need is None else f"$1까지 +{need:.0f}%") + (f" · $1 미만 {below1}거래일" if below1 else "")
                      + (f" · 미달 통지 {notices[0]['filed']}" if notices else "") + (f" · 회복 기한 {deadline} (D-{(date.fromisoformat(deadline) - today).days})" if deadline else ""), True))
    ln = None
    try:  # 🏛 $1 말고 다른 상장유지 기준(시가총액·자기자본·정기보고서 지연 등) 미달 통지
        import listing
        ln = listing.latest(t)
    except Exception:  # noqa: BLE001
        pass
    if ln and ln["kinds"][0] != "주가 $1 기준":
        dl = ln["deadline"]
        dd = (date.fromisoformat(dl) - today).days
        parts["상장유지(" + ln["kinds"][0].replace(" 기준", "") + ")"] = 2 + (1 if 0 <= dd <= 60 else 0)
        press.append(("상장 유지", f"{ln['kinds'][0]} 미달 통지 {ln['filed']}" + (f" · 기준 {ln['threshold']}" if ln.get("threshold") else "")
                      + f" · 회복 기한 {dl}" + (f" (D-{dd})" if dd >= 0 else " (지남)") + (" · 기한 추정(통지일+180일)" if ln.get("deadline_est") else ""), True))
    bs_px = float(df["Close"].dropna().tail(60).max()) if df is not None and not df.empty else price  # 규정: 최근 60일 안 최고가 기준
    bs = baby_shelf(fs, bs_px)
    if bs and bs["is_baby_shelf"]:
        parts["baby shelf"] = 1
        esc_px = 75e6 / fs if fs else None
        press.append(("ATM·ELOC 잠김", f"baby shelf 대상(공개유통시총 ${bs['public_float_value'] / 1e6:,.1f}M = 주식 {fs / 1e6:,.2f}M주[{fs_tag}] × 60일 최고 ${bs_px:.4f}) — 12개월 발행 상한 약 ${bs['cap'] / 1e6:,.1f}M"
                      + ("" if not esc_px else f" · 탈출가 ${esc_px:.4f}"), True))
    rs = [e for e in ev if e["kind"] == "역분할 시행"]
    try:
        rs += [{"date": r[0], "kind": "역분할(실행)", "title": f"1:{round(1 / r[1]):g}"} for r in conn.execute("SELECT date, ratio FROM rs_events WHERE ticker=? AND date >= ?",
                                                                                               (t, (today - timedelta(days=90)).isoformat()))]
    except Exception:  # noqa: BLE001
        pass
    if rs:
        parts["역분할"] = 1
        notes += [f"역분할 {e['date']} {e.get('title') or ''}".strip() for e in rs[:2]]
    since = (today - timedelta(days=365)).isoformat()
    fin = rep.get("financing") or {}
    n_fin = sum(1 for e in (fin.get("events") if isinstance(fin, dict) else []) or [] if str(e.get("date", "")) >= since)
    try:
        n_dil = conn.execute("SELECT COUNT(*) FROM sec_hist WHERE ticker=? AND filed >= ? AND (" + " OR ".join("form LIKE ?" for _ in DILUTION_FORMS) + ")",
                             (t, since, *[f"{f}%" for f in DILUTION_FORMS])).fetchone()[0]
    except Exception:  # noqa: BLE001
        n_dil = 0
    habit = max(n_fin, n_dil)
    if habit >= 2:
        parts["상습 희석"] = 1
        warn.append(f"상습 희석 — 최근 1년 조달·희석 서류 {habit}회")
    if dil in ("ATM", "ELOC"):
        warn.append(f"{dil} 열림 — 주가를 안 올려도 시장에 팔 수 있음")
    try:
        import watch
        oh = watch.overhang_summary(watch.overhang_rows(t).to_dict("records"), price)
        if oh.get("below_m") and fs:
            warn.append(f"출회 가능 물량 유통의 {oh['below_m'] * 1e6 / fs * 100:.0f}%")
    except Exception:  # noqa: BLE001
        pass
    moved = None
    if df is not None and len(df) > 5:
        c = df["Close"].dropna()
        moved = (float(c.iloc[-1]) / float(c.iloc[-6]) - 1) * 100
        if moved >= 50:
            warn.append(f"이미 움직임 — 5일 {moved:+.0f}%")
    score = float(sum(parts.values()))
    targets = []
    if price and price < 1:
        targets.append(("$1 상장 유지", 1.0, (1 / price - 1) * 100))
    if bs and bs["is_baby_shelf"] and fs:
        targets.append(("baby shelf 탈출", 75e6 / fs, (75e6 / fs / price - 1) * 100 if price else None))
    if ln and ln["kinds"][0] == "상장증권 시가총액 기준" and fs and price:  # 시가총액 기준 회복에 필요한 주가
        import re as _re
        mm = _re.search(r"(\d+(?:\.\d+)?)", ln.get("threshold") or "$35M")
        need_mv = float(mm.group(1)) * 1e6 if mm else 35e6
        targets.append(("시가총액 기준 회복", need_mv / fs, (need_mv / fs / price - 1) * 100))
    stance = "회피" if dil in ("ATM", "ELOC") and (m is not None and m < 6) else ("보통" if score >= 4 else "대기")
    return {"ticker": t, "price": price, "score": score, "parts": parts, "press": press, "notes": notes, "warn": warn, "targets": targets,
            "atm_open": dil in ("ATM", "ELOC"), "stance": stance, "has_report": bool(rep), "moved5": moved, "shares": fs, "shares_tag": fs_tag, "listing": ln}


def scan(conn, prices: dict, limit: int | None = None) -> list[dict]:
    out = []
    for t in candidates(conn)[: limit or None]:
        try:
            r = evaluate(t, conn, None, prices.get(t))
        except Exception:  # noqa: BLE001
            continue
        if r["score"] > 0:
            out.append(r)
    return sorted(out, key=lambda r: (-r["score"], r["ticker"]))


def build_missing_reports(client, max_n: int = 25, out=print) -> int:
    """압박 후보 중 종목 리포트가 없거나 7일 지난 종목의 리포트를 만든다(매일 아침, 상한)."""
    import report
    n = 0
    with closing(db.connect()) as conn:
        for t in candidates(conn):
            if n >= max_n:
                break
            rep = db.get_report(t)
            if rep and str(rep.get("generated_at", ""))[:10] >= (date.today() - timedelta(days=7)).isoformat():
                continue
            try:
                db.save_report(t, report.build_report(client, conn, t))
                n += 1
            except Exception:  # noqa: BLE001
                continue
    out(f"회사 압박 후보 종목 리포트 {n}개 생성")
    return n
