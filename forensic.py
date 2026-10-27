"""공시분석(덕구 SEC 포렌식 희석 스캔) 결과 보관 — claude.ai '공시 분석 프로젝트'에서 만든 보고서를 종목별로 저장해 대시보드에서 바로 본다.

claude.ai 프로젝트의 대화는 외부 프로그램이 직접 읽을 수 없어서, 보고서를 붙여넣거나(.md/.txt 파일로) 올려 저장한다.
"""
from __future__ import annotations

import re
import shutil
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd

import db

DDL = """CREATE TABLE IF NOT EXISTS forensic_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, created_at TEXT, as_of TEXT,
         source TEXT, chat_url TEXT, content TEXT)"""
META_URL = "forensic_project_url"


def _conn():
    c = db.connect()
    c.execute(DDL)
    c.commit()
    return c


def add(ticker: str, content: str, source: str = "붙여넣기", chat_url: str = "", as_of: str | None = None) -> int:
    content = (content or "").strip()
    if not content:
        raise ValueError("내용이 비어 있습니다")
    with closing(_conn()) as c:
        cur = c.execute("INSERT INTO forensic_reports (ticker, created_at, as_of, source, chat_url, content) VALUES (?,?,?,?,?,?)",
                        (ticker.strip().upper(), db.utcnow_iso(), as_of or guess_as_of(content), source, (chat_url or "").strip(), content))
        c.commit()
        return int(cur.lastrowid)


def reports(ticker: str) -> pd.DataFrame:
    with closing(_conn()):
        pass
    return db.read_df("SELECT id, ticker, created_at, as_of, source, chat_url, content FROM forensic_reports WHERE ticker=? ORDER BY created_at DESC, id DESC",
                      (ticker.upper(),))


def delete(report_id: int) -> None:
    with closing(_conn()) as c:
        c.execute("DELETE FROM forensic_reports WHERE id=?", (int(report_id),))
        c.commit()


def latest_dates() -> dict[str, str]:
    """{티커: 가장 최근 저장일(YYYY-MM-DD)} — 표의 '공시분석' 열용."""
    with closing(_conn()):
        pass
    df = db.read_df("SELECT ticker, MAX(created_at) AS d FROM forensic_reports GROUP BY ticker")
    return {r.ticker: str(r.d)[:10] for r in df.itertuples()}


def project_url() -> str:
    m = db.get_meta(META_URL)
    return (m or {}).get("value") or ""


def set_project_url(url: str) -> None:
    db.set_meta(META_URL, url.strip())


def guess_as_of(content: str) -> str | None:
    """보고서 안의 기준일(as-of / 기준일 YYYY-MM-DD)을 찾아 본다. 없으면 None."""
    m = re.search(r"(?:as[- ]of|기준일)[^0-9]{0,15}(\d{4}-\d{2}-\d{2})", content, re.I)
    return m.group(1) if m else None


def risk_badges(content: str) -> dict:
    """보고서의 위험 이모지 개수(🔴 높음 · 🟠 주의 · 🟢 양호) — 한눈 요약용(해석은 본문)."""
    return {"🔴": content.count("🔴"), "🟠": content.count("🟠"), "🟢": content.count("🟢")}


# ---------------------------------------------------------------- Cowork 자동 스캔 연동 (폴더 주고받기)
# 대시보드가 queue.txt 에 티커를 쓰면, Claude Cowork 예약 작업이 덕구 스캔을 돌려 inbox/<티커>_<YYYYMMDD>.md 로 저장하고,
# 스캐너·대시보드가 inbox 를 확인해 자동으로 저장(forensic_reports)한 뒤 파일을 archive/ 로 옮긴다.
COWORK_TASK = """[덕구 자동 공시분석]
작업 폴더: {root}
1. queue.txt 를 읽는다. 한 줄에 티커 하나다. 비어 있으면 "대기열 없음"이라고만 쓰고 끝낸다.
2. 위에서부터 최대 {per_run}개 티커만 처리한다(사용량 절약).
3. 각 티커마다 sec-dilution-scan 스킬(덕구 SEC 포렌식 희석 스캔)의 지침대로 전체 스캔을 실행한다.
4. 보고서 전체를 마크다운 그대로(표·이모지 포함) inbox\\<티커>_<YYYYMMDD>.md 로 저장한다. 예: inbox\\JBDI_20261015.md
5. 처리한 티커는 queue.txt 에서 지운다. 실패하면 지우지 말고 inbox\\<티커>_<YYYYMMDD>_ERROR.txt 에 실패 이유를 한두 줄 적는다.
6. queue.txt 와 inbox 폴더 말고는 아무 파일도 만들거나 고치지 않는다."""


def root_dir() -> Path:
    import config
    return Path(config.DB_PATH).parent / "forensic"


def _dirs() -> tuple[Path, Path, Path]:
    r = root_dir()
    inbox, archive = r / "inbox", r / "archive"
    for d in (r, inbox, archive):
        d.mkdir(parents=True, exist_ok=True)
    return r, inbox, archive


def _queue_path() -> Path:
    return _dirs()[0] / "queue.txt"


def queue_list() -> list[str]:
    p = _queue_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        t = line.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", t) and t not in out:
            out.append(t)
    return out


def _queue_write(tickers: list[str]) -> None:
    _queue_path().write_text("".join(f"{t}\n" for t in tickers), encoding="utf-8")


def queue_add(tickers) -> int:
    """대기열에 추가(중복 제외). 추가된 개수."""
    cur = queue_list()
    new = [t.strip().upper() for t in ([tickers] if isinstance(tickers, str) else tickers) if t and t.strip().upper() not in cur]
    _queue_write(cur + list(dict.fromkeys(new)))
    return len(dict.fromkeys(new))


def queue_remove(ticker: str) -> None:
    t = ticker.strip().upper()
    _queue_write([x for x in queue_list() if x != t])
    _set_error(t, None)


def errors() -> dict:
    """{티커: {"at", "why"}} — Cowork 스캔 실패. 그 종목이 성공하거나 대기열에서 빠질 때까지 남는다."""
    import json
    return json.loads((db.get_meta("forensic_errors") or {}).get("value") or "{}")


def _set_error(ticker: str, why: str | None) -> None:
    import json
    e = errors()
    if why is None:
        if ticker not in e:
            return
        e.pop(ticker, None)
    else:
        e[ticker] = {"at": db.utcnow_iso(), "why": why}
    db.set_meta("forensic_errors", json.dumps(e, ensure_ascii=False))


def cowork_task_text(per_run: int = 3) -> str:
    return COWORK_TASK.format(root=str(root_dir()), per_run=per_run)


def import_inbox() -> dict:
    """inbox 의 보고서를 가져와 저장하고 archive 로 옮긴다. 반환: {"imported": [티커...], "errors": [(티커, 사유)...], "skipped": [파일...]}"""
    from config import DB_PATH  # noqa: F401  (폴더 위치 결정용)
    _, inbox, archive = _dirs()
    res = {"imported": [], "errors": [], "skipped": []}
    for f in sorted(inbox.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".md", ".txt"):
            continue
        m = re.match(r"([A-Za-z][A-Za-z0-9.\-]{0,9})_(\d{8})(_ERROR)?", f.stem)
        if not m:
            res["skipped"].append(f.name)
            continue
        t, ymd, err = m.group(1).upper(), m.group(2), bool(m.group(3))
        raw = f.read_bytes()
        text = None
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        text = text if text is not None else raw.decode("utf-8", errors="replace")
        if err:
            res["errors"].append((t, text.strip()[:300]))
            _set_error(t, text.strip()[:300])
        elif text.strip():
            add(t, text, source="Cowork 자동", as_of=guess_as_of(text) or f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}")
            res["imported"].append(t)
            queue_remove(t)  # 성공하면 실패 기록도 지워짐
        else:
            res["skipped"].append(f.name)
            continue
        dest = archive / f.name
        if dest.exists():
            dest = archive / f"{f.stem}_{datetime.now():%H%M%S}{f.suffix}"
        shutil.move(str(f), str(dest))
    if res["imported"] or res["errors"]:
        import json
        db.set_meta("forensic_last_import", json.dumps({"at": db.utcnow_iso(), **{k: res[k] for k in ("imported", "errors")}}, ensure_ascii=False))
    return res
