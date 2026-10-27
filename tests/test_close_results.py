import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, closewatch as cw, tracker, market
db.init_db(); cw.ensure_tables()
ET = ZoneInfo("America/New_York")
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=32)[-30:]
D0 = idx[20].strftime("%Y-%m-%d"); D1 = idx[-1].strftime("%Y-%m-%d")              # D0: 결과 확인 가능, D1: 마지막 날(다음날 없음)
def frame(entry, nxt):                                                           # nxt: 다음날 (시가, 고가, 저가, 종가) 진입가 대비 %
    c = np.full(30, entry); o = c.copy(); h = c * 1.01; l = c * 0.99
    i = 21
    o[i], h[i], l[i], c[i] = [entry * (1 + x / 100) for x in nxt]
    c[i + 1:] = c[i]; o[i + 1:] = c[i]; h[i + 1:] = c[i] * 1.01; l[i + 1:] = c[i] * 0.99
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1e6}, index=idx)
PX = {"WIN1": frame(1.0, (2, 25, -3, 12)), "WIN2": frame(2.0, (0, 12, -5, -4)), "LOSE": frame(1.0, (-2, 4, -15, -10)), "NOPX": None}
market.download_daily = lambda tk, period="3mo", chunk=40: {t: PX[t] for t in tk if PX.get(t) is not None}
GOOD = {"drop_pct": -35.0, "vol_mult": 5.0, "decay": 0.2, "cs_late": 140.0, "cs_prior": 100.0, "thin_ratio": 0.4, "n_samples": 8, "ask_minutes": 2.0, "top_ask_ratio": 1.5,
        "dilution_status": "CLEAN", "intraday_filings": [], "financing": None, "shares_out": 8e6}
now = db.utcnow_iso(); at = datetime.now(timezone.utc)
with closing(db.connect()) as conn:
    cw.save_list(conn, D0, "frozen", [{"ticker": "WIN1", "rank": 1, "change_pct": -40.0, "price": 1.0}, {"ticker": "WIN2", "rank": 7, "change_pct": -30.0, "price": 2.0},
                                      {"ticker": "LOSE", "rank": 15, "change_pct": -25.0, "price": 1.0}, {"ticker": "NOPX", "rank": 3, "change_pct": -50.0, "price": 1.0}], at)
    cw.save_list(conn, D0, "live", [{"ticker": "LIVEONLY", "rank": 1, "change_pct": -60.0, "price": 1.0}], at)          # 실시간 목록은 추적 대상 아님
    cw.save_list(conn, D1, "frozen", [{"ticker": "WIN1", "rank": 2, "change_pct": -33.0, "price": 1.0}], at)                # 오늘 고정 → 결과 대기
    for t, m in (("WIN1", GOOD), ("WIN2", {**GOOD, "cs_late": 90.0, "thin_ratio": 0.9}), ("LOSE", {**GOOD, "drop_pct": -12.0})):            # BEST / 후보 / 낙폭 미달
        conn.execute("INSERT INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)", (D0, t, json.dumps(m), now))
    conn.commit()
    lines = []
    r = tracker.update_close(conn, out=lines.append, now=datetime.combine(idx[-1].date(), time(17, 0), ET)); print(r, lines)
    assert r["rows"] == 5 and r["updated"] >= 4                                                              # NOPX 는 가격 없음 → 14일 지나 no_data 또는 대기
    o = {x["ticker"]: dict(x) for x in conn.execute("SELECT * FROM close_outcomes WHERE date=?", (D0,))}
    assert abs(o["WIN1"]["next_high_pct"] - 25) < 1e-6 and abs(o["WIN1"]["next_close_pct"] - 12) < 1e-6 and abs(o["LOSE"]["next_low_pct"] + 15) < 1e-6
    assert "LIVEONLY" not in o and o["WIN1"]["entry_close"] == 1.0
    d1 = conn.execute("SELECT * FROM close_outcomes WHERE date=?", (D1,)).fetchone(); assert d1 is not None and d1["next_high_pct"] is None   # 다음날 없음
    # 매일 아침 자동 갱신(tracker.update) 안에서도 실행
    conn.execute("DELETE FROM close_outcomes"); conn.commit()
    res = tracker.update(conn, out=lambda *_: None, now=datetime.combine(idx[-1].date(), time(17, 0), ET)); assert res["close"]["updated"] >= 4
print("tracker OK")
# ---------- 화면 ----------
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": D1, "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -40.0,
                              "day_change_pct": -15.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
                              "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
import halts; halts.fetch = lambda *a, **k: []
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at_ = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at_.exception]); assert not at_.exception
def rmet(at):  # 결과 추적 영역의 지표(다른 탭에도 같은 이름이 있어서 '고정 종목'부터 5개만)
    ms = list(at.metric); i = [m.label for m in ms].index("고정 종목"); return {m.label: m.value for m in ms[i:i + 5]}
mt = rmet(at_); print(mt)
assert mt["고정 종목"] == "5" and mt["결과 확인"] == "3" and mt["반등 성공 (≥ +10%)"] == "2" and mt["성공률"] == "66.7%" and mt["다음날 종가 중앙값"] == "-4.0%"
def tbl(col): return [d.value for d in at_.dataframe if col in d.value.columns]
gt = tbl("등급")
grade = [d for d in gt if "성공률(%)" in d.columns][0].set_index("등급"); print(grade.to_string())
assert grade.loc["BEST", "반등"] == 1 and grade.loc["후보", "반등"] == 1 and grade.loc["낙폭 미달", "반등"] == 0 and grade.loc["낙폭 미달", "성공률(%)"] == 0.0
band = [d.value for d in at_.dataframe if "순위대" in d.value.columns][0].set_index("순위대"); assert band.loc["1~5위", "종목 수"] == 3 and band.loc["11~20위", "반등"] == 0
lists = [d.value for d in at_.dataframe if "결과" in d.value.columns and "토스 순위" in d.value.columns]
succ = [d for d in lists if set(d["결과"]) == {"✅ 반등"}][0]; fail = [d for d in lists if set(d["결과"]) == {"❌ 실패"}][0]
print(succ[["날짜", "티커", "토스 순위", "등급", "다음날 고가(%)", "다음날 종가(%)"]].to_string(index=False)); print(fail[["티커", "등급", "미충족", "다음날 고가(%)", "다음날 저가(%)"]].to_string(index=False))
assert set(succ["티커"]) == {"WIN1", "WIN2"} and list(fail["티커"]) == ["LOSE"] and "낙폭" in fail.iloc[0]["미충족"]
assert any("⏳ 대기" in set(d["결과"]) for d in lists)
# 기준 변경: 다음날 종가 +10% → WIN1 만 성공 / 반등 기준 20% → WIN1 만
at_.selectbox(key="cr_basis").set_value("다음날 종가").run(); assert rmet(at_)["반등 성공 (≥ +10%)"] == "1"
at_.selectbox(key="cr_basis").set_value("다음날 고가").run(); at_.slider(key="cr_target").set_value(20).run()
assert rmet(at_)["반등 성공 (≥ +20%)"] == "1"
at_.radio(key="cr_mode").set_value("오늘 탭의 기준값").run(); assert not at_.exception
# 갱신 버튼
calls = []; orig = tracker.update_close
tracker.update_close = lambda conn, **k: (calls.append(1), {"updated": 0, "pending": 0})[1]
[b for b in at_.button if b.label == "🔄 결과 지금 갱신"][0].click().run(); assert calls and not at_.exception
tracker.update_close = orig
# 거래정지 현황과 오늘 체크리스트도 같은 탭 안에서 계속 동작
assert any("오늘 거래정지 현황" in m.value for m in at_.markdown) and not at_.exception
print("ALL OK")
