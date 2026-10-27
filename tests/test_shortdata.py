import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, shortdata as sd
db.init_db()
ET = ZoneInfo("America/New_York")
approx = lambda a, b, tol=1e-9: a is not None and abs(a - b) < tol
# ---------- 파싱 ----------
F = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20261009|AAA|800|5|1000|B,Q,N\n20261009|bbb|30|0|100|Q\n20261009|ZERO|0|0|0|Q\nbadline\n20261009|NOV||0||Q\n4\n"
r = sd.parse_finra(F); assert r["AAA"] == (800.0, 5.0, 1000.0) and r["BBB"] == (30.0, 0.0, 100.0) and "NOV" not in r and len(r) == 3
I = ("#BOF|2026.10.14|10:30:01\n#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|\n"
     "AAA|USD|A CORP|1|US1|-45.2|48.5|1200|BBG1|\nBIG|USD|BIG CO|2|US2|4.5|0.25|>10000000|BBG2|\nNAF|USD|NA|3|US3|NA|NA|NA||\n#EOF|3\n")
d, as_of = sd.parse_ibkr(I)
assert d["AAA"] == {"fee": 48.5, "rebate": -45.2, "available": 1200.0, "capped": False, "cur": "USD"} and d["BIG"]["available"] == 10000000.0 and d["BIG"]["capped"] is True
assert d["NAF"]["fee"] is None and d["NAF"]["available"] is None and as_of == "2026.10.14 10:30:01"
try: sd.parse_ibkr("garbage\nlines"); raise SystemExit("머리글 없으면 오류")
except ValueError: pass
# 후보 날짜: 주말 제외, 18:30 ET 전에는 오늘 제외
c = sd.finra_candidates(datetime(2026, 10, 12, 17, 0, tzinfo=ET), 5)          # 월요일 17시 → 오늘 제외, 금(10-09)부터
assert [x.isoformat() for x in c] == ["2026-10-09", "2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05"]
assert sd.finra_candidates(datetime(2026, 10, 12, 19, 0, tzinfo=ET), 2)[0].isoformat() == "2026-10-12"
print("parse OK")
# ---------- 수집·캐시 ----------
clock = {"t": datetime(2026, 10, 12, 23, 30, tzinfo=timezone.utc)}             # ET 19:30 월요일
calls = {"http": [], "ftp": 0}
def http_get(url):
    calls["http"].append(url); d8 = url.rsplit("vol", 1)[1][:8]
    if d8 == "20261009": return 404, ""                                         # 금요일 휴장이라고 가정
    v = {"20261012": 900, "20261008": 400, "20261007": 300, "20261006": 200, "20261005": 100, "20261002": 50}.get(d8)
    return (200, f"Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n{d8}|AAA|{v}|0|1000|Q\n1\n") if v else (404, "")
ftp_text = {"v": I}
def ftp_get():
    calls["ftp"] += 1
    if ftp_text["v"] is None: raise OSError("blocked")
    return ftp_text["v"]
sc = sd.ShortClient(None, http_get=http_get, ftp_get=ftp_get, now=lambda: clock["t"])
s = sc.summary("aaa"); print(s)
assert s["sv_date"] == "2026-10-12" and approx(s["sv_ratio"], 90.0) and approx(s["sv_avg5_ratio"], (900 + 400 + 300 + 200 + 100) / 5000 * 100)   # 휴장일 건너뛰고 5거래일
assert s["borrow_fee"] == 48.5 and s["borrow_avail"] == 1200.0 and s["borrow_avail_open"] == 1200.0 and approx(s["borrow_avail_chg_pct"], 0.0) and s["errors"] == []
assert s["short_src"] == "FINRA(공매도 거래량)·IBKR(대차)" and sc.label == "FINRA·IBKR"
n_http = len(calls["http"]); assert calls["ftp"] == 1
sc.summary("BBB"); assert len(calls["http"]) == n_http and calls["ftp"] == 1                                   # 다른 종목도 같은 파일 재사용(추가 요청 없음)
# 16분 뒤: IBKR 재수신 → 대차 가능 수량이 줄면 변화율·최저값 기록, 휴장 처리된 날은 1시간 지나야 재시도
clock["t"] += timedelta(minutes=16)
ftp_text["v"] = I.replace("|1200|", "|300|").replace("|48.5|", "|90.0|")
s2 = sc.summary("AAA"); assert calls["ftp"] == 2 and s2["borrow_avail"] == 300.0 and approx(s2["borrow_avail_chg_pct"], -75.0) and s2["borrow_fee_max_today"] == 90.0
assert len(calls["http"]) == n_http                                                                            # 아직 1시간 안 지남
clock["t"] += timedelta(minutes=50)
sc.summary("AAA"); assert len(calls["http"]) == n_http + 1 and "20261009" in calls["http"][-1]                     # 미게시 날짜만 1시간 뒤 재시도
with closing(db.connect()) as conn:
    row = conn.execute("SELECT open_avail, min_avail, max_fee FROM ibkr_borrow_day WHERE symbol='AAA'").fetchone()
    assert (row["open_avail"], row["min_avail"], row["max_fee"]) == (1200.0, 300.0, 90.0)
# FTP 가 막히면 오류 문구만 남기고 직전 값 유지, 5분 뒤 재시도
clock["t"] += timedelta(minutes=16); ftp_text["v"] = None
s3 = sc.summary("AAA"); assert s3["borrow_avail"] == 300.0 and any("IBKR" in e and "방화벽" in e for e in s3["errors"])
nf = calls["ftp"]; clock["t"] += timedelta(minutes=2); sc.summary("AAA"); assert calls["ftp"] == nf          # 5분 안에는 재시도 안 함
clock["t"] += timedelta(minutes=4); ftp_text["v"] = I; s4 = sc.summary("AAA"); assert calls["ftp"] == nf + 1 and not any("IBKR" in e for e in s4["errors"])
print("fetch/cache OK")
# ---------- Fintel 보조: 무료 값이 우선, 빈 항목(공매도 잔고)만 채움 ----------
class FakeFintel:
    def __init__(s): s.n = 0
    def summary(s, t): s.n += 1; return {"sv_ratio": 1.0, "si_shares": 5e6, "si_pct_float": 25.0, "errors": ["borrow-rate: 현재 Fintel 플랜에서 제공되지 않음(403)"]}
ff = FakeFintel(); sc2 = sd.ShortClient(ff, http_get=http_get, ftp_get=ftp_get, now=lambda: clock["t"])
m = sc2.summary("AAA"); assert m["sv_ratio"] == 90.0 and m["si_shares"] == 5e6 and m["short_src"].endswith("+ Fintel") and m["errors"] == ["Fintel: borrow-rate: 현재 Fintel 플랜에서 제공되지 않음(403)"]
m2 = sc2.summary("AAA", include_fintel=False); assert "si_shares" not in m2 and ff.n == 1 and sc2.label == "FINRA·IBKR + Fintel"
print("fintel merge OK")
print("ALL OK")
# ---------- 공통 인텔과 연결: Fintel 한도(0)여도 무료 값은 모든 종목에 매 사이클 ----------
import intel
class FS:
    def cik_for(s, t): return None
intel._SEC_AT.clear(); intel._FIN_AT.clear()
sc3 = sd.ShortClient(FakeFintel(), http_get=http_get, ftp_get=ftp_get, now=lambda: clock["t"])
with closing(db.connect()) as conn:
    out = intel.compute(conn, FS(), ["AAA", "BIG"], frames={}, halts_list=None, fintel_client=sc3, sec_budget=0, fintel_budget=1, now=clock["t"])
assert out["AAA"]["short"]["sv_ratio"] == 90.0 and out["AAA"]["short"].get("si_shares") == 5e6          # 1번째 종목은 Fintel 포함(한도 1)
assert out["BIG"]["short"]["borrow_fee"] == 0.25 and out["BIG"]["short"].get("sv_ratio") is None and "si_shares" not in out["BIG"]["short"]   # 2번째는 한도 초과 → 무료 값(IBKR)만
sc_cells = intel.summary_cells(out["AAA"]); assert sc_cells["대차가능 변화(%)"] is not None and sc_cells["공매도(전일%)"] == 90.0
with closing(db.connect()) as conn:                                                                          # 다음 사이클: Fintel 주기 전이라 안 부르지만 잔고는 유지
    out2 = intel.compute(conn, FS(), ["AAA"], frames={}, halts_list=None, fintel_client=sc3, sec_budget=0, fintel_budget=5, now=clock["t"] + timedelta(minutes=5))
assert out2["AAA"]["short"]["si_shares"] == 5e6 and sc3.fintel.n == 1
print("intel link OK")
# ---------- 최신 IBKR 파일에서 빠진 종목: 옛 값을 지금 값처럼 쓰지 않음 ----------
sc5 = sd.ShortClient(None, http_get=http_get, ftp_get=ftp_get, now=lambda: clock["t"])
ftp_text["v"] = I                                                                   # AAA 포함
clock["t"] += timedelta(minutes=20); a1 = sc5.summary("AAA"); assert not a1.get("borrow_stale")
ftp_text["v"] = I.replace("#BOF|2026.10.14|10:30:01", "#BOF|2026.10.14|14:00:00").replace("AAA|USD|A CORP|1|US1|-45.2|48.5|1200|BBG1|\n", "")   # 새 파일에서 AAA 빠짐
clock["t"] += timedelta(minutes=20); a2 = sc5.summary("AAA"); print(a2.get("borrow_note"))
assert a2["borrow_stale"] is True and "14:00:00" in a2["borrow_note"] and "borrow_avail_chg_pct" not in a2
assert intel.summary_cells({"short": a2})["대차가능 변화(%)"] is None
b2 = sc5.summary("BIG"); assert not b2.get("borrow_stale") and b2["borrow_date"] == "2026.10.14 14:00:00"   # 최신 파일에 있는 종목은 정상
print("stale OK")
