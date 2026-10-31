"""🛠 운영 현황(2026-10-31): ① 🩺 아침 작업 점검표(평소보다 크게 떨어지면 빨강) ② ⏱ 자동 작업 일정(다음 실행·지난 실행) ③ 📜 작업 기록 · 홈(주인만)."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
bk = os.path.join(tmp, "bk"); os.makedirs(bk); os.environ["QUANT_BACKUP_DIR"] = bk
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import datetime, timedelta, timezone
import db, jobs, secfeed, secdigest, notify

db.init_db()
KST = jobs.KST
now = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)          # 한국 10/31(토) 09:00

# 기록 · 쪽 넘기기 · 마지막 실행 표시
for i in range(12):
    jobs.record("chartex", now - timedelta(days=12 - i, minutes=30), now - timedelta(days=12 - i), ok=i != 3, warn=0, summary=f"공매 수집 {i}")
r = jobs.runs(limit=10)
assert len(r) == 10 and r[0]["summary"] == "공매 수집 11" and r[0]["total"] == 12 and jobs.runs(limit=10, offset=10)[-1]["summary"] == "공매 수집 0"
jobs.mark("warm", True, "3개 만듦")
assert json.loads(db.get_meta("job_last:warm")["value"])["summary"] == "3개 만듦"

# 숫자 재기(지난 24시간 · 한국 날짜)
with closing(db.connect()) as conn:
    secfeed.ensure_tables(conn); secdigest.ensure(conn); notify._ensure(conn)
    t = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    for i in range(20):
        conn.execute("INSERT INTO sec_feed (accession, ticker, form, updated, url, enriched, created_at, lead) VALUES (?,?,?,?,?,1,?,?)",
                     (f"a{i}", "ABC", "8-K", t, "u", t, "On October 30, 2026, ..." if i < 5 else ""))
        conn.execute("INSERT INTO sec_digest (accession, ticker, form, filed, summary_ko, category, grade, done_at) VALUES (?,?,?,?,?,?,?,?)",
                     (f"a{i}", "ABC", "8-K", "2026-10-30", "발췌문에는 내용이 없어 확인되지 않습니다" if i < 15 else "실적 개선", "기타", "C", t))
    conn.execute("INSERT INTO alert_log (at, kind, ticker, text, ok) VALUES (?, '기타', NULL, 'x', 0)", (t,))
    conn.commit()
    m = jobs.health(conn, now)
assert m["새 공시"] == 20 and m["핵심 문장 %"] == 25 and m["AI 요약"] == 20 and m["AI 요약 '내용 없음' %"] == 75 and m["텔레그램 실패"] == 1, m
assert m["AI 비용(어제·원)"] == 0 and m["스퀴즈 순위 경과일"] is None

# 빨강 판정: 절대 기준 · 평소 대비
assert jobs.flag("AI 요약 '내용 없음' %", 75, []) == "red" and jobs.flag("AI 요약 '내용 없음' %", 35, []) == "yellow" and jobs.flag("AI 요약 '내용 없음' %", 5, []) == ""
assert jobs.flag("핵심 문장 %", 0, []) == "red" and jobs.flag("핵심 문장 %", 80, []) == ""
assert jobs.flag("새 공시", 100, [900, 1000, 1100]) == "red" and jobs.flag("새 공시", 700, [900, 1000, 1100]) == "yellow" and jobs.flag("새 공시", 980, [900, 1000, 1100]) == ""
assert jobs.flag("새 공시", 0, [900, 1000]) == ""                                         # 기록 3번 전엔 평소 비교 안 함
assert jobs.flag("PICK", 0, [5, 5, 5]) == "" and jobs.flag("스퀴즈 순위 경과일", 5, []) == "red" and jobs.flag("새 공시", None, [1, 2, 3]) == ""

# 점검표: 아침 작업 기록 8번 · 마지막에 AI 요약이 0
for i in range(8):
    jobs.record("cases", now - timedelta(days=8 - i, hours=2), now - timedelta(days=8 - i), True, 0, f"아침 {i}",
                {"AI 요약": 0 if i == 7 else 800 + i, "새 공시": 1000, "경고": 0, "걸린 시간(분)": 120})
tb = jobs.table(7)
assert len(tb["days"]) == 7 and tb["days"][0]["summary"] == "아침 7"
row = next(x for x in tb["rows"] if x["name"] == "AI 요약")
assert row["vals"][0] == (0, "red") and row["vals"][1] == (806, "") and [a[0] for a in tb["alerts"]] == ["AI 요약"], tb["alerts"]

# 일정: 토 09:00 → 아침 작업 다음은 화 07:30 · 백업은 일 03:00 · 10분마다
cs = next(s for s in jobs.SCHEDULE if s["key"] == "cases")
nx = jobs.next_run(cs, now)
assert nx.astimezone(KST).strftime("%m/%d %H:%M %a") == "11/03 07:30 Tue" and jobs.until(nx, now) == "2일 22시간 뒤", (nx, jobs.until(nx, now))
assert jobs.next_run(next(s for s in jobs.SCHEDULE if s["key"] == "backup"), now).astimezone(KST).strftime("%m/%d %H:%M") == "11/01 03:00"
assert jobs.until(now + timedelta(hours=20, minutes=53), now) == "20시간 53분 뒤" and jobs.until(now + timedelta(minutes=7, seconds=5), now) == "7분 뒤"
assert jobs.until(now + timedelta(days=5, hours=3), now) == "5일 뒤" and jobs.ago(now - timedelta(hours=3), now) == "3시간 전" and jobs.ago(now - timedelta(days=3), now) == "3일 전"
open(os.path.join(bk, "quant-20261031.db.gz"), "wb").write(b"x" * 2_000_000)
sc = {r["key"]: r for r in jobs.schedule(now)}
assert sc["cases"]["last_note"] == "아침 7" and sc["cases"]["last_ok"] is True and sc["chartex"]["last_note"] == "공매 수집 11"
assert sc["backup"]["last_note"].startswith("quant-20261031.db.gz · 2MB") and sc["warm"]["last_note"] == "3개 만듦" and sc["scanner"]["next_txt"] == "계속 실행 중"

# 아침 작업 끝 기록(cases.main 이 부름)
logs = []
mm = jobs.morning_done(datetime.now(timezone.utc) - timedelta(minutes=125), True, out=logs.append)
last = jobs.runs("cases", limit=1)[0]
assert last["summary"].startswith("아침 작업 완료 · 2시간 5분 · 경고 0") and last["metrics"]["걸린 시간(분)"] == 125 and "AI 요약" in last["metrics"], last
assert logs and logs[0].startswith("🩺 점검표 빨간 칸:") and "AI 요약 '내용 없음' %" in logs[0], logs

# 홈 화면: 주인만 🛠 운영 현황
with closing(db.connect()) as conn:   # 스캐너 기록이 하나도 없으면 대시보드가 안내만 보여 줌
    _n = db.utcnow_iso()
    db.upsert_snapshot(conn, {"date": datetime.now().date().isoformat(), "ticker": "ABC", "exchange": "NASDAQ", "first_seen": _n, "last_seen": _n, "price": 1.0,
        "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -40.0, "day_change_pct": 1.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 1e7, "atr14": 0.01,
        "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["DASH_PASSWORD"] = ""
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
md = "\n".join(m.value for m in at.markdown)
assert "🛠 운영 현황" in md and "🩺 아침 작업 점검표" in [t.label for t in at.tabs] and "오늘 빨간 칸" in md and "🌅 아침 작업" in md and "공매 수집 11" in md, md[:500]
print("ALL OK")
