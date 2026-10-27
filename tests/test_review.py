import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🤖 Claude 복기: 재료 모으기(놓친 펌핑·실패 신호·공시/뉴스) · 프롬프트 · 답 해석(분류표 밖 → 알 수 없음) · 저장(ai_cat·규칙 후보) · 주 1회 문턱 · 예산 부족 건너뜀 · 스위치 · 화면(가짜 Claude)."""
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"; os.environ["ANTHROPIC_API_KEY"] = ""
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, autopsy, review, secfeed, news, halts, aipick, config
db.init_db(); halts.fetch = lambda *a, **k: []
T = date.today(); D = T.isoformat(); D3 = (T - timedelta(days=3)).isoformat()
with closing(db.connect()) as conn:
    autopsy.ensure(conn); review.ensure(conn); secfeed.ensure_tables(conn); conn.execute(news.DDL)
    feats = json.dumps({"bucket": "$1~5", "dvol20": 1234567.891, "dd20": -40.0, "rsi": 28.123, "dil": "ATM", "zone": "발 아래", "regime": "yellow", "sec7": 1})
    conn.execute("INSERT INTO pump_autopsy (date, ticker, pump_pct, hi_pct, session, prev_close, volume, caught, caught_by, held, features, catalyst, created_at) VALUES (?,'MISS1',48.0,52.0,'reg',1.0,5e6,0,'[]','[]',?,'공시 8-K 호재 계약','x')", (D, feats))
    conn.execute("INSERT INTO pump_autopsy (date, ticker, pump_pct, hi_pct, session, prev_close, volume, caught, caught_by, held, features, catalyst, created_at) VALUES (?,'MISS2',31.0,90.0,'pre',1.0,5e6,0,'[]','[]',?,'공시·뉴스 없음','x')", (D3, feats))
    conn.execute("INSERT INTO pump_autopsy (date, ticker, pump_pct, hi_pct, session, prev_close, volume, caught, caught_by, held, features, catalyst, created_at) VALUES (?,'HIT1',60.0,70.0,'reg',1.0,5e6,1,'[\"📐\"]','[]',?,'','x')", (D, feats))          # 잡은 건 복기 대상 아님
    conn.execute("INSERT INTO signal_autopsy (source, date, ticker, status, entry, max_up, max_down, features, tags, created_at) VALUES ('score',?,'FL1','실패',2.0,3.0,-30.0,?,'[\"dilution\",\"nocat\"]','x')", (D3, feats))
    conn.execute("INSERT INTO signal_autopsy (source, date, ticker, status, entry, max_up, max_down, features, tags, created_at) VALUES ('after',?,'FL2','실패',1.0,NULL,NULL,?,'[\"other\"]','x')", (D, feats))
    conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) VALUES ('a1','MISS1',1,'8-K','c',?,?,'1.01','','[\"계약\"]',2,'호재',1,'x')", (D, D))
    conn.execute("INSERT INTO news (id, ticker, exchange, title, summary, published, link, feed, tags, sentiment, fetched) VALUES ('n1','FL1','NASDAQ','Company prices offering','s',?, 'l','f','[]','악재','x')", ((T - timedelta(days=1)).isoformat() + "T10:00:00",))
    conn.commit()
    g = review.gather(conn, days=7)
    assert [m["ticker"] for m in g["miss"]] == ["MISS2", "MISS1"] and [m["ticker"] for m in g["fail"]] == ["FL2", "FL1"], g   # 놓침은 고가 큰 순 · 실패는 최근 순
    m1 = [m for m in g["miss"] if m["ticker"] == "MISS1"][0]
    assert m1["features_prev_day"]["dvol20"] == 1234567.89 and m1["features_prev_day"]["dil"] == "ATM" and any("공시 8-K 호재 계약" in d for d in m1["docs"])
    f1 = [m for m in g["fail"] if m["ticker"] == "FL1"][0]
    assert "🧾 희석 출회(424B·S-1·ATM)" in f1["rule_tags"] and any("뉴스 악재 Company prices offering" in d for d in f1["docs_after"])
    p = review.build_prompt(g); assert "MISS1" in p and "FL2" in p and "rule_tags" in p
    # 답 해석: 분류표 밖 → 알 수 없음 · 규칙 최대 5개 · 코드블록 감싸도 됨
    ans = {"miss": [{"ticker": "miss1", "date": D, "cat": "계약·파트너십", "why": "8-K 계약 공시 당일 급등"}, {"ticker": "MISS2", "date": D3, "cat": "외계인", "why": "?"}],
           "fail": [{"source": "score", "date": D3, "ticker": "FL1", "cat": "희석 출회", "why": "오퍼링 뉴스"}, {"source": "after", "date": D, "ticker": "FL2", "cat": "거래량 부족", "why": "추정"}],
           "rules": [{"name": f"규칙{i}", "condition": f"조건{i}", "expect": "+30%", "check": "타임머신"} for i in range(7)], "summary": "계약 공시형 펌핑을 놓침"}
    parsed = review.parse("```json\n" + json.dumps(ans, ensure_ascii=False) + "\n```")
    assert parsed["miss"][0]["ticker"] == "MISS1" and parsed["miss"][0]["cat"] == "계약·파트너십" and parsed["miss"][1]["cat"] == "알 수 없음" and len(parsed["rules"]) == 5
    try:
        review.parse("답이 없어요"); assert False
    except ValueError:
        pass
    # 실행(가짜 Claude): 저장 · ai_cat · 규칙 후보 · 비용 기록
    calls = []
    def fake(prompt, system):
        calls.append(prompt); return json.dumps(ans, ensure_ascii=False), 3000, 800
    spent0 = aipick.spent_usd()
    res = review.run(conn, days=7, out=lambda *a: None, call=fake)
    assert res["status"] == "ok" and res["n_miss"] == 2 and res["n_fail"] == 2 and len(res["rules"]) == 5 and res["cost_krw"] > 0, res
    assert aipick.spent_usd() > spent0 and len(calls) == 1
    assert conn.execute("SELECT ai_cat FROM pump_autopsy WHERE ticker='MISS1'").fetchone()[0] == "계약·파트너십"
    assert tuple(conn.execute("SELECT ai_cat, ai_note FROM signal_autopsy WHERE ticker='FL1'").fetchone()) == ("희석 출회", "오퍼링 뉴스")
    assert conn.execute("SELECT ai_cat FROM pump_autopsy WHERE ticker='HIT1'").fetchone()[0] is None
    last = review.latest(conn); assert last["n_miss"] == 2 and last["rules"][0]["name"] == "규칙0" and "계약 공시형" in last["summary"]
    cc = review.cat_counts(conn); assert ("계약·파트너십", 1) in cc["miss"] and ("희석 출회", 1) in cc["fail"]
    # 주 1회: 방금 돌렸으니 안 돎 · force 면 돌지만 새 항목이 없어 empty
    assert review.run(conn, call=fake)["status"] == "not_due" and not review.due(conn)
    assert review.run(conn, call=fake, force=True)["status"] == "empty" and len(calls) == 1
    # 새 항목 + 예산 부족 → 건너뜀 · 스위치 끔 → off
    conn.execute("INSERT INTO pump_autopsy (date, ticker, pump_pct, hi_pct, session, prev_close, volume, caught, caught_by, held, features, catalyst, created_at) VALUES (?,'MISS3',35.0,40.0,'reg',1.0,5e6,0,'[]','[]',?,'','x')", (D, feats)); conn.commit()
    old = config.AI_MONTHLY_BUDGET_KRW; config.AI_MONTHLY_BUDGET_KRW = 0.0
    assert review.run(conn, call=fake, force=True)["status"] == "budget" and len(calls) == 1
    config.AI_MONTHLY_BUDGET_KRW = old
    config.AI_REVIEW_ENABLED = False; assert review.run(conn, call=fake)["status"] == "off"; config.AI_REVIEW_ENABLED = True
    # 화면(스냅샷 한 줄 필요)
    _now = db.utcnow_iso()
    db.upsert_snapshot(conn, {"date": D, "ticker": "MISS1", "exchange": "NASDAQ", "first_seen": _now, "last_seen": _now, "price": 1.5, "high_20d": 1.5, "low_20d": 0.9, "drawdown_pct": -5.0,
        "day_change_pct": 50.0, "volume_mult": 12.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.05, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
        "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "autopsy"
at = AppTest.from_file(APP, default_timeout=240).run(); assert not at.exception, [e.value for e in at.exception]
dfs = [d.value for d in at.dataframe]
assert any("조건" in d.columns and "검증 방법" in d.columns for d in dfs), [list(d.columns) for d in dfs]           # 규칙 후보 표
assert any("🤖 분류" in d.columns and (d["🤖 분류"] == "계약·파트너십").any() for d in dfs)                            # 놓친 펌핑 표에 AI 분류 열
md = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
assert "Claude 복기" in md and "계약 공시형 펌핑을 놓침" in md
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
