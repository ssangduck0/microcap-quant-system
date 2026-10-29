"""화면 없이 도는 프로그램(아침 갱신·스캐너·수집기)의 로그를 DB 폴더의 `<이름>.log` 파일에도 남긴다 (2026-10-30).

왜: 서버는 systemd 라 로그가 journalctl 에만 있어서 ⚙️ 관리 모드 '로그 보기' 가 "파일이 없습니다" 만 보여 줬다(PC 의 start_scanner.bat 시절 기능).
    밤 점검에서 공매도 잔고 받기가 10/27 부터 매일 실패했는데 아무도 못 봤다 → 실패 줄이 화면에 보여야 한다.
어떻게: RotatingFileHandler(3MB × 2개) 를 루트 로거에 붙인다. 아침 갱신은 진행 줄(out)도 INFO 로 같이 남기고, 스캐너·수집기는 WARNING 이상만(INFO 는 분 단위로 많음).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def path(name: str) -> Path:
    import config
    return Path(config.DB_PATH).with_name(f"{name}.log")


def attach(name: str, level: int = logging.WARNING, max_bytes: int = 3_000_000, backups: int = 2) -> Path | None:
    """루트 로거에 파일 핸들러를 붙인다(같은 파일에 두 번 붙지 않음). 실패해도 프로그램은 계속."""
    try:
        p = path(name)
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, RotatingFileHandler) and Path(getattr(h, "baseFilename", "")) == p:
                return p
        h = RotatingFileHandler(p, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        h.setLevel(level)
        h.setFormatter(logging.Formatter(FMT))
        root.addHandler(h)
        return p
    except Exception:  # noqa: BLE001
        return None


def out_logger(name: str = "job") -> logging.Logger:
    """아침 갱신의 진행 줄(out)용 로거: 루트가 WARNING 이어도 INFO 가 핸들러까지 간다(로거 자체 레벨 INFO · 전파)."""
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    return lg


def warnings(name: str, days: int = 7, limit: int = 60) -> list[str]:
    """파일에서 최근 n일의 WARNING/ERROR 줄만(관리 모드 '⚠️ 경고' 상자). 파일이 없으면 빈 목록."""
    p = path(name)
    if not p.exists():
        return []
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if len(line) >= 10 and line[:10] >= since and (" WARNING " in line or " ERROR " in line or " CRITICAL " in line):
            out.append(line)
    return out[-limit:]


def tail(name: str, n: int = 30) -> list[str] | None:
    p = path(name)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
