import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"]=os.path.join(tmp,"q.db"); os.environ["SEC_USER_AGENT"]="T t@e.com"
sys.path.insert(0,__import__("os").environ["QS_ROOT"])
import db, secfeed as sf
db.init_db()
ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?><feed xmlns="http://www.w3.org/2005/Atom"><title>Latest Filings</title>
<entry><title>8-K - Odyssey Marine Exploration Inc (0000798528) (Filer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/798528/000079852826000050/0000798528-26-000050-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-10-16 &lt;b&gt;AccNo:&lt;/b&gt; 0000798528-26-000050 &lt;b&gt;Size:&lt;/b&gt; 300 KB&lt;br&gt;Item 5.03: Amendments to Articles&lt;br&gt;Item 8.01: Other Events&lt;br&gt;Item 9.01: Financial Statements</summary>
<updated>2026-10-16T21:02:00-04:00</updated><category scheme="https://www.sec.gov/" label="form type" term="8-K"/><id>urn:tag:sec.gov,2008:accession-number=0000798528-26-000050</id></entry>
<entry><title>424B5 - Scinai Immunotherapeutics Ltd. (0001607310) (Filer)</title><link href="https://www.sec.gov/Archives/edgar/data/1607310/x-index.htm"/>
<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-10-16 &lt;b&gt;AccNo:&lt;/b&gt; 0001607310-26-000011</summary><updated>2026-10-16T21:01:00-04:00</updated>
<id>urn:tag:sec.gov,2008:accession-number=0001607310-26-000011</id></entry>
<entry><title>8-K - Not Ours Inc (0000000001) (Filer)</title><link href="u"/><summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-10-16</summary><updated>x</updated><id>urn:tag:sec.gov,2008:accession-number=0000000001-26-1</id></entry>
</feed>"""
p = sf.parse_atom(ATOM); print([(x["form"], x["cik"], x["items"]) for x in p])
assert p[0]["form"] == "8-K" and p[0]["cik"] == 798528 and p[0]["items"] == ["5.03", "8.01", "9.01"] and p[0]["filed"] == "2026-10-16" and p[0]["accession"] == "0000798528-26-000050"
assert p[1]["form"] == "424B5" and len(p) == 3 and sf.parse_atom("not xml") == []
assert sf.classify("8-K", ["5.03", "8.01"], "the Company announced a 1-for-25 reverse stock split") == (-2, ["정관 변경", "주식 병합"], "악재")
assert sf.classify("424B5", [], "") == (-2, ["희석 위험"], "악재")
assert sf.classify("8-K", ["8.01"], "announced a $5 million share repurchase program")[2] == "호재"
assert sf.classify("8-K", ["1.01"], "entered into a strategic partnership")[2] == "약한 호재"
assert sf.classify("8-K", ["1.01"], "partnership; securities purchase agreement for a private placement")[2] == "혼재"
assert sf.classify("8-K", ["2.02"], "")[2] == "중립" and sf.classify("SC 13G", [], "")[1] == ["대량보유"]
assert sf.classify("SCHEDULE 13D/A", [], "")[1] == ["대량보유"] and "SCHEDULE 13D" in sf.TYPES and "SCHEDULE 13G" in sf.TYPES   # 2026-10-27 EDGAR 새 양식명
class FC:
    def __init__(s): s.urls = []
    def _get(s, url, **kw):
        s.urls.append(url)
        class R: pass
        r = R(); r.text = ATOM if "getcurrent" in url else '<a href="/Archives/edgar/data/798528/000079852826000050/omex-8k.htm">doc</a>'; return r
    def fetch_text(s, url, limit=0): return "reverse stock split approved; going concern"
c = FC(); n = sf.poll(c, {798528: "OMEX", 1607310: "SCNI"}, types=["8-K"]); assert n == 2 and sf.poll(c, {798528: "OMEX", 1607310: "SCNI"}, types=["8-K"]) == 0   # 같은 공시 중복 없음
assert sf.enrich(c, 10) == 2
f = sf.feed(days=3650).set_index("ticker"); print(f[["form", "sentiment", "tags", "score"]].to_string())
assert f.loc["OMEX", "sentiment"] == "악재" and "주식 병합" in f.loc["OMEX", "tags"] and "계속기업 의문" in f.loc["OMEX", "tags"]
assert sf.item_names("5.03,8.01") == ["정관 변경(병합·수권 등)", "기타 중요 사항"]
print("ALL OK")
