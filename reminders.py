"""⏰ 예약 알림 — '나중에 다시 보자'고 미뤄 둔 일을 때가 되면 텔레그램으로 한 번 알려 준다.

매일 아침 갱신이 check() 를 부른다. 알림마다 '가장 이른 날짜' + '준비 조건'이 있고, 둘 다 맞으면(또는 늦어도 되는 날이 지나면)
텔레그램을 보내고 DB(meta 'reminder:<id>')에 보낸 날을 적어 다시 보내지 않는다. ⚙️ 관리 모드에서 상태를 볼 수 있다.
새 알림은 REMINDERS 에 추가하면 된다.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date

import db


def _hybrid_ready(conn, today: date) -> tuple[bool, str]:
    """공시 점수 '두 방식 합치기' 실험: 이벤트 라벨이 거의 다 붙었는지 + 가상매매가 쌓였는지."""
    try:
        tot = conn.execute("SELECT COUNT(*) FROM ev_docs WHERE ok=1").fetchone()[0] or 0
        lab = conn.execute("SELECT COUNT(*) FROM ev_labels").fetchone()[0] or 0
        nod = conn.execute("SELECT COALESCE(SUM(n_pending),0) FROM ev_label_try WHERE status='no_data'").fetchone()[0] or 0
    except Exception:  # noqa: BLE001
        tot = lab = nod = 0
    pend = max(0, tot - lab - nod)  # 주가 자료가 없는(상폐 추정) 공시는 '남은 일'에서 뺌
    share = pend / tot if tot else 1.0
    try:
        pt = conn.execute("SELECT COUNT(*) FROM pt_trades WHERE status='closed'").fetchone()[0] or 0
    except Exception:  # noqa: BLE001
        pt = 0
    return share < 0.05, f"이벤트 라벨 남은 비율 {share * 100:.1f}%(5% 미만이면 준비) · 라벨 {lab:,}건 · 가상매매 청산 {pt}건"


REMINDERS = [
    {"id": "evscore_hybrid", "earliest": "2026-11-15", "latest": "2026-11-22",
     "title": "🧮 공시 점수 '두 방식 합치기' 실험 시기",
     "message": ("10월 25일에 미뤄 둔 일: 공시 점수를 '호재/악재 판정 + 사건 종류·가격대·시점'으로 합쳐 최근 1년 검증으로 시험하기.\n"
                 "이벤트 라벨이 거의 다 붙어 자료가 안정됐어요. Claude 와의 대화에서 '두 방식 합치기 실험하자'고 말해 주세요. "
                 "그 전에 PC에서 python evscore.py 결과와 🧪 가상매매 신호별 성과를 함께 보면 좋아요."),
     "ready": _hybrid_ready},
]


def status(conn, today: date | None = None) -> list[dict]:
    """[{id, title, earliest, latest, sent, ready, detail, due}] — 관리 모드 표시용."""
    today = today or date.today()
    out = []
    for r in REMINDERS:
        m = db.get_meta(f"reminder:{r['id']}")
        sent = json.loads(m["value"]).get("sent") if m and m.get("value") else None
        ok, detail = r["ready"](conn, today)
        due = today.isoformat() >= r["earliest"] and (ok or today.isoformat() >= r["latest"])
        out.append({"id": r["id"], "title": r["title"], "earliest": r["earliest"], "latest": r["latest"], "sent": sent, "ready": ok, "detail": detail, "due": due})
    return out


def check(today: date | None = None, send=None, out=print) -> list[str]:
    """때가 된 알림을 텔레그램으로 한 번씩 보냄. 보낸 알림 id 목록."""
    today = today or date.today()
    if send is None:
        import notify
        send = notify.send_telegram
    done = []
    with closing(db.connect()) as conn:
        for st_, r in zip(status(conn, today), REMINDERS):
            if st_["sent"] or not st_["due"]:
                continue
            ok = send(f"⏰ {r['title']}\n\n{r['message']}\n\n(상태: {st_['detail']})")
            if ok:
                db.set_meta(f"reminder:{r['id']}", json.dumps({"sent": today.isoformat()}, ensure_ascii=False))
                done.append(r["id"])
                out(f"예약 알림 보냄: {r['title']}")
            else:
                out(f"예약 알림 보내기 실패(텔레그램): {r['title']} — 내일 다시 시도")
    return done
