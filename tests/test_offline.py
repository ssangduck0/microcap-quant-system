"""🔌 테스트 오프라인 모드(config.OFFLINE, 2026-10-28): 임시 DB 를 쓰면 자동으로 — Claude·텔레그램 키 비움 · requests 전부 즉시 차단 · 야후 건너뜀 · 가짜 post 는 그대로 됨."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, time
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_OFFLINE", None)                                   # run_all.sh 가 켜 주지 않아도 임시 DB 만으로 켜져야 함
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-must-be-blanked"; os.environ["TELEGRAM_TOKEN"] = "123:abc"
sys.path.insert(0, os.environ["QS_ROOT"])
import config, db
db.init_db()
assert config.OFFLINE is True and os.environ["ANTHROPIC_API_KEY"] == "" and os.environ["TELEGRAM_TOKEN"] == "", config.OFFLINE
assert config._under_tmp(os.environ["QUANT_DB"]) and not config._under_tmp("/home/quant/data/quant.db") and not config._under_tmp("")
import requests
t0 = time.time()
for fn in (lambda: requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS", timeout=5),
           lambda: requests.Session().post("https://api.anthropic.com/v1/messages", json={}, timeout=5),
           lambda: requests.post("https://api.telegram.org/bot123/sendMessage", timeout=5)):
    try:
        fn(); raise AssertionError("차단 안 됨")
    except requests.exceptions.ConnectionError as e:
        assert "오프라인" in str(e), e
assert time.time() - t0 < 2, time.time() - t0                            # 타임아웃 기다리지 않고 바로 실패
import aipick
try:
    aipick.call_claude("안녕", "claude-haiku-5-5"); raise AssertionError("키 없이 호출됨")
except RuntimeError as e:
    assert "ANTHROPIC_API_KEY" in str(e), e
class R:   # 가짜 post 를 넘기는 기존 테스트 방식은 그대로 됨
    status_code = 200
    def json(self): return {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 10, "output_tokens": 5}}
text, tin, tout = aipick.call_claude("안녕", "claude-haiku-5-5", post=lambda *a, **k: R(), thinking={"type": "disabled"}, kind="translate")
assert text == "ok" and (tin, tout) == (10, 5)
import market
assert market.download_daily(["AAA", "BBB"]) == {} and market.download_intraday(["AAA"]) == {} and market.fetch_splits("AAA") == [] and market.fetch_fundamentals("AAA") is None
import sec
cl = sec.SecClient("T t@e.com")
try:
    r = cl.companyfacts(320193); assert not r, r
except requests.exceptions.ConnectionError:
    pass
import regime, regsho, macro, translate, news   # 주기 작업들이 오프라인에서 예외 없이 '못 받음' 으로 끝나는지
with __import__("contextlib").closing(db.connect()) as conn:
    conn.execute(news.DDL); translate.ensure(conn)                          # 스캐너에선 뉴스 받기가 먼저 표를 만들어 줌
t0 = time.time()
with __import__("contextlib").closing(db.connect()) as conn:
    regsho.ensure_tables(conn); n = regsho.refresh(conn); assert n == 0
r = regime.refresh(force=True); assert isinstance(r, dict)
m = macro.refresh(force=True); assert isinstance(m, dict)
assert translate.run(out=lambda *_: None) == 0
assert time.time() - t0 < 10, time.time() - t0                           # 예전엔 이 네 개가 120초
print("ALL OK")
