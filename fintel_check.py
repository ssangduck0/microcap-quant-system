"""Fintel API 점검: python fintel_check.py [티커]
.env 의 FINTEL_API_KEY 로 공매도 거래량·대차 수수료·공매도 잔고를 호출해 **원본 응답과 파싱 결과를 그대로** 보여 줍니다.
(응답 필드 이름을 공식 문서에서 직접 확인하지 못해, '파싱: 값을 찾지 못함'이 나오면 위의 원본을 알려 주세요. 키 자체는 대화에 붙여넣지 마세요.)
"""
import json
import sys

import config
import fintel


def main() -> int:
    sym = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").upper()
    if not config.FINTEL_API_KEY:
        print("❌ .env 에 FINTEL_API_KEY=... 줄이 없습니다 (프로젝트 폴더의 .env 파일에 추가하세요).")
        return 1
    client = fintel.FintelClient(config.FINTEL_API_KEY)
    bad = 0
    for kind, parser in fintel.PARSERS.items():
        print(f"\n== {kind} ({sym})")
        try:
            j = client.raw(kind, sym)
        except Exception as e:  # noqa: BLE001
            print("  ❌", e)
            bad += 1
            continue
        print("  원본:", json.dumps(j, ensure_ascii=False)[:800])
        p = parser(j)
        print("  파싱:", p if p else "❌ 값을 찾지 못함 → 위 원본의 필드 이름을 알려 주세요")
        bad += 0 if p else 1
    print("\n" + ("✅ 모두 정상" if not bad else f"⚠️ {bad}개 항목 확인 필요"))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
