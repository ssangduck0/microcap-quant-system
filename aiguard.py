"""🤖⚠️ AI 계정 문제 감지 (2026-10-30).

왜: 10/30 08:12 부터 Anthropic 계정 충전 잔액이 바닥나 공시 요약·뉴스 번역이 하루 종일 'HTTP 400 credit balance is too low' 로 실패했는데
    로그(INFO/WARNING)에만 남아 아무도 몰랐다. 우리 월 예산 지갑(aipick, 5만 원)과는 별개인 '계정 자체' 문제라 충전은 사용자만 할 수 있다.
어떻게: aipick.call_claude · aisummary.call 이 4xx 를 받으면 note() → 충전 부족·키 오류면 meta 에 기록하고 하루 한 번 텔레그램.
       다음 호출이 성공하면 ok() 가 기록을 지운다(충전 뒤 저절로 경고가 사라짐). ⚙️ 관리 모드 🤖 AI 비용 칸이 problem() 으로 빨간 경고.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import db

KEY = "ai_account_problem"
ALERT_KEY = "ai_account_alerted"


def classify(status: int | None, text: str | None) -> str | None:
    """응답 → 사용자가 고쳐야 하는 계정 문제면 이유(한국어), 아니면 None(일시 오류·요청 오류는 None)."""
    t = (text or "").lower()
    if "credit balance is too low" in t or "billing" in t and "error" in t:
        return "Anthropic 계정 충전 잔액 부족"
    if status == 401 or "authentication_error" in t or "invalid x-api-key" in t:
        return "Anthropic API 키 오류(.env 의 ANTHROPIC_API_KEY)"
    if status == 403 or "permission_error" in t:
        return "Anthropic API 권한 오류"
    return None


def note(status: int | None, text: str | None, send=None) -> str | None:
    """계정 문제면 기록 + (오늘 처음이면) 텔레그램. 이유를 돌려줌. 기록·전송 실패는 조용히 넘김(본 기능의 오류 메시지를 가리지 않게)."""
    reason = classify(status, text)
    if not reason:
        return None
    try:
        db.set_meta(KEY, json.dumps({"reason": reason, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "detail": str(text or "")[:160]},
                                    ensure_ascii=False))
        today = date.today().isoformat()
        if (db.get_meta(ALERT_KEY) or {}).get("value") != today:
            db.set_meta(ALERT_KEY, today)
            if send is None:
                import notify
                send = notify.send_telegram
            send(f"🤖⚠️ AI 호출 실패 — {reason}. 공시 요약·뉴스 번역·AI PICK·공시분석이 멈춰요. "
                 "console.anthropic.com → Billing 에서 충전(키 오류면 서버 .env 확인)하세요. 우리 월 예산(관리 모드)과는 별개예요. "
                 "다음 호출이 성공하면 이 경고는 저절로 사라져요.")
    except Exception:  # noqa: BLE001
        pass
    return reason


def ok() -> None:
    """호출 성공: 남아 있던 계정 문제 기록을 지운다."""
    try:
        m = db.get_meta(KEY)
        if m and m.get("value"):
            db.set_meta(KEY, "")
    except Exception:  # noqa: BLE001
        pass


def problem(hours: float = 48) -> dict | None:
    """최근 hours 시간 안에 기록된(아직 성공으로 지워지지 않은) 계정 문제."""
    try:
        m = db.get_meta(KEY)
        if not m or not m.get("value"):
            return None
        d = json.loads(m["value"])
        at = datetime.fromisoformat(d["at"])
        if datetime.now(timezone.utc) - at > timedelta(hours=hours):
            return None
        return d
    except Exception:  # noqa: BLE001
        return None
