"""🔥 화면 캐시(pagecache, 2026-10-28): 저장소 · event_flags 벡터화(옛 구현과 같은 결과) · warm/prices/s3_data/secflags · 🏁·📚·⚡·⚙️ 화면이 캐시를 쓰는지 · 명령줄 — 인터넷 없이."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, json, tempfile, subprocess
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, halts, market, accum, regsho, watch, rank, pagecache, secbackfill as sb
db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables()
T = date.today(); d = lambda n: (T - timedelta(days=n)).isoformat()

# 가짜 야후: 요청 종목마다 130일 일봉, 호출 기록
calls = []
def fake_download(tickers, period="3mo", chunk=40):
    calls.append(sorted(tickers))
    idx = pd.bdate_range(end=pd.Timestamp(T), periods=130); out = {}
    for i, t in enumerate(tickers):
        rs = np.random.RandomState(i + 1); c = np.maximum(0.5, 2 + np.cumsum(rs.normal(0, 0.05, 130)))
        out[t] = pd.DataFrame({"Open": c, "High": c * 1.03, "Low": c * 0.97, "Close": c, "Volume": rs.randint(100_000, 1_000_000, 130).astype(float)}, index=idx)
    return out
market.download_daily = fake_download

# 1) 저장소: 넣기·꺼내기·나이·무효화·깨진 값
pagecache.put("k1", {"a": 1}); assert pagecache.get("k1") == {"a": 1} and pagecache.get("k1", 10) == {"a": 1} and pagecache.age_min("k1") < 1
with closing(db.connect()) as conn:
    conn.execute("UPDATE page_cache SET built_at=? WHERE name='k1'", ((datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat(),)); conn.commit()
assert pagecache.get("k1", 60) is None and pagecache.get("k1") == {"a": 1} and 119 < pagecache.age_min("k1") < 122
pagecache.put("k1", pd.DataFrame({"x": [1, 2]})); assert len(pagecache.get("k1", 5)) == 2
pagecache.invalidate("k1"); assert pagecache.get("k1") is None and pagecache.age_min("k1") is None
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO page_cache VALUES ('bad', ?, 1.0, X'00FF')", (db.utcnow_iso(),)); conn.commit()
assert pagecache.get("bad") is None and pagecache.status()[0]["항목"] == "bad"; pagecache.invalidate("bad")

# 2) event_flags 벡터화 — 2026-10-28 이전 구현(그대로 옮김)과 결과가 같아야 한다
def ref_event_flags(ev, hist):
    FLAGS, OFFER = sb.FLAGS, sb.OFFER
    out = pd.DataFrame(index=ev.index, columns=list(FLAGS), dtype=object)
    if ev.empty or hist.empty:
        return out
    h = hist.copy(); h["d"] = pd.to_datetime(h["filed"]).values.astype("datetime64[D]"); h["items"] = h["items"].fillna("")
    groups = {t: g for t, g in h.groupby("ticker")}
    sel = {"offering": lambda g: g["form"].str.startswith(OFFER),
           "notice": lambda g: g["form"].str.startswith("8-K") & g["items"].str.contains(r"\b3\.01\b"),
           "charter": lambda g: g["form"].str.startswith("8-K") & g["items"].str.contains(r"\b5\.03\b"),
           "news": lambda g: g["form"].str.startswith(("8-K", "6-K")), "quiet": lambda g: pd.Series(True, index=g.index)}
    for t, idx in ev.groupby("ticker").groups.items():
        if t not in groups:
            continue
        g = groups[t]; days = pd.to_datetime(ev.loc[idx, "date"]).values.astype("datetime64[D]")
        for name, (_, a, b) in FLAGS.items():
            arr = np.sort(g.loc[sel[name](g), "d"].values)
            lo = np.searchsorted(arr, days + np.timedelta64(a, "D"), side="left"); hi = np.searchsorted(arr, days + np.timedelta64(b, "D"), side="right")
            has = (hi - lo) > 0; out.loc[idx, name] = (~has) if name == "quiet" else has
    return out
code = lambda f: f.map(lambda v: -1 if pd.isna(v) else int(bool(v)))
rs = np.random.RandomState(7); tk = [f"T{i:02d}" for i in range(30)]
forms = ["424B5", "S-1", "F-3", "EFFECT", "8-K", "8-K", "6-K", "10-Q", "10-K", "SC 13G", "4"]; items_pool = ["", "1.01", "3.01", "5.03", "3.01,5.03", "8.01,9.01", "2.02"]
hist = pd.DataFrame({"ticker": rs.choice(tk[:24], 600), "form": rs.choice(forms, 600), "filed": [(date(2020, 1, 1) + timedelta(days=int(x))).isoformat() for x in rs.randint(0, 1500, 600)], "items": rs.choice(items_pool, 600)})
hist.loc[::50, "items"] = None
ev = pd.DataFrame({"ticker": rs.choice(tk, 150), "date": [(date(2020, 3, 1) + timedelta(days=int(x))).isoformat() for x in rs.randint(0, 1400, 150)]}, index=rs.permutation(1000)[:150])
new, ref = sb.event_flags(ev, hist), ref_event_flags(ev, hist)
assert list(new.columns) == list(ref.columns) and new.index.equals(ref.index) and (code(new).values == code(ref).values).all(), (code(new) != code(ref)).sum()
assert (code(new) >= 0).any().any() and (code(new) == -1).any().any()      # 덮인 종목·안 덮인 종목 둘 다 들어 있는 데이터였다
assert sb.event_flags(ev.iloc[:0], hist).empty and sb.event_flags(ev, hist.iloc[:0]).isna().all().all()

# 3) 데이터: 사건 3건 · 공시 5건(백필 완료 2종목) · 매집(순위 대상)
with closing(db.connect()) as conn:
    sb.ensure_tables(conn); conn.execute(accum.DDL); regsho.ensure_tables(conn)
    for t, dd, nh, nc in (("BRAI", d(40), 30.0, 5.0), ("BRAI", d(10), 2.0, -8.0), ("AZTR", d(20), 50.0, 20.0)):
        conn.execute("INSERT INTO case_events (ticker, date, close, drop_pct, next_high_pct, next_close_pct, fwd_5d, avg_dollar_vol, vol_mult) VALUES (?,?,1.0,-25.0,?,?,1.0,500000,2.0)", (t, dd, nh, nc))
    conn.executemany("INSERT INTO sec_hist VALUES (?,?,?,?,?)", [("a1", "BRAI", "424B5", d(12), ""), ("a2", "BRAI", "8-K", d(11), "1.01"), ("a3", "BRAI", "8-K", d(100), "3.01,5.03"),
                                                                 ("a4", "BRAI", "EFFECT", d(5), ""), ("b1", "AZTR", "10-Q", d(60), "")])
    conn.executemany("INSERT INTO sec_hist_progress VALUES (?,?,?,?)", [("BRAI", "done", 4, db.utcnow_iso()), ("AZTR", "done", 1, db.utcnow_iso())])
    A = json.dumps({"score": 8.0, "level": "강한 매집 의심", "n_absorb": 3, "n_strong": 1, "top_day": "10/16", "top_vr": 9.0, "top_chg": 12.0, "news": [], "dilution": [],
                    "absorb_days": ["10/15", "10/16"], "price": 1.0, "parts": {}, "r30": 10, "cum": 10}, ensure_ascii=False)
    conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (T.isoformat(), "BRAI", "주간", 8.0, A))
    now = db.utcnow_iso()
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "BRAI", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
    assert pagecache.effect_tickers(conn) == ["BRAI"]

# 4) warm: 네 항목 전부 · 일봉은 한 번만(EFFECT ∪ 순위 상위) · 두 번째는 건너뜀 · force 는 다시
calls.clear(); r = pagecache.warm(out=lambda *_: None); print("warm:", r)
assert set(r) == set(pagecache.ENTRIES) and all(v is not None and v >= 0 for v in r.values())
rk = pagecache.get("rank"); top = pagecache.rank_top(rk); print("rank:", list(rk["ticker"]), "top:", top)
assert "BRAI" in list(rk["ticker"]) and calls == [sorted({"BRAI", *top})]
s3 = pagecache.get("rank_s3"); assert s3["tickers"] == tuple(top) and all(set(v) == {"m", "s", "d"} for v in s3["data"].values())
fl = pagecache.get("secflags"); print(fl)
assert len(fl) == 3 and fl.loc[("BRAI", d(10)), "offering"] and fl.loc[("BRAI", d(10)), "news"] and not fl.loc[("BRAI", d(10)), "quiet"]     # 424B5(-2일)·8-K(-1일)
assert fl.loc[("BRAI", d(40)), "notice"] and fl.loc[("BRAI", d(40)), "charter"] and fl.loc[("BRAI", d(40)), "quiet"]                        # 3.01·5.03 은 60일 전, 근처 공시 없음
assert all(v is None for v in pagecache.warm(out=lambda *_: None).values()) and pagecache.warm(["rank"], force=True, out=lambda *_: None)["rank"] >= 0
st_ = {r_["항목"]: r_ for r_ in pagecache.status()}; assert set(st_) == set(pagecache.ENTRIES) and st_["rank"]["지난 시간(분)"] == 0 and st_["secflags"]["크기(KB)"] >= 0

# 5) prices / s3_data: 캐시에 있는 종목은 안 받고 없는 종목만
calls.clear(); px = pagecache.prices(("BRAI", "ZZZ")); assert set(px) == {"BRAI", "ZZZ"} and calls == [["ZZZ"]] and pagecache.prices(()) == {}
pagecache.put("rank_s3", {"tickers": ("BRAI",), "data": {"BRAI": {"m": {"strong": True, "label": "x"}, "s": {"oversold": False, "label": "y"}, "d": {"ok": None, "label": "z"}}}})
calls.clear(); assert pagecache.s3_data(("BRAI",))["BRAI"]["m"]["strong"] is True and calls == []
dd = pagecache.s3_data(("BRAI", "ZZZ")); assert set(dd) == {"BRAI", "ZZZ"} and calls == [["ZZZ"]] and set(dd["ZZZ"]) == {"m", "s", "d"}
import rank_ui
assert "①💰" in rank_ui.s3_marks(("BRAI",))["BRAI"]

# 6) secflags(cs): 캐시보다 새 사건은 그 자리에서 계산 · 캐시 없으면 전부 계산 — 직접 계산과 같다
with closing(db.connect()) as conn:
    conn.execute("INSERT INTO case_events (ticker, date, next_high_pct) VALUES ('BRAI', ?, 9.0)", (d(3),)); conn.commit()
cs = db.read_df("SELECT ticker, date, next_high_pct, next_close_pct, fwd_5d FROM case_events ORDER BY date")
direct = sb.event_flags(cs, db.read_df("SELECT ticker, form, filed, items FROM sec_hist"))
fl2 = pagecache.secflags(cs); assert fl2.index.equals(cs.index) and list(fl2.columns) == list(sb.FLAGS) and (code(fl2).values == code(direct).values).all()
assert fl2.loc[cs.index[cs["date"] == d(3)][0], "offering"]                                   # 새 사건: EFFECT(-2일)
pagecache.invalidate("secflags"); fl3 = pagecache.secflags(cs); assert (code(fl3).values == code(direct).values).all()

# 7) 화면: 🏁 순위는 캐시에서(계산 함수가 깨져도 뜸) · 📚 과거 사례 · ⚡ EFFECT(다운로드 없이) · ⚙️ 관리 모드 상태 표
pagecache.warm(force=True, out=lambda *_: None)
rk2 = pagecache.get("rank"); rk2["score"] = 55.0; pagecache.put("rank", rk2)      # 화면 기본 필터(종합 ≥ 20)에 걸리게 점수를 올려 둔 캐시
rank.compute = lambda *a, **k: (_ for _ in ()).throw(AssertionError("캐시를 안 쓰고 다시 계산함"))
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "rank"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown); assert "BRAI" in html and "종합" in html
os.environ["QUANT_TEST_PAGE"] = "cases"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown); assert "급락일 전후 공시별 결과" in html
os.environ["QUANT_TEST_PAGE"] = "effect"; calls.clear()
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown); assert "EFFECT 이후" in html and calls == [], calls
os.environ["QUANT_TEST_PAGE"] = "admin"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert any("🔥 화면 캐시" in e.label for e in at.expander) and any("지난 시간(분)" in list(f.value.columns) for f in at.dataframe)
os.environ.pop("QUANT_TEST_PAGE")

# 8) 명령줄: status
env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
p = subprocess.run([sys.executable, "-X", "utf8", "pagecache.py", "status"], cwd=os.environ["QS_ROOT"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
assert p.returncode == 0 and "secflags" in p.stdout and "rank" in p.stdout, (p.stdout[-500:], p.stderr[-800:])
print("ALL OK")
