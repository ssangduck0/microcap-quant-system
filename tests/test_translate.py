import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import json, os, sys, tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db, config, aipick, translate, news
db.init_db()
now = datetime.now(timezone.utc)
with closing(db.connect()) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS news (id TEXT PRIMARY KEY, ticker TEXT, exchange TEXT, title TEXT, summary TEXT, published TEXT, link TEXT, feed TEXT, tags TEXT, sentiment TEXT, fetched TEXT)")
    rows = [("n1", "ABCD", "NASDAQ", "ABCD Announces $5 Million Registered Direct Offering", "ABCD priced an offering at $1.00 per share.", (now - timedelta(hours=2)).isoformat(), "http://x/1", "f", "[]", "악재", now.isoformat()),
            ("n2", "EFGH", "NASDAQ", "EFGH Receives FDA Fast Track Designation", "The FDA granted Fast Track.", (now - timedelta(hours=3)).isoformat(), "http://x/2", "f", "[]", "호재", now.isoformat()),
            ("n3", None, None, "SHAREHOLDER ALERT: Class Action Filed Against XYZ - Application Deadline", "Law firm reminds investors", (now - timedelta(hours=1)).isoformat(), "http://x/3", "f", "[]", "중립", now.isoformat()),
            ("n4", "OLD", "NASDAQ", "Old news", "old", (now - timedelta(days=30)).isoformat(), "http://x/4", "f", "[]", "중립", now.isoformat())]
    conn.executemany("INSERT INTO news VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    translate.ensure(conn); translate.ensure(conn)                                # 두 번 해도 안전
    p = translate.pending(conn)
    assert [x["id"] for x in p] == ["n1", "n2"], p                                 # 소송 광고·14일 지난 뉴스는 빼고 최신순
calls = []
class R:
    status_code = 200
    def __init__(self, items): self.items = items
    def json(self):
        return {"content": [{"type": "text", "text": json.dumps({"items": self.items}, ensure_ascii=False)}], "usage": {"input_tokens": 400, "output_tokens": 300}}
def post(url, headers=None, json=None, timeout=None):
    calls.append(json)
    return R([{"id": "n1", "title_ko": "ABCD, 500만 달러 등록 직접 공모 발표", "summary_ko": "주당 $1.00에 공모가 결정됐어요.", "category": "자금조달", "grade": "a", "score": "15"},
              {"id": "n2", "title_ko": "EFGH, FDA 패스트트랙 지정", "summary_ko": "FDA가 패스트트랙을 부여했어요.", "category": "FDA", "grade": "A", "score": 88},
              {"id": "ZZZ", "title_ko": "보낸 적 없는 항목", "summary_ko": ""}])
n = translate.run(post=post, out=lambda *_: None)
assert n == 2 and calls[0]["model"] == "claude-haiku-5-5" and "번역가" in calls[0]["system"] and "공모" in calls[0]["system"]
assert calls[0]["thinking"] == {"type": "disabled"} and "output_config" not in calls[0]                # 번역은 생각 끔(Haiku 5.5 허용)
assert aipick.spent_usd() > 0                                                      # AI 월 예산과 같은 지갑
with closing(db.connect()) as conn:
    assert conn.execute("SELECT title_ko FROM news WHERE id='n1'").fetchone()[0].startswith("ABCD, 500만")
    assert tuple(conn.execute("SELECT category, ai_grade, ai_score FROM news WHERE id='n1'").fetchone()) == ("자금조달", "A", 15)   # 소문자 등급·문자 점수도 정리
    assert tuple(conn.execute("SELECT ai_grade, ai_score FROM news WHERE id='n2'").fetchone()) == ("A", 88)
assert "grade" in calls[0]["system"] and "score" in calls[0]["system"]
assert translate.run(post=post, out=lambda *_: None) == 0 and len(calls) == 1        # 다시 번역하지 않음
# 예산 부족이면 멈춤
with closing(db.connect()) as conn:
    conn.execute("UPDATE news SET title_ko=NULL WHERE id='n2'"); conn.commit()
config.AI_MONTHLY_BUDGET_KRW = aipick.spent_usd() * aipick.FX
assert translate.run(post=post, out=lambda *_: None) == 0 and len(calls) == 1
config.AI_MONTHLY_BUDGET_KRW = 10000.0
config.NEWS_TRANSLATE = False
assert translate.run(post=post, out=lambda *_: None) == 0
config.NEWS_TRANSLATE = True

# 10/29 사고 ①: translate.ensure 로 열이 16개가 된 뒤에도 뉴스 받기(ingest)가 들어가야 함(예전엔 'VALUES 11개' → OperationalError → 10/25 부터 뉴스 0건)
with closing(db.connect()) as conn:
    assert len(conn.execute("PRAGMA table_info(news)").fetchall()) >= 16
k = news.ingest([{"id": "n9", "title": "ZZZZ Corp (NASDAQ: ZZZZ) Wins Contract", "summary": "award", "published": now.isoformat(), "link": "http://x/9"},
                 {"id": "n8", "title": "Some Private Company Announces Thing", "summary": "no ticker here", "published": (now + timedelta(minutes=1)).isoformat(), "link": "http://x/8"}], "f")
assert k == 2
with closing(db.connect()) as conn:
    assert tuple(conn.execute("SELECT ticker, sentiment FROM news WHERE id='n9'").fetchone()) == ("ZZZZ", "호재")
    assert tuple(conn.execute("SELECT ticker FROM news WHERE id='n8'").fetchone()) == (None,)
# 10/29 사고 ②: 답이 max_tokens 에 잘려 JSON 이 깨져도 온전한 항목은 건지고, 보낸 횟수를 세어 MAX_TRIES 번 넘으면 건너뜀(예전엔 0건 저장 + 매 사이클 재시도로 하루 $0.28 낭비)
cut_text = '{"items":[{"id":"n9","title_ko":"ZZZZ, 계약 수주","summary_ko":"수주했어요.","category":"계약","grade":"B","score":70},{"id":"n2","title_ko":"잘린'
assert [g["id"] for g in translate.parse_items(cut_text)] == ["n9"]
assert translate.parse_items("no json at all") == [] and translate.parse_items('{"items": "x"}') == []
assert translate.BATCH == 10 and translate.MAX_OUT == 8000 and translate.MAX_TRIES == 3
class RCut(R):
    def json(self):
        return {"content": [{"type": "text", "text": cut_text}], "usage": {"input_tokens": 400, "output_tokens": translate.MAX_OUT}}
logs = []
def post_cut(url, headers=None, json=None, timeout=None):
    calls.append(json); return RCut([])
with closing(db.connect()) as conn:
    conn.execute("UPDATE news SET title_ko=NULL, tr_tries=NULL WHERE id IN ('n2','n9')"); conn.commit()
    assert [x["id"] for x in translate.pending(conn)] == ["n9", "n2", "n8"], translate.pending(conn)   # 종목 있는 뉴스 먼저(최신순), 종목 없는 글은 뒤로
assert translate.run(post=post_cut, out=logs.append) == 1 and calls[-1]["max_tokens"] == 8000
assert any("잘림" in s for s in logs), logs
with closing(db.connect()) as conn:
    assert tuple(conn.execute("SELECT title_ko, tr_tries FROM news WHERE id='n9'").fetchone()) == ("ZZZZ, 계약 수주", 1)
    assert tuple(conn.execute("SELECT title_ko, tr_tries FROM news WHERE id='n2'").fetchone()) == (None, 1)
    conn.execute("UPDATE news SET tr_tries=3 WHERE id IN ('n2','n8')"); conn.commit()
    assert translate.pending(conn) == []                                                   # 3번 실패한 건 더 안 보냄(돈 낭비 방지)
    conn.execute("UPDATE news SET tr_tries=NULL, title_ko=NULL WHERE id='n8'"); conn.execute("DELETE FROM news WHERE id IN ('n8','n9')"); conn.commit()

# 화면: 한국어 제목 크게 · 원문 작게 · 한국어로 검색
news.recent = lambda days=14: __import__("db").read_df("SELECT * FROM news")
from streamlit.testing.v1 import AppTest
def _app():
    import sys
    sys.path.insert(0, __import__("os").environ["QS_ROOT"])
    import news, news_ui, db
    news.recent = lambda days=14: db.read_df("SELECT * FROM news")
    news_ui.render()
at = AppTest.from_function(_app, default_timeout=120).run()
assert not at.exception, [e.value for e in at.exception]
md = " ".join(m.value for m in at.markdown)
assert "ABCD, 500만 달러 등록 직접 공모 발표" in md and "원문: ABCD Announces" in md, md[:800]
assert "A등급 · 15점 · 자금조달" in md                                                   # 등급·점수·분류 칩
at.toggle(key="nw_ko").set_value(False).run()
md2 = " ".join(m.value for m in at.markdown)
assert "ABCD Announces" in md2 and "Registered Direct Offering" in md2 and "500만 달러" not in md2
assert "번역 대기" not in md2                                                               # 영어 보기에선 칩 없음
at.toggle(key="nw_ko").set_value(True).run(); at.toggle(key="nw_nas").set_value(False).run()
at.text_input(key="nw_q").set_value("등록 직접 공모").run()                                  # 한국어 번역으로도 검색됨
md3 = " ".join(m.value for m in at.markdown)
assert "ABCD, 500만" in md3 and "EFGH Receives" not in md3
print("ALL OK")
