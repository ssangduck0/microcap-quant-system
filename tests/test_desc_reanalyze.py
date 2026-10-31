"""🏢 기업 설명(야후 소개 → Haiku 한국어, 종목당 한 번) · 🧾 재분석 필요 배지(리포트 뒤 새 물량 🔴 · 그 밖 공시 🟡) · 자동 대기열이 🔴 먼저(2026-10-31)."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, config, reanalyze, companydesc, forensic, forensic_ai, secbackfill, secfeed, watch, halts, aipick

db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
T = date.today(); D = lambda n: (T - timedelta(days=n)).isoformat()

# 🧾 재분석 필요
with closing(db.connect()) as conn:
    secbackfill.ensure_tables(conn); secfeed.ensure_tables(conn)
    forensic.add("RED", "# 리포트", source="test", as_of=D(10)) if hasattr(forensic, "add") else None
    forensic.add("YEL", "# 리포트", source="test", as_of=D(10))
    conn.execute("UPDATE forensic_reports SET created_at=? WHERE ticker IN ('RED','YEL')", (D(10) + "T09:00:00+00:00",))
    ins = "INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES (?,?,?,?,?)"
    for a, t, f, d, it in (("r1", "RED", "424B5", D(5), ""), ("r2", "RED", "8-K", D(3), "3.02,9.01"), ("r3", "RED", "424B5", D(10), ""),   # 분석 당일 공시는 뺌
                           ("y1", "YEL", "10-Q", D(4), ""), ("y2", "YEL", "8-K", D(2), "7.01"), ("y3", "YEL", "4", D(1), "")):
        conn.execute(ins, (a, t, f, d, it))
    conn.commit()
    n = reanalyze.need(conn, "RED", D(10))
    assert n["level"] == "red" and [f for _, f in n["red"]] == ["424B5", "8-K 3.02,9.01"], n
    y = reanalyze.need(conn, "YEL", D(10))
    assert y["level"] == "yellow" and [f for _, f in y["yellow"]] == ["10-Q"] and not y["red"], y   # 8-K 7.01·Form 4 는 일상 공시
    assert reanalyze.need(conn, "NONE", None)["level"] is None
    assert reanalyze.badge(n).startswith(f"🔴 분석({D(10)}) 뒤 새 물량 공시 2건") and "재분석 권장" in reanalyze.badge(n) and reanalyze.badge(y).startswith("🟡")
    assert reanalyze.stale(conn) == ["RED"]
    q0 = set(forensic.queue_list())
    got = forensic_ai.auto_enqueue(conn, out=lambda *_: None)
    assert got[:1] == ["RED"] and "RED" in set(forensic.queue_list()) - q0, got        # 리포트가 있어도 🔴 면 다시 대기열에

# 🏢 기업 설명: 가짜 야후·가짜 Claude
calls = []
class R:
    status_code = 200
    def json(self):
        return {"content": [{"type": "text", "text": "ABC 는 미국 보스턴의 바이오 회사로 희귀 질환 치료제를 개발해요."}], "usage": {"input_tokens": 300, "output_tokens": 80}}
def post(url, headers=None, json=None, timeout=None):
    calls.append(json); return R()
fetch = lambda t: ("ABC Bio is a Boston-based biotechnology company developing therapies for rare diseases.", "Yahoo") if t == "ABC" else ("", "")
d = companydesc.ensure_one("abc", fetch=fetch, post=post)
assert d["ko"].startswith("ABC 는 미국 보스턴의 바이오") and d["source"] == "Yahoo" and len(calls) == 1
assert calls[0]["model"] == "claude-haiku-5-5" and calls[0]["thinking"] == {"type": "disabled"} and "2~4문장" in calls[0]["system"]
assert companydesc.ensure_one("ABC", fetch=fetch, post=post)["ko"] and len(calls) == 1           # 한 번만(저장된 것 사용)
assert companydesc.ensure_one("NOPE", fetch=fetch, post=post) is None
with closing(db.connect()) as conn:
    spent = conn.execute("SELECT kind, n FROM ai_spend").fetchall()
assert [tuple(x) for x in spent] == [("desc", 1)], spent                                          # AI 예산 지갑에 '기업 설명'으로
watch.add("XYZ", "관심", 1.0, "")
fetch2 = lambda t: ("XYZ makes widgets.", "Yahoo")
logs = []
assert companydesc.morning(out=logs.append, fetch=fetch2, post=post) == 1 and "1종목 시도" in logs[0] and companydesc.get("XYZ")["ko"], logs

# 🏢 종목 화면: 기업 설명 + 재분석 배지
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "RED", "exchange": "NASDAQ", "first_seen": db.utcnow_iso(), "last_seen": db.utcnow_iso(), "price": 1.0,
        "high_20d": 1.2, "low_20d": 0.9, "drawdown_pct": -20.0, "day_change_pct": 1.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 1e7, "atr14": 0.01,
        "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.execute("INSERT OR REPLACE INTO company_desc VALUES ('RED', 'x', '레드는 오하이오의 전력 장비 회사예요.', 'Yahoo', 'x')")
    conn.commit()
import pandas as pd, numpy as np, watch_ui
idx = pd.bdate_range(end=pd.Timestamp(T), periods=60); cc = np.full(60, 1.0)
watch_ui.prices = lambda tk: {"RED": pd.DataFrame({"Open": cc, "High": cc, "Low": cc, "Close": cc, "Volume": 1e6}, index=idx)}
from streamlit.testing.v1 import AppTest
os.environ["QUANT_TEST_PAGE"] = "lookup"; os.environ["DASH_PASSWORD"] = ""
at = AppTest.from_file(os.path.join(os.environ["QS_ROOT"], "dashboard.py"), default_timeout=180); at.session_state["lookup_ticker"] = "RED"
at.run(); assert not at.exception, [e.value for e in at.exception]
md = "\n".join(m.value for m in at.markdown)
assert "레드는 오하이오의 전력 장비 회사예요." in md and "새 물량 공시 2건" in md and "재분석 권장" in md, md[:600]
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
