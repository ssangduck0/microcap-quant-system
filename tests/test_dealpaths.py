import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, json
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, dealpaths as dp, fundscan, secbackfill, pricevault
db.init_db()

# --- 매도 가능일
assert dp.avail_date("재판매 등록", "424B3", "2026-03-02", []) == ("2026-03-02", "재판매 등록 접수일")
assert dp.avail_date("공모", "424B4", "2026-03-05", [])[0] == "2026-03-09"                      # 목(5) → +2거래일 = 월(9)
assert dp.avail_date("사모·PIPE 계약", "8-K", "2026-03-02", ["2026-01-10", "2026-04-15", "2026-05-01"]) == ("2026-04-15", "재판매 등록 효력(EFFECT)")
assert dp.avail_date("사모·PIPE 계약", "8-K", "2026-03-02", [])[1].startswith("6개월 뒤 추정")

# --- 결과 계산: 매도 가능일 종가 대비
idx = pd.bdate_range(start="2026-01-02", periods=120)
c = np.r_[np.full(20, 2.0), np.linspace(1.0, 0.5, 100)]           # 딜 뒤 1.0 → 0.5 로 하락
df = pd.DataFrame({"Open": c, "High": c * 1.1, "Low": c * 0.9, "Close": c, "Volume": 1e6}, index=idx)
filed, avail = idx[19].strftime("%Y-%m-%d"), idx[20].strftime("%Y-%m-%d")
p = dp.path(df, avail, filed, unit_price=1.6)
assert abs(p["discount"] - (1.6 / 2.0 - 1) * 100) < 1e-9 and p["base"] == 1.0 and p["ret5"] < 0 and p["ret60"] < p["ret20"] < 0 and p["done"] == 1, p
assert dp.path(df, "2027-01-01", filed, 1.0) is None and dp.path(None, avail, filed, 1.0) is None

# --- 비슷한 딜: 8건 미만이면 넓힘
rows = []
for i in range(12):
    rows.append({"accession": f"a{i}", "ticker": f"T{i}", "kind": "공모", "filed": "2026-02-01", "avail": "2026-02-03", "avail_note": "x", "base": 0.5 if i < 5 else 3.0,
                 "discount": -25.0, "ret5": -5.0 - i, "ret20": -10.0 + i, "ret60": -20.0, "min60": -30.0, "max60": 15.0, "bars": 70, "done": 1, "updated": "x"})
t = pd.DataFrame(rows)
s1 = dp.similar("공모", 0.6, -30.0, df=t)
assert s1["level"] == "종류" and s1["n"] == 12, s1["level"]                                   # $1 미만 공모는 5건뿐 → '종류'로 넓힘
s2 = dp.similar("공모", 3.5, -30.0, df=t)
assert s2["level"] == "종류" and s2["n"] == 12, s2["level"]                                    # $1~5 공모 7건(8건 미만) → 가격대도 7건 → '종류'까지 넓힘
assert s1["stats"][20]["n"] == 12 and abs(s1["stats"][20]["median"] - np.median([-10.0 + i for i in range(12)])) < 1e-9 and s1["min60"] == -30.0
assert dp.similar("공모", 1.0, None, exclude="a0", df=t)["n"] == 11
assert dp.similar("없는종류", 1.0, None, df=t)["level"] == "전체 딜"

# --- update: fs_deals + EFFECT(sec_hist) + 가짜 다운로드 · 상장폐지(다운로드 없음)는 보관소로
with closing(db.connect()) as conn:
    fundscan.ensure_tables(conn)
    for d_ in secbackfill.DDL:
        conn.execute(d_)
    conn.execute("INSERT INTO fs_deals (accession, ticker, filed, form, kind, unit_price) VALUES ('d1','AAA',?,'424B4','공모',1.6)", (filed,))
    conn.execute("INSERT INTO fs_deals (accession, ticker, filed, form, kind, unit_price) VALUES ('d2','GONE',?,'8-K','사모·PIPE 계약',1.6)", (filed,))
    conn.execute("INSERT INTO sec_hist (accession, ticker, form, filed) VALUES ('e1','GONE','EFFECT',?)", (idx[30].strftime("%Y-%m-%d"),))
    pricevault.save_bars(conn, "GONE", df)                                                   # 다운로드엔 없고 보관소에만
    conn.commit()
n = dp.update(download=lambda ts: {"AAA": df}, out=lambda *_: None)
assert n == 2, n
tb = dp.table().set_index("accession")
assert tb.loc["d1", "avail_note"].startswith("공모 종결") and tb.loc["d2", "avail_note"].startswith("재판매 등록 효력") and tb.loc["d2", "avail"] == idx[30].strftime("%Y-%m-%d")
assert dp.update(download=lambda ts: {"AAA": df}, out=lambda *_: None) == 0                      # 60거래일 다 채운 딜은 다시 안 함

# --- 상세 화면: '📊 비슷한 과거 딜' 칸
import fundscan_ui
from streamlit.testing.v1 import AppTest
def _app():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import fundscan_ui as fu
    fu._similar_box({"latest_deal": {"kind": "공모", "unit_price": 0.8, "accession": "zz"}, "price": 1.0})
at = AppTest.from_function(_app, default_timeout=60).run()
assert not at.exception, [e.value for e in at.exception]
assert any("비슷한 과거 딜" in m.value for m in at.markdown) and at.dataframe and "20거래일 뒤" in list(at.dataframe[0].value["기간"])
print("ALL OK")
