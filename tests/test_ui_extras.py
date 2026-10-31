"""UI 묶음(2026-10-31, 김곰 워치리스트 참고): ↩ 워치리스트 해제 이력·되돌리기 · 📋 종합 판단/AI PICK 복사 글 · 🆕 업데이트 노트(방문객 거르기)."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import db, watch, verdict, updates, aipick, halts

db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "ABC", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 2.0,
        "high_20d": 2.2, "low_20d": 1.0, "drawdown_pct": -10.0, "day_change_pct": 1.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 1e7, "atr14": 0.01,
        "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()

# ↩ 해제 이력 · 되돌리기
watch.add("ABC", "보유", 1.0, "왜 봤나")
watch.add("XYZ", "관심", 3.0, "")
watch.remove("ABC")                       # 그때 가격 = 최신 스냅샷 2.0
watch.remove("XYZ", price=2.5)
rm = watch.removed()
assert list(rm["ticker"]) == ["XYZ", "ABC"] and rm.set_index("ticker").loc["ABC", "price"] == 2.0 and rm.set_index("ticker").loc["ABC", "list"] == "보유", rm
assert watch.restore("ABC") and list(watch.all_items()["ticker"]) == ["ABC"]
it = watch.all_items().set_index("ticker").loc["ABC"]
assert it["list"] == "보유" and it["added_price"] == 1.0 and it["note"] == "왜 봤나"
assert list(watch.removed()["ticker"]) == ["XYZ"] and not watch.restore("NONE")   # 다시 담은 종목은 목록에서 빠짐

# 📋 종합 판단 복사 글
v = {"ticker": "ABC", "summary": {"label": "🎯 올릴 이유가 있고 조달 수단은 적음", "text": "올릴 이유: 상장 유지 · 현금조달 가능성 낮음 · 공시 흐름: 조용함"},
     "purposes": [{"title": "상장 유지", "urgency": "기한 있음", "need": 1.0, "need_pct": 40.0, "deadline": "2026-11-12", "why": "$1 미달"}],
     "fin": {"level": "낮음", "score": 0, "reasons": [], "pump": {"pumps": 2, "raised": 0, "examples": [], "base": 3}},
     "flow": {"days": 14, "verdict": "조용함", "count": {"호재": 0, "희석": 0, "악재": 0, "중립": 0}, "items": [], "news": 0, "agm": ["주총 예정 2026-11-20(D-20)"]},
     "forensic": {"one_liner": "돈은 3월에 떨어짐", "as_of": "2026-10-20"}}
tx = verdict.text(v).split("\n")
assert tx[0] == "[ABC] 🧭 🎯 올릴 이유가 있고 조달 수단은 적음" and tx[1] == "근거" and tx[2].startswith("- 올릴 이유: 상장 유지 2026-11-12 필요 주가 $1.0000(+40%)"), tx
assert "- 현금조달 가능성 낮음(0점): 특별한 신호 없음" in tx and "- 최근 3년 급등 2번 중 7일 안 조달 0번(평소 3%)" in tx and any("주총: 주총 예정" in x for x in tx)
assert tx[-2].startswith("-> 종합:") and "공시분석(2026-10-20): 돈은 3월에 떨어짐" in "\n".join(tx)

# 🆕 업데이트 노트: 방문객은 방문객 줄만
own, gst = updates.latest(False), updates.latest(True)
assert own and gst and sum(len(n["lines"]) for n in gst) < sum(len(n["lines"]) for n in own) and not any("운영 현황" in x for n in gst for x in n["lines"])

# 화면: 홈 업데이트 노트 · 워치리스트 해제 칸 · AI PICK 텍스트
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py"); os.environ["DASH_PASSWORD"] = ""
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert any(e.label.startswith("🆕 업데이트 노트") for e in at.expander), [e.label for e in at.expander]
os.environ["QUANT_TEST_PAGE"] = "watch"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert any(e.label.startswith("↩ 해제한 종목 1개") for e in at.expander), [e.label for e in at.expander]
with closing(db.connect()) as conn:
    for d in aipick.DDL:
        conn.execute(d)
    conn.execute("INSERT INTO ai_pick (date, ticker, rank, timing, confidence, reason, risk, price, model) VALUES (?, 'ABC', 1, '이번 주', '높음', '상장 유지 기한', '희석', 2.0, 'm')",
                 (date.today().isoformat(),))
    conn.commit()
os.environ["QUANT_TEST_PAGE"] = "pick"
at = AppTest.from_file(APP, default_timeout=180); at.session_state["_want_tab_pick"] = "ai"   # 탭 이동(tabs.go 와 같은 길)
at.run(); assert not at.exception, [e.value for e in at.exception]
tg = [t for t in at.toggle if t.label.startswith("📋 텍스트")]
assert tg, [t.label for t in at.toggle]
tg[0].set_value(True).run(); assert not at.exception
assert any("1. ABC · ⚡이번 주 · 확신 높음\n   근거: 상장 유지 기한" in c.value for c in at.code), [c.value for c in at.code]
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
