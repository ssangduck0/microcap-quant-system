import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
import numpy as np, pandas as pd
import db, eventlab as ev, secbackfill
db.init_db()
IDX = """<div class="infoHead">Accepted</div>
<div class="info">2026-03-10 16:05:12</div><table class="tableFile"><tr><td scope="row">1</td><td scope="row">8-K</td><td scope="row"><a href="/Archives/edgar/data/7/0001/abcd-8k.htm">abcd-8k.htm</a></td><td scope="row">8-K</td></tr>
<tr><td scope="row">2</td><td scope="row">PRESS RELEASE</td><td scope="row"><a href="/Archives/edgar/data/7/0001/ex99-1.htm">ex99-1.htm</a></td><td scope="row">EX-99.1</td></tr></table>"""
ix = ev.parse_index(IDX); assert ix == {"accepted": "2026-03-10 16:05:12", "ex99": "https://www.sec.gov/Archives/edgar/data/7/0001/ex99-1.htm", "main": "https://www.sec.gov/Archives/edgar/data/7/0001/abcd-8k.htm"}
PR = "Exhibit 99.1\nFOR IMMEDIATE RELEASE\nMarch 10, 2026\nAbcd Bio Receives FDA Breakthrough Therapy Designation for ABX-1\nBOSTON, March 10, 2026 -- Abcd Bio (Nasdaq: ABCD) today announced..."
t, lead = ev.headline(PR); assert t == "Abcd Bio Receives FDA Breakthrough Therapy Designation for ABX-1" and lead.startswith("BOSTON")
assert ev.classify("7.01,9.01", PR) == (["FDA·임상"], "호재")
assert ev.classify("3.02", "announced pricing of registered direct offering") == (["공모·사모(희석)"], "악재")
assert ev.classify("", "nothing here")[0] == ["기타"]
days = pd.bdate_range("2026-03-02", "2026-03-31")
assert ev.day0("2026-03-10 16:05:12", "2026-03-10", days) == (pd.Timestamp("2026-03-11"), "장후")          # 장 마감 뒤 → 다음 거래일
assert ev.day0("2026-03-10 07:00:00", "2026-03-10", days) == (pd.Timestamp("2026-03-10"), "장전")
assert ev.day0("2026-03-14 10:00:00", "2026-03-14", days)[0] == pd.Timestamp("2026-03-16")                  # 토요일 → 월요일
assert ev.day0(None, "2026-03-10", days) == (pd.Timestamp("2026-03-11"), "시각 미상")
idx = pd.bdate_range("2026-01-01", periods=80)
c = np.full(80, 1.0); c[49:] = [1.3, 1.5, 1.2, 1.1, 1.1] + [1.1] * 26                                    # 기준일(49) 급등
df = pd.DataFrame({"Open": c, "High": c * 1.1, "Low": c * 0.9, "Close": c, "Volume": 1e5}, index=idx); df.iloc[49, 4] = 1e6; df.iloc[49, 0] = 1.2
iwm = pd.DataFrame({"Close": np.full(80, 100.0)}, index=idx)
acc = (idx[48] + pd.Timedelta(hours=17)).strftime("%Y-%m-%d %H:%M:%S")                                  # 48일 장후 → 기준일 49
rows = ev.label_one([{"accession": "a1", "ticker": "ABCD", "accepted": acc, "filed": idx[48].strftime("%Y-%m-%d")}], df, iwm)
r = rows[0]; print(r)
assert r[2] == idx[49].strftime("%Y-%m-%d") and r[3] == "장후" and abs(r[5] - 20) < 1e-9 and abs(r[6] - 30) < 1e-9 and abs(r[7] - 65) < 1e-6 and abs(r[9] - 10) < 1e-9 and abs(r[10] - 10) < 1e-9 and abs(r[12] - 10) < 1e-9
# 수집기(가짜 SEC)
with closing(db.connect()) as conn:
    secbackfill.ensure_tables(conn)
    conn.execute("INSERT INTO sec_hist VALUES ('0001-26-000001','ABCD','8-K','2026-03-10','7.01,9.01')"); conn.execute("INSERT INTO sec_hist VALUES ('x2','ABCD','10-Q','2026-03-11','')"); conn.commit()
class FC:
    def cik_for(s, t): return 7
    def _get(s, u):
        class R: text = IDX
        return R()
    def fetch_text(s, u, limit=0): assert u.endswith("ex99-1.htm"); return PR
assert ev.collect(FC(), out=lambda *_: None) == 1 and ev.collect(FC(), out=lambda *_: None) == 0         # 8-K만 · 이어받기
with closing(db.connect()) as conn:
    d = dict(conn.execute("SELECT * FROM ev_docs").fetchone()); assert d["accepted"] == "2026-03-10 16:05:12" and d["title"].startswith("Abcd Bio Receives FDA") and json.loads(d["types"]) == ["FDA·임상"]
# 라벨(가짜 일봉) · 통계 · 제안
dfx = pd.DataFrame({"Open": c, "High": c * 1.1, "Low": c * 0.9, "Close": c, "Volume": 1e5}, index=pd.bdate_range("2026-01-01", periods=80))
with closing(db.connect()) as conn:
    conn.execute("UPDATE ev_docs SET accepted=?, filed=?", (acc, idx[48].strftime("%Y-%m-%d"))); conn.commit()
assert ev.label(download=lambda ts: {t: (iwm if t == "IWM" else dfx) for t in ts}, out=lambda *_: None) == 1
tb = ev.table(); s = ev.stats(tb, min_n=1); print(s.to_string()); assert s.iloc[0]["type"] == "FDA·임상" and s.iloc[0]["+20% 이상 확률(%)"] == 100
big = pd.DataFrame({"sentiment": ["호재"] * 40 + ["중립"] * 60, "abn5": [-5.0] * 40 + [2.0] * 60, "up5": [5.0] * 40 + [25.0] * 60})
sg = ev.suggest(big); assert sg[0]["key"] == "RANK_W_NEWS" and sg[0]["new"] == 0.05 and "낮춤" in sg[0]["why"]
print("ALL OK")
# 화면
from datetime import date
import halts, config; halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    for i in range(40):                                                                                  # 호재 공시인데 성과가 평균보다 나쁜 표본
        conn.execute("INSERT INTO ev_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,1)", (f"g{i}", "AAA", "8-K", "1.01", "2025-01-01", None, "Contract award", "", '["계약·수주"]', "호재", now))
        conn.execute("INSERT INTO ev_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"g{i}", "AAA", "2025-01-02", "장후", 0.8, 1, -2, 5, -10, -6, 2, -3, -6))
        conn.execute("INSERT INTO ev_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,1)", (f"n{i}", "AAA", "8-K", "8.01", "2025-01-01", None, "Update", "", '["기타"]', "중립", now))
        conn.execute("INSERT INTO ev_labels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"n{i}", "AAA", "2025-01-02", "장중", 0.8, 0, 1, 25, -5, 3, 1, 1, 3))
    conn.commit()
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ["QUANT_TEST_PAGE"] = "eventlab"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
tbl = [d.value for d in at.dataframe if "D+5 초과수익(%)" in d.value.columns][0]; assert set(tbl["type"]) >= {"계약·수주", "기타"}
at.selectbox(key="ev_type").set_value("계약·수주").run(); assert any("제목" in d.value.columns for d in at.dataframe)
btn = [b for b in at.button if b.key == "ev_apply_RANK_W_NEWS"]; assert btn
btn[0].click().run(); assert config.overrides().get("RANK_W_NEWS") == 0.05
os.environ.pop("QUANT_TEST_PAGE"); print("UI OK")
