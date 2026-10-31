import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
tmp = tempfile.mkdtemp(); os.environ["QUANT_TEST_ALL_PAGES"]="1"; os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import numpy as np, pandas as pd
import db, rsplit as rs
db.init_db()
idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=402)[-400:]
c = np.full(400, 5.0); sp = np.zeros(400)
s = 100; sp[s] = 0.1; c[s:] = np.r_[np.linspace(5.0, 2.5, 40), np.full(400 - s - 40, 2.5)]   # 병합 후 40일간 -50% 하락 후 횡보
c[s + 45] = 3.5                                                                       # 병합 후 45일째 +40% 튐
s2 = 380; sp[s2] = 0.2                                                                # 최근 병합(20거래일 전)
df = pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c, "Volume": 1e6, "Stock Splits": sp}, index=idx)
ev, paths, cur = rs.analyze_frame(df)
assert [e["ratio"] for e in ev] == [0.1, 0.2] and cur["k"] == 19 and cur["ratio"] == 0.2
p = pd.DataFrame(paths); r40 = p[(p.split_date == idx[s].strftime("%Y-%m-%d")) & (p.k == 40)].iloc[0]
assert abs(r40["dd"] - (2.5 / 5.0 - 1) * 100) < 1e-9 and abs(r40["fwd_max"] - (3.5 * 1.02 / 2.5 - 1) * 100) < 1e-9 and r40["days_to_max"] == 5
assert p.groupby("split_date")["k"].max().iloc[0] == rs.MAX_K and rs.analyze_frame(df.drop(columns="Stock Splits")) == ([], [], None)
fwd = pd.DataFrame({**{k: [0.0] * 400 for k in ("Open",)}, "High": c, "Low": c, "Close": c, "Stock Splits": np.r_[np.zeros(399), 2.0]}, index=idx)   # 정분할(2.0)은 무시
assert rs.analyze_frame(fwd)[0] == []
import market
market._download = lambda tk, chunk_size=100, **kw: {t: df for t in tk if t == "RSX"}
r = rs.run(["RSX", "NONE"], "10y", out=lambda *_: None); assert r == {"events": 2, "current": 1}
with closing(db.connect()) as conn:
    assert conn.execute("SELECT COUNT(*) FROM rs_paths").fetchone()[0] == len(paths) and conn.execute("SELECT k FROM rs_current WHERE ticker='RSX'").fetchone()[0] == 19
allp = db.read_df("SELECT * FROM rs_paths")
sim = rs.similar(allp, 40, -50.0, 5, 5.0); e = rs.expect(sim, 2.5, 20.0); print({k: round(v, 2) if isinstance(v, float) else v for k, v in e.items()})
assert e["n"] > 0 and e["events"] == 1 and 0 < e["success"] <= 100 and e["start_price"] <= 2.5 <= e["exp_high"]
assert rs.similar(allp, 40, -50.0, exclude=("RSX", idx[s].strftime("%Y-%m-%d"))).empty and rs.expect(allp.iloc[0:0], 1.0)["n"] == 0
with closing(db.connect()) as conn:
    assert rs.record_signal(conn, "2026-10-15", "RSX", 2.5, e) and not rs.record_signal(conn, "2026-10-15", "RSX", 2.6, e)
# 📅 병합 예정(C단계): 본문 규칙 추출 · 기록 · 예정 표
D0 = __import__("datetime").date(2026, 10, 26)   # 본문 속 시행일이 고정 날짜라 '오늘'도 고정(지난 날 7일 넘으면 기록 안 하는 규칙 때문에 날짜가 지나면 실패하던 것)
T1 = "On October 20, 2026 the Board approved a 1-for-10 reverse stock split of the Company's common stock. The reverse stock split will become effective at 12:01 a.m. Eastern Time on October 30, 2026."
T2 = "The Company announced a reverse split at a ratio of one-for-25. The common stock will begin trading on a split-adjusted basis on Monday, November 3, 2026 under the same symbol."
T3 = "The Company effected a 15:1 reverse split in 2024."                       # 날짜 없음
T4 = "Quarterly results were strong; effective October 30, 2026 the CFO resigns."  # 역분할 아님
assert rs.upcoming_from_text(T1, D0) == {"date": "2026-10-30", "ratio": 10} and rs.upcoming_from_text(T2, D0) == {"date": "2026-11-03", "ratio": 25}, (rs.upcoming_from_text(T1, D0), rs.upcoming_from_text(T2, D0))
assert rs.upcoming_from_text(T3) is None and rs.upcoming_from_text(T4) is None and rs.upcoming_from_text("") is None
# 실제 공시 문구(10/27 서버 진단): 범위 문구보다 확정 비율 · 효력일보다 분할 반영 거래 시작일 · 영어 숫자 · share consolidation · '매 16주를 1주로'
P = ("the shareholders approved a reverse split at a ratio in the range of 1-for-5 to 1-for-50. The Company determined to effect a reverse stock split at a ratio of 1-for-10 "
     "(the Reverse Stock Split). Trading of the Class A common stock on a split-adjusted basis is expected to begin on October 27, 2026.")
N = ("the board approved a one-for-nine reverse stock split. The reverse stock split will become effective as of 5:00 p.m. Eastern Time on October 26, 2026, and the "
     "common stock will begin trading on a split-adjusted basis when the market opens on October 27, 2026.")
E = ("the board has determined to effect a reverse share split of the ordinary shares at a ratio of 1-for-16 (the Reverse Split), such that every 16 ordinary shares will be "
     "automatically combined and reclassified into one ordinary share. The ordinary shares will begin trading on a split-adjusted basis on the Nasdaq Capital Market on October 27, 2026.")
M = "On October 23, 2026, the company announced a two-for-one share consolidation, with its class A ordinary shares expected to begin trading on a post-consolidation basis on October 30, 2026."
assert rs.upcoming_from_text(P, D0) == {"date": "2026-10-27", "ratio": 10}, rs.upcoming_from_text(P, D0)
assert rs.upcoming_from_text(N, D0) == {"date": "2026-10-27", "ratio": 9}, rs.upcoming_from_text(N, D0)
assert rs.upcoming_from_text(E, D0) == {"date": "2026-10-27", "ratio": 16}, rs.upcoming_from_text(E, D0)
assert rs.upcoming_from_text(M, D0) == {"date": "2026-10-30", "ratio": 2}, rs.upcoming_from_text(M, D0)
# 2차(10/27 서버 진단): 'on or about' · 괄호 숫자 비율 · 지난 '이미 시행한' 병합은 무시 · 효력 예정 문장
R = ("we are proposing a share consolidation of the class a ordinary shares at a ratio of ten (10)-for-one (1), such that every ten (10) class a ordinary shares will be consolidated into one. "
     "If approved by shareholders, the share consolidation is expected to be effective on or about November 13, 2026.")
O = ("the stockholders approved an amendment to effect one or more reverse stock splits, provided that the reverse stock splits shall not, in the aggregate, exceed one-for-one hundred (1:100). "
     "Pursuant to the foregoing authorization, the company previously effected a one-for-ten (1:10) reverse stock split of its common stock, effective May 21, 2026.")
assert rs.upcoming_from_text(R, D0) == {"date": "2026-11-13", "ratio": 10}, rs.upcoming_from_text(R, D0)
assert rs.upcoming_from_text(O) is None, rs.upcoming_from_text(O)                     # 미래 시행일 없음 → 기록 안 함
A = "RoboAI announces reverse stock split. The reverse stock split is expected to become effective on November 6, 2026 at a ratio of 1-for-25."
assert rs.upcoming_from_text(A, D0) == {"date": "2026-11-06", "ratio": 25}, rs.upcoming_from_text(A, D0)
# 추가 병합(2026-10-31 MASK 10/28): 이번 추가분(2-for-1)이 먼저 나와도 그날 실제 배수인 합계(cumulative 4-for-1)로 · 이미 끝난 병합까지 합친 누적은 건너뜀
C1 = ("the board of directors approved a further 2-for-1 consolidation of the company's issued and unissued shares, such that every two (2) issued and unissued class a ordinary shares "
      "be consolidated into one (1) class a ordinary share. The further share consolidation, together with the previously announced 2-for-1 share consolidation, will result in a "
      "cumulative 4-for-1 share consolidation. The class a ordinary shares are expected to begin trading on a post-consolidation basis on October 30, 2026.")
C2 = "Company announces further share consolidation resulting in a cumulative 4 for 1 ratio. The shares will trade on a split-adjusted basis on October 30, 2026."
C3 = ("The board approved a 1-for-10 reverse stock split. Trading on a split-adjusted basis will begin on November 13, 2026. Together with the reverse split effected in March 2026, "
      "this is a cumulative 1-for-250 reduction.")
C4 = "The share consolidation at a cumulative ratio of one-for-twenty will become effective on November 2, 2026, following a further 1-for-2 share consolidation."
assert rs.upcoming_from_text(C1, D0) == {"date": "2026-10-30", "ratio": 4}, rs.upcoming_from_text(C1, D0)
assert rs.upcoming_from_text(C2, D0) == {"date": "2026-10-30", "ratio": 4}, rs.upcoming_from_text(C2, D0)
assert rs.upcoming_from_text(C3, D0) == {"date": "2026-11-13", "ratio": 10}, rs.upcoming_from_text(C3, D0)
assert rs.upcoming_from_text(C4, D0) == {"date": "2026-11-02", "ratio": 20}, rs.upcoming_from_text(C4, D0)
import watch
from datetime import date as _d
with closing(db.connect()) as conn:
    watch.ensure_tables(conn) if hasattr(watch, "ensure_tables") else None
    fut = (_d.today() + __import__("datetime").timedelta(days=5)).isoformat()
    assert rs.record_upcoming(conn, "rsx", {"date": fut, "ratio": 10}, "8-K 2026-10-27 http://x") and not rs.record_upcoming(conn, "RSX", {"date": fut, "ratio": 10}, "8-K")
    assert not rs.record_upcoming(conn, "OLD", {"date": "2020-01-01", "ratio": 5}, "8-K")      # 지난 날은 기록 안 함
    conn.execute("INSERT OR REPLACE INTO fundamentals (ticker, name, exchange, float_shares, shares_out, market_cap, updated_at) VALUES ('RSX','RSX','NASDAQ',1e6,2e7,NULL,'x')")
    conn.commit()
    up = rs.upcoming(conn)
    assert list(up["티커"]) == ["RSX"] and up.iloc[0]["비율"] == "1:10" and up.iloc[0]["D-day"] == "D-5" and abs(up.iloc[0]["병합 후 주식 수(만주)"] - 200) < 1e-9, up
    # 틀린 비율은 고쳐 쓰고, 같은 종목의 자동 기록이 ±10일 안 다른 날짜면 새 날짜로 바꿔 끼움
    assert rs.record_upcoming(conn, "RSX", {"date": fut, "ratio": 12}, "8-K 정정") and rs.upcoming(conn).iloc[0]["비율"] == "1:12"
    fut2 = (_d.today() + __import__("datetime").timedelta(days=6)).isoformat()
    assert rs.record_upcoming(conn, "RSX", {"date": fut2, "ratio": 12}, "8-K 거래 시작일")
    up2 = rs.upcoming(conn); assert list(up2["시행일"]) == [fut2], up2
    # 첨부 읽기: 주 문서가 짧으면 EX-99 도 이어 붙임(가짜 클라이언트)
    class _C:
        def _get(self, u):
            class R: text = '<a href="/Archives/edgar/data/1/0001-index.htm">x</a><a href="/Archives/edgar/data/1/main.htm">m</a><a href="/Archives/edgar/data/1/ex99-1.htm">e</a>'
            return R()
        def fetch_text(self, u, limit=0):
            return "cover only" if u.endswith("main.htm") else "Press release: " + N
    assert rs.upcoming_from_text(rs.filing_text(_C(), "http://x/idx"), D0) == {"date": "2026-10-27", "ratio": 9}
print("ALL OK")
