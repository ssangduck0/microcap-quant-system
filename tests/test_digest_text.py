"""📝 공시 AI 요약 · 🔬 이벤트 연구 본문(2026-10-31):
① 요약이 공시 목록 페이지(문서 이름·크기 표)를 읽어 99%가 '발췌에 내용 없음' → 8-K·6-K 는 EX-99 보도자료 + 주 문서(첫 Item 부터), 그 밖은 주 문서 · 우리 종목만 · 424B2 제외
② 이벤트 연구 제목·첫 문단: 한 줄로 합친 본문을 줄 단위로 잘라 제목 = 파일 머리글 · 첫 문단 = 빈칸 → 줄 살린 원문에서 · 예전 제목은 화면에서 머리글 떼기."""
import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))
import os, sys, tempfile, json
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
sys.path.insert(0, os.environ["QS_ROOT"])
from contextlib import closing
from datetime import date, timedelta
import db, sec, secfeed, secdigest, eventlab as ev, secbackfill

db.init_db()
d = lambda n: (date.today() - timedelta(days=n)).isoformat()
B = "/Archives/edgar/data/7/000000000726000001/"
IDX = {"a1": f'<a href="/ix?doc={B}abcd-8k.htm">m</a><a href="{B}ex99-1.htm">p</a><a href="{B}ex10-1.htm">c</a>',
       "a2": f'<a href="{B}sc13g.htm">m</a>'}
COVER = "united states securities and exchange commission form 8-k current report commission file number 001-1 check the appropriate box " * 30
TEXT = {"abcd-8k.htm": COVER + "item 8.01 other events. the company announced a 1-for-10 reverse stock split effective " + d(-5) + ".",
        "ex99-1.htm": "abcd bio announces 1-for-10 reverse stock split. boston -- abcd bio (nasdaq: abcd) today announced the split will be effective " + d(-5) + ".",
        "ex10-1.htm": "securities purchase agreement boilerplate",
        "sc13g.htm": "0000-26-1.txt : 20261030 accession number: 0000-26-1 conformed submission type: schedule 13g filer: business address: 1 main st " * 20 + "names of reporting persons xyz capital percent of class represented by amount in row 9: 9.9%"}
fetched = []


class C:
    def _get(s, url, **kw):
        class R: pass
        r = R(); r.text = IDX["a1" if "a1" in url else "a2"]; return r
    def fetch_text(s, url, limit=0):
        fetched.append(url.split("/")[-1]); return TEXT[url.split("/")[-1]]


# ① 본문
t8 = secdigest.doc_text(C(), "https://www.sec.gov/a1-index.htm", "8-K")
assert t8.startswith("abcd bio announces") and "item 8.01 other events" in t8 and "commission file number" not in t8 and "securities purchase" not in t8, t8[:200]
assert secdigest.doc_text(C(), "https://www.sec.gov/a2-index.htm", "SCHEDULE 13G").startswith("names of reporting persons xyz capital")   # SEC 머리글 건너뜀
import rsplit
XML = ("<SEC-DOCUMENT>0000-26-2.txt : 20261030 ACCESSION NUMBER: 0000-26-2 <XML><edgarSubmission><formData><coverPageHeader><issuerInfo><issuerName>TAT Technologies Ltd</issuerName></issuerInfo></coverPageHeader>"
       "<coverPageHeaderReportingPersonDetails><reportingPersonName>Clal Insurance Enterprises Holdings Ltd</reportingPersonName><amountBeneficiallyOwned>1,234,567</amountBeneficiallyOwned>"
       "<classPercent>9.6</classPercent><typeOfReportingPerson>IC</typeOfReportingPerson></coverPageHeaderReportingPersonDetails></formData></edgarSubmission></XML>")
assert secdigest.xml13(XML) == "issuer: TAT Technologies Ltd; reporting person: Clal Insurance Enterprises Holdings Ltd; percent of class: 9.6; amount beneficially owned: 1,234,567; type of reporting person: IC"
class CX(C):
    def fetch_raw(s, url, limit=0): return XML
tx = secdigest.doc_text(CX(), "https://www.sec.gov/a2-index.htm", "SCHEDULE 13G/A")
assert tx.startswith("issuer: TAT Technologies Ltd; reporting person: Clal") and "percent of class: 9.6" in secdigest.excerpt(tx), tx[:200]   # XML 13G: 라벨 붙은 핵심 칸이 맨 앞
assert secdigest.xml13("<p>plain</p>") == ""
assert rsplit.ex99_links(["/m.htm", "/exh_991.htm", "/exhibit991.htm", "/ex-99.htm", "/ex10-1.htm"]) == ["/exh_991.htm", "/exhibit991.htm"]   # WPRT 6-K 같은 이름도
class Old:   # 목록 페이지를 못 받는 클라이언트 → 예전처럼 주소 그대로
    def fetch_text(s, url, limit=0): return "plain " + url
assert secdigest.doc_text(Old(), "http://x/a9", "8-K") == "plain http://x/a9"

with closing(db.connect()) as conn:
    secfeed.ensure_tables(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, date TEXT, kind TEXT, title TEXT, source TEXT, origin TEXT, created_at TEXT)")
    for a, t, fm in (("a1", "ABCD", "8-K"), ("a2", "XYZQ", "SCHEDULE 13G"), ("a3", "JPM", "8-K"), ("a4", "ABCD", "424B2"), ("a5", "ABCD", "424B5")):
        conn.execute("INSERT INTO sec_feed (accession, ticker, form, company, filed, updated, url) VALUES (?,?,?,?,?,?,?)", (a, t, fm, t, d(1), d(1) + "T12:00", f"https://www.sec.gov/{a}-index.htm"))
    conn.commit()
    p = secdigest.pending(conn, core={"ABCD", "XYZQ"})
    assert sorted(x["accession"] for x in p) == ["a1", "a2", "a5"], p        # 우리 종목 밖(JPM)·424B2 는 뺌
secfeed.core_tickers = lambda ttl=3600: {"ABCD", "XYZQ"}
calls = []
class R:
    status_code = 200
    def json(self):
        items = [{"accession": "a1", "summary_ko": "ABCD 가 1대10 병합을 시행해요.", "category": "병합", "grade": "A", "rs": {"date": d(-5), "ratio": "1:10"}, "holder": None},
                 {"accession": "a2", "summary_ko": "XYZ 가 9.9% 보유.", "category": "대량보유", "grade": "B", "rs": None, "holder": {"name": "XYZ Capital", "pct": 9.9, "type": "단순투자형"}},
                 {"accession": "a5", "summary_ko": "공모.", "category": "유상증자", "grade": "B", "rs": None, "holder": None}]
        return {"content": [{"type": "text", "text": json.dumps({"items": items}, ensure_ascii=False)}], "usage": {"input_tokens": 3000, "output_tokens": 600}}
def post(url, headers=None, json=None, timeout=None):
    calls.append(json); return R()
TEXT["a5"] = "x"
class C2(C):
    def _get(s, url, **kw):
        if "a5" in url:
            raise RuntimeError("no index")
        return C._get(s, url)
    def fetch_text(s, url, limit=0):
        return "prospectus supplement" if "a5" in url else C.fetch_text(s, url)
assert secdigest.run(client=C2(), post=post, out=lambda *_: None) == 3
body = json.dumps(calls[0], ensure_ascii=False)
assert "abcd bio announces" in body and "percent of class" in body and "commission file number" not in body, body[:300]   # 목록 페이지가 아니라 내용
with closing(db.connect()) as conn:
    assert secdigest.holders(conn).iloc[0]["pct"] == 9.9
    assert conn.execute("SELECT title FROM events WHERE ticker='ABCD'").fetchone()[0] == "역분할 1:10 시행"

# ② 이벤트 연구
RAW = ("<html><body><div>EX-99.1 2 ex99-1.htm EX-99.1</div><p>Exhibit 99.1</p><p>FOR IMMEDIATE RELEASE</p>"
       "<p><b>Abcd Bio Receives FDA Breakthrough Therapy Designation for ABX-1</b></p>"
       "<p>BOSTON, March 10, 2026 -- Abcd Bio (Nasdaq: ABCD) today announced that the FDA granted Breakthrough Therapy designation.</p></body></html>")
lines = sec.html_to_text(RAW, lower=False, keep_lines=True)
assert "\n" in lines and sec.html_to_text(RAW).count("\n") == 0
tl, ld = ev.headline(lines)
assert tl == "Abcd Bio Receives FDA Breakthrough Therapy Designation for ABX-1" and ld.startswith("BOSTON, March 10, 2026"), (tl, ld)
assert ev.headline(sec.html_to_text(RAW))[1] == ""                                       # 예전: 한 줄 본문 → 첫 문단 빈칸
assert ev.clean_title("ex-99.1 2 exhibit991jeld-wenxlaunc.htm ex-99.1 exhibit991jeld-wenxlaunc exhibit 99.1 jeld-wen announces commencement of exchange offer").startswith("jeld-wen announces")
assert ev.clean_title("ex-99.1 2 ea031000901ex99-1.htm press release dated oct. 28, 2026") == "press release dated oct. 28, 2026"
assert ev.clean_title("Abcd Bio Receives FDA") == "Abcd Bio Receives FDA" and ev.clean_title(None) == ""
IDXE = ('<div class="info">x</div>Accepted</div> <div class="info">2026-03-10 16:05:12</div>'
        f'<tr><td>1</td><td>8-K</td><td><a href="{B}abcd-8k.htm">m</a></td><td>8-K</td></tr><tr><td>2</td><td>EX-99.1</td><td><a href="{B}ex99-1.htm">p</a></td><td>EX-99.1</td></tr>')
with closing(db.connect()) as conn:
    secbackfill.ensure_tables(conn)
    conn.execute("INSERT INTO sec_hist VALUES ('0001-26-000001','ABCD','8-K','2026-03-10','7.01,9.01')"); conn.commit()
class FE:
    def cik_for(s, t): return 7
    def _get(s, u):
        class R: text = IDXE
        return R()
    def fetch_raw(s, u, limit=0): assert u.endswith("ex99-1.htm"); return RAW
    def fetch_text(s, u, limit=0): return sec.html_to_text(RAW)
assert ev.collect(FE(), out=lambda *_: None) == 1
with closing(db.connect()) as conn:
    r = dict(conn.execute("SELECT * FROM ev_docs").fetchone())
assert r["title"] == "Abcd Bio Receives FDA Breakthrough Therapy Designation for ABX-1" and r["lead"].startswith("BOSTON") and json.loads(r["types"]) == ["FDA·임상"] and r["sentiment"] == "호재", r
print("ALL OK")
