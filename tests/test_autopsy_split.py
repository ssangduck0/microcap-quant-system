import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🔍 부검 병합일 가짜 펌핑(2026-10-31): 야후가 병합을 늦게 반영해 병합 당일 봉만 새 단위면 WHLR(1:6) +553% 가 '놓친 펌핑' 으로 잡혔음.
알려진 병합(야후 rs_events · SEC 🗓 역분할 시행 · 🔁 리셋 사이클 설정) / 비율 모르는 '주식 병합' 공시 + 정수배 시가 → 전날 종가 ×N 로 다시 재기 · 지난 기록 정정."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import pandas as pd
import db, autopsy, rsplit, resetcycle, secfeed, watch, mover, chartview as cv, chartex, exthilo, news, papertrade as pt, scoreboard as sb, piggy

db.init_db(); piggy.ensure_tables()
T = date.today()
days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=pd.Timestamp(T), periods=12)]
D, P, E, EP = days[-1], days[-2], days[-3], days[-4]
dd = lambda base, n: (date.fromisoformat(base) + timedelta(days=n)).isoformat()


def put(conn, t, rows):
    """rows = [(날짜, 시가, 고가, 종가, 거래량)]"""
    idx = pd.to_datetime([r[0] for r in rows])
    db.upsert_daily_prices(conn, t, pd.DataFrame({"Open": [r[1] for r in rows], "High": [r[2] for r in rows], "Low": [min(r[1], r[3]) * 0.98 for r in rows],
                                                  "Close": [r[3] for r in rows], "Volume": [r[4] for r in rows]}, index=idx))


with closing(db.connect()) as conn:
    autopsy.ensure(conn); __import__("review").ensure(conn); cv.ensure(conn); chartex.ensure(conn); conn.execute(sb.DDL); exthilo.ensure(conn)
    secfeed.ensure_tables(conn); conn.execute(news.DDL); pt.ensure(conn); rsplit.ensure_tables(conn); resetcycle.ensure(conn); watch.ensure_tables(conn); mover.ensure(conn)
    V = 1e6
    put(conn, "SPL", [(P, .25, .26, .24, V), (D, 1.40, 1.62, 1.54, V)])        # 야후 1:6(rs_events) · 봉은 환산 전 → 실제 +7% → 뺌
    put(conn, "SPR", [(P, .70, .72, .68, V), (D, 2.72, 2.74, 2.40, V)])        # SEC 1:2 · 환산해도 +76% → 진짜 펌핑(등락률 고침)
    put(conn, "GAP", [(P, .80, .82, .80, V), (D, .84, 1.76, 1.61, V)])         # SEC 1:2(다음 날) 인데 시가가 그대로 = 이미 환산된 자료 → +100% 그대로
    put(conn, "TAG", [(P, .21, .22, .206, V), (D, 2.00, 2.16, 1.98, V)])       # 비율 모르는 '주식 병합' 공시 + 시가 ×9.7 ≈ 10 → 뺌
    put(conn, "TG2", [(P, 1.0, 1.0, 1.0, V), (D, 2.0, 2.2, 2.1, V)])           # 같은 공시라도 시가 ×2 는 정수배 의심 문턱(×4) 아래 → 진짜 펌핑
    put(conn, "RCX", [(P, .25, .26, .24, V), (D, 1.40, 1.62, 1.54, V)])        # 🔁 리셋 사이클 설정의 병합(1:6) → 뺌
    put(conn, "DONE", [(P, 1.0, 1.0, 1.0, V), (D, 5.0, 5.3, 5.2, V)])          # 병합 공시는 있었지만 병합은 30일 전에 끝남 → ×5 갭도 진짜 펌핑
    put(conn, "UNK", [(P, .10, .10, .10, V), (D, .50, .53, .52, V)])           # 🗓 '역분할 시행(비율 미확인)' + 시가 ×5 → 뺌
    put(conn, "PLAIN", [(P, 1.0, 1.0, 1.0, V), (D, 1.0, 1.5, 1.45, V)])        # 병합과 무관한 보통 펌핑
    put(conn, "TSS", [(P, 1.37, 1.4, 1.31, V), (D, 1.21, 1.25, 1.10, V)])      # 병합 공시는 있지만 장 마감 뒤 급등(토스 순위 +44%, NCPL 10/28) → 토스 순위로 그대로 잡음
    conn.execute("INSERT INTO rs_events VALUES ('SPL', ?, ?, 1.54)", (D, 1 / 6))
    conn.execute("INSERT INTO rs_events VALUES ('DONE', ?, 0.2, 1.0)", (dd(D, -30),))
    for t, d, title in (("SPR", D, "역분할 1:2 시행"), ("GAP", dd(D, 1), "역분할 1:2 시행"), ("UNK", D, "역분할 시행(비율 미확인)")):
        conn.execute("INSERT INTO events (ticker, date, kind, title, source, origin, created_at) VALUES (?,?,'역분할 시행',?,'x','secfeed','x')", (t, d, title))
    conn.execute("INSERT OR REPLACE INTO reset_config (ticker, label, split_date, split_ratio) VALUES ('RCX', 'x', ?, ?)", (D, 1 / 6))
    for i, t in enumerate(("TAG", "TG2", "DONE", "TSS")):
        conn.execute("INSERT INTO sec_feed (accession, ticker, cik, form, company, filed, updated, items, url, tags, score, sentiment, enriched, created_at) "
                     "VALUES (?,?,?,'6-K','c',?,?,'','','[\"주식 병합\"]',0,'중립',1,'x')", (f"a{i}", t, 100 + i, dd(D, -3), dd(D, -3)))
    conn.execute("INSERT INTO toss_rank (date, kind, rank, ticker, price, change_pct, session, at) VALUES (?, 'up', 1, 'SPL', 1.54, 541.0, 'reg', 'x')", (D,))   # 같은 착시 → 다시 넣지 않음
    conn.execute("INSERT INTO toss_rank (date, kind, rank, ticker, price, change_pct, session, at) VALUES (?, 'up', 2, 'TSS', 1.58, 43.6, 'post', 'x')", (D,))
    conn.commit()

    known, suspect = autopsy.known_splits(conn, D)
    known.pop("WHLR", None)   # 리셋 사이클 기본값(WHLR 10/30 1:6) — 날짜에 따라 창 안에 들어옴
    assert known == {"SPL": 6.0, "SPR": 2.0, "GAP": 2.0, "RCX": 6.0} and suspect == {"TAG", "TG2", "UNK", "TSS"}, (known, suspect)   # DONE 은 병합이 이미 끝나 의심 아님
    assert autopsy.split_factor(1.40, 1.54, .24, 6.0, False) == 6.0 and autopsy.split_factor(.84, 1.61, .80, 2.0, False) is None
    assert autopsy.split_factor(2.0, 1.98, .206, None, True) == 10.0 and autopsy.split_factor(2.0, 2.1, 1.0, None, True) is None and autopsy.split_factor(2.0, 1.98, .206, None, False) is None
    skipped = []
    pumps = {p["ticker"]: p for p in autopsy.find_pumps(conn, D, tradable_only=False, skipped=skipped)}
    assert set(pumps) == {"SPR", "GAP", "TG2", "DONE", "PLAIN", "TSS"} and pumps["TSS"]["session"] == "toss", sorted(pumps)
    assert dict(skipped) == {"SPL": 6.0, "TAG": 10.0, "RCX": 6.0, "UNK": 5.0}, skipped
    assert abs(pumps["SPR"]["pump_pct"] - 76.5) < 1 and pumps["SPR"]["split"] == 2.0 and abs(pumps["SPR"]["prev_close"] - 1.36) < 1e-6
    assert abs(pumps["GAP"]["pump_pct"] - 101) < 1 and "split" not in pumps["GAP"] and "split" not in pumps["PLAIN"]

    logs = []
    res = autopsy.run(conn, D, out=logs.append)
    assert res["pumps"] == 6 and {t for t, _ in res["split_skipped"]} == {"SPL", "TAG", "RCX", "UNK"}, res
    assert "병합 봉이라 뺌 " in logs[0] and "SPL(1:6)" in logs[0] and "TAG(1:10)" in logs[0], logs[0]
    assert conn.execute("SELECT COUNT(*) FROM pump_autopsy WHERE ticker IN ('SPL','TAG','RCX','UNK')").fetchone()[0] == 0

    # 지난 기록 정정: 병합을 몰랐던 날 기록된 가짜 펌핑(LATE) · 배수 반영해 등락률만 고칠 것(UPD) · 병합과 무관한 기록(KEEP, 일봉 없음)은 그대로
    put(conn, "LATE", [(EP, .3, .3, .3, V), (E, 3.0, 3.2, 3.1, V)])
    put(conn, "UPD", [(EP, .5, .5, .5, V), (E, 1.6, 1.7, 1.6, V)])
    for t, pp, pc in (("LATE", 933.0, .3), ("UPD", 220.0, .5), ("KEEP", 80.0, 1.0)):
        conn.execute("INSERT INTO pump_autopsy (date, ticker, pump_pct, hi_pct, session, prev_close, volume, caught, caught_by, held, features, catalyst, created_at) "
                     "VALUES (?,?,?,?,'pre',?,1e6,0,'[]','[]','{}','',  'x')", (E, t, pp, pp, pc))
    conn.commit()
    assert autopsy.recheck_splits(conn, today=D) == 0                                         # 병합이 아직 안 알려짐 → 아무것도 안 바꿈
    conn.execute("INSERT INTO rs_events VALUES ('LATE', ?, 0.1, 3.1)", (E,))                 # 며칠 뒤 야후가 병합을 알려 줌
    conn.execute("INSERT INTO rs_events VALUES ('UPD', ?, 0.5, 1.6)", (E,))
    conn.commit()
    assert autopsy.recheck_splits(conn, today=D) == 2
    left = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT ticker, pump_pct, prev_close FROM pump_autopsy WHERE date=?", (E,))}
    assert "LATE" not in left and abs(left["UPD"][0] - 60) < 1e-6 and abs(left["UPD"][1] - 1.0) < 1e-9 and left["KEEP"] == (80.0, 1.0), left
    assert autopsy.recheck_splits(conn, today=D) == 0                                         # 두 번째는 바뀔 것 없음
    # 야후가 봉까지 고친 뒤(병합 전 봉 ×N): 점프가 없어져도 결과는 같음(토스 등락률은 실제로는 병합을 반영 — WHLR 10/30 은 토스 순위에 없었음)
    conn.execute("DELETE FROM toss_rank WHERE ticker='SPL'")
    put(conn, "SPL", [(P, 1.50, 1.56, 1.44, V / 6)])
    conn.commit()
    assert "SPL" not in {p["ticker"] for p in autopsy.find_pumps(conn, D, tradable_only=False)}
    assert autopsy.recheck_splits(conn, today=D) == 0 and conn.execute("SELECT COUNT(*) FROM pump_autopsy WHERE ticker='TSS'").fetchone()[0] == 1   # 토스로 잡은 진짜 펌핑은 정정에서도 그대로
print("ALL OK")
