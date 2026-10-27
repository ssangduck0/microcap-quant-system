import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, intel, halts, watch, dist_ui
db.init_db(); intel.ensure_table(); halts.fetch = lambda *a, **k: []
rng = np.random.default_rng(0)
now = db.utcnow_iso(); D = "2026-10-14"
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": D, "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -25.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    frame = pd.DataFrame({"Close": np.linspace(1.2, 1.0, 120)}, index=pd.date_range("2026-10-14 13:00", periods=120, freq="min", tz="America/New_York"))
    for i in range(10):
        conn.execute("INSERT OR REPLACE INTO close_flow (minute, ticker, date, buy_sh, sell_sh) VALUES (?,?,?,?,?)", (f"2026-10-14T15:{i:02d}", "AAA", D, 100 + 10 * i, 100.0))
    conn.commit()
    sp, cs = intel.spark_of(frame), intel.cs_spark_of(conn, D, "AAA")
    assert len(sp) == 40 and sp[0] > sp[-1] and cs[0] == 100.0 and cs[-1] == 190.0 and intel.spark_of(None) is None
    intel.save(conn, D, "AAA", {"day": D, "cs": {"late": 140.0, "source": "토스 실시간(체결가↔호가)"}, "spark": sp, "cs_spark": cs, "halt": None, "sec": None, "short": None})
    # 과거 사례 + 공시 백필
    for i in range(300):
        nh = float(rng.lognormal(2.0, 1.0) - 3); nl = float(-abs(rng.normal(10, 8)))
        conn.execute("INSERT INTO case_events (ticker, date, prev_close, close, drop_pct, vol_mult, next_high_pct, next_low_pct, next_close_pct, fwd_5d, max_down_5d, avg_dollar_vol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("ZZZ" if i % 2 else "YYY", f"20{18 + i % 8}-0{1 + i % 9}-1{i % 10}", 1.0, 0.75, -25.0 + (i % 5), 3.0, nh, nl, nh / 3, nh / 4, nl * 1.5, 1e6))
    import secbackfill as sb; sb.ensure_tables(conn)
    conn.execute("INSERT INTO sec_hist VALUES ('x1','ZZZ','424B5','2019-02-10','')"); conn.execute("INSERT INTO sec_hist_progress VALUES ('ZZZ','done',1,'x')")
    conn.commit()
db.save_report("AAA", {"ticker": "AAA", "generated_at": now, "errors": {}, "company": {}, "runway": {},
                       "timeline": [{"date": "2026-09-01", "type": "424B5", "text": "공모", "url": "u"}]})
watch.add_event("AAA", "2026-12-01", "락업 해제(추정)", "락업 90일")
s = dist_ui.tail_stats(db.read_df("SELECT * FROM case_events")); assert s["n"] == 300 and 0 <= s["p100"] <= s["p50"] <= 100 and s["lo_p10"] < 0
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
snap = [d.value for d in at.dataframe if "가격 흐름(2시간)" in d.value.columns][0]
assert list(snap.set_index("티커").loc["AAA", "가격 흐름(2시간)"]) == sp and list(snap.set_index("티커").loc["AAA", "체결강도(30분)"])[-1] == 190.0
mt = [m.label for m in at.metric]; assert "상위 10% 다음날 고가" in mt and "+50% 이상 / +100% 이상" in mt and "하위 10% 다음날 저가" in mt
def count_charts(n):
    k = 1 if getattr(n, "type", "") == "vega_lite_chart" else 0
    ch = getattr(n, "children", None)
    return k + (sum(count_charts(x) for x in ch.values()) if isinstance(ch, dict) else 0)
assert count_charts(at._tree) >= 5                                                        # 분포(히스토그램·산점도) ×2곳 + 타임라인
assert any("🗓 AAA 희석·기한 타임라인" in m.value for m in at.markdown) and any("다가오는 것" in c.value and "락업" in c.value for c in at.caption)
flags = [d.value for d in at.dataframe if "공시 조건" in d.value.columns]; print(flags[0].head(4).to_string(index=False) if flags else "no flags table")
assert flags and flags[0]["사건 수"].sum() > 0
print("ALL OK")
