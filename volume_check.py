"""거래량 비교 점검:  python volume_check.py [티커 ...]

같은 종목의 오늘 거래량을 세 곳에서 비교합니다.
  (1) 토스 1분봉 거래량 합   (2) yfinance 1분봉 거래량 합(프리/애프터 포함)   (3) 토스 실시간 거래량 랭킹(시장 전체 기준)
(1)이 (2)·(3)과 크게 다르면, 토스 1분봉의 거래량은 시장 전체 거래량이 아닙니다 -> 거래량 배수 계산에 쓰면 안 됩니다.
"""
import sys

import pandas as pd
import yfinance as yf

import config
import toss


def yf_volume(sym: str):
    try:
        y = yf.download(sym, period="1d", interval="1m", prepost=True, progress=False, auto_adjust=False)
        if isinstance(y.columns, pd.MultiIndex):
            y.columns = y.columns.get_level_values(0)
        return float(y["Volume"].sum())
    except Exception as e:  # noqa: BLE001
        print(f"  (yfinance {sym} 실패: {type(e).__name__})")
        return None


def main() -> int:
    if not config.TOSS_ENABLED:
        print("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 이 .env 에 없습니다.")
        return 1
    syms = [s.upper() for s in sys.argv[1:]]
    tc = toss.TossClient(config.TOSS_CLIENT_ID, config.TOSS_CLIENT_SECRET, config.TOSS_BASE_URL)
    rank = {r["symbol"]: r for r in tc.rankings("MARKET_TRADING_VOLUME", "US", "realtime", 100)}
    syms = syms or ["AAPL"] + list(rank)[:3]   # 기본: AAPL + 지금 거래량 상위 3종목
    print(f"{'티커':<7}{'토스 1분봉 합':>16}{'yfinance 1분봉 합':>20}{'토스/yf':>9}{'토스 랭킹(시장전체)':>22}")
    for s in syms:
        df = tc.intraday_frame(s)
        tv = float(df["Volume"].sum()) if df is not None else None
        yv = yf_volume(s)
        rv = rank.get(s, {}).get("tradingVolume")
        ratio = f"{tv / yv:.2f}" if tv and yv else "-"
        print(f"{s:<7}{(f'{tv:,.0f}' if tv else '-'):>16}{(f'{yv:,.0f}' if yv else '-'):>20}{ratio:>9}{(f'{float(rv):,.0f}' if rv else '(랭킹 밖)'):>22}")
    print("\n해석: 토스/yf 가 0.9~1.1 이면 일치(그대로 사용 가능). 그보다 많이 작으면 토스 분봉 거래량은 일부 체결분입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
