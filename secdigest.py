"""📝 공시 한국어 요약 — 스캐너가 받은 SEC 공시(sec_feed)를 Claude Haiku 5.5 가 읽고 한 번에 뽑는다:
  ① 한국어 요약(2~3문장) · 분류 · 주가 영향 등급(A 큼 / B 보통 / C 작음)   — 🔔 공시 알림에 표시
  ② 역분할(병합) 일정(시행일·비율) → 🗓 일정 표 '역분할 시행'                 — 🔁 병합 후 레이더의 '병합 예정'이 시장 전체로
  ③ 13D/13G 대량 보유(보유자·지분율·경영개입형/단순투자형)                   — 🏦 대량 보유 화면
래빗스탁의 '공시 AI 요약' · 'RS Scanner(병합 예정)' · '13D/13G 분석기' 를 우리 데이터로.
· 한 사이클에 LIMIT 건(기본 12), 6건씩 묶어 한 번에 · 원문은 앞부분 + 핵심 단어 주변만 · Haiku 생각 끔
· 비용: 공시 1건 약 1~3원 · 🤖 AI 월 예산(aipick)과 같은 지갑
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import config
import db

MODEL = "claude-haiku-5-5"
LIMIT = 12
BATCH = 6
DAYS = 7
FORMS = ("8-K", "8-K/A", "6-K", "S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-1/A", "F-3", "F-3/A", "DEF 14A", "PRE 14A", "DEF 14C", "PRE 14C",
         "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A")
KEYS = ("reverse stock split", "reverse split", "split ratio", "effective", "percent of class", "aggregate amount", "offering", "warrant",
        "purchase agreement", "deficiency", "minimum bid", "fda", "approval", "agreement")
CATS = ("유상증자", "병합", "계약·수주", "임상·FDA", "실적", "경영진·이사회", "소송", "상장유지", "대량보유", "인수합병", "기타")
DDL = """CREATE TABLE IF NOT EXISTS sec_digest (accession TEXT PRIMARY KEY, ticker TEXT, form TEXT, filed TEXT, summary_ko TEXT, category TEXT, grade TEXT,
         rs_date TEXT, rs_ratio TEXT, holder TEXT, holder_pct REAL, holder_type TEXT, done_at TEXT)"""
SYSTEM = """당신은 SEC 공시를 한국 개인 투자자에게 설명하는 분석가입니다. 각 공시 발췌를 읽고 아래 JSON 만 출력하세요(설명·마크다운 금지).
{"items":[{"accession":"...","summary_ko":"핵심 2~3문장(금액·주식수·가격·날짜 등 숫자 포함, 회사명·티커는 원문대로)",
"category":"유상증자|병합|계약·수주|임상·FDA|실적|경영진·이사회|소송|상장유지|대량보유|인수합병|기타",
"grade":"A|B|C","rs":{"date":"YYYY-MM-DD","ratio":"1:10"} 또는 null,
"holder":{"name":"보유자","pct":숫자,"type":"경영개입형|단순투자형"} 또는 null}]}
규칙: grade A = 주가에 큰 영향(희석 공모·병합 시행·FDA 결과·인수합병·상장폐지 통지), B = 보통, C = 작음(일상 보고).
rs 는 역분할 '시행일(효력일)'이 발췌에 날짜로 있을 때만. holder 는 13D/13G 일 때만(13D=경영개입형, 13G=단순투자형), pct 는 Percent of Class.
발췌에 없는 사실을 지어내지 말 것."""


def ensure(conn) -> None:
    conn.execute(DDL)


def pending(conn, limit: int = LIMIT) -> list[dict]:
    ensure(conn)
    since = (date.today() - timedelta(days=DAYS)).isoformat()
    rows = conn.execute("""SELECT f.accession, f.ticker, f.form, f.filed, f.url, f.company FROM sec_feed f LEFT JOIN sec_digest d ON d.accession = f.accession
                           WHERE d.accession IS NULL AND f.ticker IS NOT NULL AND COALESCE(f.filed, substr(f.updated,1,10)) >= ? AND f.url IS NOT NULL
                           ORDER BY COALESCE(f.filed, f.updated) DESC LIMIT ?""", (since, limit * 4)).fetchall()
    out = []
    for a, t, fm, fl, u, co in rows:
        if str(fm or "").upper() in FORMS or str(fm or "").upper().startswith("424B"):
            out.append({"accession": a, "ticker": t, "form": fm, "filed": fl, "url": u, "company": co})
        if len(out) >= limit:
            break
    return out


def excerpt(text: str, head: int = 2500, cap: int = 4200) -> str:
    import forensic_ai
    body = re.sub(r"\s+", " ", text[:head])
    win = forensic_ai._windows(text, KEYS, width=350, cap=cap - len(body))
    return (body + "\n" + win)[:cap]


def run(client=None, post=None, out=print, limit: int = LIMIT) -> int:
    """요약 안 된 최근 공시를 BATCH 건씩 요약. 요약한 건수."""
    if not getattr(config, "SEC_DIGEST", True):
        return 0
    import aipick
    with closing(db.connect()) as conn:
        try:
            items = pending(conn, limit)
        except Exception:  # noqa: BLE001 (sec_feed 없음)
            return 0
        conn.commit()
    if not items:
        return 0
    if client is None:
        import sec
        client = sec.SecClient(config.require_sec_user_agent())
    n = 0
    for i in range(0, len(items), BATCH):
        part = items[i:i + BATCH]
        docs = []
        for it in part:
            try:
                txt = client.fetch_text(it["url"], limit=400_000)
            except Exception as e:  # noqa: BLE001
                txt = f"(본문 받기 실패: {e})"
            docs.append({"accession": it["accession"], "ticker": it["ticker"], "form": it["form"], "filed": it["filed"], "company": it["company"], "text": excerpt(txt)})
        prompt = json.dumps({"items": docs}, ensure_ascii=False)
        est = aipick.cost_usd(MODEL, len(prompt) // 3 + 400, 3000)
        if est * aipick.FX > aipick.budget_left_krw():
            out("공시 요약: 이번 달 AI 예산이 부족해 건너뜀")
            break
        try:
            text, tin, tout = aipick.call_claude(prompt, MODEL, 3000, post, system=SYSTEM, thinking={"type": "disabled"}, kind="digest")
        except Exception as e:  # noqa: BLE001
            out(f"공시 요약 실패: {e}")
            break
        aipick._add_spend(aipick.cost_usd(MODEL, tin, tout), "digest", tin, tout)
        n += save(part, text)
    if n:
        out(f"공시 요약: {n}건")
    return n


def _date(s) -> str | None:
    try:
        return date.fromisoformat(str(s)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def save(part: list[dict], text: str) -> int:
    s = text[text.find("{"):text.rfind("}") + 1] if "{" in (text or "") else "{}"
    try:
        got = {g.get("accession"): g for g in (json.loads(s).get("items") or [])}
    except ValueError:
        got = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    with closing(db.connect()) as conn:
        ensure(conn)
        for it in part:
            g = got.get(it["accession"])
            if not g:
                continue
            rs = g.get("rs") if isinstance(g.get("rs"), dict) else None
            hd = g.get("holder") if isinstance(g.get("holder"), dict) else None
            rs_date = _date(rs.get("date")) if rs else None
            pct = None
            if hd:
                try:
                    pct = float(str(hd.get("pct")).replace("%", ""))
                except (TypeError, ValueError):
                    pct = None
            conn.execute("INSERT OR REPLACE INTO sec_digest VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (it["accession"], it["ticker"], it["form"], it["filed"], str(g.get("summary_ko", ""))[:600],
                          g.get("category") if g.get("category") in CATS else "기타", g.get("grade") if g.get("grade") in ("A", "B", "C") else "C",
                          rs_date, str(rs.get("ratio", ""))[:20] if rs else None, str(hd.get("name", ""))[:120] if hd else None, pct,
                          hd.get("type") if hd and hd.get("type") in ("경영개입형", "단순투자형") else None, now))
            if rs_date:  # 🗓 일정 표에 '역분할 시행' — 병합 후 레이더의 병합 예정 · AI PICK 시점 판단
                try:
                    dup = conn.execute("SELECT 1 FROM events WHERE ticker=? AND date=? AND kind='역분할 시행'", (it["ticker"], rs_date)).fetchone()
                    if not dup:
                        conn.execute("INSERT INTO events (ticker, date, kind, title, source, origin, created_at) VALUES (?,?,?,?,?,?,?)",
                                     (it["ticker"], rs_date, "역분할 시행", f"역분할 {rs.get('ratio', '')} 시행", f"공시 요약({it['form']} {it['filed']})", "secdigest", now))
                except Exception:  # noqa: BLE001 (events 표 없음)
                    pass
            n += 1
        conn.commit()
    return n


def digests(conn, accessions: list[str]) -> dict[str, dict]:
    try:
        ensure(conn)
        qs = ",".join("?" * len(accessions)) or "''"
        return {r[0]: {"summary_ko": r[1], "category": r[2], "grade": r[3]} for r in
                conn.execute(f"SELECT accession, summary_ko, category, grade FROM sec_digest WHERE accession IN ({qs})", accessions)}
    except Exception:  # noqa: BLE001
        return {}


def holders(conn, days: int = 180):
    """🏦 13D/13G 대량 보유 — 최근 days 일."""
    import pandas as pd
    ensure(conn)
    q = conn.execute("""SELECT ticker, filed, form, holder, holder_pct, holder_type, summary_ko FROM sec_digest
                        WHERE holder IS NOT NULL AND filed >= ? ORDER BY filed DESC""", ((date.today() - timedelta(days=days)).isoformat(),)).fetchall()
    return pd.DataFrame(q, columns=["ticker", "filed", "form", "holder", "pct", "type", "summary_ko"])
