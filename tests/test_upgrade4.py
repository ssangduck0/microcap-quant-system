import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import db, halts, papertrade as pt, news, config
db.init_db(); halts.fetch = lambda *a, **k: []
# ── 가상매매
rk = pd.DataFrame([{"ticker": "AAA", "rank": 1, "score": 60, "parts": {"매집": 80, "공시": 0}}, {"ticker": "BBB", "rank": 2, "score": 50, "parts": {"매집": 0, "공시": 100}},
                   {"ticker": "CCC", "rank": 3, "score": 40, "parts": {"매집": 50}}, {"ticker": "DDD", "rank": 4, "score": 30, "parts": {}}])
assert pt.open_new(rk, {"AAA": 1.0, "BBB": 2.0, "CCC": 4.0, "DDD": 9.0}, "2026-10-01") == ["AAA", "BBB", "CCC"]       # 1~3위만
assert pt.open_new(rk, {"AAA": 1.0, "BBB": 2.0, "CCC": 4.0}, "2026-10-01") == []                                      # 같은 날 두 번 안 삼
idx = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"])
bars = {"AAA": pd.DataFrame({"High": [1.0, 1.25, 1.0, 1.0], "Low": [1.0, 0.95, 1.0, 1.0], "Close": [1.0, 1.2, 1.0, 1.0]}, index=idx),          # 익절
        "BBB": pd.DataFrame({"High": [2.0, 2.5, 2.0, 2.0], "Low": [2.0, 1.7, 2.0, 2.0], "Close": [2.0, 2.1, 2.0, 2.0]}, index=idx),          # 같은 날 둘 다 → 손절
        "CCC": pd.DataFrame({"High": [4.0, 4.1, 4.2, 4.3], "Low": [4.0, 3.9, 4.0, 4.1], "Close": [4.0, 4.05, 4.1, 4.2]}, index=idx)}        # 3일 보유 종가
assert pt.update(bars) == 3
t = pt.trades().set_index("ticker"); print(t[["exit", "reason", "ret"]])
assert abs(t.loc["AAA", "exit"] - 1.2) < 1e-9 and t.loc["AAA", "reason"].startswith("익절") and abs(t.loc["BBB", "exit"] - 1.8) < 1e-9 and t.loc["BBB", "reason"].startswith("손절")
assert t.loc["CCC", "exit"] == 4.2 and "3일 보유" in t.loc["CCC", "reason"]
s = pt.summary(pt.trades(pt.book())); assert s["closed"] == 3 and abs(s["win"] - 200 / 3) < 1e-6 and abs(s["pnl"] - (200 - 100 + 50)) < 1e-6
bs = pt.by_signal(pt.trades()).set_index("신호"); assert abs(bs.loc["매집", "있을 때 평균(%)"] - 12.5) < 1e-9 and abs(bs.loc["공시", "있을 때 평균(%)"] + 10) < 1e-9
old = pt.book(); nb = pt.reset(); assert nb != old and pt.trades(nb).empty and len(pt.trades()) == 3                    # 초기화: 새 장부, 기록은 남음
# ── 순위 가중치
import rank
config.RANK_W_STRENGTH = 0.8
src = open(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "rank.py")).read(); assert "_cf.RANK_W_STRENGTH" in src and "_cf.RANK_W_NEWS" in src
# ── 뉴스
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>gnw-1</id><title>Abcd Bio Receives FDA Clearance (Nasdaq: ABCD)</title>
<link href="https://www.globenewswire.com/news-release/1"/><published>2026-10-21T12:30:00Z</published><summary>&lt;p&gt;Abcd Bio, Inc. (NASDAQ: ABCD) announced ...&lt;/p&gt;</summary></entry>
<entry><id>gnw-2</id><title>Xyz Corp Announces Pricing of $5 Million Registered Direct Offering</title><link href="https://x/2"/><updated>2026-10-21T13:00:00Z</updated>
<summary>Xyz Corp (NasdaqCM: XYZ) today announced the pricing</summary></entry></feed>"""
RSS = """<rss><channel><item><title>Foo signs contract</title><link>https://y/3</link><guid>g3</guid><pubDate>Tue, 21 Oct 2026 14:00:00 GMT</pubDate>
<description>Foo Inc. (OTCQB: FOOO)</description></item></channel></rss>"""
it = news.parse_feed(ATOM) + news.parse_feed(RSS); assert len(it) == 3 and it[0]["summary"].startswith("Abcd Bio, Inc.") and it[2]["published"].startswith("2026-10-21T14:00")
class R:
    def __init__(s, t): s.text, s.status_code = t, 200
news.set_feeds(["f1", "f2"])
res = news.refresh(lambda u: R(ATOM if u == "f1" else RSS), force=True); assert res == {"f1": 2, "f2": 1}
df = news.recent(36500).set_index("id"); print(df[["ticker", "exchange", "sentiment", "tags"]])
assert df.loc["gnw-1", "ticker"] == "ABCD" and df.loc["gnw-1", "sentiment"] == "호재" and df.loc["gnw-2", "ticker"] == "XYZ" and df.loc["gnw-2", "exchange"] == "NASDAQ"
assert df.loc["gnw-2", "sentiment"] == "악재" and pd.isna(df.loc["g3", "ticker"]) and news.refresh(lambda u: R(ATOM)) == {}                       # 10분 안엔 다시 안 받음
# ── 화면
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "AAA", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
import watch_ui
_c = np.r_[np.linspace(2, 1, 80), np.linspace(1, 1.3, 20)]
watch_ui.prices = lambda tk: {t: pd.DataFrame({"Open": _c, "High": _c * 1.02, "Low": _c * 0.98, "Close": _c, "Volume": 1e6}, index=pd.bdate_range(start=pd.Timestamp.today().normalize() - pd.Timedelta(days=160), periods=100)) for t in tk}
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
for pg in ("papertrade", "news", "chart"):
    os.environ["QUANT_TEST_PAGE"] = pg
    at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, (pg, [e.value for e in at.exception])
    html = "\n".join(m.value for m in at.markdown)
    if pg == "papertrade":
        assert "장부별 결과" in html and "신호별 성과" in html and [b for b in at.button if b.key == "pt_reset"]
    if pg == "news":
        assert "ABCD · NASDAQ" in html and "FDA" in html and "Registered Direct" in html
    if pg == "chart":
        at.text_input(key="ta_extra").set_value("AAA").run(); assert not at.exception
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
