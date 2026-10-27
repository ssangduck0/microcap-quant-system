import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🪪 토스 거래 가능 목록: 저장(시장별 실패 건너뜀·하루 1회) · 보통주만 · 배지 문구 · 다크풀 상위 표와 스퀴즈 후보가 이 목록으로 걸러짐."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import pandas as pd
import db, tradable, shortdata, darkpool as dp, squeeze
db.init_db()


class TC:
    calls = []

    def stocks_all(self, market, status="ACTIVE"):
        TC.calls.append(market)
        if market == "NYSE":
            raise RuntimeError("no NYSE")
        return [{"symbol": "GOOD", "name": "Good Co", "securityType": "STOCK", "isCommonShare": True, "status": "ACTIVE"},
                {"symbol": "ETFX", "name": "Some ETF", "securityType": "ETF", "isCommonShare": True, "status": "ACTIVE"},
                {"symbol": "PREF", "name": "Pref", "securityType": "STOCK", "isCommonShare": False, "status": "ACTIVE"},
                {"symbol": "DEAD", "name": "Dead", "securityType": "STOCK", "isCommonShare": True, "status": "DELISTED"},
                {"symbol": "", "name": "x"}] if market == "NASDAQ" else [{"symbol": "AMX", "name": "Amex Co", "securityType": "STOCK", "isCommonShare": True, "status": "ACTIVE"}]


with closing(db.connect()) as conn:
    assert tradable.active(conn) == set()                                         # 표 없음 → 빈 집합(예전 규칙으로)
    assert tradable.refresh_daily(conn, TC(), out=lambda *_: None) == 5 and TC.calls == ["NASDAQ", "AMEX", "NYSE"]
    assert tradable.refresh_daily(conn, TC()) == 0                                # 같은 날 두 번은 안 받음
    assert tradable.active(conn) == {"GOOD", "AMX"}
    assert tradable.label("GOOD") == "" and tradable.label("ETFX") == "ETF·펀드·워런트" and tradable.label("PREF") == "보통주 아님"
    assert tradable.label("DEAD") == "토스 상장폐지·거래정지" and tradable.label("LQTI") == "토스 미지원"
    # 다크풀 상위 표: 목록에 있는 GOOD 만 남고 ETFX(장외 200만 주라도)·LQTI 는 빠짐
    shortdata.ensure_tables(conn)
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-10-23", periods=3)]
    for d in days:
        for t, dpv, vol in (("GOOD", 500_000, 1_000_000), ("ETFX", 2_000_000, 2_100_000), ("LQTI", 1_500_000, 1_600_000)):
            conn.execute("INSERT INTO finra_shvol VALUES (?,?,?,?,?)", (d, t, dpv * 0.5, 0, dpv))
            db.upsert_daily_prices(conn, t, pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [vol]}, index=pd.to_datetime([d])))
    conn.commit()
    tradable._CACHE["set"] = None
    day, top = dp.top(conn, n=30)
    assert list(top["ticker"]) == ["GOOD"], top
    # 스퀴즈 후보도 목록으로 걸러짐
    conn.execute("INSERT INTO ibkr_borrow (symbol, fee, rebate, available, avail_capped, as_of) VALUES ('ETFX', 90.0, -80.0, 100, 0, 'x')")
    conn.execute("INSERT INTO ibkr_borrow (symbol, fee, rebate, available, avail_capped, as_of) VALUES ('GOOD', 90.0, -80.0, 100, 0, 'x')")
    conn.commit()
    uni = squeeze.universe(conn)
    assert "GOOD" in uni and "ETFX" not in uni, uni
print("ALL OK")
