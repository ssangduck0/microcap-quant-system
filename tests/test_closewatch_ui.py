import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, closewatch as cw
db.init_db(); cw.ensure_tables()
now = db.utcnow_iso()
base = {"price": 1.0, "drop_pct": -35.0, "vol_mult": 5.0, "decay": 0.2, "cs_late": 140.0, "cs_prior": 100.0, "cs_source": "토스 웹소켓(체결가↔호가)", "thin_ratio": 0.4, "n_samples": 8, "ask_minutes": 2.0,
        "top_ask_ratio": 1.5, "dilution_status": "CLEAN", "intraday_filings": [], "financing": None, "shares_out": 8e6,
        "vol_series": [{"t": f"{9 + i // 6:02d}:{(i % 6) * 10:02d}", "v": float(1000 * (i + 1))} for i in range(12)]}
PIPE = {"sellable": "restricted", "date": "2026-10-09", "form": "8-K", "type": "사모(PIPE)", "label": "출회 제한(재판매 등록 전)", "url": "https://sec.gov/x"}
HALT = [{"time": "10-12 10:15:30", "code": "LUDP", "reason": "변동성 정지(LULD)", "dir": "하한", "threshold": 7.5, "price_before": 8.2, "resume": "10:20:30", "carry": False}]
SHORT = {"sv_date": "2026-10-09", "sv_short": 800000.0, "sv_total": 1000000.0, "sv_ratio": 80.0, "sv_avg5_ratio": 60.0, "borrow_fee": 45.5, "borrow_avail": 1200.0, "errors": []}
cases = {"BESTA": {**base, "financing": PIPE, "warrant_filings": [], "halts": HALT, "halt_down": 1, "halt_up": 0, "halt_other": 0, "halt_active": False, "short": SHORT},                                           # 패턴 6/6 + 출회 제한 조달 -> BEST
         "CANDB": {**base, "cs_late": 80.0, "shares_out": 50e6, "warrant_filings": [{"form": "8-K", "date": "2026-10-09", "url": "https://sec.gov/w"}], "halts": [], "short_note": "Fintel 미연동 — .env 에 FINTEL_API_KEY 추가"},                         # 패턴 5/6 이지만 가산 조건이 없어 후보
         "WATCH": {**base, "decay": 0.9, "cs_late": 80.0, "thin_ratio": 0.9},            # 관찰
         "DILUT": {**base, "dilution_status": "ATM"},                                     # 희석 위험
         "SMALL": {**base, "drop_pct": -8.0},                                             # 낙폭 미달
         "TODAY": {**base, "intraday_filings": [{"form": "424B5", "url": "https://sec.gov/y", "tags": ["OFFERING"]}]},   # 장중 희석 -> 희석 위험
         "NOSEC": {**base, "intraday_filings": None, "financing": None, "sec_error": "SEC 조회 실패"}}
with closing(db.connect()) as conn:
    for t, m in cases.items():
        conn.execute("INSERT INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)", ("2026-10-12", t, json.dumps(m), now))
    conn.execute("INSERT INTO close_state (date,ticker,metrics,updated_at) VALUES (?,?,?,?)", ("2026-10-09", "OLDDAY", json.dumps(base), now))   # 이전 날짜는 표시 안 함
    for i in range(6):
        conn.execute("INSERT INTO close_samples (ts,date,ticker,price,ask_depth_usd) VALUES (?,?,?,?,?)", (f"2026-10-12T19:{i * 5:02d}:00+00:00", "2026-10-12", "BESTA", 1.0, 1000.0 - 100 * i))
    conn.commit()
    now_snap = {"date": "2026-10-12", "ticker": "SNAP", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 2.0, "low_20d": 0.9, "drawdown_pct": -40.0,
                "day_change_pct": -15.0, "volume_mult": 3.0, "buy_pressure": 55.0, "float_shares": 8e6, "atr14": 0.1, "quant_score": 50.0, "quant_detail": "{}", "pump_score": 40.0,
                "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0}
    db.upsert_snapshot(conn, now_snap)
db.set_meta("us_session", "프리마켓")
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=90).run()
print("exc:", [e.value for e in at.exception]); assert not at.exception
def board(at): return [d.value for d in at.dataframe if "패턴" in d.value.columns and "등급" in d.value.columns and "호가 얇아짐" in d.value.columns][0]   # 🎯 오늘 체크리스트 표
assert any("프리마켓" in w.value and "정규장 중에만" in w.value for w in at.warning)
t = board(at); print(t[["등급", "티커", "패턴", "낙폭", "호가 얇아짐", "출회제한 조달", "공급 제한"]].to_string(index=False))
assert list(t["티커"]) == ["BESTA", "CANDB", "NOSEC", "WATCH"] and list(t["등급"]) == ["BEST", "후보", "후보", "관찰"]   # 숨기기 기본: 희석 위험/낙폭 미달·이전 날짜 제외. NOSEC 은 패턴 6/6 이어도 장중 희석 미확인이라 BEST 불가
assert t.iloc[0]["자금조달(7일)"].startswith("사모(PIPE)") and t.iloc[0]["자금조달(7일)"].endswith("출회 제한(재판매 등록 전)") and t.iloc[0]["출회제한 조달"] == "✅" and set(t.iloc[0][["낙폭", "거래량 감소", "체강↑", "호가 얇아짐", "매도벽 없음"]]) == {"✅"}
assert {m.label: m.value for m in at.metric}["BEST"] == "1 개" and {m.label: m.value for m in at.metric}["희석 위험"] == "2 개" and {m.label: m.value for m in at.metric}["낙폭 미달"] == "1 개"
# 숨기기 해제: 전체 7종목, 확인 불가(➖) 표시
at.checkbox(key="cw_hide").set_value(False).run(); t = board(at); assert len(t) == 7 and set(t["티커"]) == set(cases)
ns = t[t["티커"] == "NOSEC"].iloc[0]; assert ns["장중 희석 없음"] == "➖" and ns["자금조달(7일)"] == "없음" and ns["출회제한 조달"] == "·" and t[t["티커"] == "BESTA"].iloc[0]["공급 제한"] == "✅"
assert t[t["티커"] == "DILUT"].iloc[0]["ATM·CB 없음"] == "❌" and t[t["티커"] == "TODAY"].iloc[0]["장중 희석 없음"] == "❌"
# 기준값 조정: 낙폭 기준을 -40 으로 올리면(더 깊어야 함) 전부 낙폭 미달 -> 기본 숨기기에서는 표시할 종목 없음
at.checkbox(key="cw_hide").set_value(True).run(); at.slider(key="cw_drop").set_value(-40).run()
assert any("표시할 종목이 없습니다" in i.value for i in at.info) and not at.exception
at.slider(key="cw_drop").set_value(-30).run(); assert list(board(at)["티커"])[0] == "BESTA"          # -35% 는 -30% 기준 통과
at.slider(key="cw_best").set_value(6).run(); g = dict(zip(board(at)["티커"], board(at)["등급"])); assert g["BESTA"] == "BEST" and g["CANDB"] == "관찰" or g["CANDB"] == "후보"   # 6/6 만 BEST
at.slider(key="cw_best").set_value(5).run(); at.slider(key="cw_decay").set_value(10).run(); assert not at.exception           # 감소 기준을 10%로 줄이면 decay 0.2 미충족
t = board(at); assert t[t["티커"] == "BESTA"].iloc[0]["거래량 감소"] == "❌"
at.slider(key="cw_decay").set_value(50).run()
# 상세: 미충족 항목 안내, 근거 링크, 차트
at.session_state["cw_table_pick"] = "CANDB"; at.run()
w = [x.value for x in at.warning if "CANDB" in x.value]; print(w)
assert w and "미충족" in w[0] and "체결강도 상승" in w[0] and "최근 30분 80% / 그 전 60분 100%" in w[0]
det = [d.value for d in at.dataframe if "항목(기준)" in d.value.columns and "그룹" in d.value.columns][0]
assert list(det["그룹"].unique()) == ["수급 패턴", "돈 유입", "희석 안전", "베스트 가산", "참고"] and any("Fintel 미연동" in v for v in det["현재 값"])
at.session_state["cw_table_pick"] = "BESTA"; at.run()
assert any("sec.gov/x" in x.value and "사모(PIPE)" in x.value for x in at.markdown) and any("호가" in x.value for x in at.markdown)           # 자금조달 근거 링크 + 호가 차트
assert any("FINRA·IBKR" in str(d.value.values) for d in at.dataframe)
# 참고용 오래된 보드는 접힌 expander 안에서 계속 동작
assert not at.exception and any("퀀트 스냅샷 기준 후보 보드" in e.label for e in at.expander)
# 새 항목: 표 열과 상세 패널
at.checkbox(key="cw_hide").set_value(False).run(); t = board(at)
for col in ("워런트 없음", "하킷", "공매도 압력"): assert col in t.columns, col
bb, cc = t[t["티커"] == "BESTA"].iloc[0], t[t["티커"] == "CANDB"].iloc[0]
assert (bb["워런트 없음"], bb["하킷"], bb["공매도 압력"]) == ("✅", "✅", "✅") and (cc["워런트 없음"], cc["하킷"], cc["공매도 압력"]) == ("❌", "·", "➖")      # 워런트 공시 있음 ❌, 정지 이력 없음 ·, Fintel 미연동 ➖
assert t[t["티커"] == "NOSEC"].iloc[0]["워런트 없음"] == "➖" and t[t["티커"] == "NOSEC"].iloc[0]["하킷"] == "➖"
at.checkbox(key="cw_hide").set_value(True).run()
at.session_state["cw_table_pick"] = "BESTA"; at.run()
det = [d.value for d in at.dataframe if "항목(기준)" in d.value.columns][0]
vals = dict(zip(det["항목(기준)"].str[:6], det["현재 값"])); print(list(det["항목(기준)"]))
assert any("하한(하킷) 1회" in v for v in det["현재 값"]) and any("대차 수수료 45.5%" in v for v in det["현재 값"]) and any("토스 웹소켓" in v for v in det["현재 값"])
hd = [d.value for d in at.dataframe if "정지 시각(ET)" in d.value.columns]
assert hd and hd[0].iloc[0]["방향"] == "하한" and hd[0].iloc[0]["재개(ET)"] == "10:20:30" and hd[0].iloc[0]["밴드 가격"] == 7.5       # 정지 이력 표
assert any("FINRA" in c.value for c in at.caption) and not at.exception
at.session_state["cw_table_pick"] = "CANDB"; at.run()
assert any("sec.gov/w" in x.value and "워런트" in x.value for x in at.markdown) and not at.exception                                   # 워런트 공시 링크
# 기준값: 체결강도 기준을 높이면 체강 항목이 미충족으로 바뀌고, 공매도 기준을 높이면 ❌
at.checkbox(key="cw_hide").set_value(True).run()
at.slider(key="cw_cs_late").set_value(150).run(); assert board(at).loc[board(at)["티커"] == "BESTA", "체강↑"].iloc[0] == "❌"
at.slider(key="cw_cs_late").set_value(110).run(); at.slider(key="cw_cs_delta").set_value(50).run(); assert board(at).loc[board(at)["티커"] == "BESTA", "체강↑"].iloc[0] == "❌"    # +40%p < +50%p
at.slider(key="cw_cs_delta").set_value(10).run()
at.checkbox(key="cw_hide").set_value(False).run(); at.slider(key="cw_short").set_value(90).run()
assert board(at).loc[board(at)["티커"] == "BESTA", "공매도 압력"].iloc[0] == "❌" and not at.exception
# 기록이 없으면 안내
os.environ["QUANT_DB"] = os.path.join(tmp, "empty.db")
print("ALL OK")
