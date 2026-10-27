import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, halts, intel, regsho, watch
db.init_db(); halts.fetch = lambda *a, **k: []; intel.ensure_table()
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    for t, fs in (("HODO", 3e6), ("BBB", 50e6)):
        db.upsert_snapshot(conn, {"date": "2026-10-14", "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.06, "high_20d": 0.1, "low_20d": 0.05,
            "drawdown_pct": -40.0, "day_change_pct": -25.0, "volume_mult": 5.0, "buy_pressure": 55.0, "float_shares": fs, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
            "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    intel.save(conn, "2026-10-14", "HODO", {"day": "2026-10-14", "short": {"borrow_fee": 80.0, "borrow_avail_chg_pct": -60.0, "sv_ratio": 70.0}})
    regsho.ensure_tables(conn)
    for d_ in ("2026-10-14", "2026-10-13"):
        conn.execute("INSERT INTO regsho_files VALUES (?,'ok',1,0)", (d_,)); conn.execute("INSERT INTO regsho_list VALUES (?,'HODO','H')", (d_,))
    conn.commit()
watch.add("HODO", "관심")
from streamlit.testing.v1 import AppTest
import streamlit as st
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
links = at.get("page_link"); print(len(links))
import re as _re
_d = open(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")).read(); _i = _d.index("PAGES = [  # (키"); _j = _d.index("]\n", _i)
_titles = {m.group(1) for m in _re.finditer(r'\("\w+", "([^"]+)", "[^"]+", "[^"]+", "[^"]+"\)', _d[_i:_j])}
assert len(_titles) == 29 and _titles <= {l.label for l in links} and {"선별", "종목"} <= {l.label for l in links}   # 메뉴 27(2026-10 정리: 수급·종목·검증 탭 묶음) + 홈 카드 + 📱 아래 메뉴
heads = [h.value for h in at.subheader]; print(heads)
assert any("qk-title" in m.value and "🏠 홈" in m.value for m in at.markdown) and not any("성과 공표" in h for h in heads)   # 기본 화면 = 홈만 그림
assert any("navsec" in m.value or "navdesc" in m.value for m in at.markdown)
os.environ["QUANT_TEST_PAGE"] = "snap"; _a = AppTest.from_file(APP, default_timeout=180).run(); assert [e for e in _a.expander if e.label == "필터"]; os.environ.pop("QUANT_TEST_PAGE")
# 페이지 전환
def open_page(key):
    os.environ["QUANT_TEST_PAGE"] = key
    a = AppTest.from_file(APP, default_timeout=180).run()
    assert not a.exception, [e.value for e in a.exception]
    return a
at = open_page("squeeze")
heads = [h.value for h in at.subheader]; assert any("qk-title" in m.value and "스퀴즈 랭크" in m.value for m in at.markdown) and not any("퀀트 스냅샷" in h for h in heads)
at.slider(key="sq_min2").set_value(0).run(); assert not at.exception
sq = [d.value for d in at.dataframe if "스퀴즈 점수" in d.value.columns][0]; print(sq[["티커", "스퀴즈 점수"]].to_string(index=False))
assert sq.iloc[0]["티커"] == "HODO" and sq.iloc[0]["스퀴즈 점수"] > 0
at = open_page("lookup")
at.text_input(key="lookup_in").set_value("HODO").run(); assert not at.exception
assert any(m.value == "### HODO · 세부 패널" for m in at.markdown) and any(b.label == "HODO" for b in at.button)      # 즐겨찾기 칩
assert any(b.label == "📲 토스증권에서 열기" for b in at.get("link_button"))
at = open_page("rsplit"); assert any("병합 예정" in e.label for e in at.expander)
for k in ("brief", "close", "piggy", "after", "setup", "watch", "events", "report", "notes", "score", "tracking", "signals", "scorecheck", "cases", "filings", "chart", "pressure", "papertrade", "accum"):
    open_page(k)                                                                                    # 모든 화면(옛 키는 새 위치의 탭으로)이 따로 열려도 오류 없음
at = open_page("snap"); assert [e for e in at.expander if e.label == "필터"] and at.get("button_group")                    # 옛 키 snap → 🏢 종목의 스냅샷 탭
at = open_page("pressure"); assert any("회사 압박" in m.value for m in at.markdown)                                          # 옛 키 pressure → 🎯 PICK 의 전체 후보 탭
os.environ.pop("QUANT_TEST_PAGE")
print("ALL OK")
