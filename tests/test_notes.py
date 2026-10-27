import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, notes_ui
db.init_db()
# --- 순수 함수 ---
assert notes_ui.decode_text("장 마감 매매 방법".encode("utf-8")) == "장 마감 매매 방법"
assert notes_ui.decode_text("장 마감 매매 방법".encode("utf-8-sig")) == "장 마감 매매 방법"            # BOM 있는 UTF-8
assert notes_ui.decode_text("마이너스 통장".encode("cp949")) == "마이너스 통장"                         # 메모장 기본(ANSI) 저장
assert notes_ui.decode_text(b"\xff\xfe\xfa") != ""                                                        # 깨진 바이트도 예외 없이
notes_ui.save("A", "본문A"); notes_ui.save("B", "본문B"); notes_ui.save("A", "본문A2")
assert notes_ui.get("A") == "본문A2" and notes_ui.get("없음") == "" and set(notes_ui.list_titles()) == {"A","B"}
assert "===== A" in notes_ui.export_all() and "본문B" in notes_ui.export_all()
notes_ui.delete("B"); assert notes_ui.list_titles() == ["A"]
notes_ui.delete("A")
print("functions OK")

# --- 화면 ---
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date":"2026-10-12","ticker":"AAA","exchange":"NASDAQ","first_seen":now,"last_seen":now,"price":1.0,"high_20d":2.0,"low_20d":0.9,
        "drawdown_pct":-40.0,"day_change_pct":-15.0,"volume_mult":3.0,"buy_pressure":55.0,"float_shares":8e6,"atr14":0.1,"quant_score":50.0,"quant_detail":"{}",
        "pump_score":40.0,"pump_detail":'{"checks":[]}',"dilution_status":"CLEAN","excluded":0})
db.save_report("AAA", {"ticker":"AAA","generated_at":now,"errors":{},"cik":1,"company":{"name":"A Corp","exchange":"NASDAQ"},"timeline":[]})
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=90).run()
print("exc:", [e.value for e in at.exception], "| tabs:", len(at.tabs))
assert not at.exception and {'🧲 수급', '⭐ 워치리스트', '🗓 일정', '📝 노트'} <= {t.label for t in at.tabs}   # 메뉴 정리: 오늘 브리핑 삭제 · 장마감 체크리스트는 🧲 수급의 탭
import shortflow as _sf
import pumpsetup as _ps
import flowread as _fr, afterscalp as _af, piggy as _pg
assert set(notes_ui.list_titles()) == {_sf.TIP_TITLE, _fr.TIP_TITLE, _af.TIP_TITLE, _pg.PROFIT_TIP_TITLE, *_ps.TIPS}                     # 처음 열면 스승님 꿀팁 원문 5개가 노트로 자동 보관됨
# 새 노트 만들기
at.text_input(key="note_new_title").set_value("장 마감 매매 방법").run()
[b for b in at.button if "만들기" in b.label][0].click().run()
assert not at.exception and "장 마감 매매 방법" in notes_ui.list_titles()
assert at.selectbox(key="note_pick").value == "장 마감 매매 방법"
# 입력하면 자동 저장(별도의 저장 버튼 없이)
at.text_area(key="note_body_장 마감 매매 방법").set_value("1) 마감 30분 전 후보 확인\n2) 다음날 고가 근처에서 매도").run()
assert notes_ui.get("장 마감 매매 방법").startswith("1) 마감 30분 전"), notes_ui.get("장 마감 매매 방법")
assert any("마지막 자동 저장" in c.value for c in at.caption)
# 두 번째 노트 -> 전환해도 각각 유지
at.text_input(key="note_new_title").set_value("공시 체크").run()
[b for b in at.button if "만들기" in b.label][0].click().run()
at.text_area(key="note_body_공시 체크").set_value("ATM 은 잔여한도 확인").run()
assert notes_ui.get("공시 체크") == "ATM 은 잔여한도 확인"
at.selectbox(key="note_pick").set_value("장 마감 매매 방법").run()
assert at.text_area(key="note_body_장 마감 매매 방법").value.startswith("1) 마감 30분 전")
assert not at.exception
# 같은 제목으로 다시 만들어도 기존 내용 보존
at.text_input(key="note_new_title").set_value("공시 체크").run()
[b for b in at.button if "만들기" in b.label][0].click().run()
assert notes_ui.get("공시 체크") == "ATM 은 잔여한도 확인"
# 삭제: 확인란 없이는 버튼 비활성
dbtn = [b for b in at.button if b.label == "삭제"][0]; assert dbtn.disabled
at.checkbox(key=[c.key for c in at.checkbox if c.key and c.key.startswith("note_del_ok_")][0]).set_value(True).run()
[b for b in at.button if b.label == "삭제"][0].click().run()
assert not at.exception and len(notes_ui.list_titles()) == 9   # 남은 노트 1개 + 꿀팁 노트 8개
# 종목 리포트의 종목별 메모도 자동 저장
at.text_area(key="note_AAA").set_value("DKI 처럼 보이지만 ELOC 확인 필요").run()
assert db.get_note("AAA") == "DKI 처럼 보이지만 ELOC 확인 필요" and not at.exception
# 다시 열어도(새 세션) 남아 있음
at2 = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=90).run()
assert at2.text_area(key="note_AAA").value.startswith("DKI") and not at2.exception
print("ALL OK")
