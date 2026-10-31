"""🩹 pricefix 계단 점검(2026-10-31): 야후 병합 기록의 '그 날짜'만 보던 수리가 놓친 경계 —
① 야후 날짜가 1~2일 어긋남 ② 야후는 고쳤는데 기록이 없어 다시 안 받음 ③ 야후 일봉도 환산 전 —
을 일봉의 하루 ×3 변화로 찾아 다시 받고, 남은 계단이 알려진 병합(야후·SEC ±5일)과 맞으면 직접 환산. 3년치 중 2년 창 밖 봉도 맞추고, 다시 받아도 ×N² 가 되지 않게."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import db, rsplit, watch, pricefix

db.init_db()
idx = pd.bdate_range(end=(pd.Timestamp.now(tz="America/New_York") - pd.Timedelta(hours=16, minutes=20)).tz_localize(None).normalize(), periods=300)   # 마지막으로 끝난 미국 거래일까지
ds = [x.strftime("%Y-%m-%d") for x in idx]
S = 280                      # 계단 날 = 끝에서 20봉 전(최근 60일 안)
SD = ds[S]
COV = 150                    # 야후는 끝 150봉만 줌(저장 일봉은 300봉 — 3년 저장 · 2년 다시 받기 흉내)
V = 1e6


def frame(o, c, lo=0):
    o, c = np.asarray(o, float)[lo:], np.asarray(c, float)[lo:]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99, "Close": c, "Volume": V}, index=idx[lo:])


def step(before, after, at=S, gap=True):
    c = np.where(np.arange(300) < at, before, after).astype(float)
    o = c.copy()
    if not gap:
        o[at] = before          # 시가는 전날 그대로 · 장중에 오름(진짜 급등)
    return o, c


B = {   # 티커 → (시가, 종가) 저장 일봉 = 야후가 주는 원자료(야후가 고친 STALE 만 따로)
    "LAT": step(0.2, 3.0),                     # ①③ 1:16 · 야후 기록은 다음 날 · 계단 ×15
    "SEC": step(0.5, 10.5),                    # ③ SEC 🗓 역분할 1:25(다음 날) · 계단 ×21
    "PUMP": step(0.6, 2.7, gap=False),         # 진짜 급등(시가 그대로) · ×4.5 · 병합 기록 있어도 안 건드림
    "HOLD": step(0.12, 5.0),                   # 근거 없는 계단 ×41(모르는 병합일 수 있음) → 그대로
    "FAR": step(0.2, 2.0),                     # 야후 1:10 기록이 20일 떨어짐 → 같은 병합 아님
    "WRONG": step(0.68, 2.8),                  # SEC 1:2 인데 계단 ×4.1 → 비율 안 맞음
    "NODL": step(0.1, 1.0),                    # 야후 1:10 기록 · 야후에서 못 받음 → 저장 일봉만 고침
    "OLD": step(0.3, 3.0, at=200),             # 100봉 전 계단(최근 60일 밖) · 근거 없음
}
spike = np.full(300, 0.9); spike[S] = 7.0      # 하루만 튐 → 다시 받기만, 계단 아님
B["SPIKE"] = (spike.copy(), spike.copy())
crash = np.where(np.arange(300) < S, 1.0, 0.25)   # 진짜 폭락 ÷4 → 다시 받기만
B["CRASH"] = (crash.copy(), crash.copy())
B["STALE"] = step(0.8, 3.2)                    # ② 저장 일봉엔 ×4 계단, 야후는 이미 고침(3.2 로 평평)
YAHOO = {t: frame(*v, lo=300 - COV) for t, v in B.items() if t not in ("NODL", "STALE")}
YAHOO["STALE"] = frame(np.full(300, 3.2), np.full(300, 3.2), lo=300 - COV)

with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn); watch.ensure_tables(conn)
    for t, (o, c) in B.items():
        db.upsert_daily_prices(conn, t, frame(o, c))
    dd = lambda base, n: (date.fromisoformat(base) + timedelta(days=n)).isoformat()
    for t, d, r in (("LAT", dd(SD, 1), 1 / 16), ("PUMP", SD, 0.25), ("FAR", dd(SD, -20), 0.1), ("NODL", SD, 0.1)):
        conn.execute("INSERT INTO rs_events VALUES (?,?,?,1.0)", (t, d, r))
    for t, d, ti in (("SEC", dd(SD, 1), "역분할 1:25 시행"), ("WRONG", SD, "역분할 1:2 시행")):
        conn.execute("INSERT INTO events (ticker, date, kind, title, source, origin, created_at) VALUES (?,?,'역분할 시행',?,'x','secfeed','x')", (t, d, ti))
    conn.commit()
    db.set_meta(pricefix.META_KEY, "2026-10-31")    # 서버처럼: 옛 방식 첫 2년 수리는 이미 끝남

    # 순수 함수
    st, days = pricefix.find_jumps([(ds[i], B["LAT"][0][i], B["LAT"][1][i]) for i in range(300)])
    assert st == [(SD, 15.0)] and days == [SD], (st, days)
    assert pricefix.find_jumps([(ds[i], B["PUMP"][0][i], B["PUMP"][1][i]) for i in range(300)])[0] == []          # 시가부터 새 단위가 아니면 계단 아님
    assert pricefix.find_jumps([(ds[i], spike[i], spike[i]) for i in range(300)]) == ([], [SD, ds[S + 1]])       # 튀고 돌아옴
    assert pricefix.match_ratio(SD, 15.0, [(dd(SD, 1), 16.0)]) == 16.0 and pricefix.match_ratio(SD, 142.0, [(SD, 200.0)]) == 200.0   # AXG
    assert pricefix.match_ratio(SD, 4.1, [(SD, 2.0)]) is None and pricefix.match_ratio(SD, 10.0, [(dd(SD, -20), 10.0)]) is None
    j = pricefix.scan(conn)
    assert set(j) == {"LAT", "SEC", "PUMP", "HOLD", "FAR", "WRONG", "NODL", "SPIKE", "CRASH", "STALE"}, sorted(j)   # OLD 는 60일 밖
    assert set(pricefix.scan(conn, pricefix.LOOKBACK_DAYS)) == set(j) | {"OLD"}

    calls = []
    def dl(ts):
        calls.append(sorted(ts))
        return {t: YAHOO[t] for t in ts if t in YAHOO}
    logs = []
    r = pricefix.morning(conn, out=logs.append, download=dl)          # 계단 점검 처음 한 번 = 2년
    assert calls == [sorted(set(j) | {"OLD"})], calls
    fixed = {t: (d, n) for t, d, n, _ in r["steps_fixed"]}
    assert fixed == {"LAT": (SD, 16.0), "SEC": (SD, 25.0), "NODL": (SD, 10.0)}, r["steps_fixed"]
    assert {t for t, *_ in r["steps_unknown"]} == {"HOLD", "FAR", "WRONG", "OLD"}, r["steps_unknown"]
    assert [t for t, *_ in r["edge"]] == ["STALE"] and abs(r["edge"][0][1] - 4.0) < 1e-9, r["edge"]
    assert "직접 환산 3곳(LAT×16" in logs[0] and "병합 근거 없는 계단 4곳" in logs[0] and "2년 창 밖 옛 봉 배수 맞춤 1종목" in logs[0], logs[0]
    cl = lambda t: [x[0] for x in conn.execute("SELECT close FROM daily_prices WHERE ticker=? ORDER BY date", (t,))]
    vol = lambda t: [x[0] for x in conn.execute("SELECT volume FROM daily_prices WHERE ticker=? ORDER BY date", (t,))]
    assert np.allclose(cl("LAT")[:S], 3.2) and np.allclose(cl("LAT")[S:], 3.0) and np.allclose(vol("LAT")[:S], V / 16)   # 2년 창 밖(0~149)도
    assert np.allclose(cl("SEC")[:S], 12.5) and np.allclose(cl("NODL")[:S], 1.0)
    assert np.allclose(cl("STALE"), 3.2)                                                                                 # 창 밖 옛 봉도 야후 배수(×4)로
    for t in ("PUMP", "HOLD", "FAR", "WRONG", "OLD", "SPIKE", "CRASH"):
        assert np.allclose(cl(t), B[t][1]), t                                                                            # 근거 없는 건 그대로
    assert {x[0]: x[1] for x in conn.execute("SELECT ticker, n FROM price_adj")} == {"LAT": 16.0, "SEC": 25.0, "NODL": 10.0}
    assert db.get_meta(pricefix.STEPS_META) is not None

    # 둘째 날(병합 나흘 뒤라고 치면): LAT 는 최근 병합(10일 안)이라 다시 받음 → 야후 원자료(환산 전)가 돌아옴 → 다시 받은 구간만 다시 환산(창 밖은 이미 ×16 → ×256 되면 안 됨)
    T2 = date.fromisoformat(SD) + timedelta(days=4)
    calls.clear(); logs.clear()
    r2 = pricefix.morning(conn, out=logs.append, download=dl, today=T2)
    assert "LAT" in calls[0] and "SEC" not in calls[0] and "STALE" not in calls[0], calls   # 고친 종목은 계단이 없어 다시 안 받음(LAT 는 최근 병합이라 받음)
    assert r2["steps_fixed"] == [] and r2["steps_again"] == ["LAT"] and r2["edge"] == [] and "LAT" not in r2["changed"], r2   # 결국 그대로 → 🎲 사건 안 지움
    assert "다시 맞춘 종목 1개" in logs[0] and "실제로 바뀐 종목 0개" in logs[0], logs[0]
    assert np.allclose(cl("LAT")[:S], 3.2) and np.allclose(vol("LAT")[:S], V / 16), cl("LAT")[:3]
    # 셋째 날: 다른 갱신이 LAT 의 최근 봉을 원자료로 되돌렸는데 야후에서 못 받은 날 → 예전 경계는 내일로(창 밖까지 다시 곱하지 않음)
    db.upsert_daily_prices(conn, "LAT", frame(*B["LAT"], lo=S - 30))
    conn.commit()
    r3 = pricefix.morning(conn, out=lambda *_: None, download=lambda ts: {})
    assert r3["steps_fixed"] == [] and r3["steps_waiting"] == [("LAT", SD)], r3
    assert np.allclose(cl("LAT")[:S - 30], 3.2) and np.allclose(cl("LAT")[S - 30:S], 0.2)
    r4 = pricefix.morning(conn, out=lambda *_: None, download=dl)                                      # 다음 날 받으면 고침
    assert np.allclose(cl("LAT")[:S], 3.2) and np.allclose(cl("LAT")[S:], 3.0)
    # 야후가 나중에 병합을 반영하면: 다시 받아도 계단 없음 · 창 밖 배수도 1 → 그대로 맞음
    YAHOO["LAT"] = frame(np.where(np.arange(300) < S, 3.2, 3.0), np.where(np.arange(300) < S, 3.2, 3.0), lo=300 - COV)
    calls.clear()
    r5 = pricefix.morning(conn, out=lambda *_: None, download=dl, today=T2)
    assert "LAT" in calls[0] and r5["steps_fixed"] == [] and r5["edge"] == [] and np.allclose(cl("LAT")[:S], 3.2) and np.allclose(cl("LAT")[S:], 3.0), r5
print("ALL OK")
