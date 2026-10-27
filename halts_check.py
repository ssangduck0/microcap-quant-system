"""거래정지 점검: python halts_check.py [티커] [--nasdaq]
기본은 업킷 API(https://upcuit.com/api/v1/halts), 실패하면 나스닥 공식 RSS 로 자동 전환합니다. --nasdaq 는 RSS 만 확인합니다."""
import sys
from collections import Counter

import halts


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = "nasdaq" if "--nasdaq" in sys.argv else None
    try:
        hs = halts.fetch(ttl=0, source=src)
    except Exception as e:  # noqa: BLE001
        print("❌ 거래정지 목록을 받지 못했습니다(업킷·나스닥 모두):", type(e).__name__, e)
        return 1
    print(f"✅ 출처: {halts.last_source} · {len(hs)}건" + ("  (업킷이 실패해 나스닥 RSS 를 사용)" if halts.last_source == "nasdaq" and not src else ""))
    print("사유 코드별:", dict(Counter(h["code"] for h in hs)))
    for h in hs[:8]:
        print(f"  {h['symbol']:<6} {h['halt']:%m-%d %H:%M:%S} {h['code']:<5} {halts.CODE_KO.get(h['code'], h.get('title') or ''):<16} "
              f"밴드가 {h['threshold']} 재개 {h['resume'] or ('호가만 재개' if h.get('status') == 'quote_resumed' else '정지 중')}"
              if h["halt"] else f"  {h['symbol']:<6} (정지 시각 없음) {h['code']}")
    if args:
        t = args[0].upper()
        mine = [h for h in hs if h["symbol"] == t]
        print(f"\n{t}: {len(mine)}건", [(h['halt'].strftime('%H:%M:%S') if h['halt'] else None, h['code'], h['threshold']) for h in mine])
    return 0


if __name__ == "__main__":
    sys.exit(main())
