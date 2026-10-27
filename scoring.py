"""점수 계산. 모든 점수는 항목별 점수(detail)를 같이 반환해서 '왜 이 점수인지' 대시보드에서 볼 수 있습니다.
점수·참고 레벨은 규칙 기반 계산값이며 투자 권유가 아닙니다."""
from __future__ import annotations

STATUS_LABEL = {
    "CLEAN": "🟢 최근 공시에서 희석 키워드 미검출",
    "ELOC": "🟡 ELOC 계약 정황",
    "OFFERING": "🟠 최근 공모/워런트 정황",
    "CB": "🔴 전환사채/전환우선주 정황",
    "ATM": "🚫 ATM 정황 (잔여한도 미확인)",
    "UNKNOWN": "⚪ 확인 불가",
}
QUANT_PENALTY = {"ATM": 40, "CB": 25, "ELOC": 10, "OFFERING": 10, "UNKNOWN": 10, "CLEAN": 0}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def quant_score(m: dict, float_shares: float | None, status: str, flags: dict) -> tuple[float, dict]:
    d: dict[str, float] = {"기본": 15.0}
    d["낙폭"] = round(min(abs(m["drawdown_pct"]), 60) / 60 * 30, 1)
    fs = float_shares or 0
    d["유통주식"] = 20.0 if 0 < fs < 10e6 else 15.0 if 0 < fs < 20e6 else 8.0 if 0 < fs < 50e6 else 0.0
    vm = m.get("volume_mult")
    d["거래량"] = round(_clamp(vm, 0, 5) / 5 * 20, 1) if vm else 0.0
    bp = m.get("buy_pressure")
    d["매수체결"] = round(_clamp((bp - 45) / 20 * 15, 0, 15), 1) if bp is not None else 0.0
    d["희석 패널티"] = float(-QUANT_PENALTY.get(status, 10))
    if flags.get("GOING_CONCERN"):
        d["계속기업 의구심"] = -5.0
    return round(_clamp(sum(d.values()), 0, 100), 1), d


def pump_checklist(m: dict, float_shares: float | None, status: str, flags: dict):
    """장마감 펌핑 체크리스트. ATM 정황이 있으면 제외(excluded=True)하되 기록은 남깁니다(통계용)."""
    dd = m["drawdown_pct"]
    fs = float_shares or 0
    vm = m.get("volume_mult") or 0
    bp = m.get("buy_pressure")
    checks = [
        ("낙폭 -20% 이하", dd <= -20),
        ("유통주식 2천만 이하", 0 < fs < 20e6),
        ("거래량 2배 이상", vm >= 2),
        ("매수체결 55% 이상", bp is not None and bp >= 55),
        ("ATM 미검출", status != "ATM"),
        ("CB 미검출", status != "CB"),
        ("희석 상태 확인됨", status != "UNKNOWN"),
    ]
    if status == "ATM":
        return 0.0, {"점수": {}, "checks": checks}, True

    d: dict[str, float] = {}
    d["낙폭"] = 25.0 if dd <= -30 else 18.0 if dd <= -20 else 10.0
    d["유통주식"] = 25.0 if 0 < fs < 10e6 else 20.0 if 0 < fs < 20e6 else 0.0
    d["거래량"] = 20.0 if vm >= 3 else 14.0 if vm >= 2 else 8.0 if vm >= 1.5 else 0.0
    d["매수체결"] = 15.0 if bp is not None and bp >= 60 else 10.0 if bp is not None and bp >= 55 else 0.0
    d["희석"] = {"CLEAN": 15.0, "ELOC": 5.0, "OFFERING": 0.0, "CB": -15.0}.get(status, 0.0)
    return round(_clamp(sum(d.values()), 0, 100), 1), {"점수": d, "checks": checks}, False


def reference_levels(price: float, atr: float | None):
    """ATR 기반 참고 레벨: 진입 = 현재가 - 0.5ATR, 손절 = 진입 - 1ATR, 목표 = 진입 + 2ATR (손익비 1:2)."""
    if not atr or atr <= 0:
        return None, None, None
    entry = max(price - 0.5 * atr, price * 0.5)
    stop = max(entry - atr, entry * 0.3)
    target = entry + 2 * atr
    return entry, stop, target


def baby_shelf(float_shares: float | None, price: float | None):
    """Baby Shelf 근사: 공개유통시가총액(비계열 주식 x 가격) < 7,500만달러면 12개월 내 S-3 1차 발행 상한은 그 1/3.

    float_shares(yfinance)는 SEC 기준 non-affiliate 주식수와 다를 수 있고, 규정은 최근 60일 내 최고가를 쓰므로 '근사'입니다.
    """
    if not float_shares or not price:
        return None
    value = float_shares * price
    return {"public_float_value": value, "is_baby_shelf": value < 75e6,
            "cap": value / 3 if value < 75e6 else None}
