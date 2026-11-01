"""📊 알림 지난 성적(2026-11-01): 🎯 펌핑 점수 알림을 🏆 출처로 · 알림 끝 '이 알림 지난 성적' 한 줄(기간이 다 끝난 판정만 셈 · 10건 미만은 '기록 쌓는 중')."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, scoreboard as sb

db.init_db()
T = date.today()
D = lambda n: (T - timedelta(days=n)).isoformat()
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    for t, ex in (("AAA", 0), ("BBB", 1), ("CCC", 0)):
        db.upsert_snapshot(conn, {"date": D(20), "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
            "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 1e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 80.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": ex})
    for t, ps, reason in (("AAA", 82, "첫 포착"), ("AAA", 85, "가격 변동"), ("BBB", 90, "첫 포착"), ("CCC", 60, "첫 포착")):
        db.insert_signal(conn, {"date": D(20), "ticker": t, "price": 1.0 if reason == "첫 포착" else 1.1, "drawdown_pct": -40.0, "quant_score": 50.0, "pump_score": ps,
                                "dilution_status": "CLEAN", "reason": reason})
    col = sb.collect(conn)
    pm = col[col.source == "pump"]
    assert list(pm.ticker) == ["AAA"] and pm.iloc[0]["entry"] == 1.0 and "펌핑 82" in pm.iloc[0]["note"], pm      # 같은 날 첫 번째만 · 제외(BBB)·70 미만(CCC) 빼고
    assert sb.SOURCES["pump"] == ("🎯 펌핑 점수 알림(≥70)", 1, 30.0, 10)

    conn.execute(sb.DDL)
    rows = [("pump", D(40 + i), f"P{i}", "성공" if i < 6 else "실패") for i in range(12)]      # 기간(10거래일) 끝남 12건 · 성공 6
    rows += [("pump", D(3), "PX", "성공")]                                                        # 아직 기간 안 → 안 셈(착시 방지)
    rows += [("after", D(5 + i), f"A{i}", "성공" if i == 0 else "실패") for i in range(3)]          # 당일 기간 · 3건
    rows += [("flow_down", D(30 + i), f"F{i}", "성공") for i in range(10)]
    rows += [("piggy", D(60), "PG", "대기")]                                                      # 대기는 안 셈
    for s, d, t, st in rows:
        conn.execute("INSERT INTO pred_outcomes (source, date, ticker, ref, status, updated_at) VALUES (?,?,?,?,?,?)", (s, d, t, "", st, now))
    conn.commit()
    sb._TRACK.update(at=0.0, stats={})
    st = sb.track_stats(conn)
    assert st["pump"] == (12, 6) and st["after"] == (3, 1) and st["flow_down"] == (10, 10) and "piggy" not in st, st

sb._TRACK.update(at=0.0, stats={})
assert sb.track_line("pump") == "📊 이 알림 지난 성적: 기간 끝난 12건 중 성공 50%(목표 +30% · 10거래일 안)", sb.track_line("pump")
assert sb.track_line("after") == "📊 이 알림 지난 성적: 기록 쌓는 중(3건 · 목표 +5% · 당일)"
assert sb.track_line("flow_down") == "📊 이 알림 지난 성적: 기간 끝난 10건 중 성공 100%(목표 5거래일 뒤 하락)"
assert sb.track_line("piggy") == "📊 이 알림 지난 성적: 기록 쌓는 중(0건 · 목표 박스 상단·목표가 · 10거래일 안)"
assert sb.track_line("nope") == "" and sb.track_line("") == ""
assert "10거래일 안 −20%" in sb.track_line("sd_ib_inflow")                                       # 내림 예측 + 목표 %

# 스캐너: 알림 끝 한 줄(실패해도 빈 문자열)
import scanner
assert scanner._track("pump").startswith("\n📊 이 알림 지난 성적: 기간 끝난 12건") and scanner._track("없는출처") == ""
# 차트 관점 알림: 🏆 출처가 있는 코드는 한 줄이 붙음
import chartview
mapped = [c for c in chartview.LIVE_CODES if c in sb.CHART_SRC]
assert set(mapped) == {"life_break", "pullback", "h60_200"} and all(sb.track_line(sb.CHART_SRC[c]) for c in mapped)
src = open(os.path.join(os.environ["QS_ROOT"], "scanner.py"), encoding="utf-8").read()
for k in ('_track("after")', '_track("pump")', '_track("piggy")', '"shortflow_exit" if', '"flow_down" if'):
    assert k in src, k
print("ALL OK")
