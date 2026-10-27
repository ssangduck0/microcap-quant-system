import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
from contextlib import closing
import db, shares, secbackfill, rsplit
db.init_db()
CF = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
    {"end": "2026-05-10", "val": 30_000_000, "filed": "2026-05-14", "form": "10-Q", "accn": "a1"},
    {"end": "2026-08-12", "val": 50_000_000, "filed": "2026-08-14", "form": "10-Q", "accn": "a2"},          # 최신(기준일 8/12)
    {"end": "2026-08-12", "val": 2_500_000, "filed": "2026-08-14", "form": "10-Q", "accn": "a2", "frame": "ClassB"}]}}}}}
c = shares.cover_shares(CF); assert c["shares"] == 52_500_000 and c["asof"] == "2026-08-12" and c["form"] == "10-Q"       # 같은 기준일 여러 종류 합산
assert shares.cover_shares({"facts": {}}) is None
with closing(db.connect()) as conn:
    rsplit.ensure_tables(conn); conn.execute("INSERT INTO rs_events VALUES ('HUBC','2026-09-15',0.04,1.0)")            # 기준일 뒤 1:25 병합
    secbackfill.ensure_tables(conn); conn.execute("INSERT INTO sec_hist VALUES ('x1','HUBC','8-K','2026-09-20','3.02,9.01')"); conn.commit()
class FC:
    def cik_for(s, t): return 1 if t == "HUBC" else None
    def companyfacts(s, cik): return CF
d = shares.estimate("HUBC", FC()); print(d)
assert d["adjusted"] == 52_500_000 * 0.04 and d["splits_after"] == [{"date": "2026-09-15", "ratio": 0.04}] and d["warn"] and "3.02" in d["issuance_after"][0]
v, tag = shares.best("HUBC", 9e9); assert v == 2_100_000 and "이후 분할 반영" in tag and "발행 미반영" in tag
v, tag = shares.best("NOPE", 5e6); assert v == 5e6 and tag.startswith("야후")
assert shares.estimate("NOPE", FC()) is None and shares.build_missing(FC(), ["HUBC", "NOPE"], out=lambda *_: None) == 0   # 7일 안 = 건너뜀
print("ALL OK")
