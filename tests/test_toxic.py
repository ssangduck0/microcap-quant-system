import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""⚠️ 할인 전환(OMH) 패턴: 본문 감지(50% of lowest · discount · prepaid · ELOC 95% 는 기록) · 기록 · 병합 뒤 '폭락 경로' · 피드 태그 · 🏆 신호(내림 −50% 목표 · 바닥 반등) · 헤더 배지."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import pandas as pd
import db, toxic, secfeed as sf, scoreboard as sb, rsplit
db.init_db()
T1 = ("the Company entered into a securities purchase agreement for senior secured convertible notes. The conversion price shall be equal to 50% of the lowest "
      "VWAP of the common stock during the ten trading days prior to conversion.")
T2 = "The notes are convertible at a 25% discount to the lowest closing price of the common stock in the five trading days preceding conversion."
T3 = "The Company entered into a Prepaid Advance Agreement with an investor, under which the investor may purchase shares at 92% of the lowest VWAP."
T4 = "Under the equity line, the purchase price per share equals 95% of the lowest daily VWAP during the three trading days following notice."
T5 = "The Company reported record revenue and reaffirmed guidance."
d1, d2, d3, d4 = toxic.detect(T1), toxic.detect(T2), toxic.detect(T3), toxic.detect(T4)
assert d1["kind"] == "전환사채" and d1["discount_pct"] == 50 and d1["level"] == "악성", d1
assert d2["discount_pct"] == 25 and d2["level"] == "주의", d2
assert d3["kind"] == "선급주식매입" and d3["discount_pct"] == 8 and d3["level"] == "주의", d3   # 선급 구조 자체가 주의
assert d4["level"] == "기록" and toxic.detect(T5) is None and toxic.detect("") is None
# 피드 분류: '할인 전환' 태그 + 악재
assert "할인 전환" in sf.classify("8-K", ["1.01"], T1)[1] and sf.classify("8-K", ["1.01"], T1)[2] == "악재"
with closing(db.connect()) as conn:
    toxic.ensure(conn); rsplit.ensure_tables(conn)
    assert toxic.scan_and_record(conn, "omh", "a1", "2026-10-07", "8-K", "http://x/a1", T1)["level"] == "악성"
    assert toxic.scan_and_record(conn, "OMH", "a2", "2026-10-08", "8-K", "http://x/a2", T4) is None        # 기록 등급은 저장 안 함
    assert toxic.scan_and_record(conn, "OMH", "a3", "2026-10-09", "10-Q", "http://x/a3", T1) is None       # 대상 서류 아님
    assert not toxic.record(conn, "OMH", "a1", "2026-10-07", "8-K", "http://x/a1", d1)                     # 중복 없음
    assert toxic.status(conn, "OMH")["level"] == "악성" and toxic.status(conn, "OMH")["path"] is False and toxic.status(conn, "NONE") is None
    conn.execute("INSERT INTO rs_events VALUES ('OMH', '2026-08-01', 0.1, 1.0)"); conn.commit()           # 계약 전 180일 안 병합 → 폭락 경로
    s = toxic.status(conn, "OMH"); assert s["path"] and s["split_date"] == "2026-08-01"
    # 바닥 신호: 계약일 종가 $10 → −70%($3) 에 처음 닿은 날
    px = [10, 9, 8, 6, 4, 3.5, 2.9, 2.5, 3.2]
    days = pd.bdate_range("2026-10-07", periods=len(px))
    db.upsert_daily_prices(conn, "OMH", pd.DataFrame({"Open": px, "High": [x * 1.1 for x in px], "Low": [x * 0.9 for x in px], "Close": px, "Volume": 1e5}, index=days))
    bs = toxic.bottom_signals(conn); assert len(bs) == 1 and bs[0]["date"] == days[6].strftime("%Y-%m-%d") and abs(bs[0]["price"] - 2.9) < 1e-9, bs
    # 🏆 성과 공표: toxic_drop(내림, −50% 저가 도달 = 성공) · toxic_bottom(오름)
    df = sb.collect(conn)
    srcs = set(df[df["ticker"] == "OMH"]["source"]); assert {"toxic_drop", "toxic_bottom"} <= srcs, srcs
    bars = pd.DataFrame({"Open": px, "High": [x * 1.1 for x in px], "Low": [x * 0.9 for x in px], "Close": px, "Volume": 1e5}, index=days)
    o = sb.outcome(bars, "2026-10-07", 10.0, 60, -1, 50.0); assert o["status"] == "성공" and o["max_down"] <= -50, o          # 저가 2.25 → −77%
    o2 = sb.outcome(bars.iloc[:3], "2026-10-07", 10.0, 60, -1, 50.0); assert o2["status"] == "대기", o2
    o3 = sb.outcome(bars, "2026-10-07", 10.0, 3, -1, 0.0); assert o3["status"] == "성공"                                       # 예전 내림 예측(목표 0)은 종가 < 진입가 기준 그대로
badge = toxic.badge("OMH"); assert badge and badge[0].startswith("⚠️ 폭락 경로") and "50%" in badge[0] and badge[1] == "red"
assert toxic.badge("NONE") is None
import company_ui
hf = company_ui.header_facts("OMH"); assert isinstance(hf, dict) and hf["share_chg"] is None and company_ui.share_chip(hf) == ""   # 표지 없음 → 칩 없음
import shares as _sh6
from datetime import date as _d, timedelta as _td
with closing(db.connect()) as conn:   # 🔬 ⑥ 헤더 칩(2026-10-28): 직전 분기 +30% 빨강 · +15% 주황 · +3% 회색(순위 카드와 같은 기준)
    conn.execute(_sh6.HIST_DDL)
    for s1, cls, color, txt in ((1_300_000, "bad", "qk-red", "+30%"), (1_150_000, "warn", "qk-orange", "+15%"), (1_030_000, "ok", "qk-gray", "+3%")):
        conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", [("HDR6", (_d.today() - _td(days=170)).isoformat(), "f", "10-Q", 1_000_000),
                                                                                 ("HDR6", (_d.today() - _td(days=80)).isoformat(), "f", "10-Q", s1)]); conn.commit()
        hf = company_ui.header_facts("HDR6"); chip = company_ui.share_chip(hf)
        assert hf["share_chg"]["cls"] == cls and f"주식수 {txt}(분기)" in chip and color in chip and "SEC 표지" in chip, (s1, hf["share_chg"], chip)
print("ALL OK")
