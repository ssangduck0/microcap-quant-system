"""화면 속도(2026-10-30 밤) — 🔁 병합 후 레이더 빠른 계산이 예전(similar+expect)과 같은 숫자 · 순위 칩 사전 재사용(내용이 바뀌면 새로) ·
🎯 PICK 스캔을 화면 캐시에서 꺼내기(없으면 계산해 넣기)."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, math, time
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db")
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import numpy as np
import pandas as pd
import db, rsplit as rs

db.init_db()

# ---- 1) 병합 후 레이더: 빠른 계산 == 예전 계산
r = np.random.default_rng(4)
rows = []
for s in range(60):
    t, sd = f"T{s % 45:02d}", f"2025-{1 + s % 12:02d}-{1 + s % 27:02d}"
    for k in range(0, 150, 2):
        fmax = float(r.normal(25, 30)) if r.random() > 0.05 else np.nan
        rows.append((t, sd, k, float(r.normal(-20, 25)), fmax, float(r.normal(-15, 10)) if r.random() > 0.05 else np.nan,
                     float(r.normal(0, 20)), int(r.integers(0, 10)) if r.random() > 0.05 else None))
cur = [(f"T{i:02d}", f"2025-{1 + i % 12:02d}-{1 + i % 27:02d}", 0.1, int(r.integers(0, 140)), float(r.uniform(0.2, 5)), float(r.normal(-20, 25)), "x") for i in range(40)]
cur.append(("ZZ", "2026-01-01", 0.2, 999, 1.0, 0.0, "x"))                       # 유사 사례 없음
with closing(db.connect()) as conn:
    rs.ensure_tables(conn)
    conn.executemany("INSERT OR REPLACE INTO rs_paths (ticker, split_date, k, dd, fwd_max, fwd_min, fwd_close, days_to_max) VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.executemany("INSERT OR REPLACE INTO rs_current (ticker, split_date, ratio, k, price, dd, at) VALUES (?,?,?,?,?,?,?)", cur)
    conn.commit()

    def slow(target, bk, bd):                                                   # 10/30 이전 radar 그대로
        c_ = db.read_df("SELECT * FROM rs_current"); paths = db.read_df("SELECT * FROM rs_paths")
        return pd.DataFrame([{**x, **rs.expect(rs.similar(paths, int(x["k"]), float(x["dd"]), bk, bd, exclude=(x["ticker"], x["split_date"])), float(x["price"]), target)}
                             for x in c_.to_dict("records")])
    for target, bk, bd in ((20.0, 10, 10.0), (50.0, 3, 5.0), (5.0, 30, 30.0)):
        t0 = time.time(); a = rs.radar(conn, target, bk, bd); t_fast = time.time() - t0
        b = slow(target, bk, bd)
        a, b = a.set_index("ticker").sort_index(), b.set_index("ticker").sort_index()
        assert list(a.index) == list(b.index)
        for col in ("n", "events", "success", "max_q25", "max_med", "max_q75", "min_med", "close_med", "days_med", "start_price", "exp_high", "exp_high_q75"):
            if col not in b:
                continue
            for x, y in zip(a[col], b[col]):
                if (x is None or (isinstance(x, float) and math.isnan(x))) and (y is None or (isinstance(y, float) and math.isnan(y))):
                    continue
                assert abs(float(x) - float(y)) < 1e-9, (target, bk, bd, col, x, y)
        assert a.loc["ZZ", "n"] == 0
    print("radar same as before · fast", round(t_fast, 3), "s")

# ---- 2) 순위 칩: 같은 표면 같은 사전(다시 만들지 않음) · 표가 바뀌면 새 사전
import rank_ui
df1 = pd.DataFrame({"ticker": ["AAA", "BBB"], "rank": [1, 2], "score": [90.0, 80.0], "urgency": [100, 0], "top_pct": [1, 2], "when": ["⏱ 오늘", "⏱ 내일"], "when_why": ["a", "b"]})
state = {"df": df1}
rank_ui.table = lambda: state["df"].copy()                                       # st.cache_data 처럼 매번 복사본
m1, m2 = rank_ui.lookup(), rank_ui.lookup()
assert m1 is m2 and m1["AAA"]["rank"] == 1, m1
assert "종합 1위" in rank_ui.chip("aaa") and rank_ui.chip("CCC") == ""
state["df"] = df1.assign(rank=[2, 1], score=[70.0, 95.0])
m3 = rank_ui.lookup()
assert m3 is not m1 and m3["AAA"]["rank"] == 2 and m3["BBB"]["rank"] == 1
state["df"] = df1.iloc[0:0]
assert rank_ui.lookup() == {}

# ---- 3) 🎯 PICK: 화면 캐시에서 꺼내기 · 없으면 계산해 넣기
import pagecache, pick30, pick30_ui
assert "pick30" in pagecache.ENTRIES and pagecache.ENTRIES["pick30"][3] is pagecache._build_pick30
calls = []
pick30.scan = lambda: calls.append(1) or {"rows": [{"ticker": "AAA"}], "at": "x"}
pick30_ui._scan.clear()
s = pick30_ui._scan()
assert s["rows"][0]["ticker"] == "AAA" and calls == [1]                          # 캐시가 없으니 계산
assert pagecache.get("pick30", 25)["rows"][0]["ticker"] == "AAA"                  # 넣어 둠
pick30_ui._scan.clear()
assert pick30_ui._scan()["at"] == "x" and calls == [1]                            # 이번엔 캐시에서(다시 계산 안 함)
assert pagecache._build_pick30()["at"] == "x" and calls == [1, 1]                 # 데우기 작업은 pick30.scan 을 부름

# ---- 4) 💰 펀드스캔 · 🧲 다크풀 표시도 화면 캐시에서(get_or_build)
import fundscan, darkpool
assert {"fundscan", "dp_flags"} <= set(pagecache.ENTRIES)
fs_calls, dp_calls = [], []
fundscan.scan = lambda: fs_calls.append(1) or [{"ticker": "FFF", "score": 9}]
darkpool.flag_map = lambda conn=None: dp_calls.append(1) or {"DDD": "DP 62% (+14p)"}
assert pagecache.get_or_build("fundscan")[0]["ticker"] == "FFF" and pagecache.get_or_build("fundscan")[0]["ticker"] == "FFF" and fs_calls == [1]   # 두 번째는 캐시
assert pagecache.get_or_build("dp_flags") == {"DDD": "DP 62% (+14p)"} and dp_calls == [1]
import fundscan_ui, accum_ui
fundscan_ui._scan.clear(); accum_ui._dp_flags.clear()
assert fundscan_ui._scan()[0]["ticker"] == "FFF" and accum_ui._dp_flags() == {"DDD": "DP 62% (+14p)"} and fs_calls == [1] and dp_calls == [1]
print("ALL OK")
