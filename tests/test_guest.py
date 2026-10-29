import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
tmp = tempfile.mkdtemp(); os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"; os.environ["DASH_PASSWORD"] = "ownerpass123"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, halts, access, watch, piggy
db.init_db(); halts.fetch = lambda *a, **k: []; watch.ensure_tables(); piggy.ensure_tables()
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": date.today().isoformat(), "ticker": "MINE", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9,
        "drawdown_pct": -40.0, "day_change_pct": -5.0, "volume_mult": 2.0, "buy_pressure": 55.0, "float_shares": 3e6, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    _d1, _d2 = (date.today() - timedelta(days=1)).isoformat(), (date.today() - timedelta(days=2)).isoformat()   # 방문객 전일 종가(A안) 검증용 야후 일봉
    conn.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)", [("MINE", _d2, 0.5, 0.6, 0.4, 0.5, 1000.0), ("MINE", _d1, 0.8, 0.9, 0.7, 0.8, 1000.0)])
    conn.commit()
watch.add("MINE", "보유"); piggy.add("PIGX", "기타")
db.set_meta("tunnel_url", "https://abc.trycloudflare.com")
tok = access.create("스터디 민수", 24)
assert access.check(tok)["name"] == "스터디 민수" and access.check("wrong") is None and access.link("https://abc.trycloudflare.com/", tok) == f"https://abc.trycloudflare.com/?guest={tok}"
import requests as _rq
def _fake_get(u, timeout=6, **kw):
    class R: status_code = 200
    return R()
_rq.get = _fake_get                                                                                 # 방문객 주소가 살아 있다고 가정
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
# 링크 없이: 비밀번호 화면
at = AppTest.from_file(APP, default_timeout=180).run(); assert at.text_input(key="_pw_in") and not [l for l in at.get("page_link")]
# 방문객 링크: 비밀번호 없이 열림 · 개인 화면 없음 · 기본 화면 종합 순위
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = tok; at.run(); (lambda b: b and b[0].click().run())([x for x in at.button if x.key == "_guest_agree"]); assert not at.exception, [e.value for e in at.exception]
labels = [l.label for l in at.get("page_link")]; print(len(labels))
assert not any(x in labels for x in ("관리 모드", "워치리스트", "저금통", "노트", "일정", "급상승/급하락", "애프터 스캘핑")) and "종합 순위" in labels   # 급상승·애프터 = 토스 자료 화면(2026-10-29 B안)
assert any("방문객 모드" in i.value and "스터디 민수" in i.value for i in at.info)
assert not any("trycloudflare" in m.value for m in at.markdown)                                   # 휴대폰 주소 숨김
assert access.all_links().iloc[0]["visits"] == 1
assert watch.scanner_priority() == ["MINE"]                                                        # 화면 밖(스캐너)은 그대로
# 숨긴 화면을 직접 지정해도 안 그림
os.environ["QUANT_TEST_PAGE"] = "admin"
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = tok; at.run(); (lambda b: b and b[0].click().run())([x for x in at.button if x.key == "_guest_agree"]); assert not at.exception
assert not any("관리 모드" in m.value for m in at.markdown if "qk-title" in m.value) and not [b for b in at.button if b.key == "adm_save"]
os.environ["QUANT_TEST_PAGE"] = "snap"
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = tok; at.run(); (lambda b: b and b[0].click().run())([x for x in at.button if x.key == "_guest_agree"]); assert not at.exception
snap = [d.value for d in at.dataframe if "퀀트점수" in d.value.columns][0]; assert (snap["워치"].fillna("") == "").all()   # ⭐ 표시 없음
import guestpx
_exp = guestpx.one("MINE")   # 토스 데이터 정책 A안: 방문객은 전일 종가(야후 일봉) · 당일 값으로 계산한 열 없음 · 스냅샷 price 1.0 은 안 보임
assert "전일 종가($)" in snap.columns and "전일 등락(%)" in snap.columns and "종가 기준일" in snap.columns and "현재가($)" not in snap.columns and not any(c in snap.columns for c in guestpx.HIDE_COLS), list(snap.columns)
assert _exp and float(snap["전일 종가($)"].iloc[0]) == _exp["close"] and _exp["close"] in (0.8, 0.5) and any("전일 종가" in c.value for c in at.caption), (_exp, snap["전일 종가($)"].tolist())
os.environ.pop("QUANT_TEST_PAGE")
# 취소 · 만료
access.revoke(tok)
at = AppTest.from_file(APP, default_timeout=180); at.query_params["guest"] = tok; at.run(); (lambda b: b and b[0].click().run())([x for x in at.button if x.key == "_guest_agree"]); assert any("만료됐거나 취소" in e.value for e in at.error)
t2 = access.create("짧게", 1)
with closing(db.connect()) as conn:
    conn.execute("UPDATE guest_tokens SET expires_at=? WHERE token=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), t2)); conn.commit()
assert access.check(t2) is None and set(access.all_links()["상태"]) == {"취소됨", "만료"}
# 관리 모드에서 링크 만들기(주인)
os.environ.pop("DASH_PASSWORD"); os.environ["QUANT_TEST_PAGE"] = "admin"
db.set_meta("guest_tunnel_url", "https://guest.trycloudflare.com")
at = AppTest.from_file(APP, default_timeout=180).run(); assert not at.exception
at.text_input(key="gu_name").set_value("스터디 지수"); [b for b in at.button if b.key == "gu_make"][0].click().run()
assert any("https://guest.trycloudflare.com/?guest=" in c.value for c in at.code)                 # 방문객 전용 주소로 and access.all_links().iloc[0]["name"] == "스터디 지수"
os.environ.pop("QUANT_TEST_PAGE"); print("ALL OK")
