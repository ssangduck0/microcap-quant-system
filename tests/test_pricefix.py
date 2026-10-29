"""🩹 pricefix — 병합 뒤 저장 일봉의 옛 기준 봉 찾기(경계 점프) · 야후 2년치로 다시 쓰기 · 처음 한 번은 전부, 그 뒤엔 최근 병합+경계만."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import db, rsplit, pricefix

db.init_db()
T = date.today()
D = lambda n: (T - timedelta(days=n)).isoformat()
idx = pd.bdate_range(end=pd.Timestamp(T) - pd.Timedelta(days=1), periods=120)
with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn)
    conn.execute("INSERT INTO rs_events VALUES ('AAA', ?, 0.1, 5.0)", (D(40),))     # 1:10, 병합 전 봉이 옛 기준(0.5) → 경계 점프 ×10
    conn.execute("INSERT INTO rs_events VALUES ('BBB', ?, 0.25, 8.0)", (D(40),))    # 1:4, 자료는 이미 환산됨(점프 없음)
    conn.execute("INSERT INTO rs_events VALUES ('CCC', ?, 0.2, 3.0)", (D(4),))      # 최근 병합
    conn.execute("INSERT INTO rs_events VALUES ('OLD', ?, 0.5, 3.0)", (D(900),))    # 2년 밖 → 대상 아님
    for t, lo, hi in (("AAA", 0.5, 5.0), ("BBB", 8.0, 8.0), ("CCC", 3.0, 3.0), ("OLD", 3.0, 3.0)):
        sd = pd.Timestamp(D(40) if t != "CCC" else D(4))
        c = np.where(idx < sd, lo, hi)
        db.upsert_daily_prices(conn, t, pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1e5}, index=idx))
    conn.commit()
    assert pricefix.boundary_tickers(conn) == ["AAA"] and pricefix.recent_split_tickers(conn) == ["CCC"] and pricefix.split_tickers(conn) == ["AAA", "BBB", "CCC"]
    calls = []
    def dl(ts):
        calls.append(list(ts))
        return {t: pd.DataFrame({"Open": 5.0, "High": 5.0, "Low": 5.0, "Close": 5.0, "Volume": 1e5}, index=idx) for t in ts if t in ("AAA", "BBB")}   # CCC 는 야후에 없음 → 그대로
    r = pricefix.morning(conn, out=lambda *_: None, download=dl)
    assert r["first"] and r["asked"] == 3 and r["tickers"] == 2 and r["rows"] == 240 and r["left"] == [] and calls == [["AAA", "BBB", "CCC"]], r
    assert tuple(conn.execute("SELECT MIN(close), MAX(close) FROM daily_prices WHERE ticker='AAA'").fetchone()) == (5.0, 5.0)   # 옛 기준 봉이 새 기준으로
    assert conn.execute("SELECT COUNT(*) FROM daily_prices WHERE ticker='CCC' AND close=3.0").fetchone()[0] == 120                # 야후에 없으면 지우지 않음
    assert db.get_meta(pricefix.META_KEY)["value"] == T.isoformat()
    calls.clear()
    r2 = pricefix.morning(conn, out=lambda *_: None, download=dl)                                                              # 두 번째: 최근 병합(CCC) + 경계(없음) 만
    assert not r2["first"] and r2["asked"] == 1 and calls == [["CCC"]] and r2["tickers"] == 0, (r2, calls)
    r3 = pricefix.morning(conn, out=lambda *_: None, download=dl, today=T + timedelta(days=30))                                  # 30일 뒤엔 최근 병합도 없음 → 다운로드 0
    assert r3["asked"] == 0 and len(calls) == 1
print("ALL OK")
