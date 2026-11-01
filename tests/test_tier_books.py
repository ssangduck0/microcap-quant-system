"""🧪 ⭐ 반등형 장부 2개(2026-11-01): 오늘 ⭐ 1·2순위(보류 제외)를 두 장부에 · −20% 장부는 가격 손절 · 장점만 장부는 비상 −50% + 공시 손절(새 조달 서류 다음 거래일 시가 · 병합 7일 전부터) · 익절은 둘 다."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import pandas as pd
import db, papertrade as pt, setup3, secbackfill, watch, piggy

db.init_db(); piggy.ensure_tables(); watch.ensure_tables()
E, D1, D2, D3, D4, D5, TODAY = "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28"
SIG = "2026-10-21"      # 한국 아침 기록 날짜(미국 10/20 종가 신호)

with closing(db.connect()) as conn:
    setup3.ensure_tiers(conn)
    for d_ in secbackfill.DDL:
        conn.execute(d_)
    for t, tr, rsi, px, hold in (("AAA", 1, 18.0, 1.0, None), ("BBB", 2, 23.0, 3.0, "🟢 조용한 장세"), ("CCC", 3, 29.0, 4.0, None),
                                 ("DDD", 2, 24.0, 2.0, None), ("EEE", 1, 19.0, 1.0, None)):
        conn.execute("INSERT INTO s3_tier_signals (date, ticker, price, tier, rsi, note, hold) VALUES (?,?,?,?,?,?,?)", (SIG, t, px, tr, rsi, "x", hold))
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('a1', 'AAA', '424B5', ?, '')", (D2,))       # 보유 중 새 조달 서류
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed, items) VALUES ('a0', 'AAA', '10-Q', ?, '')", (D1,))        # 관계없는 공시
    conn.execute("INSERT INTO events (ticker, date, kind, title, source, origin, created_at) VALUES ('DDD', '2026-10-30', '역분할 시행', '역분할 1:10 시행', 'x', 'secfeed', 'x')")
    conn.commit()
    tg = pt.event_triggers(conn, "AAA", E)
    assert tg == [(D2, True, "새 조달 서류 424B5 2026-10-22")], tg
    assert pt.event_triggers(conn, "DDD", E) == [("2026-10-23", False, "병합 예정 2026-10-30")]
    assert pt.event_triggers(conn, "EEE", E) == []

b = pt.open_tier(E, SIG)
assert b == {"tier": ["AAA", "EEE", "DDD"], "tier_d": ["AAA", "EEE", "DDD"]}, b      # 1순위 먼저 · RSI 낮은 순 · 보류(BBB)·3순위(CCC) 제외
assert pt.open_tier(E, SIG) == {"tier": [], "tier_d": []}                              # 이미 보유 → 다시 안 삼
with closing(db.connect()) as conn:
    rows = {(r["strategy"], r["ticker"]): dict(r) for r in conn.execute("SELECT * FROM pt_trades")}
assert rows[("tier", "AAA")]["sl"] == 20 and rows[("tier_d", "AAA")]["sl"] == 50 and rows[("tier", "AAA")]["tp"] == 30 and rows[("tier_d", "AAA")]["hold"] == 40
assert "⭐ 1순위" in rows[("tier", "AAA")]["note"]


def bars(rows):  # {날짜: (open, high, low, close)}
    idx = pd.to_datetime(list(rows))
    v = list(rows.values())
    return pd.DataFrame({"Open": [x[0] for x in v], "High": [x[1] for x in v], "Low": [x[2] for x in v], "Close": [x[3] for x in v], "Volume": 1e5}, index=idx)


B = {"AAA": bars({E: (1.0, 1.0, 1.0, 1.0), D1: (0.95, 1.0, 0.75, 0.8), D2: (0.8, 0.9, 0.78, 0.88), D3: (0.85, 0.9, 0.8, 0.86), D4: (0.86, 0.9, 0.8, 0.85),
                  D5: (0.85, 0.9, 0.8, 0.85)}),
     "DDD": bars({E: (2.0, 2.0, 2.0, 2.0), D1: (2.0, 2.05, 1.95, 2.0), D2: (2.0, 2.05, 1.95, 2.0), D3: (1.9, 2.0, 1.85, 1.95), D4: (1.95, 2.0, 1.9, 1.95),
                  D5: (1.95, 2.0, 1.9, 1.95)}),
     "EEE": bars({E: (1.0, 1.0, 1.0, 1.0), D1: (1.0, 1.1, 0.95, 1.05), D2: (1.05, 1.35, 1.0, 1.2), D3: (1.2, 1.25, 1.1, 1.2), D4: (1.2, 1.2, 1.1, 1.15),
                  D5: (1.15, 1.2, 1.1, 1.15)})}
n = pt.update(B, today=TODAY)
with closing(db.connect()) as conn:
    got = {(r["strategy"], r["ticker"]): (r["status"], r["exit_day"], round(r["exit"], 4) if r["exit"] is not None else None, r["reason"] or "")
           for r in conn.execute("SELECT strategy, ticker, status, exit_day, exit, reason FROM pt_trades")}
print(got)
assert got[("tier", "AAA")][:3] == ("closed", D1, 0.8) and "손절 −20%" in got[("tier", "AAA")][3]                      # −20% 장부: 가격 손절
assert got[("tier_d", "AAA")][:3] == ("closed", D3, 0.85) and got[("tier_d", "AAA")][3].startswith("공시 손절(새 조달 서류 424B5")   # 장점만: 공시 다음 거래일 시가
assert got[("tier_d", "DDD")][:3] == ("closed", D3, 1.9) and "병합 예정 2026-10-30" in got[("tier_d", "DDD")][3]          # 병합 7일 전부터
assert got[("tier", "DDD")][0] == "open"                                                                            # −20% 장부는 공시를 안 봄
assert got[("tier", "EEE")][:3] == ("closed", D2, 1.3) and got[("tier_d", "EEE")][:3] == ("closed", D2, 1.3)           # 익절은 둘 다
assert n == 5, n
assert "비상 −50%" in pt.STRATEGIES["tier_d"]["name"] and pt.cfg("tier")["on"] and pt.cfg("tier_d")["sl"] == 50
import papertrade_ui
assert "tier" in papertrade_ui.WHEN and "tier_d" in papertrade_ui.WHEN
print("ALL OK")
