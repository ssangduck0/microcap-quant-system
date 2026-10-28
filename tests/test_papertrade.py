import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🧪 가상매매 전략별 장부: 설정 저장 · 예전 거래 이전 · 먼저 닿은 쪽 판정(실시간 1분봉 · 세션 기록 · 일봉) · 전략별 매수 규칙 · 저금통 기준 이탈 · 비교표 · 전략별 초기화."""
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
import db, papertrade as pt, exthilo, afterscalp, piggy, config
db.init_db(); piggy.ensure_tables()
ET = ZoneInfo("America/New_York")
D = "2026-10-20"                                   # 화요일(매수일)
D1, D2, D3 = "2026-10-21", "2026-10-22", "2026-10-23"
TODAY = "2026-10-27"


def et(day, hh, mm=0):
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET)


def daily(rows):  # {날짜: (high, low, close)}
    idx = pd.to_datetime(list(rows))
    h = [v[0] for v in rows.values()]; l = [v[1] for v in rows.values()]; c = [v[2] for v in rows.values()]
    return pd.DataFrame({"Open": c, "High": h, "Low": l, "Close": c, "Volume": 1e5}, index=idx)


def mins(bars):  # [(datetime ET, high, low, close)]
    return pd.DataFrame({"High": [b[1] for b in bars], "Low": [b[2] for b in bars], "Close": [b[3] for b in bars]}, index=pd.DatetimeIndex([b[0] for b in bars]))


def row(t):
    with closing(db.connect()) as c:
        return dict(c.execute("SELECT * FROM pt_trades WHERE ticker=? ORDER BY id DESC LIMIT 1", (t,)).fetchone())


# ------------------------------------------------------------------ 1) 설정: 기본값 · 저장 · 범위 제한 · 전략별 켜고 끄기
s0 = pt.settings()
assert set(s0) == {"rank", "rank6", "pick", "close", "piggy", "after", "master"} and s0["rank"]["tp"] == 20.0 and s0["close"]["hold"] == 1 and s0["piggy"]["tp"] == 0.0 and s0["after"]["on"] is True
s1 = pt.save_settings({"rank": {"tp": 10, "sl": 5}, "piggy": {"on": False}, "pick": {"tp": 999, "n": 0}, "nope": {"tp": 1}})
assert s1["rank"]["tp"] == 10.0 and s1["rank"]["sl"] == 5.0 and s1["rank"]["hold"] == 3 and s1["piggy"]["on"] is False and s1["pick"]["tp"] == 200.0 and s1["pick"]["n"] == 1
assert "박스 상단" in pt.rule_text(s1["piggy"], "piggy") and "당일 마감" in pt.rule_text(s1["after"], "after") and pt.rule_text(s1["rank"], "rank") == "익절 +10% · 손절 −5% · 3거래일"
pt.save_settings({})
assert pt.settings()["rank"]["tp"] == 20.0 and pt.settings()["piggy"]["on"] is True

# ------------------------------------------------------------------ 2) 개편 전 거래(전략 열 없음) → 종합 순위 전략으로 이전 + 그때 규칙 스냅샷
with closing(db.connect()) as conn:
    conn.execute(pt.DDL)
    conn.execute("INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, status) VALUES ('old', ?, 'OLD', 1, 50, '{}', 1.0, 100, 'closed')", (D,))
    conn.commit()
    pt.ensure(conn)
r = row("OLD"); assert r["strategy"] == "rank" and r["tp"] == 20.0 and r["sl"] == 10.0 and r["hold"] == 3
assert pt.trades(strategy="rank")["ticker"].tolist() == ["OLD"] and pt.trades(strategy="pick").empty

# ------------------------------------------------------------------ 3) 먼저 닿은 쪽: 칸 순서대로 · 같은 칸에서 둘 다면 손절
assert pt.first_touch([("night", 1.1, 1.0), ("pre", 1.3, 0.95)], 1.2, 0.9) == (1, "tp")
assert pt.first_touch([("night", 1.1, 1.0), ("pre", 1.3, 0.95)], 1.2, 0.98) == (1, "sl")      # 프리장에서 익절·손절 둘 다 → 손절(보수적)
assert pt.first_touch([("night", 1.25, None), ("pre", 1.0, 0.85)], 1.2, 0.9) == (0, "tp")     # 저가 기록 없는 옛 세션은 고가만 확인
assert pt.first_touch([("reg", 1.1, 1.0)], 1.2, 0.9) is None and pt.first_touch([("reg", 1.1, 0.5)], None, 0.9) == (0, "sl")


def buy(strategy, t, entry, sig=None, **kw):
    with closing(db.connect()) as conn:
        ok = pt.open_trade(conn, strategy, D, t, entry, sig_at=sig, **kw)
        conn.commit()
    assert ok, (strategy, t)


# ------------------------------------------------------------------ 4) 실시간 판정(1분봉 · 모든 세션): 애프터 익절 · 데이마켓 손절 먼저 · 진입 전 봉 무시 · 병합 의심 건너뜀 · 애프터 전략 매도 마감
pt.save_settings({k: {"n": 20} for k in pt.STRATEGIES})      # 판정 테스트용으로 하루 한도를 넉넉히
buy("rank", "LA", 1.0); buy("rank", "LB", 1.0); buy("rank", "LC", 1.0); buy("rank", "LE", 1.0)
frames = {"LA": mins([(et(D, 16, 30), 1.25, 1.15, 1.2)]),                                               # 애프터에 +25% → 익절 +20%
          "LB": mins([(et(D, 21, 0), 0.95, 0.85, 0.9), (et(D, 21, 5), 1.30, 1.2, 1.3)]),                 # 데이마켓(전날 21:00 ET = 다음 거래일): 손절 먼저, 5분 뒤 급등은 무시
          "LC": mins([(et(D, 15, 0), 2.0, 1.9, 1.95), (et(D, 16, 10), 1.05, 1.0, 1.02)]),                # 15:00 봉은 매수(종가) 전 → 무시, 16:10 봉만 확인
          "LE": mins([(et(D1, 9, 40), 10.0, 9.0, 9.5)])}                                                  # 10배 → 병합 의심(아침 갱신에 맡김)
with closing(db.connect()) as conn:
    n = pt.live_check(conn, frames, now=et(D1, 9, 45))
assert n == 2, n
assert row("LA")["status"] == "closed" and abs(row("LA")["exit"] - 1.2) < 1e-9 and row("LA")["reason"] == "익절 +20% (애프터 실시간)" and row("LA")["exit_day"] == D
assert row("LB")["status"] == "closed" and abs(row("LB")["exit"] - 0.9) < 1e-9 and "손절 −10% (데이마켓 실시간)" == row("LB")["reason"] and row("LB")["exit_day"] == D1
assert row("LC")["status"] == "open" and row("LC")["checked_at"] and row("LC")["checked_at"].startswith("2026-10-20T20:10")   # 16:10 ET = 20:10 UTC
assert row("LE")["status"] == "open" and row("LE")["checked_at"] is None
# 🌙 애프터 전략: 매도 마감(애프터 끝 10분 전)이 지나면 마지막 가격으로 정리 · 그 전엔 먼저 닿은 쪽
db.set_meta("us_after_end", et(D, 20, 0).isoformat())
buy("after", "AF1", 1.0, sig=et(D, 16, 30)); buy("after", "AF2", 1.0, sig=et(D, 16, 30))
fr = {"AF1": mins([(et(D, 16, 40), 1.02, 0.99, 1.0), (et(D, 17, 0), 1.06, 1.01, 1.05)]),
      "AF2": mins([(et(D, 16, 40), 1.02, 0.99, 1.0), (et(D, 19, 45), 1.03, 1.0, 1.02), (et(D, 19, 55), 1.5, 1.4, 1.5)])}   # 19:55 는 마감(19:50) 뒤 → 안 봄
with closing(db.connect()) as conn:
    assert pt.live_check(conn, fr, now=et(D, 19, 56)) == 2
assert row("AF1")["reason"] == "익절 +5% (애프터 실시간)" and abs(row("AF1")["exit"] - 1.05) < 1e-9
assert row("AF2")["reason"].startswith("매도 마감 가격") and abs(row("AF2")["exit"] - 1.02) < 1e-9

# ------------------------------------------------------------------ 5) 아침 갱신: 세션 기록(ext_hilo) 순서 · 일봉 · 보유일 · 장마감/애프터/저금통 전략
buy("rank", "GA", 1.0); buy("rank", "GB", 1.0); buy("rank", "GH", 1.0); buy("rank", "GI", 1.0)
buy("close", "CJ", 1.0, sig=et(D, 15, 0))                                    # 장마감 전략: 15:00 매수, 다음 거래일 종가까지
buy("after", "AK", 1.0, sig=et(D, 16, 30)); buy("after", "AL", 1.0, sig=et(D, 16, 30)); buy("after", "AM", 1.0, sig=et(D, 16, 30))
piggy.add("PN", "기타", 0.50, 0.65); piggy.add("PP", "기타", 0.50, 0.65)
buy("piggy", "PN", 0.52, sig=et(D, 10, 0), tp_px=0.65, sl_px=0.475); buy("piggy", "PO", 0.52, sig=et(D, 10, 0), tp_px=0.65, sl_px=0.475)
buy("piggy", "PP", 0.52, sig=et(D, 10, 0), tp_px=0.65, sl_px=0.475)
with closing(db.connect()) as conn:
    exthilo.ensure(conn); afterscalp.ensure_tables(conn)
    ins = "INSERT INTO ext_hilo (date, ticker, night_high, night_low, pre_high, pre_low, reg_high, reg_low, post_high, post_low, day_low) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    conn.execute(ins, (D1, "GA", 1.05, 0.88, 1.5, 1.4, 1.6, 1.4, None, None, 0.88))      # 데이마켓에서 −12% → 손절, 뒤의 급등 무시
    conn.execute(ins, (D1, "GB", 1.02, 0.98, 1.25, 1.00, 1.0, 0.95, None, None, 0.95))    # 프리장 +25% → 익절 +20%
    conn.execute("INSERT INTO ext_hilo (date, ticker, reg_high, day_low) VALUES (?,?,?,?)", (D1, "GI", 1.25, 0.99))   # 옛 기록(저가 열 없음): 정규장 고가만 → 익절
    conn.execute(ins, (D, "CJ", None, None, None, None, 1.5, 0.99, 1.08, 0.97, 0.97))     # 정규장 1.5 는 매수(15:00) 전 세션 → 무시 · 애프터는 안 닿음
    conn.execute("INSERT INTO after_signals (date, ticker, at, price, first_hit, exit_price) VALUES (?,?,?,?,?,?)", (D, "AK", et(D, 16, 30).isoformat(), 1.0, "목표 +5%", 1.04))
    conn.execute("INSERT INTO after_signals (date, ticker, at, price, first_hit, exit_price) VALUES (?,?,?,?,?,?)", (D, "AL", et(D, 16, 30).isoformat(), 1.0, None, 1.02))
    conn.commit()
flat = {D: (1.01, 0.99, 1.0), D1: (1.01, 0.99, 1.0), D2: (1.01, 0.99, 1.0), D3: (1.01, 0.99, 1.0)}
bars = {"GA": daily(flat), "GB": daily(flat), "GH": daily(flat), "GI": daily(flat), "LC": daily(flat), "LE": daily(flat),
        "CJ": daily({D: (1.2, 0.99, 1.0), D1: (1.05, 0.98, 1.03), D2: (1.3, 1.0, 1.2)}),
        "AK": daily({D: (1.01, 0.99, 1.0), D1: (1.01, 0.99, 1.0)}), "AL": daily({D: (1.01, 0.99, 1.0), D1: (1.01, 0.99, 1.0)}),
        "AM": daily({D: (1.01, 0.98, 0.99), D1: (1.01, 0.99, 1.0)}),
        "PN": daily({D: (0.53, 0.51, 0.52), D1: (0.56, 0.53, 0.55), D2: (0.56, 0.53, 0.55)}), "PO": daily({D: (0.53, 0.51, 0.52), D1: (0.56, 0.53, 0.55)}),
        "PP": daily({D: (0.53, 0.51, 0.52), D1: (0.66, 0.53, 0.60)})}
n = pt.update(bars, today=TODAY)
ga, gb, gh, gi = row("GA"), row("GB"), row("GH"), row("GI")
assert ga["status"] == "closed" and ga["reason"] == "손절 −10% (데이마켓)" and abs(ga["exit"] - 0.9) < 1e-9 and ga["exit_day"] == D1, ga
assert gb["reason"] == "익절 +20% (프리장)" and abs(gb["exit"] - 1.2) < 1e-9, gb
assert gh["reason"] == "3일 보유 종가" and gh["exit_day"] == D3 and abs(gh["exit"] - 1.0) < 1e-9, gh                     # 기록 없는 날은 정규장 일봉
assert gi["reason"] == "익절 +20% (정규장)" and gi["exit_day"] == D1, gi
cj = row("CJ"); assert cj["reason"] == "1일 보유 종가" and cj["exit_day"] == D1 and abs(cj["exit"] - 1.03) < 1e-9, cj      # 다음 거래일 종가(그 전 +10/−5 안 닿음)
ak, al, am = row("AK"), row("AL"), row("AM")
assert ak["reason"] == "익절 +5% (애프터 분봉 기록)" and abs(ak["exit"] - 1.05) < 1e-9 and ak["exit_day"] == D, ak
assert al["reason"].startswith("매도 마감 가격(애프터 분봉 기록)") and abs(al["exit"] - 1.02) < 1e-9, al
assert "근사" in am["reason"] and abs(am["exit"] - 0.99) < 1e-9, am
pn, po, pp_ = row("PN"), row("PO"), row("PP")
assert pn["status"] == "open", pn                                                                                        # 보유 제한 없음 · 박스 안 → 계속 보유
assert po["status"] == "closed" and po["reason"].startswith("저금통에서 빠짐") and abs(po["exit"] - 0.55) < 1e-9, po     # 저금통 목록에 없음 → 그날 종가로 정리
assert pp_["reason"] == "익절 박스 상단 (정규장)" and abs(pp_["exit"] - 0.65) < 1e-9, pp_
assert row("LC")["status"] == "closed" and row("LC")["reason"] == "3일 보유 종가"                                          # 실시간으로 보던 종목도 아침에 마무리
# 저금통 기준 이탈(piggy_out) → 그날 종가로 정리(익절이든 손절이든)
assert pt.update({"PN": bars["PN"]}, today=TODAY, piggy_out={"PN"}) == 1
pn = row("PN"); assert pn["reason"].startswith("저금통 기준 이탈") and abs(pn["exit"] - 0.55) < 1e-9 and pn["exit_day"] == D2, pn

# ------------------------------------------------------------------ 6) 매수 규칙: 종합 순위 N개·하루 한 번 · PICK 유력만·30일 쿨다운 · 저금통 저점 구간 · 장마감 BEST 먼저 · 애프터 중복 금지
pt.save_settings({})
rk = pd.DataFrame([{"ticker": f"R{i}", "rank": i, "score": 90 - i, "parts": {"acc": True}} for i in range(1, 6)])
assert pt.open_new(rk, {f"R{i}": 1.0 for i in range(1, 6)}, D2) == ["R1", "R2", "R3"] and pt.open_new(rk, {f"R{i}": 1.0 for i in range(1, 6)}, D2) == []
r1 = row("R1"); assert r1["strategy"] == "rank" and r1["tp"] == 20.0 and r1["hold"] == 3 and abs(r1["qty"] - 1000.0) < 1e-9 and json.loads(r1["parts"]) == {"acc": True}
rk6 = rk.assign(score6=[10.0, 20.0, 30.0, 40.0, 50.0])   # 🏁 순위(⑥ 반영): 같은 표를 score6 로 다시 줄 세움 → R5·R4·R3 (2026-10-28, 4주 비교용)
assert pt.open_new(rk6, {f"R{i}": 1.0 for i in range(1, 6)}, D2, "rank6") == ["R5", "R4", "R3"] and pt.open_new(rk6, {f"R{i}": 1.0 for i in range(1, 6)}, D2, "rank6") == []
r5 = row("R5"); assert r5["strategy"] == "rank6" and r5["rank"] == 1 and r5["score"] == 50.0 and r5["book"] == pt.book("rank6") and pt.open_new(rk, {"R1": 1.0}, D2, "rank6") == []   # score6 없는 표면 안 삼
assert {"R1", "R2", "R3"} <= set(pt.trades(strategy="rank")["ticker"]) and set(pt.trades(strategy="rank6")["ticker"]) == {"R5", "R4", "R3"}
scan = {"pass": [{"ticker": "PK1", "status": "유력", "weak": 0, "price": 2.0, "imm_days": 3, "pressure": 7, "target_name": "상장 유지", "target": 2.6, "pct": 30},
                 {"ticker": "PK2", "status": "유력", "weak": 0, "price": 1.0, "imm_days": 5, "pressure": 6, "target_name": "워런트", "target": 1.3, "pct": 30},
                 {"ticker": "PK3", "status": "가능", "weak": 0, "price": 1.0, "imm_days": 30, "pressure": 3, "target_name": "시총", "target": 1.3, "pct": 30},
                 {"ticker": "PK4", "status": "유력", "weak": 1, "price": 1.0, "imm_days": 3, "pressure": 7, "target_name": "baby shelf 탈출", "target": 1.3, "pct": 30}]}
assert pt.open_pick(scan, D2, now=et(D2, 7, 0)) == ["PK1", "PK2"]
pk1 = row("PK1"); assert pk1["strategy"] == "pick" and pk1["tp"] == 30.0 and pk1["hold"] == 20 and "상장 유지" in pk1["note"]
with closing(db.connect()) as c:
    c.execute("UPDATE pt_trades SET status='closed', exit=2.6, exit_day=? WHERE ticker='PK1'", (D3,)); c.commit()
assert pt.open_pick(scan, D3) == []                                                                     # 30일 안 같은 종목 다시 안 삼
piggy.add("PQ", "바이오", 0.50, 0.65); piggy.add("PR", "바이오", 0.50, 0.65)
assert pt.open_piggy({"PQ": 0.52, "PR": 0.60, "PP": 0.52}, D3) == ["PQ"]                                # PR 은 중간 · PP 는 5일 쿨다운
pq = row("PQ"); assert abs(pq["tp_px"] - 0.65) < 1e-9 and abs(pq["sl_px"] - 0.475) < 1e-9 and pq["tp"] == 0.0 and pt.levels(pq) == (0.65, 0.475)
with closing(db.connect()) as c:
    assert c.execute("SELECT COUNT(*) FROM piggy_events WHERE ticker='PQ' AND date=?", (D3,)).fetchone()[0] == 1
    import closewatch
    closewatch.ensure_tables(c)
    for t, g, px in (("CW1", "관찰", 1.0), ("CW2", "후보", 2.0), ("CW3", "BEST", 3.0), ("CW4", "BEST", None)):
        c.execute("INSERT OR REPLACE INTO close_state (date, ticker, metrics, updated_at) VALUES (?,?,?,?)", (D3, t, json.dumps({"_g": g, "price": px}), "x"))
    c.commit()
    _ev = closewatch.evaluate
    closewatch.evaluate = lambda m, params=None: {"grade": m["_g"]}
    try:
        assert pt.scan_close(c, D3, ["CW1", "CW2", "CW3", "CW4"], et(D3, 15, 10)) == ["CW3", "CW2"]        # BEST 먼저 · 관찰·가격 없음 제외
        assert pt.scan_close(c, D3, ["CW1", "CW2", "CW3"], et(D3, 15, 20)) == []                          # 이미 보유
    finally:
        closewatch.evaluate = _ev
    assert pt.open_after(c, D3, "AFX", 1.0, et(D3, 16, 31)) is True and pt.open_after(c, D3, "AFX", 1.0, et(D3, 16, 32)) is False
cw3 = row("CW3"); assert cw3["strategy"] == "close" and cw3["note"] == "BEST" and cw3["rank"] == 3 and cw3["sig_at"].startswith("2026-10-23T19:10")
pt.save_settings({"after": {"on": False}})
with closing(db.connect()) as c:
    assert pt.open_after(c, D3, "AFY", 1.0) is False                                                      # 꺼진 전략은 안 삼
pt.save_settings({})
assert set(pt.open_tickers()) >= {"R1", "PK2", "PQ", "CW3", "AFX"} and "GA" not in pt.open_tickers()

# ------------------------------------------------------------------ 7) 비교표 · 전략별 장부·초기화
cmp_df = pt.compare({"R1": 1.1})
assert list(cmp_df["key"]) == ["rank", "rank6", "pick", "close", "piggy", "after", "master"] and cmp_df.set_index("key").loc["rank", "거래"] >= 8
assert cmp_df.set_index("key").loc["after", "청산"] == 5 and cmp_df.set_index("key").loc["piggy", "열린"] == 1
b_rank, b_pick = pt.book("rank"), pt.book("pick")
pt.reset("pick")
assert pt.book("rank") == b_rank and pt.book("pick") != b_pick and pt.trades(pt.book("pick"), "pick").empty and not pt.trades(b_pick, "pick").empty
sm = pt.summary(pt.trades(strategy="after"))
assert sm["closed"] == 5 and sm["win"] == 80.0, sm     # AF1 +5 · AF2 +2 · AK +5 · AL +2 · AM −1 → 4/5
# 📐 스승 눌림목(E단계 2026-10-27): 아침 차트 관점의 '눌림 타점' 신호 → 직전 종가로 매수 · 같은 종목 10일에 한 번 · 꺼지면 안 삼
import chartview as cv
pt.save_settings({"master": {"n": 3, "on": True}})
with closing(db.connect()) as conn:
    cv.ensure(conn)
    conn.execute("INSERT OR REPLACE INTO chart_signals VALUES ('2026-10-27','MST','pullback',1.9,'무릎~허리 · 허리 $2.0','x')")
    conn.execute("INSERT OR REPLACE INTO chart_signals VALUES ('2026-10-26','MST','pullback',1.95,'어제 것','x')")
    conn.execute("INSERT OR REPLACE INTO chart_signals VALUES ('2026-10-27','MS2','h60_200','3.0','60분','x')")
    conn.commit()
    assert [r["ticker"] for r in pt.master_candidates(conn, "2026-10-27")] == ["MST"] and pt.master_candidates(conn, "2026-10-27")[0]["date"] == "2026-10-27"
assert pt.open_master("2026-10-27", {"MST": 1.95}) == ["MST"]
with closing(db.connect()) as conn:
    r = [x for x in pt.open_rows(conn) if x["ticker"] == "MST"][0]
    tp_, sl_ = pt.levels(r)
    assert r["strategy"] == "master" and abs(tp_ - 1.95 * 1.10) < 1e-6 and abs(sl_ - 1.95 * 0.93) < 1e-6 and r["hold"] == 5 and "눌림 타점" in r["note"], r
assert pt.open_master("2026-10-27", {"MST": 1.95}) == []                                  # 이미 보유
pt.save_settings({"master": {"on": False}}); assert pt.open_master("2026-10-27", {"MST": 1.95}) == []
assert "master" in pt.STRATEGIES and pt.COOLDOWN_DAYS["master"] == 10
print("ALL OK")
