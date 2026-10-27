import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, halts, accum, market, secbackfill, watch
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso(); today = date.today().isoformat()
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=64)[-62:][-60:]   # 일요일엔 periods 보다 하나 적게 나오는 pandas 동작 대비
c = np.full(60, 0.95); v = np.full(60, 1e5); c[-6] = 0.95
for k, (ch, vr) in enumerate([(0.02, 3), (0.01, 3.5), (0.0, 4), (0.143, 30)]):
    i = 56 + k; c[i] = c[i - 1] * (1 + ch); v[i] = 1e5 * vr
KM = pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": v}, index=idx)
market.download_daily = lambda tk, period="3mo", chunk=200: {t: KM for t in tk if t in ("KMRK", "ICG")}
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": today, "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    secbackfill.ensure_tables(conn)
    d1 = (date.today() - timedelta(days=3)).isoformat(); d0 = (date.today() - timedelta(days=40)).isoformat(); d2 = (date.today() - timedelta(days=1)).isoformat()
    for acc, t, fm, d in (("e1", "ICG", "EFFECT", d1), ("e0", "ICG", "F-1", d0), ("e2", "ICG", "424B4", d2), ("n1", "ICG", "6-K", d2)):
        conn.execute("INSERT INTO sec_hist VALUES (?,?,?,?,'')", (acc, t, fm, d))
    conn.commit()
accum.run(["KMRK", "ICG"], out=lambda *_: None)
watch.add("KMRK", "관심")
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "accum"
at = AppTest.from_file(APP, default_timeout=180).run(); print("exc:", [e.value for e in at.exception]); assert not at.exception
cards = [m.value for m in at.markdown if 'class="qk-tk"' in m.value]; print(len(cards))
km = [x for x in cards if "KMRK" in x][0]; icg = [x for x in cards if "ICG" in x][0]
assert "강한 매집 의심" in km and "이유 미확인" in km and "희석 서류 없음(45일)" in km and "관심" in km and "&#36;1 근처" in km and "흡수일 4일" in km
assert "희석 서류 2건" in icg or "희석 서류 3건" in icg; assert "공시 1건" in icg
at.radio(key="ac_view").set_value("티커만").run(); assert any("KMRK" in m.value and "qk-chip" in m.value and "tossinvest.com" in m.value for m in at.markdown)
at.radio(key="ac_view").set_value("펼침").run(); at.radio(key="ac_per").set_value("월간").run(); assert not at.exception
at.slider(key="ac_min").set_value(10.0).run(); assert not [m for m in at.markdown if 'class="qk-tk"' in m.value]
os.environ["QUANT_TEST_PAGE"] = "effect"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
ef = [m.value for m in at.markdown if 'class="qk-tk"' in m.value]; print(ef[0][:300])
assert len(ef) == 1 and "ICG" in ef[0] and "희석 임박" in ef[0] and "424B 가격 확정" in ef[0] and "F-1" in ef[0]
os.environ.pop("QUANT_TEST_PAGE")
print("ALL OK")
