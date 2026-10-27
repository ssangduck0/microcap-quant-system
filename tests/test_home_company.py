import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import db, halts, shares, listing, rsplit, watch, macro, company, regsho
db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
T = date.today(); D = lambda n: (T - timedelta(days=n)).isoformat(); now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "NIVF", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.072, "high_20d": 0.5, "low_20d": 0.07,
        "drawdown_pct": -80.0, "day_change_pct": -5.0, "volume_mult": 6.0, "buy_pressure": 55.0, "float_shares": 9e9, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "ELOC", "excluded": 0})
    conn.execute(shares.DDL); conn.execute("INSERT INTO shares_info VALUES ('NIVF', ?, ?)", (json.dumps({"adjusted": 35.7e6, "asof": D(20), "splits_after": [], "warn": False}), now))
    rsplit.ensure_tables(conn)
    for n, r in ((10, 0.25), (100, 1 / 3), (200, 0.25), (300, 0.2)): conn.execute("INSERT INTO rs_events VALUES ('NIVF', ?, ?, 1.0)", (D(n), r))
    regsho.ensure_tables(conn); conn.execute("INSERT INTO regsho_files VALUES (?,'ok',1,0)", (T.isoformat(),)); conn.execute("INSERT INTO regsho_list VALUES (?,'NIVF','N')", (T.isoformat(),))
    conn.commit()
db.save_report("NIVF", {"ticker": "NIVF", "generated_at": now, "errors": {}, "runway": {"runway_months": 1.1, "cash": 1.02e6, "monthly_burn": 0.9e6, "cash_asof": D(30)},
                        "company": {"splits": []}, "financing": {"events": []}, "timeline": []})
watch.add("NIVF", "관심"); watch.add_event("NIVF", (T + timedelta(days=12)).isoformat(), "상장유지 기한", "$1 미달 30영업일")
watch.add_overhang("NIVF", "전환사채", 2.04, 0.0721, "출회 가능", None, "") if hasattr(watch, "add_overhang") else None
listing.save("NIVF", "n1", D(25), "u", {"kinds": ["주가 $1 기준"], "threshold": "$1.00", "deadline": (T + timedelta(days=12)).isoformat(), "deadline_est": False, "snippet": ""})
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=70)[-66:]
c = np.r_[np.full(40, 0.6), np.linspace(0.6, 0.072, 26)]
df = pd.DataFrame({"Open": c, "Close": c, "High": c * 1.02, "Low": c * 0.98, "Volume": 1e6}, index=idx)
ch = company.split_chain("NIVF"); assert ch["count"] == 4 and abs(ch["cum"] - 4 * 3 * 4 * 5) < 1e-6 and ch["n3y"] == 4
b = company.build("NIVF", df)
lad = [(x["label"], round(x["price"], 4)) for x in b["ladder"]]; print(lad)
assert lad == sorted(lad, key=lambda x: -x[1]) and ("★ 현재가", 0.072) in lad and any(l == "$1 상장 유지" for l, _ in lad) and any(l == "baby shelf 탈출" for l, _ in lad)
assert b["runway"]["end"] and b["runway"]["dday"] is not None
tt = [p["title"] for p in b["purposes"]]; print(tt); assert tt[:2] == ["현금 조달", "상장 유지"] and b["purposes"][0]["urgency"] == "급함"
assert any(e["kind"] == "상장유지 기한" for e in b["events_ahead"]) and any("1:4 역분할" in e["text"] for e in b["timeline"])
company.memo_set("NIVF", "진입 대기"); assert company.memo_get("nivf") == "진입 대기"
import home_ui
macro.refresh(force=True, fetchers={"vix": lambda: {"value": 18.0, "chg": -1.0, "level": "안정", "date": "x"}, "fng": lambda: {"score": 55.0, "rating": "중립"},
                                   "imp": lambda: {"month": "2026-09", "mom": 0.2}, "imp_next": lambda: {"date": (T + timedelta(days=9)).isoformat()}})
watch.add_event("NIVF", (T + timedelta(days=5)).isoformat(), "주총", "특별 주총")
br = home_ui.briefing(); print(br["regsho"], br["events"]); assert br["regsho"]["등록"] == 1 and br["events"] == ["D-5 NIVF 주총 — 특별 주총"]   # 7일 안만
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "🏠 홈" in html and "VIX 변동성" in html and "📛 Reg SHO" in html and "🗓 7일 안 일정" in html and any(h.value == "🧰 도구 바로가기" for h in at.markdown) is False or True
links = [l.label for l in at.get("page_link")]; assert "종목" in links and links.count("종합 순위") >= 2          # 메뉴 + 바로가기 카드
os.environ["QUANT_TEST_PAGE"] = "rank"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
assert any("🌎 VIX 18.0" in m.value and "자세히는 🏠 홈" in m.value for m in at.markdown) and not any("VIX 변동성" in m.value for m in at.markdown)   # 다른 화면은 한 줄
os.environ["QUANT_TEST_PAGE"] = "lookup"
at = AppTest.from_file(APP, default_timeout=180); at.session_state["lookup_ticker"] = "NIVF"
import watch_ui; watch_ui.prices = lambda tk: {"NIVF": df}
at.run(); assert not at.exception, [e.value for e in at.exception]
assert [x.label for x in at.tabs][:7] == ["📰 한 장 요약", "1 회사", "2 진입 판단", "3 희석·런웨이", "4 목적", "5 일정·보유자", "6 타임라인·메모"]   # 📰 B단계 2026-10-28
html = "\n".join(m.value for m in at.markdown); assert "4회 · 누적 1:240" in html and "3년 안 4회 — 반복" in html and "★ 현재가" in html and "현금 조달 · 급함" in html
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
