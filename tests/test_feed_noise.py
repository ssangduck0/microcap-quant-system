"""🔔 공시 피드 잡음(2026-10-30) — 대형 은행 구조화 채권(424B2)은 우리가 보는 종목이 아니면 저장 안 함 · 이미 쌓인 것은 본문 안 받고 처리됨 ·
본문 받기는 우리 종목 먼저 · 공시 화면에서 숨김. 8-K 같은 다른 양식은 넓은 범위(토스 거래 가능 전 종목) 그대로."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import db, secfeed as sf

db.init_db()
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": "2026-10-29", "ticker": "MICRO", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.5, "high_20d": 1.0, "low_20d": 0.4,
        "drawdown_pct": -50.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
sf._CORE_CACHE["at"] = 0.0
core = sf.core_tickers()
assert "MICRO" in core and "JPM" not in core, core
assert sf.is_noise("424B2", "JPM", core) and sf.is_noise("424b2", "jpm", core) and not sf.is_noise("424B2", "MICRO", core)
assert not sf.is_noise("8-K", "JPM", core) and not sf.is_noise("424B5", "JPM", core) and not sf.is_noise(None, None, core)   # 잡음 양식만

E = lambda form, name, cik, acc: (f'<entry><title>{form} - {name} ({cik:010d}) (Filer)</title><link href="https://www.sec.gov/Archives/edgar/data/{cik}/{acc}-index.htm"/>'   # noqa: E731
                                  f'<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-10-30 &lt;b&gt;AccNo:&lt;/b&gt; {acc}</summary><updated>2026-10-30T10:0{len(acc) % 9}:00-04:00</updated>'
                                  f'<id>urn:tag:sec.gov,2008:accession-number={acc}</id></entry>')
ATOM = ('<?xml version="1.0" encoding="ISO-8859-1" ?><feed xmlns="http://www.w3.org/2005/Atom"><title>Latest Filings</title>'
        + E("424B2", "JPMorgan Chase", 19617, "0001213900-26-000001") + E("424B2", "Micro Corp", 1111, "0001111111-26-000002")
        + E("8-K", "JPMorgan Chase", 19617, "0000019617-26-000003") + "</feed>")
fetched = []
class FC:
    def _get(s, url, **kw):
        fetched.append(url)
        class R: pass
        r = R(); r.text = ATOM if "getcurrent" in url else '<a href="/Archives/edgar/data/1/doc.htm">doc</a>'; return r
    def fetch_text(s, url, limit=0): fetched.append(url); return "Item 8.01 Other events."
n = sf.poll(FC(), {19617: "JPM", 1111: "MICRO"}, types=["424B"])
with closing(db.connect()) as conn:
    got = sorted((r[0], r[1]) for r in conn.execute("SELECT ticker, form FROM sec_feed"))
assert n == 2 and got == [("JPM", "8-K"), ("MICRO", "424B2")], (n, got)              # JPM 424B2 만 빠짐(JPM 8-K·우리 종목 424B2 는 저장)

# ---- 이미 쌓인 대기분: 잡음은 본문 안 받고 처리됨 · 우리 종목 먼저
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM sec_feed")
    rows = [("n1", "JPM", 19617, "424B2", "2026-10-30T12:00:00", "https://www.sec.gov/noise-index.htm"),
            ("o1", "OTHER", 2222, "8-K", "2026-10-30T11:00:00", "https://www.sec.gov/other-index.htm"),       # 우리 종목 아님(넓은 범위) · 더 최신
            ("m1", "MICRO", 1111, "8-K", "2026-10-30T09:00:00", "https://www.sec.gov/micro-index.htm")]
    conn.executemany("INSERT INTO sec_feed (accession, ticker, cik, form, updated, items, url, enriched, created_at) VALUES (?,?,?,?,?,'',?,0,'x')", rows)
    conn.commit()
fetched.clear()
assert sf.enrich(FC(), limit=1) == 1
assert not any("noise" in u for u in fetched) and any("micro" in u for u in fetched) and not any("other" in u for u in fetched), fetched
with closing(db.connect()) as conn:
    st = dict(conn.execute("SELECT accession, enriched FROM sec_feed").fetchall())
assert st == {"n1": 1, "m1": 1, "o1": 0}, st                                              # 잡음 처리됨(지우지 않음) · 우리 종목 먼저 · 남은 건 다음에
assert sf.enrich(FC(), limit=5) == 1 and any("other" in u for u in fetched)

# ---- 공시 화면: 잡음 숨김
with closing(db.connect()) as conn:
    conn.execute("UPDATE sec_feed SET filed='2026-10-30'"); conn.commit()
f = sf.feed(days=3650)
assert set(f["ticker"]) == {"MICRO", "OTHER"} and "JPM" not in set(f["ticker"]), list(f["ticker"])
print("ALL OK")
