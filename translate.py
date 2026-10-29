"""🌐 뉴스 번역 — 📰 뉴스 모음의 영어 제목·요약을 Claude Haiku 5.5 로 한국어 번역해 저장(한 번 번역하면 다시 안 함).

· 스캐너가 뉴스를 받은 직후 아직 번역 안 된 최근 뉴스를 최대 BATCH 건씩 한 번에 번역(소송 광고는 건너뜀)
· 비용: Haiku 5.5 입력 $0.10 · 출력 $0.50 / 100만 토큰 → 1건 약 0.15원. 🤖 AI 월 예산(aipick)과 같은 지갑에서 관리
· 고유명사(회사·약 이름·티커)·숫자는 그대로 두고, 금융 용어는 한국 투자자가 쓰는 말로(예: offering → 공모, registered direct → 등록 직접 공모)
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import datetime, timedelta, timezone

import config
import db

MODEL = "claude-haiku-5-5"
BATCH = 10         # 10/29: 30건이면 Haiku 답이 max_tokens 에 잘려 JSON 이 깨짐 → 한 건도 저장 못 하고 매 사이클(12분) 재시도 — 36시간 158번 · $0.44 낭비한 사고
MAX_OUT = 8000     # 10건 × 약 450토큰 = 4,500 + 여유(예전 6000 은 30건에 늘 모자랐음 — 서버 기록: 출력 토큰이 매번 정확히 6000)
MAX_TRIES = 3      # 같은 뉴스를 이만큼 보내도 번역이 안 오면 건너뜀(영어로 보임) — 무한 재시도 방지
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
    for col, typ in (("title_ko", "TEXT"), ("summary_ko", "TEXT"), ("category", "TEXT"), ("ai_grade", "TEXT"), ("ai_score", "INTEGER"), ("tr_tries", "INTEGER")):
        try:
            conn.execute(f"ALTER TABLE news ADD COLUMN {col} {typ}")
        except Exception:  # noqa: BLE001 (이미 있음)
            pass


def pending(conn, limit: int = BATCH) -> list[dict]:
    import news
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()
    # 종목이 붙은 뉴스(화면 기본 필터 '나스닥만' 에 보이는 것) 먼저, 그다음 최신순 · MAX_TRIES 번 실패한 것은 제외
    rows = conn.execute("SELECT id, title, summary FROM news WHERE (title_ko IS NULL OR title_ko = '') AND COALESCE(tr_tries, 0) < ? AND published >= ? "
                        "ORDER BY (ticker IS NULL), published DESC LIMIT ?", (MAX_TRIES, since, limit * 3)).fetchall()
    out = []
    for i, t, s in rows:
        if news.is_lawsuit_ad(t or "", s or ""):
            continue
        out.append({"id": i, "title": (t or "")[:200], "summary": (s or "")[:400]})
        if len(out) >= limit:
            break
    return out


def parse_items(text: str) -> list[dict]:
    """답 JSON → items. 답이 max_tokens 에 잘려 JSON 이 깨졌으면 온전한 항목({...})만 건져 낸다(예전엔 전부 버림)."""
    s = text[text.find("{"):text.rfind("}") + 1] if "{" in text else "{}"
    try:
        got = json.loads(s).get("items")
        if isinstance(got, list):
            return [g for g in got if isinstance(g, dict)]
        return []
    except ValueError:
        pass
    out = []
    for m in re.finditer(r"\{[^{}]*\"id\"\s*:[^{}]*\}", text):
        try:
            g = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(g, dict) and g.get("id"):
            out.append(g)
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
    est = aipick.cost_usd(MODEL, len(prompt) // 2 + 400, MAX_OUT)
    if est * aipick.FX > aipick.budget_left_krw():
        out("뉴스 번역: 이번 달 AI 예산이 부족해 건너뜀")
        return 0
    text, tin, tout = _call(prompt, post)
    aipick._add_spend(aipick.cost_usd(MODEL, tin, tout), "translate", tin, tout)
    got = parse_items(text)
    ids = {x["id"] for x in items}
    n = 0
    with closing(db.connect()) as conn:
        conn.executemany("UPDATE news SET tr_tries = COALESCE(tr_tries, 0) + 1 WHERE id=?", [(i,) for i in ids])   # 보낸 횟수(실패해도 무한 재시도 안 함)
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
    cut = tout >= MAX_OUT - 8   # 출력 토큰이 한도에 닿았으면 답이 잘린 것
    out(f"뉴스 번역: {n}건/{len(items)}건 · ${aipick.cost_usd(MODEL, tin, tout):.4f}" + (f" · ⚠️ 답이 잘림(출력 {tout} 토큰 — 묶음을 더 줄여야 함)" if cut else "")
        + (f" · ⚠️ 한 건도 못 읽음({MAX_TRIES}번 실패한 뉴스는 건너뜀)" if n == 0 else ""))
    return n


def _call(prompt: str, post=None) -> tuple[str, int, int]:
    import aipick
    return aipick.call_claude(prompt, MODEL, MAX_OUT, post, system=SYSTEM, thinking={"type": "disabled"}, kind="translate")  # 번역엔 생각이 필요 없음(비용만 늘어남)
