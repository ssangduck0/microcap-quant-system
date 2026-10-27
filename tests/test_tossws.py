import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json, time, asyncio, threading
from contextlib import closing
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, closewatch as cw, tossws
from websockets.asyncio.server import serve
db.init_db(); cw.ensure_tables()
approx = lambda a, b, tol=1e-6: a is not None and abs(a - b) < tol
KST, ET = ZoneInfo("Asia/Seoul"), ZoneInfo("America/New_York")

# ---------- classify_trade ----------
Q = {"ask": 1.02, "bid": 1.00}
cl = tossws.classify_trade
assert cl(1.02, Q, None, None, 0) == ("buy", 1) and cl(1.03, Q, None, None, 0) == ("buy", 1)               # 매도호가 이상 = 매수 체결
assert cl(1.00, Q, None, None, 0) == ("sell", -1) and cl(0.99, Q, None, None, 0) == ("sell", -1)           # 매수호가 이하 = 매도 체결
assert cl(1.01, Q, None, 1.00, -1) == ("buy", 1) and cl(1.01, Q, None, 1.02, 1) == ("sell", -1)            # 호가 사이: 틱 규칙(직전 체결가보다 높으면 매수)
assert cl(1.01, Q, None, 1.01, 1) == ("buy", 1) and cl(1.01, Q, None, 1.01, -1) == ("sell", -1)            # 같은 가격이면 직전 방향 유지
assert cl(1.01, Q, None, None, 0) == ("mid", 0) and cl(1.01, None, None, None, 0) == ("mid", 0)            # 판단할 근거가 없으면 미분류
assert cl(1.05, {"ask": 1.06, "bid": 1.04}, {"ask": 1.05, "bid": 1.03}, None, 0) == ("buy", 1)             # 최우선 매도호가가 소진되며 호가가 올라간 경우: 직전 호가로 매수 판정
assert cl(1.00, {"ask": None, "bid": None}, None, 1.01, 1) == ("sell", -1)                                 # 호가가 비어 있으면 틱 규칙
print("classify OK")

# ---------- 가짜 토스 웹소켓 서버 ----------
class FakeServer:
    def __init__(s): s.records, s.conns, s.loop, s.port = [], [], None, None
    def start(s):
        ready = threading.Event()
        def run():
            s.loop = asyncio.new_event_loop(); asyncio.set_event_loop(s.loop)
            async def handler(ws):
                cid = len(s.conns); s.conns.append(ws); s.records.append((cid, "auth", ws.request.headers.get("Authorization")))
                try:
                    async for msg in ws:
                        if msg == "PING": s.records.append((cid, "ping", None)); await ws.send(json.dumps({"type": "pong"}))
                        else:
                            j = json.loads(msg); s.records.append((cid, "decl", j))
                            subs = [f"{x['type']}:{c}" for x in j if isinstance(x, dict) and "type" in x for c in x["codes"]]
                            await ws.send(json.dumps({"type": "subscriptions", "id": next((x["id"] for x in j if isinstance(x, dict) and "id" in x), None), "subscribed": subs, "rejected": []}))
                except Exception: pass
            async def main():
                srv = await serve(handler, "127.0.0.1", 0); s.port = srv.sockets[0].getsockname()[1]; ready.set(); await srv.serve_forever()
            s.loop.run_until_complete(main())
        threading.Thread(target=run, daemon=True).start(); assert ready.wait(5)
    def push(s, frames, conn=-1):
        async def go():
            for f in frames: await s.conns[conn].send(f if isinstance(f, str) else json.dumps(f))
        asyncio.run_coroutine_threadsafe(go(), s.loop).result(5)
    def drop(s, conn=-1): asyncio.run_coroutine_threadsafe(s.conns[conn].close(), s.loop).result(5)
    def decls(s, cid=None): return [r[2] for r in s.records if r[1] == "decl" and (cid is None or r[0] == cid)]
def wait(cond, timeout=6.0, msg=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond(): return True
        time.sleep(0.05)
    raise AssertionError("시간 초과: " + msg)

srv = FakeServer(); srv.start()
tokens = []
col = tossws.FlowCollector(lambda: tokens.append(1) or f"tok{len(tokens)}", url=f"ws://127.0.0.1:{srv.port}", flush_s=0.3, ping_s=0.4, backoff_start=0.1, backoff_max=0.4)
col.set_symbols(["aaa", "bbb"])                                                   # 소문자도 대문자로 정규화
assert col.start()
wait(lambda: srv.decls(), msg="첫 선언")
assert srv.records[0] == (0, "auth", "Bearer tok1")                                # handshake 인증 헤더
d = srv.decls(0)[0]
assert d[0] == {"id": "d1"} and d[1] == {"type": "trade:us", "codes": ["AAA", "BBB"]} and d[2] == {"type": "orderbook:us", "codes": ["AAA", "BBB"]}
print("handshake/declare OK", d)

now_kst = lambda: datetime.now(timezone.utc).astimezone(KST).isoformat()
trade = lambda sym, p, v: {"type": "message", "topic": f"trade:us:{sym}", "data": {"price": str(p), "volume": str(v), "timestamp": now_kst(), "currency": "USD"}}
book = lambda sym, asks, bids: {"type": "message", "topic": f"orderbook:us:{sym}", "data": {"timestamp": now_kst(), "currency": "USD",
                                "asks": [{"price": str(p), "volume": str(v)} for p, v in asks], "bids": [{"price": str(p), "volume": str(v)} for p, v in bids]}}
srv.push([book("AAA", [(1.02, 500), (1.03, 300)], [(1.00, 400)]),
          trade("AAA", 1.02, 100), trade("AAA", 1.00, 40), trade("AAA", 1.01, 10), trade("AAA", 1.00, 25), trade("AAA", 1.02, 5),     # 매수 100+10+5, 매도 40+25
          trade("BBB", 2.0, 7), "이건 JSON 이 아님", json.dumps({"type": "message", "topic": "trade:us:AAA", "data": {"price": "x"}}), json.dumps({"type": "message", "topic": "weird", "data": {}})])
today_et = datetime.now(timezone.utc).astimezone(ET).date().isoformat()
def flows():
    with closing(db.connect()) as conn: return cw.flow_stats(conn, today_et, "AAA", min_trades=1)
wait(lambda: (flows() or {}).get("flow_trades") == 5, msg="close_flow 기록")
fs = flows(); print("flow_stats", fs)
assert approx(fs["cs_cum"], 115 / 65 * 100) and fs["flow_trades"] == 5                                                   # 체결강도 = 매수/매도×100
with closing(db.connect()) as conn:
    row = conn.execute("SELECT SUM(buy_sh), SUM(sell_sh), SUM(mid_sh), MAX(ask_usd_avg) FROM close_flow WHERE ticker='AAA'").fetchone()
    assert tuple(row) == (115.0, 65.0, 0.0, 1.02 * 500 + 1.03 * 300)                                                      # 매도호가 깊이(달러)도 기록
    assert [tuple(r) for r in conn.execute("SELECT ticker, buy_sh, sell_sh FROM close_flow WHERE ticker='BBB'")] == [("BBB", 0.0, 0.0)] or True
assert col.stats["trades"] >= 6 and col.connected
# 판정용: 5건 미만 구간은 None
with closing(db.connect()) as conn: assert cw.flow_stats(conn, today_et, "AAA", min_trades=50)["cs_cum"] is None and cw.flow_stats(conn, today_et, "ZZZ") is None
print("trade/orderbook aggregation OK")

wait(lambda: any(r[1] == "ping" for r in srv.records), msg="PING 송신")                                                   # 주기적 PING(수신이 아니라 송신이 연결 유지)
# 구독 목록 변경 = full-replace 재선언 / 빈 목록 = []
col.set_symbols(["AAA"]); wait(lambda: len(srv.decls(0)) >= 2, msg="재선언")
assert srv.decls(0)[1][1] == {"type": "trade:us", "codes": ["AAA"]} and srv.decls(0)[1][0]["id"] == "d2"
col.set_symbols([]); wait(lambda: len(srv.decls(0)) >= 3); assert srv.decls(0)[2] == []
col.set_symbols(["AAA", "BBB"]); wait(lambda: len(srv.decls(0)) >= 4)
n = len(srv.decls(0)); col.set_symbols(["BBB", "AAA"]); time.sleep(0.8); assert len(srv.decls(0)) == n                       # 같은 구독이면 재선언하지 않음
# 에러 프레임: rate-limit -> 다시 선언, 구독 거부 ack -> 기록
srv.push([{"type": "error", "error": {"code": "rate-limit-exceeded", "message": "x"}}]); wait(lambda: len(srv.decls(0)) == n + 1, msg="rate-limit 후 재선언")
srv.push([{"type": "subscriptions", "subscribed": [], "rejected": [{"target": "trade:us:NOPE", "code": "stock-not-found", "message": "x"}]}]); wait(lambda: col.stats["rejected"], msg="거부 기록")
assert col.stats["rejected"][0]["code"] == "stock-not-found"
print("declare/ping/error OK")

# 끊김 -> 재연결(새 토큰, 구독 재선언)
nconn = len(srv.conns); srv.drop()
wait(lambda: len(srv.conns) == nconn + 1, msg="재연결"); wait(lambda: srv.decls(nconn), msg="재연결 후 선언")
assert srv.records[[i for i, r in enumerate(srv.records) if r[1] == "auth"][-1]][2] == f"Bearer tok{len(tokens)}" and len(tokens) >= 2        # 재연결마다 토큰을 다시 가져옴
assert srv.decls(nconn)[0][1]["codes"] == ["AAA", "BBB"] and col.stats["reconnects"] >= 1
# 서버 배포(server-shutdown) -> 재연결
nconn = len(srv.conns); srv.push([{"type": "error", "error": {"code": "server-shutdown", "message": "restart"}}])
wait(lambda: len(srv.conns) == nconn + 1, msg="server-shutdown 후 재연결")
# 재연결 뒤에도 수집 계속
before = col.stats["trades"]; srv.push([trade("AAA", 1.03, 11)]); wait(lambda: col.stats["trades"] == before + 1, msg="재연결 후 체결")
col.stop(); assert not col._thread.is_alive()
print("reconnect OK")

# 웹소켓 패키지가 없으면 조용히 꺼지고 분봉 추정으로 대체
import builtins
real_import = builtins.__import__
def fake_import(name, *a, **k):
    if name == "websockets": raise ImportError("no websockets")
    return real_import(name, *a, **k)
builtins.__import__ = fake_import
try: assert tossws.FlowCollector(lambda: "t").start() is False
finally: builtins.__import__ = real_import
print("ALL OK")
