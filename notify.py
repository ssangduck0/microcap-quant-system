"""텔레그램 알림(선택). 토큰은 환경변수 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 로만 읽습니다."""
import logging

import requests

import config

log = logging.getLogger("notify")


def send_telegram(text: str) -> bool:
    if not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID):
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("텔레그램 전송 실패: %s", type(e).__name__)  # 토큰이 URL에 있으므로 예외 전문은 남기지 않음
        return False
