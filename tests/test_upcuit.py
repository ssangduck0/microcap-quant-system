import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from datetime import date, datetime
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd, requests
import halts
ETZ = ZoneInfo("America/New_York")
# 공식 스펙(openapi.json)의 필드 그대로
J = {"api_version": 1, "meta": {"count": 4, "source": "nasdaq", "stale": False},
     "data": [
  {"symbol": "abcd", "name": "Example Corp", "market": "NASDAQ", "status": "resumed", "reasons": [{"code": "LUDP", "title": "Volatility Trading Pause"}],
   "pause_threshold_price": 3.45, "halted_at": "2026-05-08T09:57:26-04:00", "halted_at_epoch_ms": 1, "halted_at_local": {"date": "05/08/2026", "time": "09:57:26", "tz": "America/New_York"},
   "resumed_at": "2026-05-08T10:02:32-04:00", "resumed_at_epoch_ms": 2, "resumed_at_local": None, "quote_resumed_at": "2026-05-08T10:02:26-04:00", "quote_resumed_at_epoch_ms": 3},
  {"symbol": "NEWS", "name": "News Inc", "market": "NYSE", "status": "quote_resumed", "reasons": [{"code": "T1", "title": "Halt - News Pending"}, {"code": "LUDS", "title": "Straddle"}],
   "pause_threshold_price": None, "halted_at": None, "halted_at_epoch_ms": None, "halted_at_local": {"date": "05/08/2026", "time": "11:00:00", "tz": "America/New_York"},
   "resumed_at": None, "resumed_at_epoch_ms": None, "resumed_at_local": None, "quote_resumed_at": "2026-05-08T11:25:00-04:00", "quote_resumed_at_epoch_ms": 4},
  {"symbol": "ZZZ", "name": "Z", "market": "NASDAQ", "status": "halted", "reasons": [{"code": "T12", "title": "Additional Information Requested"}],
   "pause_threshold_price": "bad", "halted_at": "2026-05-08T14:00:00Z", "halted_at_local": None, "resumed_at": None, "resumed_at_local": None, "quote_resumed_at": None, "future_field": 1},
  {"name": "no symbol"}]}
hs = halts.parse_upcuit(J)
assert [h["symbol"] for h in hs] == ["ABCD", "NEWS", "ZZZ"]                                          # 심볼 없는 항목 제외, 대문자, 모르는 필드는 무시
a = hs[0]; assert a["code"] == "LUDP" and a["threshold"] == 3.45 and a["halt"] == datetime(2026, 5, 8, 9, 57, 26, tzinfo=ETZ) and a["resume"] == datetime(2026, 5, 8, 10, 2, 32, tzinfo=ETZ) and a["status"] == "resumed"
n = hs[1]; assert n["code"] == "LUDS" and n["halt"] == datetime(2026, 5, 8, 11, 0, tzinfo=ETZ) and n["resume"] is None and n["status"] == "quote_resumed" and n["title"] == "Straddle"   # LULD 사유 우선, 동부시간 대체
z = hs[2]; assert z["threshold"] is None and z["halt"] == datetime(2026, 5, 8, 10, 0, tzinfo=ETZ) and z["code"] == "T12"                                                         # 잘못된 기준가, UTC(Z) → 동부시간
for bad in ({}, {"data": "x"}, [], "x"):
    try: halts.parse_upcuit(bad); raise SystemExit("형식 오류가 나야 함")
    except ValueError: pass
# 요약: 업킷 데이터로도 같은 결과(방향·호가 재개 표시·사유 제목 대체)
idx = pd.date_range("2026-05-08 09:30", "2026-05-08 15:59", freq="min", tz=ETZ)
reg = pd.DataFrame({"Open": 3.0, "High": 3.0, "Low": 3.0, "Close": np.linspace(3.0, 4.0, len(idx)), "Volume": 1.0}, index=idx)
sm = halts.summarize(hs, "ABCD", date(2026, 5, 8), reg); assert sm["halt_up"] == 1 and sm["halts"][0]["resume"] == "10:02:32" and sm["halt_active"] is False
sn = halts.summarize(hs, "NEWS", date(2026, 5, 8), reg); assert sn["halts"][0]["quote_resumed"] is True and sn["halt_active"] is True and sn["halts"][0]["dir"] == "미상"
assert halts.summarize(hs, "ZZZ", date(2026, 5, 8), reg)["halts"][0]["reason"] == "추가 정보 요청"
print("parse_upcuit OK")

XML = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_halts_fintel.py")).read().split('XML = """')[1].split('"""')[0]
class R:
    def __init__(s, status=200, js=None, text="", headers=None): s.status_code, s._js, s.text, s.headers = status, js, text, headers or {}
    def json(s):
        if s._js is None: raise ValueError("not json")
        return s._js
    def raise_for_status(s):
        if s.status_code >= 400: raise requests.HTTPError(str(s.status_code))
class S:
    def __init__(s, routes): s.routes, s.calls = routes, []
    def get(s, url, headers=None, timeout=None):
        s.calls.append((url, dict(headers or {})))
        r = s.routes["upcuit" if "upcuit" in url else "nasdaq"]
        return r.pop(0) if isinstance(r, list) else r
def reset(): halts._cache.update(t=0.0, data=None); halts._etag.update(etag=None, data=None)
# 1) 업킷 성공 → 나스닥 호출 없음, 출처 기록, ETag 저장
reset(); s1 = S({"upcuit": R(200, J, headers={"ETag": "W/\"abc\""}), "nasdaq": R(200, text=XML)})
d = halts.fetch(session=s1, ttl=0); assert len(d) == 3 and halts.last_source == "upcuit" and len(s1.calls) == 1 and s1.calls[0][0] == "https://upcuit.com/api/v1/halts"
# 2) 다음 호출은 If-None-Match 를 보내고 304 면 이전 데이터 재사용
s2 = S({"upcuit": R(304), "nasdaq": R(200, text=XML)}); d2 = halts.fetch(session=s2, ttl=0)
assert s2.calls[0][1].get("If-None-Match") == "W/\"abc\"" and d2 is d and halts.last_source == "upcuit"
# 3) 업킷 503(준비 중) → 나스닥 RSS 로 자동 전환
reset(); s3 = S({"upcuit": R(503), "nasdaq": R(200, text=XML)}); d3 = halts.fetch(session=s3, ttl=0)
assert halts.last_source == "nasdaq" and [h["symbol"] for h in d3] == ["NEPH", "WLDS", "OLDH", "DONE"] and [u for u, _ in s3.calls] == ["https://upcuit.com/api/v1/halts", "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"]
# 4) 업킷 형식이 바뀌면(필드 없음) → 나스닥
reset(); s4 = S({"upcuit": R(200, {"weird": 1}), "nasdaq": R(200, text=XML)}); halts.fetch(session=s4, ttl=0); assert halts.last_source == "nasdaq"
# 5) 둘 다 실패 → 예외(스캐너는 '확인 불가'로 처리)
reset(); s5 = S({"upcuit": R(500), "nasdaq": R(503)})
try: halts.fetch(session=s5, ttl=0); raise SystemExit("예외가 나야 함")
except requests.HTTPError: pass
# 6) 나스닥만 사용 설정이면 업킷을 부르지 않음 / 캐시 안에서는 재호출 없음
reset(); s6 = S({"upcuit": R(200, J), "nasdaq": R(200, text=XML)}); halts.fetch(session=s6, source="nasdaq"); halts.fetch(session=s6, source="nasdaq")
assert [u for u, _ in s6.calls] == ["https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"] and halts.last_source == "nasdaq"
print("fetch OK")
print("ALL OK")
