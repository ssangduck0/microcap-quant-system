"""10-24 실제 화면(방문객 링크) 검토에서 찾은 문제들의 수정 확인."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
from contextlib import closing
from datetime import date, timedelta
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None); os.environ.pop("QUANT_TEST_PAGE", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, halts
db.init_db(); halts.fetch = lambda *a, **k: []
T = date.today()

# 1) 💰 펀드스캔이 멈추던 문제: 런웨이가 수천 년이면 날짜 계산이 넘쳤음 → 50년 넘으면 '바닥 없음'
import runway
assert runway.months_to_date(T, 1e9) is None and runway.months_to_date(T, float("inf")) is None and runway.months_to_date(T, float("nan")) is None
assert runway.months_to_date(T, 3) == (T + timedelta(days=91)).isoformat()
with closing(db.connect()) as conn:
    runway.save(conn, "TINY", {"cash": 5e6, "cash_asof": (T - timedelta(days=30)).isoformat(), "monthly_burn": 0.001}); conn.commit()
    r = runway.now("TINY", conn)
assert r["floor"] is None and r["runway_now"] > 1e6 and "50년" in runway.label(r), r       # 예전엔 OverflowError
import company
db.save_report("TINY", {"ticker": "TINY", "runway": {"cash": 5e6, "cash_asof": T.isoformat(), "monthly_burn": 0.001, "runway_months": 5e9}})
assert company.runway("TINY")["end"] is None                                                 # 🏢 기업 분석도 같은 문제(OverflowError 는 안 잡고 있었음)

# 2) 상장유지 기준 금액: 회사의 현재 금액을 기준으로 잘못 읽어 '$0M' 이던 것
import listing
txt = ("On October 13, 2026, the Company received a letter from Nasdaq stating that its stockholders' equity of $0.3 million as of June 30, 2026 "
       "did not comply with the minimum stockholders' equity requirement of $2.5 million for continued listing. The Company has until April 11, 2027 to regain compliance.")
p = listing.parse(txt, "2026-10-13")
assert p["threshold"] == "$2.5M" and p["deadline"] == "2027-04-11", p
p2 = listing.parse("Nasdaq notified the Company that its stockholders' equity of $0 million was below the requirement.", "2026-10-13")
assert p2["threshold"] == "$2.5M", p2                                                         # 기준 금액이 안 보이면 기본값

# 3) 작은 금액: $0.0M → K 단위
import pressure
assert pressure.money(130_000) == "$130K" and pressure.money(2_500_000) == "$2.50M" and pressure.money(None) == "-" and pressure.money(-50_000) == "-$50K"

# 4) 리포트 한눈에: 야후 유통주식으로는 회전율·초소형 신호를 세지 않음
import glance, shares
assert "야후" in shares.best("ZZZZ", 890_000)[1]

# 5) 뉴스: 소송 광고 · 우리 종목
import news
assert news.is_lawsuit_ad("Duolingo, Inc. Notice of December 7, 2026 Application Deadline for Class Action Lawsuit - Contact Lewis Kahn, Esq.")
assert not news.is_lawsuit_ad("Amber International Holding Limited Announces Results") and news.classify("Rosen Law Firm reminds investors who purchased ...")[1] == "중립"

# 6) 화면: 메뉴 묶음 순서 · 방문객 토큰 유지 · 방문객에게 무거운 버튼 숨김 · EFFECT 중복
now = db.utcnow_iso()
with closing(db.connect()) as conn:
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "ZZZ", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 1.2, "low_20d": 0.8,
        "drawdown_pct": -10.0, "day_change_pct": -1.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 1e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
from streamlit.testing.v1 import AppTest
APP = __import__("os").path.join(__import__("os").environ["QS_ROOT"], "dashboard.py")
at = AppTest.from_file(APP, default_timeout=180)
at.query_params["v"] = "full"
at.run(); assert not at.exception, [e.value for e in at.exception]
labels = [l.label for l in at.get("page_link")]
i_home, i_guide, i_rank, i_brief = labels.index("홈"), labels.index("가이드북"), labels.index("종합 순위"), labels.index("공시 알림")
assert i_guide < i_rank < i_brief, labels[:8]                                                  # 홈 묶음(홈·가이드북) 다음에 오늘 묶음

import access
tok = access.create("검토", 24)
at = AppTest.from_file(APP, default_timeout=180)
at.query_params["guest"] = tok
at.run(); assert not at.exception, [e.value for e in at.exception]
[b for b in at.button if b.label == "위 내용에 동의하고 보기"][0].click().run()
del at.query_params["guest"]                                                                  # 다른 화면으로 옮겨 주소에서 토큰이 빠진 상황
at.run(); assert not at.exception
assert at.query_params.get("guest") in (tok, [tok]), dict(at.query_params)                  # 주소에 토큰을 다시 붙여 둠(새로고침해도 안 끊김)
assert not any("주소 끝에 ?v=lite" in c.value for c in at.caption)                            # 방문객에겐 맞지 않는 주소 안내 숨김

os.environ["QUANT_TEST_PAGE"] = "squeeze"
at2 = AppTest.from_file(APP, default_timeout=180); at2.query_params["guest"] = tok; at2.run()
if [b for b in at2.button if b.label == "위 내용에 동의하고 보기"]:
    [b for b in at2.button if b.label == "위 내용에 동의하고 보기"][0].click().run()
assert not at2.exception, [e.value for e in at2.exception]
assert not [b for b in at2.button if "공매도 잔고 지금 받기" in b.label]                      # 방문객은 서버에 무거운 작업을 못 시킴

os.environ["QUANT_TEST_PAGE"] = "effect"
import accum
accum.filings_map = lambda conn, tks, since: {"DFNS": [(T.isoformat(), "EFFECT"), (T.isoformat(), "EFFECT"), (T.isoformat(), "S-1")]}
import watch_ui
watch_ui.prices = lambda tks: {}
at3 = AppTest.from_file(APP, default_timeout=180); at3.query_params["v"] = "full"; at3.run()
assert not at3.exception, [e.value for e in at3.exception]
assert any("1건 · 최신순" in c.value for c in at3.caption), [c.value for c in at3.caption]   # 같은 날 EFFECT 두 건 → 한 줄
os.environ.pop("QUANT_TEST_PAGE", None)
# 7) SEC 재무: 회사가 다른 항목 이름으로 바꿔 보고하면 '가장 최근' 항목을 씀(예전엔 첫 항목의 2022년 값 → 런웨이 0.0개월·현금 −4,637억 원)
import report
cf = {"facts": {"us-gaap": {
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": "2022-10-31", "val": 50e6}]}},
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": {"units": {"USD": [{"end": (T - timedelta(days=60)).isoformat(), "val": 80e6}]}}}}}
rw = report.runway_from_facts(cf)
assert rw["cash"] == 80e6 and rw["cash_asof"] == (T - timedelta(days=60)).isoformat() and rw["v"] == 4, rw
# 8) 펀드스캔: 오래된 재무 → 런웨이 비움(재무 오래됨) · 1년 넘은 XBRL 워런트 안 씀 · 현재가 50배 넘는 행사가(병합 미반영 추정) 제외
import fundscan, json as _j
with closing(db.connect()) as conn:
    fundscan.ensure_tables(conn)
    conn.execute("INSERT INTO fs_deals (accession, ticker, filed, form, kind, proceeds, warrants) VALUES ('d1','OLDF',?, '424B4','공모',1e6,?)",
                 ((T - timedelta(days=30)).isoformat(), _j.dumps([{"name": "Old", "qty": 1000, "price": 900.0}, {"name": "New", "qty": 1000, "price": 1.5}])))
    conn.execute("INSERT OR REPLACE INTO fs_xbrl VALUES ('OLDF', ?, 'x')", (_j.dumps({"warrants": {"val": 5e5, "end": "2022-10-31"}, "wavg_price": {"val": 7.6, "end": "2022-10-31"}, "shares_hist": []}),))
    runway.save(conn, "OLDF", {"cash": 5e6, "cash_asof": "2023-01-31", "monthly_burn": 1e6, "v": 4})
    db.upsert_snapshot(conn, {"date": T.isoformat(), "ticker": "OLDF", "exchange": "NASDAQ", "first_seen": now, "last_seen": now, "price": 1.0, "high_20d": 1.2, "low_20d": 0.8,
        "drawdown_pct": -10.0, "day_change_pct": -1.0, "volume_mult": 1.0, "buy_pressure": 50.0, "float_shares": 1e7, "atr14": 0.01, "quant_score": 50.0, "quant_detail": "{}",
        "pump_score": 40.0, "pump_detail": '{"checks":[]}', "dilution_status": "CLEAN", "excluded": 0})
    conn.commit()
    a = fundscan.analyze("OLDF", conn)
assert a["runway_now"] is None and a["runway_info"]["stale"], a.get("runway_now")
assert abs(a["need"] - 50.0) < 1e-6, a["need"]                                       # 900달러 행사가(현재가 900배)는 빼고 1.5달러 기준 +50%
assert any("병합 미반영" in x for x in a["adj_note"]) if "adj_note" in a else True
import fundscan_ui
assert fundscan_ui._rw_txt(a).startswith("재무 오래됨")
# 9) 🏢 기업 분석 런웨이: 종목 리포트가 없어도 런웨이 저장소로(예전엔 전부 '-')
with closing(db.connect()) as conn:
    runway.save(conn, "NOREP", {"cash": 6e6, "cash_asof": (T - timedelta(days=30)).isoformat(), "monthly_burn": 1e6, "v": 4}); conn.commit()
cr = company.runway("NOREP")
assert cr["months"] is not None and 4.5 < cr["months"] < 5.5 and cr["end"] and cr["note"].startswith("런웨이"), cr
co = company.runway("OLDF")                                                                       # 오래된 재무 → 런웨이 비우고 이유
assert co["months"] is None and co["end"] is None and "오래됨" in co["note"], co
# 10) BLS 수입물가: 차단 페이지(HTML)·HTTP 오류·BLS 실패 메시지를 알아보게(예전엔 JSONDecodeError 만)
import macro
class _R:
    def __init__(self, code=200, text="", j=None): self.status_code, self.text, self._j = code, text, j
    def json(self):
        if self._j is None: raise ValueError("no json")
        return self._j
for resp, need in ((_R(403, "<html>Access Denied"), "HTTP 403"), (_R(200, "<html>blocked"), "JSON 이 아닌 응답"),
                   (_R(200, j={"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]}), "REQUEST_NOT_PROCESSED")):
    try:
        macro.fetch_imp(http_get=lambda u, r=resp: r); raise AssertionError("실패해야 함")
    except RuntimeError as e:
        assert need in str(e), e
# 11) 홈 브리핑: 최근 3일 공시(주말에도 0건이 아니게)
import home_ui, secfeed
with closing(db.connect()) as conn:
    secfeed.ensure_tables(conn)
    conn.execute("INSERT INTO sec_feed (accession, ticker, form, company, filed, updated, items, tags, sentiment, score) VALUES ('h1','ZZZ','8-K','Z',?,?,'','[]','호재',1)",
                 ((T - timedelta(days=2)).isoformat(), f"{(T - timedelta(days=2)).isoformat()}T09:00:00-04:00"))
    conn.commit()
assert home_ui.briefing(False)["news_count"]["전체"] >= 1
# 12) 주말 날짜: 금요일 시간외 봉이 UTC 로 오면 토요일로 찍히던 문제 · yfinance 주말 줄
import market, pandas as _pd
assert market.et_trade_date(_pd.Timestamp("2026-10-17 00:30", tz="UTC")) == "2026-10-16"      # 금 20:30 ET
assert market.et_trade_date(_pd.Timestamp("2026-10-18")) == "2026-10-16" and market.et_trade_date(_pd.Timestamp("2026-10-16 15:00", tz="America/New_York")) == "2026-10-16"
# 13) 일정 중복: 같은 종목·날·종류 자동 일정은 하나만(수동은 그대로)
import watch
ev = _pd.DataFrame([{"id": 1, "ticker": "CYAB", "date": "2026-11-09", "kind": "상장유지 기한", "title": "S-1", "source": "", "origin": "자동", "created_at": "a"},
                    {"id": 2, "ticker": "CYAB", "date": "2026-11-09", "kind": "상장유지 기한", "title": "S-1/A", "source": "", "origin": "자동", "created_at": "b"},
                    {"id": 3, "ticker": "CYAB", "date": "2026-11-09", "kind": "상장유지 기한", "title": "내 메모", "source": "", "origin": "수동", "created_at": "c"}])
d = watch.dedupe_events(ev)
assert len(d) == 2 and set(d["title"]) == {"S-1/A", "내 메모"}, d
# 14) 표 정리: 소수 한 자리 · 가격은 네 자리 · None → '-'
import ui_kit
t = ui_kit.tidy(_pd.DataFrame({"그날 등락(%)": [-33.5516, None], "진입가(종가,$)": [0.2233, 1.5], "판정": [None, "x"]}))
assert list(t["그날 등락(%)"]) == ["-33.6", "-"] and list(t["진입가(종가,$)"]) == ["0.2233", "1.5000"] and list(t["판정"]) == ["-", "x"], t
# 15) 🐷 저금통: 실제 사용(전체 화면 테스트 모드가 아님)에서는 고른 칸 하나만 계산 — '공매도 흐름'은 안 고르면 계산 안 함
import shortflow_ui
_calls = []
_orig_tab = shortflow_ui.render_tab
shortflow_ui.render_tab = lambda *a, **k: _calls.append(1)
os.environ["QUANT_TEST_PAGE"] = "piggy"
at5 = AppTest.from_file(APP, default_timeout=180); at5.query_params["v"] = "full"; at5.run()
assert not at5.exception, [e.value for e in at5.exception]
assert not _calls, "공매도 흐름을 안 골랐는데 계산함"
at5.button_group(key="pg_sec").set_value("🩳 공매도 흐름 (스승님 꿀팁)").run()
assert not at5.exception and _calls, "공매도 흐름을 고르면 계산해야 함"
shortflow_ui.render_tab = _orig_tab
os.environ.pop("QUANT_TEST_PAGE", None)
# 16) 병합 후 레이더: 병합일 종가만 병합 전 단위(25배)로 남아 있으면 맞춤 — 예전엔 가격이 그대로여도 −96% 로 나왔음
import numpy as np, rsplit, pandas as pd
idx2 = pd.bdate_range(start=pd.Timestamp.today().normalize() - pd.Timedelta(days=50), periods=30)
close = np.r_[np.full(10, 0.2), [5.0], np.full(19, 5.0)]          # 10일째(인덱스 10)가 25:1 병합일 — 병합일 값만 조정 안 된 25배? 아님: 여기선 정상 조정
df_ok = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Stock Splits": [0] * 10 + [0.04] + [0] * 19}, index=idx2)
bad = close.copy(); bad[10] = 125.0                                 # 병합일 종가만 25배(병합 전 단위)로 남은 경우
df_bad = df_ok.assign(Close=bad, High=np.maximum(bad, close), Low=np.minimum(bad, close))
_, _, cur_ok = rsplit.analyze_frame(df_ok); _, _, cur_bad = rsplit.analyze_frame(df_bad)
assert abs(cur_ok["dd"]) < 1e-9 and abs(cur_bad["dd"]) < 1e-9, (cur_ok, cur_bad)    # 둘 다 '그대로(0%)'(예전엔 bad 가 −96%)
real = close.copy(); real[11:] = 2.5                                # 실제로 반토막 난 경우는 그대로 −50%
_, _, cur_real = rsplit.analyze_frame(df_ok.assign(Close=real, High=real, Low=real))
assert abs(cur_real["dd"] + 50) < 1e-9, cur_real
# 17) 수입물가: BLS 503 이면 FRED(IR) 예비 · 둘 다 실패면 두 이유 모두
_t = date.today(); _base = _t.year * 12 + _t.month - 1 - 29           # 오늘 기준 최근 29개월(지난달까지)
_ym = [f"{(_base + m) // 12}-{(_base + m) % 12 + 1:02d}" for m in range(1, 30)]
csv = "observation_date,IR\n" + "\n".join(f"{ym}-01,{140 + m * 0.5}" for m, ym in zip(range(1, 30), _ym))
def _get(u):
    return _R(503, "Service Unavailable") if "bls.gov" in u else _R(200, csv)
d = macro.fetch_imp(http_get=_get)
assert d["month"] == _ym[-1] and abs(d["mom"] - (154.5 / 154.0 - 1) * 100) < 1e-9 and d["yoy"] is not None and "FRED" in d["source"] and len(d["hist"]) == 24
_dbn = {"series": {"docs": [{"period": _ym + ["9999-12"], "value": [140 + m * 0.5 for m in range(1, 30)] + ["NA"]}]}}
d2 = macro.fetch_imp(http_get=lambda u: _R(503, "x") if "bls.gov" in u else (_R(200, j=_dbn) if "nomics" in u else _R(503, "x")))
assert d2["month"] == _ym[-1] and "DBnomics" in d2["source"]
_old = {"series": {"docs": [{"period": [f"{2023 + (m - 1) // 12}-{(m - 1) % 12 + 1:02d}" for m in range(1, 26)], "value": [140 + m * 0.5 for m in range(1, 26)]}]}}
try:  # 갱신이 멈춘 복사본(2025-01 까지)은 받지 않음
    macro.fetch_imp(http_get=lambda u: _R(503, "x") if "bls.gov" in u else (_R(200, j=_old) if "nomics" in u else _R(503, "x"))); raise AssertionError("오래된 자료는 실패해야 함")
except RuntimeError as e:
    assert "오래됨" in str(e), e                                  # BLS 막히면 DBnomics(‘NA’ 칸은 건너뜀)
try:
    macro.fetch_imp(http_get=lambda u: _R(503, "x")); raise AssertionError("실패해야 함")
except RuntimeError as e:
    assert "HTTP 503" in str(e) and "FRED" in str(e) and "DBnomics" in str(e)
print("ALL OK")
