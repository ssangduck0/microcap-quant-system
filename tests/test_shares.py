"""📐 발행주식 수 추정(SEC 표지·분할·발행 경고) + 🐷 ⑥ 용 표지 이력·직전 두 분기 변동률(2026-10-28) — 인터넷 없이."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import db, shares, secbackfill, rsplit
db.init_db()
T = date.today(); d = lambda n: (T - timedelta(days=n)).isoformat()
A0, A1 = d(171), d(77)                      # 직전 분기 표지 · 최신 표지(94일 간격)
CF = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
    {"end": A0, "val": 30_000_000, "filed": d(167), "form": "10-Q", "accn": "a1"},
    {"end": A1, "val": 50_000_000, "filed": d(75), "form": "10-Q", "accn": "a2"},
    {"end": A1, "val": 2_500_000, "filed": d(75), "form": "10-Q", "accn": "a2", "frame": "ClassB"},     # 같은 기준일 다른 종류 → 합산
    {"end": A1, "val": 49_000_000, "filed": d(76), "form": "10-Q", "accn": "a2x"}]}}}}}                 # 같은 기준일에 먼저 낸 값 → 가장 늦게 낸 것만 씀
c = shares.cover_shares(CF); assert c["shares"] == 52_500_000 and c["asof"] == A1 and c["form"] == "10-Q" and c["src"] == "SEC dei:EntityCommonStockSharesOutstanding"
assert shares.cover_shares({"facts": {}}) is None and shares._points({"facts": {}}) == ("", [])
src, pts = shares._points(CF); assert [p["shares"] for p in pts] == [30_000_000, 52_500_000] and pts[1]["filed"] == d(75)
with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('HUBC',?,0.04,1.0)", (d(43),))            # 최신 기준일 뒤 1:25 병합
    secbackfill.ensure_tables(conn); conn.execute("INSERT INTO sec_hist VALUES ('x1','HUBC','8-K',?,'3.02,9.01')", (d(38),)); conn.commit()
class FC:
    calls = []
    def cik_for(s, t): return 1 if t == "HUBC" else None
    def companyfacts(s, cik): FC.calls.append(cik); return CF
dd = shares.estimate("HUBC", FC()); print(dd)
assert dd["adjusted"] == 52_500_000 * 0.04 and dd["splits_after"] == [{"date": d(43), "ratio": 0.04}] and dd["warn"] and "3.02" in dd["issuance_after"][0]
v, tag = shares.best("HUBC", 9e9); assert v == 2_100_000 and "이후 분할 반영" in tag and "발행 미반영" in tag
v, tag = shares.best("NOPE", 5e6); assert v == 5e6 and tag.startswith("야후")
assert shares.estimate("NOPE", FC()) is None and shares.build_missing(FC(), ["HUBC", "NOPE"], out=lambda *_: None) == 0   # 7일 안 = 건너뜀
assert shares.build_missing(FC(), ["HUBC"], out=lambda *_: None, force=True) == 1 and len(FC.calls) == 2                 # force 는 다시 받음(서버 소급용)
assert shares.build_missing(FC(), ["HUBC"], out=lambda *_: None, max_age=30) == 0 and shares.build_missing(FC(), ["HUBC"], out=lambda *_: None, max_age=-1) == 1   # max_age(우주 30일 주기)
class NF:   # 아무 종목도 SEC 자료가 없는 가짜 → 시도 횟수 상한(limit×3)에서 멈춤(예전엔 목록 끝까지)
    calls = 0
    def cik_for(s, t): NF.calls += 1; return None
    def companyfacts(s, cik): return {}
assert shares.build_missing(NF(), [f"X{i:04d}" for i in range(2000)], limit=50, out=lambda *_: None) == 0 and NF.calls == 150
# 🐷 ⑥: 표지 이력 · 직전 두 분기 변동률(사이 분할 반영) · 같은 연결 재사용
with closing(db.connect()) as conn:
    h = shares.history("HUBC", conn); assert [(p["asof"], p["shares"]) for p in h] == [(A0, 30_000_000), (A1, 52_500_000)]
    ch = shares.change("HUBC", conn); print(ch)
    assert ch and abs(ch["pct"] - 75.0) < 1e-9 and ch["d0"] == A0 and ch["d1"] == A1 and ch["src"] == "SEC 표지" and ch["splits"] == 0   # 1:25 병합은 d1 뒤라 미반영
    conn.execute("INSERT INTO rs_events VALUES ('HUBC',?,0.5,1.0)", (d(120),)); conn.commit()                               # 두 표지 사이 1:2 병합 → 옛 표지 30M 은 15M 기준
    ch = shares.change("HUBC", conn); assert abs(ch["pct"] - 250.0) < 1e-9 and ch["splits"] == 1
    assert shares.change("HUBC") and shares.get("HUBC", conn)["adjusted"] == 2_100_000 and shares.best("HUBC", None, conn)[0] == 2_100_000
    assert abs(shares.turnover("HUBC", 1_050_000, None, conn)["pct"] - 50.0) < 1e-9 and shares.turnover("NOPE", None, None, conn) is None
    # 판정 보류(None): 점 1개 · 연 1회 보고(20-F, 365일 간격 > 200일) · 최신 표지가 200일 넘게 오래됨 · 이력 없음
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", [("ONE", A1, "f", "10-Q", 1e6),
        ("FPI", d(400), "f", "20-F", 1e6), ("FPI", d(35), "f", "20-F", 2e6),
        ("OLD", d(400), "f", "10-Q", 1e6), ("OLD", d(300), "f", "10-Q", 2e6)])
    conn.commit()
    assert shares.change("ONE", conn) is None and shares.change("FPI", conn) is None and shares.change("OLD", conn) is None and shares.change("NONE", conn) is None
    # 보류 이유 문구(🐷 ⑥ 화면 값): 1개 · 연 1회(20-F) · 오래됨 · 없음 · 직전 분기 표지 없음(간격 < 75일)
    rs = {t: shares.hold_reason(t, conn) for t in ("ONE", "FPI", "OLD", "NONE", "HUBC")}; print(rs)
    assert rs["ONE"].startswith("SEC 표지 1개뿐") and A1 in rs["ONE"] and rs["FPI"] == f"연 1회 보고(20-F · 최신 표지 {d(35)}) — 분기 변동 판정 불가"
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", [("FPI1", d(301), "f", "20-F", 1e6), ("FPIX", d(666), "f", "20-F", 1e6), ("TENK", d(500), "f", "10-K", 1e6), ("TENK", d(135), "f", "10-K", 1e6)]); conn.commit()
    assert shares.hold_reason("FPI1", conn).startswith("연 1회 보고(20-F · 최신 표지") and shares.hold_reason("FPIX", conn).startswith("연 1회 보고(20-F) 인데 최신 표지가 666일 전")   # 20-F 는 표지 1개·300일이어도 '연 1회', 1년 반 넘으면 지연
    assert shares.hold_reason("TENK", conn) == "연 1회 보고(10-K · 표지 간격 365일) — 분기 변동 판정 불가" and shares.change("TENK", conn) is None
    assert rs["OLD"].startswith("SEC 최신 표지가 300일 전") and rs["NONE"].startswith("SEC 표지 없음") and "ChartExchange" in rs["NONE"]
    conn.execute("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", ("HUBC", d(60), "f", "10-Q", 6e7)); conn.commit()   # 최신 표지 뒤 17일 만에 또 표지(S-1 등) → 직전 분기 표지는 그 전 것
    assert shares.change("HUBC", conn)["d0"] == A0 and shares.hold_reason("CLOSE", conn).startswith("SEC 표지 없음")
    conn.executemany("INSERT OR REPLACE INTO shares_hist VALUES (?,?,?,?,?)", [("CLOSE", d(50), "f", "10-Q", 1e6), ("CLOSE", d(20), "f", "10-Q", 1e6)]); conn.commit()
    assert shares.change("CLOSE", conn) is None and rs["HUBC"] and shares.hold_reason("CLOSE", conn) == "직전 분기 표지 없음(최근 두 표지 간격 30일)"
print("ALL OK")
