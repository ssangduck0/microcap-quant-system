"""텔레그램 알림(선택). 토큰은 환경변수 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 로만 읽습니다.
+ 🔔→📨 보낸 알림 기록(2026-10-28): 나가는 모든 알림을 `alert_log` 표에 남겨 화면(🔔 공시 알림 → 📨 보낸 알림 탭)에서 시간순으로 되짚어 볼 수 있게.
  종류는 첫 글자(이모지)로, 종목은 첫 줄의 대문자 티커로 자동 분류. 토큰이 없거나 전송에 실패해도 ok=0 으로 남긴다(무엇을 보내려 했는지 보이게)."""
import logging
import re
from contextlib import closing

import requests

import config

log = logging.getLogger("notify")

KIND_BY_EMOJI = {"📐": "📐 차트", "🌙": "🌙 애프터", "⏰": "⏰ 시간", "🔔": "🔔 공시", "🩳": "🩳 공매", "📈": "📈 판정", "🔀": "🔀 교차검증", "🚦": "🚦 장세",
                 "🐷": "🐷 저금통", "🧪": "🧪 가상매매", "🏆": "🏆 검증", "🤖": "🤖 AI", "🧾": "🧾 공시분석", "📰": "📰 요약", "⚠️": "⚠️ 주의", "⚠": "⚠️ 주의",
                 "✅": "✅ 테스트", "📡": "📡 숏 데이터", "🕶": "🕶 다크풀", "🔍": "🔍 부검", "🧠": "🧠 모델", "☁️": "☁️ 백업"}
DDL = "CREATE TABLE IF NOT EXISTS alert_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT, ticker TEXT, text TEXT, ok INTEGER)"
_TICKER = re.compile(r"(?<![A-Za-z$])\$?([A-Z]{1,5})(?![a-z])")
_PUMP = re.compile(r"^\[[A-Z][A-Z0-9.\-]{0,5}\]\s*펌핑점수")   # 스캐너 본 신호 형식 "[POM] 펌핑점수 85 | 낙폭 … | 가격 변동"
_NOT_TICKER = {"KST", "ET", "USD", "SEC", "ATM", "ELOC", "CB", "AI", "PICK", "VIX", "SPY", "HY", "FTD", "RSI", "VWAP", "SAR", "OK", "TOP", "BEST", "NT", "PR", "IPO", "ETF", "EPS", "CEO", "CFO", "FDA", "PDUFA", "NASDAQ", "NYSE", "OTC", "API", "DB", "REG", "SHO", "GC", "MA", "BB", "S", "K", "Q", "F", "M", "B", "A", "C", "D", "I", "II", "III"}


def classify(text: str) -> tuple[str, str | None]:
    """알림 글 → (종류, 종목). 종류는 맨 앞 이모지, 종목은 첫 줄에서 처음 나오는 1~5자리 대문자."""
    s = (text or "").strip()
    kind = "기타"
    for em, name in KIND_BY_EMOJI.items():
        if s.startswith(em):
            kind = name
            break
    first = s.split("\n", 1)[0]
    if kind == "기타" and _PUMP.match(first):   # 2026-10-30: 스캐너 본 신호가 하루 70~100건인데 전부 '기타' 로 세어짐 → 🎯 신호
        kind = "🎯 신호"
    ticker = None
    for m in _TICKER.finditer(first):
        tk = m.group(1)
        if tk not in _NOT_TICKER and len(tk) >= 2 or (len(tk) == 1 and m.group(0).startswith("$")):
            ticker = tk
            break
    return kind, ticker


def _ensure(conn) -> None:
    conn.execute(DDL)
    if "retried" not in {r[1] for r in conn.execute("PRAGMA table_info(alert_log)")}:   # 2026-10-31: 실패 알림 다시 보내기(한 번만)
        conn.execute("ALTER TABLE alert_log ADD COLUMN retried INTEGER")


def _log(text: str, ok: bool, retried: int | None = None) -> None:
    try:
        import db
        kind, ticker = classify(text)
        with closing(db.connect()) as conn:
            _ensure(conn)
            conn.execute("INSERT INTO alert_log (at, kind, ticker, text, ok, retried) VALUES (?,?,?,?,?,?)",
                         (db.utcnow_iso(), kind, ticker, (text or "")[:2000], int(bool(ok)), retried))
            conn.commit()
    except Exception:  # noqa: BLE001
        pass


def send_telegram(text: str, _retry: bool = False) -> bool:
    if not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID):
        _log(text, False, 1)   # 키 없음 = 다시 보낼 것도 없음
        return False
    ok = False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        r.raise_for_status()
        ok = True
    except Exception as e:  # noqa: BLE001
        log.warning("텔레그램 전송 실패: %s", type(e).__name__)  # 토큰이 URL에 있으므로 예외 전문은 남기지 않음
    _log(text, ok, 1 if _retry else None)
    return ok


RETRY_MIN = 30
RETRY_WAIT_MIN = 5


def retry_failed(max_age_min: int = RETRY_MIN, limit: int = 10, now=None) -> int:
    """최근 max_age_min 분 안에 전송 실패한 알림을 한 번만 다시 보냄(끝에 '⏱ 지연 전송' 표시). 다시 보낸 건수(성공).
    2026-10-31: 10/31 06:20~07:01 텔레그램 응답 지연으로 11건(🎯 신호 4 · 🐷 저금통 3 · 🌙 애프터 3 · 🔔 공시 1)이 실패하고 그대로 사라졌음.
    응답만 늦고 실제로는 도착한 경우엔 두 번 올 수 있음(잃는 것보다 나음). 다시 보낸 것이 또 실패하면 더 안 보냄."""
    if not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID):
        return 0
    from datetime import datetime, timedelta, timezone
    import db
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(minutes=max_age_min)).isoformat(timespec="seconds")
    until = (now - timedelta(minutes=RETRY_WAIT_MIN)).isoformat(timespec="seconds")   # 끊김이 지나가게 몇 분 기다렸다가
    try:
        with closing(db.connect()) as conn:
            _ensure(conn)
            rows = conn.execute("SELECT id, at, text FROM alert_log WHERE ok=0 AND retried IS NULL AND at >= ? AND at <= ? ORDER BY id LIMIT ?",
                                (since, until, limit)).fetchall()
            if not rows:
                return 0
            conn.executemany("UPDATE alert_log SET retried=1 WHERE id=?", [(r[0],) for r in rows])   # 먼저 표시(두 번 다시 보내지 않게)
            conn.commit()
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for _id, at, text in rows:
        try:
            hhmm = (datetime.fromisoformat(str(at).replace("Z", "+00:00")) + timedelta(hours=9)).strftime("%H:%M")
        except ValueError:
            hhmm = "?"
        n += int(send_telegram(f"{text}\n⏱ 지연 전송({hhmm} KST 첫 전송 실패)", _retry=True))
    if rows:
        log.info("텔레그램 실패 알림 다시 보냄: %d건 중 %d건 성공", len(rows), n)
    return n


def repeat_ok(conn, ticker: str, reason: str, cap: int | None = None, now=None) -> bool:
    """🎯 펌핑 신호 재알림을 보낼지(2026-10-31): '가격 변동' 재알림만 같은 종목 최근 24시간 cap 번까지(신규·첫 포착·희석 변경은 항상).
    10/28~30 펌핑 신호 알림 262건 중 '가격 변동' 210건(80%) · 같은 종목 하루 최대 15번(SGLY) → 중요한 알림이 묻힘."""
    from datetime import datetime, timedelta, timezone
    cap = int(getattr(config, "SIGNAL_ALERT_MAX_PER_DAY", 3)) if cap is None else int(cap)
    if cap <= 0 or not str(reason or "").startswith("가격 변동"):
        return True
    since = ((now or datetime.now(timezone.utc)) - timedelta(hours=24)).isoformat(timespec="seconds")
    try:
        n = conn.execute("SELECT COUNT(*) FROM alert_log WHERE ticker=? AND at >= ? AND text LIKE ?", (ticker, since, f"[{ticker}] 펌핑점수%")).fetchone()[0]
    except Exception:  # noqa: BLE001  (알림 기록 표가 아직 없음)
        return True
    return n < cap


def recent(conn, days: int = 7, kind: str | None = None, ticker: str | None = None, limit: int = 500):
    """최근 days 일 보낸 알림(최신순) → DataFrame[시각(KST), 종류, 종목, 내용, 보냄]."""
    import pandas as pd
    conn.execute(DDL)
    sql = "SELECT at, kind, ticker, text, ok FROM alert_log WHERE at >= datetime('now', ?)"
    args: list = [f"-{int(days)} day"]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if ticker:
        sql += " AND ticker=?"
        args.append(ticker.upper())
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    rows = [tuple(r) for r in conn.execute(sql, args).fetchall()]
    df = pd.DataFrame(rows, columns=["at", "종류", "종목", "내용", "ok"])
    if df.empty:
        return pd.DataFrame(columns=["시각(KST)", "종류", "종목", "내용", "보냄"])
    t = pd.to_datetime(df["at"], utc=True, errors="coerce").dt.tz_convert("Asia/Seoul")
    df["시각(KST)"] = t.dt.strftime("%m/%d %H:%M")
    df["날짜"] = t.dt.strftime("%Y-%m-%d")
    df["보냄"] = df["ok"].map({1: "✅", 0: "❌"})
    df["종목"] = df["종목"].fillna("")
    df["내용"] = df["내용"].astype(str).str.replace("\n", " · ", regex=False).str.slice(0, 160)
    return df[["시각(KST)", "종류", "종목", "내용", "보냄", "날짜"]]


def counts(conn, days: int = 7):
    """날짜 × 종류 건수(넓은 표, 막대 차트용)."""
    import pandas as pd
    df = recent(conn, days, limit=100000)
    if df.empty:
        return pd.DataFrame()
    return df.pivot_table(index="날짜", columns="종류", values="내용", aggfunc="count", fill_value=0).sort_index()
