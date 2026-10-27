"""🤖 AI 요약 · 🔀 교차검증 — 우리 시스템이 정리한 사실만 Claude(Anthropic API)에 넘겨 김곰 형식 한글 요약을 만들고,
Cowork 덕구 스캔(공시 원문 기반) 보고서와 핵심 항목을 맞대어 일치·불일치를 표시한다.

.env: ANTHROPIC_API_KEY=… (필수) · AI_MODEL(기본 claude-sonnet-5-5) · AI_PRICE_IN / AI_PRICE_OUT(100만 토큰당 달러, 기본 2 / 10)
월 예산: 관리 모드 AI_MONTHLY_BUDGET_KRW(기본 10,000원) — 넘으면 호출하지 않는다. 같은 종목 요약은 하루 한 번(그 사이 저장본).
AI 도 틀릴 수 있다: '넘겨준 사실만 사용, 추측은 (추정)' 으로 지시하고, 교차검증에서 어긋난 항목은 원문 확인이 필요하다.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import closing
from datetime import date, datetime, timezone

import db

API_URL = "https://api.anthropic.com/v1/messages"
DDL = ["""CREATE TABLE IF NOT EXISTS ai_reports (ticker TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, model TEXT, content TEXT, in_tok INTEGER, out_tok INTEGER,
          cost_usd REAL, created_at TEXT, PRIMARY KEY (ticker, day, kind))"""]
SECTIONS = ["판정", "매수 동기", "해소하려는 문제", "압박 목적", "가격 사다리", "출회 주체", "주의사항"]
CHECK_ITEMS = ["런웨이", "ATM·ELOC", "전환사채·워런트", "baby shelf", "$1 상장유지", "역분할", "최종 판정"]


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def model() -> str:
    import config
    return getattr(config, "AI_MODEL", None) or os.environ.get("AI_MODEL", "claude-sonnet-5-5")


PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}  # 100만 토큰당 달러(바뀌면 .env AI_PRICE_IN/OUT)


def prices() -> tuple[float, float]:
    base = PRICES.get(model(), (2.0, 10.0))
    return float(os.environ.get("AI_PRICE_IN", base[0])), float(os.environ.get("AI_PRICE_OUT", base[1]))


def fx() -> float:
    try:
        return float((db.get_meta("usdkrw") or {}).get("value") or 1350.0)
    except (TypeError, ValueError):
        return 1350.0


def month_spend_usd() -> float:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        r = conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_reports WHERE substr(created_at,1,7)=?", (date.today().strftime("%Y-%m"),)).fetchone()
    return float(r[0] or 0)


def budget_left_krw() -> float:
    import config
    return float(getattr(config, "AI_MONTHLY_BUDGET_KRW", 10000)) - month_spend_usd() * fx()


# ---------------------------------------------------------------- 사실 모으기(우리 시스템이 이미 정리한 것만)
def facts(ticker: str, with_forensic: bool = True) -> dict:
    t = ticker.upper()
    f: dict = {"티커": t, "오늘": date.today().isoformat()}
    df = None
    try:
        import market
        df = market.download_daily([t], period="3mo").get(t)
        if df is not None and not df.empty:
            c = df["Close"].dropna()
            f["가격(Yahoo 일봉)"] = {"기준일": c.index[-1].strftime("%Y-%m-%d"), "종가$": round(float(c.iloc[-1]), 4), "60일 최고$": round(float(c.tail(60).max()), 4),
                                 "60일 최저$": round(float(c.tail(60).min()), 4), "1개월 등락%": round((float(c.iloc[-1]) / float(c.iloc[-22]) - 1) * 100, 1) if len(c) > 22 else None}
    except Exception:  # noqa: BLE001
        pass
    with closing(db.connect()) as conn:
        s = conn.execute("SELECT date, price, day_change_pct, volume_mult, float_shares, dilution_status FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        if s:
            f["스캐너"] = {"날짜": s["date"], "가격$": s["price"], "등락%": s["day_change_pct"], "거래량배수": s["volume_mult"], "유통주식": s["float_shares"], "희석판정": s["dilution_status"]}
        try:
            import pressure
            p = pressure.evaluate(t, conn, None, df)
            f["회사 압박"] = {"점수": p["score"], "항목": [f"{a}: {b}" for a, b, _ in p["press"]], "목표가": [f"{n} ${v:.4f} ({pc:+.0f}%)" for n, v, pc in p["targets"] if pc is not None],
                           "주의": p["warn"], "참고": p["notes"], "구조": p["stance"]}
        except Exception:  # noqa: BLE001
            pass
        try:
            a = conn.execute("SELECT data FROM accum WHERE ticker=? AND period='주간' ORDER BY date DESC LIMIT 1", (t,)).fetchone()
            if a:
                d = json.loads(a[0])
                f["매집(주간)"] = {k: d.get(k) for k in ("level", "score", "n_absorb", "absorb_days", "top_day", "top_vr", "top_chg", "cum", "r30", "news", "dilution")}
        except Exception:  # noqa: BLE001
            pass
        try:
            import regsho
            n = regsho.streaks(conn).get(t)
            if n:
                f["Reg SHO 연속일"] = n
        except Exception:  # noqa: BLE001
            pass
        try:
            f["최근 공시"] = [{"서류": r["form"], "날짜": r["filed"], "판정": r["sentiment"], "태그": json.loads(r["tags"] or "[]"), "핵심문장": (r["lead"] or "")[:400]}
                          for r in conn.execute("SELECT form, filed, sentiment, tags, lead FROM sec_feed WHERE ticker=? ORDER BY updated DESC LIMIT 6", (t,))]
        except Exception:  # noqa: BLE001
            pass
        try:
            f["내부자 매수"] = [{"날짜": r["date"], "이름": r["owner"], "직책": r["title"], "주식": r["shares"], "가격$": r["price"]}
                            for r in conn.execute("SELECT date, owner, title, shares, price FROM insider_tx WHERE ticker=? AND code='P' ORDER BY date DESC LIMIT 5", (t,))]
        except Exception:  # noqa: BLE001
            pass
        try:
            f["역분할"] = [{"날짜": r[0], "비율": f"1:{round(1 / r[1]):g}"} for r in conn.execute("SELECT date, ratio FROM rs_events WHERE ticker=? ORDER BY date DESC LIMIT 3", (t,))]
        except Exception:  # noqa: BLE001
            pass
        try:
            f["일정"] = [{"날짜": r["date"], "종류": r["kind"], "내용": r["title"]} for r in conn.execute(
                "SELECT date, kind, title FROM events WHERE ticker=? AND date >= ? ORDER BY date LIMIT 8", (t, (date.today()).isoformat()))]
        except Exception:  # noqa: BLE001
            pass
    try:
        import watch
        oh = watch.overhang_rows(t)
        if not oh.empty:
            f["물량 장부"] = [{"종류": r.kind, "수량M": r.qty_m, "행사가$": r.price, "상태": r.status, "만기": r.expiry} for r in oh.itertuples()][:10]
    except Exception:  # noqa: BLE001
        pass
    rep = db.get_report(t) or {}
    if rep.get("runway"):
        rw = rep["runway"]
        f["런웨이(종목 리포트·XBRL)"] = {**{k: rw.get(k) for k in ("runway_months", "cash", "monthly_burn", "cash_asof")}, "리포트 생성일": str(rep.get("generated_at", ""))[:10]}
    fin = rep.get("financing") or {}
    if isinstance(fin, dict) and fin.get("events"):
        f["자금조달 이력(종목 리포트)"] = [{k: e.get(k) for k in ("date", "form", "kind", "amount", "text") if e.get(k) is not None} for e in fin["events"][:8]]
    if with_forensic:
        try:
            import forensic
            fr = forensic.reports(t)
            if not fr.empty:
                f["덕구 스캔(공시 원문 기반 보고서)"] = {"저장일": str(fr.iloc[0]["created_at"])[:10], "본문": fr.iloc[0]["content"][:9000]}
        except Exception:  # noqa: BLE001
            pass
    try:
        import themes
        tb = themes.table()
        th = tb.set_index("ticker")["themes"].get(t) if not tb.empty else None
        if th:
            f["테마"] = th
    except Exception:  # noqa: BLE001
        pass
    return f


SYSTEM = ("너는 나스닥 초소형주 공시·수급 분석가다. 사용자가 넘겨준 JSON 사실만 근거로 한국어로 쓴다. 사실에 없는 숫자·사건·이름은 만들지 않는다. "
          "'덕구 스캔(공시 원문 기반 보고서)'은 SEC 원문을 읽은 사실이므로 워런트·전환사채·ATM 한도·런웨이·역분할 이력은 이것을 우선한다. "
          "가격·거래량처럼 시스템 값이 더 최신이면 날짜를 밝혀 함께 적는다(예: '10-16 종가 $0.97, 덕구 기준일 10-13 $1.07'). 숫자에는 기준일을 붙인다. "
          "추론은 문장 끝에 (추정)을 붙인다. 투자 권유를 하지 않는다. 반드시 JSON 하나만 출력한다(앞뒤 설명·코드블록 금지).")


def _prompt(f: dict) -> str:
    return ("아래 사실로 김곰 워치리스트 형식의 요약을 만들어라. 키: " + ", ".join(f'"{s}"' for s in SECTIONS)
            + ', "한줄요약", "확인필요"(사실이 부족하거나 원문 확인이 필요한 점 목록). 각 값은 문자열 목록이고 항목당 1~2문장, 전체 1,500자 이내로 짧게. '
              '"판정"은 [매력/보통/대기/회피] 중 하나로 시작하는 한 문장.\n\n'
            + json.dumps(f, ensure_ascii=False, default=str))


def call(system: str, user: str, max_tokens: int = 3500, http_post=None) -> tuple[str, int, int]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError(".env 에 ANTHROPIC_API_KEY 가 없습니다.")
    pin, pout = prices()
    est = (len(user) / 2.5 * pin + max_tokens * pout) / 1e6 * fx()  # 한글·JSON 기준 대략 2.5자/토큰
    if est > budget_left_krw():
        raise RuntimeError(f"이번 달 AI 예산이 부족합니다(남은 {max(budget_left_krw(), 0):,.0f}원, 이번 호출 예상 {est:,.0f}원). 관리 모드에서 상한을 바꿀 수 있어요.")
    import requests
    post = http_post or (lambda url, headers, body: requests.post(url, headers=headers, json=body, timeout=120))
    r = post(API_URL, {"x-api-key": key, "anthropic-version": os.environ.get("AI_API_VERSION", "2023-06-01"), "content-type": "application/json"},
             {"model": model(), "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]})
    if getattr(r, "status_code", 200) >= 400:
        raise RuntimeError(f"API 오류 {r.status_code}: {str(getattr(r, 'text', ''))[:300]}")
    j = r.json()
    text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    u = j.get("usage") or {}
    return text, int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)


def _salvage(t: str) -> dict:
    """응답이 길어 잘린 JSON 에서 끝까지 쓰인 항목만 살린다(문자열·문자열 목록)."""
    out: dict = {}
    for m in re.finditer(r'"([^"\\]{1,30})"\s*:\s*("(?:[^"\\]|\\.)*"|\[(?:\s*"(?:[^"\\]|\\.)*"\s*,?)*\s*\]|-?\d+(?:\.\d+)?)', t):
        try:
            out[m.group(1)] = json.loads(m.group(2))
        except Exception:  # noqa: BLE001
            continue
    items = re.findall(r'\{\s*"이름"\s*:.*?\}', t, re.S)  # 교차검증 항목(완성된 것만)
    if items:
        good = []
        for x in items:
            try:
                good.append(json.loads(x))
            except Exception:  # noqa: BLE001
                pass
        if good:
            out["항목"] = good
            out.pop("이름", None)
            for k in ("A", "B", "판정", "메모"):
                out.pop(k, None)
    return out


def _json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    try:
        return json.loads(m.group(0) if m else t)
    except Exception:  # noqa: BLE001
        part = _salvage(t)
        if part:
            part.setdefault("확인필요", [])
            if isinstance(part["확인필요"], str):
                part["확인필요"] = [part["확인필요"]]
            part["확인필요"] = list(part["확인필요"]) + ["AI 응답이 길어 끝부분이 잘렸어요 — 보이는 항목만 표시합니다."]
            return part
        return {"한줄요약": text.strip()[:1500], "확인필요": ["AI 응답을 형식대로 읽지 못해 원문 그대로 보여 줍니다."]}


def _save(t: str, kind: str, content: dict, i: int, o: int) -> dict:
    pin, pout = prices()
    cost = (i * pin + o * pout) / 1e6
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        conn.execute("INSERT OR REPLACE INTO ai_reports VALUES (?,?,?,?,?,?,?,?,?)", (t, date.today().isoformat(), kind, model(), json.dumps(content, ensure_ascii=False), i, o, cost,
                                                                                     datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return {**content, "_cost_krw": cost * fx(), "_tokens": (i, o)}


def latest(ticker: str, kind: str = "summary") -> dict | None:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        r = conn.execute("SELECT day, model, content, cost_usd, created_at FROM ai_reports WHERE ticker=? AND kind=? ORDER BY created_at DESC LIMIT 1", (ticker.upper(), kind)).fetchone()
    if not r:
        return None
    return {**json.loads(r["content"]), "_day": r["day"], "_model": r["model"], "_cost_krw": (r["cost_usd"] or 0) * fx(), "_at": r["created_at"]}


def summarize(ticker: str, force: bool = False, http_post=None) -> dict:
    t = ticker.upper()
    old = latest(t)
    if old and old.get("_day") == date.today().isoformat() and not force:
        return old
    ensure_report(t)
    text, i, o = call(SYSTEM, _prompt(facts(t)), http_post=http_post)
    return _save(t, "summary", _json(text), i, o)


def ensure_report(t: str) -> bool:
    """종목 리포트(런웨이·조달 이력)가 없거나 7일 지났으면 만든다. SEC 요청 수십 번."""
    from datetime import timedelta
    rep = db.get_report(t)
    if rep and str(rep.get("generated_at", ""))[:10] >= (date.today() - timedelta(days=7)).isoformat():
        return False
    try:
        import config
        import report
        import sec
        if "@" not in config.SEC_USER_AGENT:
            return False
        with closing(db.connect()) as conn:
            db.save_report(t, report.build_report(sec.SecClient(config.SEC_USER_AGENT), conn, t))
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 🔀 교차검증(AI 요약 ↔ 덕구 스캔)
CHECK_SYSTEM = ("너는 데이터 검증자다. A=우리 시스템이 모은 데이터(JSON), B=SEC 공시 원문을 읽은 덕구 스캔 보고서. 각 항목에서 두 쪽 값을 짧게 옮기고 판정한다: "
                "일치(같은 결론) / 시점차(기준일이 달라 생긴 차이 — 각 기준일을 메모에) / 다름(같은 시점인데 다름) / 한쪽만(한쪽에만 정보). "
                "원문을 읽은 B 가 구체적이면 B 를 더 믿되 근거를 적는다. 시점차·한쪽만은 일치율 계산에서 빼고(일치 ÷ (일치+다름)), 새로운 사실은 만들지 않는다. JSON 하나만 출력한다.")


def _check_prompt(a: dict, b: str) -> str:
    return ('항목: ' + ", ".join(CHECK_ITEMS) + '. 출력 형식: {"항목": [{"이름": "...", "A": "...", "B": "...", "판정": "일치|다름|한쪽만", "메모": "..."}], '
            '"일치율": 0~100 정수, "종합": "두세 문장", "원문확인": ["..."]}. 판정은 일치|시점차|다름|한쪽만. A·B·메모는 각각 한 문장 이내로 짧게.\n\n[A: 시스템 데이터]\n'
            + json.dumps(a, ensure_ascii=False, default=str)
            + "\n\n[B: 덕구 스캔]\n" + b[:24000])


def cross_check(ticker: str, http_post=None) -> dict:
    import forensic
    t = ticker.upper()
    fr = forensic.reports(t)
    if fr.empty:
        raise RuntimeError("덕구 스캔 보고서가 없습니다. 🧾 공시분석 대기열에 넣으면 다음 Cowork 실행 때 생겨요.")
    ensure_report(t)
    a = facts(t, with_forensic=False)  # 덕구 보고서를 뺀 '우리 데이터' 와 원문 보고서를 맞댄다
    text, i, o = call(CHECK_SYSTEM, _check_prompt(a, fr.iloc[0]["content"]), max_tokens=3500, http_post=http_post)
    res = _json(text)
    res["_forensic_at"] = str(fr.iloc[0]["created_at"])[:16]
    return _save(t, "check", res, i, o)


def conflicts(res: dict) -> list[dict]:
    return [x for x in res.get("항목", []) if x.get("판정") == "다름"]
