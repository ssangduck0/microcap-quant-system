import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""ChartExchange 공매도 잔고 '유통주식 기준' 바뀜(2026-11-01 대시보드 점검): 분모 추정 · 바뀐 날 찾기 · 그래프 구간 나누기·안내 문구."""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import pandas as pd
import chartex, shortpanel_ui

assert chartex.implied_float(10.0, 1e5) == 1e6 and chartex.implied_float(0, 1e5) is None and chartex.implied_float(None, 5) is None
a, b = {"si_pct": 54.25, "short_shares": 370306}, {"si_pct": 3.77, "short_shares": 388715}       # WKHS 04-30 → 05-15
fa, fb = chartex.basis_jump(a, b)
assert round(fa / 1e3) == 683 and round(fb / 1e6, 1) == 10.3                                     # 분모 68만 → 1,031만(약 15배)
assert chartex.basis_jump({"si_pct": 9.4, "short_shares": 918189}, {"si_pct": 9.99, "short_shares": 974127}) is None   # 진짜 잔고 변화(분모 같음)
assert chartex.basis_jump({"si_pct": 10, "short_shares": 1e5}, {"si_pct": 5.6, "short_shares": 1e5}) is None   # 1.79배 → 기준 미만
rows = [{"date": "2026-04-15", "si_pct": 62.5, "short_shares": 426622}, {"date": "2026-04-30", **a}, {"date": "2026-05-15", **b},
        {"date": "2026-05-29", "si_pct": 4.0, "short_shares": 412000}]
br = chartex.basis_breaks(rows)
assert list(br) == ["2026-05-15"], br
print("basis OK")

days = pd.date_range("2026-04-15", "2026-06-05").strftime("%Y-%m-%d")
rep = {r["date"]: r for r in rows}
cur, recs = None, []
for d in days:   # ChartExchange 일별: 보고일 사이는 직전 값 이월
    if d in rep:
        cur = rep[d]
    recs.append({"date": d, "si_pct": cur["si_pct"], "short_shares": cur["short_shares"], "reported": int(d in rep)})
sis = pd.DataFrame(recs)
wide, note = shortpanel_ui.si_segments(sis)
assert list(wide.columns) == ["유통 대비 공매도 잔고(%) · 기준 1", "기준 2(05-15~)"], list(wide.columns)
assert wide.loc["2026-05-14", "유통 대비 공매도 잔고(%) · 기준 1"] == 54.25 and pd.isna(wide.loc["2026-05-14", "기준 2(05-15~)"])
assert wide.loc["2026-05-15", "기준 2(05-15~)"] == 3.77 and pd.isna(wide.loc["2026-05-15", "유통 대비 공매도 잔고(%) · 기준 1"])
assert "05-15(유통 68.3만 → 10.3M주 · 잔고 주식 37.0만 → 38.9만주)" in note and "앞뒤 % 는 바로 비교하지 말고" in note, note
w3, n3 = shortpanel_ui.si_segments(sis[sis["date"] >= "2026-05-05"])                           # 180일 창: 바뀌기 전 보고일(04-30)이 창 밖이어도 이월 값과 비교
assert "05-15(유통 68.3만 → 10.3M주" in n3 and list(w3.columns)[1] == "기준 2(05-15~)", (list(w3.columns), n3)
w2, n2 = shortpanel_ui.si_segments(sis[sis["date"] < "2026-05-15"])                            # 바뀐 날이 없으면 예전 그대로
assert list(w2.columns) == ["유통 대비 공매도 잔고(%)"] and n2 == ""
print("ALL OK")
