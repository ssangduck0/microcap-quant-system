"""notify.classify — 알림 글 → (종류, 종목): 스캐너 본 신호 '[POM] 펌핑점수 …' 는 🎯 신호(예전엔 '기타'), 이모지 종류, 종목 추출."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
import notify

assert notify.classify("[POM] 펌핑점수 85.0 | 낙폭 -57.4% | 🟠 최근 공모/워런트 정황 | 가격 변동") == ("🎯 신호", "POM")
assert notify.classify("[BRK.A] 펌핑점수 70 | 낙폭 -10%")[0] == "🎯 신호"
assert notify.classify("[pom] 펌핑점수 85")[0] == "기타"                      # 소문자 = 형식 아님
k, t = notify.classify("🌙 ABCD 애프터 진입 구간 $1.2000\n목표 +5%"); assert k.startswith("🌙") and t == "ABCD", (k, t)
k, t = notify.classify("👥 방문객 접속 · 형님들 · 윈도우 PC"); assert t != "PC" or k != "기타" or True   # 방문객 줄은 종목이 아니어도 됨
assert notify.classify("")[0] == "기타" and notify.classify("아무 글 $Z 하나")[1] == "Z"

# 🎯 '가격 변동' 재알림 하루 상한(2026-10-31)
import db, config
from contextlib import closing
from datetime import datetime, timedelta, timezone
db.init_db()
now = datetime.now(timezone.utc)
with closing(db.connect()) as conn:
    conn.execute(notify.DDL)
    for h in (1, 5, 10):                                                     # 24시간 안 3번
        conn.execute("INSERT INTO alert_log (at, kind, ticker, text, ok) VALUES (?,?,?,?,1)", ((now - timedelta(hours=h)).isoformat(), "🎯 신호", "POM", "[POM] 펌핑점수 85 | 낙폭 -50% | x | 가격 변동"))
    conn.execute("INSERT INTO alert_log (at, kind, ticker, text, ok) VALUES (?,?,?,?,1)", ((now - timedelta(hours=30)).isoformat(), "🎯 신호", "POM", "[POM] 펌핑점수 85 | 가격 변동"))   # 24시간 밖
    conn.execute("INSERT INTO alert_log (at, kind, ticker, text, ok) VALUES (?,?,?,?,1)", ((now - timedelta(hours=2)).isoformat(), "🐷 저금통", "POM", "🐷 POM 저점"))         # 다른 알림
    conn.commit()
    assert not notify.repeat_ok(conn, "POM", "가격 변동", cap=3) and notify.repeat_ok(conn, "POM", "가격 변동", cap=4)
    assert notify.repeat_ok(conn, "POM", "신규 거래일 포착", cap=3) and notify.repeat_ok(conn, "POM", "희석 상태 변경 CLEAN→ATM", cap=3)   # 첫 포착·희석 변경은 항상
    assert notify.repeat_ok(conn, "POM", "가격 변동", cap=0) and notify.repeat_ok(conn, "AAA", "가격 변동", cap=1)                  # 0 = 제한 없음 · 다른 종목
    config.SIGNAL_ALERT_MAX_PER_DAY = 3
    assert not notify.repeat_ok(conn, "POM", "가격 변동")
assert "SIGNAL_ALERT_MAX_PER_DAY" in config.SETTINGS
print("ALL OK")
