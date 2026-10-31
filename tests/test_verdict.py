"""🧭 종합 판단 카드(2026-10-31): 급등 뒤 조달 이력 · 현금조달 가능성(높음/중간/낮음 + 이유 · 30일 뒤 검증) · 공시 흐름 · 워런트 목적 · 한 줄 종합 · 🏢 종목 화면."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import db, verdict, secbackfill, secfeed, rsplit, watch, halts

db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
T = date.today(); D = lambda n: (T - timedelta(days=n)).isoformat()
idx = pd.bdate_range(end=pd.Timestamp(T), periods=500)
c = np.full(500, 1.0)
for i in (100, 300, 450):
    c[i:] *= 1.6                                            # 급등 3번(+60%, 그대로 머묾)
pump_days = [idx[i].date() for i in (100, 300, 450)]

with closing(db.connect()) as conn:
    secbackfill.ensure_tables(conn); secfeed.ensure_tables(conn); rsplit.ensure_tables(conn)
    for t in ("RSK", "SAFE"):
        db.upsert_daily_prices(conn, t, pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1e6}, index=idx))
    conn.execute("INSERT INTO rs_events VALUES ('RSK', ?, 0.5, 1.0)", ((pump_days[2] + timedelta(days=2)).isoformat(),))   # 세 번째는 병합 ±5일 → 급등 아님
    ins = "INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES (?,?,?,?,?)"
    conn.execute(ins, ("h1", "RSK", "424B5", (pump_days[0] + timedelta(days=3)).isoformat(), ""))      # 급등 1 → 3일 뒤 공모
    conn.execute(ins, ("h2", "RSK", "S-1", (pump_days[1] + timedelta(days=30)).isoformat(), ""))       # 급등 2 → 30일 뒤(7일 밖)
    conn.execute(ins, ("h3", "RSK", "8-K", D(20), "3.02,9.01"))
    conn.execute(ins, ("h4", "RSK", "EFFECT", D(10), ""))
    conn.execute(ins, ("h5", "RSK", "S-3", D(40), ""))
    conn.execute(ins, ("h6", "RSK", "424B4", D(30), ""))
    conn.execute(ins, ("h7", "RSK", "424B3", D(5), ""))                                                  # 재판매(424B3)는 회사 조달 아님
    conn.execute(ins, ("h8", "RSK", "DEF 14A", D(25), ""))
    conn.execute(ins, ("h9", "RSK", "8-K", D(3), "5.07"))
    conn.commit()

    pu = verdict.pump_raise(conn, "RSK")
    assert pu["pumps"] == 2 and pu["raised"] == 1 and pu["examples"][0][1] == "424B5" and pu["base"] is not None and 0 < pu["base"] < 30, pu
    assert verdict.pump_raise(conn, "SAFE")["pumps"] == 3 and verdict.pump_raise(conn, "SAFE")["raised"] == 0

    f = verdict.financing(conn, "RSK", runway={"months": 2.0}, dilution="ATM")
    rs = [r for _, r in f["reasons"]]
    assert f["level"] == "높음" and f["score"] == 3 + 2 + 1 + 1 + 1 + 1 + 2, (f["score"], rs)   # 런웨이·ATM·등록·EFFECT·60일 공모·상습(4번)·급등 뒤 1/2(절반 이상 +2)
    assert rs[0].startswith("런웨이 2.0개월") and any("ATM 열림" in r for r in rs) and any("급등 뒤 7일 안 조달 1/2번" in r for r in rs) and any("상습" in r for r in rs), rs
    g = verdict.financing(conn, "SAFE", runway={"months": 30.0}, dilution="CLEAN")
    assert g["level"] == "낮음" and g["score"] == -2 and g["reasons"][0][1].startswith("현금 넉넉"), g

    # 공시 흐름(14일) · 주총
    fi = "INSERT INTO sec_feed (accession, ticker, form, filed, updated, items, url, tags, sentiment, enriched, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,'x')"
    conn.execute(fi, ("f1", "RSK", "424B5", D(2), D(2), "", "u", '["희석 위험"]', "악재"))
    conn.execute(fi, ("f2", "RSK", "8-K", D(4), D(4), "3.02", "u", "[]", "악재"))
    conn.execute(fi, ("f3", "RSK", "8-K", D(6), D(6), "8.01", "u", '["파트너십·계약"]', "약한 호재"))
    conn.execute(fi, ("f4", "RSK", "8-K", D(30), D(30), "8.01", "u", "[]", "호재"))                     # 14일 밖
    conn.execute("INSERT INTO events (ticker, date, kind, title, source, origin, created_at) VALUES ('RSK', ?, '주총', '연례 주총', 's', 'secfeed', 'x')", ((T + timedelta(days=9)).isoformat(),))
    conn.commit()
    fl = verdict.flow(conn, "RSK")
    assert fl["count"] == {"호재": 1, "희석": 2, "악재": 0, "중립": 0} and fl["verdict"] == "희석 공시 우세", fl
    assert fl["agm"][0].startswith("위임장(DEF 14A)") and fl["agm"][1].startswith("주총 결과(8-K 5.07)") and fl["agm"][2] == f"주총 예정 {(T + timedelta(days=9)).isoformat()}(D-9)", fl["agm"]
    assert verdict.flow(conn, "SAFE")["verdict"] == "조용함 — 14일 공시 없음"

# 워런트 목적 · 한 줄 종합
wp = verdict.warrant_purpose({"warrants": [{"price": 1.5, "qty": 2e6}, {"price": 9.0, "qty": 1e6}, {"price": 0.5, "qty": 1e6}]}, 1.0)
assert wp["need"] == 1.5 and abs(wp["need_pct"] - 50) < 1e-9 and "약 $3.00M" in wp["why"], wp
assert verdict.warrant_purpose({"warrants": [{"price": 0.5, "qty": 1e6}]}, 1.0) is None
p_soon = [{"title": "상장 유지", "urgency": "기한 있음", "need": 1.0, "need_pct": 40.0, "deadline": (T + timedelta(days=12)).isoformat(), "why": "x"}]
s1 = verdict.summary(p_soon, f, fl)
assert s1["label"].startswith("⚠️ 올릴 이유는 있지만 조달 가능성 큼") and "올릴 이유: 상장 유지(D-12) 목표 +40%" in s1["text"] and "현금조달 가능성 높음(런웨이 2.0개월)" in s1["text"] and "희석 공시 우세" in s1["text"], s1
assert verdict.summary(p_soon, g, fl)["label"].startswith("🎯") and verdict.summary([], f, fl)["label"].startswith("🔻") and verdict.summary([], g, fl)["label"] == "➖ 뚜렷한 방향 없음"

# 검증: 기록 → 30일 뒤 실제 조달
with closing(db.connect()) as conn:
    conn.execute(verdict.FIN_DDL)
    conn.execute("INSERT INTO fin_verdict VALUES (?, 'RSK', '높음', 9, '[]')", (D(45),))
    conn.execute("INSERT INTO fin_verdict VALUES (?, 'SAFE', '낮음', -2, '[]')", (D(45),))
    conn.execute("INSERT INTO fin_verdict VALUES (?, 'RSK', '높음', 9, '[]')", (D(5),))                 # 30일 안 지난 것은 아직 안 셈
    conn.commit()
    st = verdict.fin_stats(conn)
    assert st == {"높음": (1, 100), "낮음": (1, 0)}, st                                              # RSK 는 45일 전 판정 뒤 30일 안에 S-3·424B4·3.02
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "RSK", "exchange": "NASDAQ", "first_seen": db.utcnow_iso(), "last_seen": db.utcnow_iso(), "price": 1.0,
        "high_20d": 1.2, "low_20d": 0.9, "drawdown_pct": -20.0, "day_change_pct": 1.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 1e7, "atr14": 0.01,
        "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "ATM", "excluded": 0})
    conn.commit()
    logs = []
    assert verdict.log_daily(conn, out=logs.append) == 1 and "높음" in logs[0] and "30일 뒤 실제 조달 높음 100%(1건)" in logs[0], logs
assert json.loads(db.get_meta("fin_stats")["value"]) == {"높음": [1, 100], "낮음": [1, 0]}

# 🏢 종목 화면 맨 위 카드
db.save_report("RSK", {"ticker": "RSK", "generated_at": db.utcnow_iso(), "errors": {}, "runway": {"runway_months": 2.0, "cash": 1e6, "monthly_burn": 5e5, "cash_asof": D(30)},
                       "company": {"splits": []}, "financing": {"events": []}, "timeline": []})
from streamlit.testing.v1 import AppTest
os.environ["QUANT_TEST_PAGE"] = "lookup"; os.environ["DASH_PASSWORD"] = ""
import watch_ui
dfr = pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1e6}, index=idx); watch_ui.prices = lambda tk: {"RSK": dfr}   # 인터넷 없이
at = AppTest.from_file(os.path.join(os.environ["QS_ROOT"], "dashboard.py"), default_timeout=180); at.session_state["lookup_ticker"] = "RSK"
at.run(); assert not at.exception, [e.value for e in at.exception]
md = "\n".join(m.value for m in at.markdown)
assert "🧭" in md and "🎯 주가를 올려야 하는 이유" in md and "🏦 현금조달 가능성" in md and "📰 공시 흐름" in md and "현금조달 가능성 높음" in md and "희석 공시 우세" in md, md[:800]
assert "이 판정의 지난 성적" in md and "급등 2번 중 7일 안 조달 공시 1번" in md.replace("최근 3년 ", ""), md[:800]
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
