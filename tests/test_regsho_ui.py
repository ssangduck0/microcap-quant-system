import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ["QUANT_TEST_PAGE"] = "regsho"
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, halts, regsho, intel, shortflow, watch, multisignal, shortdata
db.init_db(); halts.fetch = lambda *a, **k: []; intel.ensure_table()
now = db.utcnow_iso()
days = [f"2026-10-{d:02d}" for d in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20, 21)]          # 15 거래일
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-21", "ticker": "NIVF", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.27, "high_20d": 0.5, "low_20d": 0.2,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CB", "excluded": 0})
    regsho.ensure_tables(conn)
    for i, d in enumerate(days):
        conn.execute("INSERT INTO regsho_files VALUES (?,'ok',1,0)", (d,))
        conn.execute("INSERT INTO regsho_list VALUES (?,'NIVF','Nivf Corp')", (d,))                   # 15일 연속 → 고위험
        if i >= 8: conn.execute("INSERT INTO regsho_list VALUES (?,'MEDS','Meds Inc')", (d,))         # 7일 → 위험
        if d == days[-1]: conn.execute("INSERT INTO regsho_list VALUES (?,'NEWZ','New Z')", (d,))     # 신규
        if d == days[-2]: conn.execute("INSERT INTO regsho_list VALUES (?,'GONE','Gone')", (d,))      # 어제만 → 오늘 빠짐
    shortdata.ensure_tables(conn)
    conn.execute("INSERT INTO ibkr_borrow_day VALUES ('2026-10-21','NIVF',250000,150000,646.6)"); conn.execute("INSERT INTO finra_shvol VALUES ('2026-10-20','NIVF',1313958,0,2297000)")
    intel.save(conn, "2026-10-21", "NIVF", {"day": "2026-10-21", "short": {"borrow_fee": 646.6, "borrow_avail": 150000.0, "sv_ratio": 57.2, "sv_short": 1313958.0, "sv_date": "2026-10-20"}})
    shortflow.record(conn, "NIVF", "2026-10-21", shortflow.STAGES[2], 0.27)
    conn.commit()
    assert regsho.summary(conn, days[-1]) == {"cur": {"등록": 3, "고위험": 1, "위험": 1, "신규": 1}, "delta": {"등록": 0, "고위험": 0, "위험": 0, "신규": 0}}   # 어제: NIVF 14·MEDS 6·GONE 1 → 같은 구성
    assert regsho.streaks_at(conn, days[-2])["GONE"] == 1 and regsho.level(15) == "고위험" and regsho.level(7) == "위험" and regsho.level(1) == "신규"
watch.add("MEDS", "관심")
ms = multisignal.collect(days=400); assert set(ms["NIVF"]) >= {"Reg SHO", "공매도 흐름"}
_orig_collect = multisignal.collect; multisignal.collect = lambda days=5: _orig_collect(days=400)   # 화면은 최근 5일 창 → 고정 날짜(2026-10-21) 자료가 보이게
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
html = "\n".join(m.value for m in at.markdown)
assert "qk-cards" in html and "등록된 티커" in html and "→ 전일 대비 +0" in html                          # 요약 카드 + 전일 대비(고위험 +1)
order = [m.value for m in at.markdown if 'class="qk-rank"' in m.value]; print([o[o.index("qk-tk") + 7:o.index("qk-tk") + 11] for o in order])
assert len(order) == 3 and "NIVF" in order[0] and "MEDS" in order[1] and "NEWZ" in order[2]                 # 연속일수 순위
assert "멀티 시그널 2" in order[0] and "희석 CB" in order[0] and "관심" in order[1] and "qk-pill\">15일째" in html
at.radio(key="rg_tab").set_value("고위험").run(); assert len([m for m in at.markdown if 'class="qk-rank"' in m.value]) == 1
at.radio(key="rg_tab").set_value("관심").run(); assert "MEDS" in [m.value for m in at.markdown if 'class="qk-rank"' in m.value][0]
at.radio(key="rg_tab").set_value("전체").run()
[b for b in at.button if b.key == "rg_btn_NIVF"][0].click().run(); assert not at.exception
html = "\n".join(m.value for m in at.markdown)
assert "646.6%" in html and "57.2%" in html and "1,313,958" in html and 'qk-hist on">10-21 (조회일)' in html and html.count("qk-hist") >= 15
at.selectbox(key="rg_day").set_value(days[-2]).run(); assert not at.exception
assert "GONE" in "\n".join(m.value for m in at.markdown if 'class="qk-rank"' in m.value)                    # 날짜를 바꾸면 그날 목록
os.environ.pop("QUANT_TEST_PAGE")
print("ALL OK")
