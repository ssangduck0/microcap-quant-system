"""👥 방문객 모드 — 전용 링크(?guest=토큰)로 비밀번호 없이 열람만. 기간이 지나거나 취소하면 막힌다.

방문객에게 숨기는 것: 관리 모드·워치리스트·저금통·노트·일정 화면, 내 관심·보유 종목 표시, 비용·변경이 생기는 버튼(AI 만들기·덕구 스캔 요청·지금 분석 등).
스캐너·아침 작업처럼 화면 밖에서는 항상 '방문객 아님'이라 기존 동작 그대로다.
"""
from __future__ import annotations

import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pandas as pd

import db

HIDDEN_PAGES = {"admin", "watch", "piggy", "notes", "events"}
DURATIONS = {"1시간": 1, "3시간": 3, "하루": 24, "3일": 72, "7일": 168}
DDL = """CREATE TABLE IF NOT EXISTS guest_tokens (token TEXT PRIMARY KEY, name TEXT, created_at TEXT, expires_at TEXT, revoked INTEGER DEFAULT 0, last_seen TEXT,
          visits INTEGER DEFAULT 0)"""
DDL_VISITS = """CREATE TABLE IF NOT EXISTS guest_visits (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, name TEXT, at TEXT, ip TEXT, country TEXT, device TEXT, ua TEXT,
          fp TEXT, new_device INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0)"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_tables(conn) -> None:
    conn.execute(DDL)
    conn.execute(DDL_VISITS)
    have = {r[1] for r in conn.execute("PRAGMA table_info(guest_tokens)")}
    for col, typ in (("single_device", "INTEGER DEFAULT 1"), ("bound_fp", "TEXT")):
        if col not in have:
            conn.execute(f"ALTER TABLE guest_tokens ADD COLUMN {col} {typ}")
    if "agreed_at" not in {r[1] for r in conn.execute("PRAGMA table_info(guest_visits)")}:
        conn.execute("ALTER TABLE guest_visits ADD COLUMN agreed_at TEXT")
    conn.commit()


def create(name: str, hours: float, single_device: bool = True) -> str:
    tok = secrets.token_urlsafe(18)
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        conn.execute("INSERT INTO guest_tokens (token, name, created_at, expires_at, revoked, visits, single_device) VALUES (?,?,?,?,0,0,?)",
                     (tok, name.strip() or "방문객", _now().isoformat(), (_now() + timedelta(hours=hours)).isoformat(), 1 if single_device else 0))
        conn.commit()
    return tok


def check(token: str | None) -> dict | None:
    """유효한 링크면 {name, expires_at, left_min}, 아니면 None."""
    if not token:
        return None
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        r = conn.execute("SELECT * FROM guest_tokens WHERE token=?", (str(token),)).fetchone()
    if not r or r["revoked"]:
        return None
    exp = datetime.fromisoformat(r["expires_at"])
    left = (exp - _now()).total_seconds() / 60
    if left <= 0:
        return None
    return {"token": r["token"], "name": r["name"], "expires_at": r["expires_at"], "left_min": left}


def touch(token: str) -> None:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        conn.execute("UPDATE guest_tokens SET last_seen=?, visits=COALESCE(visits,0)+1 WHERE token=?", (_now().isoformat(), token))
        conn.commit()


def revoke(token: str) -> None:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        conn.execute("UPDATE guest_tokens SET revoked=1 WHERE token=?", (token,))
        conn.commit()


def all_links() -> pd.DataFrame:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
    df = db.read_df("SELECT * FROM guest_tokens ORDER BY created_at DESC")
    if df.empty:
        return df
    now = _now()
    df["상태"] = ["취소됨" if rv else ("만료" if datetime.fromisoformat(e) <= now else "사용 가능") for rv, e in zip(df["revoked"], df["expires_at"])]
    df["남은 시간"] = [("-" if s != "사용 가능" else left_text((datetime.fromisoformat(e) - now).total_seconds() / 60)) for s, e in zip(df["상태"], df["expires_at"])]
    return df


def left_text(minutes: float) -> str:
    m = int(max(0, minutes))
    return f"{m // 1440}일 {m % 1440 // 60}시간" if m >= 1440 else (f"{m // 60}시간 {m % 60}분" if m >= 60 else f"{m}분")


def link(base: str, token: str) -> str:
    return base.rstrip("/") + "/?guest=" + token


def is_guest() -> bool:
    try:
        import streamlit as st
        return bool(st.session_state.get("_guest"))
    except Exception:  # noqa: BLE001
        return False


def can_edit() -> bool:
    return not is_guest()


# ---------------------------------------------------------------- 접속 기록 · 한 기기 전용
def client_info(headers: dict | None) -> dict:
    """요청 헤더 → IP(클라우드플레어가 넘겨준 실제 주소)·국가·기기·브라우저·기기 지문(브라우저 정보 기준)."""
    import hashlib
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    ip = h.get("cf-connecting-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip() or "로컬(같은 PC·와이파이)"
    ua = h.get("user-agent", "")
    dev = ("아이폰" if "iPhone" in ua else "아이패드" if "iPad" in ua else "안드로이드" if "Android" in ua else "윈도우 PC" if "Windows" in ua
           else "맥" if "Macintosh" in ua else "리눅스" if "Linux" in ua else "알 수 없음")
    br = ("삼성 인터넷" if "SamsungBrowser" in ua else "카카오톡" if "KAKAOTALK" in ua else "네이버" if "NAVER" in ua else "엣지" if "Edg/" in ua
          else "크롬" if "Chrome" in ua else "사파리" if "Safari" in ua else "파이어폭스" if "Firefox" in ua else "기타")
    return {"ip": ip, "country": h.get("cf-ipcountry", "-"), "device": f"{dev} · {br}", "ua": ua[:300], "fp": hashlib.sha256(ua.encode()).hexdigest()[:16]}


def record_visit(token: str, info: dict) -> dict:
    """방문 기록. 반환 {"allowed": bool, "new_device": bool}. 한 기기 전용 링크는 처음 연 기기(브라우저 지문)만 허용."""
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        r = conn.execute("SELECT name, single_device, bound_fp FROM guest_tokens WHERE token=?", (token,)).fetchone()
        if not r:
            return {"allowed": False, "new_device": False}
        seen = {x[0] for x in conn.execute("SELECT DISTINCT fp FROM guest_visits WHERE token=? AND blocked=0", (token,))}
        new_dev = bool(seen) and info["fp"] not in seen
        allowed = True
        if r["single_device"]:
            if not r["bound_fp"]:
                conn.execute("UPDATE guest_tokens SET bound_fp=? WHERE token=?", (info["fp"], token))
            elif r["bound_fp"] != info["fp"]:
                allowed = False
        conn.execute("INSERT INTO guest_visits (token, name, at, ip, country, device, ua, fp, new_device, blocked) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (token, r["name"], _now().isoformat(), info["ip"], info["country"], info["device"], info["ua"], info["fp"], 1 if new_dev else 0, 0 if allowed else 1))
        conn.commit()
    return {"allowed": allowed, "new_device": new_dev, "name": r["name"]}


def visits(limit: int = 300) -> pd.DataFrame:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
    return db.read_df("SELECT * FROM guest_visits ORDER BY id DESC LIMIT ?", (limit,))


# ---------------------------------------------------------------- 비밀번호 잠금(무차별 대입 방지)
LOCK_FAILS, LOCK_WINDOW_MIN, LOCK_MIN = 10, 10, 15


def pw_locked() -> float:
    """잠겨 있으면 남은 분, 아니면 0."""
    m = db.get_meta("pw_lock_until")
    if m and m.get("value"):
        left = (datetime.fromisoformat(m["value"]) - _now()).total_seconds() / 60
        if left > 0:
            return left
    return 0.0


def pw_fail() -> bool:
    """실패 1회 기록. 10분 안 10회면 15분 잠그고 True(이번에 잠김)."""
    import json
    m = db.get_meta("pw_fails")
    fails = json.loads(m["value"]) if m and m.get("value") else []
    cut = (_now() - timedelta(minutes=LOCK_WINDOW_MIN)).isoformat()
    fails = [x for x in fails if x >= cut] + [_now().isoformat()]
    db.set_meta("pw_fails", json.dumps(fails[-50:]))
    if len(fails) >= LOCK_FAILS:
        db.set_meta("pw_lock_until", (_now() + timedelta(minutes=LOCK_MIN)).isoformat())
        db.set_meta("pw_fails", "[]")
        return True
    return False


def guest_only() -> bool:
    """방문객 전용 서버(비밀번호 입력창 없음, 방문객 링크로만)."""
    import os
    return os.environ.get("QUANT_GUEST_ONLY") == "1"


# ---------------------------------------------------------------- 경고문 · 동의 · 워터마크
DEFAULT_NOTICE = """이 화면은 초대받은 분만 볼 수 있는 열람 전용 자료입니다.
링크와 화면을 다른 사람에게 공유하거나, 캡처·녹화해 배포하지 마세요.
접속 시각·기기·IP 가 기록되며, 무단 공유가 확인되면 즉시 접속이 차단됩니다.
무단 배포로 피해가 생기면 관련 법령에 따른 책임이 따를 수 있습니다.
모든 내용은 공부용 참고 자료이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다."""


def notice() -> str:
    m = db.get_meta("guest_notice")
    return (m["value"] if m and m.get("value") else DEFAULT_NOTICE).strip()


def set_notice(text: str) -> None:
    db.set_meta("guest_notice", text.strip())


def agree(token: str) -> None:
    """이 링크의 가장 최근 접속 기록에 동의 시각을 남긴다."""
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        r = conn.execute("SELECT id FROM guest_visits WHERE token=? AND blocked=0 ORDER BY id DESC LIMIT 1", (token,)).fetchone()
        if r:
            conn.execute("UPDATE guest_visits SET agreed_at=? WHERE id=?", (_now().isoformat(), r["id"]))
            conn.commit()


def watermark_css(text: str) -> str:
    """화면 전체에 옅게 반복되는 기울어진 글자(이름·시각·IP) — 클릭은 그대로 통과."""
    from html import escape
    from urllib.parse import quote
    t = escape(text)
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='600' height='340'><text x='30' y='190' transform='rotate(-20 300 170)' "
           f"font-family='sans-serif' font-size='13' fill='rgb(150,150,150)' fill-opacity='0.10'>{t}</text></svg>")
    return ("<style>.qk-wm{position:fixed;inset:0;z-index:999999;pointer-events:none;background-image:url(\"data:image/svg+xml;utf8,"
            + quote(svg) + "\");background-repeat:repeat;}</style><div class='qk-wm'></div>")



def short_ip(ip: str) -> str:
    """워터마크용 짧은 IP — IPv6 는 앞 두 묶음만(예: 2001:4430:…), IPv4 는 그대로."""
    if not ip:
        return ""
    if ":" in ip:
        return ":".join(ip.split(":")[:2]) + ":…"
    return ip
