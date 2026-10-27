import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, halts, shortdata, shortint, squeeze as sq, regsho
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso(); today = date.today()
with closing(db.connect()) as conn:
    for t, fs in (("BENF", 3e6), ("KAZR", 50e6), ("LOW", 80e6)):
        db.upsert_snapshot(conn, {"date": today.isoformat(), "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
            "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": fs, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    shortdata.ensure_tables(conn)
    conn.execute("INSERT INTO ibkr_borrow (symbol,fee,rebate,available,avail_capped,as_of) VALUES ('BENF',115.37,0,0,0,'x'),('KAZR',18.7,0,500000,0,'x'),('LOW',1.0,0,10000000,1,'x')")
    for i in range(5):
        d = (today - timedelta(days=i)).isoformat()
        conn.execute("INSERT INTO ibkr_borrow_day VALUES (?,?,?,?,?)", (d, "BENF", 50000, 0, 115.0 + i))
        conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (d, "BENF", 600 + i, 0, 1000))
        conn.execute("INSERT INTO ibkr_avail_hist VALUES (?,?,?,?)", ("BENF", f"{d}T10:00", 50000 - i * 5000, 115.0)) if conn.execute("SELECT name FROM sqlite_master WHERE name='ibkr_avail_hist'").fetchone() else None
    conn.execute("CREATE TABLE IF NOT EXISTS ibkr_avail_hist (symbol TEXT NOT NULL, ts TEXT NOT NULL, avail REAL, fee REAL, PRIMARY KEY (symbol, ts))")
    conn.execute("INSERT OR IGNORE INTO ibkr_avail_hist VALUES ('BENF', ?, 45000, 115)", (now,))
    conn.commit()
shortint.refresh(["BENF", "KAZR"], getter=lambda t: {"BENF": {"shortPercentOfFloat": 0.6074, "shortRatio": 25.65, "sharesShort": 950400, "dateShortInterest": 1791763200, "floatShares": 1.56e6},
                                                    "KAZR": {"shortPercentOfFloat": 1.6198, "shortRatio": 1.88, "sharesShort": 2e6}}[t], out=lambda *_: None)
si = shortint.latest_map(); assert abs(si["BENF"]["si_pct"] - 60.74) < 1e-9 and abs(si["KAZR"]["si_pct"] - 161.98) < 1e-9 and si["BENF"]["si_date"]
rs = sq.rows(); print([(r["ticker"], r["score"]) for r in rs])
assert rs[0]["ticker"] == "BENF" and rs[0]["parts"]["공매도 비율"] == 30 and rs[0]["parts"]["청산 소요일"] == 20 and rs[0]["parts"]["대차 가용"] == 10 and rs[-1]["ticker"] == "LOW"
ch = sq.save_ranks(rs, (today - timedelta(days=1)).isoformat()); ch = sq.save_ranks(list(reversed(rs)), today.isoformat())
assert ch["LOW"] == 2 and ch["BENF"] == -2                                                   # 어제 3위 → 오늘 1위 = ↑2
with closing(db.connect()) as conn:
    assert "BENF" in json.loads(conn.execute("SELECT v FROM shortdata_meta WHERE k='tracked'").fetchone()[0])     # 15분 가용주식 기록 대상
os.environ["QUANT_TEST_PAGE"] = "squeeze"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
tb = [d.value for d in at.dataframe if "스퀴즈 점수" in d.value.columns][0]; print(tb[["순위", "변화", "티커", "스퀴즈 점수", "공매도 비율(%)", "청산 소요일", "대차 가용"]].to_string(index=False))
assert tb.iloc[0]["티커"] == "BENF" and tb.iloc[0]["대차 가용"] == "0 (HTB)" and abs(tb.iloc[0]["공매도 비율(%)"] - 60.74) < 1e-9
open(__import__("os").path.join(__import__("tempfile").gettempdir(), "sp_app.py"), "w").write('import sys; sys.path.insert(0,__import__("os").environ["QS_ROOT"])\nimport ui_kit, report_dialog\nui_kit.inject()\nreport_dialog.render("BENF", "short")\n')
os.environ.pop("QUANT_TEST_PAGE")
at = AppTest.from_file(__import__("os").path.join(__import__("tempfile").gettempdir(), "sp_app.py"), default_timeout=120).run(); assert not at.exception, [e.value for e in at.exception]
assert [x.label for x in at.tabs][:2] == ["🧨 공매도", "📌 한눈에"]
html = "\n".join(m.value for m in at.markdown); assert "60.74%" in html and "25.65일" in html and "0K" in html and "HTB" in html and "115.37%" in html
assert any("대차 수수료" in w.value for w in at.warning)
print("ALL OK")
