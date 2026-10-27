import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, closewatch as cw, sec
db.init_db()
approx = lambda a, b, tol=1e-9: a is not None and abs(a - b) < tol
ET = "America/New_York"

# ---------- regular ----------
idx = pd.date_range("2026-10-12 04:00", "2026-10-12 19:59", freq="min", tz=ET)
df = pd.DataFrame({"Open":1.,"High":1.,"Low":1.,"Close":1.,"Volume":1.}, index=idx)
r = cw.regular(df); assert r.index[0].strftime("%H:%M") == "09:30" and r.index[-1].strftime("%H:%M") == "15:59" and len(r) == 390
assert cw.regular(None) is None and cw.regular(df.iloc[0:0]).empty
print("regular OK")

# ---------- 합성 급락일 정규장 데이터 ----------
ridx = pd.date_range("2026-10-12 09:30", "2026-10-12 15:59", freq="min", tz=ET)         # 390봉
n = len(ridx)
close = np.r_[np.linspace(9.0, 7.5, 150), np.linspace(7.5, 7.4, n - 150 - 30)]            # 150분까지 하락 후 완만한 하락
close = np.r_[close, np.linspace(7.52, 7.9, 30)]                                            # 마지막 30분만 반등(체결강도 상승)
vol = np.r_[np.full(30, 1000.), np.full(60, 10000.), np.full(n - 90, 500.)]                 # 10:00~11:00(30~90분)에 거래량 폭발 후 감소
reg = pd.DataFrame({"Open": np.r_[9.0, close[:-1]], "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": vol}, index=ridx)

# ---------- volume_stats ----------
avg20 = 1_500_000.0
vs = cw.volume_stats(reg, avg20)
assert approx(vs["vol_total"], vol.sum()) and approx(vs["peak60"], 60 * 10000 + 0.0, 1e-6)                # 피크: 폭발 60분 구간(포함 경계 때문에 정확히 60분 합)
assert approx(vs["last60"], 60 * 500.0) and approx(vs["decay"], 30000 / 600000) and approx(vs["vol_mult"], vol.sum() / avg20)
assert approx(vs["burst_mult"], 600000 / (avg20 / 6.5), 1e-9) and vs["mins_since_peak"] > 200
print("volume_stats OK", {k: (round(v, 3) if isinstance(v, (int, float)) and v is not None and not isinstance(v, bool) else v) for k, v in vs.items()})

# ---------- buy_stats ----------
bs = cw.buy_stats(reg)
assert bs["buy_late"] is not None and bs["buy_late"] > 95 and bs["buy_prior"] is not None and bs["buy_prior"] < 50        # 마지막 30분은 상승 봉(100%), 그 전 60분은 하락 봉(0%)
flat = reg.copy(); flat["Close"] = 7.5
assert cw.buy_stats(flat)["buy_late"] is None and cw.buy_stats(flat)["buy_prior"] is None           # 방향이 전혀 없으면 계산 불가(None)
assert cw.buy_stats(reg.iloc[:4])["buy_late"] is None                                               # 봉이 5개 미만이면 계산 불가
print("buy_stats OK", bs)

# ---------- volume_series ----------
vsr = cw.volume_series(reg, 10); assert vsr[0] == {"t": "09:30", "v": 10000.0} and vsr[3]["v"] == 100000.0 and len(vsr) == 39

# ---------- daily_context ----------
def candle(o, h, l, c, v): return {"openPrice": str(o), "highPrice": str(h), "lowPrice": str(l), "closePrice": str(c), "volume": str(v), "timestamp": "x"}
daily = [candle(9.0, 9.1, 7.4, 7.92, 3e6), candle(10.0, 10.5, 9.8, 10.0, 1.5e6)] + [candle(10, 10.3, 9.7, 10.0, 1e6 + 1e5 * i) for i in range(20)]
ctx = cw.daily_context(daily, reg)
assert ctx and approx(ctx["prev_close"], 10.0) and ctx["n_hist"] == 20 and approx(ctx["avg_vol20"], np.mean([1.5e6] + [1e6 + 1e5 * i for i in range(19)]))
# 맨 앞이 새 날(데이마켓) 봉이면 두 번째 봉이 오늘 봉
daily2 = [candle(5.0, 5.1, 4.9, 5.0, 1e4)] + daily
ctx2 = cw.daily_context(daily2, reg); assert ctx2 and approx(ctx2["prev_close"], 10.0)
assert cw.daily_context([candle(5, 5, 5, 5, 1)] * 3, reg) is None and cw.daily_context([], reg) is None            # 오늘 봉을 못 찾으면 판정 불가
assert cw.daily_context(daily[:1], reg) is None                                                                  # 이전 봉이 없으면 None
print("daily_context OK")

# ---------- ask_stats ----------
book = {"asks": [(1.01, 1000.), (1.02, 500.), (1.03, 300.)], "bids": [(1.00, 700.), (0.99, 200.)]}
a = cw.ask_stats(book, 600.0)
assert approx(a["ask_depth_sh"], 1800) and approx(a["ask_depth_usd"], 1.01*1000 + 1.02*500 + 1.03*300) and approx(a["top_ask_ratio"], 1000 / 400) and approx(a["ask_minutes"], 3.0)
assert approx(a["best_ask"], 1.01) and approx(a["best_bid"], 1.00) and a["n_ask"] == 3
assert cw.ask_stats({"asks": [], "bids": []}, 1) is None and cw.ask_stats(None, 1) is None
assert cw.ask_stats({"asks": [(1.0, 10.0), (1.1, 10.0)], "bids": []}, 0)["top_ask_ratio"] is None and cw.ask_stats({"asks": [(1.0, 10.0)], "bids": []}, 0)["ask_minutes"] is None   # 단계 2개 이하·거래량 0 은 계산 불가
print("ask_stats OK")

# ---------- thinning ----------
t0 = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
S = lambda vals: [(t0 + timedelta(minutes=5 * i), v) for i, v in enumerate(vals)]
assert approx(cw.thinning(S([100, 100, 100, 100, 50])), 0.5) and approx(cw.thinning(S([100, 120, 80, 100, 100, 100, 200])), 2.0)
assert cw.thinning(S([100, 100, 50])) is None                                       # 샘플 4개 미만
assert cw.thinning([(t0 + timedelta(minutes=i), 100.0) for i in range(5)]) is None  # 15분 이상 이전 샘플이 2개 미만
S2 = lambda pairs: [(t0 + timedelta(minutes=m), v) for m, v in pairs]
assert approx(cw.thinning(S2([(0, 1000), (5, 1000), (100, 100), (105, 100), (110, 100), (115, 100), (120, 50)])), 0.5)     # 90분보다 오래된 샘플은 기준에서 제외
print("thinning OK")

# ---------- 체결강도 변환/집계 ----------
assert approx(cw.buy_ratio_to_cs(55.0), 55 / 45 * 100) and approx(cw.buy_ratio_to_cs(50.0), 100.0) and cw.buy_ratio_to_cs(100.0) == 999.0 and cw.buy_ratio_to_cs(None) is None
assert approx(cw._cs(115, 65), 115 / 65 * 100) and cw._cs(10, 0) == 999.0 and cw._cs(0, 0) is None and cw._cs(0, 10) == 0.0
with closing(db.connect()) as conn:
    cw.ensure_tables(conn)
    base = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
    for i in range(100):                                     # 100분: 앞 60분은 매도 우위(60%), 마지막 30분은 매수 우위(70%)
        buy, sell = (40.0, 60.0) if i < 70 else (70.0, 30.0)
        conn.execute("INSERT INTO close_flow (minute,ticker,date,buy_sh,sell_sh,mid_sh,n_trades,ask_usd_avg,ask_usd_last,n_books) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ((base + timedelta(minutes=i)).isoformat(), "FLW", "2026-10-12", buy, sell, 0.0, 3, 1000.0 - i * 5, 900.0, 4))
    conn.commit()
    f = cw.flow_stats(conn, "2026-10-12", "FLW")
    # 마지막 분 = 99. 최근 30분 = 70..99(30분, 매수 70/매도 30), 그 전 60분 = 10..69(60분, 매수 40/매도 60)
    assert approx(f["cs_late"], 70 / 30 * 100) and approx(f["cs_prior"], 40 / 60 * 100) and f["flow_trades"] == 300 and approx(f["cs_cum"], (70 * 40 + 30 * 70) / (70 * 60 + 30 * 30) * 100)
    ser = cw.ws_ask_series(conn, "2026-10-12", "FLW"); assert len(ser) == 100 and ser[0][1] == 1000.0 and ser[-1][1] == 1000.0 - 99 * 5
    assert cw.flow_stats(conn, "2026-10-13", "FLW") is None
print("flow OK")

# ---------- scan_ext ----------
assert {"PIPE", "EXT1"} <= set(cw.scan_ext("the company entered into a securities purchase agreement for a private placement of common stock pursuant to section 4(a)(2)", "8-K"))
t_rd = cw.scan_ext("registered direct offering of shares and warrants", "8-K"); assert "REG_DIRECT" in t_rd and "OFFERING" in t_rd
assert "PIPE" not in cw.scan_ext("x " * 20000 + "private placement", "424B5")           # 424B 는 앞부분만 본다(본문 위험요인의 일반 문구 오탐 방지)
print("scan_ext OK")

# ---------- classify_financing ----------
today = date(2026, 10, 12)
F = lambda form, d, acc: {"accession": acc, "form": form, "filed": d, "items": "", "url": f"https://x/{acc}"}
tg = {"p": ["PIPE", "OFFERING", "EXT1"], "rd": ["REG_DIRECT", "OFFERING", "EXT1"], "atm": ["ATM", "EXT1"], "cb": ["CB", "EXT1"], "el": ["ELOC", "EXT1"], "x": ["EXT1"], "w": ["WARRANT", "EXT1"]}
tags_of = lambda f: tg.get(f["accession"], [])
cls = lambda fl: cw.classify_financing(fl, tags_of, today)
r1 = cls([F("8-K", "2026-10-09", "p")]); assert r1["type"] == "사모(PIPE)" and r1["sellable"] == "restricted" and "재판매 등록 전" in r1["label"]
r2 = cls([F("S-1", "2026-10-10", "x"), F("8-K", "2026-10-09", "p")]); assert r2["sellable"] == "restricted" and "등록 대기" in r2["label"]
r3 = cls([F("EFFECT", "2026-10-11", "x"), F("S-1", "2026-10-10", "x"), F("8-K", "2026-10-09", "p")]); assert r3["sellable"] == "free" and "효력" in r3["label"]
assert cls([F("EFFECT", "2026-10-08", "x"), F("8-K", "2026-10-09", "p")])["sellable"] == "restricted"          # 사모보다 앞선 EFFECT 는 무관
assert cls([F("424B5", "2026-10-09", "x")])["sellable"] == "immediate" and cls([F("8-K", "2026-10-09", "rd")])["type"] == "공모/등록직접"
assert cls([F("8-K", "2026-10-09", "atm")])["type"] == "ATM" and cls([F("8-K", "2026-10-09", "cb")])["sellable"] == "immediate"
assert cls([F("8-K", "2026-10-09", "el")])["type"] == "ELOC" and cls([F("8-K", "2026-10-09", "el")])["sellable"] == "restricted"
assert cls([F("8-K", "2026-10-09", "w")]) is None and cls([F("8-K", "2026-10-09", "x")]) is None              # 워런트만/희석 없음
assert cls([F("8-K", "2026-09-20", "p")]) is None                                                           # 기간(7일) 밖
assert cls([F("8-K", "2026-10-10", "rd"), F("8-K", "2026-10-02", "p")])["type"] == "공모/등록직접"                # 가장 최근 이벤트 기준
print("classify_financing OK")

# ---------- sec_context (가짜 SEC 클라이언트 + 캐시) ----------
class FakeSec:
    def __init__(s): s.fetched = []
    def cik_for(s, t): return None if t == "NOCIK" else 5
    def submissions(s, cik):
        rec = {"accessionNumber": [], "primaryDocument": [], "form": [], "filingDate": [], "items": []}
        for acc, form, d in [("0001-01", "424B5", "2026-10-12"), ("0001-02", "8-K", "2026-10-12"), ("0001-03", "8-K", "2026-10-09"), ("0001-04", "10-Q", "2026-10-12")]:
            rec["accessionNumber"].append(acc); rec["primaryDocument"].append("a.htm"); rec["form"].append(form); rec["filingDate"].append(d); rec["items"].append("")
        return {"filings": {"recent": rec}}
    def fetch_text(s, url):
        s.fetched.append(url); k = url.split("/")[-2]
        return {"000101": "prospectus supplement registered direct offering", "000102": "quarterly results press release", "000103": "private placement section 4(a)(2)"}[k]
cw.ensure_tables()
fs = FakeSec()
with closing(db.connect()) as conn:
    cx = cw.sec_context(fs, conn, "AAA", today)
    print(cx)
    assert [x["form"] for x in cx["intraday"]] == ["424B5", "8-K"] and cx["intraday"][0]["tags"] and not cx["intraday"][1]["tags"]    # 10-Q 는 제외, 424B5 만 희석 태그
    assert cx["financing"]["type"] == "공모/등록직접" and cx["errors"] == 0                                       # 오늘 424B5 가 가장 최근 조달
    n_first = len(fs.fetched); cw.sec_context(fs, conn, "AAA", today); assert len(fs.fetched) == n_first         # 캐시: 재조회 없음
    assert cw.sec_context(fs, conn, "NOCIK", today) == {"error": "SEC CIK 없음(ETF/ADR/신규상장 가능성)"}
print("sec_context OK")

# ---------- sec_context: 워런트 ----------
class FakeSecW(FakeSec):
    def submissions(self, cik):
        rec = {"accessionNumber": ["0009-01", "0009-02", "0009-03"], "primaryDocument": ["a.htm"] * 3, "form": ["8-K", "8-K", "10-Q"],
               "filingDate": ["2026-10-12", "2026-10-08", "2026-10-12"], "items": ["", "", ""]}
        return {"filings": {"recent": rec}}
    def fetch_text(self, url):
        k = url.split("/")[-2]; return {"000901": "an offering of common stock and warrants to purchase common stock", "000902": "pre-funded warrants issued"}[k]
with closing(db.connect()) as conn:
    cxw = cw.sec_context(FakeSecW(), conn, "WWW", today)
    assert [(w["form"], w["date"]) for w in cxw["warrants"]] == [("8-K", "2026-10-12"), ("8-K", "2026-10-08")]            # 10-Q 는 대상 아님
    assert cw.sec_context(FakeSec(), conn, "AAA", today)["warrants"] == []
print("warrants OK")

# ---------- evaluate ----------
good = {"drop_pct": -35.0, "vol_mult": 5.0, "decay": 0.2, "cs_late": 140.0, "cs_prior": 100.0, "cs_source": "토스 웹소켓(체결가↔호가)", "thin_ratio": 0.4, "ask_minutes": 2.0, "top_ask_ratio": 1.5,
        "dilution_status": "CLEAN", "intraday_filings": [], "financing": {"sellable": "restricted", "date": "2026-10-09", "type": "사모(PIPE)", "label": "출회 제한(재판매 등록 전)"},
        "shares_out": 8e6, "n_samples": 8}
e = cw.evaluate(good); by = {i["key"]: i["status"] for i in e["items"]}
assert e["grade"] == "BEST" and e["n_pattern"] == 6 and all(by[k] == "pass" for k in cw.PATTERN_KEYS + ["no_atm_cb", "no_intraday", "fin_restricted", "supply"]) and by["short"] == "unknown"
# 기준값 조정
assert cw.evaluate(good, {"drop": -40})["grade"] == "낙폭 미달" and cw.evaluate({**good, "drop_pct": -35.0}, {"drop": -30})["grade"] == "BEST"
# 희석 위험(ATM/CB, 장중 희석)이면 패턴이 좋아도 등급이 내려감
assert cw.evaluate({**good, "dilution_status": "ATM"})["grade"] == "희석 위험" and cw.evaluate({**good, "dilution_status": "CB"})["grade"] == "희석 위험"
assert cw.evaluate({**good, "intraday_filings": [{"form": "424B5", "tags": ["OFFERING"]}]})["grade"] == "희석 위험"
# 패턴 5/6 + 보너스(공급 제한) -> BEST, 보너스 없으면 후보, 4/6 후보, 2~3 관찰, 그 이하 미달
g2 = {**good, "financing": None}; assert cw.evaluate(g2)["grade"] == "BEST"                       # 공급 제한(발행주식수 ≤ 20M)이 보너스 역할
assert cw.evaluate({**g2, "shares_out": 50e6})["grade"] == "후보"
assert cw.evaluate({**good, "decay": 0.9})["grade"] == "BEST" and cw.evaluate({**good, "decay": 0.9, "cs_late": 80.0})["grade"] == "후보"       # 5/6 BEST, 4/6 후보
assert cw.evaluate({**good, "decay": 0.9, "cs_late": 80.0, "thin_ratio": 0.9})["grade"] == "관찰"
assert cw.evaluate({"drop_pct": -35.0})["grade"] == "미달"                                                     # 낙폭만 충족하고 나머지는 확인 불가
# 확인 불가는 '충족'으로 세지 않음 / 출회 가능 자금조달은 보너스 실패
bad_fin = cw.evaluate({**good, "financing": {"sellable": "immediate", "date": "2026-10-09", "type": "공모/등록직접", "label": "즉시 출회 가능"}, "shares_out": 50e6})
assert {i["key"]: i["status"] for i in bad_fin["items"]}["fin_restricted"] == "fail" and bad_fin["grade"] == "후보"
nodata = cw.evaluate({"drop_pct": -30.0, "intraday_filings": None, "dilution_status": "UNKNOWN"}); sn = {i["key"]: i["status"] for i in nodata["items"]}
assert sn["no_intraday"] == "unknown" and sn["no_atm_cb"] == "unknown" and sn["buy"] == "unknown" and sn["ask_thin"] == "unknown"
assert all("name" in i and "value" in i for i in e["items"]) and cw.GRADE_ORDER["BEST"] < cw.GRADE_ORDER["후보"] < cw.GRADE_ORDER["낙폭 미달"]
# 새 항목: 워런트/하킷/공매도
W = lambda m, **kw: {i["key"]: i for i in cw.evaluate({**good, **m}, kw)["items"]}
assert W({"warrant_filings": []})["no_warrant"]["status"] == "pass" and W({"warrant_filings": [{"form": "8-K", "date": "2026-10-09", "url": "u"}]})["no_warrant"]["status"] == "fail"
assert W({})["no_warrant"]["status"] == "unknown"
assert cw.evaluate({**good, "warrant_filings": [{"form": "8-K", "date": "2026-10-09", "url": "u"}]})["grade"] == "BEST"           # 최근 워런트 공시는 표시만(오늘 공시면 장중 희석으로 이미 희석 위험)
assert W({"halts": None})["halt"]["status"] == "unknown" and W({"halts": []})["halt"]["status"] == "na"
hv = W({"halts": [{"time": "10-12 10:15:30", "code": "LUDP", "reason": "변동성 정지(LULD)", "dir": "하한"}], "halt_down": 1, "halt_up": 0, "halt_other": 0, "halt_active": False})["halt"]
assert hv["status"] == "pass" and "하한(하킷) 1회" in hv["value"] and "10:15:30 하한" in hv["value"]
hu = W({"halts": [{"time": "10-12 10:15:30", "code": "LUDP", "reason": "x", "dir": "상한"}], "halt_down": 0, "halt_up": 1, "halt_other": 0, "halt_active": True})["halt"]
assert hu["status"] == "na" and "상한(상킷) 1회" in hu["value"] and "현재 정지 중" in hu["value"]
assert W({"short": None, "short_note": "Fintel 미연동"})["short"]["status"] == "unknown" and "Fintel 미연동" in W({"short": None, "short_note": "Fintel 미연동"})["short"]["value"]
shv = W({"short": {"sv_date": "2026-10-09", "sv_short": 800000.0, "sv_total": 1000000.0, "sv_ratio": 80.0, "sv_avg5_ratio": 60.0, "borrow_fee": 45.5, "borrow_avail": 1200.0, "si_shares": 5e6, "si_pct_float": 12.3, "errors": []}})["short"]
assert shv["status"] == "pass" and "80%" in shv["value"] and "대차 수수료 45.5%" in shv["value"] and "12.3% float" in shv["value"]
assert W({"short": {"sv_date": "2026-10-09", "sv_short": 300000.0, "sv_total": 1000000.0, "sv_ratio": 30.0, "sv_avg5_ratio": 35.0, "errors": []}})["short"]["status"] == "fail"
assert W({"short": {"sv_date": "x", "sv_short": 3.0, "sv_total": 10.0, "sv_ratio": 30.0, "sv_avg5_ratio": 35.0, "errors": []}}, short_ratio=25.0)["short"]["status"] == "pass"   # 기준값 조정
assert cw.evaluate({**good, "short": {"sv_ratio": 99.0, "sv_short": 1.0, "sv_avg5_ratio": 99.0, "errors": []}})["grade"] == "BEST" and "short" not in cw.PATTERN_KEYS   # 공매도는 등급에 불포함(참고)
# 체결강도 항목: 기준값(110%, +10%p)
assert W({"cs_late": 105.0, "cs_prior": 90.0})["buy"]["status"] == "fail" and W({"cs_late": 120.0, "cs_prior": 115.0})["buy"]["status"] == "fail"
assert W({"cs_late": 120.0, "cs_prior": 100.0})["buy"]["status"] == "pass" and W({"cs_late": 120.0, "cs_prior": None})["buy"]["status"] == "pass" and W({"cs_late": None})["buy"]["status"] == "unknown"
assert "토스 웹소켓" in W({})["buy"]["value"] and W({}, cs_late=150.0, cs_delta=50.0)["buy"]["status"] == "fail"
# 장중 희석을 확인하지 못한 종목(SEC 실패)은 패턴이 완벽해도 BEST 불가 -> 후보
unk = cw.evaluate({**good, "intraday_filings": None}); assert unk["grade"] == "후보" and {i["key"]: i["status"] for i in unk["items"]}["no_intraday"] == "unknown"
assert cw.evaluate({**good, "intraday_filings": None, "decay": 0.9, "cs_late": 80.0})["grade"] == "후보"      # 4/6 도 후보
print("evaluate OK")

# ---------- pick_shortlist ----------
passing = [("A", {"day_change_pct": -12.0}), ("B", {"day_change_pct": -45.0}), ("C", {"day_change_pct": -5.0}), ("D", {"day_change_pct": None}), ("E", {"day_change_pct": -30.0})]
assert cw.pick_shortlist(passing, -10.0, 2) == ["B", "E"] and cw.pick_shortlist(passing, -10.0, 10) == ["B", "E", "A"] and cw.pick_shortlist(passing, -50.0, 5) == []
print("ALL OK")
