import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, aipick, config, watch
db.init_db()
watch.scanner_priority = lambda: ["WWW"]                          # 워치리스트 종목 하나
T = date.today()
idx = pd.bdate_range(start=pd.Timestamp(T) - pd.Timedelta(days=130), periods=80)
with closing(db.connect()) as conn:
    for t, base in (("AAA", 1.0), ("BBB", 0.5), ("CCC", 2.0), ("WWW", 3.0)):
        c = base * (1 + np.sin(np.arange(80) / 5) * 0.1)
        db.upsert_daily_prices(conn, t, pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": np.full(80, 2e5)}, index=idx))
    conn.commit()
scan = {"pass": [{"ticker": "AAA", "status": "유력", "weak": False, "target_name": "$1 상장유지", "target": 1.0, "pct": 45.0, "imm_days": 12, "pressure": 7.0, "runway": 6.0, "price": 0.7,
                  "why": ["상장유지 기한", "증자 전"]},
                 {"ticker": "BBB", "status": "가능", "weak": True, "target_name": "워런트", "target": 0.8, "pct": 60.0, "imm_days": 40, "pressure": 4.0, "runway": None, "price": 0.5, "why": []},
                 {"ticker": "CCC", "status": "대기", "weak": False, "target_name": "-", "target": None, "pct": 35.0, "imm_days": None, "pressure": 2.0, "runway": 12.0, "price": 2.0, "why": "x"}]}

# 대상: PICK 우선(유력→가능→대기) + 종합 순위 상위로 채움(워치리스트는 안 넣음)
RK = pd.DataFrame([{"ticker": "WWW", "score": 61.2, "urgency": 1, "parts": {"매집": 2, "스퀴즈": 1}}, {"ticker": "AAA", "score": 55.0, "urgency": 1, "parts": {"PICK": 3}}])
aipick_rank = RK
_orig_cands = aipick.candidates
aipick.candidates = lambda conn, scan=None, limit=None, ranking=None: _orig_cands(conn, scan, limit, RK if ranking is None else ranking)
with closing(db.connect()) as conn:
    cs = aipick.candidates(conn, scan)
    assert [c["ticker"] for c in cs] == ["AAA", "BBB", "CCC", "WWW"] and cs[-1]["src"] == "순위" and cs[0]["rank"]["pos"] == 2
    assert [c["ticker"] for c in aipick.candidates(conn, scan, limit=3)] == ["AAA", "BBB", "CCC"]
    for ddl in ("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, date TEXT, kind TEXT, title TEXT, source TEXT, origin TEXT, created_at TEXT)",
                "CREATE TABLE IF NOT EXISTS fs_deals (accession TEXT PRIMARY KEY, ticker TEXT, filed TEXT, form TEXT, kind TEXT, proceeds REAL, unit_price REAL, shares REAL, pfw REAL, warrants TEXT, agent TEXT, resale INTEGER, source TEXT, url TEXT, parsed_at TEXT)",
                "CREATE TABLE IF NOT EXISTS fs_deal_paths (accession TEXT PRIMARY KEY, ticker TEXT, kind TEXT, filed TEXT, avail TEXT, avail_note TEXT, base REAL, discount REAL, ret5 REAL, ret20 REAL, ret60 REAL, min60 REAL, max60 REAL, bars INTEGER, done INTEGER, updated TEXT)",
                "CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY, ticker TEXT, exchange TEXT, title TEXT, summary TEXT, published TEXT, link TEXT, feed TEXT, tags TEXT, sentiment TEXT, fetched TEXT)",
                "CREATE TABLE IF NOT EXISTS insider_tx (accession TEXT, seq INTEGER, ticker TEXT, owner TEXT, title TEXT, date TEXT, code TEXT, shares REAL, price REAL, value REAL, after_shares REAL, url TEXT)",
                "CREATE TABLE IF NOT EXISTS short_interest (ticker TEXT, date TEXT, shares_short REAL, prior REAL, si_pct REAL, dtc REAL, si_date TEXT, float_sh REAL)",
                "CREATE TABLE IF NOT EXISTS rs_events (ticker TEXT, date TEXT, ratio REAL, split_close REAL)",
                "CREATE TABLE IF NOT EXISTS s3_tier_signals (date TEXT, ticker TEXT, price REAL, tier INTEGER, rsi REAL, note TEXT, PRIMARY KEY (date, ticker))"):
        conn.execute(ddl)
    d = lambda n: (T + timedelta(days=n)).isoformat()
    conn.execute("INSERT INTO events (ticker, date, kind, title) VALUES ('AAA', ?, '주총', '병합 승인 투표')", (d(6),))
    conn.execute("INSERT INTO events (ticker, date, kind, title) VALUES ('AAA', ?, '실적', '먼 일정')", (d(60),))     # 30일 밖은 뺌
    conn.execute("INSERT INTO fs_deals (accession, ticker, filed, kind, proceeds, unit_price, warrants, resale) VALUES ('a1','AAA',?, 'PIPE', 5000000, 0.5, '[{\"strike\":0.6}]', 1)", (d(-20),))
    conn.execute("INSERT INTO fs_deal_paths (accession, ticker, kind, avail) VALUES ('a1','AAA','PIPE',?)", (d(10),))
    conn.execute("INSERT INTO news (id, ticker, title, published, sentiment) VALUES ('n1','AAA','FDA fast track granted',?, '호재')", (d(-1),))
    conn.execute("INSERT INTO insider_tx (accession, seq, ticker, date, code, value) VALUES ('i1',1,'AAA',?, 'P', 25000)", (d(-5),))
    conn.execute("INSERT INTO short_interest (ticker, date, si_pct, dtc, float_sh, si_date) VALUES ('AAA', ?, 22.5, 3.1, 8000000, ?)", (d(-3), d(-10)))
    conn.execute("INSERT INTO rs_events (ticker, date, ratio) VALUES ('AAA', ?, 10)", (d(-200),))
    conn.execute("INSERT INTO s3_tier_signals VALUES (?, 'AAA', 0.7, 1, 18, 'x')", (d(-2),))
    conn.commit()
    b = aipick.brief(conn, cs[0], {"AAA": 12})
    assert b["pick"]["status"] == "유력" and b["px"]["last"] > 0 and "rsi" in b["px"] and b["regsho_days"] == 12 and "상장유지 기한" in b["pick"]["why"]
    assert len(b["events"]) == 1 and "D+6" in b["events"][0] and "병합 승인" in b["events"][0], b["events"]
    assert "$5.0M" in b["deals"][0] and "@$0.5" in b["deals"][0] and "재판매" in b["deals"][0] and "매도 가능" in b["sell_open"][0]
    assert "FDA" in b["news"][0] and b["insider_buy"].startswith("1건") and b["short"]["si_pct"] == 22.5 and b["short"]["float_m"] == 8.0
    assert b["reverse_splits_2y"].startswith("1회") and b["s3_tier"] == 1 and b["rank"]["score"] == 55.0
    assert "runway" not in aipick.brief(conn, cs[1])["pick"] and "events" not in aipick.brief(conn, cs[1])          # 없는 값은 빼서 토큰 절약

# 해석: 코드 블록·이상한 값·중복·지어낸 티커
ans = {"picks": [{"ticker": "BBB", "rank": 2, "timing": "다음 주", "confidence": "중간", "reason": "워런트 근처", "risk": "희석"},
                 {"ticker": "AAA", "rank": 1, "timing": "이번 주", "confidence": "높음", "reason": "상장유지 기한 임박", "risk": "ATM"},
                 {"ticker": "aaa", "rank": 3, "timing": "x", "confidence": "y", "reason": "", "risk": ""},
                 {"ticker": "FAKE", "rank": 4, "timing": "진행 중", "confidence": "높음", "reason": "지어냄", "risk": ""}]}
p = aipick.parse("```json\n" + json.dumps(ans, ensure_ascii=False) + "\n```")
assert [x["ticker"] for x in p] == ["AAA", "BBB", "FAKE"] and p[0]["confidence"] == "높음"
p2 = aipick.parse(json.dumps({"picks": [{"ticker": "ZZ", "timing": "언젠가", "confidence": "?"}]}))
assert p2[0]["timing"] == "나중" and p2[0]["confidence"] == "낮음" and p2[0]["rank"] == 1

# 🗓 판단 전 공시 일정 스캔: 종목당 7일에 한 번 · 실패해도 계속
import watch as _w
scanned = []
def _fake_scan(client, t, days=365, max_docs=12):
    scanned.append(t)
    if t == "BBB":
        raise RuntimeError("SEC 오류")
_w.scan_ticker = _fake_scan
assert aipick.refresh_events(["AAA", "BBB"], out=lambda *_: None, client=object()) == 1 and scanned == ["AAA", "BBB"]
assert aipick.refresh_events(["AAA", "BBB"], out=lambda *_: None, client=object()) == 0 and scanned == ["AAA", "BBB"]   # 7일 안엔 다시 안 함
aipick.refresh_events = lambda tickers, out=print, client=None, days_gap=7: 0                                             # 아래 판단 시험에선 생략

# 실행(가짜 API) · 지어낸 티커 버림 · 비용 누적 · 하루 한 번 · 성과 공표 기록
calls = []
class R:
    status_code = 200
    def json(self):
        return {"content": [{"type": "text", "text": json.dumps(ans, ensure_ascii=False)}], "usage": {"input_tokens": 26000, "output_tokens": 5000}}
def post(url, headers=None, json=None, timeout=None):
    calls.append(json); return R()
r = aipick.run(today=T, scan=scan, post=post, out=lambda *_: None)
assert r["ok"] and r["n"] == 2, r
assert calls[0]["model"] == config.AI_PICK_MODEL and "AAA" in calls[0]["messages"][0]["content"] and "JSON" in calls[0]["system"] and calls[0]["max_tokens"] == 16000 and calls[0]["output_config"] == {"effort": "medium"}
assert "진행 중인 강한 수급" in calls[0]["system"]
assert abs(r["cost_usd"] - (26000 / 1e6 * 2 + 5000 / 1e6 * 10)) < 1e-9 and abs(aipick.spent_usd() - r["cost_usd"]) < 1e-9
with closing(db.connect()) as conn:
    cur, prev = aipick.latest(conn)
    assert [x["ticker"] for x in cur] == ["AAA", "BBB"] and cur[0]["price"] > 0 and prev == {}
    assert conn.execute("SELECT COUNT(*) FROM ai_pick_sig").fetchone()[0] == 2
assert aipick.run(today=T, scan=scan, post=post, out=lambda *_: None)["msg"].startswith("오늘 이미") and len(calls) == 1
# 다음 날: 순위 변동 · 같은 종목은 10일 안에 다시 기록 안 함
r2 = aipick.run(today=T + timedelta(days=1), scan=scan, post=post, out=lambda *_: None)
with closing(db.connect()) as conn:
    cur, prev = aipick.latest(conn)
    assert prev == {"AAA": 1, "BBB": 2} and conn.execute("SELECT COUNT(*) FROM ai_pick_sig").fetchone()[0] == 2

# 같은 날 다시 판단(force): 그날 기록은 새 판단으로 교체(섞이지 않음)
ans2 = {"picks": [{"ticker": "CCC", "rank": 1, "timing": "진행 중", "confidence": "높음", "reason": "r", "risk": "k"}]}
class R2(R):
    def json(self):
        return {"content": [{"type": "text", "text": json.dumps(ans2, ensure_ascii=False)}], "usage": {"input_tokens": 100, "output_tokens": 10}}
d1 = (T + timedelta(days=1)).isoformat()
aipick.run(today=T + timedelta(days=1), scan=scan, post=lambda *a, **k: (calls.append(1), R2())[1], force=True, out=lambda *_: None)
with closing(db.connect()) as conn:
    assert [r[0] for r in conn.execute("SELECT ticker FROM ai_pick_sig WHERE date=?", (d1,))] == ["CCC"]
    assert [r[0] for r in conn.execute("SELECT ticker FROM ai_pick WHERE date=?", (d1,))] == ["CCC"]

# 예산: 남은 예산보다 예상 비용이 크면 호출하지 않음
config.AI_MONTHLY_BUDGET_KRW = aipick.spent_usd() * aipick.FX + 1
r3 = aipick.run(today=T + timedelta(days=2), scan=scan, post=post, out=lambda *_: None)
assert not r3["ok"] and "예산" in r3["msg"] and len(calls) == 3
config.AI_MONTHLY_BUDGET_KRW = 10000.0
config.AI_PICK_ENABLED = False
assert aipick.run(today=T + timedelta(days=3), scan=scan, post=post, out=lambda *_: None)["msg"].startswith("AI PICK 꺼짐")
config.AI_PICK_ENABLED = True

# 🏆 성과 공표: 확신별 출처 · 20거래일 안 +30%
import scoreboard as sb
with closing(db.connect()) as conn:
    col = sb.collect(conn)
hi = col[col["source"] == "ai_hi"]
assert set(hi["ticker"]) == {"AAA", "CCC"} and hi[hi["ticker"] == "AAA"].iloc[0]["horizon"] == 20 and hi.iloc[0]["target"] == 30.0 and "1위" in hi.iloc[0]["note"]
assert len(col[col["source"] == "ai_mid"]) == 1

# 화면
from streamlit.testing.v1 import AppTest
def _app():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import pick30_ui
    pick30_ui.render_ai()
at = AppTest.from_function(_app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
md = " ".join(m.value for m in at.markdown)
assert "CCC" in md and "확신 높음" in md and "진행 중" in md, md[:500]                       # 가장 최근 판단(같은 날 다시 판단한 것)
assert "🆕" in md                                                                             # 직전 판단(AAA·BBB)에 없던 종목
assert "이번 달 AI 비용" in md and any(b.label.startswith("🔄 지금 다시 판단") for b in at.button)
print("ALL OK")
