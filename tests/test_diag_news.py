import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile, io, contextlib
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__)))); sys.path.insert(0, _os_qs.environ["QS_ROOT"])
import db; db.init_db()
import requests, news, diag_news
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>1</id><title>ABC Corp (NASDAQ: ABCD) Announces FDA Approval</title>
<summary>x</summary><published>2026-10-23T10:00:00Z</published><link href="https://x/1"/></entry></feed>"""
class R:
    def __init__(self, code, text=""): self.status_code, self.text = code, text
def fake(url, **k):
    if "ok" in url: return R(200, ATOM)
    if "html" in url: return R(200, "<html>blocked</html>")
    if "boom" in url: raise requests.ConnectionError("no route")
    return R(403)
requests.get = fake
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for n, u in [("a", "https://ok"), ("b", "https://deny"), ("c", "https://boom"), ("d", "https://html")]:
        diag_news.probe(n, u)
out = buf.getvalue()
assert "HTTP 200 · 글 1개 · 종목 뽑힘 1개 (예: ABCD)" in out and "HTTP 403" in out and "접속 실패: ConnectionError" in out and "글 없음(차단 페이지일 수 있음)" in out and "blocked" in out, out
# refresh 오류에 HTTP 번호가 보임
r = news.refresh(http_get=lambda u: R(404), force=True)
assert all("HTTP 404" in v for v in r.values()), r
# 기본 피드: 막힌 GlobeNewswire 만 저장돼 있으면 새 기본값(PR Newswire), 다른 주소가 섞여 있으면 그대로
assert all("prnewswire.com" in u for u in news.feeds())
news.set_feeds(["https://www.globenewswire.com/AtomFeed/x", "https://www.globenewswire.com/RssFeed/y"])
assert news.feeds() == news.DEFAULT_FEEDS
news.set_feeds(["https://www.globenewswire.com/AtomFeed/x", "https://my.feed/rss"])
assert news.feeds() == ["https://www.globenewswire.com/AtomFeed/x", "https://my.feed/rss"]
print("ALL OK")
