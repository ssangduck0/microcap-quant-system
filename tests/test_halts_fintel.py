import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json, time
from datetime import date, datetime
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import pandas as pd, numpy as np, requests
import db, halts, fintel
db.init_db()
ETZ = ZoneInfo("America/New_York")
approx = lambda a, b, tol=1e-9: a is not None and abs(a - b) < tol

# ================= 나스닥 거래정지 피드 =================
XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/"><channel><title>NASDAQTrader.com</title><ndaq:numItems>5</ndaq:numItems>
<item><title>NEPH</title><pubDate>Fri, 08 May 2026 09:57:26 EDT</pubDate><ndaq:HaltDate>05/08/2026</ndaq:HaltDate><ndaq:HaltTime>09:57:26.163</ndaq:HaltTime><ndaq:IssueSymbol>NEPH</ndaq:IssueSymbol>
<ndaq:IssueName>Nephros Inc.</ndaq:IssueName><ndaq:Market>NASDAQ</ndaq:Market><ndaq:ReasonCode>LUDP</ndaq:ReasonCode><ndaq:PauseThresholdPrice>3.45</ndaq:PauseThresholdPrice>
<ndaq:ResumptionDate>05/08/2026</ndaq:ResumptionDate><ndaq:ResumptionQuoteTime>10:02:26</ndaq:ResumptionQuoteTime><ndaq:ResumptionTradeTime>10:02:32</ndaq:ResumptionTradeTime></item>
<item><title>wlds</title><ndaq:HaltDate>05/08/2026</ndaq:HaltDate><ndaq:HaltTime>10:30:00</ndaq:HaltTime><ndaq:IssueSymbol>WLDS</ndaq:IssueSymbol><ndaq:Market>NASDAQ</ndaq:Market><ndaq:ReasonCode>LUDS</ndaq:ReasonCode>
<ndaq:PauseThresholdPrice></ndaq:PauseThresholdPrice><ndaq:ResumptionDate></ndaq:ResumptionDate><ndaq:ResumptionTradeTime></ndaq:ResumptionTradeTime></item>
<item><title>OLDH</title><ndaq:HaltDate>05/07/2026</ndaq:HaltDate><ndaq:HaltTime>19:50:00</ndaq:HaltTime><ndaq:ReasonCode>T1</ndaq:ReasonCode><ndaq:ResumptionDate></ndaq:ResumptionDate></item>
<item><title>DONE</title><ndaq:HaltDate>05/07/2026</ndaq:HaltDate><ndaq:HaltTime>11:00:00</ndaq:HaltTime><ndaq:IssueSymbol>DONE</ndaq:IssueSymbol><ndaq:ReasonCode>T12</ndaq:ReasonCode><ndaq:ResumptionDate>05/07/2026</ndaq:ResumptionDate><ndaq:ResumptionQuoteTime>12:00:00</ndaq:ResumptionQuoteTime></item>
<item><title></title><ndaq:HaltDate>05/08/2026</ndaq:HaltDate></item>
</channel></rss>"""
hs = halts.parse_feed(XML)
assert [h["symbol"] for h in hs] == ["NEPH", "WLDS", "OLDH", "DONE"]                                                  # 심볼 없는 항목은 제외, title 만 있어도 사용(대문자)
n = hs[0]; assert n["code"] == "LUDP" and n["threshold"] == 3.45 and n["market"] == "NASDAQ" and n["halt"] == datetime(2026, 5, 8, 9, 57, 26, 163000, tzinfo=ETZ)
assert n["resume"] == datetime(2026, 5, 8, 10, 2, 32, tzinfo=ETZ)                                                      # 재개는 체결 시각 우선
assert hs[1]["threshold"] is None and hs[1]["resume"] is None and hs[1]["code"] == "LUDS" and hs[3]["resume"] == datetime(2026, 5, 7, 12, 0, tzinfo=ETZ)   # 호가 재개 시각 대체
try: halts.parse_feed("<rss><broken"); raise SystemExit("파싱 오류가 나야 함")
except Exception as e: assert "ParseError" in type(e).__name__ or "Error" in type(e).__name__

# 방향 추정
d = halts.direction
assert d({"code": "LUDP", "threshold": 3.45}, 3.20) == "상한" and d({"code": "LUDP", "threshold": 3.45}, 3.80) == "하한" and d({"code": "LUDS", "threshold": 3.0}, 3.5) == "하한"
assert d({"code": "LUDP", "threshold": None}, 3.2) == "미상" and d({"code": "LUDP", "threshold": 3.0}, None) == "미상" and d({"code": "LUDP", "threshold": 3.0}, 3.0) == "미상"
assert d({"code": "T1", "threshold": 3.0}, 3.2) is None
# 종목별 요약: 정지 직전 1분봉 종가와 밴드 가격 비교
idx = pd.date_range("2026-05-08 09:30", "2026-05-08 15:59", freq="min", tz=ETZ)
reg = pd.DataFrame({"Open": 3.0, "High": 3.0, "Low": 3.0, "Close": np.linspace(3.0, 4.0, len(idx)), "Volume": 1.0}, index=idx)
sm = halts.summarize(hs, "NEPH", date(2026, 5, 8), reg)
h0 = sm["halts"][0]
assert len(sm["halts"]) == 1 and approx(h0["price_before"], float(reg["Close"].iloc[26])) and h0["dir"] == "상한" and sm["halt_up"] == 1 and sm["halt_down"] == 0   # 09:56 종가 3.07 < 밴드 3.45 → 상한
assert sm["halt_active"] is False and h0["resume"] == "10:02:32" and h0["time"] == "05-08 09:57:26" and h0["carry"] is False and h0["reason"] == "변동성 정지(LULD)"
sm2 = halts.summarize(hs, "WLDS", date(2026, 5, 8), reg)                                                           # 재개 없음 + 밴드 없음 = 방향 미상, 현재 정지 중
assert sm2["halt_active"] is True and sm2["halts"][0]["dir"] == "미상" and sm2["halt_other"] == 1
sm3 = halts.summarize(hs, "OLDH", date(2026, 5, 8), reg)                                                           # 전날 걸려 아직 재개 안 된 정지는 이월(carry)로 포함
assert len(sm3["halts"]) == 1 and sm3["halts"][0]["carry"] is True and sm3["halt_active"] is True and sm3["halts"][0]["reason"] == "뉴스 대기"
assert halts.summarize(hs, "DONE", date(2026, 5, 8), reg)["halts"] == [] and halts.summarize(hs, "NONE", date(2026, 5, 8), None)["halts"] == []   # 전날 이미 재개된 정지/없는 종목은 제외
sm4 = halts.summarize(hs, "NEPH", date(2026, 5, 8), None); assert sm4["halts"][0]["price_before"] is None and sm4["halts"][0]["dir"] == "미상"        # 1분봉이 없으면 방향 미상

# fetch: 캐시, HTTP 오류는 예외
class Resp:
    def __init__(s, text="", status=200): s.text, s.status_code = text, status
    def raise_for_status(s):
        if s.status_code >= 400: raise requests.HTTPError(f"{s.status_code}")
class Sess:
    def __init__(s, resp): s.resp, s.calls = resp, []
    def get(s, url, headers=None, timeout=None): s.calls.append((url, headers, timeout)); return s.resp
halts._cache.update(t=0.0, data=None)
ss = Sess(Resp(XML)); r1 = halts.fetch(session=ss, source="nasdaq"); r2 = halts.fetch(session=ss, source="nasdaq")
assert len(r1) == 4 and r1 is r2 and len(ss.calls) == 1 and ss.calls[0][0] == "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts" and "User-Agent" in ss.calls[0][1]   # 30초 캐시
halts._cache.update(t=0.0, data=None)
try: halts.fetch(session=Sess(Resp("", 403)), source="nasdaq"); raise SystemExit("HTTP 오류가 나야 함")
except requests.HTTPError: pass
halts._cache.update(t=0.0, data=None)
print("halts OK")

# ================= Fintel =================
sv = fintel.parse_short_volume
a = sv([{"date": "2026-10-08", "shortVolume": 400, "totalVolume": 1000}, {"date": "2026-10-09", "shortVolume": "800", "totalVolume": "1,000"}])
assert approx(a["sv_ratio"], 80.0) and a["sv_date"] == "2026-10-09" and approx(a["sv_avg5_ratio"], 1200 / 2000 * 100) and a["sv_short"] == 800.0
b = sv({"data": [{"Date": "2026-10-09T00:00:00", "short_volume": 300, "total_volume": 1000, "short_exempt_volume": 5}]}); assert approx(b["sv_ratio"], 30.0) and b["sv_date"] == "2026-10-09"   # 래퍼·스네이크 케이스·날짜 시각 허용
c = sv([{"date": "2026-10-09", "shortVolume": 5, "totalVolume": 0}, {"date": "2026-10-08", "short": 600, "volume": 1000}]); assert approx(c["sv_ratio"], 60.0) and c["sv_date"] == "2026-10-08"            # 거래량 0 은 제외, 이름 변형
assert sv([]) is None and sv({"foo": 1}) is None and sv("x") is None and sv([{"date": "d"}]) is None
rows = [{"date": f"2026-10-{d:02d}", "shortVolume": 100 * d, "totalVolume": 1000} for d in (9, 1, 5, 2, 8, 6, 7)]                      # 정렬되지 않은 입력: 날짜순으로 정렬 후 최근 5일 평균
r = sv(rows); assert r["sv_date"] == "2026-10-09" and approx(r["sv_avg5_ratio"], (500 + 600 + 700 + 800 + 900) / 5000 * 100)
bw = fintel.parse_borrow
assert bw({"fee": 45.5, "available": 1200, "date": "2026-10-09T15:00:00"}) == {"borrow_fee": 45.5, "borrow_avail": 1200.0, "borrow_date": "2026-10-09T15:00:00"}
assert bw([{"date": "2026-10-08", "feeRate": 10}, {"date": "2026-10-09", "feeRate": "55.5%", "sharesAvailable": 0}])["borrow_fee"] == 55.5 and bw({"x": 1}) is None and bw([]) is None
si = fintel.parse_short_interest
assert si([{"date": "2026-09-30", "shortInterest": 1000000, "daysToCover": 2.5, "percentFloat": 12.5}, {"date": "2026-09-15", "shortInterest": 5}]) == {"si_date": "2026-09-30", "si_shares": 1000000.0, "si_pct_float": 12.5, "si_dtc": 2.5}
assert si({"short_interest": 7, "days_to_cover": 1.2})["si_shares"] == 7.0 and si([]) is None

class R:
    def __init__(s, status=200, js=None): s.status_code, s._js = status, js
    def json(s): return s._js
    def raise_for_status(s):
        if s.status_code >= 400: raise requests.HTTPError(str(s.status_code))
class FSess:
    def __init__(s, routes): s.routes, s.calls = routes, []
    def get(s, url, headers=None, timeout=None):
        s.calls.append((url, headers)); kind = url.rsplit("/", 1)[-1]; r = s.routes[kind]; return r(url) if callable(r) else r
cl = lambda routes: fintel.FintelClient("KEY123", session=FSess(routes))
c1 = cl({"short-volume": R(200, [{"date": "2026-10-09", "shortVolume": 800, "totalVolume": 1000}]), "borrow-rate": R(200, {"fee": 40.0, "available": 900}),
         "short-interest": R(200, [{"date": "2026-09-30", "shortInterest": 2000000, "percentFloat": 20.0}])})
s = c1.summary("aaa"); print(s)
assert s["sv_ratio"] == 80.0 and s["borrow_fee"] == 40.0 and s["si_shares"] == 2e6 and s["errors"] == []
assert c1.session.calls[0][0] == "https://api.fintel.io/v1/securities/us/AAA/short-volume" and c1.session.calls[0][1]["X-API-KEY"] == "KEY123" and len(c1.session.calls) == 3
c1.summary("AAA"); assert len(c1.session.calls) == 3                                                               # 캐시(TTL) 안에서는 재호출 없음
# 캐시 만료(대차 수수료는 20분): 해당 항목만 다시 호출
import sqlite3; from contextlib import closing
with closing(db.connect()) as conn: conn.execute("UPDATE fintel_cache SET fetched_at = fetched_at - 3600 WHERE kind='borrow-rate'"); conn.commit()
c1.summary("AAA"); assert [u.rsplit("/", 1)[-1] for u, _ in c1.session.calls[3:]] == ["borrow-rate"]
# 오류 처리: 플랜 제한은 해당 항목만 실패, 키 오류는 중단, 404/429/응답 형식 불명
c2 = cl({"short-volume": R(200, [{"date": "2026-10-09", "shortVolume": 1, "totalVolume": 2}]), "borrow-rate": R(403), "short-interest": R(404)})
s2 = c2.summary("BBB"); assert s2["sv_ratio"] == 50.0 and "플랜" in s2["errors"][0] and "404" in s2["errors"][1] and len(c2.session.calls) == 3
c3 = cl({"short-volume": R(401), "borrow-rate": R(200, {}), "short-interest": R(200, {})}); s3 = c3.summary("CCC")
assert "API 키" in s3["errors"][0] and len(c3.session.calls) == 1 and "sv_ratio" not in s3                           # 키가 잘못됐으면 나머지는 호출하지 않음
c4 = cl({"short-volume": R(429), "borrow-rate": R(200, {"weird": 1}), "short-interest": R(500)}); s4 = c4.summary("DDD")
assert "한도" in s4["errors"][0] and "필드 이름 확인" in s4["errors"][1] and "HTTPError" in s4["errors"][2]
print("fintel OK")
print("ALL OK")
