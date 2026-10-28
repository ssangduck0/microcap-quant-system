"""💵 broker(4단계 1주 모드 1부, 2026-10-29) — 가짜 토스 클라이언트로: 기본 dry-run(실제 호출 0) · 안전장치 전부 · 1주 지정가 매수 · 체결 → 보유·일지·OCO · TTL 취소 ·
OCO 체결 감지 · 매도 · 일손실 킬 스위치 · 연속 거부 킬 · 요청 표 · toss.py 주문 메서드(헤더·본문·페이지·429)."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import datetime, timedelta, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import config, db, toss, broker, journal
db.init_db()
config.apply_overrides()
assert config.OFFLINE and config.LIVE_TRADING is False and config.LIVE_ONE_SHARE is True and broker.strategies() == {"piggy"} and broker.is_live() is False
T0 = datetime(2026, 10, 29, 14, 0, tzinfo=timezone.utc); D = "2026-10-29"
sent = []
import notify; notify.send_telegram = lambda text: sent.append(text) or True


class FakeTC:
    """토스 흉내: 주문은 PENDING 으로 받고, fill() 로 체결시킨다. 조건주문·계좌·매수가능금액 포함."""
    def __init__(s):
        s.db, s.cond, s.calls, s.n, s.bp, s.fail = {}, {}, [], 0, 1000.0, None
    def accounts(s): s.calls.append("accounts"); return [{"accountSeq": 77, "accountNo": "123-45", "accountType": "BROKERAGE"}]
    def buying_power(s, account, currency="USD"): assert account == 77; return {"currency": currency, "cashBuyingPower": s.bp}
    def order_create(s, account, symbol, side, qty, price=None, *, order_type="LIMIT", tif="DAY", client_order_id=None):
        assert account == 77 and order_type == "LIMIT" and price is not None and client_order_id
        s.calls.append(("create", symbol, side, qty, price, client_order_id))
        if s.fail:
            raise toss.TossError(422, s.fail, "거부")
        s.n += 1; oid = f"O{s.n}"
        s.db[oid] = {"orderId": oid, "clientOrderId": client_order_id, "symbol": symbol, "side": side, "orderType": "LIMIT", "status": "PENDING", "quantity": qty, "price": price,
                     "orderedAt": "2026-10-29T23:00:00+09:00", "execution": {"filledQuantity": 0, "averageFilledPrice": None}}
        return {"orderId": oid, "clientOrderId": client_order_id}
    def order_cancel(s, account, oid): s.calls.append(("cancel", oid)); s.db[oid]["status"] = "CANCELED"; return {"orderId": oid}
    def orders(s, account, status="OPEN", **k):
        return [o for o in s.db.values() if (o["status"] in broker.OPEN_STATES) == (status == "OPEN")]
    def cond_create(s, account, body): s.calls.append(("cond", body)); cid = f"C{len(s.cond) + 1}"; s.cond[cid] = body; return {"conditionalOrderId": cid, "clientOrderId": body.get("clientOrderId")}
    def cond_cancel(s, account, cid): s.calls.append(("cond_cancel", cid)); s.cond.pop(cid, None); return {"conditionalOrderId": cid}
    def fill(s, oid, px): o = s.db[oid]; o["status"] = "FILLED"; o["execution"] = {"filledQuantity": o["quantity"], "averageFilledPrice": px}
    def oco_sell(s, symbol, qty, px):   # 토스 서버의 OCO 가 체결시킨 매도(우리 멱등키 없음)
        s.n += 1; oid = f"X{s.n}"
        s.db[oid] = {"orderId": oid, "clientOrderId": None, "symbol": symbol, "side": "SELL", "orderType": "LIMIT", "status": "FILLED", "quantity": qty, "price": px,
                     "orderedAt": "2026-10-30T01:00:00+09:00", "execution": {"filledQuantity": qty, "averageFilledPrice": px}}


tc = FakeTC()
# 1) 기본 dry-run: 기록만, 실제 호출 0
with closing(db.connect()) as conn:
    r = broker.mirror_buy(conn, tc, "piggy", "aaa", 0.5, tp_px=0.7, sl_px=0.45, pt_id=1, now=T0)
    assert r["mode"] == "dry" and r["ok"] and r["qty"] == 1 and abs(r["limit_px"] - 0.505) < 1e-9 and tc.calls == [] and sent == [], r
    row = dict(conn.execute("SELECT * FROM live_orders").fetchone()); assert row["status"] == "DRY" and row["mode"] == "dry" and row["ticker"] == "AAA" and row["client_order_id"] == f"piggy-AAA-20261029-B1"
    assert broker.mirror_buy(conn, tc, "rank", "BBB", 0.5, now=T0)["mode"] == "off"                                   # 실매매 대상 전략 아님
    assert broker.sync(conn, tc, now=T0) == {"filled": 0, "canceled": 0, "ttl": 0, "oco_fills": 0, "kill": None} and tc.calls == []   # 꺼져 있으면 조회도 안 함
# 2) 안전장치(can_buy) 하나씩
config.LIVE_TRADING = True
with closing(db.connect()) as conn:
    ok = lambda **k: broker.can_buy(conn, "piggy", "ZZZ", 0.5, 1, day=D, **k)
    assert ok() == (True, "")
    assert ok(dilution="ATM")[1] == "희석 ATM" and ok(share_cls="bad")[1] == "⑥ 주식수 +20% 초과" and ok(dollar_vol=1000)[1].startswith("거래대금") and ok(buying_power=0.3)[1].startswith("매수가능")
    assert broker.can_buy(conn, "piggy", "ZZZ", 7.0, 1, day=D)[1].startswith("주가 $7.00 > 상한") and broker.can_buy(conn, "piggy", "ZZZ", 0.5, 0, day=D)[1] == "1주 미만"
    assert broker.can_buy(conn, "after", "ZZZ", 0.5, 1, day=D)[1].startswith("전략 'after'")
    config.LIVE_ONE_SHARE = False; assert broker.quantity_for(0.42) == 238 and broker.quantity_for(150.0) == 0; config.LIVE_ONE_SHARE = True
# 3) 라이브 1주 매수 → 체결 → 보유·일지·OCO
with closing(db.connect()) as conn:
    r = broker.mirror_buy(conn, tc, "piggy", "AAA", 0.5, tp_px=0.7, sl_px=0.45, pt_id=1, dilution="CLEAN", share_cls="ok", dollar_vol=80000, now=T0)
    assert r["ok"] and r["mode"] == "live" and r["order_id"] == "O1" and tc.calls[-1] == ("create", "AAA", "BUY", 1, 0.505, "piggy-AAA-20261029-B2") and "매수 주문 AAA" in sent[-1], (r, tc.calls)
    assert broker.mirror_buy(conn, tc, "piggy", "AAA", 0.5, now=T0)["why"] == "미체결 매수 있음"
    assert broker.day_stats(conn, D) == {"buys": 1, "open": 0, "exposure": 0.51, "realized": 0.0}, broker.day_stats(conn, D)      # 0.505 → 반올림 0.51
    s = broker.sync(conn, tc, now=T0 + timedelta(minutes=5)); assert s["filled"] == 0 and s["ttl"] == 0                               # 아직 대기
    tc.fill("O1", 0.50)
    s = broker.sync(conn, tc, now=T0 + timedelta(minutes=6)); assert s["filled"] == 1, s
    pos = broker.positions(conn); assert len(pos) == 1 and pos[0]["ticker"] == "AAA" and pos[0]["qty"] == 1 and pos[0]["avg_px"] == 0.5 and pos[0]["tp_px"] == 0.7 and pos[0]["sl_px"] == 0.45 and pos[0]["cond_id"] == "C1", pos
    body = tc.cond["C1"]; assert body["type"] == "OCO" and body["symbol"] == "AAA" and body["orderType"] == "LIMIT" and body["first"] == {"orderSide": "SELL", "triggerPrice": 0.7, "orderPrice": 0.7} \
        and body["second"]["triggerPrice"] == 0.45 and abs(body["second"]["orderPrice"] - 0.4455) < 1e-9 and body["expireDate"] == "2026-11-28", body
    j = journal.rows(conn) if hasattr(journal, "rows") else db.read_df("SELECT * FROM trade_journal")
    jl = db.read_df("SELECT * FROM trade_journal"); assert len(jl) == 1 and jl.iloc[0]["side"] == "매수" and jl.iloc[0]["price"] == 0.5 and jl.iloc[0]["signal"] == "자동 piggy", jl
    assert broker.mirror_buy(conn, tc, "piggy", "AAA", 0.5, now=T0)["why"] == "이미 보유"
# 4) TTL: 미체결 매수 30분 넘으면 취소, 그날 재시도 안 함
with closing(db.connect()) as conn:
    r = broker.mirror_buy(conn, tc, "piggy", "BBB", 1.234, tp_px=1.5, sl_px=1.1, now=T0); assert r["ok"] and r["limit_px"] == 1.24 and r["order_id"] == "O2"
    s = broker.sync(conn, tc, now=T0 + timedelta(minutes=31)); assert s["ttl"] == 1 and tc.db["O2"]["status"] == "CANCELED" and ("cancel", "O2") in tc.calls, s
    s = broker.sync(conn, tc, now=T0 + timedelta(minutes=32)); assert s["canceled"] == 1
    assert dict(conn.execute("SELECT status FROM live_orders WHERE client_order_id='piggy-BBB-20261029-B1'").fetchone())["status"] == "CANCELED"
    assert broker.mirror_buy(conn, tc, "piggy", "BBB", 1.234, now=T0)["why"] == "오늘 이미 거부·취소된 종목"
# 5) OCO 체결 감지(토스가 판 것) → 보유 정리·손익·일지
with closing(db.connect()) as conn:
    tc.oco_sell("AAA", 1, 0.70)
    s = broker.sync(conn, tc, now=T0 + timedelta(hours=3)); assert s["oco_fills"] == 1 and broker.positions(conn) == [], s
    cl = db.read_df("SELECT * FROM live_closed"); assert len(cl) == 1 and abs(cl.iloc[0]["pnl_usd"] - 0.2) < 1e-9 and cl.iloc[0]["reason"].startswith("익절·손절")
    jl = db.read_df("SELECT * FROM trade_journal"); assert len(jl) == 2 and jl.iloc[-1]["side"] == "매도" and "+0.20" in jl.iloc[-1]["note"]
    assert broker.day_stats(conn, D)["realized"] == 0.2
# 6) 우리 매도(청산 판정·화면 요청): OCO 취소 → 지정가 매도 → 체결 → 정리. 일손실 넘으면 킬 스위치
with closing(db.connect()) as conn:
    config.LIVE_MAX_ORDERS_PER_DAY = 10
    r = broker.mirror_buy(conn, tc, "piggy", "CCC", 2.0, tp_px=2.6, sl_px=1.8, now=T0 + timedelta(hours=4)); assert r["ok"]
    tc.fill(r["order_id"], 2.0); broker.sync(conn, tc, now=T0 + timedelta(hours=4, minutes=1))
    assert broker.positions(conn)[0]["cond_id"] == "C2"
    assert broker.sell(conn, tc, "NOPE", 1.0, "x")["why"] == "보유 없음"
    r2 = broker.sell(conn, tc, "CCC", 1.0, "저금통 박스 이탈", now=T0 + timedelta(hours=5)); assert r2["ok"] and ("cond_cancel", "C2") in tc.calls and tc.calls[-1][0] == "create" and tc.calls[-1][2] == "SELL" and tc.calls[-1][4] == 0.99
    assert broker.sell(conn, tc, "CCC", 1.0, "again")["why"] == "미체결 매도 있음"
    config.LIVE_DAILY_LOSS_USD = 0.5
    tc.fill(r2["order_id"], 0.99)
    s = broker.sync(conn, tc, now=T0 + timedelta(hours=5, minutes=1)); assert s["filled"] == 1 and s["kill"] and "실현손실" in s["kill"], s
    assert broker.positions(conn) == [] and abs(broker.day_stats(conn, D)["realized"] - (0.2 - 1.01)) < 1e-9
    assert broker.killed() and config.LIVE_TRADING is False and broker.is_live() is False and config.overrides().get("LIVE_TRADING") is False
    assert broker.mirror_buy(conn, tc, "piggy", "DDD", 0.5, now=T0)["mode"] == "dry"                                                    # 킬 뒤엔 dry
    assert any("킬 스위치" in x for x in sent)
    broker.unkill(); config.LIVE_TRADING = True; assert broker.is_live()
    assert config.LIVE_MAX_ORDERS_PER_DAY == 3 and config.LIVE_DAILY_LOSS_USD == 50.0   # kill → save_overrides → apply_overrides 가 모듈 값을 DB 설정·기본값으로 되돌림(운영 기준)
    config.LIVE_MAX_ORDERS_PER_DAY = 10
# 7) 연속 거부 3회 → 킬 · 요청 표
with closing(db.connect()) as conn:
    tc.fail = "insufficient-buying-power"; broker._fails = 0
    for i, t in enumerate(("E1", "E2", "E3")):
        r = broker.mirror_buy(conn, tc, "piggy", t, 0.5, now=T0 + timedelta(hours=6))
        assert r["ok"] is False and r["why"] == "insufficient-buying-power", (t, r, broker.day_stats(conn, D), broker.killed())
    assert broker.killed() and "연속 거부 3회" in broker.killed(); tc.fail = None; broker.unkill(); config.LIVE_TRADING = True
    rid = broker.request(conn, "sell", "zzz", "화면에서"); assert rid >= 1 and broker.process_requests(conn, tc, {"ZZZ": 1.0}) == 1
    assert "보유 없음" in dict(conn.execute("SELECT result FROM live_requests WHERE id=?", (rid,)).fetchone())["result"]
    st = broker.status(conn, now=T0); assert st["live"] and st["day"]["buys"] >= 3 and isinstance(st["recent"], list) and st["limits"]["LIVE_ONE_SHARE"] is True
# 8) toss.py 주문 메서드: 헤더·본문·result 파싱·페이지·429 재시도(멱등키 있을 때만)
class Resp:
    def __init__(s, status=200, body=None, headers=None): s.status_code = status; s._b = body if body is not None else {}; s.headers = headers or {}; s.text = json.dumps(s._b)
    def json(s): return s._b
class Sess:
    def __init__(s): s.log = []; s.n429 = 0
    def post(s, url, data=None, json=None, headers=None, params=None, timeout=0):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        if path == "/oauth2/token":
            return Resp(200, {"access_token": "tokA", "token_type": "Bearer", "expires_in": 86400})
        s.log.append(("POST", path, json, headers))
        if path == "/api/v1/orders" and json.get("clientOrderId") == "retry-1" and s.n429 == 0:
            s.n429 += 1; return Resp(429, {"error": {"code": "rate-limit-exceeded", "message": "slow", "requestId": "r1"}}, {"Retry-After": "1"})
        if path == "/api/v1/orders":
            return Resp(200, {"result": {"orderId": "ORD1", "clientOrderId": json.get("clientOrderId")}})
        if path.endswith("/cancel"):
            return Resp(200, {"result": {"orderId": "ORD1c"}})
        if path == "/api/v1/conditional-orders":
            return Resp(200, {"result": {"conditionalOrderId": "COND9", "clientOrderId": json.get("clientOrderId")}})
        return Resp(404, {"error": {"code": "not-found", "message": ""}})
    def get(s, url, params=None, headers=None, timeout=0):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        s.log.append(("GET", path, params, headers))
        if path == "/api/v1/accounts":
            return Resp(200, {"result": {"accounts": [{"accountSeq": 77, "accountNo": "1", "accountType": "BROKERAGE"}]}})
        if path == "/api/v1/buying-power":
            return Resp(200, {"result": {"currency": params["currency"], "cashBuyingPower": "123.45"}})
        if path == "/api/v1/orders":
            if params["status"] == "OPEN":
                return Resp(200, {"result": {"orders": [{"orderId": "A", "status": "PENDING"}], "nextCursor": None, "hasNext": False}})
            if params.get("cursor") == "c2":
                return Resp(200, {"result": {"orders": [{"orderId": "C", "status": "FILLED"}], "nextCursor": None, "hasNext": False}})
            return Resp(200, {"result": {"orders": [{"orderId": "B", "status": "CANCELED"}], "nextCursor": "c2", "hasNext": True}})
        return Resp(404, {"error": {"code": "not-found", "message": ""}})
    def delete(s, url, params=None, headers=None, timeout=0):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        s.log.append(("DELETE", path, None, headers)); return Resp(200, {"result": {"conditionalOrderId": path.rsplit("/", 1)[1]}})
class Clock:
    def __init__(s): s.t = 1000.0; s.slept = []
    def now(s): return s.t
    def sleep(s, x): s.slept.append(x); s.t += x
sess, clk = Sess(), Clock()
cl = toss.TossClient("id", "secret", "https://openapi.tossinvest.com", session=sess, sleep=clk.sleep, clock=clk.now)
assert cl.accounts() == [{"accountSeq": 77, "accountNo": "1", "accountType": "BROKERAGE"}] and sess.log[-1][3]["Authorization"] == "Bearer tokA" and "X-Tossinvest-Account" not in sess.log[-1][3]
assert cl.buying_power(77, "USD") == {"currency": "USD", "cashBuyingPower": "123.45"} and sess.log[-1][3]["X-Tossinvest-Account"] == "77"
r = cl.order_create(77, "AAA", "BUY", 1, 0.505, client_order_id="k-1"); assert r == {"orderId": "ORD1", "clientOrderId": "k-1"}
m, p, body, h = sess.log[-1]; assert (m, p) == ("POST", "/api/v1/orders") and body == {"symbol": "AAA", "side": "BUY", "orderType": "LIMIT", "quantity": "1", "price": "0.505", "clientOrderId": "k-1"} and h["X-Tossinvest-Account"] == "77"
n0 = len(sess.log); r = cl.order_create(77, "AAA", "BUY", 1, 0.5, client_order_id="retry-1"); assert r["orderId"] == "ORD1" and len(sess.log) - n0 == 2 and clk.slept[-1] == 1.0   # 429 → Retry-After 뒤 1번 재시도(멱등키 있음)
assert cl.order_cancel(77, "ORD1") == {"orderId": "ORD1c"} and sess.log[-1][1] == "/api/v1/orders/ORD1/cancel"
assert [o["orderId"] for o in cl.orders(77, "OPEN")] == ["A"] and [o["orderId"] for o in cl.orders(77, "CLOSED", since="2026-10-27")] == ["B", "C"] and sess.log[-1][2]["cursor"] == "c2" and sess.log[-2][2]["from"] == "2026-10-27"
body = broker.oco_body("AAA", 1, 0.7, 0.45, "oco-1", "2026-11-28"); r = cl.cond_create(77, body)
assert r["conditionalOrderId"] == "COND9" and sess.log[-1][2]["first"] == {"orderSide": "SELL", "triggerPrice": "0.7", "orderPrice": "0.7"} and sess.log[-1][2]["quantity"] == "1" and sess.log[-1][2]["type"] == "OCO"
assert cl.cond_cancel(77, "COND9") == {"conditionalOrderId": "COND9"} and sess.log[-1][0] == "DELETE"
try:
    cl.order_create(77, "AAA", "BUY", 1, None); raise AssertionError("지정가인데 가격 없이 통과")
except ValueError:
    pass
# 9) 정규장 저금통 저점 구간 → 1주 매수(dry 는 하루 한 번 기록, 라이브는 주문 · 희석 ATM 은 금지) · 장 밖·전략 꺼짐이면 아무것도 안 함
import piggy
piggy.ensure_tables(); piggy.add("PGA", "좁은 박스(15~30%)", 1.00, 1.30); piggy.add("PGB", "좁은 박스(15~30%)", 2.00, 2.50); piggy.add("PGC", "좁은 박스(15~30%)", 3.00, 4.00)
now_ = db.utcnow_iso()
with closing(db.connect()) as conn:
    for t, dil, dv in (("PGA", "CLEAN", 90000.0), ("PGB", "ATM", 90000.0), ("PGC", "CLEAN", 90000.0)):
        db.upsert_snapshot(conn, {"date": D, "ticker": t, "exchange": "NASDAQ", "first_seen": now_, "last_seen": now_, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -40.0,
                                  "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0, "pump_detail": '{"checks":[]}',
                                  "dilution_status": dil, "excluded": 0, "avg_dollar_vol": dv})
    PX = {"PGA": {"price": 1.02}, "PGB": {"price": 2.05}, "PGC": {"price": 3.60}}          # PGA·PGB 저점 구간, PGC 는 중간
    T1 = datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)                               # 금요일 10:00 ET(정규장)
    assert broker._regular(T1) and not broker._regular(datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)) and not broker._regular(datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc))
    assert broker.scan_piggy(conn, tc, prices=PX, now=datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)) == {"checked": 0, "bought": [], "dry": [], "skipped": {}}   # 장 밖
    config.LIVE_TRADING = False
    r = broker.scan_piggy(conn, tc, prices=PX, now=T1); assert r["checked"] == 3 and r["dry"] == ["PGA"] and r["skipped"] == {"PGB": "희석 ATM"} and r["bought"] == [], (r, broker.strategies(), broker.piggy_targets(conn), piggy.items().to_dict("records"))
    assert broker.scan_piggy(conn, tc, prices=PX, now=T1 + timedelta(minutes=1)) == {"checked": 3, "bought": [], "dry": [], "skipped": {}}   # 같은 날 두 번 안 함
    rows = db.read_df("SELECT ticker, status, mode, note FROM live_orders WHERE day='2026-10-30'"); assert sorted(rows["ticker"]) == ["PGA", "PGB"] and set(rows["mode"]) == {"dry"}
    config.LIVE_TRADING = True
    T2 = T1 + timedelta(days=3, hours=1)                                                    # 월요일 11/2 15:00 UTC = 10:00 EST(11/1 에 서머타임 끝 → 14:00 UTC 는 09:00 이라 장 밖!)
    n_calls = len(tc.calls)
    r = broker.scan_piggy(conn, tc, prices=PX, now=T2); assert r["bought"] == ["PGA"] and r["skipped"] == {"PGB": "희석 ATM"}, r
    assert tc.calls[n_calls][0] == "create" and tc.calls[n_calls][1:4] == ("PGA", "BUY", 1) and abs(tc.calls[n_calls][4] - 1.03) < 1e-9   # 1.02 × 1.01 = 1.0302 → $1 이상은 소수 2자리 절삭
    oid = tc.calls[n_calls][5]; row = dict(conn.execute("SELECT * FROM live_orders WHERE client_order_id=?", (oid,)).fetchone()); assert json.loads(row["note"]) == {"tp": 1.3, "sl": 0.95}
    tc.fill(row["order_id"], 1.02); broker.sync(conn, tc, now=T2 + timedelta(minutes=1))
    pos = broker.positions(conn); assert [p["ticker"] for p in pos] == ["PGA"] and pos[0]["tp_px"] == 1.3 and abs(pos[0]["sl_px"] - 0.95) < 1e-9 and pos[0]["cond_id"], pos
    config.LIVE_STRATEGIES = ""; assert broker.scan_piggy(conn, tc, prices=PX, now=T2)["checked"] == 0; config.LIVE_STRATEGIES = "piggy"
# 10) 1주 왕복 테스트(probe): 요청 표 → 주가 상한·전략 목록 무시하고 1주 매수 → 체결 → OCO 대신 바로 되팔기 → 체결 → 정리
with closing(db.connect()) as conn:
    T3 = T2 + timedelta(hours=1)
    rid = broker.request(conn, "probe", "aapl", "관리 화면 1주 왕복")
    n_calls, n_cond = len(tc.calls), len(tc.cond)
    assert broker.process_requests(conn, tc, {"AAPL": 250.0}, now=T3) == 1
    res = json.loads(dict(conn.execute("SELECT result FROM live_requests WHERE id=?", (rid,)).fetchone())["result"]); assert res["ok"] and res["mode"] == "live" and res["qty"] == 1 and res["limit_px"] == 252.5, res
    tc.fill(res["order_id"], 250.0)
    s = broker.sync(conn, tc, now=T3 + timedelta(minutes=1)); assert s["filled"] == 1 and len(tc.cond) == n_cond and tc.calls[-1][0] == "create" and tc.calls[-1][2] == "SELL" and tc.calls[-1][4] == 247.5, (s, tc.calls[-1])
    sell_oid = tc.calls[-1][5]; row = dict(conn.execute("SELECT * FROM live_orders WHERE client_order_id=?", (sell_oid,)).fetchone()); tc.fill(row["order_id"], 249.0)
    s = broker.sync(conn, tc, now=T3 + timedelta(minutes=2)); assert s["filled"] == 1 and all(p["ticker"] != "AAPL" for p in broker.positions(conn))
    cl = db.read_df("SELECT * FROM live_closed WHERE ticker='AAPL'"); assert len(cl) == 1 and abs(cl.iloc[0]["pnl_usd"] + 1.0) < 1e-9 and cl.iloc[0]["reason"] == "1주 왕복 테스트 매도"
    assert any("1주 왕복" in x or "AAPL" in x for x in sent)
print("ALL OK")
