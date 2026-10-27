import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, halts, lite
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-14", "ticker": "HODO", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.06, "high_20d": 0.1, "low_20d": 0.05,
        "drawdown_pct": -40.0, "day_change_pct": -25.0, "volume_mult": 5.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()

# --- 규칙 단위
assert lite.is_mobile("Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit Mobile Safari") and lite.is_mobile("iPhone OS 18")
assert not lite.is_mobile("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") and not lite.is_mobile("iPad; CPU OS 17")
st_ = {}; assert lite.decide(st_, None, "Android Mobile") is True                 # 휴대폰 → 간략
assert lite.decide(st_, None, "Windows") is True                                # 이 창에서 한 번 정하면 유지
assert lite.decide(st_, "full", "Android Mobile") is False and lite.decide({}, "lite", "Windows") is True   # 주소가 우선
assert lite.decide({}, None, "") is False                                       # 알 수 없으면 전체
assert lite.pages() == lite.DEFAULT_PAGES
lite.save_pages(["pick", "home", "score"]); assert lite.pages() == ["pick", "score"]   # 홈은 저장 안 해도 항상
lite.reset_pages(); assert lite.pages() == lite.DEFAULT_PAGES
P = [("home", "홈", "🏠", "", "홈"), ("rank", "종합", "🏁", "", "오늘"), ("brief", "브", "📰", "", "오늘"), ("accum", "매", "🧲", "", "발굴"), ("pick", "p", "🎯", "", "선별"), ("score", "s", "🏆", "", "추적")]
assert lite.categories(P, ["rank", "brief", "accum", "pick", "score"]) == [("홈", "🏠", "home"), ("오늘", "📰", "rank"), ("발굴", "🧲", "accum"), ("선별", "🎯", "pick"), ("추적", "🏆", "score")]
assert lite.canon(["brief", "snap", "rank", "close", "accum", "home"]) == ["lookup", "rank", "accum"]    # 옛 키 → 새 키(홈 제외·중복 제거)

# --- 화면: 간략 모드(?v=lite)
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180)
at.query_params["v"] = "lite"
at.run(); assert not at.exception, [e.value for e in at.exception]
titles = [t.value for t in at.title]; assert any("초소형주 퀀트 대시보드" in t for t in titles), titles         # 홈: 고정 정보 있음
md = " ".join(m.value for m in at.markdown); assert "발견 종목" in md and "환율" in md
labels = [l.label for l in at.get("page_link")]
assert "관리 모드" not in labels and "종목" not in labels, labels   # 간략: 종목·관리 없음
for need in ("홈", "오늘", "발굴", "선별", "추적", "검증", "PICK +30%", "종합 순위"):
    assert need in labels, (need, labels)
assert [b for b in at.button if b.label == "🖥 전체 보기로"]
# 홈에서 전체 보기로 → 관리 모드 링크가 생김
[b for b in at.button if b.label == "🖥 전체 보기로"][0].click().run(); assert not at.exception
labels = [l.label for l in at.get("page_link")]; assert "관리 모드" in labels and "종목" in labels
assert [b for b in at.button if b.label == "📱 간략 보기로"]

# --- 다른 화면: 홈 고정 정보 없음 + 투자 권유 아님 한 줄은 유지
os.environ["QUANT_TEST_PAGE"] = "score"
at2 = AppTest.from_file(APP, default_timeout=180); at2.query_params["v"] = "lite"; at2.run()
assert not at2.exception, [e.value for e in at2.exception]
assert not [t for t in at2.title if "초소형주 퀀트 대시보드" in t.value]
md2 = " ".join(m.value for m in at2.markdown)
assert "누적 종목-일" not in md2 and any("투자 권유가 아닙니다" in c.value for c in at2.caption)
assert at2.get("button_group"), "🏆 검증의 탭(성과 공표·점수 검증·타임머신·가상매매)"

# --- 관리 모드: 간략 화면 구성 · 화면 속도
os.environ["QUANT_TEST_PAGE"] = "admin"
at3 = AppTest.from_file(APP, default_timeout=180); at3.query_params["v"] = "full"; at3.run()
assert not at3.exception, [e.value for e in at3.exception]
ms = at3.multiselect(key="adm_lite_pages"); assert set(ms.value) == set(lite.DEFAULT_PAGES)
ms.set_value(["pick", "score"]).run(); [b for b in at3.button if b.label == "💾 간략 화면 저장"][0].click().run()
assert lite.pages() == ["pick", "score"], lite.pages()
at3.run(); assert at3.dataframe and any("화면 속도" in m.value for m in at3.markdown)   # 앞에서 그린 화면들 시간이 남음
os.environ.pop("QUANT_TEST_PAGE", None)
print("UI OK")
