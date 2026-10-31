"""🏢 기업 설명(2026-10-31 · 김곰 워치리스트 '기업 설명' 참고): 야후 회사 소개(영어)를 Claude Haiku 가 쉬운 한국어 2~4문장으로.
종목당 한 번만(저장) · 비용 약 1원(Haiku 5.5, 생각 끔) · AI 월 예산 지갑(aipick) 안에서.
아침 작업이 워치리스트·PICK·AI PICK·급상승 종목 중 없는 것부터 하루 DAILY 개 · 종목 화면 버튼(주인)으로도."""
from __future__ import annotations

from contextlib import closing

import config
import db

MODEL = "claude-haiku-5-5"
DAILY = 40
DDL = "CREATE TABLE IF NOT EXISTS company_desc (ticker TEXT PRIMARY KEY, en TEXT, ko TEXT, source TEXT, updated TEXT)"
SYSTEM = ("당신은 미국 소형주 회사 소개를 한국 개인 투자자에게 설명합니다. 영어 원문을 쉬운 한국어 2~4문장으로 옮기세요: "
          "무엇을 만들거나 파는 회사인지 · 주요 제품·고객·지역 · 본사. 회사명·제품명·숫자는 원문대로. 원문에 없는 내용(전망·평가)은 쓰지 말 것. 설명 문장만 출력.")


def ensure(conn) -> None:
    conn.execute(DDL)


def get(t: str) -> dict | None:
    try:
        with closing(db.connect()) as conn:
            ensure(conn)
            r = conn.execute("SELECT ticker, en, ko, source, updated FROM company_desc WHERE ticker=?", (t.upper(),)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return dict(r) if r else None


def fetch_en(t: str) -> tuple[str, str]:
    """(영어 소개, 출처). 야후 longBusinessSummary — 오프라인·실패면 빈칸."""
    if getattr(config, "OFFLINE", False):
        return "", ""
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        return (info.get("longBusinessSummary") or "").strip(), "Yahoo"
    except Exception:  # noqa: BLE001
        return "", ""


def translate(en: str, post=None) -> tuple[str, float]:
    """(한국어, 비용 USD). 예산이 모자라면 빈칸."""
    import aipick
    prompt = en[:4000]
    est = aipick.cost_usd(MODEL, len(prompt) // 3 + 200, 600)
    if est * aipick.FX > aipick.budget_left_krw():
        return "", 0.0
    text, tin, tout = aipick.call_claude(prompt, MODEL, 600, post, system=SYSTEM, thinking={"type": "disabled"}, kind="desc")
    usd = aipick.cost_usd(MODEL, tin, tout)
    aipick._add_spend(usd, "desc", tin, tout)
    return (text or "").strip(), usd


def ensure_one(t: str, fetch=None, post=None) -> dict | None:
    """저장된 한국어 설명이 없으면 받아서 번역해 저장. 실패하면 None."""
    t = t.upper()
    cur = get(t)
    if cur and cur.get("ko"):
        return cur
    en, src = (fetch or fetch_en)(t)
    if not en:
        return cur
    ko, _ = translate(en, post)
    with closing(db.connect()) as conn:
        ensure(conn)
        conn.execute("INSERT OR REPLACE INTO company_desc VALUES (?,?,?,?,?)", (t, en, ko or None, src, db.utcnow_iso()))
        conn.commit()
    return get(t)


def priority(conn, n: int = 200) -> list[str]:
    """설명을 먼저 채울 종목: 워치리스트 → 오늘 PICK·AI PICK → 급상승 → 최신 스냅샷(순서 유지, 중복 제거)."""
    out: list[str] = []
    for sql in ("SELECT ticker FROM watchlist WHERE list != '블랙'", "SELECT ticker FROM pick_signals WHERE date=(SELECT MAX(date) FROM pick_signals)",
                "SELECT ticker FROM ai_pick WHERE date=(SELECT MAX(date) FROM ai_pick) ORDER BY rank",
                "SELECT ticker FROM toss_rank WHERE kind='up' AND date=(SELECT MAX(date) FROM toss_rank) ORDER BY rank",
                "SELECT ticker FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots) ORDER BY pump_score DESC"):
        try:
            out += [str(r[0]).upper() for r in conn.execute(sql) if r[0]]
        except Exception:  # noqa: BLE001
            pass
    return list(dict.fromkeys(out))[:n]


def morning(limit: int = DAILY, out=print, fetch=None, post=None) -> int:
    with closing(db.connect()) as conn:
        ensure(conn)
        have = {r[0] for r in conn.execute("SELECT ticker FROM company_desc WHERE ko IS NOT NULL OR (en IS NOT NULL AND updated >= date('now','-30 day'))")}
        todo = [t for t in priority(conn) if t not in have][:limit]
    n = 0
    for t in todo:
        try:
            r = ensure_one(t, fetch, post)
            n += bool(r and r.get("ko"))
        except Exception:  # noqa: BLE001
            continue
    if todo:
        out(f"🏢 기업 설명: {len(todo)}종목 시도 · 한국어 {n}개 저장")
    return n
