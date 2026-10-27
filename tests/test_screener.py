import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, screener, secbackfill, aipick
db.init_db()
T = date.today()
d = lambda n: (T - timedelta(days=n)).isoformat()
idx = pd.bdate_range(start=pd.Timestamp(T) - pd.Timedelta(days=400), periods=260)
c = np.r_[np.linspace(0.6, 0.15, 240), [0.15, 0.148, 0.145, 0.14, 0.138, 0.137, 0.135, 0.132, 0.13, 0.127, 0.12, 0.12, 0.122, 0.12, 0.13, 0.135, 0.13, 0.127, 0.125, 0.12]]
with closing(db.connect()) as conn:
    db.upsert_daily_prices(conn, "SURG", pd.DataFrame({"Open": c, "High": c * 1.04, "Low": c * 0.96, "Close": c, "Volume": np.full(260, 3e6)}, index=idx))
    for ddl in secbackfill.DDL:
        conn.execute(ddl)
    now = db.utcnow_iso()
    db.upsert_snapshot(conn, {"date": idx[-1].strftime("%Y-%m-%d"), "ticker": "SURG", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.12, "high_20d": 0.15, "low_20d": 0.11,
        "drawdown_pct": -20.0, "day_change_pct": -5.7, "volume_mult": 1.0, "buy_pressure": 40.0, "float_shares": 52.9e6, "atr14": 0.01, "quant_score": 5.0, "quant_detail": "{}",
        "pump_score": 0.0, "pump_detail": '{"checks":[]}', "dilution_status": "ATM", "excluded": 1})
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('s1','SURG','424B5',?, '')", (d(20),))
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('s2','SURG','8-K',?, '3.01,9.01')", (d(70),))     # 과거 이력 → 한글 항목명
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('s3','SURG','4',?, '')", (d(30),))                # 내부자 서류는 건너뜀
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('f1','SURG','8-K',?, '8.01')", (d(45),))          # sec_feed 와 같은 공시 → 한 번만
    conn.execute("CREATE TABLE IF NOT EXISTS sec_feed (accession TEXT PRIMARY KEY, ticker TEXT, cik INTEGER, form TEXT, company TEXT, filed TEXT, updated TEXT, items TEXT, url TEXT, tags TEXT, score INTEGER, sentiment TEXT, enriched INTEGER, created_at TEXT, lead TEXT, summary_ko TEXT)")
    conn.execute("INSERT INTO sec_feed (accession, ticker, form, filed, updated, items, tags, sentiment, summary_ko) VALUES ('f1','SURG','8-K',?,?,'8.01','[\"자산매각\"]','호재','자산 매각 완료')", (d(45), d(45)))
    conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, date TEXT, kind TEXT, title TEXT, source TEXT, origin TEXT, created_at TEXT)")
    conn.execute("INSERT INTO events (ticker, date, kind, title) VALUES ('SURG', ?, '상장유지 기한', '$1 호가 회복 기한')", (d(-40),))
    conn.execute("CREATE TABLE IF NOT EXISTS ext_hilo (date TEXT, ticker TEXT, night_high REAL, pre_high REAL, reg_high REAL, post_high REAL, day_low REAL, updated TEXT, PRIMARY KEY (date, ticker))")
    conn.execute("INSERT INTO ext_hilo VALUES (?, 'SURG', NULL, NULL, 0.124, 0.121, 0.112, '')", (idx[-1].strftime("%Y-%m-%d"),))
    conn.commit()

# 야후 가짜: 실적 일정·컨센서스·직전 분기
class YF:
    calendar = {"Earnings Date": [date(T.year, 11, 15)], "Revenue Average": 18.7e6, "Revenue Low": 18.0e6, "Revenue High": 19.5e6, "Earnings Average": -0.02}
    quarterly_income_stmt = pd.DataFrame({pd.Timestamp("2026-06-30"): {"Total Revenue": 16.21e6, "Diluted EPS": 0.05}})
with closing(db.connect()) as conn:
    e = screener.earnings("SURG", conn, YF())
    assert e["next_date"] == f"{T.year}-11-15" and e["rev_avg"] == 18.7e6 and e["last_rev"] == 16.21e6 and e["last_eps"] == 0.05 and e["last_q"] == "2026-06-30"
    class Boom:
        @property
        def calendar(self): raise RuntimeError("no network")
    assert screener.earnings("SURG", conn, Boom())["rev_avg"] == 18.7e6                              # 3일 안이면 저장본
    assert screener.fetch_earnings("X", Boom())["next_date"] is None                                  # 실패해도 조용히
    g = screener.gather(conn, "SURG", YF())
    assert any("스캐너 제외" in w and "ATM" in w for w in g["exclusion"]) and any("③ 희석" in w for w in g["exclusion"]) and any("승률 점수" in w for w in g["exclusion"])
    lv = g["levels"]
    assert abs(lv["last"] - 0.12) < 1e-9 and lv["day_box"][0] < 0.12 < lv["day_box"][1] and lv["resistance"] >= 0.135 and lv["support"][0] < lv["support"][1] <= lv["day_box"][0] * 1.0001
    assert abs(lv["resistance1"] - 0.15 * 1.04) < 1e-9 and lv["resistance1"] < lv["resistance"]        # 1차 = 20일 고가, 2차 = 60일 최고 종가(더 높음)
    assert lv["danger"] < lv["support"][0] and lv["after_high"] == 0.121 and lv["vs_month_start"] and 0 <= lv["pos_in_box"] <= 100
    ev = g["events"]
    assert any(x["kind"] == "8-K" and x["text"] == "자산 매각 완료" and "d1" in x and "d5" in x for x in ev) and any(x["kind"] == "상장유지 기한" for x in ev)
    assert any(x["kind"] == "424B5" and x["text"].startswith("공모 가격 확정") for x in ev) and any(x["kind"] == "8-K" and x["text"] == "상장유지 통지" for x in ev)   # sec_hist 합침
    assert not any(x["kind"] == "4" for x in ev) and sum(1 for x in ev if x["date"] == d(45)) == 1                                                       # Form 4 제외 · 중복 없음
    assert screener.hist_label("8-K", "2.02, 9.01") == "실적 발표" and screener.hist_label("SC 13G/A", "") is None and screener.hist_label("S-3", "") == "선반 등록(S-3)"
    assert g["mcap"] and abs(g["mcap"] - 0.12 * 52.9e6) < 1 and g["in_universe"]

# 카드 만들기(가짜 Claude) → 저장 · 성과 공표 기록 · 같은 날 교체
ans = {"headline": "ATM 증자 활성 — 상승 눌림 위험", "check_points": ["3분기 매출 $18.7M 상회 여부", "병합 비율 공시", "ATM 매도 여부"],
       "scenarios": [{"name": "상회", "condition": "매출 > $18.7M", "path": "$0.127 갭 회복 후 $0.15 재시험"}, {"name": "하회", "condition": "매출 정체", "path": "$0.112 이탈, $0.10 시험"}],
       "rr": "1:0.9", "stance": "회피", "why": "ATM 이 열려 있어 오르면 팔림"}
class R:
    status_code = 200
    def json(self): return {"content": [{"type": "text", "text": json.dumps(ans, ensure_ascii=False)}], "usage": {"input_tokens": 3000, "output_tokens": 500}}
calls = []
def post(url, headers=None, json=None, timeout=None):
    calls.append(json); return R()
import screener as sc
_g = sc.gather
sc.gather = lambda conn, t, yf_ticker=None: _g(conn, t, YF())
card = sc.build("SURG", post=post, source="래빗스탁 커뮤니티")
assert card["ai"]["stance"] == "회피" and card["ai"]["cost_usd"] > 0 and calls[0]["output_config"] == {"effort": "medium"} and "희석" in calls[0]["system"]
assert "ATM" in calls[0]["messages"][0]["content"] and "18700000" in calls[0]["messages"][0]["content"] and "resistance_20d" in calls[0]["messages"][0]["content"]
with closing(db.connect()) as conn:
    assert sc.latest_card(conn, "SURG")["source"] == "래빗스탁 커뮤니티"
    assert conn.execute("SELECT COUNT(*) FROM screener_sig").fetchone()[0] == 1
sc.build("SURG", post=post, source="직접")
with closing(db.connect()) as conn:
    assert conn.execute("SELECT COUNT(*) FROM screener_cards").fetchone()[0] == 1 and conn.execute("SELECT COUNT(*) FROM screener_sig").fetchone()[0] == 1
import scoreboard as sb
with closing(db.connect()) as conn:
    col = sb.collect(conn)
r = col[col["source"] == "scr"]
assert len(r) == 1 and r.iloc[0]["ticker"] == "SURG" and r.iloc[0]["target"] == 30.0 and r.iloc[0]["horizon"] == 20

# 화면
from streamlit.testing.v1 import AppTest
def _app():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import screener_ui
    screener_ui.render("SURG")
at = AppTest.from_function(_app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
assert any("ATM" in e.value for e in at.error) and any("③ 희석" in e.value for e in at.error)
md = " ".join(m.value for m in at.markdown) + " " + " ".join(df_.value.to_string() for df_ in at.dataframe)
assert "ATM 증자 활성" in md and "상회" in md and "1차 저항" in md and "2차 저항" in md and "상장유지 통지" in md and "11-15" in md, md[:600]
print("ALL OK")
