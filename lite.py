"""📱 간략 모드 — 휴대폰에서 꼭 필요한 화면만(홈 · 오늘 · 발굴 · 선별 · 추적).

같은 서버·같은 데이터를 쓰고, 보이는 화면 수만 줄인다(메뉴·요소가 적어 휴대폰에서 가볍다).
- 휴대폰으로 열면 기본이 간략 모드, PC 는 전체 모드. 홈의 버튼이나 주소 끝 ?v=lite / ?v=full 로 바꿀 수 있다.
- 간략 모드에 넣을 화면은 ⚙️ 관리 모드에서 고른다(DB meta 'lite_pages').
"""
import json

import db

ALIAS = {  # 옛 화면 키 → (새 화면 키, 탭 키). 메뉴 정리(2026-10-26) 전 주소·북마크·저장된 간략 화면 목록이 계속 동작하게
    "brief": ("home", None), "report": ("lookup", "report"), "snap": ("lookup", "snap"), "chart": ("lookup", "chart"),
    "setup": ("accum", "setup"), "close": ("accum", "close"), "pressure": ("pick", "pressure"),
    "scorecheck": ("score", "scorecheck"), "papertrade": ("score", "papertrade"), "autopsy": ("score", "autopsy"), "tracking": ("score", "score"), "signals": ("score", "score")}
# 홈은 항상 들어감. 종목(🏢)은 휴대폰에서 보기 어려워 기본에서 뺌(관리 모드에서 넣을 수 있음)
DEFAULT_PAGES = ["rank", "alerts", "news",             # 오늘
                 "accum", "themes",                     # 발굴
                 "pick",                                # 선별
                 "score"]                               # 추적(확인용이라 필수)
NOT_ALLOWED = {"home"}  # 홈은 고르지 않아도 항상 있음
CAT_ICON = {"홈": "🏠", "오늘": "📰", "발굴": "🧲", "선별": "🎯", "종목": "🏢", "추적": "🏆", "관리": "⚙️"}


def canon(keys: list[str]) -> list[str]:
    """옛 키를 새 키로(중복 제거·순서 유지)."""
    out = []
    for k in keys:
        k = ALIAS.get(k, (k, None))[0]
        if k not in out and k not in NOT_ALLOWED:
            out.append(k)
    return out


def pages() -> list[str]:
    try:
        m = db.get_meta("lite_pages")
        v = json.loads(m["value"]) if m and m.get("value") else None
        if isinstance(v, list) and v:
            return canon([str(x) for x in v])
    except Exception:  # noqa: BLE001
        pass
    return list(DEFAULT_PAGES)


def save_pages(keys: list[str]) -> None:
    db.set_meta("lite_pages", json.dumps([k for k in keys if k not in NOT_ALLOWED], ensure_ascii=False))


def reset_pages() -> None:
    db.set_meta("lite_pages", "")


def is_mobile(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(k in ua for k in ("iphone", "android", "mobile", "ipod")) and "ipad" not in ua


def decide(state: dict, query_v: str | None, user_agent: str) -> bool:
    """이번 화면이 간략 모드인지. 주소(?v=) > 이 창에서 고른 값 > 기기(휴대폰이면 간략)."""
    q = (query_v or "").strip().lower()
    if q in ("lite", "full"):
        state["_lite"] = q == "lite"
    if "_lite" not in state:
        state["_lite"] = is_mobile(user_agent)
    return bool(state["_lite"])


def categories(pages_: list[tuple], keys: list[str]) -> list[tuple[str, str, str]]:
    """아래 메뉴용 (묶음, 아이콘, 그 묶음의 첫 화면 키). PAGES 순서를 따름."""
    out, seen = [("홈", CAT_ICON["홈"], "home")], {"홈"}
    pos = {p[0]: i for i, p in enumerate(pages_)}
    ordered = sorted((p for p in pages_ if p[0] in keys),  # 묶음 안 첫 화면: 기본 목록 순서 우선(오늘 → 브리핑)
                     key=lambda p: DEFAULT_PAGES.index(p[0]) if p[0] in DEFAULT_PAGES else 100 + pos[p[0]])
    cat_order = {}
    for p in pages_:
        cat_order.setdefault(p[4], len(cat_order))
    for k, _t, _i, _d, cat in sorted(ordered, key=lambda p: cat_order[p[4]]):
        if k in keys and cat not in seen:
            seen.add(cat)
            out.append((cat, CAT_ICON.get(cat, _i), k))
    return out
