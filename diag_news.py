"""📰 뉴스 피드 점검 — 지금 쓰는 피드와 후보 피드에 PC에서 직접 접속해 보고 결과를 보여준다(DB는 바꾸지 않음).

실행(프로젝트 폴더에서):  python diag_news.py
HTTP 200 + 글 수 + '종목 뽑힘' 이 있는 주소가 쓸 수 있는 피드. 403 = 사이트가 프로그램 접속을 막음, 404 = 주소 틀림.
"""
import os
import sys

os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import requests

import news

CANDIDATES = [  # (이름, 주소) — 접속해 봐야 알 수 있는 후보들
    ("GlobeNewswire 상장사 RSS", "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies"),
    ("GlobeNewswire M&A RSS", "https://www.globenewswire.com/RssFeed/subjectcode/27-Mergers%20And%20Acquisitions/feedTitle/GlobeNewswire%20-%20Mergers%20And%20Acquisitions"),
    ("GlobeNewswire 전체 RSS", "https://www.globenewswire.com/RssFeed/"),
    ("PR Newswire 전체", "https://www.prnewswire.com/rss/news-releases-list.rss"),
    ("PR Newswire 헬스케어", "https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss"),
    ("PR Newswire 금융", "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss"),
    ("Business Wire 전체", "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFpRWQ=="),
    ("ACCESSWIRE 전체", "https://www.accesswire.com/rss/latest"),
]


def probe(name: str, url: str) -> None:
    try:
        r = requests.get(url, headers={"User-Agent": news.UA, "Accept": "application/atom+xml, application/rss+xml, application/xml"}, timeout=20)
        line = f"HTTP {r.status_code}"
        if r.status_code < 400:
            try:
                items = news.parse_feed(r.text)
                tick = [m.group(2) for it in items for m in [news.TICKER_RE.search(it["title"] + " " + it["summary"])] if m]
                line += f" · 글 {len(items)}개 · 종목 뽑힘 {len(tick)}개" + (f" (예: {', '.join(tick[:5])})" if tick else "")
                if items:
                    line += f" · 최신: {items[0]['published']} {items[0]['title'][:50]}"
                else:  # 차단 안내 페이지(HTML)도 200으로 올 수 있음
                    line += f" · 글 없음(차단 페이지일 수 있음) · 내용 앞부분: {r.text[:80]!r}"
            except Exception as e:  # noqa: BLE001
                line += f" · 피드 형식 아님({type(e).__name__}) · 내용 앞부분: {r.text[:80]!r}"
    except Exception as e:  # noqa: BLE001
        line = f"접속 실패: {type(e).__name__} {str(e)[:80]}"
    print(f"- {name}\n    {url[:110]}\n    → {line}")


if __name__ == "__main__":
    print("== 지금 쓰는 피드")
    for u in news.feeds():
        probe("현재", u)
    print("\n== 후보 피드")
    for n, u in CANDIDATES:
        probe(n, u)
    print("\n끝. 이 결과를 그대로 복사해 붙여 주세요.")
