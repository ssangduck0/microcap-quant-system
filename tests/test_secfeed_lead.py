"""🔔 공시 피드 본문(2026-10-31): ① '핵심 문장'이 소문자 본문에서 'On October …' 를 못 찾아 전부 빈칸 → 대소문자 살린 주 문서(iXBRL '/ix?doc=')에서
② 병합 공시는 판정용 본문(첫 첨부 — EX-3.1 정관 증서 등)에 시행일이 없으면 주 문서 + EX-99 로 다시 읽어 🗓 역분할 시행 기록(ATYR 1:40) · 판정(태그·점수)은 그대로."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, sec, secfeed as sf, rsplit, watch

db.init_db()
D = date.today() + timedelta(days=2)
DS = f"{D:%B} {D.day}, {D.year}"
B = "/Archives/edgar/data/1339970/000133997026000071/"
IDX8 = f'<a href="/ix?doc={B}atyr-8k.htm">main</a><a href="{B}ex3-1.htm">ex3</a><a href="{B}0001339970-26-000071.txt">all</a>'   # 실제 목록 페이지처럼 주 문서는 iXBRL 링크
IDX6 = f'<a href="/ix?doc={B}chow-6k.htm">main</a><a href="{B}ex99-1.htm">ex99</a>'
MAIN8 = (f"<html><body><p>FORM 8-K</p><p>Item 5.03 Amendments to Articles of Incorporation.</p><p>On October 27, 2026, aTyr Pharma, Inc. (the &ldquo;Company&rdquo;) filed a "
         f"certificate of amendment to effect a one-for-forty (1-for-40) reverse stock split of its outstanding common stock. The amendment will be effective at 5:00 p.m. "
         f"Eastern Time on {DS}. The common stock will begin trading on a split-adjusted basis on {DS}.</p><p>Item 9.01 Financial Statements and Exhibits.</p></body></html>")
EX3 = "certificate of amendment of the restated certificate of incorporation. reverse stock split. each forty shares of common stock shall be combined into one share."
COVER6 = "<html><body>FORM 6-K REPORT OF FOREIGN PRIVATE ISSUER Exhibit 99.1 Press release</body></html>"
EX99 = "<html><body><p>On October 28, 2026, Chow Corp (the &ldquo;Company&rdquo;) announced the closing of a private placement of 86,207 shares. The proceeds will fund working capital.</p></body></html>"
RAW = {B + "atyr-8k.htm": MAIN8, B + "chow-6k.htm": COVER6, B + "ex99-1.htm": EX99}
calls = []


class FC:   # 실제 SecClient 처럼: fetch_text = 소문자 본문 · fetch_raw = HTML 원문
    def _get(s, url, **kw):
        class R: pass
        r = R(); r.text = IDX8 if "atyr" in url else IDX6; return r
    def fetch_raw(s, url, limit=0):
        calls.append(("raw", url.split("/")[-1])); return RAW[url.replace("https://www.sec.gov", "")]
    def fetch_text(s, url, limit=0):
        calls.append(("text", url.split("/")[-1]))
        p = url.replace("https://www.sec.gov", "")
        return EX3 if p.endswith("ex3-1.htm") else sec.html_to_text(RAW[p])


assert sec.html_to_text("<p>On October</p>").strip() == "on october" and sec.html_to_text("<p>On October</p>", lower=False).strip() == "On October"
assert sf.lead_of(sec.html_to_text(MAIN8)) == ""                                    # 예전: 소문자 본문 → 항상 빈칸
assert sf.lead_of(sec.html_to_text(MAIN8, lower=False)).startswith("On October 27, 2026, aTyr Pharma")
assert rsplit.doc_links(IDX8) == [B + "atyr-8k.htm", B + "ex3-1.htm", B + "0001339970-26-000071.txt"] and rsplit.ex99_links(rsplit.doc_links(IDX6)) == [B + "ex99-1.htm"]
assert rsplit.upcoming_from_text(EX3) is None                                        # 첨부엔 시행일이 없음 → 예전엔 일정을 놓침

with closing(db.connect()) as conn:
    sf.ensure_tables(conn); watch.ensure_tables(conn)
    ins = "INSERT INTO sec_feed (accession, ticker, cik, form, updated, items, url, enriched, created_at) VALUES (?,?,?,?,?,?,?,0,'x')"
    conn.execute(ins, ("a8", "ATYR", 1339970, "8-K", "2026-10-27T09:03", "5.03,9.01", "https://www.sec.gov/Archives/edgar/data/1339970/000133997026000071/atyr-index.htm"))
    conn.execute(ins, ("a6", "CHOW", 1, "6-K", "2026-10-28T17:00", "", "https://www.sec.gov/Archives/edgar/data/1/chow-index.htm"))
    conn.commit()
sf.core_tickers = lambda ttl=3600: {"ATYR", "CHOW"}
assert sf.enrich(FC(), limit=5) == 2
with closing(db.connect()) as conn:
    rows = {r["accession"]: dict(r) for r in conn.execute("SELECT * FROM sec_feed")}
    ev = conn.execute("SELECT ticker, date, title FROM events WHERE kind='역분할 시행'").fetchall()
a8, a6 = rows["a8"], rows["a6"]
sc, tags, sent = sf.classify("8-K", ["5.03", "9.01"], EX3)
assert (a8["score"], __import__("json").loads(a8["tags"]), a8["sentiment"]) == (sc, tags, sent), a8   # 판정은 예전 본문(첫 첨부) 그대로
assert a8["lead"].startswith("On October 27, 2026, aTyr Pharma, Inc. (the “Company”) filed"), a8["lead"]
assert a6["lead"].startswith("On October 28, 2026, Chow Corp"), a6["lead"]                            # 6-K 표지뿐 → EX-99 보도자료에서
assert [tuple(x) for x in ev] == [("ATYR", D.isoformat(), "역분할 1:40 시행")], ev                    # 주 문서로 다시 읽어 기록(확정까지)

# 가짜 클라이언트에 fetch_raw 가 없으면 핵심 문장만 빈칸(오류 없음)
class FC2(FC):
    fetch_raw = None
with closing(db.connect()) as conn:
    conn.execute("UPDATE sec_feed SET enriched=0, lead=NULL"); conn.execute("DELETE FROM events"); conn.commit()
assert sf.enrich(FC2(), limit=5) == 2
with closing(db.connect()) as conn:
    assert {r[0] for r in conn.execute("SELECT COALESCE(lead,'') FROM sec_feed")} == {""}
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='역분할 시행'").fetchone()[0] == 1

# 아침 작업의 한 번 소급: 병합 태그·5.03 공시만 · 주 문서 + EX-99 항상
with closing(db.connect()) as conn:
    conn.execute("DELETE FROM events"); conn.execute("UPDATE sec_feed SET filed=?", (date.today().isoformat(),)); conn.commit()
calls.clear()
r = rsplit.backfill_upcoming(FC(), days=30, out=lambda *_: None, only_tagged=True, min_main=10**9)
assert r == {"read": 1, "new": 1} and ("text", "atyr-8k.htm") in calls and not any("chow" in c[1] for c in calls), (r, calls)   # CHOW 6-K 는 병합 태그가 없어 안 읽음
print("ALL OK")
