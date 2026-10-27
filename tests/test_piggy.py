import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, piggy
db.init_db(); piggy.ensure_tables()
idx = pd.bdate_range(end="2026-10-14", periods=122)[-120:]
def frame(close, spread=0.02):
    c = np.asarray(close, float); return pd.DataFrame({"Open": c, "High": c * (1 + spread), "Low": c * (1 - spread), "Close": c, "Volume": 200000.0}, index=idx[-len(c):])
t = np.arange(120)
BOX = frame(0.575 + 0.07 * np.sin(t / 3.0))                                          # $0.505~0.645 박스, 주기 약 19일
DOWN = frame(np.linspace(0.9, 0.4, 120))                                              # 꾸준한 하락
BREAK = frame(np.r_[0.575 + 0.07 * np.sin(t[:110] / 3.0), np.full(10, 0.40)])          # 박스였다가 마지막 10일 이탈
mb, md, mk = piggy.box_metrics(BOX), piggy.box_metrics(DOWN), piggy.box_metrics(BREAK)
for name, m in (("BOX", mb), ("DOWN", md), ("BREAK", mk)):
    print(name, {k: round(v, 2) if isinstance(v, float) else v for k, v in m.items() if k in ("support", "resistance", "width_pct", "inside_pct", "trend_month_pct", "bounces", "breaks", "pos", "score", "below1_days", "recent_break")})
assert mb["inside_pct"] >= 95 and abs(mb["trend_month_pct"]) < 3 and mb["bounces"] >= 2 and 15 <= mb["width_pct"] <= 60 and mb["score"] >= 80 and mb["below1_days"] == 60
assert md["score"] < 60 and md["trend_month_pct"] < -5                                 # 하락 추세는 점수 낮음
assert mk["recent_break"] is True and mk["breaks"] >= 3 and abs(mk["support"] - mb["support"]) < 0.02 and mk["score"] < mb["score"] / 1.5   # 박스는 이탈 전 구간 기준 → 이탈을 잡고 감점
assert mb["recent_break"] is False and piggy.zone(mk["price"], mk["support"], mk["resistance"]) == "⚠️ 박스 이탈"
UP = frame(np.r_[0.575 + 0.07 * np.sin(t[:110] / 3.0), np.full(10, 0.80)]); mu = piggy.box_metrics(UP); assert mu["recent_breakout"] is True and mu["recent_break"] is False
assert piggy.box_metrics(BOX.tail(20)) is None and piggy.box_metrics(None) is None     # 데이터 부족
# 박스 위치 구간
assert piggy.zone(0.52, 0.50, 0.65) == "🟢 저점 구간" and piggy.zone(0.63, 0.50, 0.65) == "🔴 고점 구간" and piggy.zone(0.58, 0.50, 0.65) == "⏸ 중간"
assert piggy.zone(0.46, 0.50, 0.65) == "⚠️ 박스 이탈" and piggy.zone(None, 0.5, 0.6) == "확인 불가" and piggy.zone(0.5, 0.6, 0.5) == "확인 불가"
# 저금통 목록 + 박스(직접/자동)
piggy.add("abcd", "바이오·헬스"); piggy.add("EFGH", "기타", 0.30, 0.40, 500000, "메모")
it = piggy.items().set_index("ticker"); assert it.loc["ABCD", "budget_krw"] == 1000000 and it.loc["EFGH", "box_low"] == 0.30
assert piggy.box_of(it.loc["EFGH"].to_dict(), mb) == (0.30, 0.40, "직접") and piggy.box_of(it.loc["ABCD"].to_dict(), mb)[2] == "자동"
assert piggy.box_of(it.loc["ABCD"].to_dict(), None) == (None, None, "없음")
piggy.update("ABCD", box_low=0.51); assert piggy.box_of(piggy.items().set_index("ticker").loc["ABCD"].to_dict(), mb)[2] == "일부 직접"
piggy.add("ABCD", "중국·아시아"); assert piggy.items().set_index("ticker").loc["ABCD", "box_low"] == 0.51                # 다시 담아도 박스 유지, 카테고리만 변경
piggy.remove("EFGH"); assert piggy.tickers() == ["ABCD"]
# 후보 찾기(가짜 다운로드): 가격 필터 → 박스 분석 → 저장
import market
PX = {"BOX1": BOX, "DOWN1": DOWN, "PRICY": frame(np.full(120, 5.0)), "SHORT": BOX.tail(10)}
market.download_daily = lambda tk, period="3mo", chunk=200: {t: (PX[t].tail(5) if period == "5d" else PX[t]) for t in tk if t in PX}
res = piggy.screen(["BOX1", "DOWN1", "PRICY", "SHORT", "NONE"], fx=1342.0, max_krw=1000, chunk=2)
print(res[["ticker", "score"]].to_string(index=False))
assert set(res["ticker"]) == {"BOX1", "DOWN1"}                                         # $5 종목은 가격에서, 10일짜리는 데이터 부족으로 제외
d, sc = piggy.latest_scan(); assert d and set(sc["ticker"]) == {"BOX1", "DOWN1"}
print("ALL OK")
# ---------- 알림: 구간 진입 시 한 번만 ----------
piggy.add("BOX1", "좁은 박스(15~30%)")
m1 = piggy.alerts({"BOX1": 0.51}, today="2026-10-15"); print(m1)
assert len(m1) == 1 and "BOX1 🟢 저점 구간 — 매수 검토" in m1[0]
assert piggy.alerts({"BOX1": 0.51}, today="2026-10-15") == []                          # 같은 날 같은 구간은 다시 안 보냄
assert piggy.alerts({"BOX1": 0.58}, today="2026-10-15") == []                          # 중간 구간은 알림 없음
assert "고점 구간 — 매도 검토" in piggy.alerts({"BOX1": 0.64}, today="2026-10-15")[0]
assert "박스 이탈 — 손절·제외 검토" in piggy.alerts({"BOX1": 0.40}, today="2026-10-15")[0]
assert len(piggy.alerts({"BOX1": 0.51}, today="2026-10-16")) == 1 and piggy.alerts({}, today="2026-10-16") == []
# ---------- 매매 기록 ----------
tr = pd.DataFrame([{"id": None, "date": "2026-10-10", "ticker": "box1", "buy": 0.50, "sell": 0.60, "qty": 1000, "fee_pct": 1.0, "note": ""},
                   {"id": None, "date": "2026-10-11", "ticker": "BOX1", "buy": 0.60, "sell": 0.54, "qty": 1000, "fee_pct": 1.0, "note": "이탈 손절"},
                   {"id": None, "date": "2026-10-12", "ticker": "BOX1", "buy": 0.52, "sell": None, "qty": 1000, "fee_pct": 0.0, "note": "보유"},
                   {"id": None, "date": "", "ticker": "", "buy": None, "sell": None, "qty": None, "fee_pct": None, "note": ""}])
piggy.save_trades(tr); saved = piggy.trades(); assert len(saved) == 3 and set(saved["ticker"]) == {"BOX1"}
s = piggy.trade_stats(saved, 1342.0); print(s)
assert s["n"] == 2 and s["open"] == 1 and s["win_rate"] == 50.0 and abs(s["avg_ret"] - ((20 - 1) + (-10 - 1)) / 2) < 1e-9
assert abs(s["pnl_krw"] - ((1000 * 0.10 * 1342 - 1000 * 0.50 * 1342 * 0.01) + (1000 * -0.06 * 1342 - 1000 * 0.60 * 1342 * 0.01))) < 1e-6
assert piggy.trade_stats(saved[saved["sell"].isna()], 1342.0)["n"] == 0   # 보유 중만 있으면 청산 거래 0
print("ALL OK 2")
