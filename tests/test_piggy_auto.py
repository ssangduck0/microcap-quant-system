import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""🐷 저금통 자동 담기·빼기: 기준(안정성·반등·폭·거래대금·최근 이탈·희석·가격) · 최대 개수 · 직접 담은 종목은 안 뺌 · 기준 이탈 목록."""
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
import db, piggy, config
db.init_db(); piggy.ensure_tables()
FX = 1342.0


def put_scan(day, rows):
    with closing(db.connect()) as c:
        c.execute("DELETE FROM piggy_scan WHERE date=?", (day,))
        for t, m in rows.items():
            full = {"price": 0.5, "score": 80.0, "bounces": 3, "width_pct": 30.0, "dollar_vol": 50000.0, "recent_break": False, "support": 0.45, "resistance": 0.6} | m
            c.execute("INSERT OR REPLACE INTO piggy_scan (date, ticker, price, metrics) VALUES (?,?,?,?)", (day, t, full["price"], json.dumps(full)))
        c.commit()


piggy._dil_map = lambda: {"DILX": "ATM", "GOOD2": "CLEAN"}
put_scan("2026-10-20", {"GOOD1": {"score": 90}, "GOOD2": {"score": 70}, "LOWSC": {"score": 40}, "BRK": {"recent_break": True}, "DILX": {}, "PRICY": {"price": 2.0},
                        "FEWB": {"bounces": 1}, "WIDE": {"width_pct": 90}, "THIN": {"dollar_vol": 5000}})
r = piggy.rules(); assert r["score"] == 60 and r["bounces"] == 2 and r["n"] == 20 and r["on"] is True
m = {"price": 0.5, "score": 80.0, "bounces": 3, "width_pct": 30.0, "dollar_vol": 50000.0, "recent_break": False}
assert piggy.rule_ok(m, None, FX) and not piggy.rule_ok(m | {"score": 59}, None, FX) and not piggy.rule_ok(m, "ELOC", FX) and not piggy.rule_ok(m | {"price": 0.8}, None, FX)
assert not piggy.rule_ok(None, None, FX) and piggy.rule_ok(m, "UNKNOWN", FX)
# 자동 담기 최대 1개 → 안정성 가장 높은 GOOD1 만
config.PIGGY_AUTO_N = 1
res = piggy.auto_sync(FX, out=lambda *_: None)
assert res["added"] == ["GOOD1"] and res["removed"] == [] and piggy.items().set_index("ticker").loc["GOOD1", "category"] == piggy.AUTO_CAT
# 한도를 늘리면 GOOD2 추가 · 직접 담은 종목(LOWSC)은 기준 미달이어도 그대로 두고 '기준 이탈'로만 알림
config.PIGGY_AUTO_N = 5
piggy.add("LOWSC", "기타"); piggy.add("NOSCAN", "기타")
res = piggy.auto_sync(FX, out=lambda *_: None)
assert res["added"] == ["GOOD2"] and res["removed"] == [] and res["breakers"] == ["LOWSC"], res
assert piggy.rule_breakers(FX) == {"LOWSC"} and set(piggy.tickers_all()) == {"GOOD1", "GOOD2", "LOWSC", "NOSCAN"}      # 분석에 없는 NOSCAN 은 보류
# 다음 날 GOOD1 이 기준에서 벗어나면(안정성 30) 자동으로 담은 것은 뺌 · 분석에 없는 GOOD2 는 보류
put_scan("2026-10-21", {"GOOD1": {"score": 30}, "LOWSC": {"score": 40}, "NEW1": {"score": 85}})
res = piggy.auto_sync(FX, out=lambda *_: None)
assert res["removed"] == ["GOOD1"] and res["added"] == ["NEW1"] and sorted(res["breakers"]) == ["GOOD1", "LOWSC"] or res["breakers"] == ["LOWSC"], res
assert set(piggy.tickers_all()) == {"GOOD2", "LOWSC", "NOSCAN", "NEW1"}
# 자동 담기 끔 → 아무것도 안 함
config.PIGGY_AUTO_ADD = False
put_scan("2026-10-22", {"NEW2": {"score": 95}})
assert piggy.auto_sync(FX, out=lambda *_: None) == {"added": [], "removed": [], "breakers": []} and "NEW2" not in piggy.tickers_all()
config.PIGGY_AUTO_ADD = True
print("ALL OK")
