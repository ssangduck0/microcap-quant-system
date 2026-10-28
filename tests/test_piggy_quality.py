import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, piggy, watch
db.init_db(); piggy.ensure_tables(); watch.ensure_tables()
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=262)[-260:]
c = np.full(260, 0.60); h = c * 1.02
for i, base in ((60, 0.60), (140, 0.62), (220, 0.90)):                         # 3번 급등: 0.60·0.62 근처 발사대(합쳐짐) + 0.90 발사대
    c[i - 10:i] = base; h[i - 10:i] = base * 1.02; h[i] = base * 1.45; c[i] = base * 1.25
for i in (100, 180, 200, 240):                                                  # 발작(+20~25%)
    h[i] = c[i - 1] * 1.22
df = pd.DataFrame({"Open": c, "High": h, "Low": c * 0.98, "Close": c, "Volume": 1e6}, index=idx)
sp = piggy.spike_stats(df, days=252); print(sp); assert sp["spikes30"] == 4 and sp["spikes20"] == 8 and abs(sp["max_spike"] - 53.0) < 1e-6   # 0.60→0.90 계단도 급등 1회
assert piggy.spike_stats(df, days=126)["spikes20"] >= 3
z = piggy.launch_zones(df); print([(round(x["level"], 3), len(x["dates"])) for x in z])
assert len(z) == 2 and abs(z[0]["level"] - 0.607) < 0.01 and len(z[0]["dates"]) == 3 and abs(z[1]["level"] - 0.90) < 1e-9   # 0.60 근처 3번(합쳐짐) + 0.90 1번
nz = piggy.near_zone(0.63, z); assert nz["near"] and abs(nz["level"] - z[0]["level"]) < 1e-9
assert not piggy.near_zone(0.75, z)["near"] and piggy.near_zone(None, z) is None and piggy.launch_zones(None) == []
# 종배 이력(과거 사례 DB)
with closing(db.connect()) as conn:
    for d, o, hi in (("2026-01-05", 12.0, 30.0), ("2026-03-05", -3.0, 5.0), ("2026-06-05", 25.0, 40.0)):
        conn.execute("INSERT INTO case_events (ticker, date, next_open_pct, next_high_pct, next_close_pct) VALUES (?,?,?,?,?)", ("RMSG", d, o, hi, 1.0))
    conn.commit()
    cb = piggy.close_bounce(conn, "rmsg"); print(cb)
    assert cb["n"] == 3 and abs(cb["gap_up_rate"] - 200 / 3) < 1e-9 and abs(cb["open_ge10_rate"] - 200 / 3) < 1e-9 and piggy.close_bounce(conn, "NONE") is None
    # ⑥ 주식수 변동 · ⑦ 희석 구조 변화(이력 없으면 None → 있으면 판정)
    import chartex; chartex.ensure(conn)
    qq = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df, "CLEAN")}
    assert qq["⑥"]["결과"] is None and qq["⑦"]["결과"] is None and len(qq) == 7
    assert qq["⑥"]["값"].startswith("판정 보류 — SEC 표지 없음"), qq["⑥"]
    import shares
    conn.execute(shares.HIST_DDL)
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", [("RMSG", (date.today() - timedelta(days=400)).isoformat(), "f0", "20-F", 900_000),
                                                                             ("RMSG", (date.today() - timedelta(days=35)).isoformat(), "f0", "20-F", 1_000_000)])
    conn.commit()
    qq = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df, "CLEAN")}
    assert qq["⑥"]["결과"] is None and "연 1회 보고(20-F" in qq["⑥"]["값"], qq["⑥"]   # 연 1회 보고는 표지가 2개여도 보류 + 이유 문구(2026-10-28)
    conn.execute("DELETE FROM shares_hist WHERE ticker='RMSG'"); conn.commit()
    # ⑥ SEC 분기 표지 이력(2026-10-28): ChartExchange 가 없을 때 직전 두 분기 표지 비교(1.0M → 1.3M = +30%)
    import shares
    conn.execute(shares.HIST_DDL)
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", [("RMSG", (date.today() - timedelta(days=170)).isoformat(), "f1", "10-Q", 1_000_000),
                                                                             ("RMSG", (date.today() - timedelta(days=80)).isoformat(), "f2", "10-Q", 1_300_000)])
    conn.commit()
    qq = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df, "CLEAN")}
    assert qq["⑥"]["결과"] is False and "+30.0%" in qq["⑥"]["값"] and "SEC 표지" in qq["⑥"]["값"], qq["⑥"]
    conn.execute("INSERT INTO piggy_scan VALUES (?, 'RMSG', 0.6, '{}')", (date.today().isoformat(),)); conn.execute("INSERT INTO piggy_list (ticker) VALUES ('COCH')"); conn.commit()
    assert piggy.share_targets(conn) == ["COCH", "RMSG"]
    for d, so in (((date.today() - timedelta(days=80)).isoformat(), 1_000_000), (date.today().isoformat(), 1_300_000)):
        conn.execute("INSERT OR REPLACE INTO cx_shares VALUES (?,?,?,?,?)", ("RMSG", d, so, so * 0.8, 80.0))
    conn.execute("CREATE TABLE IF NOT EXISTS dilution_hist (ticker TEXT NOT NULL, date TEXT NOT NULL, status TEXT, PRIMARY KEY (ticker, date))")
    conn.execute("INSERT OR REPLACE INTO dilution_hist VALUES ('RMSG', ?, 'CLEAN')", ((date.today() - timedelta(days=60)).isoformat(),))
    conn.execute("INSERT OR REPLACE INTO dilution_hist VALUES ('RMSG', ?, 'ATM')", ((date.today() - timedelta(days=10)).isoformat(),))
    conn.commit()
    qq = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df, "ATM")}
    assert qq["⑥"]["결과"] is False and "+30.0%" in qq["⑥"]["값"] and "ChartExchange" in qq["⑥"]["값"] and qq["⑦"]["결과"] is False and "CLEAN → ATM" in qq["⑦"]["값"], (qq["⑥"], qq["⑦"])   # ChartExchange 이력이 있으면 그게 우선
    conn.execute("UPDATE cx_shares SET shares_out=1_100_000 WHERE ticker='RMSG' AND date=?", (date.today().isoformat(),)); conn.execute("DELETE FROM dilution_hist WHERE status='ATM'"); conn.commit()
    qq = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df, "CLEAN")}
    assert qq["⑥"]["결과"] is True and qq["⑦"]["결과"] is True            # 기간 밖 CLEAN 1건만 남음 → 변화 없음
    conn.execute("INSERT OR REPLACE INTO dilution_hist VALUES ('RMSG', ?, 'CLEAN')", (date.today().isoformat(),)); conn.commit()
    assert {x["기준"][:1]: x["결과"] for x in piggy.quality("RMSG", conn, df, "CLEAN")}["⑦"] is True
    # 5가지 기준
    q = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df, "WARRANT")}
    assert q["①"]["결과"] == "주의"                                                  # 220일째 $1.125 마감 → 최근 $1 미만 39거래일 → 주의
    assert {x["기준"][:1]: x["결과"] for x in piggy.quality("RMSG", conn, df * 0.5, "WARRANT")}["①"] is False   # 1년 내내 $1 미만(180거래일 넘음) → 위험
    q = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df * 3, "WARRANT")}     # $1 위
    assert q["①"]["결과"] is True and q["②"]["결과"] is None and q["③"]["결과"] is True and q["④"]["결과"] is True and q["⑤"]["결과"] is True   # 워런트만 = 통과
    assert {x["기준"][:1]: x["결과"] for x in piggy.quality("RMSG", conn, df, "ATM")}["④"] is False
    db.save_report("RMSG", {"ticker": "RMSG", "generated_at": db.utcnow_iso(), "errors": {}, "runway": {"runway_months": 18.0},
                            "company": {"delisting_notices": [{"filed": (date.today() - timedelta(days=30)).isoformat(), "url": "u"}]}, "timeline": []})
    q2 = {x["기준"][:1]: x for x in piggy.quality("RMSG", conn, df * 3, "CLEAN")}
    assert q2["②"]["결과"] is True and q2["①"]["결과"] == "주의" and "미달 통지" in q2["①"]["값"]        # 최근 1년 안 3.01 통지만 → 주의
    watch.add_event("RMSG", (date.today() + timedelta(days=20)).isoformat(), "상장유지 기한", "회복 기한")
    assert {x["기준"][:1]: x["결과"] for x in piggy.quality("RMSG", conn, df * 3, "CLEAN")}["①"] is False            # 통지 + 기한 60일 이내 → 위험
    low = (df * 3).copy(); low.iloc[-40:, low.columns.get_loc("Close")] = 0.5
    assert {x["기준"][:1]: x["결과"] for x in piggy.quality("XX", conn, low, "CLEAN")}["①"] == "주의"                   # $1 미만 40거래일 → 주의(동전주라도 바로 상폐 아님)
# 호재·시드
piggy.add("RMSG", "기타"); piggy.update("RMSG", catalyst="FDA 결정", catalyst_date="2026-11-20")
r = piggy.items().set_index("ticker").loc["RMSG"]; assert r["catalyst"] == "FDA 결정" and r["catalyst_date"] == "2026-11-20"
assert piggy.seed_krw() is None; piggy.set_seed_krw(20_000_000); assert piggy.seed_krw() == 20_000_000
print("ALL OK")
