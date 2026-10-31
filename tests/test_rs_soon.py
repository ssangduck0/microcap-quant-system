"""🚫 병합 예정 보류(2026-11-01): 병합 시행 7일 안 종목 → 저금통 자동 담기 제외 · 저금통 알림 '매수 보류' · 가상매매 진입 안 함 · 실매매 금지 목록 · 📄 서랍 경고 칩."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_PAGE", None); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, halts, watch, rsplit, piggy, papertrade, broker, drawer, config

db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables(); piggy.ensure_tables()
T = date.today()
D = lambda n: (T + timedelta(days=n)).isoformat()
with closing(db.connect()) as conn:
    for t, n in (("AAA", 3), ("BBB", 10), ("CCC", -2), ("DDD", 0)):
        conn.execute("INSERT INTO events (ticker, date, kind, title, source, origin, created_at) VALUES (?,?,?,?,?,?,?)", (t, D(n), "역분할 시행", "역분할 1:20 시행", "8-K", "secfeed", db.utcnow_iso()))
    conn.commit()
    a = rsplit.soon(conn, "aaa")
    assert a == {"date": D(3), "title": "역분할 1:20 시행", "d": 3}, a
    assert rsplit.soon(conn, "BBB") is None and rsplit.soon(conn, "CCC") is None and rsplit.soon(conn, "DDD")["d"] == 0 and rsplit.soon(conn, "ZZZ") is None
    assert rsplit.soon(conn, "BBB", days=10)["d"] == 10

# 🐷 저금통 기준: 다른 조건이 다 맞아도 병합 예정이면 탈락
m = lambda t: {"ticker": t, "price": 0.5, "score": 70, "bounces": 3, "width_pct": 30, "dollar_vol": 50000, "recent_break": False}
assert piggy.rule_ok(m("BBB"), None, 1350.0) is True
assert piggy.rule_ok(m("AAA"), None, 1350.0) is False and piggy.rule_ok(m("DDD"), None, 1350.0) is False

# 🐷 알림: 🟢 저점 구간이어도 병합 예정이면 '매수 보류' · 성과 공표 기록 안 함
piggy.add("AAA", "기타", box_low=0.40, box_high=0.80)
piggy.add("BBB", "기타", box_low=0.40, box_high=0.80)
msgs = piggy.alerts({"AAA": 0.42, "BBB": 0.42})
ma = next(x for x in msgs if "AAA" in x); mb = next(x for x in msgs if "BBB" in x)
assert "매수 보류 — 병합 예정" in ma and f"D-3" in ma and "매수 검토" in mb, msgs
with closing(db.connect()) as conn:
    ev = {r[0] for r in conn.execute("SELECT ticker FROM piggy_events")}
assert ev == {"BBB"}, ev

# 🧪 가상매매: 어떤 전략도 병합 예정 종목은 사지 않음
with closing(db.connect()) as conn:
    assert papertrade.open_trade(conn, "rank", T.isoformat(), "AAA", 1.0) is False
    assert papertrade.open_trade(conn, "rank", T.isoformat(), "BBB", 1.0) is True
    conn.commit()
    # 💵 실매매 금지 목록
    broker.ensure(conn)
    config.LIVE_STRATEGIES = "rank"
    ok, why = broker.can_buy(conn, "rank", "AAA", 1.0, 1)
    assert ok is False and why.startswith("병합 예정 " + D(3)), why
    ok2, why2 = broker.can_buy(conn, "rank", "BBB", 1.0, 1)
    assert "병합" not in why2, why2
    ok3, why3 = broker.can_buy(conn, "probe", "AAA", 1.0, 1)
    assert "병합" not in why3, why3                                                  # 연결 시험(probe)은 막지 않음
    assert drawer.headline(conn, "AAA")["rs_soon"]["d"] == 3 and drawer.headline(conn, "BBB")["rs_soon"] is None

# 📄 서랍: 경고 칩
from streamlit.testing.v1 import AppTest
app = os.path.join(tmp, "rs_app.py")
with open(app, "w", encoding="utf-8") as f:
    f.write(f"import sys; sys.path.insert(0, {os.environ['QS_ROOT']!r})\nimport ui_kit, report_dialog\nui_kit.inject()\nreport_dialog.render('AAA')\n")
at = AppTest.from_file(app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
html = "\n".join(x.value for x in at.markdown)
assert "🚫 병합 예정" in html and "매수 보류" in html, html[:600]
print("ALL OK")
