import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🧨 공매도 잔고 받을 순서(C단계): Reg SHO·고수수료인데 오래된 종목 먼저 → 한 번도 안 받은 종목 → 오래된 순. 스퀴즈 후보에 급등락·장외 공매도 60%↑ 종목 포함."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, shortint, shortdata, regsho, mover, squeeze
db.init_db()
today = date.today().isoformat()
old = (date.today() - timedelta(days=10)).isoformat()
with closing(db.connect()) as conn:
    shortdata.ensure_tables(conn); shortint.ensure_tables(conn); regsho.ensure_tables(conn); mover.ensure(conn)
    now = db.utcnow_iso()
    for t in ("SNAPA", "SNAPB", "HOTOLD", "HOTNEW", "FEE", "MOVER", "SV60"):
        db.upsert_snapshot(conn, {"date": today, "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
            "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0}) if t in ("SNAPA", "SNAPB", "HOTOLD", "HOTNEW") else None
    conn.execute("INSERT INTO regsho_files VALUES (?,?,?,?)", (today, "ok", 2, 0.0))   # streaks() 는 받은 파일 날짜 기준
    conn.execute("INSERT INTO regsho_list VALUES (?,?,?)", (today, "HOTOLD", "Hot Old")); conn.execute("INSERT INTO regsho_list VALUES (?,?,?)", (today, "HOTNEW", "Hot New"))
    conn.execute("INSERT INTO ibkr_borrow (symbol, fee, rebate, available, avail_capped, as_of) VALUES ('FEE', 25.0, -20.0, 1000, 0, ?)", (now,))
    conn.execute("INSERT INTO toss_rank VALUES (?,?,?,?,?,?,?,?)", (today, "up", 1, "MOVER", 1.0, 50.0, "정규장", now))
    conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (today, "SV60", 700000, 0, 1000000))
    conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (today, "SV40", 400000, 0, 1000000))
    conn.execute("INSERT INTO short_interest VALUES ('HOTOLD', ?, 1, 1, 10, 1, ?, 1e6)", (old, old))
    conn.execute("INSERT INTO short_interest VALUES ('HOTNEW', ?, 1, 1, 10, 1, ?, 1e6)", (today, today))
    conn.execute("INSERT INTO short_interest VALUES ('SNAPB', ?, 1, 1, 10, 1, ?, 1e6)", (old, old))
    conn.commit()
    uni = set(squeeze.universe(conn))
    assert {"SNAPA", "SNAPB", "HOTOLD", "HOTNEW", "FEE", "MOVER", "SV60"} <= uni and "SV40" not in uni, uni     # 수수료 20%↑·급등락·장외 공매도 60%↑ 포함
order = shortint.priority(max_n=10)
assert order[:2] == ["FEE", "HOTOLD"], order                       # 핫한데 안 받았거나 오래된 것 먼저(알파벳)
assert order.index("SNAPA") < order.index("SNAPB") < order.index("HOTNEW"), order   # 한 번도 안 받은 것 → 오래된 것 → 오늘 받은 것
assert len(shortint.priority(max_n=3)) == 3
# refresh 는 가짜 getter 로 — 이미 오늘 받은 HOTNEW 는 건너뜀
n = shortint.refresh(order, max_n=100, out=lambda *_: None, getter=lambda t: {"shortPercentOfFloat": 0.2, "dateShortInterest": 1760000000, "sharesShort": 100, "sharesShortPriorMonth": 90, "shortRatio": 2.0, "floatShares": 1e6})
assert n == len(order) - 1, (n, len(order))
print("ALL OK")
