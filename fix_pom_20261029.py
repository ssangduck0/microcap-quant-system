"""2026-10-29 01:15 실매매 첫 운영 사고의 잘못된 **장부만** 바로잡는 1회용 스크립트(실주문 없음, 토스 호출 없음).

무슨 일이었나: 1주 왕복 테스트로 POM 1주를 $1.89 에 사고 $1.87 매도를 낸 뒤, 옛 '토스 OCO 체결 감지'가 사용자가 따로 들고 있던
POM 386주를 $1.59 에 직접 판 기록을 우리 1주 포지션의 OCO 체결로 잘못 붙여 −$115.80 으로 기록 → 일손실 킬 스위치 작동.
(감지 규칙은 같은 날 고침: 조건주문이 실제 발동했을 때만 · 수량 일치 · 보유 시작 뒤 주문만.)

이 스크립트가 하는 일: 가짜 'oco-…' 매도 줄 · live_closed POM(386주) · 일지 'POM 매도 386주' 삭제 → POM 1주 포지션(매수 $1.89) 복원
→ 우리 매도 주문(S1)을 PENDING 으로 되돌려 다음 sync 가 토스 상태(이미 체결)를 다시 읽어 올바른 손익으로 정리하게 함 → 킬 메모 해제.
LIVE_TRADING 은 건드리지 않는다(꺼진 채, 관리 화면에서 사용자가 결정).

사용(서버): sudo -u quant /home/quant/quant_system/venv/bin/python -X utf8 /home/quant/quant_system/fix_pom_20261029.py [--drop-sell-requests]
  --drop-sell-requests : 관리 화면에서 눌러 둔 '지금 팔기'(FAMI·MRNO) 요청을 실행하지 않고 닫는다(안 주면 배포 뒤 스캐너가 실제로 판다).
"""
import sys
from contextlib import closing

import db

DROP = "--drop-sell-requests" in sys.argv[1:]
with closing(db.connect()) as conn:
    bad = [tuple(r) for r in conn.execute("SELECT client_order_id, qty, avg_px FROM live_orders WHERE client_order_id LIKE 'oco-%' AND ticker='POM' AND qty=386")]
    print("가짜 OCO 매도 줄:", bad)
    conn.execute("DELETE FROM live_orders WHERE client_order_id LIKE 'oco-%' AND ticker='POM' AND qty=386")
    print("live_closed POM 386주 삭제:", conn.execute("DELETE FROM live_closed WHERE ticker='POM' AND qty=386").rowcount)
    print("일지 'POM 매도 386' 삭제:", conn.execute("DELETE FROM trade_journal WHERE ticker='POM' AND side='매도' AND qty=386").rowcount)
    buy = conn.execute("SELECT avg_px, client_order_id FROM live_orders WHERE client_order_id='probe-POM-20261028-B2'").fetchone()
    if buy:
        conn.execute("INSERT OR REPLACE INTO live_positions (ticker, strategy, qty, avg_px, tp_px, sl_px, cond_id, opened_at, buy_coid) "
                     "VALUES ('POM','probe',1,?,NULL,NULL,NULL,'2026-10-28T16:15:43+00:00',?)", (buy["avg_px"], buy["client_order_id"]))
        n = conn.execute("UPDATE live_orders SET status='PENDING', filled_qty=0, avg_px=NULL WHERE client_order_id='probe-POM-20261028-S1'").rowcount
        print(f"POM 1주 포지션 복원(매수 ${buy['avg_px']}) · 매도 주문 S1 을 PENDING 으로 되돌림({n}줄) → 다음 sync 가 토스 체결을 반영")
    pend = [tuple(r) for r in conn.execute("SELECT id, kind, ticker FROM live_requests WHERE done_at IS NULL")]
    print("대기 중 요청:", pend)
    if DROP and pend:
        conn.execute("UPDATE live_requests SET done_at=?, result='사고 정리 스크립트로 닫음(실행 안 함)' WHERE done_at IS NULL AND kind='sell'", (db.utcnow_iso(),))
        print("→ '지금 팔기' 요청을 실행하지 않고 닫음")
    conn.commit()
    print("positions:", [tuple(r) for r in conn.execute("SELECT ticker, strategy, qty, avg_px, cond_id FROM live_positions")])
    print("closed:", [tuple(r) for r in conn.execute("SELECT ticker, qty, pnl_usd, reason FROM live_closed")])
db.set_meta("live:kill", "")
print("킬 메모 해제. LIVE_TRADING 은 그대로(꺼짐) — 다시 켜려면 관리 화면 두 단계. DONE")
