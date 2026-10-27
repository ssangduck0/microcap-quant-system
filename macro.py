"""🌎 시장 지표 — VIX · 공포·탐욕 지수(CNN) · 미국 수입물가지수(BLS). 스캐너가 주기적으로 받아 DB 에 저장하고 화면은 읽기만 한다.

VIX: 야후 '^VIX' 일봉(15분 주기) · 공포·탐욕: CNN 웹 데이터(공식 공개 API 아님 — 바뀌면 '확인 불가', 30분 주기)
수입물가지수: BLS 공개 API 시리즈 EIUIR(전체 수입품, 지수) → 전월비·전년비(하루 1회), 다음 발표일은 BLS 일정표에서(실패하면 관리 모드에서 직접 입력)
예상치(컨센서스)는 무료 공식 출처가 없어 관리 모드에서 직접 입력한다. 시장 분석은 원문으로 직접 확인할 것.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

import db

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/EIUIR"
BLS_SCHEDULE = "https://www.bls.gov/schedule/news_release/ximpim.htm"
TTL_MIN = {"vix": 15, "fng": 30, "imp": 720, "imp_next": 1440}
RATING_KO = {"extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립", "greed": "탐욕", "extreme greed": "극단적 탐욕"}
LINKS = [("CNN 공포·탐욕", "https://edition.cnn.com/markets/fear-and-greed"), ("VIX (Cboe)", "https://www.cboe.com/tradable_products/vix/"),
         ("수입물가지수 (BLS)", "https://www.bls.gov/mxp/"), ("BLS 발표 일정", BLS_SCHEDULE), ("경제 캘린더 (Investing)", "https://kr.investing.com/economic-calendar/"),
         ("SEC EDGAR", "https://www.sec.gov/edgar/search/"), ("FINRA 공매도 거래", "https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data"),
         ("나스닥 Reg SHO", "https://www.nasdaqtrader.com/trader.aspx?id=RegSHOThreshold"), ("토스증권", "https://tossinvest.com/")]
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get() -> dict:
    m = db.get_meta("macro")
    try:
        return json.loads(m["value"]) if m and m.get("value") else {}
    except (TypeError, ValueError):
        return {}


def _save(d: dict) -> None:
    db.set_meta("macro", json.dumps(d, ensure_ascii=False, default=str))


def fetch_vix(download=None) -> dict:
    import market
    dl = download or (lambda: market.download_daily(["^VIX"], period="6mo").get("^VIX"))
    df = dl()
    c = df["Close"].dropna()
    if len(c) < 2:
        raise RuntimeError("VIX 자료 없음")
    v, p = float(c.iloc[-1]), float(c.iloc[-2])
    return {"value": v, "prev": p, "chg": v - p, "date": c.index[-1].strftime("%Y-%m-%d"),
            "level": "안정" if v < 20 else ("경계" if v < 30 else "공포"), "hist": [[d.strftime("%Y-%m-%d"), round(float(x), 2)] for d, x in c.tail(130).items()]}


def fetch_fng(http_get=None) -> dict:
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"}, timeout=15))
    full = get(CNN_URL).json()
    j = full["fear_and_greed"]
    rating = str(j.get("rating", "")).lower()
    hist = []
    for p in ((full.get("fear_and_greed_historical") or {}).get("data") or [])[-260:]:
        try:
            hist.append([datetime.fromtimestamp(float(p["x"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d"), round(float(p["y"]), 1)])
        except (KeyError, TypeError, ValueError):
            continue
    return {"score": float(j["score"]), "prev": None if j.get("previous_close") is None else float(j["previous_close"]),
            "week": None if j.get("previous_1_week") is None else float(j["previous_1_week"]), "rating": RATING_KO.get(rating, rating), "at": str(j.get("timestamp", ""))[:16],
            "hist": hist}


FRED_IMP_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IR"  # 같은 지표(수입물가지수·전체 수입품, BLS EIUIR) — BLS 가 막힐 때 예비
DBN_IMP_URL = "https://api.db.nomics.world/v22/series/BLS/ei/EIUIR?observations=1"  # DBnomics(BLS 자료 복사본) — 한국에서 BLS·FRED 가 막힐 때


def fetch_imp(http_get=None) -> dict:
    """수입물가지수: BLS 먼저, 실패하면(503·차단 등) FRED 의 같은 시리즈(IR)."""
    try:
        return _fetch_imp_bls(http_get)
    except Exception as e1:  # noqa: BLE001
        errs = []
        for name, fn in (("DBnomics", _fetch_imp_dbn), ("FRED", _fetch_imp_fred)):
            try:
                out = fn(http_get)
                out["source"] = f"{name}(BLS 실패: {str(e1)[:30]})"
                return out
            except Exception as e2:  # noqa: BLE001
                errs.append(f"{name} {str(e2)[:50]}")
        raise RuntimeError(f"{e1} · 예비도 실패: " + " · ".join(errs)) from None


def _from_months(rows: list[tuple[str, float]]) -> dict:
    """[(YYYY-MM, 지수)] → 전월비·전년비·최근 24개월 전월비."""
    rows = sorted(rows, reverse=True)
    if len(rows) < 13:
        raise RuntimeError("수입물가지수 자료 부족")
    from datetime import date as _d
    _y, _m = int(rows[0][0][:4]), int(rows[0][0][5:7])
    if (_d.today().year - _y) * 12 + (_d.today().month - _m) > 4:  # 갱신이 멈춘 복사본(예: DBnomics 2025-01)을 최신처럼 보여주지 않게
        raise RuntimeError(f"자료가 오래됨(최근 {rows[0][0]})")
    cur, prev = rows[0][1], rows[1][1]
    yago = next((v for m, v in rows if m == f"{int(rows[0][0][:4]) - 1}{rows[0][0][4:]}"), None)
    hist = [[a[0], round((a[1] / b[1] - 1) * 100, 2)] for a, b in zip(rows[:24], rows[1:25])]
    return {"month": rows[0][0], "index": cur, "mom": (cur / prev - 1) * 100, "yoy": None if not yago else (cur / yago - 1) * 100,
            "prelim": False, "hist": list(reversed(hist))}


def _fetch_imp_dbn(http_get=None) -> dict:
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"}, timeout=10))
    r = get(DBN_IMP_URL)
    if getattr(r, "status_code", 200) >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    doc = r.json()["series"]["docs"][0]
    rows = []
    for m, v in zip(doc["period"], doc["value"]):
        try:
            rows.append((str(m)[:7], float(v)))
        except (TypeError, ValueError):
            continue  # 'NA'
    return _from_months(rows)


def _fetch_imp_fred(http_get=None) -> dict:
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": BROWSER_UA}, timeout=10))
    r = get(FRED_IMP_URL)
    if getattr(r, "status_code", 200) >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    lines = [ln.strip() for ln in str(getattr(r, "text", "")).splitlines() if ln.strip()]
    if not lines or "," not in lines[0]:
        raise RuntimeError("CSV 가 아님")
    rows = []
    for ln in lines[1:]:
        d, v = ln.split(",")[:2]
        try:
            rows.append((d[:7], float(v)))
        except ValueError:
            continue  # '.' = 값 없음
    return _from_months(rows)


def _fetch_imp_bls(http_get=None) -> dict:
    import requests
    import config
    # BLS 는 기본 이름표(python-requests)면 차단 페이지(HTML)를 줘서 JSONDecodeError 가 났음 → 연락처 이름표를 붙임
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": config.SEC_USER_AGENT or BROWSER_UA, "Accept": "application/json"}, timeout=10))
    r = get(BLS_URL)
    if getattr(r, "status_code", 200) >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"JSON 이 아닌 응답(차단 페이지일 수 있음): {str(getattr(r, 'text', ''))[:60]!r}") from None
    if str(j.get("status", "")).upper() not in ("", "REQUEST_SUCCEEDED"):
        raise RuntimeError(f"BLS: {j.get('status')} {' '.join(j.get('message') or [])[:80]}")
    rows = [r for r in j["Results"]["series"][0]["data"] if str(r.get("period", "")).startswith("M") and r.get("period") != "M13"]
    rows.sort(key=lambda r: (int(r["year"]), int(r["period"][1:])), reverse=True)
    if len(rows) < 13:
        raise RuntimeError("수입물가지수 자료 부족")
    cur, prev = float(rows[0]["value"]), float(rows[1]["value"])
    yago = next((float(r["value"]) for r in rows if int(r["year"]) == int(rows[0]["year"]) - 1 and r["period"] == rows[0]["period"]), None)
    prelim = any(str(f.get("code", "")).upper() == "P" for f in rows[0].get("footnotes") or [] if isinstance(f, dict))
    hist = []
    for a, b in zip(rows[:24], rows[1:25]):
        hist.append([f"{a['year']}-{a['period'][1:]}", round((float(a["value"]) / float(b["value"]) - 1) * 100, 2)])
    return {"month": f"{rows[0]['year']}-{rows[0]['period'][1:]}", "index": cur, "mom": (cur / prev - 1) * 100, "yoy": None if not yago else (cur / yago - 1) * 100,
            "prelim": prelim, "hist": list(reversed(hist))}


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_schedule(html: str, today: date | None = None) -> str | None:
    """BLS 일정표에서 오늘 이후 가장 가까운 발표일(YYYY-MM-DD)."""
    today = today or date.today()
    out = []
    for mon, d, y in re.findall(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})", html):
        try:
            dt = date(int(y), MONTHS[mon[:3].lower()], int(d))
        except ValueError:
            continue
        if dt >= today:
            out.append(dt)
    return min(out).isoformat() if out else None


def fetch_imp_next(http_get=None) -> dict:
    import config
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": config.SEC_USER_AGENT or BROWSER_UA}, timeout=20))
    d = parse_schedule(get(BLS_SCHEDULE).text)
    if not d:
        raise RuntimeError("다음 발표일을 찾지 못함")
    return {"date": d, "source": "BLS 일정표"}


def refresh(force: bool = False, fetchers: dict | None = None) -> dict:
    """주기(TTL)가 지난 항목만 다시 받는다. 실패한 항목은 오류만 기록하고 예전 값은 남긴다."""
    f = {"vix": fetch_vix, "fng": fetch_fng, "imp": fetch_imp, "imp_next": fetch_imp_next, **(fetchers or {})}
    d = get()
    now = _now()
    for k, fn in f.items():
        cur = d.get(k) or {}
        at = cur.get("_at")
        if not force and at and now - datetime.fromisoformat(at) < timedelta(minutes=TTL_MIN.get(k, 60)):
            continue
        try:
            d[k] = {**fn(), "_at": now.isoformat(), "_err": None}
        except Exception as e:  # noqa: BLE001
            d[k] = {**{kk: vv for kk, vv in cur.items() if not kk.startswith("_")}, "_at": now.isoformat(), "_err": f"{type(e).__name__}: {str(e)[:120]}"}
    _save(d)
    return d


def set_manual(next_date: str | None, forecast: float | None) -> None:
    """관리 모드: 수입물가지수 다음 발표일·예상치(전월비 %) 직접 입력."""
    db.set_meta("macro_manual", json.dumps({"next_date": next_date or None, "forecast": forecast}, ensure_ascii=False))


def manual() -> dict:
    m = db.get_meta("macro_manual")
    try:
        return json.loads(m["value"]) if m and m.get("value") else {}
    except (TypeError, ValueError):
        return {}
