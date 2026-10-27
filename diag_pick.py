"""PICK +30% 점검 — 왜 전부 '대기'인지 실제 DB로 요약한다(읽기만 함, 아무것도 바꾸지 않음).

실행(프로젝트 폴더에서):  python diag_pick.py
결과를 그대로 복사해 Claude 에게 붙여 주면 된다. 종목 이름·숫자만 나오고 비밀값(.env)은 나오지 않는다.
"""
from __future__ import annotations

import os
import sys
os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")  # 화면 없이 실행할 때 나오는 경고 줄 숨김
import logging


class _Quiet(logging.Filter):
    def filter(self, rec):  # noqa: D102
        return not rec.name.startswith("streamlit")


logging.getLogger().addFilter(_Quiet())
try:
    import streamlit.logger as _stl
    _stl.set_log_level("error")
except Exception:  # noqa: BLE001
    pass
from collections import Counter
from contextlib import closing
from datetime import date

try:  # 윈도우 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import config
config.apply_overrides()
import db
import pick30


def q(conn, sql: str, p=()):
    try:
        return conn.execute(sql, p).fetchall()
    except Exception as e:  # noqa: BLE001
        return f"(읽기 실패: {e})"


def main() -> None:
    today = date.today().isoformat()
    print(f"== PICK 점검 {today} · DB {config.DB_PATH}")
    s = pick30.scan()
    rows = s["pass"] + s["fail"]
    print(f"\n[1] 등록 {s['registered']}종목 → 통과 {len(s['pass'])} (탈락 {len(s['fail'])})")
    print("    탈락 단계: " + ", ".join(f"{k} {v}" for k, v in s["funnel"].items() if v))
    st = Counter(r["status"] for r in s["pass"])
    print(f"    통과 상태: 유력 {st.get('유력', 0)} · 가능 {st.get('가능', 0)} · 대기 {st.get('대기', 0)}")
    print("    대기 원인: " + ", ".join(f"{k} {v}" for k, v in s["why"].items() if k != "대기"))

    print("\n[2] 임박도 자료가 있는 종목 수 (등록 전체 기준)")
    print(f"    런웨이(현금 바닥) 계산됨 {sum(r['has_runway'] for r in rows)}/{len(rows)}"
          f" · 상장유지 통지 {sum(r['has_listing'] for r in rows)}/{len(rows)}"
          f" · 앞으로의 일정 있음 {sum(1 for r in rows if r['n_events'])}/{len(rows)}"
          f" · 지난 상장유지 기한 {sum(1 for r in rows if r['past'])}")
    rw = sorted(r["runway"] for r in rows if r["runway"] is not None)  # 흑자·오래된 재무는 숫자가 없음
    info = [r.get("runway_info") or {} for r in rows]
    print(f"    런웨이 자료 내용: 숫자 있음 {len(rw)} · 흑자(소모 없음) {sum(1 for i in info if i.get('profitable'))}"
          f" · 오래된 재무 {sum(1 for i in info if i.get('stale'))} · 추정 현금 소진 {sum(1 for i in info if i.get('exhausted') and not i.get('stale'))}")
    if rw:
        print(f"    런웨이 분포(개월): 최소 {rw[0]:.1f} · 중간 {rw[len(rw) // 2]:.1f} · 최대 {rw[-1]:.1f} · 3개월 이하 {sum(1 for x in rw if x <= 3)}")

    with closing(db.connect()) as conn:
        print("\n[3] 원재료 테이블")
        r = q(conn, "SELECT COUNT(*), SUM(deadline >= ?), MAX(filed) FROM listing_notices", (today,))
        print(f"    상장유지 통지(listing_notices): {r if isinstance(r, str) else f'전체 {r[0][0]} · 기한 안 지남 {r[0][1] or 0} · 최근 접수 {r[0][2]}'}")
        r = q(conn, "SELECT origin, COUNT(*) FROM events WHERE date >= ? GROUP BY origin", (today,))
        print(f"    앞으로의 일정(events): {r if isinstance(r, str) else (', '.join((o or '수동') + ' ' + str(n) for o, n in r) or '없음')}")
        r = q(conn, "SELECT kind, COUNT(*) FROM events WHERE date >= ? GROUP BY kind ORDER BY 2 DESC LIMIT 8", (today,))
        if not isinstance(r, str) and r:
            print("    일정 종류: " + ", ".join(f"{k} {n}" for k, n in r))
        r = q(conn, "SELECT COUNT(*), COUNT(DISTINCT ticker), MAX(filed) FROM fs_deals")
        print(f"    펀드스캔 딜(fs_deals): {r if isinstance(r, str) else f'{r[0][0]}건 · {r[0][1]}종목 · 최근 {r[0][2]}'}")
        r = q(conn, "SELECT COUNT(*), SUM(data LIKE '%\"cash\"%'), MAX(updated) FROM fs_runway")
        print(f"    런웨이 저장소(fs_runway): {r if isinstance(r, str) else f'{r[0][0]}종목 받음 · 현금 자료 있음 {r[0][1] or 0} · 최근 {r[0][2]}'}")
        r = q(conn, "SELECT COUNT(*), MAX(updated) FROM fs_xbrl")
        print(f"    XBRL 재무(fs_xbrl): {r if isinstance(r, str) else f'{r[0][0]}종목 · 최근 갱신 {r[0][1]}'}")
        r = q(conn, "SELECT COUNT(*), MAX(generated_at) FROM reports")
        print(f"    종목 리포트(reports): {r if isinstance(r, str) else f'{r[0][0]}건 · 최근 {r[0][1]}'}")

    print("\n[4] 통과 종목별 이유 (최대 30개)")
    for r in pick30.sort(s["pass"], "유력·임박 순")[:30]:
        print(f"    {r['ticker']:<6} {r['status']} +{r['pct']:.0f}% → {r['target_name']} · {r['why']}")
    print("\n끝. 이 결과를 그대로 복사해 붙여 주세요.")


if __name__ == "__main__":
    main()
