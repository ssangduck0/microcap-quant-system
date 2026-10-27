"""📅 주말 날짜로 잘못 찍힌 스캐너 기록 정리(10-18 같은 토·일 날짜).

원인: 금요일 시간외 봉의 시각이 UTC 로 들어와 토요일 날짜가 됐음(market.et_trade_date 로 고침).
처음엔 '확인만' 한다:  python fix_weekend_dates.py
정리하려면:            python fix_weekend_dates.py --apply
 - 같은 종목의 직전 금요일 기록이 없으면 → 금요일 날짜로 옮김
 - 이미 있으면 → 주말 기록을 지움(금요일 기록이 같은 장 데이터라 중복)
"""
import sys
from contextlib import closing
from datetime import date, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
import config
config.apply_overrides()
import db

TABLES = ["daily_snapshots", "signals"]


def friday(d: str) -> str:
    x = date.fromisoformat(d)
    while x.weekday() >= 5:
        x -= timedelta(days=1)
    return x.isoformat()


def main(apply: bool) -> None:
    with closing(db.connect()) as conn:
        for tb in TABLES:
            try:
                rows = conn.execute(f"SELECT rowid, date, ticker FROM {tb} WHERE strftime('%w', date) IN ('0','6')").fetchall()
            except Exception as e:  # noqa: BLE001
                print(f"{tb}: 건너뜀({e})")
                continue
            move = dele = 0
            for rid, d, t in rows:
                f = friday(d)
                has = conn.execute(f"SELECT 1 FROM {tb} WHERE date=? AND ticker=? LIMIT 1", (f, t)).fetchone()
                if has:
                    dele += 1
                    if apply:
                        conn.execute(f"DELETE FROM {tb} WHERE rowid=?", (rid,))
                else:
                    move += 1
                    if apply:
                        conn.execute(f"UPDATE {tb} SET date=? WHERE rowid=?", (f, rid))
            days = sorted({d for _, d, _ in rows})
            print(f"{tb}: 주말 날짜 {len(rows):,}줄 {days[:6]} → 금요일로 옮김 {move:,} · 중복 지움 {dele:,}" + ("" if apply else "  (확인만 — 정리하려면 --apply)"))
        if apply:
            conn.commit()
            print("정리했어요.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
