"""📨 보낸 알림 기록(2026-10-28): notify.send_telegram 이 모든 알림을 alert_log 에 남김(종류·종목 자동 분류, 실패도 기록) · recent/counts · 🔔 공시 알림 화면의 '📨 보낸 알림' 탭."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"] = "1"; os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
import db, config, notify, halts
db.init_db(); halts.fetch = lambda *a, **k: []

# 분류: 이모지 → 종류, 첫 줄의 대문자 → 종목(KST·ET 같은 약어는 제외, $ 붙은 한 글자도 종목)
assert notify.classify("📐 BRAI 허리 눌림목 ✅ $2.10") == ("📐 차트", "BRAI")
assert notify.classify("🔔 SHFS 8-K · 호재\n내용") == ("🔔 공시", "SHFS")
assert notify.classify("⏰ 애프터 매도 마감 15:50 KST 입니다.") == ("⏰ 시간", None)
assert notify.classify("🌙 F 애프터 진입 구간 $1.00")[1] is None and notify.classify("🌙 $F 애프터 진입")[1] == "F"
assert notify.classify("그냥 글") == ("기타", None) and notify.classify("")[0] == "기타"

# 보내기: 토큰 있음 + 가짜 전송(성공·실패) · 토큰 없음 → 전부 기록, ok 만 다름
config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID = "t", "c"
calls = []
class R:
    def __init__(self, fail=False): self.fail = fail
    def raise_for_status(self):
        if self.fail: raise RuntimeError("boom")
notify.requests.post = lambda url, json=None, timeout=None: (calls.append(json), R())[1]
assert notify.send_telegram("📐 BRAI 허리 눌림목\n현재 $2.10") is True
assert notify.send_telegram("🔔 SHFS 8-K · 호재\n3.02 사모") is True
assert notify.send_telegram("🩳 AZTR 공매 눌림 2단계\n현재 $1.00") is True
notify.requests.post = lambda url, json=None, timeout=None: R(fail=True)
assert notify.send_telegram("📈 WORX 성공 (2026-10-27)") is False                      # 전송 실패도 기록(❌)
config.TELEGRAM_TOKEN = ""
assert notify.send_telegram("✅ 테스트") is False and len(calls) == 3                      # 토큰 없음: 호출 없이 기록만
with closing(db.connect()) as conn:
    df = notify.recent(conn, 7); print(df)
    assert list(df["종류"]) == ["✅ 테스트", "📈 판정", "🩳 공매", "🔔 공시", "📐 차트"] and list(df["보냄"]) == ["❌", "❌", "✅", "✅", "✅"]   # 최신순
    assert list(df["종목"]) == ["", "WORX", "AZTR", "SHFS", "BRAI"] and " · " in df.iloc[-1]["내용"] and "현재 $2.10" in df.iloc[-1]["내용"]
    assert len(notify.recent(conn, 7, kind="🔔 공시")) == 1 and len(notify.recent(conn, 7, ticker="brai")) == 1 and len(notify.recent(conn, 7, limit=2)) == 2
    ct = notify.counts(conn, 7); assert ct.shape[0] == 1 and ct.iloc[0].sum() == 5 and ct.iloc[0]["📐 차트"] == 1
    assert df.iloc[0]["시각(KST)"].count(":") == 1 and len(df.iloc[0]["날짜"]) == 10
    conn.execute("DELETE FROM alert_log"); conn.commit()
    assert notify.recent(conn, 7).empty and notify.counts(conn, 7).empty

# 화면: 🔔 공시 알림 → 📨 보낸 알림 탭(기록 있을 때 표·카드, 없을 때 안내)
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = os.path.join(os.environ["QS_ROOT"], "dashboard.py")
os.environ["QUANT_TEST_PAGE"] = "alerts"
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
assert "📨 보낸 알림" in [x.label for x in at.tabs] and any("아직 기록된 알림이 없어요" in i.value for i in at.info)
config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID = "t", "c"; notify.requests.post = lambda url, json=None, timeout=None: R()
notify.send_telegram("📐 BRAI 허리 눌림목\n현재 $2.10"); notify.send_telegram("🔔 SHFS 8-K · 호재")
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception, [e.value for e in at.exception]
html = "\n".join(m.value for m in at.markdown)
assert "📨 보낸 알림" in [h.value for h in at.subheader] and "최근 7일" in html and "2건" in html
assert any("내용" in list(d.value.columns) and "BRAI" in list(d.value["종목"]) for d in at.dataframe)
os.environ.pop("QUANT_TEST_PAGE"); os.environ.pop("QUANT_TEST_ALL_PAGES"); print("ALL OK")
