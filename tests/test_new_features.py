import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, datetime, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, rsplit, regsho, scoreboard, halts, market, shortflow, tosslink
db.init_db(); halts.fetch = lambda *a, **k: []; db.set_meta("usdkrw", "1342")
rng = np.random.default_rng(1)
now = db.utcnow_iso(); D = "2026-10-14"
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": D, "ticker": "HODO", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.06, "high_20d": 0.1, "low_20d": 0.05,
        "drawdown_pct": -40.0, "day_change_pct": -25.0, "volume_mult": 5.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0, "win_score": 75.0})
    for i in range(200):
        conn.execute("INSERT INTO case_events (ticker, date, close, drop_pct, vol_mult, next_high_pct, next_low_pct, next_close_pct, fwd_5d, max_down_5d, max_up_5d) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f"T{i}", f"2020-01-{1 + i % 28:02d}", 1.0, -25.0 + (i % 4), 5.0, float(i % 40), -10.0, 2.0, 1.0, -15.0, float(i % 60)))
    rsplit.ensure_tables(conn)
    for i in range(60):
        conn.execute("INSERT INTO rs_paths VALUES (?,?,?,?,?,?,?,?)", (f"P{i}", "2020-01-01", 20 + i % 5, -40.0 + i % 6, float(10 + i), -5.0, 3.0, 4))
    conn.execute("INSERT INTO rs_events VALUES ('P0','2020-01-01',0.1,5.0)")
    conn.execute("INSERT INTO rs_current VALUES ('HODO','2026-09-15',0.04,21,0.06,-38.0,'x')")
    regsho.ensure_tables(conn)
    for d_ in ("2026-10-14", "2026-10-13", "2026-10-12"):
        conn.execute("INSERT INTO regsho_files VALUES (?,'ok',1,0)", (d_,)); conn.execute("INSERT INTO regsho_list VALUES (?,'HODO','House of Doge')", (d_,))
    shortflow.record(conn, "HODO", "2026-10-01", shortflow.STAGES[2], 0.05)
    conn.commit()
    assert rsplit.record_daily(conn, D, 20.0, 50.0, 20) == 1                                     # 유사 60건·성공률 높음 → 예측 기록
tosslink.save("HODO", "NAS0231005001")
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
labels = [x.label for x in at.tabs]; assert "🔁 병합 후 레이더" in labels and "🏆 성과 공표" in labels
snap = [d.value for d in at.dataframe if "퀀트점수" in d.value.columns][0].set_index("티커").loc["HODO"]
print(snap[["예상 다음날 고가(원)", "5일 내 기대 최고(원)", "Reg SHO", "토스"]].to_dict())
assert snap["Reg SHO"] == "📛 3일째" and "~" in snap["예상 다음날 고가(원)"] and snap["토스"].endswith("NAS0231005001/order")
radar = [d.value for d in at.dataframe if "예상 반등 출발가(원)" in d.value.columns][0].set_index("티커").loc["HODO"]
assert radar["비율"] == "25:1" and radar["유사 사례"] >= 20 and radar["Reg SHO"] == "📛 3일째"
import re as _re  # 🏆 숫자는 이제 카드(휴대폰 2열)로 그림
_cm = _re.search(r'<div class="t">예측</div><div class="v">([\d,]+)</div>', " ".join(m.value for m in at.markdown)); assert _cm and int(_cm.group(1).replace(",", "")) >= 1   # 🏆: 병합 레이더 + 공매도 흐름 + 승률 점수(70↑) 등
sbt = [d.value for d in at.dataframe if "결과" in d.value.columns and "목표(%)" in d.value.columns]; assert sbt and "토스" in sbt[0].columns
at.button_group(key="sb_unit").set_value("월간").run(); assert not at.exception
at.checkbox(key="f52_on").set_value(True).run(); assert not at.exception                        # 52주 필터(가격 없음 → 빈 결과 안내)
print("ALL OK")
