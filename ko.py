"""🇰🇷 화면용 한글 이름(2026-11-02 · 사용자 '영어로 나오는 곳 한글로'): 공시 태그 · 서류 이름 · 8-K 항목 · 내부자 직함 · 제출 기업 구분 · 주문 메모.
자료(DB)는 그대로 두고 화면에 보일 때만 바꾼다(검색·기록·판정이 원래 값에 기대므로)."""
from __future__ import annotations

import json
import re

TAG = {"ATM": "ATM(시장가 수시 발행)", "CB": "전환사채", "ELOC": "ELOC(주식 매수 약정)", "WARRANT": "워런트", "OFFERING": "공모·사모",
       "REVERSE_SPLIT": "병합(역분할)", "GOING_CONCERN": "계속기업 의구심", "SHELF_S3": "선반 등록(S-3)", "PARTIAL_CHECK": "일부만 확인",
       "TOXIC": "악성 전환", "PIPE": "사모(PIPE)", "DELIST": "상장폐지 통지", "기타": "기타"}
FORM = {"8-K": "수시 공시", "8-K/A": "수시 공시 정정", "6-K": "외국 기업 수시 공시", "10-Q": "분기 보고서", "10-K": "연차 보고서", "20-F": "외국 기업 연차 보고서",
        "424B1": "투자설명서", "424B2": "투자설명서", "424B3": "투자설명서(재판매·추가)", "424B4": "최종 투자설명서", "424B5": "투자설명서(선반 발행)",
        "424B7": "투자설명서(재판매)", "S-1": "증권 신고서", "S-1/A": "증권 신고서 정정", "F-1": "외국 기업 증권 신고서", "S-3": "선반 등록", "F-3": "외국 기업 선반 등록",
        "S-8": "임직원 주식 보상 등록", "EFFECT": "등록 효력 발생", "4": "내부자 거래", "3": "내부자 최초 보고", "144": "매도 예정 신고",
        "DEF 14A": "주총 위임장", "PRE 14A": "주총 위임장(예비)", "DEFA14A": "주총 추가 자료", "NT 10-K": "연차 보고 지연", "NT 10-Q": "분기 보고 지연",
        "SC 13D": "대량보유(경영 참여)", "SC 13D/A": "대량보유 변경(경영 참여)", "SC 13G": "대량보유(단순 투자)", "SC 13G/A": "대량보유 변경(단순 투자)",
        "SCHEDULE 13D": "대량보유(경영 참여)", "SCHEDULE 13D/A": "대량보유 변경(경영 참여)", "SCHEDULE 13G": "대량보유(단순 투자)",
        "SCHEDULE 13G/A": "대량보유 변경(단순 투자)", "425": "합병 관련 자료", "CORRESP": "SEC 답변서", "UPLOAD": "SEC 질의서", "ARS": "연차 주주 보고서"}
TITLE = [(r"chief executive officer|\bceo\b", "최고경영자(CEO)"), (r"chief financial officer|\bcfo\b", "최고재무책임자(CFO)"),
         (r"chief operating officer|\bcoo\b", "최고운영책임자(COO)"), (r"chief technology officer|\bcto\b", "최고기술책임자(CTO)"),
         (r"chief medical officer|\bcmo\b", "최고의학책임자"), (r"chief scientific officer|\bcso\b", "최고과학책임자"),
         (r"chief accounting officer|\bcao\b", "최고회계책임자"), (r"chief commercial officer", "최고영업책임자"), (r"chief legal officer|general counsel", "법무 책임자"),
         (r"executive chairman|chairman of the board|\bchairman\b|\bchair\b", "이사회 의장"), (r"\bpresident\b", "사장"),
         (r"executive vice president|\bevp\b", "전무"), (r"senior vice president|\bsvp\b", "상무"), (r"vice president|\bvp\b", "부사장"),
         (r"\btreasurer\b", "재무 담당"), (r"\bsecretary\b", "총무"), (r"\bdirector\b", "이사"), (r"10% owner|10 percent owner", "10% 주주"),
         (r"\bfounder\b", "창업자"), (r"\bofficer\b", "임원")]
FILER = [("large accelerated filer", "대형 가속 제출 기업"), ("non-accelerated filer", "비가속 제출 기업(소형)"), ("accelerated filer", "가속 제출 기업"),
         ("smaller reporting company", "소규모 보고 기업"), ("emerging growth company", "신생 성장 기업")]


def tag(t: str | None) -> str:
    return TAG.get(str(t or "").strip(), str(t or ""))


def tags(v) -> str:
    """태그 목록(JSON 문자열·리스트·'A, B' 글) → '전환사채 · 워런트'."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = [x.strip() for x in v.split(",") if x.strip()]
    return " · ".join(tag(x) for x in (v or []))


def form(f: str | None) -> str:
    """서류 코드 → '8-K(수시 공시)'. 모르는 코드는 그대로."""
    s = str(f or "").strip()
    k = FORM.get(s) or FORM.get(s.upper())
    return f"{s}({k})" if k and not s.upper().startswith(("SC ", "SCHEDULE")) else (k or s)


def items(v) -> str:
    """8-K 항목 '1.01,2.03' → '중요 계약 · 채무 발생'(screener.ITEM_KO)."""
    try:
        from screener import ITEM_KO
    except Exception:  # noqa: BLE001
        ITEM_KO = {}
    out = []
    for x in re.split(r"[,\s]+", str(v or "")):
        if x and x not in ("9.01",):   # 9.01(재무제표·첨부)은 거의 모든 8-K 에 붙어 뺌
            out.append(ITEM_KO.get(x, x))
    return " · ".join(out)


def title(t: str | None) -> str:
    """내부자 직함(영어) → 한글. 여러 개면 ' · ' 로."""
    s = str(t or "").strip()
    if not s:
        return ""
    found, low = [], s.lower()
    for pat, ko in TITLE:
        if re.search(pat, low) and ko not in found:
            found.append(ko)
            low = re.sub(pat, " ", low)
    return " · ".join(found) if found else s


def filer(c: str | None) -> str:
    low = re.sub(r"<[^>]+>", " ", str(c or "")).lower()
    out = []
    for en, ko in FILER:
        if en in low:
            out.append(ko)
            low = low.replace(en, " ")
    return " · ".join(out) if out else str(c or "")


def order_note(v) -> str:
    """주문 메모 JSON {'tp': 0.28, 'sl': 0.095, 'hold': None} → '목표 +28.0% · 손절 −9.5%'."""
    if v is None or v == "":
        return "-"
    d = v
    if isinstance(v, str):
        try:
            d = json.loads(v)
        except ValueError:
            return v
    if not isinstance(d, dict):
        return str(v)
    parts = []
    if d.get("tp") is not None:
        parts.append(f"목표 +{float(d['tp']) * 100:.1f}%")
    if d.get("sl") is not None:
        parts.append(f"손절 −{float(d['sl']) * 100:.1f}%")
    if d.get("hold"):
        parts.append(f"보유 {d['hold']}일")
    rest = {k: v for k, v in d.items() if k not in ("tp", "sl", "hold") and v not in (None, "")}
    parts += [f"{k} {v}" for k, v in rest.items()]
    return " · ".join(parts) or "-"
