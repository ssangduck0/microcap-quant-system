"""🔁 리셋 사이클(resetcycle + 탭) — 달력(상환일 굴림) · 10일 창 · 병합 환산 · 시나리오 · 과거 사이클 재측정(컨닝 없음) · 설정 변경 반영 · 방문객 숨김 · 화면 AppTest."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, shutil
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date
import numpy as np, pandas as pd
import db, resetcycle as rc
db.init_db()

# ---- 달력: 9/5(토) → 노동절(월) → 9/8(화) · 콜럼버스의 날은 개장 · 추수감사절·성금요일 휴장
hol = rc.holidays(2025, 2026)
assert date(2026, 11, 26) in hol and date(2026, 4, 3) in hol and date(2026, 10, 12) not in hol and date(2026, 11, 11) not in hol
assert rc.redeem_for(2026, 9, 5, hol) == date(2026, 9, 8) and rc.redeem_for(2026, 11, 5, hol) == date(2026, 11, 5) and rc.redeem_for(2026, 7, 5, hol) == date(2026, 7, 6)
cfg0 = {"redeem_day": 5}
assert rc.next_redeem(date(2026, 10, 30), cfg0, hol) == date(2026, 11, 5) and rc.next_redeem(date(2026, 11, 5), cfg0, hol) == date(2026, 11, 5)
assert rc.next_redeem(date(2026, 11, 6), cfg0, hol) == date(2026, 12, 7) and rc.next_redeem(date(2026, 12, 8), cfg0, hol) == date(2027, 1, 5)
assert rc.trading_days_between(date(2026, 10, 29), date(2026, 11, 5), hol) == [date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]

# ---- 가짜 일봉(10/30 1:6 병합 **전** 기준 = 야후가 아직 안 고친 상태) 7/20 ~ 10/29
idx = pd.bdate_range("2026-07-20", "2026-10-29")
rng = np.random.default_rng(7)
c = np.linspace(3.0, 0.24, len(idx)); v = rng.integers(200_000, 3_000_000, len(idx)).astype(float)
df = pd.DataFrame({"Open": c, "High": c * 1.05, "Low": c * 0.95, "Close": c, "Volume": v}, index=idx)

# ---- 설정 씨앗(WHLR) 이 들어가고 has() 가 참
assert rc.has("WHLR") and not rc.has("ZZZZ") and rc.tickers() == ["WHLR"]
cfg = rc.config("whlr"); assert cfg["window_days"] == 10 and abs(cfg["discount_pct"] - 45) < 1e-9 and abs(cfg["split_ratio"] - 1 / 6) < 1e-9
assert [x["seq"] for x in rc.cycles("WHLR")] == [35, 36, 37]

# ---- 병합 환산: 병합일(10/30) 이 마지막 봉(10/29) 뒤 → 전부 ×6 · 거래량 ÷6
sp = rc.splits("WHLR", cfg); assert sp == [("2026-10-30", 1 / 6)]
d6, notes = rc.to_current(df, sp)
assert notes == ["2026-10-30 1:6 병합 환산(×6)"] and abs(d6["Close"].iloc[-1] - 0.24 * 6) < 1e-9 and abs(d6["Volume"].iloc[-1] - v[-1] / 6) < 1e-6
# 이미 환산된 자료(점프 없음)는 다시 안 곱한다 · 미환산 자료(병합일 전후 ×6 점프)는 곱한다
adj = d6.copy(); adj.loc["2026-10-30"] = [1.5, 1.6, 1.4, 1.5, 500_000.0]
_, n2 = rc.to_current(adj, sp); assert n2 == [], n2
raw = df.copy(); raw.loc["2026-10-30"] = [1.5, 1.6, 1.4, 1.5, 500_000.0]
d7, n3 = rc.to_current(raw, sp); assert n3 == ["2026-10-30 1:6 병합 환산(×6)"] and abs(d7.loc["2026-10-29", "Close"] - 0.24 * 6) < 1e-9 and abs(d7.loc["2026-10-30", "Close"] - 1.5) < 1e-9
assert abs(rc.factor_after(sp, "2026-10-05") - 6) < 1e-9 and abs(rc.factor_after(sp, "2026-10-30") - 1) < 1e-9

# ---- 창 · 기준가 · 시나리오(10/30 기준: 11/5 상환 → 창 10/22~11/4 = 확정 6 + 가정 4)
r = rc.compute("WHLR", df, today=date(2026, 10, 30))
assert r["redeem"] == date(2026, 11, 5) and r["dday"] == 6 and r["known_n"] == 6 and len(r["window"]) == 10
assert [w["date"].isoformat() for w in r["window"]][:2] == ["2026-10-22", "2026-10-23"] and [w["date"].isoformat() for w in r["window"]][-1] == "2026-11-04"
kn = [w for w in r["window"] if w["known"]]
hand = sum(w["close"] * w["vol"] for w in kn) / sum(w["vol"] for w in kn)
assert abs(r["base_known"] - hand) < 1e-9 and abs(kn[-1]["close"] - 0.24 * 6) < 1e-9   # 환산된 값으로 계산
s0 = next(s for s in r["scenarios"] if s["pct"] == 0)
closes = [w["close"] for w in kn] + [r["last_close"]] * 4; vols = [w["vol"] for w in kn] + [r["assume_vol"]] * 4
assert abs(s0["base"] - sum(a * b for a, b in zip(closes, vols)) / sum(vols)) < 1e-9 and abs(s0["conv"] - s0["base"] * 0.55) < 1e-9
assert abs(s0["pref_shares"] - 41.96 / s0["conv"]) < 1e-9 and abs(s0["cur_over_conv"] - r["last_close"] / s0["conv"]) < 1e-9
sm = next(s for s in r["scenarios"] if s["pct"] == -0.4); assert sm["conv"] < s0["conv"] and sm["future_weight"] > 0
r2 = rc.compute("WHLR", df, today=date(2026, 10, 30), assume_vol=1e9)        # 가정 거래량이 크면 남은 날이 평균을 지배
s02 = next(s for s in r2["scenarios"] if s["pct"] == 0); assert abs(s02["base"] - r["last_close"]) < 1e-3 and s02["future_weight"] > 0.99
# 어음(미가동): 하루 $100K ÷ max(종가, 하한 0.25)
nt = r["note"]; assert nt and not nt["active"] and abs(nt["shares"] - 100_000 / (0.24 * 6)) < 1e-6 and abs(nt["pct_out"] - nt["shares"] / 979_000 * 100) < 1e-9
assert r["pref_over_mcap"] and r["pref_over_mcap"] > 10   # 잔여 우선주 청산가치 ≫ 시총

# ---- 과거 사이클 재측정: 발표값 ×(그 뒤 병합) · 상환일 이전 10봉만 사용(컨닝 없음)
rp = {x["seq"]: x for x in r["replay"]}
assert set(rp) == {35, 36, 37} and abs(rp[37]["announced"] - 2.73 * 6) < 1e-9 and abs(rp[35]["announced"] - 0.40 * 6) < 1e-9
assert all(x["bars_before"] == 10 for x in rp.values()) and all(x["close_ratio"] and x["low_ratio"] and x["high_ratio"] for x in rp.values())
w37 = d6[d6.index < "2026-10-05"].tail(10); b37 = (w37["Close"] * w37["Volume"]).sum() / w37["Volume"].sum()
assert abs(rp[37]["calc"] - b37 * 0.55) < 1e-9
cheat = df.copy(); m = cheat.index >= "2026-10-05"; cheat.loc[m, ["Open", "High", "Low", "Close"]] *= 50; cheat.loc[m, "Volume"] *= 1000   # 상환일 뒤를 바꿔도
rc2 = {x["seq"]: x for x in rc.compute("WHLR", cheat, today=date(2026, 10, 30))["replay"]}
assert abs(rc2[37]["calc"] - rp[37]["calc"]) < 1e-9 and rc2[37]["high_ratio"] > rp[37]["high_ratio"]   # 기준가는 그대로, 결과만 달라짐
# 나스닥 2년 규정: 설정 병합 1건(10/30) → 1년 안 병합 있음 → 유예 없음
sr = r["split_rule"]; assert sr["n2y"] == 1 and sr["within1y"] and sr["flag"]
assert "11/5" in rc.kst_note(date(2026, 11, 5)) and "06:00" in rc.kst_note(date(2026, 11, 5))   # 11월은 서머타임 끝 → 23:30~06:00
assert "05:00" in rc.kst_note(date(2026, 10, 5))

# ---- 설정을 바꾸면 결과가 바뀐다 · 사이클 추가
rc.save_config("WHLR", discount_pct=50.0, window_days=5)
r3 = rc.compute("WHLR", df, today=date(2026, 10, 30)); s03 = next(s for s in r3["scenarios"] if s["pct"] == 0)
assert len(r3["window"]) == 5 and abs(s03["conv"] - s03["base"] * 0.5) < 1e-9
rc.save_config("WHLR", discount_pct=45.0, window_days=10)
rc.add_cycle("WHLR", "2026-07-06", 34, 0.20, "test"); assert [x["seq"] for x in rc.cycles("WHLR")][0] == 34
rc.save_config("ABCD", label="다른 종목", discount_pct=40.0); assert rc.has("ABCD") and rc.config("ABCD")["discount_pct"] == 40.0
assert rc.compute("ZZZZ", df) is None
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM reset_config WHERE ticker='ABCD'"); conn.execute("DELETE FROM reset_cycles WHERE seq=34"); conn.commit()

# ---- 아침 메모: D-3 밖이면 로그만 · 안이면 텔레그램(가짜) · 일봉 없으면 로그만
sent, logs = [], []
assert rc.morning(out=logs.append, today=date(2026, 10, 30), download=lambda t: df, send=lambda m: sent.append(m) or True) == []
assert len(logs) == 1 and "WHLR" in logs[0] and "D-6" in logs[0] and "전환가 시나리오" in logs[0] and sent == []
assert rc.morning(out=logs.append, today=date(2026, 11, 3), download=lambda t: df, send=lambda m: sent.append(m) or True) == sent and len(sent) == 1 and "D-2" in sent[0]
assert rc.morning(out=logs.append, today=date(2026, 11, 3), download=lambda t: None, send=lambda m: sent.append(m) or True) == [] and "일봉 없음" in logs[-1] and len(sent) == 1
# ---- 진행 중 봉: 미국 정규장 마감 전이면 오늘 봉은 live(계산엔 넣되 '진행 중' 표시)
live_df = df.copy(); live_df.loc["2026-10-30"] = [1.5, 1.6, 1.4, 1.5, 300_000.0]
rl = rc.compute("WHLR", live_df, now_et=pd.Timestamp("2026-10-30 11:00", tz="America/New_York"))
assert rl["today"] == date(2026, 10, 30) and [w["date"] for w in rl["window"] if w.get("live")] == [date(2026, 10, 30)] and rl["known_n"] == 7
_w = {w["date"]: w for w in rl["window"]}
assert rl["adjust_notes"] == ["2026-10-30 1:6 병합 환산(×6)"] and abs(_w[date(2026, 10, 30)]["close"] - 1.5) < 1e-9 and abs(_w[date(2026, 10, 29)]["close"] - 0.24 * 6) < 1e-9   # 미환산(0.24→1.5 점프) 봉만 ×6
rl2 = rc.compute("WHLR", live_df, now_et=pd.Timestamp("2026-10-30 17:00", tz="America/New_York")); assert not any(w.get("live") for w in rl2["window"])
print("calc OK")

# ---- 화면: 주인에겐 🏢 기업 분석에 '🔁 리셋 사이클' 탭 · 방문객에겐 탭 없음
from streamlit.testing.v1 import AppTest
today = pd.Timestamp.today().normalize()
idx2 = pd.bdate_range(end=today - pd.Timedelta(days=1), periods=90)
c2 = np.linspace(20.0, 1.5, len(idx2))
pd.DataFrame({"Open": c2, "High": c2 * 1.05, "Low": c2 * 0.95, "Close": c2, "Volume": 1_000_000.0}, index=idx2).to_csv(os.path.join(tmp, "rc.csv"))
os.environ["QUANT_RC_CSV"] = os.path.join(tmp, "rc.csv")
APP = os.path.join(os.environ["QS_ROOT"], "tests", "apps", "rc_app.py")
at = AppTest.from_file(APP, default_timeout=240).run(); assert not at.exception, [e.value for e in at.exception]
labels = [x.label for x in at.tabs]; assert "🔁 리셋 사이클" in labels, labels
html = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
assert "시나리오" in html and "다음 상환일" in html and "과거 사이클" in html and "나스닥 반복 병합 규정" in html, html[:400]
assert any("남은 날 하루 거래량 가정" in (n.label or "") for n in at.number_input)
os.environ["QUANT_RC_GUEST"] = "1"
at2 = AppTest.from_file(APP, default_timeout=240).run(); assert not at2.exception, [e.value for e in at2.exception]
labels2 = [x.label for x in at2.tabs]; assert "🔁 리셋 사이클" not in labels2 and "1 회사" in labels2, labels2
html2 = "\n".join(m.value for m in at2.markdown); assert "나스닥 반복 병합 규정" not in html2
print("UI OK")
shutil.rmtree(tmp, ignore_errors=True)
print("ALL OK")
