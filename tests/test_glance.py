import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import numpy as np, pandas as pd
import db, shares, listing, themes, rsplit, secbackfill, accum, watch, community, events_brief, glance
db.init_db(); watch.ensure_tables()
T = date.today(); D = lambda n: (T - timedelta(days=n)).isoformat()
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "HUBC", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 0.33, "high_20d": 1.9, "low_20d": 0.3,
        "drawdown_pct": -80.0, "day_change_pct": -5.0, "volume_mult": 4.6, "buy_pressure": 55.0, "float_shares": 9e9, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.execute(shares.DDL); conn.execute("INSERT INTO shares_info VALUES ('HUBC', ?, ?)", (json.dumps({"adjusted": 2.1e6, "asof": D(60), "splits_after": [{"date": D(30), "ratio": 0.04}],
                 "warn": True, "issuance_after": [f"{D(20)} 8-K (3.02 미등록 증권 판매)"]}), now))
    themes.ensure_tables(conn); themes.save_moves(conn, T.isoformat(), [("HUBC", 0.33, -5.0, 4.6, -20.0, 2.81e6)])
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('HUBC', ?, 0.04, 1.0)", (D(30),)); conn.execute("INSERT INTO rs_events VALUES ('HUBC', ?, 0.1, 1.0)", (D(400),))
    secbackfill.ensure_tables(conn)
    for acc, fm, d, it in (("a1", "8-K", D(5), "5.02"), ("a2", "8-K", D(25), "3.01"), ("a3", "8-K", D(40), "5.03,8.01"), ("a4", "8-K", D(75), "1.01,2.01"), ("a5", "4", D(3), "")):
        conn.execute("INSERT INTO sec_hist VALUES (?,?,?,?,?)", (acc, "HUBC", fm, d, it))
    conn.execute(accum.DDL); conn.execute("INSERT INTO accum VALUES (?,?,?,?,?)", (T.isoformat(), "HUBC", "주간", 6.0, json.dumps({"score": 6.0, "level": "매집 의심", "n_absorb": 2, "n_strong": 0,
                 "top_day": "10/19", "top_vr": 4.6, "top_chg": -5.0, "news": [], "dilution": [], "absorb_days": []})))
    conn.commit()
listing.save("HUBC", "a2", D(25), "u", {"kinds": ["상장증권 시가총액 기준"], "threshold": "$35M", "deadline": (T + timedelta(days=150)).isoformat(), "deadline_est": False, "snippet": ""})
to = shares.turnover("HUBC"); assert abs(to["pct"] - 2.81e6 / 2.1e6 * 100) < 1e-6                            # 회전율 134%
ev = events_brief.build("HUBC"); print([e["text"] for e in ev][:6])
assert any("임원·이사 변경" in e["text"] for e in ev) and any("시가총액 기준 미달 통지" in e["text"] for e in ev) and any("1:25 역분할" in e["text"] for e in ev)
assert not any(e["text"] == "" for e in ev) and all("Form 4" not in e["text"] for e in ev) and any(e["text"].startswith("[예정] 상장유지 기한") for e in ev)
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=130)[-126:]
c = np.r_[np.full(60, 15.0), np.linspace(15.0, 0.33, 66)]
df = pd.DataFrame({"Close": c, "High": c * 1.02, "Low": c * 0.98}, index=idx)
g = glance.build("HUBC", df); print(g["ok"]); print(g["risk"])
assert any("회전율 134%" in x and "주식 전체를 넘음" in x for x in g["ok"]) and any("초소형 주식 수" in x and "2.10M" in x for x in g["ok"]) and any("과매도" in x for x in g["ok"])
assert any("재병합 반복" in x for x in g["risk"]) and any("추가 발행 가능성" in x for x in g["risk"]) and any("상장증권 시가총액 기준" in x for x in g["risk"])
assert abs(g["mcap"] - 0.33 * 2.1e6) < 1e-6
import watch_ui; watch_ui.prices = lambda tk: {"HUBC": df}
calls = []
community.fetch = (lambda f: (lambda t, http_get=None, ttl_min=30: (calls.append(t), {"ok": True, "n": 30, "bull": 18, "bear": 12, "bull_pct": 60.0, "watchers": 5000})[1]))(community.fetch)
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(__import__("os").path.join(__import__("tempfile").gettempdir(), "glance_app.py"), default_timeout=120).run(); print("exc:", [e.value for e in at.exception]); assert not at.exception
html = "\n".join(m.value for m in at.markdown)
assert "✅ 충족 신호" in html and "⚠️ 리스크 플래그" in html and "📌 이벤트" in html and "📝 최종 정리" in html and "약 &#36;0.7M" in html and "약 2.10M주" in html
assert not calls                                                                                          # 커뮤니티는 버튼을 눌러야만
[b for b in at.button if b.key == "cm_HUBC"][0].click().run(); assert any("강세 비율 60%" in i.value and "고점 신호" in i.value for i in at.info)
c2 = community.__wrapped__ if hasattr(community, "__wrapped__") else None
print("ALL OK")
