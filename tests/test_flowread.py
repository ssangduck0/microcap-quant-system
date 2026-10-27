import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, flowread as fr
db.init_db()
# 스승님 이미지 1(분산): 06.02 275원 거래량 4,429,653 → 06.03 253원 -8.05% 거래량 13,052,497
img1 = pd.DataFrame({"Open": [280, 276, 270], "High": [282, 280, 272], "Low": [272, 270, 250], "Close": [280.2, 275, 253], "Volume": [4e6, 4429653, 13052497]},
                    index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]))
t1 = fr.classify(img1); print(t1.to_string(index=False))
r = t1.iloc[-1]; assert abs(r["전일 대비 거래량(배)"] - 13052497 / 4429653) < 1e-9 and abs(r["등락(%)"] - (253 / 275 - 1) * 100) < 1e-9 and r["판정"] == fr.KINDS["dist"]
assert fr.verdict(t1) == "🔻 분산 — 내릴 쪽"
# 이미지 2(털기): 06.03 2,170원 거래량 7,835,865 → 06.04 2,461원 +13.38% 거래량 53,207,826, 시가 3,424 고가 3,943 저가 2,415
img2 = pd.DataFrame({"Open": [2200, 2200, 3424], "High": [2250, 2354, 3943], "Low": [2150, 2078, 2415], "Close": [2215.6, 2170, 2461], "Volume": [7e6, 7835865, 53207826]},
                    index=pd.to_datetime(["2026-06-02", "2026-06-03", "2026-06-04"]))
t2 = fr.classify(img2); r2 = t2.iloc[-1]; print(t2.to_string(index=False))
assert r2["판정"] == fr.KINDS["shake"] and r2["시가 대비"] == "하락" and abs(r2["고점 되돌림(%)"] - (3943 - 2461) / (3943 - 2415) * 100) < 1e-9   # 시가보다 낮게 끝났어도 전일 대비 상승 = 털기
assert fr.verdict(t2) == "🔺 털기 — 다음날 상승 마감 확인 필요"
# 털기 다음날: 상승 마감 → 확인 / 하락 → 실패
ok = pd.concat([img2, pd.DataFrame({"Open": [2470], "High": [2600], "Low": [2450], "Close": [2550], "Volume": [2e7]}, index=pd.to_datetime(["2026-06-05"]))])
assert fr.classify(ok).iloc[-1]["판정"] == fr.KINDS["ok"] and fr.verdict(fr.classify(ok)) == "🔺 털기 확인 — 오를 쪽"
bad = pd.concat([img2, pd.DataFrame({"Open": [2450], "High": [2460], "Low": [2200], "Close": [2250], "Volume": [2e7]}, index=pd.to_datetime(["2026-06-05"]))])
assert fr.verdict(fr.classify(bad)) == "⚠️ 털기 실패 — 주의"
assert fr.classify(img1, {"spike": 3.5}).iloc[-1]["판정"] == ""                                              # 기준을 높이면 분산 아님(2.95배)
assert fr.classify(img1.head(2)).empty and fr.verdict(pd.DataFrame()) == ""
# 다크풀 덤핑·매집 의심
idx = pd.bdate_range(end="2026-10-14", periods=12)[-10:]; fall = pd.DataFrame({"Close": np.linspace(1.0, 0.8, 10)}, index=idx)
dm = fr.dumping(fall, {"dark_pct": 70.0, "days": 5}, {"borrow_avail": 300000.0, "borrow_avail_chg_pct": -5.0}); print(dm)
assert dm["status"] is True and dm["roomy"] is True and dm["chg"] < 0
assert fr.dumping(fall, {"dark_pct": 40.0}, {"borrow_avail": 300000.0})["status"] is False                       # 장외 비중 낮음
assert fr.dumping(fall, {"dark_pct": 70.0}, {"borrow_avail": 1000.0})["status"] is False                         # 대차 빠듯(공매도 쪽일 수 있음)
assert fr.dumping(fall, None, {"borrow_avail": 300000.0})["status"] is None and fr.dumping(fall, {"dark_pct": 70.0}, {"borrow_stale": True, "borrow_avail": 1e6})["status"] is None
# 자동 리스크 확인(데이터 없을 때는 확인 불가로)
with closing(db.connect()) as conn:
    rc = fr.risk_checks("ZZZ", conn, fall); print(rc)
    assert [x["항목"] for x in rc][:2] == ["8-K 악재(최근 90일)", "펀더멘탈: 런웨이 6개월 미만"] and rc[0]["문제"] is None and rc[3]["문제"] is False and rc[3]["값"] == "9거래일"   # 10일치라 $1 미만 9거래일(30일 미만)
    assert fr.record(conn, "AAA", "2026-06-03", fr.KINDS["dist"], 253.0) and not fr.record(conn, "AAA", "2026-06-03", fr.KINDS["dist"], 253.0)
print("ALL OK")
