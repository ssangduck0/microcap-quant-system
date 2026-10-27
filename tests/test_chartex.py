import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""📡 ChartExchange: 가짜 HTTP 로 페이지 넘기기(최신순, since 까지) · 저장 4표 · short_interest 거울 · 신호(잔고 +30%·FTD 급증) · 성과 공표 수집 · 429 재시도 · 403 주식수 건너뜀 · 키 없으면 꺼짐."""
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("CHARTEXCHANGE_API_KEY", None)
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, chartex as cx, shortint, scoreboard as sb
os.environ.pop("CHARTEXCHANGE_API_KEY", None)   # config 가 .env 를 읽어 다시 넣으므로 import 뒤에 비움
db.init_db()
with closing(db.connect()) as _c:
    shortint.ensure_tables(_c)
assert not cx.enabled() and cx.collect(out=lambda *_: None) == {}                      # 키 없으면 조용히 꺼짐
today = date.today()
D = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
calls = []


def fake_get(url, q):
    calls.append((url.split("/api/v1/")[1], q.get("page", 1), q.get("symbol")))
    ep, page = url.split("/api/v1/")[1], int(q.get("page", 1))
    sym = q["symbol"].split(":")[1]
    if sym == "RATE" and len([c for c in calls if c[2] == q["symbol"]]) == 1:
        return 429, ""
    if ep.startswith("data/stocks/shares/") and sym == "NOSH":
        return 403, "forbidden"
    if ep.startswith("data/stocks/short-interest-daily/"):
        rows = [{"date": D(i), "short_interest": str(20 + i), "short_position": 1000 + i, "days_to_cover": "2.0", "change_number": 500 if i == 3 else 0, "change_percent": "50.0" if i == 3 else "0.0"} for i in range(0, 40)]
        return 200, json.dumps({"count": 40, "next": None, "results": rows[(page - 1) * 1000: page * 1000]})
    if ep.startswith("data/stocks/short-interest/"):
        return 200, json.dumps({"count": 1, "next": None, "results": [{"date": D(3), "short_interest": "23", "short_position": 1003, "days_to_cover": "2.0", "change_number": 500, "change_percent": "50.0"}]})
    if ep.startswith("data/stocks/failure-to-deliver/"):
        rows = [{"date": D(i), "fails": 90_000 if i == 0 else 5_000, "price": "1.0", "t": D(i + 1), "t_35": D(i - 35), "noti": "100.0", "change": 0} for i in range(0, 30)]
        ps = int(q.get("page_size", 1000)); part = rows[(page - 1) * ps: page * ps]
        return 200, json.dumps({"count": 30, "next": "x" if page * ps < 30 else None, "results": part})
    if ep.startswith("data/stocks/short-volume/"):
        return 200, json.dumps({"results": [{"date": D(0), "rt": 1000, "st": 600, "lt": 400, "fs": 500, "fse": 50, "xnas": 30, "xnys": 20, "arcx": 0}]})
    if ep.startswith("data/stocks/shares/"):
        return 200, json.dumps({"results": [{"date": D(0), "shares_out": 5_000_000, "shares_float": 3_000_000, "free_float": 60.0}]})
    if ep.startswith("data/stocks/borrow-fee/ib/"):
        return 200, json.dumps({"results": [{"timestamp": "2026-10-27 05:13:47", "available": 70000, "fee": "1050.5", "rebate": "-1046.6"}]})
    return 404, ""


client = cx.Client(key="test", rpm=100000, http_get=fake_get)
with closing(db.connect()) as conn:
    cx.ensure(conn)
    # since 까지만: 최신순 40행 중 since = 10일 전 → 11행
    rows = client.rows("data/stocks/short-interest-daily/", "AAA", D(10)); assert len(rows) == 11 and rows[0]["date"] == D(0)
    # FTD 는 2페이지(25 + 5) · 30일 전까지
    rows = client.rows("data/stocks/failure-to-deliver/", "AAA", D(40), page_size=25); assert len(rows) == 30 and calls[-1][1] == 2
    r = cx.pull(conn, client, "aaa", backfill=True, shares_ok={"ok": True})
    assert r["si"] >= 41 and r["ftd"] == 30 and r["sv"] == 1 and r["shares"] == 1, r
    si = conn.execute("SELECT si_pct, dtc, reported FROM cx_short_interest WHERE ticker='AAA' AND date=?", (D(3),)).fetchone(); assert tuple(si) == (23.0, 2.0, 1)
    sv = dict(conn.execute("SELECT * FROM cx_short_volume WHERE ticker='AAA'").fetchone()); assert sv["exch_short"] == 50 and abs(sv["short_pct"] - 60) < 1e-9 and sv["finra_short"] == 500
    m = conn.execute("SELECT si_pct, dtc, si_date, float_sh, src FROM short_interest WHERE ticker='AAA'").fetchone()
    assert tuple(m) == (20.0, 2.0, D(0), 3_000_000.0, "chartexchange")                      # 기존 표에 거울(스퀴즈·AI PICK 이 그대로 씀)
    assert conn.execute("SELECT last_date FROM cx_progress WHERE ticker='AAA' AND kind='ftd'").fetchone()[0] == D(0)
    # 두 번째(증분): since = 마지막 날짜 → 그날 이후만
    calls.clear(); r2 = cx.pull(conn, client, "AAA"); assert r2["si"] == 1 and r2["ftd"] == 1 and all(c[1] == 1 for c in calls)
    # 403 주식수 → 이번 실행 동안 건너뜀
    ok = {"ok": True}; r3 = cx.pull(conn, client, "NOSH", kinds=("si", "shares"), shares_ok=ok); assert ok["ok"] is False and r3["shares"] == 0
    assert cx.pull(conn, client, "NOSH2", kinds=("shares",), shares_ok=ok) == {}                 # 건너뜀
    # 429 → 61초 대기 후 재시도(테스트에선 sleep 을 가짜로)
    import time as _t; _orig = _t.sleep; _t.sleep = lambda s: None
    try:
        assert len(client.rows("data/stocks/short-volume/", "RATE", None)) == 1
    finally:
        _t.sleep = _orig
    # 신호: 잔고 보고 +50%(3일 전 보고) → si_up · FTD 90,000 vs 평균 5,000 → ftd_spike
    n = cx.record_signals(conn); assert n == 3, n   # AAA si_up·ftd_spike + NOSH si_up(가짜 응답이 같음)
    sig = {r[0]: r[1] for r in conn.execute("SELECT kind, note FROM cx_signals WHERE ticker='AAA'")}
    assert "si_up" in sig and "ftd_spike" in sig and "18.0배" in sig["ftd_spike"], sig
    assert cx.record_signals(conn) == 0                                                         # 같은 날 중복 없음
    # 화면용 조회
    f = cx.ftd_summary(conn, "AAA"); assert f["last"]["fails"] == 90_000 and f["n"] == 30 and f["max"]["settle_date"] == D(0)
    assert cx.ftd_map(conn)["AAA"]["fails"] == 90_000 and cx.float_of(conn, "AAA")["shares_float"] == 3_000_000 and len(cx.si_series(conn, "AAA")) >= 40
    assert len(cx.borrow_recent(conn, client, "AAA")) == 1 and len(cx.borrow_recent(conn, client, "AAA")) == 1   # 두 번째는 캐시(요청 안 함)
    # 🏆 성과 공표에 들어감
    df = sb.collect(conn)
    assert set(df[df["source"].str.startswith("cx_")]["source"]) == {"cx_si_up", "cx_ftd_spike"}
    st_ = cx.status(conn); assert st_["cx_ftd"]["tickers"] == 1
# collect(): 대상 고르기 + 시간 예산
with closing(db.connect()) as conn:
    tg = cx.targets(conn); assert set(tg) == {"si", "ftd", "sv"}
res = cx.collect(client=client, out=lambda *_: None, tg={"si": ["BBB"], "ftd": ["BBB", "CCC"], "sv": ["CCC"]})
assert res["tickers"] == 2 and res["ftd"] >= 2 and res["errors"] == 0 and res["calls"] > 0, res
print("ALL OK")
