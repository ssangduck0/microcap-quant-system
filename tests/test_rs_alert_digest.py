import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""스캐너 업그레이드 4·5번(2026-11-01): 알림 끝 '🚫 병합 예정' 한 줄(rsplit.flag_line · 스캐너 · 🌙 시간외 급등) · 🩳 공매도 흐름 하루 요약."""
import os, sys, tempfile
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
tmp = tempfile.mkdtemp()
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, rsplit, scanner, shortflow, extalert, setup3
db.init_db()
T = date.today()
with closing(db.connect()) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS events (ticker TEXT, date TEXT, kind TEXT, title TEXT, source TEXT)")
    for t, d, title in (("RSA", T + timedelta(days=3), "1:20 역분할 시행"), ("RSB", T, "역분할 시행"), ("RSC", T + timedelta(days=9), "1:10 역분할 시행")):
        conn.execute("INSERT INTO events (ticker, date, kind, title, source) VALUES (?,?,?,?,?)", (t, d.isoformat(), "역분할 시행", title, "8-K"))
    conn.commit()

    # ---- 4번: 🚫 병합 예정 한 줄 ----
    a = rsplit.flag_line(conn, "RSA")
    assert a.startswith("🚫 병합 예정 D-3(") and "1:20" in a and (T + timedelta(days=3)).isoformat()[5:] in a and "매수 보류" in a, a
    assert rsplit.flag_line(conn, "RSB").startswith("🚫 병합 예정 오늘 시행(") and "1:" not in rsplit.flag_line(conn, "RSB")
    assert rsplit.flag_line(conn, "RSC") == "" and rsplit.flag_line(conn, "NONE") == ""      # 7일 밖 · 일정 없음
    assert scanner._rs(conn, "RSA") == "\n" + a and scanner._rs(conn, "NONE") == ""
    print("flag_line OK")

    # 🌙 시간외 급등 알림에도 붙음(관심 종목 = 어제 setup3 신호)
    D = T - timedelta(days=max(0, T.weekday() - 4))                       # 가장 가까운 평일(주말이면 금요일)
    conn.execute(setup3.LOG_DDL)
    conn.execute("INSERT INTO setup3_signals VALUES (?, 'RSA', 1.0, 1, 'x')", ((D - timedelta(days=1)).isoformat(),))
    db.upsert_daily_prices(conn, "RSA", pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1e5]}, index=pd.to_datetime([D.isoformat()])))
    conn.commit()
    ix = pd.date_range(f"{D.isoformat()} 16:05", periods=30, freq="min", tz="America/New_York")
    frames = {"RSA": pd.DataFrame({"High": np.r_[np.full(29, 1.02), [1.15]], "Close": np.full(30, 1.1)}, index=ix)}
    msgs = []
    now = pd.Timestamp(f"{D.isoformat()} 16:40", tz="America/New_York").tz_convert("UTC").to_pydatetime()
    extalert.check(conn, frames, pct=10.0, send=lambda m: msgs.append(m) or True, now=now, download=lambda ts: {})
    assert msgs and "🚫 병합 예정 D-3" in msgs[0], msgs
    print("extalert OK")

    # ---- 5번: 🩳 하루 요약 ----
    day = "2026-11-03"                                                     # 화요일
    shortflow.record(conn, "RSA", day, shortflow.STAGES[2], 1.00)
    shortflow.record(conn, "SFB", day, shortflow.STAGES[1], 2.00)
    shortflow.record(conn, "SFC", day, shortflow.STAGES[3], 3.00)          # ① 관찰은 요약에서 뺌
    shortflow.record(conn, "SFD", "2026-11-02", shortflow.STAGES[2], 4.00) # 다른 날
    idx = pd.bdate_range(end=day, periods=5)
    daily = {"RSA": pd.DataFrame({"Close": [1, 1, 1, 1, 1.10]}, index=idx), "SFB": pd.DataFrame({"Close": [2, 2, 2, 2, 1.90]}, index=idx)}
    sent = []
    after = datetime(2026, 11, 3, 21, 15, tzinfo=timezone.utc)            # 16:15 ET
    config.SHORTFLOW_ALERTS, config.SHORTFLOW_DIGEST = True, True
    assert not scanner.shortflow_digest(conn, daily, now=datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc), send=sent.append)   # 15:00 ET: 아직
    assert scanner.shortflow_digest(conn, daily, now=after, send=sent.append) and len(sent) == 1
    msg = sent[0]
    assert msg.startswith("🩳 공매도 흐름 하루 요약 (11-03 · 워치리스트·저금통 2건)"), msg
    assert "• RSA ② 바닥 반복 확인 $1.0000 → 마감 $1.1000 (+10.0%)" in msg and "• SFB ③ 수익확정 커버형 양봉 $2.0000 → 마감 $1.9000 (-5.0%)" in msg
    assert "SFC" not in msg and "SFD" not in msg and "🚫 RSA 병합 예정 D-3" in msg, msg
    assert not scanner.shortflow_digest(conn, daily, now=after + timedelta(hours=1), send=sent.append) and len(sent) == 1   # 하루 한 번
    db.set_meta("shortflow_digest_day", "")
    assert not scanner.shortflow_digest(conn, daily, now=datetime(2026, 11, 7, 21, 15, tzinfo=timezone.utc), send=sent.append)  # 토요일
    config.SHORTFLOW_DIGEST = False
    assert not scanner.shortflow_digest(conn, daily, now=after, send=sent.append)                                             # 끄면 즉시 알림(요약 없음)
    config.SHORTFLOW_DIGEST = True
    assert shortflow.digest_text(conn, "2026-11-04") is None                                                                  # 기록 없는 날
    print("digest OK")

assert config.SETTINGS["SHORTFLOW_DIGEST"][0] is bool and config._DEFAULTS["SHORTFLOW_DIGEST"] is True
print("ALL OK")
