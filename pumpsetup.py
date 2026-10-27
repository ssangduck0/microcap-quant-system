"""🕵️ 세력·셋업 — 스승님 꿀팁(극펌핑 공통점·작전주 셋업·흔적·병합+수권 증가)을 SEC 공시·공매도 데이터로 판정.

펌핑 셋업 신호(+): 병합 안건과 수권주식 증액이 함께(자본 재구성 = 대규모 희석 예고) · 수권주식 증액 · 병합 안건 ·
  케이맨/영국령 버진아일랜드 설립 · F-1(S-1) 등록서류가 보통주+워런트 구조 · 조달 상대방이 1곳(세력 1집단 추정) ·
  주식 수가 적은데 병합 안건 · 흔적(대차 넉넉 + 다크풀 비중 높음)
피할 신호(−): ATM·ELOC(시장가 희석) · 조달 상대방 2곳 이상(이해관계 혼재) · 최근 8-K 악재(물량 떠넘기기 주의)
모두 키워드·대리 지표라 원문 확인이 필요하고, '곧 펌핑'은 셋업 레이더의 이후 20거래일 결과로 검증한다.
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, timedelta

import pandas as pd

import db
import sec

TIPS = {
    "스승님 꿀팁 — 극펌핑 종목의 공통점(세력 1집단)": """큰 폭등을 유발하는 종목들 공통점에 대해서
세력이 1집단 입니다. 2집단 이상 있으면 서로 이해관계가 섞여서 힘듭니다.
즉 1번세력이 남겨먹을려고 펌핑중에 2번 세력이 희석을 풀어버리는 경우를 말합니다.
그럼 죽쒀서 개준꼴이 되기 때문에 극펌핑은 1개세력만 들어가 있는 상황에서 거의 다 나옵니다.""",
    "스승님 꿀팁 — 작전주 셋업 찾기(수권 증액·케이맨/BVI·F-1 워런트)": """수권자본금 한도 증액을 주총에서 했는지 체크 해보세요(수빌 발행수, 자본금 증액 통을 키워둔것)
그러면 오퍼링 한가득 준비하고 큰 펌핑을 그리고 있다는 증거입니다.
그리고 케이맨제도. 버진아일랜드 이 두곳 설립지를 체크하세요
그리고 보통주+워런트 구조의 F-1 선반제출종목 찾아보시면 곧 펌핑 하는 종목입니다.
날짜까진 맞출순 없지만 이 공통점은 다 들어갑니다(절대적아니라 대부분)""",
    "스승님 꿀팁 — 흔적(대차 넉넉 + 다크풀 50~60%, 시체치우기)": """공매도 가용잔고 널널하고 남아있는데, 다크풀거래량이 계속 50~60%대 이상이면 매집.가격억누르기 입니다.
그 말인즉슨 쏠려고 준비한다는 힌트이기도 합니다.
다만 위 지표체크후 해당종목을 분석해 보세요. 8K로 샅샅이 보시고, 그 내용중 악재가 있는건 걸러내셔야합니다.
(호재는 캐치하기가 힘든경우가 많습니다만, 악재는 캐치가 됩니다) 그건 물량 떠넘기기 일수가 있거든요-대폭락전 움직임
지루한 횡보속에 개미들은 못견뎌 물량을 던지고 호가창이 가벼워지면 그때 쏩니다. 소위 시체치우기 작업입니다.
분석중에 그냥 출발하면 내꺼 아닌겁니다. 포모 못견디면 자산은 녹아내릴수 밖에 없습니다.
급등으로 수익보시는분들 찐들은 그냥 급등 올라타는게 아닙니다. 이미 급등하는 종목이 왜 급등하는지 사전에 공부하고 알고 계셨기 때문에 안심하고 중간탑승으로 수익을 보는겁니다.""",
    "스승님 꿀팁 — 주총 병합안건 + 수권주식수 증가": """주주총회 안건에 병합.수권주식수 증가 이 2개가 같이 보이면 자본 재구성 계획을 가지고 있는겁니다. 즉 대규모 희석 예고 입니다.
희석은 장기적인 주가하락의 이유입니다. 하지만 역설적으로 희석당시엔 물량을 떠넘기기위한 대규모매수세 유입이 필요하기 때문에 호재를 뿌려 주가상승을 유도 하기도 합니다.
우리는 이때 먹고 빠져야 하는것이지요. 그리고 주식수가 얼마 되지도 않는데 병합안건 나오는건 가장 확실한 증거가 됩니다.
초극펌핑이 있었던 이룽파워 EWPL: 병합 선안건.수권주식수증가가 선행됐고, 선반 F-1의 구성이 보통주+워런트 형태 였습니다.
(ATM.ELOC는 피하셔야합니다) 이런 구조에서 펌핑이 잘 나옵니다.""",
}
FOMO_CARD = ("분석 중에 그냥 출발하면 내 것 아닙니다. 포모를 못 견디면 자산은 녹아내립니다. "
             "급등으로 버는 사람은 그냥 올라타는 게 아니라, 왜 급등하는지 미리 공부해 두었기 때문에 중간 탑승을 합니다. — 스승님")
CAVEAT = ("세력·작전은 데이터로 직접 볼 수 없어 공시 키워드와 대리 지표로 추정합니다. 조달 상대방은 아래 이름 목록에 있는 곳만 셉니다. "
          "소형주는 개인 주문 내부 체결 때문에 평소에도 장외(다크풀) 비중이 높을 수 있어 평소 수준과 함께 보세요. 셋업 종목은 펌핑 뒤 급락도 빠릅니다.")
INC_CODES = {"E9": "케이맨 제도", "D8": "영국령 버진아일랜드"}
COUNTERPARTIES = [  # 소형주 자금조달에 자주 나오는 주관사·투자자(목록에 없는 곳은 세지 못함)
    "H.C. Wainwright", "Maxim Group", "ThinkEquity", "Aegis Capital", "Univest", "EF Hutton", "Spartan Capital", "D. Boral", "Craft Capital",
    "Kingswood", "Dawson James", "Alexander Capital", "WestPark", "Joseph Gunnar", "Boustead", "Benchmark", "Network 1", "Prime Number",
    "R.F. Lafferty", "Roth Capital", "A.G.P.", "Alliance Global", "Laidlaw", "Brookline", "Univest Securities", "Revere Securities", "Bancroft",
    "Yorkville", "Streeterville", "Lind Global", "Alpha Capital", "Hudson Bay", "Armistice", "Anson", "Iroquois", "Ionic Ventures", "3i, LP",
    "Sabby", "Ayrton", "Intracoastal", "L1 Capital", "Mast Hill", "1800 Diagonal", "Arena Investors", "Alumni Capital", "Helena Global",
    "White Lion", "Keystone Capital", "Tumim", "Lincoln Park", "GHS Investments", "Seastar", "Triton Funds", "Cavalry Fund", "ClearThink"]
NEG_ITEMS = {"1.03": "파산·회생", "2.04": "채무 조기상환 사유", "2.06": "자산 손상", "3.01": "상장유지 미달", "4.01": "감사인 교체", "4.02": "재무제표 신뢰 불가(정정)"}
PROXY_FORMS = {"DEF 14A", "PRE 14A", "DEFA14A", "DEF 14C", "PRE 14C", "8-K", "8-K/A", "6-K"}
REG_FORMS = {"F-1", "F-1/A", "S-1", "S-1/A"}
P_AUTH = re.compile(r"increas\w*\s+(?:in\s+)?(?:the\s+)?(?:number\s+of\s+)?(?:our\s+|the\s+company'?s\s+)?authori[sz]ed\s+(?:number\s+of\s+)?(?:shares|share\s+capital|ordinary\s+shares|common\s+stock|capital)"
                    r"|authori[sz]ed\s+share\s+capital\s+(?:of\s+the\s+company\s+)?(?:be|was|is|will\s+be)\s+increased", re.I)
P_RS = re.compile(r"reverse\s+(?:stock\s+|share\s+)?split|share\s+consolidation|consolidat\w+\s+of\s+(?:the\s+)?(?:company'?s\s+)?(?:issued\s+)?(?:ordinary\s+|common\s+)?shares", re.I)
P_WAR = re.compile(r"warrants?\s+to\s+purchase|pre-funded\s+warrants?|units?,?\s+each\s+consisting|common\s+warrants?", re.I)
P_INC = re.compile(r"(?:incorporated|organized|exempted\s+company|business\s+company)[^.]{0,80}?(cayman\s+islands|british\s+virgin\s+islands)", re.I)
DDL = ["CREATE TABLE IF NOT EXISTS setup_doc_cache (accession TEXT PRIMARY KEY, flags TEXT)",
       "CREATE TABLE IF NOT EXISTS setup_cache (ticker TEXT PRIMARY KEY, at TEXT, data TEXT)",
       "CREATE TABLE IF NOT EXISTS setup_first (ticker TEXT PRIMARY KEY, date TEXT, price REAL, score INTEGER)"]


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    conn.commit()


def doc_flags(text: str, form: str) -> dict:
    t = re.sub(r"\s+", " ", text)
    tags = set(sec.scan_text(text, form))
    cps = sorted({n for n in COUNTERPARTIES if re.search(re.escape(n), t, re.I)})
    inc = P_INC.search(t[:200_000])
    return {"auth_inc": bool(P_AUTH.search(t)), "reverse_split": bool(P_RS.search(t)), "warrants": bool(P_WAR.search(t)),
            "atm": "ATM" in tags, "eloc": "ELOC" in tags, "counterparties": cps, "inc_text": inc.group(1).title() if inc else None}


def dark_stats(conn, ticker: str, df: pd.DataFrame | None) -> dict | None:
    """FINRA 장외 거래량 ÷ 전체 거래량(Yahoo 일봉) — 최근 저장된 날짜들(최대 5일) 평균."""
    if df is None or df.empty:
        return None
    try:
        rows = conn.execute("SELECT date, total FROM finra_shvol WHERE symbol=? ORDER BY date DESC LIMIT 5", (ticker.upper(),)).fetchall()
    except Exception:  # noqa: BLE001
        return None
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    vals = []
    for r in rows:
        ts = pd.Timestamp(r["date"])
        if ts in d.index and d.loc[ts, "Volume"] > 0:
            vals.append(min(r["total"] / float(d.loc[ts, "Volume"]) * 100, 100.0))
    return {"dark_pct": sum(vals) / len(vals), "days": len(vals)} if vals else None


def analyze(client, conn, ticker: str, today: date | None = None, days: int = 365, max_docs: int = 15, shares_out: float | None = None,
            dark: dict | None = None, short: dict | None = None, dilution_status: str | None = None) -> dict:
    ensure_tables(conn)
    today = today or date.today()
    t = ticker.upper()
    cik = client.cik_for(t)
    if not cik:
        return {"error": "SEC CIK 없음(ETF/신규상장/티커 변경 가능성)"}
    sub = client.submissions(cik)
    filings = sec.recent_filings(sub, cik)
    cutoff = (today - timedelta(days=days)).isoformat()
    recent = [f for f in filings if f["filed"] >= cutoff]
    inc_code = (sub.get("stateOfIncorporation") or "").upper()
    inc = INC_CODES.get(inc_code) or ((sub.get("stateOfIncorporationDescription") or "") if re.search(r"cayman|virgin", sub.get("stateOfIncorporationDescription") or "", re.I) else None)
    neg = [{"date": f["filed"], "item": it.strip(), "name": NEG_ITEMS[it.strip()], "url": f["url"]}
           for f in filings if f["form"] in ("8-K", "8-K/A") and f["filed"] >= (today - timedelta(days=90)).isoformat()
           for it in f["items"].split(",") if it.strip() in NEG_ITEMS]
    docs = [f for f in recent if f["form"] in REG_FORMS or f["form"] in PROXY_FORMS or f["form"].startswith("424B")][:max_docs]
    found = {"auth": [], "rs": [], "reg_war": [], "atm": False, "eloc": False, "cps": set(), "inc_text": None}
    errors = 0
    for f in docs:
        row = conn.execute("SELECT flags FROM setup_doc_cache WHERE accession=?", (f["accession"],)).fetchone()
        if row:
            fl = json.loads(row["flags"])
        else:
            try:
                fl = doc_flags(client.fetch_text(f["url"]), f["form"])
            except Exception:  # noqa: BLE001
                errors += 1
                continue
            conn.execute("INSERT OR REPLACE INTO setup_doc_cache (accession, flags) VALUES (?,?)", (f["accession"], json.dumps(fl)))
            conn.commit()
        ev = {"date": f["filed"], "form": f["form"], "url": f["url"]}
        if fl["auth_inc"] and f["form"] in PROXY_FORMS:
            found["auth"].append(ev)
        if fl["reverse_split"] and f["form"] in PROXY_FORMS:
            found["rs"].append(ev)
        if f["form"] in REG_FORMS and fl["warrants"]:
            found["reg_war"].append(ev)
        found["atm"] |= fl["atm"]
        found["eloc"] |= fl["eloc"]
        found["cps"] |= set(fl["counterparties"])
        found["inc_text"] = found["inc_text"] or fl.get("inc_text")
    inc = inc or found["inc_text"]
    both = any(abs((date.fromisoformat(a["date"]) - date.fromisoformat(r["date"])).days) <= 120 for a in found["auth"] for r in found["rs"])
    atm_eloc = found["atm"] or found["eloc"] or dilution_status in ("ATM", "ELOC")
    cps = sorted(found["cps"])
    small = shares_out is not None and shares_out <= 10e6
    sh = short or {}
    roomy = (sh.get("borrow_avail_capped") or (sh.get("borrow_avail") or 0) >= 50_000) and (sh.get("borrow_fee") is None or sh["borrow_fee"] < 20) and not sh.get("borrow_stale")
    trace = dark is not None and dark.get("dark_pct", 0) >= 50 and bool(roomy)
    first = lambda xs: xs[0]["url"] if xs else None  # noqa: E731
    sig = [
        {"구분": "+", "신호": "병합 안건 + 수권주식 증액이 함께(자본 재구성 = 대규모 희석 예고)", "결과": both, "근거": first(found["rs"])},
        {"구분": "+", "신호": "수권주식(수권자본) 증액 안건·승인", "결과": bool(found["auth"]), "근거": first(found["auth"])},
        {"구분": "+", "신호": "병합(역분할) 안건·승인", "결과": bool(found["rs"]), "근거": first(found["rs"])},
        {"구분": "+", "신호": "주식 수가 적은데 병합 안건(가장 확실한 증거)", "결과": bool(found["rs"]) and small,
         "근거": None, "값": None if shares_out is None else f"발행주식 {shares_out / 1e6:.2f}M"},
        {"구분": "+", "신호": "설립지 케이맨 제도·영국령 버진아일랜드", "결과": bool(inc), "근거": None, "값": inc or (sub.get("stateOfIncorporationDescription") or inc_code or "-")},
        {"구분": "+", "신호": "F-1(S-1) 등록서류가 보통주+워런트 구조", "결과": bool(found["reg_war"]), "근거": first(found["reg_war"])},
        {"구분": "+", "신호": "조달 상대방 1곳(세력 1집단 추정)", "결과": len(cps) == 1, "근거": None, "값": ", ".join(cps) or "목록에서 못 찾음"},
        {"구분": "+", "신호": "흔적: 대차 넉넉 + 다크풀(장외) 비중 50% 이상", "결과": trace if dark is not None and short else None, "근거": None,
         "값": ("-" if dark is None else f"장외 {dark['dark_pct']:.0f}%({dark['days']}일)") + (" · 대차 넉넉" if roomy else (" · 대차 빠듯" if short else " · 대차 정보 없음"))},
        {"구분": "−", "신호": "ATM·ELOC(시장가 희석) — 피할 것", "결과": bool(atm_eloc), "근거": None},
        {"구분": "−", "신호": "조달 상대방 2곳 이상(이해관계 혼재)", "결과": len(cps) >= 2, "근거": None, "값": ", ".join(cps) or "-"},
        {"구분": "−", "신호": "최근 90일 8-K 악재(물량 떠넘기기 주의)", "결과": bool(neg), "근거": neg[0]["url"] if neg else None,
         "값": ", ".join(f"{n['date']} {n['item']} {n['name']}" for n in neg) or "없음(6-K 회사는 판정 어려움)"},
    ]
    plus = sum(1 for s in sig if s["구분"] == "+" and s["결과"])
    minus = sum(1 for s in sig if s["구분"] == "−" and s["결과"])
    verdict = ("피함 — 시장가 희석(ATM·ELOC)" if atm_eloc else "주의 — 악재·상대방 혼재" if minus else
               "강한 셋업" if plus >= 4 else "셋업 일부" if plus >= 2 else "셋업 약함")
    return {"ticker": t, "plus": plus, "minus": minus, "verdict": verdict, "signals": sig, "counterparties": cps, "incorporation": inc,
            "negatives": neg, "docs": len(docs), "errors": errors, "analyzed": today.isoformat()}


def save(conn, ticker: str, data: dict, price: float | None = None) -> None:
    ensure_tables(conn)
    conn.execute("INSERT OR REPLACE INTO setup_cache (ticker, at, data) VALUES (?,?,?)", (ticker.upper(), db.utcnow_iso(), json.dumps(data, ensure_ascii=False)))
    if "error" not in data:
        conn.execute("INSERT OR IGNORE INTO setup_first (ticker, date, price, score) VALUES (?,?,?,?)", (ticker.upper(), data["analyzed"], price, data["plus"]))
    conn.commit()


def cached(conn, ticker: str) -> tuple[str, dict] | None:
    ensure_tables(conn)
    r = conn.execute("SELECT at, data FROM setup_cache WHERE ticker=?", (ticker.upper(),)).fetchone()
    return (r["at"], json.loads(r["data"])) if r else None


def all_cached() -> pd.DataFrame:
    with closing(db.connect()) as c:
        ensure_tables(c)
    return db.read_df("SELECT c.ticker, c.at, c.data, f.date AS first_date, f.price AS first_price FROM setup_cache c LEFT JOIN setup_first f ON f.ticker=c.ticker")
