"""📇 종목 스크리너 카드 — 남이 추천한 종목(래빗스탁 커뮤니티 등)이나 궁금한 종목을 한 장으로.
① ⚠️ 우리 후보에서 제외된 이유(ATM·ELOC 희석 상태, 상장유지 통지, 완전희석 배수, 낮은 점수) — 맨 위
② 실적 일정·컨센서스(야후: 다음 발표일, 매출·EPS 컨센서스, 직전 분기) + 당일 박스·시총·기준일 대비
③ 이벤트 로그: 공시(최근 수집분 + 과거 이력)·일정·딜·내부자·병합 + 그 뒤 주가 반응(D+1·D+5, 시간외 고점)
④ 레벨 맵(일봉 계산): 1차 저항(20일 고가) · 2차 저항(60일 최고 종가) · 갭 · 당일 박스 · 지지 · 위험 — AI 가 아니라 규칙
⑤ 시나리오·확인 포인트·위험 대비 보상: Claude(Sonnet 5.5, 약 100원) — 🤖 AI 월 예산과 같은 지갑
카드는 종목·날짜별로 저장(같은 날 다시 만들면 교체). 외부 후보는 🏆 성과 공표 '📇 외부 후보' 로 기록해 추천이 맞는지 검증.
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
import db

MODEL = "claude-sonnet-5-5"
DDL = ["""CREATE TABLE IF NOT EXISTS screener_cards (ticker TEXT, date TEXT, card TEXT, source TEXT, PRIMARY KEY (ticker, date))""",
       """CREATE TABLE IF NOT EXISTS ticker_earnings (ticker TEXT PRIMARY KEY, fetched TEXT, next_date TEXT, rev_avg REAL, rev_low REAL, rev_high REAL,
          eps_avg REAL, last_q TEXT, last_rev REAL, last_eps REAL)""",
       """CREATE TABLE IF NOT EXISTS screener_sig (date TEXT, ticker TEXT, price REAL, source TEXT, PRIMARY KEY (date, ticker))"""]
SYSTEM = """당신은 나스닥 초소형주 단기 트레이딩 분석가입니다. 사용자의 시스템이 정리한 한 종목의 자료(JSON)만 보고 '스크리너 카드'의 판단 부분을 씁니다.
자료에 없는 사실·날짜는 쓰지 말고, 숫자·날짜를 근거로 적으세요. 희석(ATM·ELOC·완전희석 배수·현금 바닥)이 있으면 가장 먼저 경고하세요.
반드시 JSON 만 출력:
{"headline":"한 줄 요약(40자 이내)","check_points":["확인 포인트 3개(각 50자 이내)"],
 "scenarios":[{"name":"긍정|중립|부정 또는 상회|부합|하회","condition":"조건(40자)","path":"예상 가격 경로(60자, 레벨 맵 숫자 사용)"}],
 "rr":"위험 대비 보상 한 줄(레벨 맵의 저항·지지로 계산, 예: 1:0.9)","stance":"관망|소량|관심|회피 중 하나","why":"stance 이유(60자)"}"""


def ensure(conn) -> None:
    for d in DDL:
        conn.execute(d)


# ---------------------------------------------------------------- 실적 일정·컨센서스(야후)
def fetch_earnings(t: str, yf_ticker=None) -> dict:
    """다음 실적 발표일 · 매출/EPS 컨센서스 · 직전 분기 매출/EPS(없으면 None)."""
    out = {"next_date": None, "rev_avg": None, "rev_low": None, "rev_high": None, "eps_avg": None, "last_q": None, "last_rev": None, "last_eps": None}
    try:
        if yf_ticker is None:
            import yfinance as yf
            yf_ticker = yf.Ticker(t)
        cal = yf_ticker.calendar or {}
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                d0 = ed[0] if isinstance(ed, (list, tuple)) else ed
                out["next_date"] = str(getattr(d0, "isoformat", lambda: d0)())[:10]
            for k, col in (("rev_avg", "Revenue Average"), ("rev_low", "Revenue Low"), ("rev_high", "Revenue High"), ("eps_avg", "Earnings Average")):
                v = cal.get(col)
                out[k] = None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)
        q = yf_ticker.quarterly_income_stmt
        if q is not None and not q.empty:
            col = q.columns[0]
            out["last_q"] = str(col)[:10]
            for k, row in (("last_rev", "Total Revenue"), ("last_eps", "Diluted EPS")):
                if row in q.index and pd.notna(q.loc[row, col]):
                    out[k] = float(q.loc[row, col])
    except Exception:  # noqa: BLE001
        pass
    return out


def earnings(t: str, conn, yf_ticker=None, max_age_days: int = 3) -> dict:
    """저장본이 3일 안이면 그대로, 아니면 야후에서 받아 저장."""
    ensure(conn)
    r = conn.execute("SELECT * FROM ticker_earnings WHERE ticker=?", (t,)).fetchone()
    if r and r["fetched"] and r["fetched"] >= (date.today() - timedelta(days=max_age_days)).isoformat():
        return dict(r)
    e = fetch_earnings(t, yf_ticker)
    conn.execute("INSERT OR REPLACE INTO ticker_earnings VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (t, date.today().isoformat(), e["next_date"], e["rev_avg"], e["rev_low"], e["rev_high"], e["eps_avg"], e["last_q"], e["last_rev"], e["last_eps"]))
    conn.commit()
    return {"ticker": t, "fetched": date.today().isoformat(), **e}


# ---------------------------------------------------------------- 자료 모으기
def _q(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001
        return []


def exclusion(conn, t: str) -> list[str]:
    """⚠️ 우리 후보에서 빠진 이유들(없으면 빈 목록)."""
    why = []
    snap = _q(conn, "SELECT date, excluded, dilution_status, COALESCE(win_score, quant_score), pump_score FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
    if snap:
        s = snap[0]
        if s[1]:
            why.append(f"스캐너 제외 — 희석 상태 {s[2] or '?'}(수시 증자 프로그램이 살아 있으면 상승이 눌려요) · {s[0]}")
        if s[3] is not None and s[3] < 30:
            why.append(f"승률 점수 {s[3]:.0f}점(낮음)")
    try:
        import setup3
        dl = setup3.dilution_absent(t, conn)
        if dl.get("ok") is False:
            why.append("③ 희석 판정 ❌ " + dl["label"].lstrip("❌ ").strip())
    except Exception:  # noqa: BLE001
        pass
    try:
        import listing
        ln = listing.latest(t)
        if ln:
            why.append(f"🏛 상장유지 통지 {ln.get('filed', '')[:10]} · {', '.join(ln.get('kinds') or [])}" + (f" · 기한 {ln['deadline']}" if ln.get("deadline") else ""))
    except Exception:  # noqa: BLE001
        pass
    return why


def _prices(conn, t: str, n: int = 260) -> pd.DataFrame:
    q = _q(conn, "SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT ?", (t, n))
    if not q:
        return pd.DataFrame()
    return pd.DataFrame(q, columns=["date", "open", "high", "low", "close", "volume"]).iloc[::-1].reset_index(drop=True)


def levels(px: pd.DataFrame, ext_post: float | None = None) -> dict:
    """레벨 맵(규칙): 1차 저항(20일 고가) · 2차 저항(60일 최고 종가) · 갭 구간(직전 종가 ~ 20일 고가 중 가까운 쪽) · 당일 박스 · 1차 지지 · 하방 위험."""
    if px.empty or len(px) < 5:
        return {}
    c = px["close"].astype(float)
    last, prev = float(c.iloc[-1]), float(c.iloc[-2])
    lo_d, hi_d = float(px["low"].iloc[-1]), float(px["high"].iloc[-1])
    hi20 = float(px["high"].tail(20).max())
    res1 = hi20                                   # 1차 저항 = 20일 고가(가까운 벽)
    res = max(float(c.tail(60).max()), hi20)      # 2차 저항 = 60일 최고 종가(1차보다 낮을 순 없으니 같으면 하나로 표시)
    gap = (min(prev, hi20), max(prev, hi20)) if prev > hi_d else None     # 직전 종가가 당일 고가보다 위 = 메워야 할 갭
    lo20 = float(px["low"].tail(20).min())
    sup = (round(min(lo20, lo_d) * 0.97, 4), round(min(lo20, lo_d), 4))
    low52 = float(px["low"].tail(250).min())
    danger = round(max(low52, 0) * 0.98, 4) if low52 < sup[0] else round(sup[0] * 0.92, 4)
    pos = None if hi_d == lo_d else round((last - lo_d) / (hi_d - lo_d) * 100, 1)
    return {"last": last, "prev": prev, "day_box": (lo_d, hi_d), "pos_in_box": pos, "resistance": res, "resistance1": res1, "gap": gap, "support": sup, "danger": danger,
            "day_range_pct": round((hi_d / lo_d - 1) * 100, 1) if lo_d else None, "hi52": float(px["high"].tail(250).max()), "lo52": low52,
            "after_high": ext_post, "vs_month_start": _vs_month_start(px)}


def _vs_month_start(px: pd.DataFrame) -> dict | None:
    m = px["date"].iloc[-1][:7]
    first = px[px["date"].str.startswith(m)]
    if first.empty:
        return None
    base = float(first["close"].iloc[0])
    return {"date": first["date"].iloc[0], "base": base, "pct": round((float(px["close"].iloc[-1]) / base - 1) * 100, 1)}


ITEM_KO = {"1.01": "중요 계약", "1.02": "계약 해지", "1.03": "파산", "2.01": "자산 인수·처분", "2.02": "실적 발표", "2.03": "채무 발생", "2.04": "채무 조기상환 요구",
           "3.01": "상장유지 통지", "3.02": "비등록 증권 발행", "3.03": "주주 권리 변경", "4.01": "감사인 변경", "4.02": "재무제표 신뢰 불가", "5.01": "지배권 변경",
           "5.02": "임원·이사 변동", "5.03": "정관 변경(역분할·수권주 등)", "5.07": "주총 결과", "7.01": "Reg FD 공개", "8.01": "기타 사건", "9.01": "재무제표·첨부"}
FORM_KO = [("424B", "공모 가격 확정"), ("S-1", "신규 등록"), ("F-1", "신규 등록"), ("S-3", "선반 등록"), ("F-3", "선반 등록"), ("EFFECT", "등록 효력"),
           ("10-Q", "분기 보고서"), ("10-K", "연간 보고서"), ("20-F", "연간 보고서"), ("6-K", "외국기업 수시 보고"), ("8-K", "수시 보고"), ("DEF 14A", "주총 안내")]
SKIP_FORMS = ("3", "4", "5", "144", "D")   # 내부자(Form 4)는 insider_tx 로 따로 들어가고, SC 13 대량 보유는 별도 화면


def hist_label(form: str, items: str) -> str | None:
    """과거 공시 이력(sec_hist) 한 줄을 한글로. 건너뛸 서류면 None."""
    f = (form or "").strip()
    base = f.split("/")[0].strip()
    if base in SKIP_FORMS or base.startswith("SC 13"):
        return None
    its = [x.strip() for x in re.split(r"[,; ]+", items or "") if re.fullmatch(r"\d\.\d\d", x.strip())]
    if base.startswith("8-K") and its:
        main = [i for i in its if i != "9.01"] or its
        return " · ".join(ITEM_KO.get(i, f"항목 {i}") for i in main[:3])
    for pre, ko in FORM_KO:
        if base.startswith(pre):
            return f"{ko}({f})"
    return f


def event_log(conn, t: str, px: pd.DataFrame, days: int = 240, limit: int = 20) -> list[dict]:
    """공시(최근 수집분 sec_feed + 과거 이력 sec_hist)·일정·딜·내부자·병합 + 그 뒤 주가 반응."""
    since = (date.today() - timedelta(days=days)).isoformat()
    ev, seen = [], set()
    for r in _q(conn, "SELECT COALESCE(filed, substr(updated,1,10)), form, tags, sentiment, summary_ko, accession FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) >= ? ORDER BY 1", (t, since)):
        try:
            tags = ", ".join(json.loads(r[2])[:3]) if r[2] else ""
        except ValueError:
            tags = ""
        seen.add(r[5])
        ev.append({"date": str(r[0])[:10], "kind": r[1], "text": (r[4] or tags or r[3] or "")[:90]})
    # 과거 공시 이력(sec_hist): 같은 공시(accession)는 한 번만. 예전엔 sec_feed 최근분만 보여 1~2건이던 문제
    for r in _q(conn, "SELECT accession, form, filed, COALESCE(items,'') FROM sec_hist WHERE ticker=? AND filed >= ? ORDER BY filed", (t, since)):
        if r[0] in seen:
            continue
        lab = hist_label(r[1], r[3])
        if lab:
            ev.append({"date": str(r[2])[:10], "kind": r[1], "text": lab})
    for r in _q(conn, "SELECT date, kind, title FROM events WHERE ticker=? AND date >= ? ORDER BY date", (t, since)):
        ev.append({"date": str(r[0])[:10], "kind": r[1] or "일정", "text": (r[2] or "")[:90]})
    for r in _q(conn, "SELECT filed, kind, proceeds, unit_price FROM fs_deals WHERE ticker=? AND filed >= ? ORDER BY filed", (t, since)):
        ev.append({"date": str(r[0])[:10], "kind": f"딜 {r[1] or ''}", "text": (f"${r[2] / 1e6:.1f}M " if r[2] else "") + (f"@${r[3]:.3g}" if r[3] else "")})
    for r in _q(conn, "SELECT date, ratio FROM rs_events WHERE ticker=? AND date >= ?", (t, since)):
        ev.append({"date": str(r[0])[:10], "kind": "병합", "text": f"1:{r[1]:g}" if r[1] else ""})
    ins = _q(conn, "SELECT date, SUM(value) FROM insider_tx WHERE ticker=? AND code='P' AND date >= ? GROUP BY date", (t, since))
    for r in ins:
        ev.append({"date": str(r[0])[:10], "kind": "내부자 매수", "text": f"${(r[1] or 0) / 1000:,.0f}K"})
    if px.empty:
        return sorted(ev, key=lambda e: e["date"])[-limit:]
    dates = list(px["date"])
    close = list(px["close"].astype(float))
    for e in ev:
        i = next((k for k, d in enumerate(dates) if d >= e["date"]), None)
        if i is not None and i >= 1:
            base = close[i - 1]
            e["d1"] = round((close[i] / base - 1) * 100, 1)
            e["d5"] = round((close[min(i + 4, len(close) - 1)] / base - 1) * 100, 1)
    return sorted(ev, key=lambda e: e["date"])[-limit:]


def gather(conn, t: str, yf_ticker=None) -> dict:
    t = t.upper()
    ensure(conn)
    px = _prices(conn, t)
    post = _q(conn, "SELECT MAX(COALESCE(post_high,0)) FROM ext_hilo WHERE ticker=? AND date=(SELECT MAX(date) FROM ext_hilo WHERE ticker=?)", (t, t))
    ext_post = float(post[0][0]) if post and post[0][0] else None
    lv = levels(px, ext_post)
    shares = None
    for sql in ("SELECT float_sh FROM short_interest WHERE ticker=? ORDER BY date DESC LIMIT 1", "SELECT float_shares FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1"):
        r = _q(conn, sql, (t,))
        if r and r[0][0]:
            shares = float(r[0][0])
            break
    try:
        import forensic_ai
        fm = forensic_ai.metrics_at(conn, t)
    except Exception:  # noqa: BLE001
        fm = None
    if fm and fm.get("basic"):
        shares = shares or float(fm["basic"])
    return {"ticker": t, "px": px, "levels": lv, "exclusion": exclusion(conn, t), "earnings": earnings(t, conn, yf_ticker),
            "events": event_log(conn, t, px), "shares": shares, "mcap": (lv.get("last") or 0) * shares if shares and lv else None,
            "forensic": fm, "in_universe": bool(_q(conn, "SELECT 1 FROM daily_snapshots WHERE ticker=? LIMIT 1", (t,)))}


# ---------------------------------------------------------------- AI 판단 · 카드
def _brief(g: dict) -> dict:
    lv, e = g["levels"], g["earnings"]
    return {"ticker": g["ticker"], "exclusion": g["exclusion"], "price": lv.get("last"), "prev": lv.get("prev"), "day_box": lv.get("day_box"),
            "pos_in_box_pct": lv.get("pos_in_box"), "resistance_20d": lv.get("resistance1"), "resistance_60d": lv.get("resistance"), "gap": lv.get("gap"), "support": lv.get("support"), "danger": lv.get("danger"),
            "hi52": lv.get("hi52"), "lo52": lv.get("lo52"), "after_high": lv.get("after_high"), "vs_month_start": lv.get("vs_month_start"),
            "mcap_usd": None if g["mcap"] is None else round(g["mcap"]), "shares": g["shares"],
            "earnings": {k: e.get(k) for k in ("next_date", "rev_avg", "rev_low", "rev_high", "eps_avg", "last_q", "last_rev", "last_eps") if e.get(k) is not None},
            "events": [{k: v for k, v in ev.items() if v not in (None, "")} for ev in g["events"]],
            "forensic": None if not g["forensic"] else {k: g["forensic"].get(k) for k in ("as_of", "fd_ratio", "baby_shelf", "runway_months", "toxic", "atm_eloc")}}


def judge(g: dict, post=None) -> dict:
    import aipick
    prompt = f"오늘 {date.today().isoformat()}. 자료:\n" + json.dumps(_brief(g), ensure_ascii=False, separators=(",", ":"))
    est = aipick.cost_usd(MODEL, len(prompt) // 2 + 500, 4000)
    if est * aipick.FX > aipick.budget_left_krw():
        return {"error": "이번 달 AI 예산이 부족해요"}
    text, tin, tout = aipick.call_claude(prompt, MODEL, 4000, post, system=SYSTEM, effort="medium")
    aipick._add_spend(aipick.cost_usd(MODEL, tin, tout))
    s = re.sub(r"```(?:json)?", "", text).strip()
    try:
        j = json.loads(s[s.find("{"):s.rfind("}") + 1])
    except ValueError:
        return {"error": "AI 답을 읽지 못했어요", "raw": text[:300]}
    j["cost_usd"] = round(aipick.cost_usd(MODEL, tin, tout), 4)
    return j


def build(t: str, post=None, yf_ticker=None, with_ai: bool = True, source: str = "직접") -> dict:
    """카드 만들기 → 저장. 외부 후보(우리 후보가 아닌 종목)는 🏆 성과 공표 기록."""
    t = t.upper()
    today = date.today().isoformat()
    with closing(db.connect()) as conn:
        g = gather(conn, t, yf_ticker)
        card = {"ticker": t, "date": today, "exclusion": g["exclusion"], "levels": {k: v for k, v in g["levels"].items()}, "earnings": g["earnings"],
                "events": g["events"], "shares": g["shares"], "mcap": g["mcap"], "forensic": g["forensic"], "in_universe": g["in_universe"], "source": source,
                "ai": judge(g, post) if with_ai and g["levels"] else None, "made": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        conn.execute("INSERT OR REPLACE INTO screener_cards VALUES (?,?,?,?)", (t, today, json.dumps(card, ensure_ascii=False, default=str), source))
        if g["levels"].get("last") and not conn.execute("SELECT 1 FROM screener_sig WHERE ticker=? AND date >= ?", (t, (date.today() - timedelta(days=10)).isoformat())).fetchone():
            conn.execute("INSERT OR IGNORE INTO screener_sig VALUES (?,?,?,?)", (today, t, g["levels"]["last"], source))
        conn.commit()
    return card


def latest_card(conn, t: str) -> dict | None:
    ensure(conn)
    r = conn.execute("SELECT card FROM screener_cards WHERE ticker=? ORDER BY date DESC LIMIT 1", (t.upper(),)).fetchone()
    return json.loads(r[0]) if r else None
