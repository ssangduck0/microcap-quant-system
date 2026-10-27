"""🧾 서버 자동 공시분석 — 덕구 SEC 포렌식 희석 스캔(sec-dilution-scan 스킬 v0.1)을 서버에서 Claude API 로 실행.

서버 이전 뒤 PC 의 Cowork 는 서버 폴더(대기열)를 읽을 수 없어 공시분석이 멈췄다 → 서버가 직접 한다.
· 대기열(forensic.queue_list)에서 하루 FORENSIC_PER_RUN(기본 3)종목 · 아침 갱신 때 · 대시보드 버튼 · `python forensic_ai.py [티커]`
· 조사 순서(스킬 §3): ① 재무(10-K·10-Q 핵심 부분) ② 자금조달(8-K·S-1/S-3/F-1/F-3·424B) ③ 내부자(우리 Form 4 기록·DEF 14A) ④ 시장 데이터(일봉)
  큰 서류는 핵심 단어 주변만 잘라 보냄(비용) — 원문에 없으면 '공시에 명시되지 않음'/'추가 확인 필요'
· 보고서는 스킬 명세(forensic_spec.md) 그대로 11개 섹션 마크다운 → forensic.add 로 저장(리포트 화면에 그대로) · 성공하면 대기열에서 빠짐
· 비용: Sonnet 5.5 종목당 약 100~200원 · 🤖 AI 월 예산(aipick)과 같은 지갑
"""
from __future__ import annotations

import re
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import config
import db

MODEL = "claude-sonnet-5-5"
SPEC_PATH = Path(__file__).resolve().parent / "forensic_spec.md"
MAX_CHARS = 90_000          # 보내는 원문 합계 한도(약 2.5~3만 토큰)
RETRY_DAYS = 2              # 실패한 종목은 이 기간 동안 다시 시도하지 않음(비용)
KEYS_FIN = ("going concern", "substantial doubt", "cash and cash equivalents", "net cash used in operating", "shares of common stock outstanding",
            "aggregate market value", "non-affiliates", "authorized", "accumulated deficit", "subsequent event")
KEYS_FUND = ("warrant", "convertible", "at-the-market", "at the market", "sales agreement", "equity line", "purchase agreement", "pre-funded",
             "exercise price", "baby shelf", "i.b.6", "use of proceeds", "registered direct", "private placement", "lock-up", "reverse stock split",
             "promissory note", "conversion price", "reset")
FUND_FORMS = ("S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-1/A", "F-3", "F-3/A")


def system_prompt() -> str:
    spec = SPEC_PATH.read_text(encoding="utf-8") if SPEC_PATH.exists() else ""
    return ("당신은 '덕구 SEC 포렌식 희석 스캔'을 수행하는 분석가입니다. 아래 지침과 섹션 명세를 그대로 따르세요.\n"
            "웹 검색은 할 수 없고, 사용자가 붙여 준 SEC 원문 발췌·우리 DB 자료만 근거로 씁니다. 발췌에 없으면 '공시에 명시되지 않음' 또는 '추가 확인 필요'.\n"
            "모든 수치에 as-of 날짜와 출처(공시일·form·accession)를 붙이고, 사실/해석/추측을 구분합니다.\n"
            "출력: 첫 줄 '# {티커} 덕구 SEC 포렌식 희석 스캔 (as-of YYYY-MM-DD)' 다음 11개 섹션 마크다운만(서론·맺음말 없이).\n"
            "섹션 제목은 반드시 '## 1. 무슨 회사인지 요약', '## 2. 💰 현재 런웨이 / 월 소모량' … '## 11. 대기 중인 호재' 처럼 '## 번호. 제목' 형식.\n"
            "자료가 부족해도 11개 섹션을 모두 출력하고 못 채운 칸은 '추가 확인 필요' 또는 '공시에 명시되지 않음'으로 채울 것(거절·요약만 하지 말 것).\n"
            "맨 마지막 줄에 기계가 읽는 요약을 HTML 주석 한 줄로(화면엔 안 보임, 모르는 값은 null):\n"
            '<!-- DILUTION_JSON {"basic": 기본 발행주식수, "fd": 완전희석 주식수(§4 합계), "fd_ratio": fd÷basic, "baby_shelf": "적용"|"미적용"|null, '
            '"runway_months": 숫자|null, "toxic": true|false|null, "atm_eloc": true|false|null} -->\n\n' + spec)


def _windows(text: str, keys, width: int = 900, cap: int = 14000) -> str:
    """긴 서류에서 핵심 단어 주변만 모음(겹치면 합침)."""
    low = text.lower()
    spans = []
    for k in keys:
        for m in re.finditer(re.escape(k), low):
            spans.append((max(0, m.start() - width), min(len(text), m.end() + width)))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out, n = [], 0
    for a, b in merged:
        seg = re.sub(r"\s+", " ", text[a:b])
        out.append("… " + seg + " …")
        n += len(seg)
        if n >= cap:
            break
    return "\n".join(out)


XBRL_TAGS = [  # (분류, 태그, 이름) — SEC companyfacts(재무 숫자 데이터). 원문 발췌에서 잘려 '추가 확인 필요'가 되던 칸을 채움
    ("dei", "EntityCommonStockSharesOutstanding", "발행주식수(표지)"),
    ("dei", "EntityPublicFloat", "non-affiliate float($, 10-K 표지)"),
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "현금"),
    ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "현금+제한현금"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "영업현금흐름(OCF, 기간 누적)"),
    ("us-gaap", "NetIncomeLoss", "순이익"),
    ("us-gaap", "StockholdersEquity", "자본총계"),
    ("us-gaap", "Liabilities", "부채총계"),
    ("us-gaap", "CommonStockSharesAuthorized", "수권주식수"),
    ("us-gaap", "CommonStockSharesOutstanding", "발행주식수(재무제표)"),
    ("ifrs-full", "CashAndCashEquivalents", "현금(IFRS)"),
    ("ifrs-full", "CashFlowsFromUsedInOperatingActivities", "영업현금흐름(IFRS)"),
]


def xbrl_summary(facts: dict, n: int = 6) -> str:
    """companyfacts → 태그별 최근 값 n개(기준일·기간·서류·접수일). 숫자 표라 토큰이 적음."""
    lines = []
    f = facts.get("facts") or {}
    for ns, tag, name in XBRL_TAGS:
        units = ((f.get(ns) or {}).get(tag) or {}).get("units") or {}
        for unit, rows in units.items():
            rows = [r for r in rows if r.get("val") is not None and r.get("end")]
            rows.sort(key=lambda r: (r["end"], r.get("filed", "")), reverse=True)
            seen, out = set(), []
            for r in rows:
                k = (r["end"], r.get("start"))
                if k in seen:
                    continue
                seen.add(k)
                per = f"{r['start']}~{r['end']}" if r.get("start") else f"{r['end']} 기준"
                out.append(f"{per} {r['val']:,} ({r.get('form', '')} 접수 {r.get('filed', '')})")
                if len(out) >= n:
                    break
            if out:
                lines.append(f"- {name} [{tag}, {unit}]: " + " | ".join(out))
    return "\n".join(lines)


def gather(client, ticker: str, today: date | None = None) -> dict:
    """SEC 원문 발췌 + 우리 DB 자료. {'error'} 또는 {'company', 'parts': [(제목, 본문)], 'docs': n}"""
    today = today or date.today()
    t = ticker.upper()
    cik = client.cik_for(t)
    if not cik:
        return {"error": f"SEC CIK 없음 — 티커 '{t}' 가 EDGAR 에 미국 등록 발행사로 없어요(오타·티커 변경·해외 상장 확인)"}
    import sec
    sub = client.submissions(cik)
    filings = sec.recent_filings(sub, cik)
    cutoff = (today - timedelta(days=540)).isoformat()
    recent = [f for f in filings if f["filed"] >= cutoff]
    parts: list[tuple[str, str]] = []
    total = 0

    def add(f, keys=None, head=0, cap=14000):
        nonlocal total
        if total >= MAX_CHARS:
            return
        try:
            text = client.fetch_text(f["url"], limit=2_000_000)
        except Exception as e:  # noqa: BLE001
            parts.append((f"{f['form']} {f['filed']} {f['accession']}", f"(본문 받기 실패: {e})"))
            return
        body = (re.sub(r"\s+", " ", text[:head]) + "\n" if head else "") + (_windows(text, keys, cap=cap) if keys else "")
        body = body[:max(0, MAX_CHARS - total)]
        total += len(body)
        parts.append((f"{f['form']} · 접수 {f['filed']} · accession {f['accession']} · {f['url']}", body))

    core = [f for f in recent if f["form"] in ("10-K", "10-K/A", "20-F", "10-Q", "6-K", "8-K", "8-K/A") + FUND_FORMS or f["form"].startswith("424B")]
    if not core:
        forms = sorted({f["form"] for f in filings[:30]})
        return {"error": f"최근 18개월 핵심 공시(10-K·10-Q·8-K·S-1/S-3·424B)가 없어요 — 장외(OTC)·해외 기업이거나 공시가 멈춘 회사일 수 있어요(최근 서류 종류: {', '.join(forms[:8]) or '없음'})"}
    big = [f for f in recent if f["form"] in ("10-K", "20-F", "10-K/A")][:1] + [f for f in recent if f["form"] in ("10-Q", "6-K")][:1]
    for f in big:                                                     # ① 재무
        add(f, KEYS_FIN + ("warrant", "convertible", "at-the-market"), head=3000, cap=16000)
    for f in [f for f in recent if f["form"] in FUND_FORMS][:2]:     # ② 자금조달: 등록신고서
        add(f, KEYS_FUND, head=2500, cap=10000)
    for f in [f for f in recent if f["form"].startswith("424B")][:3]:
        add(f, KEYS_FUND, head=4000, cap=5000)
    for f in [f for f in recent if f["form"] in ("8-K", "8-K/A") and any(x in f["items"] for x in ("1.01", "3.02", "3.03", "5.03", "8.01", "3.01"))][:5]:
        add(f, KEYS_FUND, head=3500, cap=4000)
    for f in [f for f in recent if f["form"] in ("DEF 14A", "PRE 14A", "DEF 14C")][:1]:   # ③ 주총(병합·수권주식)
        add(f, ("reverse stock split", "authorized shares", "increase the number of authorized", "proposal"), head=1500, cap=5000)
    with closing(db.connect()) as conn:                               # ③ 내부자(Form 4) · ④ 시장 데이터 — SEC 원문 아님
        try:
            ins = conn.execute("SELECT date, owner, title, code, shares, price, value FROM insider_tx WHERE ticker=? AND date >= ? ORDER BY date DESC LIMIT 12",
                               (t, (today - timedelta(days=365)).isoformat())).fetchall()
        except Exception:  # noqa: BLE001
            ins = []
        if ins:
            parts.append(("우리 DB · Form 4 거래(최근 1년, code P=장내 매수 S=매도)", "\n".join(" | ".join(str(x) for x in r) for r in ins)))
        px = conn.execute("SELECT date, close, volume FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 60", (t,)).fetchall()
        if px:
            hi = max(px, key=lambda r: r[1] or 0)
            parts.append(("시장 데이터(SEC 원문 아님 · 우리 일봉)", f"현재가(최근 종가) ${px[0][1]} ({px[0][0]}) · 60일 최고 종가 ${hi[1]} ({hi[0]}) · 60거래일 수 {len(px)}"))
    listing = "\n".join(f"{f['filed']} {f['form']} items={f['items']} {f['accession']}" for f in recent[:40])
    parts.insert(0, ("최근 공시 목록(최신순 40건)", listing))
    try:  # ① 재무 숫자 — XBRL(companyfacts): 발행주식수·non-affiliate float·분기별 현금·OCF(TTM 계산용)
        xs = xbrl_summary(client.companyfacts(cik))
        if xs:
            parts.insert(1, ("SEC XBRL 재무 숫자(companyfacts · 원문 재무제표의 태그 값 · 기간 누적 값은 분기 차감으로 단독 분기 계산)", xs))
    except Exception as e:  # noqa: BLE001
        parts.insert(1, ("SEC XBRL 재무 숫자", f"(받기 실패: {e})"))
    return {"company": (sub.get("name") or t), "cik": cik, "parts": parts, "docs": len(parts)}


def build_prompt(ticker: str, g: dict, today: date | None = None) -> str:
    today = today or date.today()
    head = f"티커 {ticker.upper()} · 회사 {g['company']} · CIK {g['cik']} · 오늘 {today.isoformat()}\n아래 발췌만 근거로 스캔하세요.\n"
    return head + "\n\n".join(f"===== {title} =====\n{body}" for title, body in g["parts"])


def analyze(ticker: str, client=None, post=None, today: date | None = None, out=print) -> dict:
    """한 종목 분석 → 저장. {'ok', 'msg', 'cost_usd'}"""
    import aipick
    import forensic
    today = today or date.today()
    t = ticker.upper()
    if client is None:
        import sec
        client = sec.SecClient(config.require_sec_user_agent())
    g = gather(client, t, today)
    if g.get("error"):
        forensic._set_error(t, g["error"])
        db.set_meta(f"forensic_ai_fail:{t}", today.isoformat())
        return {"ok": False, "msg": f"{t}: {g['error']}", "cost_usd": 0.0}
    prompt = build_prompt(t, g, today)
    est = aipick.cost_usd(MODEL, len(prompt) // 3 + 5000, 20000)
    if est * aipick.FX > aipick.budget_left_krw():
        return {"ok": False, "msg": f"{t}: 이번 달 AI 예산이 부족해 건너뜀", "cost_usd": 0.0, "budget": True}
    # Sonnet 5.5 는 생각이 기본 — 희석 계산(완전희석·베이비 쉐프)엔 생각이 필요하니 끄지 않고 깊이(medium)만 낮추고, 보고서를 쓸 자리를 넉넉히
    text, tin, tout = aipick.call_claude(prompt, MODEL, 32000, post, system=system_prompt(), effort="medium", timeout=900)
    usd = aipick.cost_usd(MODEL, tin, tout)
    aipick._add_spend(usd)
    md = text.strip()
    try:  # Claude 의 답은 항상 남겨 둠(문제가 생기면 원인 확인용)
        raw_dir = forensic.root_dir() / "ai_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{t}_{today:%Y%m%d}.md").write_text(md or "(빈 답)", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    heads = len(re.findall(r"(?m)^#{1,3}\s*\d{1,2}[.)]\s*\S", md))
    if len(md) < 300 or heads < 5:
        why = f"서버 분석 결과가 비정상(길이 {len(md)}자 · 섹션 제목 {heads}개) — 답 앞부분: {re.sub(chr(10), ' ', md)[:160]}"
        forensic._set_error(t, why)
        db.set_meta(f"forensic_ai_fail:{t}", today.isoformat())
        return {"ok": False, "msg": f"{t}: {why}", "cost_usd": usd}
    as_of = forensic.guess_as_of(md) or today.isoformat()
    met = parse_metrics(md)
    md = re.sub(r"<!--\s*DILUTION_JSON.*?-->", "", md, flags=re.S).strip()  # 기계용 줄은 보고서 화면에서 빼고 수치만 따로 저장
    forensic.add(t, md, source=f"서버 자동(Claude {MODEL})", as_of=as_of)
    if met:  # ✅ 3대 조건 ③·AI PICK 이 쓰는 완전희석 배수 등
        save_metrics(t, as_of, met)
    forensic.queue_remove(t)
    forensic._set_error(t, None)
    msg = f"{t}: 공시 {g['docs']}건 발췌 → 보고서 저장 · ${usd:.3f}(약 {usd * aipick.FX:,.0f}원)"
    out(msg)
    return {"ok": True, "msg": msg, "cost_usd": usd}


def run(limit: int | None = None, client=None, post=None, out=print, tickers: list[str] | None = None) -> dict:
    """대기열에서 limit 종목 분석. 대기열에 없는 종목의 예전 실패 기록은 정리."""
    import forensic
    if not getattr(config, "FORENSIC_AI", True) and tickers is None:
        return {"ok": False, "n": 0, "msg": "서버 공시분석 꺼짐(관리 모드)"}
    q = forensic.queue_list()
    for t in list(forensic.errors()):                 # 티커를 고쳐서 대기열에서 빠진 종목의 오래된 실패 기록 정리
        if t not in q:
            forensic._set_error(t, None)
    today = date.today()
    todo = tickers or [t for t in q if not ((db.get_meta(f"forensic_ai_fail:{t}") or {}).get("value", "") >= (today - timedelta(days=RETRY_DAYS)).isoformat())]
    todo = todo[: (limit or int(getattr(config, "FORENSIC_PER_RUN", 3)))]
    done, msgs = 0, []
    for t in todo:
        try:
            r = analyze(t, client=client, post=post, today=today, out=out)
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "msg": f"{t}: 실패 {e}"}
            db.set_meta(f"forensic_ai_fail:{t}", today.isoformat())
        msgs.append(r["msg"])
        if not r.get("ok"):
            out(r["msg"])
        done += bool(r.get("ok"))
        if r.get("budget"):
            break
    if msgs:
        out(f"서버 공시분석: {done}/{len(todo)}종목 완료")
    return {"ok": True, "n": done, "msg": " · ".join(msgs) or "대기열 비어 있음"}


MET_DDL = """CREATE TABLE IF NOT EXISTS forensic_metrics (ticker TEXT, as_of TEXT, basic REAL, fd REAL, fd_ratio REAL, baby_shelf TEXT, runway_months REAL,
               toxic INTEGER, atm_eloc INTEGER, saved TEXT, PRIMARY KEY (ticker, as_of))"""


def parse_metrics(md: str) -> dict | None:
    """보고서 맨 끝 <!-- DILUTION_JSON {...} --> → 숫자. fd_ratio 가 없으면 fd÷basic."""
    import json as _j
    m = re.search(r"<!--\s*DILUTION_JSON\s*(\{.*?\})\s*-->", md or "", re.S)
    if not m:
        return None
    try:
        d = _j.loads(m.group(1))
    except ValueError:
        return None

    def num(x):
        try:
            return None if x is None else float(str(x).replace(",", ""))
        except ValueError:
            return None
    out = {"basic": num(d.get("basic")), "fd": num(d.get("fd")), "fd_ratio": num(d.get("fd_ratio")), "baby_shelf": d.get("baby_shelf"),
           "runway_months": num(d.get("runway_months")), "toxic": d.get("toxic"), "atm_eloc": d.get("atm_eloc")}
    if out["fd_ratio"] is None and out["basic"] and out["fd"]:
        out["fd_ratio"] = out["fd"] / out["basic"]
    return out


def save_metrics(ticker: str, as_of: str, m: dict) -> None:
    from datetime import datetime, timezone
    with closing(db.connect()) as conn:
        conn.execute(MET_DDL)
        b = lambda v: None if v is None else int(bool(v))  # noqa: E731
        conn.execute("INSERT OR REPLACE INTO forensic_metrics VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (ticker.upper(), as_of, m.get("basic"), m.get("fd"), m.get("fd_ratio"), m.get("baby_shelf"), m.get("runway_months"),
                      b(m.get("toxic")), b(m.get("atm_eloc")), datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()


def metrics_at(conn, ticker: str, as_of: str | None = None, max_age: int = 120) -> dict | None:
    """그날(as_of) 이전 가장 최근 공시분석 수치(컨닝 없음) — max_age 일보다 오래되면 안 씀."""
    end = as_of or (date.today() + timedelta(days=1)).isoformat()
    start = (date.fromisoformat(end[:10]) - timedelta(days=max_age)).isoformat()
    try:
        r = conn.execute("SELECT as_of, basic, fd, fd_ratio, baby_shelf, runway_months, toxic, atm_eloc FROM forensic_metrics "
                         "WHERE ticker=? AND as_of < ? AND as_of >= ? ORDER BY as_of DESC LIMIT 1", (ticker.upper(), end, start)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not r:
        return None
    return dict(zip(["as_of", "basic", "fd", "fd_ratio", "baby_shelf", "runway_months", "toxic", "atm_eloc"], r))


def latest_brief(conn, ticker: str, days: int = 45) -> str | None:
    """AI PICK 용: 최근 보고서의 §10 적색경보·§2 런웨이 요약(짧게)."""
    try:
        r = conn.execute("SELECT content, as_of FROM forensic_reports WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker.upper(),)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not r or not r[0]:
        return None
    if r[1] and str(r[1]) < (date.today() - timedelta(days=days)).isoformat():
        return None
    txt = r[0]
    picks = []
    for key in ("적색경보", "런웨이", "베이비 쉐프", "악성 희석"):
        i = txt.find(key)
        if i >= 0:
            picks.append(re.sub(r"\s+", " ", txt[i:i + 260]))
    badge = f"🔴{txt.count('🔴')} 🟠{txt.count('🟠')} 🟢{txt.count('🟢')}"
    return (f"(as-of {r[1]}) {badge} | " + " | ".join(picks))[:900]


if __name__ == "__main__":
    import sys
    import quiet  # noqa: F401
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    config.apply_overrides()
    args = [a.upper() for a in sys.argv[1:] if not a.startswith("-")]
    res = run(tickers=args or None, out=print)  # 종목별 결과·합계는 run 이 출력
