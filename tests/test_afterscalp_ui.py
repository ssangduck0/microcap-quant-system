import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, afterscalp as af, halts, notes_ui
db.init_db(); halts.fetch = lambda *a, **k: []
ET = ZoneInfo("America/New_York")
now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
a_start, a_end = now - timedelta(minutes=150), now + timedelta(minutes=90)          # 애프터 2시간 30분 진행 중
db.set_meta("us_after_start", a_start.isoformat()); db.set_meta("us_after_end", a_end.isoformat()); db.set_meta("us_session", "애프터마켓"); db.set_meta("usdkrw", "1342")
idx = pd.date_range(now.astimezone(ET) - timedelta(minutes=900), now.astimezone(ET), freq="min")
n = len(idx); s = n - 150
base = np.full(n, 1.0); base[s:s + 30] = np.linspace(1.0, 1.3, 30); base[s + 30:s + 90] = np.linspace(1.3, 1.08, 60); base[s + 90:] = 1.08 + 0.002 * np.sin(np.arange(n - s - 90))
GOOD = pd.DataFrame({"Open": base, "High": base * 1.003, "Low": base * 0.997, "Close": base, "Volume": 1e5}, index=idx)
THIN = GOOD.copy(); THIN["Volume"] = 10.0
import scanner, toss, closewatch, notify, config, universe
class TC:
    def rankings(self, rank_type, country="US", duration="1d", count=20):
        if rank_type == "TOP_GAINERS": raise RuntimeError("unknown rank type")
        return [{"symbol": "GOODX", "price": {"lastPrice": "1.08", "basePrice": "1.0"}}, {"symbol": "THINX", "price": {"lastPrice": "1.08", "basePrice": "1.0"}}]
    def stocks(self, syms): return [{"symbol": s, "securityType": "STOCK", "isCommonShare": True, "status": "ACTIVE"} for s in syms]
toss.fetch_intraday_many = lambda tc, syms, workers=4, deadline_sec=150: {t: {"GOODX": GOOD, "THINX": THIN}[t] for t in syms if t in ("GOODX", "THINX")}
universe.from_watchlist = lambda: []
sent = []; notify.send_telegram = lambda m: sent.append(m) or True
with closing(db.connect()) as conn:
    scanner.after_scalp_cycle(conn, TC(), {})
    scanner.after_scalp_cycle(conn, TC(), {})                                       # 같은 날 두 번째 사이클: 신호·알림 중복 없음
day = a_start.astimezone(ET).date().isoformat()
st_ = {t: d for t, _, d in af.states(day)}; print({t: d["stage"] for t, d in st_.items()})
assert st_["GOODX"]["stage"] == af.STAGE_IN and st_["THINX"]["stage"] == "–"           # 거래대금 부족은 제외
sig = af.signals(); assert list(sig["ticker"]) == ["GOODX"] and len([m for m in sent if m.startswith("🌙 GOODX")]) == 1
kst = af.deadline_of(a_end).astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M"); assert f"매도 마감 {kst} KST" in sent[0] and "손절 -5%" in sent[0]
# 매도 마감 5분 전 알림(한 번만)
db.set_meta("us_after_end", (now + timedelta(minutes=12)).isoformat())
with closing(db.connect()) as conn:
    scanner.after_scalp_cycle(conn, TC(), {}); scanner.after_scalp_cycle(conn, TC(), {})
assert sum(m.startswith("⏰ 애프터 매도 마감") for m in sent) == 1
print("scanner OK")
# 대시보드 (스냅샷이 하나도 없으면 대시보드가 '기록 없음'으로 일찍 멈추므로 한 줄 넣음)
_now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": day, "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": _now, "last_seen": _now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -15.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
from streamlit.testing.v1 import AppTest
import streamlit as st
st.cache_data.clear()
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception and "🌙 애프터 스캘핑" in [x.label for x in at.tabs]
assert af.TIP_TITLE in notes_ui.list_titles()
tb = [d.value for d in at.dataframe if "MA50 거리(%)" in d.value.columns][0]; print(tb[["티커", "단계", "거래대금(억 원)", "정상 캔들(%)", "급등(%)"]].to_string(index=False))
assert tb.iloc[0]["티커"] == "GOODX" and tb.iloc[0]["단계"] == af.STAGE_IN
assert any(m.value.startswith("#### 🌙 GOODX") for m in at.markdown)
mt = {m.label: m.value for m in at.metric}; assert mt["지금 세션"] == "애프터마켓" and mt["신호"] == "1"
sg = [d.value for d in at.dataframe if "먼저 닿은 쪽" in d.value.columns][0]; assert sg.iloc[0]["티커"] == "GOODX"
print("ALL OK")
