import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, extalert, setup3, timemachine as tm
db.init_db()

# --- 🌙 시간외 급등 알림
D = date(2026, 10, 23)  # 금요일
with closing(db.connect()) as conn:
    conn.execute(setup3.LOG_DDL)
    conn.execute("INSERT INTO setup3_signals VALUES (?, 'AAA', 1.0, 1, 'x')", ((D - timedelta(days=1)).isoformat(),))
    conn.execute("INSERT INTO setup3_signals VALUES (?, 'BBB', 1.0, 0, 'x')", ((D - timedelta(days=1)).isoformat(),))
    db.upsert_daily_prices(conn, "AAA", pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1e5]}, index=pd.to_datetime([D.isoformat()])))
    db.upsert_daily_prices(conn, "BBB", pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1e5]}, index=pd.to_datetime([D.isoformat()])))
    conn.commit()
    assert set(extalert.interest(conn, today=D)) >= {"AAA", "BBB"}
    ix = pd.date_range("2026-10-23 16:05", periods=30, freq="min", tz="America/New_York")   # 애프터
    frames = {"AAA": pd.DataFrame({"High": np.r_[np.full(29, 1.02), [1.15]], "Close": np.full(30, 1.1)}, index=ix),
              "BBB": pd.DataFrame({"High": np.full(30, 1.05), "Close": np.full(30, 1.04)}, index=ix)}                   # +5% → 기준 미만
    msgs = []
    now = datetime(2026, 10, 23, 20, 40, tzinfo=timezone.utc)                                   # 16:40 ET
    sent = extalert.check(conn, frames, pct=10.0, send=lambda m: msgs.append(m) or True, now=now, download=lambda ts: {})
    assert sent == ["AAA"] and "+15.0%" in msgs[0] and "애프터마켓" in msgs[0] and "3대 조건" in msgs[0], msgs
    assert extalert.check(conn, frames, pct=10.0, send=lambda m: msgs.append(m) or True, now=now, download=lambda ts: {}) == []   # 같은 세션 한 번만
    reg_now = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)                                # 11:00 ET 정규장
    assert extalert.check(conn, frames, pct=10.0, send=lambda m: True, now=reg_now, download=lambda ts: {}) == []
    assert extalert._session(pd.Timestamp("2026-10-23 21:30", tz="America/New_York")) == "night" and extalert._session(pd.Timestamp("2026-10-23 05:00", tz="America/New_York")) == "pre"

# --- 🕰 과매도 심화: 투매 끝 · 호재 공시(그날 '전' 5일 안 · 당일 제외) · RSI 깊이
idx = pd.bdate_range(start="2025-01-02", periods=80)
c = np.r_[np.linspace(2.0, 1.2, 70), [1.0, 0.98, 0.97, 0.97, 0.98], np.full(5, 1.0)]
v = np.r_[np.full(70, 1e5), [6e5, 2e5, 1.5e5, 1e5, 1e5], np.full(5, 1e5)]
d = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": v}, index=idx)
k = idx[73].strftime("%Y-%m-%d")
gd = [idx[71].strftime("%Y-%m-%d"), idx[73].strftime("%Y-%m-%d")]
r = {x["date"]: x for x in tm.ticker_rows("X", d, [], idx[30].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d"), step=1, good=gd)}
assert r[k]["climax"] is True                                                                  # 70번째 날 투매(거래량 6배·−16.7%) 뒤 거래량 마름
assert r[k]["good"] is True and r[idx[71].strftime("%Y-%m-%d")]["good"] is False             # 공시 당일은 아직 모름
assert r[idx[60].strftime("%Y-%m-%d")]["ovs25"] in (True, False) and "ovs20" in r[k]
sm = tm.summarize(pd.DataFrame(list(r.values())))
assert any(x["조합"] == "과매도+투매 끝+③" for x in sm["combos"]) and any(x["조합"] == "📰 호재 공시(5일 안)" for x in sm["combos"])
import config
assert "EXT_ALERTS" in config.SETTINGS and "EXT_ALERT_PCT" in config.SETTINGS
# --- ⭐ 검증 순위: RSI≤20+희석 없음 1 · ≤25 2 · 과매도 3 · 희석 있거나 모르면 없음
assert setup3.tier(18, True, True) == 1 and setup3.tier(23, True, True) == 2 and setup3.tier(28, True, True) == 3 and setup3.tier(40, True, True) == 3
assert setup3.tier(15, True, False) is None and setup3.tier(15, True, None) is None and setup3.tier(45, False, True) is None
rows = [{"ticker": "T1", "tier": 1, "price": 1.0, "support": {"rsi": 18.0}, "dilution": {"label": "✅ 없음"}},
        {"ticker": "T2", "tier": None, "price": 1.0, "support": {"rsi": 50.0}, "dilution": {"label": "x"}}]
with closing(db.connect()) as conn:
    assert setup3.record_tiers(conn, rows) == 1 and setup3.record_tiers(conn, rows) == 0       # 10일에 한 번
    import scoreboard as sb
    col = sb.collect(conn)
    t1 = col[col["source"] == "s3_t1"]
    assert len(t1) == 1 and t1.iloc[0]["target"] == 30.0 and t1.iloc[0]["horizon"] == 40 and "RSI 18" in t1.iloc[0]["note"] and "반등형" in t1.iloc[0]["note"]
    import config as _c
    _c.TIER_HOLD_DAYS, _c.TIER_TARGET = 10, 25.0                                                # 관리 모드에서 바꾸면 판정 기준도 바뀜
    t1b = sb.collect(conn); t1b = t1b[t1b["source"] == "s3_t1"].iloc[0]
    assert t1b["horizon"] == 10 and t1b["target"] == 25.0
    _c.TIER_HOLD_DAYS, _c.TIER_TARGET = 40, 30.0
    assert "T1" in extalert.interest(conn)                                                       # 🌙 시간외 급등 알림 대상
# 타임머신: 비용 뺀 수익 · 거래 활발 종목 · 연도별 단타 수익
assert "분할 수익 −비용2%(%)" in sm["short"][0] and "거래 활발 종목 분할 수익(%)" in sm["short"][0]
assert sm["by_year"] and "⚡ 5일 분할 수익(%)" in sm["by_year"][0]
assert "hold" in sm and isinstance(sm["hold"], list)
print("ALL OK")
