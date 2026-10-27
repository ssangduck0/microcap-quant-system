"""🌐 뉴스 번역 — 📰 뉴스 모음의 영어 제목·요약을 Claude Haiku 5.5 로 한국어 번역해 저장(한 번 번역하면 다시 안 함).

· 스캐너가 뉴스를 받은 직후 아직 번역 안 된 최근 뉴스를 최대 BATCH 건씩 한 번에 번역(소송 광고는 건너뜀)
· 비용: Haiku 5.5 입력 $0.10 · 출력 $0.50 / 100만 토큰 → 1건 약 0.15원. 🤖 AI 월 예산(aipick)과 같은 지갑에서 관리
· 고유명사(회사·약 이름·티커)·숫자는 그대로 두고, 금융 용어는 한국 투자자가 쓰는 말로(예: offering → 공모, registered direct → 등록 직접 공모)
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone

import config
import db

MODEL = "claude-haiku-5-5"
BATCH = 30
DAYS = 14
SYSTEM = """당신은 미국 증시 보도자료를 한국 개인 투자자에게 전달하는 번역가입니다.
각 항목의 title 과 summary 를 자연스러운 한국어로 번역하세요.
규칙: 회사·약·제품 이름, 티커, 숫자, 날짜, 금액은 원문 그대로. 금융 용어는 한국 투자자가 쓰는 말로
(offering 공모 · registered direct offering 등록 직접 공모 · private placement 사모 · reverse split 액면병합(역분할) ·
warrant 워런트 · at-the-market(ATM) ATM 증자 · Nasdaq deficiency notice 나스닥 상장유지 미달 통지 · FDA approval FDA 승인 · topline results 톱라인 결과).
summary 는 핵심만 2문장 이내로 줄여도 됩니다.
각 항목에 category(짧은 분류 한 단어: 실적·계약·FDA·임상·신제품·자금조달·희석·병합·상장유지·소송·인수합병·인사·기타)와
grade(초소형주 주가 영향: A 큼 · B 보통 · C 작음)와 score(0~100, 호재면 높게·악재면 낮게·소송 광고·단순 안내는 50 근처)를 붙이세요.
반드시 JSON 만 출력: {"items":[{"id":"...","title_ko":"...","summary_ko":"...","category":"...","grade":"A|B|C","score":0}]}"""


def ensure(conn) -> None:
    for col, typ in (("title_ko", "TEXT"), ("summary_ko", "TEXT"), ("category", "TEXT"), ("ai_grade", "TEXT"), ("ai_score", "INTEGER")):
        try:
            conn.execute(f"ALTER TABLE news ADD COLUMN {col} {typ}")
        except Exception:  # noqa: BLE001 (이미 있음)
            pass


def pending(conn, limit: int = BATCH) -> list[dict]:
    import news
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()
    rows = conn.execute("SELECT id, title, summary FROM news WHERE (title_ko IS NULL OR title_ko = '') AND published >= ? ORDER BY published DESC LIMIT ?",
                        (since, limit * 3)).fetchall()
    out = []
    for i, t, s in rows:
        if news.is_lawsuit_ad(t or "", s or ""):
            continue
        out.append({"id": i, "title": (t or "")[:200], "summary": (s or "")[:400]})
        if len(out) >= limit:
            break
    return out


def run(post=None, out=print, limit: int = BATCH) -> int:
    """번역 안 된 최근 뉴스를 한 번에 번역. 번역한 건수."""
    if not getattr(config, "NEWS_TRANSLATE", True):
        return 0
    import aipick
    with closing(db.connect()) as conn:
        ensure(conn)
        conn.commit()
        items = pending(conn, limit)
    if not items:
        return 0
    prompt = json.dumps({"items": items}, ensure_ascii=False)
    est = aipick.cost_usd(MODEL, len(prompt) // 2 + 400, 6000)
    if est * aipick.FX > aipick.budget_left_krw():
        out("뉴스 번역: 이번 달 AI 예산이 부족해 건너뜀")
        return 0
    text, tin, tout = _call(prompt, post)
    aipick._add_spend(aipick.cost_usd(MODEL, tin, tout), "translate", tin, tout)
    s = text[text.find("{"):text.rfind("}") + 1] if "{" in text else "{}"
    try:
        got = json.loads(s).get("items") or []
    except ValueError:
        got = []
    ids = {x["id"] for x in items}
    n = 0
    with closing(db.connect()) as conn:
        for g in got:
            if g.get("id") in ids and str(g.get("title_ko", "")).strip():
                gr = str(g.get("grade", "")).strip().upper()[:1]
                try:
                    sc = max(0, min(100, int(float(g.get("score")))))
                except (TypeError, ValueError):
                    sc = None
                conn.execute("UPDATE news SET title_ko=?, summary_ko=?, category=?, ai_grade=?, ai_score=? WHERE id=?",
                             (str(g["title_ko"])[:300], str(g.get("summary_ko", ""))[:600], str(g.get("category", ""))[:20], gr if gr in "ABC" and gr else None, sc, g["id"]))
                n += 1
        conn.commit()
    out(f"뉴스 번역: {n}건 · ${aipick.cost_usd(MODEL, tin, tout):.4f}")
    return n


def _call(prompt: str, post=None) -> tuple[str, int, int]:
    import aipick
    return aipick.call_claude(prompt, MODEL, 6000, post, system=SYSTEM, thinking={"type": "disabled"}, kind="translate")  # 번역엔 생각이 필요 없음(비용만 늘어남)
