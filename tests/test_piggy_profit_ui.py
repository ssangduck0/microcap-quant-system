import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, piggy, watch, market, halts, notes_ui
db.init_db(); piggy.ensure_tables(); watch.ensure_tables(); halts.fetch = lambda *a, **k: []; db.set_meta("usdkrw", "1342.0")
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=262)[-260:]
c = 0.55 + 0.05 * np.sin(np.arange(260) / 3.0); h = c * 1.02
for i in (60, 140, 230):                                                          # 0.55 근처에서 횡보하다 +40% 급등(발사대)
    h[i] = c[i - 1] * 1.40
for i in (180, 200, 245, 250):
    h[i] = c[i - 1] * 1.22                                                        # 간간이 발작
RM = pd.DataFrame({"Open": c, "High": h, "Low": c * 0.98, "Close": c, "Volume": 2e5}, index=idx)
market.download_daily = lambda tk, period="3mo", chunk=200: {x: (RM.tail(5) if period == "5d" else RM.tail(126) if period == "6mo" else RM) for x in tk if x == "RMSG"}
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": idx[-1].strftime("%Y-%m-%d"), "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0,
        "low_20d": 0.9, "drawdown_pct": -40.0, "day_change_pct": -15.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0,
        "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    db.save_dilution(conn, {"ticker": "RMSG", "cik": 1, "status": "WARRANT", "flags": {}, "evidence": []})
    conn.execute("INSERT OR REPLACE INTO case_progress (ticker, status) VALUES ('RMSG', 'done')")
    for d, o in (("2025-12-01", 15.0), ("2026-02-01", 8.0), ("2026-05-01", -2.0)):
        conn.execute("INSERT INTO case_events (ticker, date, next_open_pct, next_high_pct, next_close_pct) VALUES (?,?,?,?,?)", ("RMSG", d, o, o + 10, 1.0))
    conn.commit()
db.save_report("RMSG", {"ticker": "RMSG", "generated_at": now, "errors": {}, "runway": {"runway_months": 20.0}, "company": {}, "timeline": []})
piggy.add("RMSG", "기타", budget_krw=3_000_000); piggy.set_seed_krw(20_000_000)
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
assert piggy.PROFIT_TIP_TITLE in notes_ui.list_titles()
lst = [d.value for d in at.dataframe if "손익비 기준" in d.value.columns][0]; row = lst.set_index("티커").loc["RMSG"]; print(row[["손익비 기준", "발사대", "시드 대비(%)"]].to_dict())
assert row["손익비 기준"] == "4/7 ❌✅✅✅✅➖➖" and row["발사대"].startswith("🎯") and abs(row["시드 대비(%)"] - 15.0) < 1e-9   # ① 1년 내내 $1 미만(180일 넘음) = 위험, ②~⑤ 통과 · ⑥⑦ 은 이력 없어 ➖(2026-10-27 기준 7개)
assert any("시드의 10%를 넘는 종목: RMSG" in w.value for w in at.warning)
q = [d.value for d in at.dataframe if "기준" in d.value.columns and "값" in d.value.columns][0].set_index("기준")
assert q.loc["① 상폐 위험 없음", "결과"] == "❌ 미달" and q.loc["② 펀더멘탈 단단(런웨이 12개월 이상)", "결과"] == "✅ 통과" and q.loc["④ 시장가 희석 없음(ATM·ELOC·전환사채 아님)", "결과"] == "✅ 통과"
zones = [d.value for d in at.dataframe if "자리($)" in d.value.columns][0]; assert len(zones) >= 1 and zones["횟수"].sum() >= 3
assert {m.label: m.value for m in at.metric}["다음날 갭 상승 비율"] == "67%"
assert any("앞으로 예정된 호재" in c.value and "RMSG" in c.value for c in at.code)
# 호재 저장 → 🗓 일정에 추가
at.text_input(key="pg_cat_txt_RMSG").set_value("FDA 결정"); at.text_input(key="pg_cat_dt_RMSG").set_value("2026-11-20")
[b for b in at.button if b.key == "pg_cat_save_RMSG"][0].click().run(); assert not at.exception
assert piggy.items().set_index("ticker").loc["RMSG", "catalyst"] == "FDA 결정" and (watch.events_df(["RMSG"])["title"] == "호재: FDA 결정").any()
# 후보 찾기: 발작·급등 필터
[b for b in at.button if b.key == "ps_run"][0].click().run(); assert not at.exception
_, sc = piggy.latest_scan(); assert sc.iloc[0]["spikes20"] >= 3
at.slider(key="ps_score").set_value(0).run(); at.slider(key="ps_b").set_value(0).run(); at.slider(key="ps_w").set_value((0, 150)).run(); at.number_input(key="ps_dv").set_value(0).run()
cands = [d.value for d in at.dataframe if "발작(6개월)" in d.value.columns]; print(cands[0][["티커", "발작(6개월)", "급등 +30%(6개월)"]].to_string(index=False) if cands else "none")
assert cands and "RMSG" in set(cands[0]["티커"])
at.slider(key="ps_spk").set_value(9).run(); assert not [d.value for d in at.dataframe if "발작(6개월)" in d.value.columns]          # 발작 9회 이상 → 없음
print("ALL OK")
