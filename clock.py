"""⏰ 시계·반응 규칙 — BRAI식 공시분석의 '규칙으로 되는 부분'(A단계 2026-10-28, 비용 0)

1) PR 소화력 `pr_reactions`: 호재 공시·뉴스가 난 날(또는 고가 +20%↑ 급등일)마다 장중 고가 %(세션 고점 포함) vs 종가 % · 되돌림 비율(fade) → 회차별로 "호재 뒤 고점을 지키는 힘"이 약해지는지
2) 하락 원인 `drop_cause`: 공매 잔고(%)·대차비용(%)·숏볼륨(%) → "현물 매도 추정" / "공매 눌림 가능" / "보류"
3) 다음 보고 기한 `report_due`: SEC submissions 의 회계연도 말(fiscalYearEnd)·신고자 구분(category)·20-F 발행사 여부 → 10-K/20-F·10-Q 법정기한 + NT 연장일, D-day
4) 사모 희석 계산 `pipe_sim`: 필요 금액을 N% 할인 사모로 조달하면 필요한 주식 수 = 유통주식의 몇 %
5) 사다리 보강 `extra_levels`: 50일선 · 최근 PR 고점(공급벽) · PR 직전 종가 · 사모 할인가
컨닝 없음: 모두 '그날까지' 표만 쓴다(as_of 인자). 숫자는 추정이며 출처(공시일)를 함께 둔다.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import db

BIG_MOVE_PCT = 20.0        # 공시·뉴스가 없어도 고가 +20%↑ 인 날은 'PR/급등일'로 본다
FEE_HIGH, SI_LOW, SV_HIGH = 50.0, 5.0, 60.0
DDL = """CREATE TABLE IF NOT EXISTS report_due (ticker TEXT PRIMARY KEY, fye TEXT, category TEXT, fpi INTEGER, next_form TEXT, period_end TEXT, due TEXT, nt_due TEXT,
         last_annual TEXT, updated_at TEXT)"""


def ensure(conn) -> None:
    conn.execute(DDL)


# ---------------------------------------------------------------- 1) PR 소화력
def _daily(conn, t: str, since: str, until: str) -> pd.DataFrame:
    rows = conn.execute("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? AND date BETWEEN ? AND ? ORDER BY date", (t, since, until)).fetchall()
    d = pd.DataFrame([tuple(r) for r in rows], columns=["date", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def _ext_highs(conn, t: str, since: str) -> dict[str, float]:
    try:
        return {r[0]: max(float(x) for x in r[1:] if x) for r in conn.execute("SELECT date, night_high, pre_high, reg_high, post_high FROM ext_hilo WHERE ticker=? AND date >= ?", (t, since))
                if any(r[1:])}
    except Exception:  # noqa: BLE001
        return {}


def event_days(conn, t: str, since: str, until: str) -> dict[str, str]:
    """{날짜: 사유} — 호재 공시(8-K·6-K 호재/약한 호재/강한 호재) · 호재 뉴스."""
    out: dict[str, str] = {}
    try:
        for form, d0, sent, tags in conn.execute("SELECT form, COALESCE(filed, substr(updated,1,10)), sentiment, tags FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) BETWEEN ? AND ?", (t, since, until)):
            if sent and "호재" in sent:
                try:
                    tg = ", ".join(json.loads(tags or "[]")[:2])
                except Exception:  # noqa: BLE001
                    tg = ""
                out.setdefault(d0, f"공시 {form} {sent}" + (f"({tg})" if tg else ""))
    except Exception:  # noqa: BLE001
        pass
    try:
        for d0, title, sent in conn.execute("SELECT substr(published,1,10), title, sentiment FROM news WHERE ticker=? AND substr(published,1,10) BETWEEN ? AND ?", (t, since, until)):
            if sent and "호재" in sent:
                out.setdefault(d0, f"뉴스 호재 {(title or '')[:40]}")
    except Exception:  # noqa: BLE001
        pass
    return out


def pr_reactions(conn, t: str, as_of: str | None = None, days: int = 240) -> dict:
    """PR·급등일마다 반응. 반환 {"rows": [...최신순], "n", "trend": '약해짐'|'비슷'|'강해짐'|None, "note"}.
    행: date, why, prev, high, close, hi_pct, close_pct, fade(0=고점 그대로 마감 · 1=상승분 전부 반납 · >1 전일보다 아래 마감)."""
    t = t.upper()
    until = as_of or date.today().isoformat()
    since = (date.fromisoformat(until) - timedelta(days=days)).isoformat()
    d = _daily(conn, t, (date.fromisoformat(since) - timedelta(days=7)).isoformat(), until)
    if len(d) < 3:
        return {"rows": [], "n": 0, "trend": None, "note": "일봉 부족"}
    ext = _ext_highs(conn, t, since)
    ev = event_days(conn, t, since, until)
    d["prev"] = d["close"].shift(1)
    rows = []
    reacted: dict[str, bool] = {}
    for i in range(1, len(d)):
        r = d.iloc[i]
        prev = r["prev"]
        if prev is None or pd.isna(prev) or prev <= 0 or pd.isna(r["close"]) or r["date"] < since:
            continue
        hi = max(float(r["high"] if not pd.isna(r["high"]) else 0), float(ext.get(r["date"], 0) or 0))
        hi_pct = (hi / prev - 1) * 100
        why = ev.get(r["date"])
        if why is not None:
            reacted[r["date"]] = hi_pct >= 5
            if hi_pct < 5:      # 호재가 났는데 고가가 +5% 도 안 되면 '반응 없음'으로 따로 센다
                why += " · 반응 없음"
        else:
            pdt = d.iloc[i - 1]["date"]
            if hi_pct >= 5 and pdt in ev and not reacted.get(pdt):   # 장 마감 뒤 공시 → 다음날 반응
                why = f"전날 {ev[pdt]}"
            elif hi_pct >= BIG_MOVE_PCT:
                why = f"급등일(고가 +{hi_pct:.0f}%)"
            else:
                continue
        close_pct = (float(r["close"]) / prev - 1) * 100
        fade = None if hi <= prev else (hi - float(r["close"])) / (hi - prev)
        rows.append({"date": r["date"], "why": why, "prev": float(prev), "high": hi, "close": float(r["close"]), "hi_pct": hi_pct, "close_pct": close_pct,
                     "fade": None if fade is None else float(fade), "volume": float(r["volume"] or 0)})
    rows = rows[::-1]
    fades = [x["fade"] for x in rows if x["fade"] is not None and x["hi_pct"] >= 10][:4]
    trend = None
    if len(fades) >= 2:
        trend = "약해짐" if fades[0] > fades[1] + 0.15 else ("강해짐" if fades[0] < fades[1] - 0.15 else "비슷")
    note = ""
    if rows:
        last = rows[0]
        note = f"최근 {last['date']} {last['why']}: 장중 {last['hi_pct']:+.0f}% → 종가 {last['close_pct']:+.0f}%" + (f" (상승분 {min(last['fade'], 2) * 100:.0f}% 반납)" if last["fade"] is not None else "")
        if trend:
            note += f" · 고점 지키는 힘 {trend}"
    return {"rows": rows[:12], "n": len(rows), "trend": trend, "note": note}


# ---------------------------------------------------------------- 2) 하락 원인
def drop_cause(conn, t: str) -> dict:
    """공매 잔고·대차비용·숏볼륨으로 '하락이 공매인가 현물 매도인가'. 반환 {"verdict", "why", "si_pct", "fee", "sv_pct"}."""
    t = t.upper()
    si = fee = sv = None
    try:
        r = conn.execute("SELECT si_pct FROM short_interest WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        si = None if not r or r[0] is None else float(r[0])
    except Exception:  # noqa: BLE001
        pass
    try:
        r = conn.execute("SELECT fee FROM ibkr_borrow WHERE symbol=?", (t,)).fetchone()
        fee = None if not r or r[0] is None else float(r[0])
    except Exception:  # noqa: BLE001
        pass
    try:
        r = conn.execute("SELECT short_pct FROM cx_short_volume WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        sv = None if not r or r[0] is None else float(r[0])
    except Exception:  # noqa: BLE001
        pass
    if si is None and fee is None and sv is None:
        return {"verdict": "자료 없음", "why": "공매 잔고·대차비용·숏볼륨 자료가 아직 없어요", "si_pct": si, "fee": fee, "sv_pct": sv}
    bits = []
    if si is not None:
        bits.append(f"공매 잔고 {si:.1f}%")
    if fee is not None:
        bits.append(f"대차비용 {fee:.0f}%")
    if sv is not None:
        bits.append(f"숏볼륨 {sv:.0f}%")
    why = " · ".join(bits)
    if si is not None and si < SI_LOW and (fee or 0) >= FEE_HIGH:
        return {"verdict": "현물 매도 추정", "why": why + " → 빌릴 주식이 거의 없고 비싸서 새 공매도가 어려움. 하락은 보유자 매도(차익실현·사모 투자자 출회)일 가능성", "si_pct": si, "fee": fee, "sv_pct": sv}
    if (sv or 0) >= SV_HIGH or (si or 0) >= 15:
        return {"verdict": "공매 눌림 가능", "why": why + " → 매도 체결의 절반 넘게가 공매 또는 잔고가 큼", "si_pct": si, "fee": fee, "sv_pct": sv}
    return {"verdict": "보류", "why": why + " → 한쪽으로 단정하기 어려움", "si_pct": si, "fee": fee, "sv_pct": sv}


# ---------------------------------------------------------------- 3) 다음 보고 기한
def _add_months(d: date, m: int) -> date:
    y, mo = d.year + (d.month - 1 + m) // 12, (d.month - 1 + m) % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
    return date(y, mo, min(d.day, last))


def _bday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _filer_days(cat: str) -> tuple[int, int]:
    """신고자 구분 → (연차 보고 기한 일수, 분기 보고 기한 일수). SEC category 는 'Non-accelerated filer<br>Smaller reporting company' 처럼 여러 개가 붙어 오므로 부분 일치."""
    c = (cat or "").lower()
    if "large accelerated" in c:
        return 60, 40
    if "accelerated filer" in c and "non-accelerated" not in c:
        return 75, 40
    return 90, 45


def report_due(sub: dict, today: date | None = None) -> dict | None:
    """SEC submissions JSON → 다음 정기 보고 기한. {fye, category, fpi, next_form, period_end, due, nt_due, dday, last_annual}.
    규칙: 20-F = 회계연도 말 + 4개월(NT +15일) · 10-K = 60/75/90일(대형 가속/가속/비가속, NT +15) · 10-Q = 분기 말 + 40/45일(NT +5)."""
    today = today or date.today()
    fye = str(sub.get("fiscalYearEnd") or "").strip()
    if len(fye) != 4 or not fye.isdigit():
        return None
    cat = re.sub(r"<br\s*/?>", " · ", str(sub.get("category") or "")).strip(" ·")   # SEC 는 구분을 <br> 로 이어 줌
    forms = sub.get("filings", {}).get("recent", {}).get("form", []) or []
    dates = sub.get("filings", {}).get("recent", {}).get("filingDate", []) or []
    fpi = any(f in ("20-F", "20-F/A", "6-K") for f in forms[:200])
    annual_forms = ("20-F", "20-F/A") if fpi else ("10-K", "10-K/A", "10-KT")
    last_annual = next((d for f, d in zip(forms, dates) if f in annual_forms), None)
    mm, dd = int(fye[:2]), int(fye[2:])
    # 가장 최근에 지난 회계연도 말
    fy_end = date(today.year, mm, min(dd, 28 if mm == 2 else dd))
    if fy_end > today:
        fy_end = date(today.year - 1, mm, min(dd, 28 if mm == 2 else dd))
    cands = []
    if fpi:
        due = _bday(_add_months(fy_end, 4))
        if not (last_annual and last_annual > fy_end.isoformat()):
            cands.append(("20-F", fy_end, due, _bday(due + timedelta(days=15))))
        else:   # 올해 20-F 는 냈음 → 다음 회계연도
            nxt = _add_months(fy_end, 12)
            cands.append(("20-F", nxt, _bday(_add_months(nxt, 4)), _bday(_add_months(nxt, 4) + timedelta(days=15))))
    else:
        a_days, q_days = _filer_days(cat)
        if not (last_annual and last_annual > fy_end.isoformat()):
            due = _bday(fy_end + timedelta(days=a_days))
            cands.append(("10-K", fy_end, due, _bday(due + timedelta(days=15))))
        for k in (3, 6, 9, 15, 18, 21):   # 분기 말(올해·내년)
            q_end = _add_months(fy_end, k)
            due = _bday(q_end + timedelta(days=q_days))
            if due >= today - timedelta(days=5):
                cands.append(("10-Q", q_end, due, _bday(due + timedelta(days=5))))
        nxt = _add_months(fy_end, 12)
        cands.append(("10-K", nxt, _bday(nxt + timedelta(days=a_days)), _bday(nxt + timedelta(days=a_days + 15))))
    cands = [c for c in cands if c[2] >= today - timedelta(days=5)]
    if not cands:
        return None
    form, pe, due, nt = sorted(cands, key=lambda c: c[2])[0]
    return {"fye": fye, "category": cat or "-", "fpi": bool(fpi), "next_form": form, "period_end": pe.isoformat(), "due": due.isoformat(), "nt_due": nt.isoformat(),
            "dday": (due - today).days, "last_annual": last_annual}


def report_due_cached(conn, t: str, client=None, max_age_days: int = 3) -> dict | None:
    """DB 캐시(report_due 표) → 없거나 오래되면 client 로 받아 저장. client 없으면 캐시만."""
    ensure(conn)
    t = t.upper()
    r = conn.execute("SELECT * FROM report_due WHERE ticker=?", (t,)).fetchone()
    if r:
        d = dict(r)
        try:
            fresh = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(d["updated_at"].replace("Z", "").replace("+00:00", ""))).days < max_age_days
        except Exception:  # noqa: BLE001
            fresh = False
        if fresh or client is None:
            if d.get("due"):
                d["dday"] = (date.fromisoformat(d["due"]) - date.today()).days
            d["fpi"] = bool(d.get("fpi"))
            return d if d.get("due") else None
    if client is None:
        return None
    try:
        cik = client.cik_for(t)
        if not cik:
            return None
        info = report_due(client.submissions(cik))
    except Exception:  # noqa: BLE001
        return None
    if not info:
        return None
    conn.execute("INSERT OR REPLACE INTO report_due VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (t, info["fye"], info["category"], int(info["fpi"]), info["next_form"], info["period_end"], info["due"], info["nt_due"], info["last_annual"], db.utcnow_iso()))
    conn.commit()
    return info


def refresh_due(conn, client, tickers: list[str], out=print, limit: int = 60) -> int:
    n = 0
    todo = list(dict.fromkeys(str(t).upper() for t in tickers if t))[:limit]
    for t in todo:
        if report_due_cached(conn, t, client):
            n += 1
    out(f"⏰ 보고 기한: {n}/{len(todo)}종목 갱신")
    return n


# ---------------------------------------------------------------- 4) 사모 계산 · 5) 사다리 보강
def pipe_sim(price: float | None, amount_usd: float | None, float_shares: float | None, shares_out: float | None, discount_pct: float = 20.0) -> dict | None:
    if not price or not amount_usd or price <= 0:
        return None
    px = price * (1 - discount_pct / 100)
    sh = amount_usd / px
    return {"discount_pct": discount_pct, "price": px, "shares": sh, "amount_usd": amount_usd,
            "pct_float": None if not float_shares else sh / float_shares * 100, "pct_out": None if not shares_out else sh / shares_out * 100}


def extra_levels(conn, t: str, price: float | None, df=None, amount_usd: float | None = None, float_shares: float | None = None, shares_out: float | None = None,
                 as_of: str | None = None) -> list[dict]:
    """사다리에 보탤 가격대: 50일선 · 최근 PR 고점(공급벽) · PR 직전 종가 · 사모 20% 할인가."""
    lv = []
    if df is not None and not df.empty and "Close" in df:
        c = df["Close"].dropna()
        if len(c) >= 50:
            lv.append({"price": float(c.tail(50).mean()), "label": "50일 이동평균", "note": "세력이 주도해야 넘는 선(키쟈키라)", "kind": "ref"})
    try:
        pr = pr_reactions(conn, t, as_of)
        big = [x for x in pr["rows"] if x["hi_pct"] >= 15]
        if big:
            last = big[0]
            lv.append({"price": last["high"], "label": f"{last['date'][5:].replace('-', '/')} PR 고점 · 공급벽", "note": f"장중 {last['hi_pct']:+.0f}% → 종가 {last['close_pct']:+.0f}%", "kind": "ref"})
            lv.append({"price": last["prev"], "label": "PR 직전 종가", "note": "되돌림이 머무는 자리", "kind": "ref"})
    except Exception:  # noqa: BLE001
        pass
    sim = pipe_sim(price, amount_usd, float_shares, shares_out)
    if sim:
        note = f"${sim['amount_usd'] / 1e6:.1f}M 조달 시 {sim['shares'] / 1e6:.2f}M주" + (f" = 유통주식의 {sim['pct_float']:.0f}%" if sim["pct_float"] is not None else "")
        lv.append({"price": sim["price"], "label": "사모 20% 할인가(가정)", "note": note, "kind": "pipe"})
    for x in lv:
        x["pct"] = None if not price else (x["price"] / price - 1) * 100
    return lv


def rule_block(conn, t: str, price: float | None, df=None, client=None, amount_usd: float | None = None, float_shares: float | None = None,
               shares_out: float | None = None, as_of: str | None = None) -> dict:
    """🏢 종목 화면·공시분석 프롬프트용 묶음(as_of 를 주면 그날까지 자료만)."""
    return {"pr": pr_reactions(conn, t, as_of), "drop": drop_cause(conn, t), "due": report_due_cached(conn, t, client),
            "levels": extra_levels(conn, t, price, df, amount_usd, float_shares, shares_out, as_of), "pipe": pipe_sim(price, amount_usd, float_shares, shares_out)}


def due_targets(conn, n_up: int = 20) -> list[str]:
    """아침에 보고 기한을 받아 둘 종목: 저금통 · 가상매매 보유 · 감시 우선 30 · 급상승 상위 20."""
    out: list[str] = []
    try:
        import piggy
        out += list(piggy.tickers())
    except Exception:  # noqa: BLE001
        pass
    try:
        import papertrade
        out += list(papertrade.open_tickers())
    except Exception:  # noqa: BLE001
        pass
    try:
        import watch
        out += list(watch.scanner_priority())[:30]
    except Exception:  # noqa: BLE001
        pass
    try:
        import mover
        out += [r["ticker"] for r in mover.latest(conn, "up")[1][:n_up] if r.get("ticker")]
    except Exception:  # noqa: BLE001
        pass
    return list(dict.fromkeys(str(t).upper() for t in out if t))


def rule_text(rb: dict) -> str:
    """Claude 공시분석 프롬프트에 넣는 한 덩어리(SEC 원문 아님 · 우리 규칙 계산)."""
    lines = []
    pr = rb.get("pr") or {}
    if pr.get("rows"):
        lines.append("PR·급등일 반응(최신순, 장중 고가 % → 종가 %, 상승분 반납 비율): " + " | ".join(
            f"{r['date']} {r['why'][:28]}: {r['hi_pct']:+.0f}% → {r['close_pct']:+.0f}%" + (f" (반납 {min(r['fade'], 2) * 100:.0f}%)" if r["fade"] is not None else "") for r in pr["rows"][:6]))
        if pr.get("trend"):
            lines.append(f"고점을 지키는 힘: {pr['trend']}")
    dr = rb.get("drop") or {}
    if dr.get("verdict"):
        lines.append(f"하락 원인(규칙): {dr['verdict']} — {dr['why']}")
    due = rb.get("due") or {}
    if due.get("due"):
        lines.append(f"다음 정기 보고: {due['next_form']} 기한 {due['due']} (NT 제출 시 {due['nt_due']}) · 회계연도 말 {due['fye'][:2]}/{due['fye'][2:]} · {due['category']}")
    for x in rb.get("levels") or []:
        lines.append(f"가격대 {x['label']}: ${x['price']:.4f} ({x['note']})")
    return "\n".join(lines)
