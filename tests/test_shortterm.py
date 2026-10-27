import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, exthilo, timemachine as tm, setup3 as s3, secbackfill
db.init_db()
T = date.today()

# --- 🌙 세션 구분(동부시간): 데이마켓(20시 이후 → 다음 거래일) · 프리 · 정규 · 애프터 · 더 높은 값만 갱신
ix = pd.to_datetime(["2026-10-22 21:00", "2026-10-23 05:00", "2026-10-23 10:00", "2026-10-23 17:00", "2026-10-23 21:00"]).tz_localize("America/New_York")
f = pd.DataFrame({"High": [1.5, 1.2, 1.1, 1.8, 2.0], "Low": [1.0, 1.0, 0.9, 1.0, 1.0]}, index=ix)
ss = exthilo.sessions(f)
assert {k: v for k, v in ss["2026-10-23"].items() if not k.endswith("_low") or k == "day_low"} == {"night_high": 1.5, "pre_high": 1.2, "reg_high": 1.1, "post_high": 1.8, "day_low": 0.9}, ss
assert ss["2026-10-23"]["reg_low"] == 0.9 and ss["2026-10-23"]["post_low"] == 1.0   # 세션별 최저가(가상매매 판정용)
assert ss["2026-10-26"]["night_high"] == 2.0                                     # 금요일 21시 = 월요일 거래일의 데이마켓
with closing(db.connect()) as conn:
    exthilo.record(conn, {"AAA": f})
    exthilo.record(conn, {"AAA": f.assign(High=f["High"] * 0.5)})              # 낮은 값으로는 안 바뀜
    r = conn.execute("SELECT pre_high, post_high FROM ext_hilo WHERE date='2026-10-23' AND ticker='AAA'").fetchone()
    assert tuple(r) == (1.2, 1.8)
    dh = exthilo.day_highs(conn, ["AAA"], "2026-10-01")
    assert dh["AAA"]["2026-10-23"] == 1.8

# --- ⚡ 단타 기준: 목표에 닿으면 그 가격, 못 닿으면 5일째 종가 · 분할 · 시간외 고점 반영
idx = pd.bdate_range(start="2025-01-02", periods=120)
c = np.r_[np.full(100, 1.0) + np.sin(np.arange(100) / 3) * 0.05, [1.0, 1.05, 1.12, 1.0, 0.95, 0.9], np.full(14, 0.9)]
d = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": np.full(120, 2e5)}, index=idx)
k = idx[99].strftime("%Y-%m-%d")
row = {x["date"]: x for x in tm.ticker_rows("X", d, [], k, k, step=1)}[k]
c0 = c[99]; c5 = (c[104] / c0 - 1) * 100; pk = (max(c[100:105] * 1.01) / c0 - 1) * 100
assert abs(row["p5"] - pk) < 1e-6 and row["done5"] and abs(row["c5"] - c5) < 1e-6
assert row["ev10"] == (10.0 if pk >= 10 else c5) and row["ev30"] == c5                    # +30% 못 닿음 → 5일째 종가
assert abs(row["ev_split"] - sum((t if pk >= t else c5) for t in (10, 20, 30)) / 3) < 1e-9
ext = {idx[102].strftime("%Y-%m-%d"): c0 * 1.6}                                            # 애프터에 +60% 찍은 날
row2 = {x["date"]: x for x in tm.ticker_rows("X", d, [], k, k, step=1, ext=ext)}[k]
assert row2["p5"] >= 59.9 and row2["ev50"] == 50.0 and row2["ext_days"] == 1                 # 시간외 고점으로 +50% 목표 달성
row3 = {x["date"]: x for x in tm.ticker_rows("X", d, [], k, k, step=1, ext={idx[102].strftime("%Y-%m-%d"): c0 * 80})}[k]
assert row3["p5"] < 59                                                                       # 단위가 다른(20배↑) 값은 무시
# 📡 숏 조건(C단계): 공개 지연 뒤부터 켜짐 · 조합 집계에 포함
import chartex
with closing(db.connect()) as conn:
    chartex.ensure(conn)
    rep = idx[50].strftime("%Y-%m-%d")
    conn.execute("INSERT INTO cx_short_interest VALUES ('X', ?, 30.0, 1000, 2.0, 400, 66.7, 1)", (rep,))
    for j in range(30):
        conn.execute("INSERT INTO cx_ftd VALUES ('X', ?, NULL, ?, 1.0, 0, NULL, 0)", (idx[20 + j].strftime("%Y-%m-%d"), 90_000 if j == 29 else 5_000))
    conn.execute("INSERT INTO cx_short_volume VALUES ('X', ?, 1000000, 650000, 350000, 600000, 50000, 0, 65.0)", (idx[60].strftime("%Y-%m-%d"),))
    conn.commit()
    sf = tm.short_flags(conn, ["X", "Y"])
assert set(sf) == {"X"} and tm._bday_shift(rep, 9) in sf["X"]["si_up"] and rep not in sf["X"]["si_up"] and len(sf["X"]["si_up"]) == 10      # 보고일 당일엔 모름
assert tm._bday_shift(idx[49].strftime("%Y-%m-%d"), 15) in sf["X"]["ftd_spike"] and len(sf["X"]["sv60"]) == 1 and idx[61].strftime("%Y-%m-%d") in sf["X"]["sv60"]
rs_ = {x["date"]: x for x in tm.ticker_rows("X", d, [], idx[40].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d"), step=1, shorts=sf["X"])}
assert rs_[tm._bday_shift(rep, 9)]["si_up"] and not rs_[rep]["si_up"] and rs_[idx[61].strftime("%Y-%m-%d")]["sv60"] and rs_[idx[61].strftime("%Y-%m-%d")]["short_any"]
assert not tm.ticker_rows("X", d, [], idx[40].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d"), step=1)[0]["short_any"]                  # shorts 없으면 꺼짐
assert all(("gc3" in x and "pb" in x) for x in rs_.values())                                                        # 📐 스승 관점 깃발이 모든 행에
smx = tm.summarize(pd.DataFrame(list(rs_.values())))
assert any(c_["조합"].startswith("📐") for c_ in smx["combos"]) and "📐 허리 눌림+③" in tm.KEY_COMBOS
assert any(c_["조합"].startswith("📡 숏 잔고 보고") for c_ in smx["combos"]), [c_["조합"] for c_ in smx["combos"]][-9:]
sm = tm.summarize(pd.DataFrame(tm.ticker_rows("X", d, [], idx[40].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d"), step=1)))
assert sm["short"] and sm["short"][0]["조합"] == "전체(기준)" and "수익 분할 10·20·30(%)" in sm["short"][0]

# --- 🏆 신호 난 날의 조건(그날까지 정보만) · 출처별 갖춤/안 갖춤 성공률
with closing(db.connect()) as conn:
    for d_ in secbackfill.DDL:
        conn.execute(d_)
    db.upsert_daily_prices(conn, "AAA", d)
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('x1','AAA','424B5',?, '')", (idx[95].strftime("%Y-%m-%d"),))
    conn.commit()
    pairs = [("AAA", idx[94].strftime("%Y-%m-%d")), ("AAA", idx[99].strftime("%Y-%m-%d")), ("ZZZ", idx[99].strftime("%Y-%m-%d"))]
    cd = s3.conditions_at(conn, pairs)
    assert cd[pairs[0]]["dil"] == 1 and cd[pairs[1]]["dil"] == 0 and pairs[2] not in cd     # 공시 전날엔 '희석 없음', 뒤엔 '있음' · 일봉 없으면 빠짐
    assert conn.execute("SELECT COUNT(*) FROM s3_cond").fetchone()[0] == 2
sbdf = pd.DataFrame([{"출처": "A", "ticker": "AAA", "date": pairs[0][1], "status": "성공"}, {"출처": "A", "ticker": "AAA", "date": pairs[1][1], "status": "실패"}])
rep = s3.condition_report(sbdf, cd)
r3 = rep[(rep["출처"] == "A") & (rep["조건"] == "③ 희석 없음")].iloc[0]
assert r3["갖춤 신호"] == 1 and r3["갖춤 성공률(%)"] == 100.0 and r3["안 갖춤 성공률(%)"] == 0.0 and r3["차이(%p)"] == 100.0

# --- 🏁 종합 순위 카드: ①②③ 표시
import rank_ui, watch_ui
up = pd.DataFrame({"Open": 1.0, "High": 1.02, "Low": 0.98, "Close": np.r_[np.full(30, 1.0), np.linspace(1.0, 1.3, 10)],
                   "Volume": np.r_[np.full(30, 1e5), np.full(10, 3e5)]}, index=pd.bdate_range(start=pd.Timestamp(T) - pd.Timedelta(days=70), periods=40))
watch_ui.prices = lambda tks: {"OK": up}
mk = rank_ui.s3_marks.__wrapped__(("OK",)) if hasattr(rank_ui.s3_marks, "__wrapped__") else rank_ui.s3_marks(("OK",))
assert "①💰" in mk["OK"], mk
# --- 🌙 최근 60일 시간외 분봉 채우기 · 정규장만 vs 시간외 포함 비교
with closing(db.connect()) as conn:
    db.upsert_daily_prices(conn, "BBB", pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1e5},
                                                      index=pd.bdate_range(start=pd.Timestamp(T) - pd.Timedelta(days=30), periods=10)))
calls = []
def _dl(ts):
    calls.append(list(ts))
    return {t: f for t in ts}
n_b = exthilo.backfill(days=60, download=_dl, out=lambda *_: None)
assert n_b >= 1 and any("BBB" in c for c in calls)
assert exthilo.backfill(days=60, download=_dl, out=lambda *_: None) == 0                # 받은 종목은 다시 안 받음
ext_all = {x.strftime("%Y-%m-%d"): v for x, v in zip(idx, c * 1.25)}                       # 모든 날 시간외 고점이 종가의 +25%
rows_e = tm.ticker_rows("X", d, [], idx[40].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d"), step=1, ext=ext_all)
r0 = next(x for x in rows_e if x["done5"])
assert r0["p1"] > r0["p1r"] and r0["ext_days"] == 5
sm2 = tm.summarize(pd.DataFrame(rows_e))
ec = sm2["ext_cmp"][0]
assert ec["조합"] == "전체(기준)" and ec["D+1 +10% 시간외 포함(%)"] >= ec["D+1 +10% 정규장만(%)"] and ec["D+1 +10% 시간외 포함(%)"] == 100.0
# --- ⏱ 못 튀면 며칠째 정리: x일째까지 닿은 목표는 그 가격, 나머지는 x일째 종가
cx1 = (c[100] / c0 - 1) * 100; pk1 = (c[100] * 1.01 / c0 - 1) * 100
assert abs(row["evx1"] - sum((t if pk1 >= t else cx1) for t in (10, 20, 30)) / 3) < 1e-9 and row["evx5"] == row["ev_split"]
assert sm["exit_days"] and "1일째 정리 · 전체(%)" in sm["exit_days"][0]
print("ALL OK")
