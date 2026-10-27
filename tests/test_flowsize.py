import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""📊 매매강도: 금액 구간 나누기 · 실시간 체결 → 구간별 분 집계 저장(가짜 체결) · 요약·타임라인 · 카드 화면(AppTest)."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import datetime, timezone
import db, closewatch as cw, tossws, flowsize as fz
db.init_db(); cw.ensure_tables()
assert fz.bucket_of(150_000) == "XL" and fz.bucket_of(99_999) == "L" and fz.bucket_of(10_000) == "L" and fz.bucket_of(5_000) == "M" and fz.bucket_of(999) == "S"
col = tossws.FlowCollector(lambda: "t", flush_s=1)
T0 = datetime(2026, 10, 26, 14, 30, tzinfo=timezone.utc)   # 10/26 ET 10:30
col._on_book("AAA", {"timestamp": T0.isoformat(), "asks": [{"price": "10.00", "volume": "100"}], "bids": [{"price": "9.90", "volume": "100"}]})
col._on_trade("AAA", {"timestamp": T0.isoformat(), "price": "10.00", "volume": "20000"})     # 매수 $200,000 → XL
col._on_trade("AAA", {"timestamp": T0.isoformat(), "price": "9.90", "volume": "2000"})       # 매도 $19,800 → L
col._on_trade("AAA", {"timestamp": T0.replace(minute=31).isoformat(), "price": "10.00", "volume": "300"})   # 매수 $3,000 → M
col._on_trade("AAA", {"timestamp": T0.replace(minute=31).isoformat(), "price": "9.90", "volume": "50"})     # 매도 $495 → S
col._on_trade("AAA", {"timestamp": T0.replace(minute=31).isoformat(), "price": "9.95", "volume": "10"})     # 호가 사이·틱 규칙: 직전 9.90 보다 높음 → 매수 $99.5 → S
col._flush()
with closing(db.connect()) as conn:
    assert fz.days(conn, "aaa") == ["2026-10-26"]
    s = fz.summary(conn, "AAA", "2026-10-26")
    assert abs(s["buy"] - 203_099.5) < 1e-6 and abs(s["sell"] - (19_800 + 495)) < 1e-6 and s["verdict"] == "매수세 우세", s
    assert s["by"]["XL"]["buy_n"] == 1 and s["by"]["L"]["sell_n"] == 1 and s["by"]["M"]["buy_sh"] == 300 and s["by"]["S"]["sell_n"] == 1 and s["by"]["S"]["buy_n"] == 1, s["by"]
    tl = fz.timeline(conn, "AAA", "2026-10-26")
    assert list(tl.index) == ["23:30", "23:31"] and abs(tl["누적 순매수($)"].iloc[-1] - s["net"]) < 1e-6, tl   # KST 23:30
    # close_flow(주식 수) 도 같이 기록됨
    r = conn.execute("SELECT SUM(buy_sh), SUM(sell_sh) FROM close_flow WHERE ticker='AAA'").fetchone(); assert r[0] == 20310 and r[1] == 2050, r
    assert fz.summary(conn, "AAA", "2026-10-27") is None and fz.basic(conn, "AAA", "2026-10-26")["n"] == 5
# 카드 화면
APP = """
import os, sys; sys.path.insert(0, os.environ["QS_ROOT"])
import streamlit as st, flow_ui
flow_ui.card("AAA", key="t")
st.markdown("---")
flow_ui.card("NONE", key="t2")
"""
from streamlit.testing.v1 import AppTest
at = AppTest.from_string(APP, default_timeout=60).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "매수세 우세" in html and "매수 91%" in html, html[:600]
tb = [d.value for d in at.dataframe if "구간" in d.value.columns][0]; assert len(tb) == 4 and tb.iloc[0]["구간"].startswith("XL")
assert any("실시간 체결 기록이 없어요" in c.value for c in at.caption) and [b for b in at.button if b.key.startswith("cp_btn_")]
print("ALL OK")
