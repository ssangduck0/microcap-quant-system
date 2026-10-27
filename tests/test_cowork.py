import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, forensic, watch, halts
db.init_db(); halts.fetch = lambda *a, **k: []
root = forensic.root_dir(); assert str(root) == os.path.join(tmp, "forensic")
# ---------- 대기열 ----------
assert forensic.queue_list() == [] and forensic.queue_add("jbdi") == 1 and forensic.queue_add(["JBDI", "aaa", "BBB", "bad line!"]) == 3
assert forensic.queue_list() == ["JBDI", "AAA", "BBB"]                                   # 형식이 틀린 줄은 무시
(root / "queue.txt").write_text("\ufeffjbdi\n\n  ccc  \n", encoding="utf-8")              # 사람이(또는 Cowork가) 직접 고친 파일: BOM·공백·소문자
assert forensic.queue_list() == ["JBDI", "CCC"]
forensic.queue_remove("jbdi"); assert forensic.queue_list() == ["CCC"]
forensic.queue_add(["JBDI", "AAA"])
print("queue OK")
# ---------- Cowork 결과 가져오기 ----------
inbox = root / "inbox"
(inbox / "JBDI_20261015.md").write_text("## JBDI 덕구 스캔 (기준일 2026-10-14)\n🔴 ELOC 활성", encoding="utf-8")
(inbox / "aaa_20261015.md").write_bytes("## AAA 스캔\n판정: 양호".encode("cp949"))                 # 한국어 윈도우 기본 인코딩도 읽음
(inbox / "CCC_20261015_ERROR.txt").write_text("SEC CIK 를 찾지 못함", encoding="utf-8")
(inbox / "notes.md").write_text("이름 형식이 다름", encoding="utf-8")
(inbox / "DDD_20261015.md").write_text("   ", encoding="utf-8")
r = forensic.import_inbox(); print(r)
assert set(r["imported"]) == {"JBDI", "AAA"} and r["errors"] == [("CCC", "SEC CIK 를 찾지 못함")] and set(r["skipped"]) == {"notes.md", "DDD_20261015.md"}
j = forensic.reports("JBDI").iloc[0]; assert j["source"] == "Cowork 자동" and j["as_of"] == "2026-10-14" and "ELOC" in j["content"]
assert forensic.reports("AAA").iloc[0]["as_of"] == "2026-10-15" and "양호" in forensic.reports("AAA").iloc[0]["content"]   # 기준일이 없으면 파일 날짜
assert forensic.queue_list() == ["CCC"]                                                     # 성공한 종목은 대기열에서 빠지고, 실패(CCC)는 남음
arch = sorted(p.name for p in (root / "archive").iterdir()); assert arch == ["CCC_20261015_ERROR.txt", "JBDI_20261015.md", "aaa_20261015.md"]
assert sorted(p.name for p in inbox.iterdir()) == ["DDD_20261015.md", "notes.md"]           # 처리 못 한 파일은 그대로 둠
last = json.loads(db.get_meta("forensic_last_import")["value"]); assert set(last["imported"]) == {"JBDI", "AAA"} and last["errors"] == [["CCC", "SEC CIK 를 찾지 못함"]]
(inbox / "JBDI_20261015.md").write_text("두 번째 결과", encoding="utf-8"); forensic.import_inbox()
assert len(list((root / "archive").glob("JBDI_20261015*"))) == 2 and len(forensic.reports("JBDI")) == 2      # 같은 이름이면 보관 파일 이름을 바꿔 둘 다 보관
assert forensic.import_inbox() == {"imported": [], "errors": [], "skipped": ["DDD_20261015.md", "notes.md"]}
print("import OK")
# ---------- 화면 ----------
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-13", "ticker": "EEE", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.3, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -35.0, "day_change_pct": -20.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
watch.add("EEE", "관심"); watch.add("FFF", "보유"); watch.add("ZZZ", "블랙")
(inbox / "EEE_20261016.md").write_text("## EEE 자동 스캔 결과\n🟠 주의", encoding="utf-8")       # 대시보드를 열면 자동 저장
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
assert forensic.reports("EEE").iloc[0]["source"] == "Cowork 자동" and any("## EEE 자동 스캔 결과" in m.value for m in at.markdown)
assert any("자동 저장" in t.value for t in at.toast) if hasattr(at, "toast") else True
# 자동 스캔 요청 버튼 → 대기열 추가 → 다시 누르면 빼기
b = [x for x in at.button if x.label == "⏰ 자동 스캔 요청 (Cowork)" and str(x.key).startswith("snap_q_")][0]; b.click().run()
assert "EEE" in forensic.queue_list() and any(x.label == "⏰ 자동 스캔 대기 중 · 빼기" for x in at.button)
[x for x in at.button if x.label == "⏰ 자동 스캔 대기 중 · 빼기" and str(x.key).startswith("snap_unq_")][0].click().run(); assert "EEE" not in forensic.queue_list()
# 설정 패널: 서버 자동 분석 안내 · (스위치를 켜면) 예전 Cowork 지시문(폴더 경로 포함), 워치리스트 전체 추가(블랙 제외), 최근 실패 표시
assert not any("[덕구 자동 공시분석]" in c.value for c in at.code)                       # 서버 자동 분석이 기본 — Cowork 안내는 접혀 있음
at.toggle(key="cw_show").set_value(True).run()
assert any("[덕구 자동 공시분석]" in c.value and str(root) in c.value for c in at.code)
[x for x in at.button if x.key == "cw_q_all"][0].click().run()
assert set(forensic.queue_list()) >= {"EEE", "FFF", "CCC"} and "ZZZ" not in forensic.queue_list()
at.slider(key="cw_per_run").set_value(5).run(); assert any("최대 5개" in c.value for c in at.code)
assert any("CCC 분석 실패" in w.value for w in at.warning)                                     # 다른 종목 결과가 그 뒤에 들어와도 실패 표시는 남음
assert "CCC" in forensic.errors()
at.multiselect(key="cw_q_rm").set_value(["FFF"]).run(); [x for x in at.button if x.key == "cw_q_rm_btn"][0].click().run()
assert "FFF" not in forensic.queue_list() and not at.exception
(inbox / "CCC_20261017.md").write_text("## CCC 재스캔 성공", encoding="utf-8"); forensic.import_inbox()
assert "CCC" not in forensic.errors() and "CCC" not in forensic.queue_list()                  # 성공하면 실패 기록이 지워짐
forensic._set_error("XYZ", "테스트"); forensic.queue_remove("XYZ"); assert "XYZ" not in forensic.errors()   # 대기열에서 빼도 지워짐
print("ALL OK")
