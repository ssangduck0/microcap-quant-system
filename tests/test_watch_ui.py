import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, watch, intel, closewatch as cw, market, universe, config
db.init_db(); watch.ensure_tables(); intel.ensure_table(); cw.ensure_tables()
ET = ZoneInfo("America/New_York"); today = datetime.now(ET).date()
idx = pd.bdate_range(end=pd.Timestamp(today), periods=42)[-40:]
def mk(closes): c = np.array(closes, float); return pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": 1e6}, index=idx[-len(c):])
PX = {"AAA": mk(np.r_[np.full(38, 0.9), 1.0, 1.30]), "BBB": mk(np.r_[np.full(39, 3.0), 2.4]), "CCC": mk(np.full(40, 5.0))}
calls = []
market.download_daily = lambda tk, period="3mo", chunk=40: (calls.append(list(tk)), {t: PX[t] for t in tk if t in PX})[1]
now = db.utcnow_iso(); D = today.isoformat()
def snap(t, **kw):
    r = {"date": D, "ticker": t, "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.3, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -35.0,
         "day_change_pct": -20.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
         "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0}
    r.update(kw); return r
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, snap("AAA", win_score=82.0)); db.upsert_snapshot(conn, snap("BBB", win_score=55.0, day_change_pct=-35.0))
    intel.save(conn, D, "AAA", {"day": D, "cs": {"late": 130.0, "source": "토스 실시간(체결가↔호가)"}, "halt": {"halts": [{"time": "x"}], "halt_up": 0, "halt_down": 2, "halt_other": 0, "halt_active": True},
                                "sec": {"intraday": [{"form": "424B5", "url": "u", "tags": ["OFFERING"]}], "financing": None, "warrants": []}, "short": None})
    conn.execute("INSERT INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)", (D, "AAA", json.dumps({"drop_pct": -35.0, "vol_mult": 5.0, "decay": 0.2, "buy_late": 62.0,
        "buy_prior": 48.0, "thin_ratio": 0.4, "n_samples": 8, "ask_minutes": 2.0, "top_ask_ratio": 1.5, "dilution_status": "CLEAN", "intraday_filings": [], "financing": None, "shares_out": 8e6}), now))
    conn.commit()
db.save_report("AAA", {"ticker": "AAA", "generated_at": now, "errors": {}, "runway": {"runway_months": 4.5, "cash": 9e6, "monthly_burn": 2e6, "cash_asof": "2026-06-30"}, "company": {}, "timeline": []})
watch.add_overhang("AAA", "워런트", 2.5, 1.45); watch.add_overhang("AAA", "선지급 워런트", 1.0, 0.0001); watch.add_overhang("AAA", "전환사채", None, 0.85, status="확인 필요", origin="자동 후보", source="u")
watch.add_event("AAA", (today + timedelta(days=1)).isoformat(), "주총", "역분할 안건"); watch.add_event("AAA", (today + timedelta(days=40)).isoformat(), "워런트 만기", "2.5M주")
from streamlit.testing.v1 import AppTest
import streamlit as st
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
st.cache_data.clear()
at = AppTest.from_file(APP, default_timeout=120).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception and {'🧲 수급', '⭐ 워치리스트', '🗓 일정', '📝 노트'} <= {t.label for t in at.tabs}   # 메뉴 정리: 오늘 브리핑 삭제 · 장마감 체크리스트는 🧲 수급의 탭
assert any("워치리스트가 비어 있습니다" in i.value for i in at.info)
# 1) 📊 종목 상세에서 추가(표 첫 종목) → 워치 열 표시
btn = [b for b in at.button if b.label.startswith("⭐ ") and "워치리스트에 추가" in b.label][0]; first = btn.label.split()[1]
btn.click().run(); assert not at.exception and first in watch.lists_map()
snapt = [d.value for d in at.dataframe if "워치" in d.value.columns and "퀀트점수" in d.value.columns][0]
assert snapt.set_index("티커").loc[first, "워치"] == "⭐ 관심"
watch.add("AAA", "보유", 1.0, "주력"); watch.update("AAA", added_price=1.0, note="주력"); watch.add("BBB", "관심", 3.0); watch.add("ZZZ", "블랙")
st.cache_data.clear(); at = AppTest.from_file(APP, default_timeout=120).run(); assert not at.exception
# 2) ⭐ 워치리스트 표
wl = [d.value for d in at.dataframe if "출회 가능(M주)" in d.value.columns][0]; print(wl.drop(columns=["메모"]).to_string(index=False))
a = wl.set_index("티커").loc["AAA"]
assert list(wl["티커"]) == ["AAA", "BBB"]                                                                   # 블랙(ZZZ) 기본 숨김, 보유 먼저
assert abs(a["현재가($)"] - 1.30) < 1e-9 and abs(a["오늘(%)"] - 30.0) < 1e-6 and abs(a["추가 후(%)"] - 30.0) < 1e-6 and a["$1 연속"] == "위 2일"
assert a["승률 점수"] == 82.0 and a["체결강도(%)"] == 130.0 and a["거래정지"].startswith("하킷 2") and a["장중 희석"] == "❌ 1건"
assert abs(a["출회 가능(M주)"] - 1.0) < 1e-9 and abs(a["위 대역(M주)"] - 2.5) < 1e-9 and a["바로 위 물량대"] == "$1.45 (+12%)" and a["확인 필요"] == 1
assert a["런웨이(개월)"] == 4.5 and a["다음 일정"].endswith("주총") and a["리스트"] == "💼 보유"
assert wl.set_index("티커").loc["BBB", "$1 연속"] == "위 40일"
# 3) 상세: 지표, 물량 장부 편집, 일정 추가
mt = {m.label: m.value for m in at.metric}
assert mt["지금 출회 가능"] == "1.00M주" and mt["위 대역"] == "2.50M주" and mt["바로 위 물량대"] == "$1.45" and mt["런웨이"] == "4.5개월" and mt["Baby Shelf"] == "대상"
assert mt["잠김 / 확인 필요"] == "0.00M주 / 1건"
ed = at.get("data_editor") if hasattr(at, "get") else []
oh = watch.overhang_rows("AAA"); oh.loc[oh["kind"] == "전환사채", ["status", "qty_m"]] = ["활성", 4.0]
watch.save_overhang_edits("AAA", oh)                                                                         # 화면의 저장 버튼과 같은 함수
st.cache_data.clear(); at = AppTest.from_file(APP, default_timeout=120).run()
mt = {m.label: m.value for m in at.metric}; assert mt["지금 출회 가능"] == "5.00M주" and mt["잠김 / 확인 필요"] == "0.00M주 / 0건"      # 전환사채 $0.85 ≤ $1.30 → 출회 가능
at.selectbox(key="wl_l_AAA").set_value("그레이").run(); assert watch.lists_map()["AAA"] == "그레이" and not at.exception
at.text_input(key="wl_note_AAA").set_value("바뀐 메모").run(); assert watch.all_items().set_index("ticker").loc["AAA", "note"] == "바뀐 메모"
# 4) 🗓 일정
evt = [d.value for d in at.dataframe if "남은기간" in d.value.columns]; print(evt[-1][["임박", "날짜", "남은기간", "티커", "종류"]].to_string(index=False))
assert any((e["종류"] == "주총").any() and (e["임박"] == "🔥").any() for e in evt)
assert {m.label: m.value for m in at.metric}["🔥 3거래일 안"] == "1 건"
at.slider(key="ev_ahead").set_value(60).run(); assert any("워런트 만기" in list(e["종류"]) for e in [d.value for d in at.dataframe if "남은기간" in d.value.columns])
dollar = [d.value for d in at.dataframe if "$1 이상 연속" in d.value.columns]; assert dollar and dollar[0].set_index("티커").loc["AAA", "판단"] == "회복까지 8거래일"
# 5) (📰 오늘 브리핑 화면은 2026-10-26 메뉴 정리로 삭제 — 홈과 같은 내용이라 검사도 뺌)
# 6) 스캐너 우선 종목에 워치리스트 포함(블랙 제외)
config.SCAN_UNIVERSE = "manual"; universe.get_tickers = lambda use_legacy_toss=True: ["XYZ"]
config.SCAN_UNIVERSE = "nasdaq"; universe.load_listed_toss = lambda tc, a: []; universe.load_listed = lambda include_amex=False: ["AAA", "QQQ"]
allt, prio = universe.get_universe(None); assert {"AAA", "BBB"} <= prio and "ZZZ" not in prio and "BBB" in allt
print("ALL OK")
