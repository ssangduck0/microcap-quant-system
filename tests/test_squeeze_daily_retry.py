"""멈춘 기능 2개(2026-10-31): ① 🧨 스퀴즈 순위·대차 감시 목록이 화면을 열 때만 저장돼 10/26 뒤로 멈춤 → 아침 작업이 매일(감시 목록 = 스퀴즈 상위 + Reg SHO + 워치리스트 + 저금통)
② 🔔 텔레그램 전송 실패(10/31 새벽 11건)가 그대로 사라짐 → 5분 기다렸다가 30분 안에 한 번 다시(끝에 '⏱ 지연 전송')."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import datetime, timedelta, timezone
import db, config, shortdata, squeeze as sq, regsho, watch, piggy, notify

db.init_db()
with closing(db.connect()) as conn:
    shortdata.ensure_tables(conn); conn.commit()

# ① 스퀴즈 순위 매일
sq.rows = lambda r30=None: [{"ticker": t, "score": 90 - i} for i, t in enumerate(["AAA", "BBB", "CCC"])]
regsho.streaks = lambda conn: {"SHO1": 5, "BBB": 2}
watch.scanner_priority = lambda: ["WAT1"]
piggy.tickers_all = lambda: ["PIG1", "aaa"]
logs = []
assert sq.daily(out=logs.append, day="2026-10-30") == 3 and "1위 AAA(90점)" in logs[0], logs
sq.rows = lambda r30=None: [{"ticker": t, "score": 90 - i} for i, t in enumerate(["CCC", "AAA", "BBB"])]
sq.daily(out=lambda *_: None, day="2026-10-31")
with closing(db.connect()) as conn:
    got = conn.execute("SELECT date, ticker, rank FROM squeeze_rank ORDER BY date, rank").fetchall()
    tracked = json.loads(conn.execute("SELECT v FROM shortdata_meta WHERE k='tracked'").fetchone()[0])
assert [tuple(x) for x in got] == [("2026-10-30", "AAA", 1), ("2026-10-30", "BBB", 2), ("2026-10-30", "CCC", 3), ("2026-10-31", "CCC", 1), ("2026-10-31", "AAA", 2), ("2026-10-31", "BBB", 3)], got
assert tracked == ["CCC", "AAA", "BBB", "SHO1", "WAT1", "PIG1"], tracked                       # 스퀴즈 상위 + Reg SHO + 워치리스트 + 저금통(중복·대소문자 정리)
assert sq.save_ranks([{"ticker": "AAA", "score": 1}, {"ticker": "CCC", "score": 0}], "2026-11-02") == {"AAA": 1, "CCC": -1}   # 전날(10/31) 대비 변화(↑ 양수)
big = [{"ticker": f"T{i:03d}", "score": 300 - i} for i in range(300)]
sq.save_ranks(big[:100], "2026-11-03", track_from=big)
with closing(db.connect()) as conn:
    tr2 = json.loads(conn.execute("SELECT v FROM shortdata_meta WHERE k='tracked'").fetchone()[0])
    assert conn.execute("SELECT COUNT(*) FROM squeeze_rank WHERE date='2026-11-03'").fetchone()[0] == 100
assert tr2[:150] == [f"T{i:03d}" for i in range(150)] and tr2[150:] == ["SHO1", "BBB", "WAT1", "PIG1", "AAA"], tr2[148:]   # 순위는 100개만 저장해도 감시는 상위 150
regsho.streaks = lambda conn: (_ for _ in ()).throw(RuntimeError("x"))
assert sq.tracked(None, big[:2]) == ["T000", "T001", "WAT1", "PIG1", "AAA"]   # 한 출처가 실패해도 나머지는
sq.rows = lambda r30=None: []
assert sq.daily(out=lambda *_: None) == 0

# ② 텔레그램 실패 다시 보내기
config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID = "t", "c"
sent, fail = [], {"on": True}
class Resp:
    def raise_for_status(self): pass
def post(url, json=None, timeout=None):
    if fail["on"]:
        raise TimeoutError("read timeout")
    sent.append(json["text"]); return Resp()
notify.requests.post = post
assert notify.send_telegram("[LICN] 펌핑점수 80.0 | 낙폭 -36.9% | 가격 변동") is False
assert notify.send_telegram("🐷 FAMI 저금통 진입 구간") is False
with closing(db.connect()) as conn:
    rows = conn.execute("SELECT id, at, kind, ticker, ok, retried FROM alert_log ORDER BY id").fetchall()
assert [(r[2], r[3], r[4], r[5]) for r in rows] == [("🎯 신호", "LICN", 0, None), ("🐷 저금통", "FAMI", 0, None)], rows
t_fail = datetime.fromisoformat(rows[0][1].replace("Z", "+00:00"))
assert notify.retry_failed(now=t_fail + timedelta(minutes=2)) == 0 and sent == []                 # 5분 안은 기다림(끊김이 지나가게)
fail["on"] = False
assert notify.retry_failed(now=t_fail + timedelta(minutes=6)) == 2
assert sent[0].startswith("[LICN] 펌핑점수") and "⏱ 지연 전송(" in sent[0] and sent[1].startswith("🐷 FAMI"), sent
assert notify.retry_failed(now=t_fail + timedelta(minutes=7)) == 0 and len(sent) == 2                # 한 번만
with closing(db.connect()) as conn:
    rows = conn.execute("SELECT kind, ticker, ok, retried FROM alert_log ORDER BY id").fetchall()
assert [tuple(r) for r in rows] == [("🎯 신호", "LICN", 0, 1), ("🐷 저금통", "FAMI", 0, 1), ("🎯 신호", "LICN", 1, 1), ("🐷 저금통", "FAMI", 1, 1)], rows   # 다시 보낸 것도 같은 종류·종목으로
# 다시 보낸 것이 또 실패하면 더 안 보냄 · 30분 지난 실패는 안 보냄
fail["on"] = True
notify.send_telegram("🌙 VCIG 애프터 진입 구간")
t2 = datetime.now(timezone.utc)
assert notify.retry_failed(now=t2 + timedelta(minutes=6)) == 0
assert notify.retry_failed(now=t2 + timedelta(minutes=12)) == 0
fail["on"] = False
assert notify.retry_failed(now=t2 + timedelta(minutes=13)) == 0 and len(sent) == 2
fail["on"] = True; notify.send_telegram("🔔 OLDX 8-K · 악재"); fail["on"] = False
assert notify.retry_failed(now=datetime.now(timezone.utc) + timedelta(minutes=45)) == 0           # 30분 넘으면 버림
config.TELEGRAM_TOKEN = ""
assert notify.send_telegram("✅ 키 없음") is False and notify.retry_failed() == 0                    # 키 없으면 다시 보낼 것도 없음
print("ALL OK")
