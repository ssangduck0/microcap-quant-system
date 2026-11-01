"""📄 종목 서랍(2026-11-01): 희석 수단 3단계 · 가격 사다리 · 풀리는 물량 · 하락 원인 후보 · 신호 기록 · 상태 변화 + 리포트 대화상자 탭 구성·서랍 표시자·CSS."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_PAGE", None); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, halts, shortdata, chartex, regsho, secbackfill, watch, drawer

db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
T = date.today()
D = lambda n: (T - timedelta(days=n)).isoformat()
now = db.utcnow_iso()
wd = [T - timedelta(days=i) for i in range(1, 60)]
wd = sorted(d for d in wd if d.weekday() < 5)[-30:]                 # 30 평일(오래된 순)
closes = [2.0] * 18 + [1.8, 1.7, 3.0, 4.9, 5.0, 5.6, 6.0, 5.0, 4.8, 4.7, 5.0, 3.4]   # 급등(1.7 → 6.0) 뒤 마지막 날 −32%
vols = [1e5] * 20 + [3e7, 8e7, 2e7, 2e6, 1e6, 1e6, 1e6, 1e6, 1e6, 3e6]
with closing(db.connect()) as conn:
    shortdata.ensure_tables(conn); chartex.ensure(conn); regsho.ensure_tables(conn)
    for d_ in secbackfill.DDL:
        conn.execute(d_)
    conn.execute("CREATE TABLE IF NOT EXISTS rs_events (ticker TEXT, date TEXT, ratio REAL, PRIMARY KEY (ticker, date))")
    db.upsert_snapshot(conn, {"date": wd[-1].isoformat(), "ticker": "CLX", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 3.4, "high_20d": 6.0, "low_20d": 1.7,
        "drawdown_pct": -40.0, "day_change_pct": -32.0, "volume_mult": 2.0, "buy_pressure": 45.0, "float_shares": 9e5, "atr14": 0.3, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "OFFERING", "excluded": 0})
    for d, c, v in zip(wd, closes, vols):
        conn.execute("INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?)", ("CLX", d.isoformat(), c, c * 1.05, c * 0.95, c, v))
    for d in wd:
        conn.execute("INSERT OR REPLACE INTO regsho_files (date, status) VALUES (?, 'ok')", (d.isoformat(),))
    for d in wd[-5:] + wd[5:10]:                                     # 앞 5일 등재 → 해제 → 마지막 5일 다시 등재
        conn.execute("INSERT OR IGNORE INTO regsho_list (date, symbol, name) VALUES (?, 'CLX', 'x')", (d.isoformat(),))
    for d, p, sh in ((D(47), 3.0, 3e4), (D(32), 45.5, 4.55e5), (D(17), 32.7, 3.27e5), (D(5), 3.0, 3.3e5)):   # 마지막: 잔고 주식은 그대로인데 % 만 ÷11(유통주식 기준 바뀜)
        conn.execute("INSERT INTO cx_short_interest (ticker, date, si_pct, short_shares, dtc, change_shares, change_pct, reported) VALUES ('CLX',?,?,?,3.3,1,1,1)", (d, p, sh))
    conn.execute("INSERT INTO ibkr_borrow (symbol,fee,rebate,available,avail_capped,as_of) VALUES ('CLX',808,0,5000,0,?)", ((T - timedelta(days=9)).strftime("%Y.%m.%d 02:37:07"),))
    fil = [("8-K", D(16), "1.01,2.03,9.01"), ("8-K", D(19), "3.01,9.01"), ("S-1/A", D(58), ""), ("S-1", D(83), ""), ("DEF 14C", D(65), ""), ("10-Q", D(79), "")]
    for i, (fm, d, it) in enumerate(fil):
        conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES (?, 'CLX', ?, ?, ?)", (f"a{i}", fm, d, it))
    conn.execute("INSERT INTO rs_events VALUES ('CLX', '2025-06-10', ?)", (1 / 15,))
    conn.execute("""CREATE TABLE IF NOT EXISTS pred_outcomes (source TEXT, date TEXT, ticker TEXT, ref TEXT, entry REAL, max_up REAL, max_down REAL, close_h REAL, bars INTEGER, status TEXT,
                    updated_at TEXT, PRIMARY KEY (source, date, ticker, ref))""")
    conn.execute("INSERT INTO pred_outcomes VALUES ('chart_h60', ?, 'CLX', '', 4.97, 20.7, -2.4, 12.0, 5, '성공', ?)", (D(5), now))
    conn.execute("INSERT INTO pred_outcomes VALUES ('cx_ftd_spike', ?, 'CLX', '', 5.0, 0.0, -34.0, NULL, 3, '대기', ?)", (D(3), now))
    # 물량 장부가 있는 종목(풀리는 물량)
    conn.execute("INSERT INTO overhang (ticker, kind, qty_m, price, status, ukey) VALUES ('WRT', '워런트', 2.0, 1.2, '유효', 'w1'), ('WRT', '워런트', 1.0, 1.5, '유효', 'w2'), ('WRT', 'CB', 0.5, 3.0, '유효', 'c1')")
    conn.execute("INSERT INTO daily_prices VALUES ('WRT', ?, 1.0, 1.0, 1.0, 1.0, 1e6)", (wd[-1].isoformat(),))
    db.upsert_snapshot(conn, {"date": wd[-1].isoformat(), "ticker": "WRT", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 1.0, "low_20d": 1.0,
        "drawdown_pct": 0.0, "day_change_pct": 0.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 2e8, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()

    sup = {s["name"].split("(")[0]: s for s in drawer.supply_status(conn, "CLX")}
    assert sup["공모·재판매 등록"]["state"] == "확인됨" and "효력(EFFECT) 미확인" in sup["공모·재판매 등록"]["detail"], sup
    assert sup["ATM"]["state"] == "1년 공시에 없음" and sup["부채·전환사채"]["state"] == "확인됨" and sup["워런트"]["state"] == "모름"
    assert sup["주식 병합"]["state"] == "이력 있음" and "1:15" in sup["주식 병합"]["detail"] and "동의서(14C)" in sup["주식 병합"]["detail"]
    assert sup["Baby shelf"]["state"] == "대상" and sup["상장 위험"]["state"] == "확인됨"
    w = {s["name"].split("(")[0]: s for s in drawer.supply_status(conn, "WRT")}
    assert w["워런트"]["state"] == "확인됨" and "2M주 @$1.2" in w["워런트"]["detail"] and w["부채·전환사채"]["state"] == "확인됨" and w["상장 위험"]["state"] == "6개월 공시에 없음"
    assert w["공모·재판매 등록"]["state"] == "1년 공시에 없음" and w["Baby shelf"]["state"] == "아님"

    lad = drawer.ladder(conn, "CLX")
    labs = [p["label"] for p in lad]
    assert labs[0] == "30일 최저" and "지금" in labs and "+30%" in labs and "+50%" in labs and labs[-1] == "30일 고점", labs
    assert [p["price"] for p in lad] == sorted(p["price"] for p in lad) and next(p for p in lad if p["label"] == "지금")["price"] == 3.4
    lw = drawer.ladder(conn, "WRT")
    assert any(p["label"] == "워런트 행사가" and p["price"] == 1.2 for p in lw) and any(p["label"] == "$1 상장 유지" for p in lw)
    ul = drawer.unlock(conn, "WRT", 1.0)
    assert [(u["label"], round(u["qty_m"], 2), u["n"]) for u in ul] == [("지금", 0.0, 0), ("+30%", 2.0, 1), ("+50%", 3.0, 2)], ul
    assert drawer.unlock(conn, "CLX", 3.4) is None                                                   # 장부 없음

    cz = drawer.causes(conn, "CLX")
    titles = [c["title"] for c in cz]
    assert titles[0].startswith("급등 뒤 되돌림") and "조달 수단 대기·실행" in titles and "부채·사모 발행" in titles and "결제 실패 지속" in titles and "상장 기준 미달" in titles, titles
    assert "$1.70 →" in cz[0]["why"] and "$6.30(+271%)" in cz[0]["why"], cz[0]
    assert drawer.causes(conn, "WRT") == []                                                           # 안 빠진 종목은 후보 없음

    sg = drawer.signals(conn, "CLX")
    assert [s["source"] for s in sg] == ["cx_ftd_spike", "chart_h60"] and sg[1]["name"].startswith("📐") and sg[1]["status"] == "성공"

    hs = drawer.history(conn, "CLX")
    tx = " | ".join(h["text"] for h in hs)
    assert "Reg SHO 등재" in tx and "Reg SHO 해제" in tx and "공식 잔고 3.0% → 45.5%(결제일 기준 · 잔고 주식 3.0만 → 45.5만주)" in tx and "공식 잔고 45.5% → 32.7%" in tx, tx
    assert "유통주식 기준 바뀜(1.0M → 11.0M주" in tx and "잔고 % 32.7 → 3.0 는 비교 불가 · 잔고 주식 32.7만 → 33.0만주" in tx and "공식 잔고 32.7% → 3.0%" not in tx, tx   # 2026-11-01
    assert "8-K 상장 기준 미달 통지" in tx and "8-K 부채 · 중요 계약" in tx and "S-1/A 조달 서류" in tx and "-32%" in tx and "거래량 평소의" in tx
    assert [h["date"] for h in hs] == sorted((h["date"] for h in hs), reverse=True)

    hd = drawer.headline(conn, "CLX")
    assert hd["price"] == 3.4 and round(hd["chg"]) == -32 and hd["si"] == 3.0 and round(hd["si_float"]) == 11_000_000 and hd["sho"] == 5 and hd["n_sig"] == 2 and hd["listing"] and hd["fee"] == 808
    assert drawer.edgar_url("clx", "S-1/A").endswith("CIK=CLX&type=S-1&dateb=&owner=include&count=40")

# 리포트 대화상자: 서랍 표시자 · 탭 순서 · 새 탭 내용
from streamlit.testing.v1 import AppTest
app = os.path.join(tmp, "dr_app.py")
with open(app, "w", encoding="utf-8") as f:
    f.write(f"import sys; sys.path.insert(0, {os.environ['QS_ROOT']!r})\nimport ui_kit, report_dialog\nui_kit.inject()\nreport_dialog.render('CLX', __import__('os').environ.get('DR_FOCUS'))\n")
at = AppTest.from_file(app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
assert [x.label for x in at.tabs][:8] == ["📌 한눈에", "🧨 숏·수급", "🏦 공급·근거", "🏆 성과·이력", "⚡ 지금", "🤖 AI 요약", "🔀 교차검증", "🧾 덕구 스캔"]
html = "\n".join(m.value for m in at.markdown)
assert 'class="qk-drawer"' in html and "Reg SHO 5일째" in html and "상장 기준 미달 통지" in html and "급등 뒤 되돌림" in html
assert "공식 공매도 잔고" in html and "32.7%" in html and "하락 원인 후보" in html and "희석 수단" in html
assert "확인됨 / 공시에 없음 / 모름" in html and "qk-ladder" in html and "30일 고점" in html and "원문 목록" in html          # 🏦 공급·근거
assert "이 종목에 난 우리 신호와 결과" in html and "60분봉" in html and "상태 변화 이력" in html and "Reg SHO 해제" in html       # 🏆 성과·이력
assert "nasdaqth" in html and "거래소 공식 목록" in html                                                                      # 🧨 숏·수급
os.environ["DR_FOCUS"] = "short"
at = AppTest.from_file(app, default_timeout=120).run()
assert not at.exception and [x.label for x in at.tabs][:2] == ["🧨 숏·수급", "📌 한눈에"]
import ui_kit
assert '[role="dialog"]:has(.qk-drawer)' in ui_kit.CSS and "right: 0" in ui_kit.CSS and "background: inherit" in ui_kit.CSS
print("ALL OK")
