"""토스 Open API 연결 점검:  python toss_check.py

각 단계의 성공/실패와 서버가 준 오류 코드·메시지를 보여줍니다. client_secret 과 토큰은 출력하지 않습니다.
이 결과를 (민감정보 없이) 그대로 공유하면 문제 원인을 바로 볼 수 있습니다.
"""
import sys
import time

import config
import toss


def step(name, fn):
    t0 = time.time()
    try:
        out = fn()
        print(f"  ✅ {name}: {out}  ({time.time() - t0:.1f}s)")
        return True
    except toss.TossError as e:
        print(f"  ❌ {name}: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {name}: {type(e).__name__}: {e}")
    return False


SAMPLE = "AAPL"  # 점검용 종목(원하면 python toss_check.py NVDA 처럼 바꿀 수 있음)


def main() -> int:
    global SAMPLE
    if len(sys.argv) > 1:
        SAMPLE = sys.argv[1].upper()
    if not config.TOSS_ENABLED:
        print("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 이 .env 에 없습니다 (또는 TOSS_ENABLED=0).")
        return 1
    tc = toss.TossClient(config.TOSS_CLIENT_ID, config.TOSS_CLIENT_SECRET, config.TOSS_BASE_URL)
    print(f"토스 Open API 점검 ({config.TOSS_BASE_URL})")
    if not step("1. 토큰 발급 + 환율", lambda: f"USD/KRW {tc.exchange_rate():,.2f}"):
        print("\n→ 403/access_denied 이면: 토스증권 WTS > 설정 > Open API > 허용 IP 관리에 지금 쓰는 PC의 공인 IP를 등록하세요.")
        print("→ 401/invalid_client 이면: client_id/secret 값(따옴표·공백 포함 여부)을 확인하세요.")
        return 2
    step("2. 미국 장 세션", lambda: toss.us_session(tc.us_calendar()))
    step("3. 현재가(AAPL, 하나의 요청으로 여러 종목)", lambda: {k: v["price"] for k, v in tc.prices(["AAPL", "NVDA"]).items()})
    step("4. 1분봉(AAPL, 최근 3개)", lambda: [(c["timestamp"][11:16], c["closePrice"], c["volume"]) for c in tc.candles("AAPL", "1m", 3)[0]])
    step("5. 오늘 1분봉 전체(AAPL)", lambda: (lambda d: f"{len(d)}개 봉, 거래량 합 {d['Volume'].sum():,.0f}" if d is not None else "없음")(tc.intraday_frame("AAPL")))
    step("6. 최근 체결(AAPL)", lambda: f"{len(tc.trades('AAPL', 5))}건 (체결 항목에 매수/매도 구분은 없음)")
    step("7. 미국 급하락 랭킹(1일)", lambda: [(r["symbol"], r["price"]["changeRate"]) for r in tc.rankings("TOP_LOSERS", "US", "1d", 5)])
    step("8. 미국 거래량 랭킹(실시간)", lambda: [(r["symbol"], r["tradingVolume"]) for r in tc.rankings("MARKET_TRADING_VOLUME", "US", "realtime", 5)])
    step("9. 나스닥 전체 종목 수", lambda: f"{len(tc.stocks_all('NASDAQ'))}개")
    def depth():
        before, pages, earliest = None, 0, None
        while pages < 60:
            c, nxt = tc.candles("AAPL", "1m", 200, before)
            pages += 1
            if not c:
                break
            earliest = c[-1]["timestamp"]
            if not nxt:
                return f"{pages}페이지에서 끝: 가장 오래된 1분봉 {earliest}"
            before = nxt
        return f"{pages}페이지(약 {pages * 200:,}봉)까지 계속 이어짐: 가장 오래된 봉 {earliest}"
    step("10. 1분봉이 과거 어디까지 제공되는지(AAPL)", depth)
    # ---- 장마감 체크리스트가 의존하는 가정 확인 (제가 실서버를 호출할 수 없어 직접 확인해야 하는 부분) ----
    import closewatch

    def book_levels():
        b = tc.orderbook(SAMPLE)
        return (f"매도 {len(b['asks'])}단계 / 매수 {len(b['bids'])}단계 · 매도 상위: {b['asks'][:3]} · 매수 상위: {b['bids'][:3]}"
                "  → 단계가 1~2개뿐이면 '매도벽' 판정은 거의 의미가 없습니다")
    step("11. 호가 단계 수(%s)" % SAMPLE, book_levels)

    def daily_match():
        df = tc.intraday_frame(SAMPLE)
        reg = closewatch.regular(df)
        daily = tc.daily_candles(SAMPLE, 4)
        lines = [f"일봉 {c['timestamp'][:16]} O{c['openPrice']} H{c['highPrice']} L{c['lowPrice']} C{c['closePrice']} V{c['volume']}" for c in daily[:3]]
        if reg is None or reg.empty:
            return " | ".join(lines) + " | 오늘 정규장 1분봉이 없음(장 시작 전/휴장) → 매칭 확인 불가"
        ctx = closewatch.daily_context(tc.daily_candles(SAMPLE, 25), reg)
        last = reg.iloc[-1]
        return (" | ".join(lines) + f" | 1분봉(정규장) 시가 {reg['Open'].iloc[0]:.2f} 마지막 종가 {last['Close']:.2f} 거래량 합 {reg['Volume'].sum():,.0f} | "
                + ("오늘 봉 매칭 성공: 전일 종가 %.2f, 20일 평균 거래량 %s" % (ctx["prev_close"], f"{ctx['avg_vol20']:,.0f}") if ctx
                   else "오늘 봉 매칭 실패 → 이 경우 알려 주세요(일봉 날짜 해석을 고쳐야 합니다)"))
    step("12. 토스 일봉의 '오늘 봉' 찾기", daily_match)

    def volume_consistency():
        reg = closewatch.regular(tc.intraday_frame(SAMPLE))
        if reg is None or reg.empty:
            return "정규장 1분봉이 없어 확인 불가(장중에 다시 실행하세요)"
        ctx = closewatch.daily_context(tc.daily_candles(SAMPLE, 25), reg)
        if not ctx or not ctx.get("today_daily_volume"):
            return "오늘 일봉을 못 찾아 확인 불가"
        r = reg["Volume"].sum() / ctx["today_daily_volume"]
        return f"1분봉 합 / 오늘 일봉 거래량 = {r:.2f} (0.9~1.1이면 같은 기준. 많이 다르면 알려 주세요 — 거래량 배수에 영향)"
    step("13. 일봉 거래량 vs 1분봉 합계", volume_consistency)

    def ws_check():
        import asyncio
        import json
        import time as _t
        try:
            import websockets  # noqa: F401
        except ImportError:
            raise RuntimeError("websockets 패키지가 없습니다 → pip install websockets")
        import tossws

        async def go():
            from websockets.asyncio.client import connect
            counts, sample = {"trade": 0, "orderbook": 0}, {}
            async with connect(tossws.WS_URL, additional_headers={"Authorization": f"Bearer {tc._token()}"}, open_timeout=15) as ws:
                await ws.send(json.dumps([{"id": "check"}, {"type": "trade:us", "codes": [SAMPLE]}, {"type": "orderbook:us", "codes": [SAMPLE]}]))
                end = _t.time() + 10
                while _t.time() < end:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - _t.time()))
                    except asyncio.TimeoutError:
                        break
                    f = json.loads(raw)
                    if f.get("type") == "subscriptions":
                        sample["ack"] = {"구독": f.get("subscribed"), "거부": f.get("rejected")}
                    elif f.get("type") == "message":
                        k = str(f.get("topic", "")).split(":")[0]
                        counts[k] = counts.get(k, 0) + 1
                        sample.setdefault(k, f.get("data"))
                    elif f.get("type") == "error":
                        sample["error"] = f.get("error")
            return counts, sample
        counts, sample = asyncio.run(go())
        return (f"10초 동안 체결 {counts['trade']}건 · 호가 {counts['orderbook']}건 · ack {sample.get('ack')} · 에러 {sample.get('error')} · 체결 예 {sample.get('trade')} · "
                f"호가 예 {str(sample.get('orderbook'))[:140]}  → 403 이면 허용 IP 미등록, 체결/호가가 0건이면 장이 한산한 종목일 수 있으니 거래가 활발한 종목으로 다시 실행하세요")
    step("14. 실시간 웹소켓 연결·구독(체결강도 계산용)", ws_check)
    print("\n❌ 가 있는 단계의 메시지를 알려주시면 원인을 확인할 수 있어요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
