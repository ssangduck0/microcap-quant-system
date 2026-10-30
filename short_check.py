"""공매도 데이터 점검: python short_check.py [티커]
FINRA 일별 공매도 거래량 파일과 IBKR 대차 파일(공개 FTP)을 실제로 받아 보고, 파싱 결과와 종목 값을 보여 줍니다(키 불필요).
FINRA 파일 주소 형식(cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt)은 공식 화면에서 직접 확인하지 못한 부분이라,
'❌ FINRA' 가 나오면 결과를 알려 주세요."""
import sys
from contextlib import closing

import db
import shortdata


def main() -> int:
    sym = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").upper()
    db.init_db()
    sc = shortdata.ShortClient.from_config()
    bad = 0
    with closing(db.connect()) as conn:
        shortdata.ensure_tables(conn)
        print("== FINRA 일별 공매도 거래량")
        sc.refresh_finra(conn)
        files = conn.execute("SELECT date, status, n FROM finra_files ORDER BY date DESC LIMIT 8").fetchall()
        for f in files:
            print(f"  {f['date']}  {'✅' if f['status'] == 'ok' else '·'} {f['status']} {f['n'] or ''}")
        if not any(f["status"] == "ok" for f in files):
            print("  ❌ FINRA 파일을 하나도 받지 못했습니다", sc.errors.get("finra", ""))
            bad += 1
        print(f"  {sym}:", sc.finra_for(conn, sym) or "값 없음(해당 종목이 장외 거래 보고에 없거나 파일 미수신)")
        print("\n== IBKR 대차(공개 FTP ftp2.interactivebrokers.com / shortstock)")
        conn.execute("DELETE FROM shortdata_meta WHERE k='ibkr_fetched'")  # 점검은 항상 새로 받음
        conn.commit()
        sc.refresh_ibkr(conn)
        n = conn.execute("SELECT COUNT(*) FROM ibkr_borrow").fetchone()[0]
        if sc.errors.get("ibkr"):
            print("  ❌", sc.errors["ibkr"])
            bad += 1
        else:
            print(f"  ✅ {n:,}종목 · 파일 시각 {conn.execute('SELECT v FROM shortdata_meta WHERE k=?', ('ibkr_fetched',)).fetchone()[0]}")
        iv = sc.ibkr_for(conn, sym)
        print(f"  {sym}:", iv or "값 없음(IBKR 대차 목록에 한 번도 없었음)")
        if iv and iv.get("borrow_stale"):
            print("  ⚠️", iv["borrow_note"])
    print("\n== 합친 요약 (대시보드·체크리스트가 쓰는 값)")
    print(" ", sc.summary(sym))
    print("\n" + ("✅ 모두 정상" if not bad else f"⚠️ {bad}개 출처 확인 필요"))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
