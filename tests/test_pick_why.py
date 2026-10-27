import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, io, contextlib
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, pick30
db.init_db()
T = date.today(); now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.5, "high_20d": 0.55, "low_20d": 0.4,
        "drawdown_pct": -20.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 50.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
    tgt = {"targets": [("$1 상장 유지", 1.0, "")], "score": 6}
    d = lambda n: (T + timedelta(days=n)).isoformat()  # noqa: E731

    # 지난 상장유지 기한: 예전엔 음수 일수라 '유력'으로 잡혔음 → 이제 임박으로 세지 않고 이유에 적음
    r = pick30.evaluate("AAA", conn, {**tgt, "listing": {"deadline": d(-20)}}, None)
    assert r["status"] == "대기" and r["imm_days"] is None and "20일 지남" in r["why"] and r["past"], r
    # 자료 없음
    r = pick30.evaluate("AAA", conn, tgt, None)
    assert r["status"] == "대기" and r["why"].startswith("임박 자료 없음") and "런웨이 미확인" in r["why"] and not r["has_runway"], r
    # 일정이 멂 + 런웨이 김
    r = pick30.evaluate("AAA", conn, {**tgt, "listing": {"deadline": d(120)}}, {"runway_now": 8.0, "floor": d(243)})
    assert r["status"] == "대기" and "D-120" in r["why"] and "45일 넘음" in r["why"] and "런웨이 8.0개월" in r["why"], r
    # 가능: 런웨이 3개월 이하 / 45일 안 기한
    r = pick30.evaluate("AAA", conn, tgt, {"runway_now": 2.5, "floor": d(76)})
    assert r["status"] == "가능" and "런웨이 2.5개월" in r["why"], r
    r = pick30.evaluate("AAA", conn, {**tgt, "listing": {"deadline": d(30)}}, None)
    assert r["status"] == "가능" and r["why"] == "상장유지 기한 D-30", r
    # 유력: 14일 안 + 압박 5 이상
    r = pick30.evaluate("AAA", conn, {**tgt, "listing": {"deadline": d(7)}}, None)
    assert r["status"] == "유력" and r["why"] == "상장유지 기한 D-7 · 압박 6", r

    # 약한 목표(baby shelf): 14일 안 + 압박 5↑ 이어도 '유력'이 아니라 '가능'
    bs = {"targets": [("baby shelf 탈출", 1.0, "")], "score": 6}
    r = pick30.evaluate("AAA", conn, {**bs, "listing": {"deadline": d(7)}}, None)
    assert r["weak"] and r["status"] == "가능", r
    strong = pick30.evaluate("AAA", conn, {**tgt, "listing": {"deadline": d(7)}}, None)
    assert not strong["weak"] and strong["status"] == "유력"
    # 같은 상태면 강한 목표 먼저
    a1 = {**r, "ticker": "W", "status": "가능", "imm_days": 1}; a2 = {**strong, "ticker": "S", "status": "가능", "imm_days": 30}
    assert [x["ticker"] for x in pick30.sort([a1, a2], "유력·임박 순")] == ["S", "W"]
    # 🏆 기록: 같은 종목·목표는 30일에 한 번, 목표 종류별 출처
    fake = {"pass": [r, strong]}
    assert pick30.record(conn, fake) == 2 and pick30.record(conn, fake) == 0
    assert pick30.record(conn, fake, today=T + timedelta(days=31)) == 2
    import scoreboard as sb
    p = sb.collect(conn)
    assert set(p["source"]) >= {"pick_bs", "pick_strong"}, p
    row = p[p["source"] == "pick_bs"].iloc[0]
    assert abs(row["target"] - r["pct"]) < 1e-6 and row["horizon"] == 60 and "baby shelf" in row["note"], row

rows = [{"status": "대기", "imm_days": None, "has_runway": False, "runway": None, "has_listing": False, "past": None},
        {"status": "대기", "imm_days": 90, "has_runway": True, "runway": 6.0, "has_listing": True, "past": None},
        {"status": "가능", "imm_days": 10, "has_runway": True, "runway": 2.0, "has_listing": True, "past": None}]
w = pick30.why_stats(rows)
assert w["대기"] == 2 and w["임박 자료 없음"] == 1 and w["일정이 45일 넘게 남음"] == 1 and w["런웨이 미확인"] == 1 and w["런웨이 3개월 넘음"] == 1, w

# 점검 명령이 빈 DB 에서도 끝까지 돈다
import diag_pick
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    diag_pick.main()
out = buf.getvalue(); assert "[1] 등록" in out and "[3] 원재료" in out and "끝." in out, out[-500:]
print("ALL OK")
