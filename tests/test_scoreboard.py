import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, scoreboard as sb, closewatch as cw, shortflow, flowread, afterscalp, pumpsetup, piggy, rsplit
db.init_db(); cw.ensure_tables(); piggy.ensure_tables()
idx = pd.bdate_range("2026-09-01", "2026-10-14")
def mk(c): c = np.asarray(c, float); return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c}, index=idx)
n = len(idx); up = mk(np.r_[np.full(10, 1.0), np.linspace(1.0, 1.5, n - 10)]); down = mk(np.r_[np.full(10, 1.0), np.linspace(1.0, 0.7, n - 10)])
PX = {"UPX": up, "DNX": down}
D = idx[9].strftime("%Y-%m-%d"); LAST = idx[-1].strftime("%Y-%m-%d")
GOOD = {"drop_pct": -35.0, "vol_mult": 5.0, "decay": 0.2, "cs_late": 140.0, "cs_prior": 100.0, "thin_ratio": 0.4, "n_samples": 8, "ask_minutes": 2.0, "top_ask_ratio": 1.5,
        "dilution_status": "CLEAN", "intraday_filings": [], "financing": None, "shares_out": 8e6}
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    from datetime import datetime, timezone
    cw.save_list(conn, D, "frozen", [{"ticker": "UPX", "rank": 1, "change_pct": -30.0, "price": 1.0}, {"ticker": "DNX", "rank": 2, "change_pct": -30.0, "price": 1.0}], datetime.now(timezone.utc))
    for t in ("UPX", "DNX"): conn.execute("INSERT INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)", (D, t, json.dumps(GOOD), now))
    db.upsert_snapshot(conn, {"date": D, "ticker": "UPX", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -15.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0, "win_score": 80.0})
    shortflow.record(conn, "DNX", D, shortflow.STAGES[0], 1.0)                                   # ④ 청산 → 내려가야 성공
    flowread.record(conn, "UPX", D, flowread.KINDS["dist"], 1.0)                                   # 분산 → 올라서 실패
    afterscalp.record_signal(conn, D, "AFT", datetime.now(timezone.utc), 2.0); afterscalp.update_outcome(conn, D, "AFT", {"first_hit": "목표 +5%", "max_up": 6.0})
    afterscalp.record_signal(conn, LAST, "AF2", datetime.now(timezone.utc), 2.0)                     # 오늘 신호 → 대기
    pumpsetup.ensure_tables(conn); conn.execute("INSERT INTO setup_first VALUES ('UPX', ?, 1.0, 5)", (D,))
    conn.execute("INSERT INTO piggy_events VALUES (?, 'UPX', 1.0, 0.95, 1.2)", (D,)); conn.commit()
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_signals VALUES (?, 'DNX', 1.0, 60.0, 30, 1.3, 'x')", (D,)); conn.execute("INSERT INTO rs_signals VALUES (?, 'UPX', NULL, 60.0, 30, 1.3, 'x')", (LAST,)); conn.commit()
    p = sb.collect(conn); print(p[["source", "ticker", "target", "horizon", "direction"]].to_string(index=False))
    assert set(p["source"]) == {"close", "score", "shortflow_exit", "flow_down", "after", "setup", "piggy", "rsplit"}
    assert abs(p[p.source == "piggy"].iloc[0]["target"] - 20.0) < 1e-9                                # 박스 상단까지 +20%
    r = sb.update(conn, today=date(2026, 10, 14), out=lambda *_: None, download=lambda tk: {t: PX[t] for t in tk if t in PX})
    tb = sb.table(conn).set_index(["source", "ticker", "date"])
st = tb["status"].to_dict(); print({k: v for k, v in st.items()})
exp = {("close", "UPX"): "실패", ("close", "DNX"): "실패", ("score", "UPX"): "실패", ("shortflow_exit", "DNX"): "성공", ("flow_down", "UPX"): "실패",
       ("after", "AFT"): "성공", ("setup", "UPX"): "성공", ("piggy", "UPX"): "성공", ("rsplit", "DNX"): "실패"}
for (src, t), v in exp.items(): assert st[(src, t, D)] == v, (src, t, st[(src, t, D)])
assert st[("after", "AF2", LAST)] == "대기" and st[("rsplit", "UPX", LAST)] == "대기"                 # 오늘 신호는 대기
t2 = sb.table(db.connect()); assert t2.set_index(["source", "ticker"]).loc[("shortflow_exit", "DNX"), "close_h"] < 0
# 기간 묶기 · 요약
pk = sb.period_key(pd.Series(["2026-10-12", "2026-10-14", "2026-12-31"]), "주간"); assert list(pk) == ["2026-W42", "2026-W42", "2026-W53"]
assert list(sb.period_key(pd.Series(["2026-10-12"]), "월간")) == ["2026-10"] and list(sb.period_key(pd.Series(["2026-10-12"]), "연간")) == ["2026"]
sm = sb.summarize(t2).set_index("출처"); print(sm.to_string())
assert abs(sm.loc["🎯 장마감 체크리스트(BEST·후보)", "평균 최고 상승(%)"] - t2[t2.source == "close"]["max_up"].mean()) < 1e-9 and t2[t2.source == "close"]["entry"].notna().all()   # 진입가 없는 신호도 신호일 종가로 계산
assert sm.loc["🌙 애프터 진입 구간", "성공률(%)"] == 50.0 or sm.loc["🌙 애프터 진입 구간", "대기"] == 1
# 이미 판정된 예측은 다시 계산하지 않음
calls = []
with closing(db.connect()) as conn:
    sb.update(conn, today=date(2026, 10, 14), out=lambda *_: None, download=lambda tk: (calls.append(list(tk)), {t: PX[t] for t in tk if t in PX})[1])
assert calls == [["UPX"]]                                                                       # 대기 중인 rsplit UPX(오늘)만 다시
print("ALL OK")
