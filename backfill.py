"""과거 일봉 백필: 감시했던 종목(+manual_tickers.txt +인자)의 최대 10년 일봉을 daily_prices 에 저장합니다.

  python backfill.py --years 10
  python backfill.py --years 10 --tickers AAPL,MSFT

주의(생존편향): 지금 하락 랭킹에 있는 종목만 백필하면 상장폐지된 초소형주가 빠져서 성과가 실제보다 좋게 나옵니다.
과거 상폐 종목까지 포함하려면 상폐 종목 목록이 있는 유료 데이터(Sharadar, Norgate, CRSP 등)가 필요합니다.
"""
import argparse
import logging
from contextlib import closing

import db
import market
import universe

log = logging.getLogger("backfill")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--tickers", default="")
    ap.add_argument("--nasdaq", action="store_true", help="나스닥 상장 전체를 백필 (오래 걸리고 DB가 커짐)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db.init_db()
    with closing(db.connect()) as conn:
        seen = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM daily_snapshots")]
        tickers = list(dict.fromkeys(
            seen + universe.from_manual() + [t.strip().upper() for t in args.tickers.split(",") if t.strip()]))
        if args.nasdaq:
            listed = universe.load_listed(include_amex=False)
            tickers = list(dict.fromkeys(tickers + listed))
            log.warning("나스닥 전체 %d개 백필: 수십 분 걸리고 DB가 수백 MB까지 커질 수 있습니다.", len(tickers))
        if not tickers:
            raise SystemExit("백필할 종목이 없습니다. manual_tickers.txt 를 만들거나 --tickers 를 지정하세요.")
        log.info("%d개 종목, 최근 %d년 백필 시작", len(tickers), args.years)
        total = 0
        for i in range(0, len(tickers), 20):
            chunk = tickers[i:i + 20]
            data = market.download_daily(chunk, period=f"{args.years}y")
            for t, df in data.items():
                total += db.upsert_daily_prices(conn, t, df)
            missing = [t for t in chunk if t not in data]
            if missing:
                log.warning("데이터 없음(상폐/티커변경 가능): %s", missing)
        log.info("완료: %d행 저장", total)


if __name__ == "__main__":
    main()
