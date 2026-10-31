"""🛠 운영 현황(2026-10-31 · 김곰 워치리스트 홈의 '자동 스캔 일정 · 스캔 히스토리 · 일간 브리핑'을 우리 식으로):
① 🩺 아침 작업 점검표 — 아침 작업이 끝날 때 핵심 숫자를 남기고, 평소(직전 6번 중앙값)보다 크게 떨어지거나 기준을 넘으면 빨갛게
② ⏱ 자동 작업 일정 — 무엇을 · 언제 · 다음 실행까지 남은 시간 · 지난 실행 결과
③ 📜 작업 기록 — 끝난 작업 한 줄씩(아침 작업 · 공매 수집 · 배포)
왜: 10/31 하루에 '조용한 고장' 5개(핵심 문장 1,690건 전부 빈칸 · AI 요약 99% '내용 없음' · 스퀴즈 순위 10/26 뒤 멈춤 ·
텔레그램 11건 유실 · 병합 경계 21곳)를 찾았는데, 모두 화면엔 안 보이고 서버를 뒤져서야 알았음 → 매일 숫자로 보이게."""
from __future__ import annotations

import json
import os
import statistics
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import db

KST = ZoneInfo("Asia/Seoul")
DDL = """CREATE TABLE IF NOT EXISTS job_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, started TEXT, finished TEXT, ok INTEGER,
         secs REAL, warn INTEGER, summary TEXT, metrics TEXT)"""
KEEP = 2000
TAG = {"cases": "아침", "chartex": "공매", "deploy": "배포", "backup": "백업"}


def ensure(conn) -> None:
    conn.execute(DDL)


def record(job: str, started: datetime, finished: datetime | None = None, ok: bool = True, warn: int = 0, summary: str = "",
           metrics: dict | None = None) -> None:
    """끝난 작업 한 줄(📜 작업 기록 · 🩺 점검표 재료). 실패해도 본 작업을 막지 않음."""
    finished = finished or datetime.now(timezone.utc)
    try:
        with closing(db.connect()) as conn:
            ensure(conn)
            conn.execute("INSERT INTO job_runs (job, started, finished, ok, secs, warn, summary, metrics) VALUES (?,?,?,?,?,?,?,?)",
                         (job, started.isoformat(timespec="seconds"), finished.isoformat(timespec="seconds"), int(bool(ok)),
                          round((finished - started).total_seconds(), 1), int(warn or 0), (summary or "")[:500], json.dumps(metrics or {}, ensure_ascii=False)))
            conn.execute(f"DELETE FROM job_runs WHERE id NOT IN (SELECT id FROM job_runs ORDER BY id DESC LIMIT {KEEP})")
            conn.commit()
    except Exception:  # noqa: BLE001
        pass


def mark(job: str, ok: bool = True, summary: str = "") -> None:
    """자주 도는 작업(10분 캐시 데우기)은 표에 쌓지 않고 마지막 한 번만."""
    try:
        db.set_meta(f"job_last:{job}", json.dumps({"at": db.utcnow_iso(), "ok": bool(ok), "summary": summary}, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


def runs(job: str | None = None, limit: int = 10, offset: int = 0) -> list[dict]:
    try:
        with closing(db.connect()) as conn:
            ensure(conn)
            q = "SELECT * FROM job_runs" + (" WHERE job=?" if job else "") + " ORDER BY id DESC LIMIT ? OFFSET ?"
            rows = [dict(r) for r in conn.execute(q, ((job,) if job else ()) + (limit, offset))]
            n = conn.execute("SELECT COUNT(*) FROM job_runs" + (" WHERE job=?" if job else ""), (job,) if job else ()).fetchone()[0]
    except Exception:  # noqa: BLE001
        return []
    for r in rows:
        try:
            r["metrics"] = json.loads(r.get("metrics") or "{}")
        except ValueError:
            r["metrics"] = {}
        r["total"] = n
    return rows


# ---------------------------------------------------------------- ① 점검표
# (이름, 방향) — up: 클수록 정상(평소의 절반 아래·0이면 빨강) · down: 작을수록 정상(기준을 넘으면) · info: 참고만
METRICS = [("새 공시", "up"), ("핵심 문장 %", "up"), ("AI 요약", "up"), ("AI 요약 '내용 없음' %", "down"), ("뉴스", "up"), ("종목 뉴스 번역 %", "up"),
           ("텔레그램 보냄", "up"), ("텔레그램 실패", "down"), ("신호", "up"), ("일봉 종목(최신일)", "up"), ("스냅샷 종목(최신일)", "up"),
           ("스퀴즈 순위 경과일", "down"), ("부검 펌핑(최신일)", "info"), ("사건 표", "up"), ("시뮬레이션", "up"), ("PICK", "info"), ("AI PICK", "up"),
           ("공시분석", "up"), ("AI 비용(어제·원)", "info"), ("병합 일정(앞으로)", "info"), ("걸린 시간(분)", "info"), ("경고", "down")]
DIRECTION = dict(METRICS)
# 기록이 쌓이기 전에도 바로 알 수 있는 절대 기준 (노랑, 빨강) — down 은 이 값 이상, up(%)은 이 값 미만
ABS_DOWN = {"AI 요약 '내용 없음' %": (30, 60), "스퀴즈 순위 경과일": (2, 4), "텔레그램 실패": (3, 10), "경고": (1, 5)}
ABS_UP = {"핵심 문장 %": (40, 20), "종목 뉴스 번역 %": (50, 25)}   # 종목 없는 뉴스는 원래 번역 안 함(10/31 서버: 종목 뉴스 66%)


def health(conn, now: datetime | None = None) -> dict:
    """아침 작업 끝에 재는 숫자(지난 24시간 · 한국 날짜 기준 오늘). 표가 없으면 None."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    today = now.astimezone(KST).date()
    td = today.isoformat()

    def one(sql: str, args: tuple = ()):
        try:
            r = conn.execute(sql, args).fetchone()
            return r[0] if r else None
        except Exception:  # noqa: BLE001
            return None

    def pct(a, b, min_n: int = 10):
        return None if a is None or not b or b < min_n else round(a / b * 100)

    m: dict = {}
    m["새 공시"] = one("SELECT COUNT(*) FROM sec_feed WHERE created_at >= ?", (since,))
    k8 = "created_at >= ? AND enriched=1 AND (form LIKE '8-K%' OR form LIKE '6-K%')"
    m["핵심 문장 %"] = pct(one(f"SELECT COUNT(*) FROM sec_feed WHERE {k8} AND COALESCE(lead,'') != ''", (since,)), one(f"SELECT COUNT(*) FROM sec_feed WHERE {k8}", (since,)))
    dg = one("SELECT COUNT(*) FROM sec_digest WHERE done_at >= ?", (since,))
    m["AI 요약"] = dg
    m["AI 요약 '내용 없음' %"] = pct(one("SELECT COUNT(*) FROM sec_digest WHERE done_at >= ? AND (summary_ko LIKE '%확인되지 않%' OR summary_ko LIKE '%발췌%' "
                                       "OR summary_ko LIKE '%내용이 없%')", (since,)), dg)
    nw = one("SELECT COUNT(*) FROM news WHERE fetched >= ?", (since,))
    m["뉴스"] = nw
    tk = "fetched >= ? AND COALESCE(ticker,'') != ''"
    m["종목 뉴스 번역 %"] = pct(one(f"SELECT COUNT(*) FROM news WHERE {tk} AND COALESCE(title_ko,'') != ''", (since,)), one(f"SELECT COUNT(*) FROM news WHERE {tk}", (since,)))
    m["텔레그램 보냄"] = one("SELECT COUNT(*) FROM alert_log WHERE at >= ? AND ok=1", (since,))
    m["텔레그램 실패"] = one("SELECT COUNT(*) FROM alert_log WHERE at >= ? AND ok=0", (since,))
    m["신호"] = one("SELECT COUNT(*) FROM signals WHERE ts >= ?", (since,))
    m["일봉 종목(최신일)"] = one("SELECT COUNT(*) FROM daily_prices WHERE date=(SELECT MAX(date) FROM daily_prices)")
    m["스냅샷 종목(최신일)"] = one("SELECT COUNT(*) FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots)")
    lr = one("SELECT MAX(date) FROM squeeze_rank")
    try:
        m["스퀴즈 순위 경과일"] = (today - date.fromisoformat(str(lr)[:10])).days if lr else None
    except ValueError:
        m["스퀴즈 순위 경과일"] = None
    m["부검 펌핑(최신일)"] = one("SELECT COUNT(*) FROM pump_autopsy WHERE date=(SELECT MAX(date) FROM pump_autopsy)")
    m["사건 표"] = one("SELECT COUNT(*) FROM presim_ep")
    m["시뮬레이션"] = one("SELECT COUNT(*) FROM presim_log WHERE day=?", (td,))
    m["PICK"] = one("SELECT COUNT(*) FROM pick_signals WHERE date=?", (td,))
    m["AI PICK"] = one("SELECT COUNT(*) FROM ai_pick WHERE date=?", (td,))
    m["공시분석"] = one("SELECT COUNT(*) FROM forensic_reports WHERE created_at >= ?", (since,))
    usd = one("SELECT SUM(usd) FROM ai_spend WHERE date=?", ((today - timedelta(days=1)).isoformat(),))
    try:
        import aipick
        fx = aipick.FX
    except Exception:  # noqa: BLE001
        fx = 1400.0
    m["AI 비용(어제·원)"] = round((usd or 0) * fx)
    m["병합 일정(앞으로)"] = one("SELECT COUNT(*) FROM events WHERE kind='역분할 시행' AND date >= ?", (td,))
    return m


def flag(name: str, value, history: list) -> str:
    """'red' · 'yellow' · ''. history = 직전 실행들의 같은 값(최근 것 먼저)."""
    if value is None:
        return ""
    d = DIRECTION.get(name, "info")
    if d == "down" and name in ABS_DOWN:
        y, r = ABS_DOWN[name]
        return "red" if value >= r else ("yellow" if value >= y else "")
    if d != "up":
        return ""
    if name in ABS_UP:
        y, r = ABS_UP[name]
        if value < r:
            return "red"
        if value < y:
            return "yellow"
    prev = [h for h in history[:6] if isinstance(h, (int, float))]
    if len(prev) < 3:
        return ""
    med = statistics.median(prev)
    if med <= 0:
        return ""
    if value == 0 or value < 0.5 * med:
        return "red"
    return "yellow" if value < 0.75 * med else ""


def table(n: int = 7) -> dict:
    """점검표 재료: {"days": [아침 작업 실행 최근 n개(최근 것 먼저)], "rows": [{"name", "vals": [(값, 색)], "dir"}], "alerts": [(이름, 값, 평소)]}"""
    rs = runs("cases", limit=n + 6)
    days = rs[:n]
    out_rows, alerts = [], []
    for name, d in METRICS:
        series = [r["metrics"].get(name) for r in rs]
        vals = []
        for i in range(len(days)):
            v = series[i]
            c = flag(name, v, series[i + 1:])
            vals.append((v, c))
            if i == 0 and c == "red":
                prev = [h for h in series[1:7] if isinstance(h, (int, float))]
                alerts.append((name, v, statistics.median(prev) if prev else None))
        out_rows.append({"name": name, "dir": d, "vals": vals})
    return {"days": days, "rows": out_rows, "alerts": alerts}


# ---------------------------------------------------------------- ② 일정
SCHEDULE = [
    {"key": "scanner", "name": "🔍 스캐너", "what": "토스 순위·시세·신호 → 공시 피드·AI 요약 → 알림(실패 알림 다시 보내기)", "when": "계속 · 한 바퀴 약 12~15분", "kind": "loop"},
    {"key": "collector", "name": "🧲 이벤트 수집기", "what": "8-K 보도자료 모으기 · 주가 반응 라벨(🔬 이벤트 연구)", "when": "계속", "kind": "loop"},
    {"key": "chartex", "name": "📡 공매·FTD 수집", "what": "ChartExchange 공매도 잔고·FTD·숏볼륨", "when": "화~토 06:40", "kind": "cron", "days": (1, 2, 3, 4, 5), "hm": (6, 40)},
    {"key": "cases", "name": "🌅 아침 작업", "what": "공시 동기화 → 병합 일정·계단 수리 → 사건 표·시뮬레이션 → PICK·AI PICK·공시분석 → 부검 → 성과 공표 → 스퀴즈 순위"
                                                   " (토요일엔 복기·모델 재학습도)", "when": "화~토 07:30 · 약 2시간", "kind": "cron", "days": (1, 2, 3, 4, 5), "hm": (7, 30)},
    {"key": "warm", "name": "🔥 화면 캐시 데우기", "what": "느린 화면(PICK·펀드스캔·다크풀 등) 미리 계산", "when": "10분마다", "kind": "every", "minutes": 10},
    {"key": "backup", "name": "💾 DB 백업", "what": "DB 압축 사본(14일) + Cloudflare R2 사본(21일)", "when": "매일 03:00", "kind": "cron", "days": tuple(range(7)), "hm": (3, 0)},
]


def next_run(spec: dict, now: datetime | None = None, last: datetime | None = None) -> datetime | None:
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    if spec["kind"] == "cron":
        for off in range(0, 9):
            d = now.date() + timedelta(days=off)
            cand = datetime(d.year, d.month, d.day, spec["hm"][0], spec["hm"][1], tzinfo=KST)
            if d.weekday() in spec["days"] and cand > now:
                return cand
        return None
    if spec["kind"] == "every":
        base = (last or now).astimezone(KST)
        nxt = base + timedelta(minutes=spec["minutes"])
        return nxt if nxt > now else now
    return None


def until(t: datetime | None, now: datetime | None = None) -> str:
    """'2일 뒤' · '20시간 53분 뒤' · '7분 뒤'."""
    if t is None:
        return "-"
    s = (t - (now or datetime.now(timezone.utc))).total_seconds()
    if s <= 60:
        return "곧"
    m = int(s // 60)
    if m < 60:
        return f"{m}분 뒤"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}시간 {m}분 뒤" if m else f"{h}시간 뒤"
    d, h = divmod(h, 24)
    return f"{d}일 {h}시간 뒤" if d < 3 and h else f"{d}일 뒤"


def ago(t: datetime | None, now: datetime | None = None) -> str:
    if t is None:
        return "-"
    s = ((now or datetime.now(timezone.utc)) - t).total_seconds()
    if s < 90:
        return "방금"
    m = int(s // 60)
    if m < 60:
        return f"{m}분 전"
    h = m // 60
    return f"{h}시간 전" if h < 48 else f"{h // 24}일 전"


def _ts(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def backup_dir() -> Path:
    return Path(os.environ.get("QUANT_BACKUP_DIR") or (Path(config.DB_PATH).resolve().parent.parent / "backup"))


def last_runs(now: datetime | None = None) -> dict:
    """작업별 지난 실행 {key: {"at": datetime|None, "ok": bool|None, "text": str}}."""
    out: dict = {}
    for k in ("cases", "chartex"):
        r = (runs(k, limit=1) or [None])[0]
        out[k] = {"at": _ts(r["finished"]), "ok": bool(r["ok"]), "text": r["summary"]} if r else {"at": None, "ok": None, "text": "기록 없음"}
    try:
        b = json.loads((db.get_meta("scanner_beat") or {}).get("value") or "{}")
        out["scanner"] = {"at": _ts(b.get("at")), "ok": True, "text": b.get("phase") or ""}
    except Exception:  # noqa: BLE001
        out["scanner"] = {"at": None, "ok": None, "text": "-"}
    try:
        with closing(db.connect()) as conn:
            f = conn.execute("SELECT MAX(fetched) FROM ev_docs").fetchone()[0]
        out["collector"] = {"at": _ts(f), "ok": True, "text": "마지막 보도자료 수집"}
    except Exception:  # noqa: BLE001
        out["collector"] = {"at": None, "ok": None, "text": "-"}
    try:
        w = json.loads((db.get_meta("job_last:warm") or {}).get("value") or "{}")
        out["warm"] = {"at": _ts(w.get("at")), "ok": w.get("ok"), "text": w.get("summary") or ""}
    except Exception:  # noqa: BLE001
        out["warm"] = {"at": None, "ok": None, "text": "-"}
    try:
        fs = sorted(backup_dir().glob("quant-*.db.gz"), key=lambda p: p.stat().st_mtime)
        if fs:
            p = fs[-1]
            out["backup"] = {"at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc), "ok": True, "text": f"{p.name} · {p.stat().st_size / 1e6:,.0f}MB"}
        else:
            out["backup"] = {"at": None, "ok": None, "text": "백업 파일 없음(이 PC)"}
    except Exception:  # noqa: BLE001
        out["backup"] = {"at": None, "ok": None, "text": "-"}
    return out


def schedule(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    lr = last_runs(now)
    rows = []
    for s in SCHEDULE:
        last = lr.get(s["key"]) or {}
        nx = next_run(s, now, last.get("at"))
        rows.append({**s, "next": nx, "next_txt": until(nx, now) if s["kind"] != "loop" else "계속 실행 중",
                     "last_at": last.get("at"), "last_txt": ago(last.get("at"), now), "last_ok": last.get("ok"), "last_note": last.get("text") or ""})
    return rows


# ---------------------------------------------------------------- 아침 작업 끝에(cases.main 이 부름)
def morning_done(started: datetime, ok: bool = True, out=print) -> dict:
    """아침 작업 한 줄 기록 + 점검 숫자. 경고 수는 이번 실행 동안 cases.log 에 남은 WARNING/ERROR 줄."""
    finished = datetime.now(timezone.utc)
    try:
        import filelog
        since = started.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        warn = sum(1 for ln in filelog.warnings("cases", days=1, limit=10_000) if ln[:19] >= since)
    except Exception:  # noqa: BLE001
        warn = 0
    try:
        with closing(db.connect()) as conn:
            m = health(conn, finished)
    except Exception:  # noqa: BLE001
        m = {}
    mins = round((finished - started).total_seconds() / 60)
    m["걸린 시간(분)"] = mins
    m["경고"] = warn
    record("cases", started, finished, ok, warn, f"아침 작업 {'완료' if ok else '실패'} · {mins // 60}시간 {mins % 60}분 · 경고 {warn}", m)
    try:
        t = table(7)
        if t["alerts"]:
            out("🩺 점검표 빨간 칸: " + " · ".join(f"{n} {v}(평소 {('-' if p is None else round(p))})" for n, v, p in t["alerts"]))
    except Exception:  # noqa: BLE001
        pass
    return m
