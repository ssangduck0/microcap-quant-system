import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, halts
db.init_db(); halts.fetch = lambda *a, **k: []
now = db.utcnow_iso()
def snap(d, t, **kw):
    r = {"date": d, "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -40.0,
         "day_change_pct": -15.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
         "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0}
    r.update(kw); return r
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, snap("2026-10-14", "GUTS", win_score=61.0, win_p=0.31))
    db.upsert_snapshot(conn, snap("2026-10-15", "GUTS", win_score=72.0, win_p=0.42))
    db.upsert_snapshot(conn, snap("2026-10-16", "GUTS"))                                  # 오늘 프리마켓: 점수 없음
    db.upsert_snapshot(conn, snap("2026-10-16", "NEWX"))                                  # 이전 점수도 없음
    db.upsert_snapshot(conn, snap("2026-10-16", "LIVE", win_score=80.0, win_p=0.5))       # 오늘 정규장 점수 있음
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
t = [d.value for d in at.dataframe if "점수 기준" in d.value.columns][0].set_index("티커"); print(t[["승률 점수", "예상 성공확률(%)", "점수 기준"]].to_string())
assert t.loc["GUTS", "승률 점수"] == 72.0 and t.loc["GUTS", "점수 기준"] == "전 거래일 10-15" and abs(t.loc["GUTS", "예상 성공확률(%)"] - 42.0) < 1e-9
assert t.loc["LIVE", "점수 기준"] == "오늘 정규장" and t.loc["NEWX", "점수 기준"] == "" and str(t.loc["NEWX", "승률 점수"]) in ("nan", "None")
# 비밀번호(선택)
os.environ["DASH_PASSWORD"] = "pw1234"
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=180).run()
assert not [d for d in at.dataframe] and at.text_input(key="_pw_in")
at.text_input(key="_pw_in").set_value("wrong").run(); assert any("비밀번호가 다릅니다" in e.value for e in at.error)
at.text_input(key="_pw_in").set_value("pw1234").run(); assert not at.exception and [d for d in at.dataframe]
os.environ.pop("DASH_PASSWORD")
print("ALL OK")
