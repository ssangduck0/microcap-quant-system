import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, forensic, watch, halts
db.init_db(); halts.fetch = lambda *a, **k: []
REPORT = """## §1. 재무 · 런웨이 (기준일 2026-10-10)
| 항목 | 값 |
|---|---|
| 현금 | $9.0M 🟠 |
## §8. ☠️ 악성 희석
🔴 ELOC 고할인 · 🟢 ATM 없음"""
# ---------- 모듈 ----------
rid = forensic.add("aaa", REPORT, chat_url="https://claude.ai/chat/x")
r = forensic.reports("AAA").iloc[0]; assert r["as_of"] == "2026-10-10" and r["source"] == "붙여넣기" and r["chat_url"] == "https://claude.ai/chat/x"
assert forensic.risk_badges(REPORT) == {"🔴": 1, "🟠": 1, "🟢": 1} and forensic.latest_dates()["AAA"] == r["created_at"][:10]
try: forensic.add("AAA", "   "); raise SystemExit("빈 내용은 오류")
except ValueError: pass
forensic.add("AAA", "두번째 보고서"); assert len(forensic.reports("AAA")) == 2 and forensic.reports("AAA").iloc[0]["content"] == "두번째 보고서"   # 최신이 먼저
forensic.delete(int(forensic.reports("AAA").iloc[0]["id"])); assert len(forensic.reports("AAA")) == 1
assert forensic.project_url() == ""; forensic.set_project_url("https://claude.ai/project/abc"); assert forensic.project_url() == "https://claude.ai/project/abc"
print("module OK")
# ---------- 화면: 행 클릭(선택 상태)으로 종목 상세 전환 ----------
now = db.utcnow_iso()
def snap(t, **kw):
    r = {"date": "2026-10-13", "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.3, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -35.0,
         "day_change_pct": -20.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
         "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0}
    r.update(kw); return r
with closing(db.connect()) as conn:
    for t in ("ZZZ", "AAA", "BBB"): db.upsert_snapshot(conn, snap(t))
from streamlit.testing.v1 import AppTest
import streamlit as st
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
st.cache_data.clear()
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
snapt = [d.value for d in at.dataframe if "공시분석" in d.value.columns and "퀀트점수" in d.value.columns][0]
first = snapt.iloc[0]["티커"]; print("first row:", first, "| 공시분석 열:", dict(zip(snapt["티커"], snapt["공시분석"])))
assert snapt.set_index("티커").loc["AAA", "공시분석"] != "" and snapt.set_index("티커").loc["BBB", "공시분석"] == ""
md = [m.value for m in at.markdown]
assert f"#### {first}" in md and any(f"🧾 {first} 공시분석" in x for x in md)                    # 아직 안 눌렀으면 첫 행
assert any("행을 누르면" in c.value for c in at.caption)
at.session_state["snap_table_pick"] = "AAA"; at.run(); assert not at.exception                    # 'AAA' 행을 누른 것과 같은 상태
md = [m.value for m in at.markdown]
assert "#### AAA" in md and any("🧾 AAA 공시분석" in x for x in md) and any(p.label == "섹션" or "§8" in str(getattr(p, "options", "")) for p in at.get("button_group"))   # 저장된 보고서 본문
assert any("🔴 1 · 🟠 1 · 🟢 1" in c.value and "원 대화 열기" in c.value for c in at.caption)
assert any(b.label == "🔗 공시 분석 프로젝트 열기" for b in at.get("link_button"))
# 저장 폼(종목 상세의 BBB): 붙여넣고 저장 → 바로 표시
at.session_state["snap_table_pick"] = "BBB"; at.run()
assert any("BBB 의 저장된 공시분석이 없습니다" in i.value for i in at.info)
at.text_area(key="snap_text_BBB").set_value("## BBB 스캔\n🔴 ATM 활성")   # 폼: 입력한 뒤 저장 버튼과 함께 전달
btn = [b for b in at.button if b.label == "💾 저장" and getattr(b, "form_id", "") == "snap_form_BBB"]
print("forms:", [getattr(b, "form_id", None) for b in at.button if b.label == "💾 저장"])
btn[0].click().run(); assert not at.exception
assert len(forensic.reports("BBB")) == 1 and forensic.reports("BBB").iloc[0]["content"].startswith("## BBB 스캔")
at.run(); assert any("## BBB 스캔" in m.value for m in at.markdown)
# 표의 공시분석 열에 날짜가 생김
snapt = [d.value for d in at.dataframe if "공시분석" in d.value.columns and "퀀트점수" in d.value.columns][0]; assert snapt.set_index("티커").loc["BBB", "공시분석"] != ""
# ⭐ 워치리스트: 행 선택 → 상세에 공시분석, 표에 공시분석 열
watch.add("AAA", "관심"); watch.add("BBB", "보유")
st.cache_data.clear(); at = AppTest.from_file(APP, default_timeout=120).run(); assert not at.exception
wl = [d.value for d in at.dataframe if "출회 가능(M주)" in d.value.columns][0]; assert list(wl.columns)[2] == "토스" and "공시분석" in wl.columns and (wl["공시분석"] != "").all()
at.session_state["wl_table_pick"] = "AAA"; at.run(); assert "##### AAA" in [m.value for m in at.markdown] and any("🧾 AAA 공시분석" in m.value for m in at.markdown)
# 🗂 종목 리포트 탭에도 같은 섹션
assert any("🧾 공시분석" in e.label for e in at.expander)
print("ALL OK")
