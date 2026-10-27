"""📒 실제 매매 일지(2026-10-28): FIFO 손익 · 신호별 성적 · 가상매매 비교 · 🏆 검증 탭 화면 — 인터넷 없이."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, journal, papertrade, halts
db.init_db(); halts.fetch = lambda *a, **k: []
T = date.today(); d = lambda n: (T - timedelta(days=n)).isoformat()

with closing(db.connect()) as conn:
    assert journal.rows(conn).empty and journal.ledger(conn)["summary"]["n_trades"] == 0 and journal.by_signal(pd.DataFrame()).empty and journal.paper_compare(conn).empty
    # BRAI: 100주 @2 (📐) · 50주 @3 (직접) · 120주 @4 매도 → FIFO: 100@2 → +200(+100%) · 20@3 → +20(+33%) · 남은 30@3 보유
    journal.add(conn, "brai", "매수", d(27), 2.0, 100, "📐 허리 눌림목")
    journal.add(conn, "BRAI", "매수", d(23), 3.0, 50, "직접 판단")
    journal.add(conn, "BRAI", "매도", d(18), 4.0, 120)
    journal.add(conn, "AZTR", "매수", d(5), 1.0, 10, "📐 허리 눌림목")          # 보유만
    journal.add(conn, "LOST", "매도", d(2), 5.0, 3)                               # 매수 기록 없이 판 것
    for bad in (("", "매수", d(1), 1, 1), ("X", "보유", d(1), 1, 1), ("X", "매수", d(1), 0, 1), ("X", "매수", d(1), 1, 0)):
        try:
            journal.add(conn, *bad); raise AssertionError(bad)
        except ValueError:
            pass
    idx = pd.bdate_range(end=pd.Timestamp(T), periods=30)
    for t, px in (("BRAI", 4.5), ("AZTR", 1.5)):
        c = np.full(30, px)
        db.upsert_daily_prices(conn, t, pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": np.full(30, 1e5)}, index=idx))
    conn.commit()
    L = journal.ledger(conn); s = L["summary"]; print(s); print(L["closed"]); print(L["open"])
    cl = L["closed"]; assert len(cl) == 3 and list(cl["종목"]) == ["BRAI", "BRAI", "LOST"]
    assert abs(cl.iloc[0]["손익($)"] - 200) < 1e-9 and abs(cl.iloc[0]["손익(%)"] - 100) < 1e-9 and cl.iloc[0]["보유일"] == 9 and cl.iloc[0]["근거 신호"] == "📐 허리 눌림목"
    assert abs(cl.iloc[1]["손익($)"] - 20) < 1e-9 and abs(cl.iloc[1]["수량"] - 20) < 1e-9 and cl.iloc[1]["근거 신호"] == "직접 판단"
    assert cl.iloc[2]["근거 신호"] == "(매수 기록 없음)" and cl.iloc[2]["손익($)"] is None or pd.isna(cl.iloc[2]["손익($)"])
    op = L["open"]; assert len(op) == 2 and list(op["종목"]) == ["AZTR", "BRAI"]
    br = op[op["종목"] == "BRAI"].iloc[0]; assert abs(br["수량"] - 30) < 1e-9 and abs(br["현재가($)"] - 4.5) < 1e-9 and abs(br["평가손익($)"] - 45) < 1e-9 and abs(br["평가손익(%)"] - 50) < 1e-6
    assert s["n_trades"] == 5 and s["n_closed"] == 2 and s["n_open"] == 2 and abs(s["realized"] - 220) < 1e-9 and s["win_rate"] == 100 and abs(s["unrealized"] - 50) < 1e-9
    bs = journal.by_signal(cl).set_index("근거 신호"); print(bs)
    assert bs.loc["📐 허리 눌림목", "건수"] == 1 and abs(bs.loc["📐 허리 눌림목", "합계 손익($)"] - 200) < 1e-9 and bs.loc["직접 판단", "승률(%)"] == 100 and list(bs.index) == ["📐 허리 눌림목", "직접 판단"]
    # 🧪 가상매매 비교: BRAI 는 가상매매도 하루 뒤 샀고 익절 · AZTR 은 없음
    papertrade.ensure(conn)
    conn.execute("INSERT INTO pt_trades (book, day, ticker, rank, score, parts, entry, qty, exit_day, exit, reason, status, strategy) VALUES ('paper', ?, 'BRAI', 1, 50, '{}', 2.1, 100, ?, 2.4, '익절 +14%', '마감', 'master')", (d(26), d(22)))
    conn.commit()
    cp = journal.paper_compare(conn).set_index("종목"); print(cp)
    assert cp.loc["BRAI", "가상매매"].iloc[0] == "있음" if isinstance(cp.loc["BRAI", "가상매매"], pd.Series) else cp.loc["BRAI", "가상매매"] == "있음"
    first = cp.loc["BRAI"].iloc[0] if isinstance(cp.loc["BRAI"], pd.DataFrame) else cp.loc["BRAI"]
    assert first["가상 전략"] == "master" and "+14.3%" in first["가상 결과"] and cp.loc["AZTR", "가상매매"] == "없음"
    journal.delete(conn, int(journal.rows(conn).iloc[-1]["id"])); assert len(journal.rows(conn)) == 4      # LOST 매도 삭제
    assert journal.signal_options()[0] == "직접 판단" and len(journal.signal_options()) > 5

# 화면: 🏆 검증 → 📒 매매 일지 탭
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "score"
at = AppTest.from_file(APP, default_timeout=180); at.query_params["tab"] = "journal"; at.run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "📒 실제 매매 일지" in [h.value for h in at.subheader] and "실현 손익" in html and "+220.00" in html and "근거 신호별 실전 성적" in html and "🧪 가상매매와 비교" in html
assert any("평가손익($)" in list(d.value.columns) for d in at.dataframe) and any("가상 결과" in list(d.value.columns) for d in at.dataframe)
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
