"""🤖 Claude 복기 — 우리만의 AI 3단계(2026-10-28). 주 1회, 🔍 부검에 쌓인 놓친 펌핑·실패 신호를 Haiku 가 읽고
   ① 놓친 펌핑의 촉매 종류 ② 실패 신호의 원인 종류를 정해진 분류표에서 고르고 ③ '규칙 후보'(조건 → 기대 → 검증 방법)를 최대 5개 제안한다.
결과는 pump_autopsy / signal_autopsy 의 ai_cat·ai_note 열과 review_runs 표에 남고, 🔍 부검 탭에 보인다. 규칙 후보는 사람이 읽고 🕰 타임머신 조합으로 검증한 뒤에만 반영(자동 반영 없음).
비용: Haiku(입력 $0.10/백만 토큰) · 한 번에 최대 24건 → 약 20~40원. aipick 월 예산 지갑을 같이 쓴다. AI_REVIEW_ENABLED 로 끌 수 있다.
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import db

MODEL = "claude-haiku-5-5"
MAX_MISS, MAX_FAIL = 12, 12
WEEK_DAYS = 6            # 마지막 복기 뒤 이만큼 지나야 다시(주 1회)
MAX_OUT = 3500
PUMP_CATS = ["FDA·임상", "계약·파트너십", "인수합병·대량보유", "실적·가이던스", "숏스퀴즈·공매 커버", "병합·주식수 변화", "자금조달 중단·희석 해소", "밈·테마 수급", "세력·펌프(재료 없음)", "알 수 없음"]
FAIL_CATS = ["희석 출회", "장세·시장 하락", "공매 눌림", "거래량 부족", "재료 소멸·기대 이탈", "시간외 펌핑 되돌림", "기술적 이탈(지지 붕괴)", "진입 늦음(이미 오른 뒤)", "알 수 없음"]
SYSTEM = """당신은 미국 초소형주(마이크로캡) 급등주를 연구하는 한국인 퀀트 분석가입니다. 아래 JSON 에는 두 묶음이 있습니다.
- miss: 우리 대시보드가 사전에 신호를 내지 못한 '놓친 펌핑'(전날 기준 특징 + 전후 공시·뉴스 제목)
- fail: 우리가 신호를 냈지만 목표에 못 가고 '실패'한 것(신호일 특징 + 그 뒤 공시·뉴스 + 규칙 태그)
할 일: 각 항목의 촉매/원인을 아래 분류표에서 **하나만** 고르고(없으면 '알 수 없음'), 한국어 한 줄(60자 이내)로 근거를 쓰세요. 추측은 '추정'이라고 밝히세요.
그리고 전체를 보고 우리 발굴 규칙에 보탤 '규칙 후보'를 최대 5개 제안하세요. 각 후보는 숫자로 검증 가능한 조건이어야 합니다(예: "20일 거래대금 $100만↑ & 낙폭 −30% 안 & 호재 공시 당일").
반드시 아래 JSON 만 출력(설명·마크다운 금지):
{"miss":[{"ticker":"","date":"","cat":"","why":""}], "fail":[{"source":"","date":"","ticker":"","cat":"","why":""}],
 "rules":[{"name":"","condition":"","expect":"","check":""}], "summary":"전체 한 줄(80자 이내)"}
miss 의 cat 은 __PUMP__ 중 하나, fail 의 cat 은 __FAIL__ 중 하나.""".replace("__PUMP__", " / ".join(PUMP_CATS)).replace("__FAIL__", " / ".join(FAIL_CATS))   # % 서식 안 씀(본문에 % 기호가 있음)
DDL = """CREATE TABLE IF NOT EXISTS review_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT, since TEXT, until TEXT, model TEXT, n_miss INTEGER, n_fail INTEGER,
         cost_krw REAL, summary TEXT, rules TEXT, raw TEXT)"""
NEW_COLS = {"ai_cat": "TEXT", "ai_note": "TEXT", "ai_run": "INTEGER"}
FEAT_SHOW = ["bucket", "dvol20", "float", "mcap", "dd20", "rsi", "vol_x", "zone", "stage", "dil", "si_pct", "sv_pct", "regsho", "sec7", "news7", "regime"]


def ensure(conn) -> None:
    import autopsy
    autopsy.ensure(conn)
    conn.execute(DDL)
    for tbl in ("pump_autopsy", "signal_autopsy"):
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
        for c, typ in NEW_COLS.items():
            if c not in have:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {c} {typ}")


# ---------------------------------------------------------------- 재료 모으기
def _docs(conn, ticker: str, since: str, until: str, limit: int = 4) -> list[str]:
    out = []
    try:
        for form, d0, sent, tags, items in conn.execute("SELECT form, COALESCE(filed, substr(updated,1,10)), sentiment, tags, items FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) BETWEEN ? AND ? ORDER BY updated DESC LIMIT ?",
                                                        (ticker, since, until, limit)):
            try:
                tg = ",".join(json.loads(tags or "[]")[:4])
            except Exception:  # noqa: BLE001
                tg = ""
            out.append(f"{d0} 공시 {form} {sent or ''} {tg} {('항목 ' + str(items)[:40]) if items else ''}".strip())
    except Exception:  # noqa: BLE001
        pass
    try:
        for d0, title, sent in conn.execute("SELECT substr(published,1,10), title, sentiment FROM news WHERE ticker=? AND substr(published,1,10) BETWEEN ? AND ? ORDER BY published DESC LIMIT ?",
                                            (ticker, since, until, limit)):
            out.append(f"{d0} 뉴스 {sent or ''} {(title or '')[:80]}".strip())
    except Exception:  # noqa: BLE001
        pass
    return out


def _feat(js: str | None) -> dict:
    try:
        f = json.loads(js or "{}")
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for k in FEAT_SHOW:
        v = f.get(k)
        if v is None:
            continue
        out[k] = round(v, 2) if isinstance(v, float) else v
    return out


def gather(conn, days: int = 7, max_miss: int = MAX_MISS, max_fail: int = MAX_FAIL, only_new: bool = True) -> dict:
    """최근 days 일의 놓친 펌핑(등락 큰 순) · 실패 신호(최근 순). only_new=True 면 아직 복기 안 한 것만."""
    ensure(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    cond = " AND ai_run IS NULL" if only_new else ""
    miss = []
    for r in conn.execute(f"SELECT date, ticker, pump_pct, hi_pct, session, features, catalyst FROM pump_autopsy WHERE caught=0 AND date >= ?{cond} ORDER BY hi_pct DESC LIMIT ?", (since, max_miss)):
        d0 = r[0]
        miss.append({"ticker": r[1], "date": d0, "pump_pct": round(r[2] or 0, 1), "hi_pct": round(r[3] or 0, 1), "session": r[4], "features_prev_day": _feat(r[5]),
                     "docs": _docs(conn, r[1], (date.fromisoformat(d0) - timedelta(days=3)).isoformat(), (date.fromisoformat(d0) + timedelta(days=1)).isoformat()) or [r[6] or ""]})
    fail = []
    for r in conn.execute(f"SELECT source, date, ticker, entry, max_up, max_down, features, tags FROM signal_autopsy WHERE date >= ?{cond} ORDER BY date DESC LIMIT ?", (since, max_fail)):
        d0 = r[1]
        try:
            import autopsy
            tags = [autopsy.TAGS.get(k, k) for k in json.loads(r[7] or "[]")]
        except Exception:  # noqa: BLE001
            tags = []
        fail.append({"source": r[0], "date": d0, "ticker": r[2], "entry": r[3], "max_up_pct": r[4], "max_down_pct": r[5], "features_signal_day": _feat(r[6]), "rule_tags": tags,
                     "docs_after": _docs(conn, r[2], d0, (date.fromisoformat(d0) + timedelta(days=12)).isoformat())})
    return {"since": since, "until": date.today().isoformat(), "miss": miss, "fail": fail}


def build_prompt(g: dict) -> str:
    return json.dumps({"miss": g["miss"], "fail": g["fail"]}, ensure_ascii=False)


# ---------------------------------------------------------------- 답 해석
def parse(text: str) -> dict:
    s = re.sub(r"```(?:json)?", "", text or "").strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("JSON 이 아닌 답")
    d = json.loads(s[i:j + 1])
    out = {"miss": [], "fail": [], "rules": [], "summary": str(d.get("summary") or "")[:160]}
    for m in d.get("miss") or []:
        c = m.get("cat") if m.get("cat") in PUMP_CATS else "알 수 없음"
        out["miss"].append({"ticker": str(m.get("ticker", "")).upper(), "date": str(m.get("date", "")), "cat": c, "why": str(m.get("why", ""))[:120]})
    for m in d.get("fail") or []:
        c = m.get("cat") if m.get("cat") in FAIL_CATS else "알 수 없음"
        out["fail"].append({"source": str(m.get("source", "")), "ticker": str(m.get("ticker", "")).upper(), "date": str(m.get("date", "")), "cat": c, "why": str(m.get("why", ""))[:120]})
    for r in (d.get("rules") or [])[:5]:
        if r.get("condition"):
            out["rules"].append({k: str(r.get(k, ""))[:200] for k in ("name", "condition", "expect", "check")})
    return out


def save(conn, g: dict, parsed: dict, cost_krw: float, raw: str, model: str = MODEL) -> int:
    ensure(conn)
    cur = conn.execute("INSERT INTO review_runs (run_at, since, until, model, n_miss, n_fail, cost_krw, summary, rules, raw) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (db.utcnow_iso(), g["since"], g["until"], model, len(g["miss"]), len(g["fail"]), cost_krw, parsed["summary"], json.dumps(parsed["rules"], ensure_ascii=False), raw[:20000]))
    run_id = cur.lastrowid
    for m in parsed["miss"]:
        conn.execute("UPDATE pump_autopsy SET ai_cat=?, ai_note=?, ai_run=? WHERE ticker=? AND date=?", (m["cat"], m["why"], run_id, m["ticker"], m["date"]))
    for m in parsed["fail"]:
        conn.execute("UPDATE signal_autopsy SET ai_cat=?, ai_note=?, ai_run=? WHERE ticker=? AND date=? AND (source=? OR ?='')", (m["cat"], m["why"], run_id, m["ticker"], m["date"], m["source"], m["source"]))
    # 답에 빠진 항목도 '이번 복기에 포함'으로 표시(다음 주에 또 보내지 않게)
    for m in g["miss"]:
        conn.execute("UPDATE pump_autopsy SET ai_run=COALESCE(ai_run, ?) WHERE ticker=? AND date=?", (run_id, m["ticker"], m["date"]))
    for m in g["fail"]:
        conn.execute("UPDATE signal_autopsy SET ai_run=COALESCE(ai_run, ?) WHERE source=? AND ticker=? AND date=?", (run_id, m["source"], m["ticker"], m["date"]))
    conn.commit()
    return run_id


# ---------------------------------------------------------------- 실행
def latest(conn) -> dict | None:
    ensure(conn)
    r = conn.execute("SELECT * FROM review_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    try:
        d["rules"] = json.loads(d.get("rules") or "[]")
    except Exception:  # noqa: BLE001
        d["rules"] = []
    return d


def due(conn) -> bool:
    last = latest(conn)
    if not last:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(last["run_at"]).replace(tzinfo=timezone.utc) >= timedelta(days=WEEK_DAYS)
    except Exception:  # noqa: BLE001
        return True


def run(conn=None, days: int = 7, out=print, call=None, force: bool = False) -> dict:
    """주 1회 복기. call(prompt, system) → (text, in_tok, out_tok) 를 넣으면 가짜로 테스트. 반환 {"status", ...}."""
    import config
    if conn is None:
        with closing(db.connect()) as c:
            return run(c, days, out, call, force)
    ensure(conn)
    if not getattr(config, "AI_REVIEW_ENABLED", True) and not force:
        return {"status": "off"}
    if not force and not due(conn):
        return {"status": "not_due"}
    g = gather(conn, days)
    if not g["miss"] and not g["fail"]:
        out("🤖 복기: 새로 볼 놓친 펌핑·실패 신호가 없어 건너뜀")
        return {"status": "empty"}
    import aipick
    prompt = build_prompt(g)
    est = aipick.cost_usd(MODEL, len(prompt) // 3 + len(SYSTEM) // 3 + 200, MAX_OUT)
    if est * aipick.FX > aipick.budget_left_krw():
        out(f"🤖 복기: 이번 달 AI 예산이 부족해 건너뜀(예상 {est * aipick.FX:.0f}원, 남은 {aipick.budget_left_krw():.0f}원)")
        return {"status": "budget"}
    try:
        if call:
            text, tin, tout = call(prompt, SYSTEM)
        else:
            text, tin, tout = aipick.call_claude(prompt, MODEL, MAX_OUT, system=SYSTEM, thinking={"type": "disabled"}, kind="review")
        parsed = parse(text)
    except Exception as e:  # noqa: BLE001
        out(f"🤖 복기 실패: {e}")
        return {"status": "error", "error": str(e)}
    cost = aipick.cost_usd(MODEL, tin, tout)
    aipick._add_spend(cost, "review", tin, tout)
    run_id = save(conn, g, parsed, cost * aipick.FX, text)
    out(f"🤖 복기 #{run_id}: 놓친 펌핑 {len(g['miss'])}건 · 실패 신호 {len(g['fail'])}건 · 규칙 후보 {len(parsed['rules'])}개 · 약 {cost * aipick.FX:.0f}원 · {parsed['summary']}")
    for r in parsed["rules"]:
        out(f"  규칙 후보: {r['name']} — {r['condition']} → {r['expect']} (검증: {r['check']})")
    return {"status": "ok", "run_id": run_id, "n_miss": len(g["miss"]), "n_fail": len(g["fail"]), "rules": parsed["rules"], "summary": parsed["summary"], "cost_krw": cost * aipick.FX}


def cat_counts(conn, days: int = 90) -> dict:
    ensure(conn)
    since = (date.today() - timedelta(days=days)).isoformat()
    miss = conn.execute("SELECT ai_cat, COUNT(*) FROM pump_autopsy WHERE caught=0 AND ai_cat IS NOT NULL AND date >= ? GROUP BY ai_cat ORDER BY 2 DESC", (since,)).fetchall()
    fail = conn.execute("SELECT ai_cat, COUNT(*) FROM signal_autopsy WHERE ai_cat IS NOT NULL AND date >= ? GROUP BY ai_cat ORDER BY 2 DESC", (since,)).fetchall()
    return {"miss": [(a, b) for a, b in miss], "fail": [(a, b) for a, b in fail]}


if __name__ == "__main__":
    import sys
    print(run(force="--force" in sys.argv))
