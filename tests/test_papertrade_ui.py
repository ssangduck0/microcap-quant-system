import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🧪 가상매매 화면(전략 비교표·전략 고르기·전략별 초기화) + ⚙️ 관리 모드 전략별 규칙 저장 — Streamlit AppTest(인터넷 없음)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import db, config, halts, papertrade as pt
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
with closing(db.connect()) as conn:   # 대시보드는 스캐너 데이터가 하나는 있어야 화면을 그림
    db.upsert_snapshot(conn, {"date": "2026-10-16", "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
config.MANUAL_TICKERS_FILE = os.path.join(tmp, "manual_tickers.txt")
with closing(db.connect()) as conn:
    pt.ensure(conn)
    pt.open_trade(conn, "rank", "2026-10-20", "RK1", 1.0, rank=1, score=80, parts={"acc": True})
    pt.open_trade(conn, "piggy", "2026-10-20", "PG1", 0.5, tp_px=0.65, sl_px=0.475, note="박스")
    conn.execute("UPDATE pt_trades SET status='closed', exit=1.2, exit_day='2026-10-21', reason='익절 +20% (프리장)' WHERE ticker='RK1'")
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "papertrade"            # 옛 주소 → 🏆 검증의 가상매매 탭
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "전략 비교" in html and "#### 🏁 종합 순위" in html and "장부별 결과" in html and "신호별 성과" in html, [x for x in ("전략 비교", "#### 🏁 종합 순위", "장부별 결과", "신호별 성과") if x not in html] + [html[:1500], [e.value for e in at.error], [c.value for c in at.caption][:5]]
cmp_tbl = [d.value for d in at.dataframe if "전략" in d.value.columns][0]
assert list(cmp_tbl["전략"]) == [v["name"] for v in pt.STRATEGIES.values()] and cmp_tbl.set_index("전략").loc["🏁 종합 순위", "청산"] == 1
assert at.radio(key="pt_strat").value == "🏁 종합 순위"
at.radio(key="pt_strat").set_value("🐷 저금통").run(); assert not at.exception
html = "\n".join(m.value for m in at.markdown)
assert "#### 🐷 저금통" in html and "열린 포지션" in html and "신호별 성과" not in html
b_rank, b_piggy = pt.book("rank"), pt.book("piggy")
[b for b in at.button if b.key == "pt_reset"][0].click().run(); assert not at.exception
assert pt.book("rank") == b_rank and pt.book("piggy") != b_piggy                                   # 고른 전략(저금통)만 새 장부
# ⚙️ 관리 모드: 전략별 규칙 저장 → 새 매수부터 적용
os.environ["QUANT_TEST_PAGE"] = "admin"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
at.number_input(key="adm_pt_rank_tp").set_value(10.0); at.number_input(key="adm_pt_close_sl").set_value(7.0); at.toggle(key="adm_pt_pick_on").set_value(False)
[b for b in at.button if b.key == "adm_pt_save"][0].click().run(); assert not at.exception
s = pt.settings(); assert s["rank"]["tp"] == 10.0 and s["close"]["sl"] == 7.0 and s["pick"]["on"] is False and s["rank"]["sl"] == 10.0, s
with closing(db.connect()) as conn:
    assert pt.open_trade(conn, "rank", "2026-10-22", "RK2", 1.0) and pt.open_trade(conn, "pick", "2026-10-22", "PK9", 1.0) is False
    r = dict(conn.execute("SELECT tp, sl FROM pt_trades WHERE ticker='RK2'").fetchone()); assert r["tp"] == 10.0 and r["sl"] == 10.0
    assert dict(conn.execute("SELECT tp FROM pt_trades WHERE ticker='RK1'").fetchone())["tp"] == 20.0     # 지난 거래 규칙은 그대로
assert any("PIGGY_AUTO_SCORE" == k for k in config.SETTINGS) and at.number_input(key="adm_PIGGY_AUTO_SCORE")      # 저금통 자동 담기 기준도 관리 모드에
os.environ.pop("QUANT_TEST_PAGE")
print("ALL OK")
