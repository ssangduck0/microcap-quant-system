import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp()
os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import config, db, cases, winmodel
db.init_db()
rng = np.random.default_rng(11); N = 6000
dates = (pd.to_datetime("2019-01-01") + pd.to_timedelta(rng.integers(0, 2800, N), unit="D")).strftime("%Y-%m-%d")
drop = np.clip(-10 - rng.exponential(12, N), -95, -10); vol = np.exp(rng.normal(1, 1, N)); pre = -rng.exponential(25, N); dv = 10 ** rng.uniform(4.5, 7.5, N)
succ = rng.random(N) < 1/(1+np.exp(-(-1.6 + 0.04*(-drop-20) + 0.55*np.log2(vol))))
nh = np.where(succ, rng.uniform(10, 40, N), rng.uniform(-5, 9.9, N))
ev = pd.DataFrame({"ticker":[f"T{i}" for i in range(N)], "date":dates, "close":1.0, "drop_pct":drop, "vol_mult":vol, "pre_dd_pct":pre, "avg_dollar_vol":dv,
                   "next_high_pct":nh, "next_close_pct":nh-5, "max_up_3d":nh*1.1, "max_up_5d":nh*1.2, "fwd_3d":nh-5, "fwd_5d":nh-4})   # 3·5일 목표 열(2026-10-29)
with closing(db.connect()) as conn:
    cases.save_events(conn, [{**{k: None for k in cases.EVENT_COLS}, **r} for r in ev.to_dict("records")]); conn.commit()
res = winmodel.fit_all(24, out=lambda *_: None); md = db.get_model("high_10")
# 라이브 성과용: 일부 사건과 같은 (티커, 날짜)에 스냅샷을 만든다(점수는 스캐너가 기록했을 값)
pick = ev.sample(80, random_state=1)
sc = winmodel.score_frame(md, pick.reset_index(drop=True), ["CLEAN"]*80)
statuses = np.random.default_rng(2).choice(["CLEAN","ELOC","CB","ATM"], 80)
now = db.utcnow_iso()
def base_snap(t, d, **kw):
    r = {"date":d,"ticker":t,"exchange":"NASDAQ","first_seen":now,"last_seen":now,"price":1.0,"high_20d":2.0,"low_20d":0.9,"drawdown_pct":-50.0,"volume_mult":3.0,
         "buy_pressure":55.0,"float_shares":8e6,"atr14":0.1,"entry_ref":0.9,"stop_ref":0.8,"target_ref":1.2,"quant_score":50.0,"quant_detail":"{}","pump_score":40.0,
         "pump_detail":'{"checks":[]}',"dilution_status":"CLEAN","excluded":0}
    r.update(kw); return r
with closing(db.connect()) as conn:
    for (i, r), s, st_ in zip(pick.iterrows(), sc.itertuples(), statuses):
        db.upsert_snapshot(conn, base_snap(r["ticker"], r["date"], day_change_pct=r["drop_pct"], pre_dd_pct=r["pre_dd_pct"], avg_dollar_vol=r["avg_dollar_vol"],
                           win_p=s.win_p, win_score=s.win_score, win_model="high_10", dilution_status=st_))
    LATEST = "2026-10-12"
    db.upsert_snapshot(conn, base_snap("NOW1", LATEST, day_change_pct=-22.0, pre_dd_pct=-30.0, avg_dollar_vol=2e6, volume_mult=4.0, win_p=0.41, win_score=83.0, win_model="high_10"))
    db.upsert_snapshot(conn, base_snap("NOW2", LATEST, day_change_pct=-4.0, pre_dd_pct=-30.0, avg_dollar_vol=2e6, volume_mult=1.0))          # 등락률 -10% 미만 -> 점수 없음
    db.upsert_snapshot(conn, base_snap("NOW3", LATEST, day_change_pct=None))                                                           # 이전 버전 데이터
# 🧠 신호 승률 모델(2단계)도 같은 models 표에 들어온다(2026-10-28 서버에서 이것 때문에 탭이 KeyError 로 죽었음) → 선택 상자엔 안 보이고 3절에 따로 나와야 함
db.save_model("sigmodel", {"name": "sigmodel", "n_train": 1200, "n_test": 300, "cutoff": "2026-09-01", "n_tickers": 150, "from": "2024-10-01", "to": "2026-10-20", "fitted_at": "2026-10-25T00:00:00",
    "targets": {"p30": {"horizon": 20, "target_pct": 30, "auc_train": 0.71, "auc_test": 0.64, "base_rate_test": 12.0, "base_rate_train": 11.0, "lift_top": 2.1, "weights": [{"특징": "급등 폭", "key": "spike", "가중치": 0.8}, {"특징": "거래량 배수", "key": "vol", "가중치": -0.3}],
                        "deciles": [{"분위": 1, "표본": 30, "예측 확률(%)": 3.0, "실제 적중(%)": 2.5}, {"분위": 10, "표본": 30, "예측 확률(%)": 30.0, "실제 적중(%)": 25.0}]},
                "p10": {"horizon": 5, "target_pct": 10, "auc_train": 0.66, "auc_test": 0.60, "base_rate_test": 20.0, "base_rate_train": 19.0, "lift_top": 1.6, "weights": [{"특징": "급등 폭", "key": "spike", "가중치": 0.5}], "deciles": []}}})
print("db ready")

from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py"), default_timeout=120).run()
print("exc:", [e.value for e in at.exception])
tbl = [d.value for d in at.dataframe if "예상 성공확률(%)" in d.value.columns and "퀀트점수" in d.value.columns][0]   # 📊 스냅샷 표
print(tbl[["티커","오늘 등락(%)","승률 점수","예상 성공확률(%)","유사 사례 수"]].to_string(index=False))
assert "승률 점수" in tbl.columns and "예상 성공확률(%)" in tbl.columns
r1 = tbl[tbl["티커"]=="NOW1"].iloc[0]; assert r1["승률 점수"]==83.0 and abs(r1["예상 성공확률(%)"]-41.0)<1e-9
assert tbl[tbl["티커"]=="NOW2"].iloc[0]["승률 점수"] != tbl[tbl["티커"]=="NOW2"].iloc[0]["승률 점수"]   # NaN

def card(t):
    at.session_state["snap_table_pick"] = t; at.run()
    assert not at.exception, [e.value for e in at.exception]
    ms = {m.label[:8]: m.value for m in at.metric}
    return ms, [i.value[:40] for i in at.info if "승률 점수 없음" in i.value]
ms, info = card("NOW1"); print("NOW1:", {k:v for k,v in ms.items() if k.startswith(("승률 점수","예상 성공","희석 보정","과거 검증"))}, info)
assert ms["승률 점수"].startswith("83") and ms["예상 성공확률"]=="41.0%" and ms["희석 보정 배수"]=="×1.00" and any(k.startswith("과거 검증") for k in ms)
ms, info = card("NOW2"); print("NOW2:", info); assert info and "-10%" in at.info[[i for i,x in enumerate(at.info) if "승률 점수 없음" in x.value][0]].value
ms, info = card("NOW3"); print("NOW3:", info); assert info

# 점수 검증 탭
mm = {m.label: m.value for m in at.metric}
print("검증 탭 지표:", {k: v for k, v in mm.items() if k.startswith(("OOS","기준 성공","상위 20","학습 구간","결과가 확인","전체 성공"))})
assert "OOS AUC" in mm and float(mm["OOS AUC"]) > 0.6
_sb = at.selectbox[[s.label for s in at.selectbox].index("검증할 모델")]; assert not any("sigmodel" in o for o in _sb.options) and any(o.startswith("high_10") for o in _sb.options) and any(o.startswith("close_0") for o in _sb.options), _sb.options   # options 는 표시 글
assert any(o.startswith("high3_20") and "3일 안 최고가 ≥ +20%" in o for o in _sb.options) and any(o.startswith("high5_30") and "5일 안 최고가 ≥ +30%" in o for o in _sb.options), _sb.options   # 3일·5일 고가 모델(2026-10-29)
_sb.set_value("high5_30").run(); assert not at.exception, [e.value for e in at.exception]
assert any("🧠 신호 승률 모델" in m.value for m in at.markdown) and any(m.label == "검증 AUC" and m.value == "0.640" for m in at.metric) and any(m.label == "상위 10% 배수" and m.value == "×2.10" for m in at.metric)
assert int(mm["결과가 확인된 점수 기록"].replace(",","")) == 80
print("warnings:", [w.value[:50] for w in at.warning if "표본" in w.value])
shapes = [d.value.shape for d in at.dataframe]; print("tables:", shapes)
# 모델 바꾸기
at.selectbox[[s.label for s in at.selectbox].index("검증할 모델")].set_value("close_0").run()
print("close_0 exc:", [e.value for e in at.exception], "| live:", [m.value for m in at.metric if m.label=="결과가 확인된 점수 기록"])
print("ALL OK"); print(os.environ["QUANT_DB"])
