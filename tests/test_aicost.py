"""🤖 AI 비용 표(2026-10-28): 기능별 지출 기록(ai_spend) · 종목 AI 요약(ai_reports) 합산 · 월말 예상 · 관리 모드 섹션 — 인터넷 없이."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import db, config, aipick, aisummary, halts
db.init_db(); halts.fetch = lambda *a, **k: []
T = date.today(); M = T.strftime("%Y-%m")
config.AI_MONTHLY_BUDGET_KRW = 50000.0

assert aipick.spend_rows() == [] and aipick.spend_days() == {}
s0 = aipick.spend_summary(); assert s0["spent_krw"] == 0 and s0["left_krw"] == 50000 and s0["top"] is None
# 기록: 공시분석 2건 · AI PICK 1건 · 모르는 꼬리표는 '기타'
aipick._add_spend(0.15, "forensic", 30000, 15000); aipick._add_spend(0.10, "forensic", 20000, 10000)
aipick._add_spend(0.05, "pick", 10000, 3000); aipick._add_spend(0.01, "???")
aipick._add_spend(0.02)   # 꼬리표 없이(옛 호출 방식) → 기타
with closing(db.connect()) as conn:   # 🏢 종목 AI 요약은 자기 표(ai_reports)에 비용을 남김 → 표에 합산
    aisummary.ensure_tables(conn)
    conn.execute("INSERT OR REPLACE INTO ai_reports VALUES ('ABC', ?, 'company', 'claude-sonnet-5-5', '{}', 100, 50, 0.04, ?)", (T.isoformat(), db.utcnow_iso()))
    conn.commit()
rows = aipick.spend_rows(); print([(r["kind"], round(r["month_usd"], 2), r["month_n"], r["today_n"]) for r in rows])
assert [r["kind"] for r in rows] == ["forensic", "pick", "summary", "other"]                                   # 많이 쓴 순
f = rows[0]; assert abs(f["month_usd"] - 0.25) < 1e-9 and f["month_n"] == 2 and f["today_n"] == 2 and f["in_tok"] == 50000 and f["out_tok"] == 25000
assert abs(rows[3]["month_usd"] - 0.03) < 1e-9 and rows[3]["month_n"] == 2 and rows[2]["month_n"] == 1 and abs(rows[2]["month_usd"] - 0.04) < 1e-9
assert abs(aipick.spent_usd() - 0.33) < 1e-9                                                                   # 지갑 합계(meta)는 ai_reports 와 별개
d = aipick.spend_days(); assert list(d) == [T.isoformat()] and abs(d[T.isoformat()] - 0.37) < 1e-9             # 날짜별엔 요약 포함
s = aipick.spend_summary(); print({k: v for k, v in s.items() if k != "rows"})
assert abs(s["spent_krw"] - 0.33 * aipick.FX) < 1e-6 and abs(s["left_krw"] - (50000 - 0.33 * aipick.FX)) < 1e-6 and s["top"]["kind"] == "forensic"
assert abs(s["forecast_krw"] - 0.33 / T.day * s["days_in"] * aipick.FX) < 1e-6 and s["elapsed"] == T.day      # 지금까지 하루 평균 × 그달 일수
assert abs(s["today_krw"] - 0.37 * aipick.FX) < 1e-6 and s["untracked_krw"] < 1e-6
# 기록 전 지출(합계만 있는 10/28 이전) → '기능별 기록 전' 금액
db.set_meta(f"ai_spend:{M}", f"{aipick.spent_usd() + 1.0:.6f}")
s2 = aipick.spend_summary(); assert abs(s2["untracked_krw"] - 1.0 * aipick.FX) < 1e-3 and abs(s2["spent_krw"] - 1.33 * aipick.FX) < 1e-3
# 지난달 조회는 그달 일수 전체로 평균
last = (T.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
assert aipick.spend_summary(last)["elapsed"] == aipick.spend_summary(last)["days_in"] and aipick.spend_rows(last) == []
# 호출처 꼬리표가 실제로 붙는지(가짜 Claude): call_claude(kind=) 빈 답 → '기타' 가 아니라 그 기능으로 기록
class R:
    status_code = 200
    def json(self): return {"content": [{"type": "thinking", "thinking": ""}], "stop_reason": "max_tokens", "usage": {"input_tokens": 1000, "output_tokens": 500}}
try:
    aipick.call_claude("p", "claude-haiku-5-5", 100, post=lambda *a, **k: R(), kind="translate")
except RuntimeError as e:
    assert "빈 답" in str(e)
assert any(r["kind"] == "translate" and r["month_n"] == 1 for r in aipick.spend_rows())
# 관리 모드 화면에 섹션이 그려지는지
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
config.MANUAL_TICKERS_FILE = os.path.join(tmp, "manual_tickers.txt")
os.environ["QUANT_TEST_PAGE"] = "admin"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(os.path.join(os.environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown); caps = "\n".join(c.value for c in at.caption)
assert "🤖 AI 비용" in html and "이번 달 지출" in html and "월말 예상" in html and "가장 많이 쓰는 기능: 🧾 공시분석" in caps and "기능별 기록 전" in caps
assert any("기능" in list(d.value.columns) and "건당(원)" in list(d.value.columns) for d in at.dataframe)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
