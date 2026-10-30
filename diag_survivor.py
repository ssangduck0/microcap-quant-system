"""📉 생존 편향 점검 — 상장폐지·사라진 종목이 통계에서 얼마나 빠져 있는지, 빠진 종목의 성과가 남은 종목과 얼마나 다른지 잰다(읽기만 함).

실행(프로젝트 폴더에서):  python diag_survivor.py
"""
import json
import os
import sys

os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
import logging
try:
    import streamlit.logger as _stl
    _stl.set_log_level("error")
except Exception:  # noqa: BLE001
    pass
logging.getLogger().addFilter(lambda rec: not rec.name.startswith("streamlit"))

from contextlib import closing
from datetime import date, timedelta

import config
config.apply_overrides()
import db


def q(conn, sql, p=()):
    try:
        return conn.execute(sql, p).fetchall()
    except Exception as e:  # noqa: BLE001
        return f"(읽기 실패: {e})"


def stats(conn, tickers: set[str]) -> str:
    """이벤트 연구 사건 중 이 종목들 것: 건수 · D+5 시장 대비 이긴 확률 · 중앙값."""
    if not tickers:
        return "0건"
    try:
        df = db.read_df("SELECT ticker, abn5 FROM ev_labels WHERE abn5 IS NOT NULL")
    except Exception:  # noqa: BLE001  (이벤트 연구를 아직 안 돌린 DB 엔 ev_labels 표가 없음)
        return "0건(이벤트 연구 결과 없음)"
    if df.empty:
        return "0건"
    a, b = df[df["ticker"].isin(tickers)], df[~df["ticker"].isin(tickers)]
    f = lambda x: f"{len(x):,}건 · 이긴 확률 {(x['abn5'] > 0).mean() * 100:.1f}% · 중앙값 {x['abn5'].median():+.1f}%" if len(x) else "0건"  # noqa: E731
    return f"해당 {f(a)}  |  나머지 {f(b)}"


def main() -> None:
    import universe
    print(f"== 생존 편향 점검 · DB {config.DB_PATH}")
    with closing(db.connect()) as conn:
        print("\n[1] 📚 과거 사례(cases) 수집 상태 — 상장폐지 종목 포함 여부")
        r = q(conn, "SELECT status, is_delisted, COUNT(*) FROM case_progress GROUP BY status, is_delisted ORDER BY 2, 1")
        print("    " + (r if isinstance(r, str) else ", ".join(f"{'상폐' if d else '상장'}·{s} {n:,}" for s, d, n in r) or "(없음)"))

        dl = set()
        try:
            p = universe._cache_path("toss:nasdaq:delisted")
            if p.exists():
                dl = set(json.loads(p.read_text(encoding="utf-8")).get("tickers", []))
        except Exception:  # noqa: BLE001
            pass
        print(f"\n[2] 토스 나스닥 상장폐지 목록: {len(dl):,}종목" + ("" if dl else " (캐시 없음 — 아침 갱신 후 생김)"))

        ev_t = {x[0] for x in q(conn, "SELECT DISTINCT ticker FROM ev_labels")} if not isinstance(q(conn, "SELECT 1 FROM ev_labels LIMIT 1"), str) else set()
        hist_t = {x[0] for x in q(conn, "SELECT DISTINCT ticker FROM sec_hist")} if not isinstance(q(conn, "SELECT 1 FROM sec_hist LIMIT 1"), str) else set()
        print(f"\n[3] 🔬 이벤트 연구: 주가 반응이 계산된 종목 {len(ev_t):,} · 공시 이력(sec_hist) 종목 {len(hist_t):,}")
        print(f"    상장폐지 목록과 겹침: 이벤트 연구 {len(ev_t & dl):,}종목 · 공시 이력 {len(hist_t & dl):,}종목")
        print("    상폐 종목 사건 vs 나머지: " + stats(conn, dl))

        mx = q(conn, "SELECT MAX(date) FROM daily_snapshots")
        mx = mx[0][0] if not isinstance(mx, str) and mx and mx[0][0] else None
        gone = set()
        if mx:
            cut = (date.fromisoformat(mx) - timedelta(days=30)).isoformat()
            gone = {x[0] for x in q(conn, "SELECT ticker FROM daily_snapshots GROUP BY ticker HAVING MAX(date) < ?", (cut,))}
            seen = q(conn, "SELECT COUNT(DISTINCT ticker) FROM daily_snapshots")[0][0]
            print(f"\n[4] 스캐너가 봤는데 30일 넘게 안 보이는 종목: {len(gone):,} / {seen:,} (상폐·티커 변경·조건 밖으로 나감)")
            print("    그 종목들의 사건 vs 나머지: " + stats(conn, gone))

        print("\n[5] 사건 뒤 데이터가 끊긴 경우(D+5 전에 주가가 사라짐 = 라벨 못 붙음)")
        r = q(conn, "SELECT COUNT(*) FROM ev_docs d LEFT JOIN ev_labels l ON l.accession=d.accession WHERE l.accession IS NULL AND d.ok=1")
        tot = q(conn, "SELECT COUNT(*) FROM ev_docs WHERE ok=1")
        if not isinstance(r, str) and not isinstance(tot, str):
            print(f"    본문은 받았는데 라벨이 없는 공시 {r[0][0]:,} / {tot[0][0]:,} — 이 중 일부는 상폐로 주가가 끊긴 것")
            r2 = q(conn, "SELECT COUNT(*) FROM ev_docs d LEFT JOIN ev_labels l ON l.accession=d.accession WHERE l.accession IS NULL AND d.ok=1 AND d.ticker IN (%s)"
                   % ",".join("?" * len(dl)), tuple(dl)) if dl else [[0]]
            if not isinstance(r2, str):
                print(f"    그중 상장폐지 목록 종목: {r2[0][0]:,}")
        print("\n[6] 라벨 시도 기록(수집기가 돌면서 쌓임) — 주가 자료가 사라진 회사 = 상폐·티커 변경 추정")
        r = q(conn, "SELECT status, COUNT(*), SUM(n_pending) FROM ev_label_try GROUP BY status")
        print("    " + (r if isinstance(r, str) else (", ".join(f"{s_} {n:,}종목(남은 공시 {p_ or 0:,})" for s_, n, p_ in r) or "아직 없음 — 수집기가 한 번 돌면 생김")))
        nod = [] if isinstance(r, str) else [x[0] for x in q(conn, "SELECT ticker FROM ev_label_try WHERE status='no_data' ORDER BY n_pending DESC LIMIT 5")]
    probe = (nod or sorted(dl))[:5]
    if probe and getattr(config, "TOSS_CLIENT_ID", ""):
        print(f"\n[7] 토스에 그 회사들의 일봉이 남아 있나(예시 {len(probe)}개)")
        try:
            import toss
            tc = toss.TossClient(config.TOSS_CLIENT_ID, config.TOSS_CLIENT_SECRET, config.TOSS_BASE_URL)
            for t in probe:
                try:
                    c = tc.daily_candles(t, 5)
                    print(f"    {t}: {'있음 ' + str(len(c)) + '개' if c else '없음'}")
                except Exception as e:  # noqa: BLE001
                    print(f"    {t}: 오류 {type(e).__name__} {str(e)[:60]}")
        except Exception as e:  # noqa: BLE001
            print(f"    토스 연결 실패: {type(e).__name__}")
    try:
        import pricevault as pv
        sm = pv.summary()
        print(f"\n[8] 🗄 주가 보관소: 보관 {sm['tickers']:,}종목 · {sm['rows']:,}줄 ({sm['first']} ~ {sm['last']}) · 오늘 대상 {sm['watch']:,} · 끊김 {sm['gone']:,}")
        for t, g in list(pv.gone().items())[:10]:
            print(f"    끊김 {t}: 마지막 {g['last_date']} ${g['last_close']} · {g['reason']}")
    except Exception as e:  # noqa: BLE001
        print(f"\n[8] 주가 보관소 읽기 실패: {e}")
    print("\n끝. 이 결과를 그대로 복사해 붙여 주세요.")


if __name__ == "__main__":
    main()
