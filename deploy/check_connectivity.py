"""🌐 접속 시험 — 서버(또는 PC)에서 대시보드가 쓰는 외부 자료를 실제로 받을 수 있는지 한 번에 확인한다.

    python deploy/check_connectivity.py

데이터센터(클라우드) IP 는 야후 파이낸스가 막는 경우가 있어 서버를 만들고 '가장 먼저' 돌려 본다.
같은 명령을 집 PC 에서도 돌려 두 결과를 비교하면 서버에서만 막히는 곳을 바로 알 수 있다.
토스 Open API 는 '허용 IP' 에 서버 공인 IP 를 등록해야 한다(미등록이면 403).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import requests  # noqa: E402

try:
    import config  # .env 를 읽음(SEC_USER_AGENT · 텔레그램 · Anthropic · 토스 키)
    config.apply_overrides()
except Exception as e:  # noqa: BLE001
    print("config 를 읽지 못했어요:", e)
    config = None

UA = getattr(config, "SEC_USER_AGENT", "") or "Quant Dashboard contact@example.com"
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    t0 = time.time()
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {str(e)[:120]}"
    results.append((name, ok, msg))
    print(f"{'✅' if ok else '❌'} {name:<28} {time.time() - t0:5.1f}초  {msg}")


def _bday(n_back: int) -> date:
    d = date.today()
    k = 0
    while True:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            k += 1
            if k >= n_back:
                return d


def yf_daily():
    import yfinance as yf
    tk = ["AAPL", "MSFT", "SOUN", "MULN", "SNDL", "OCGN", "NKLA", "IDEX", "GNS", "BNAI"]
    oks = []
    for rnd in range(3):  # 연속 요청에서 막히는지(레이트리밋)
        df = yf.download(tk, period="3mo", interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=False)
        got = sum(1 for t in tk if t in df.columns.get_level_values(0) and df[t]["Close"].notna().sum() > 10)
        oks.append(got)
        time.sleep(1)
    return min(oks) >= 7, f"일봉 10종목 × 3번 → 받은 종목 {oks}"


def yf_intraday():
    import yfinance as yf
    df = yf.download(["AAPL", "SOUN", "SNDL"], period="5d", interval="5m", prepost=True, group_by="ticker", progress=False, threads=True)
    n = int(df.notna().any(axis=1).sum()) if df is not None else 0
    return n > 100, f"5분봉(프리·애프터 포함) {n}줄"


def sec():
    h = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
    r = requests.get("https://data.sec.gov/submissions/CIK0000320193.json", headers=h, timeout=20)
    r2 = requests.get("https://www.sec.gov/files/company_tickers.json", headers=h, timeout=20)
    ok = r.status_code == 200 and r2.status_code == 200
    return ok, f"HTTP {r.status_code}/{r2.status_code} · User-Agent '{UA[:40]}'" + ("" if "@" in UA else " ⚠️ 이메일이 없어요(.env SEC_USER_AGENT)")


def nasdaq_regsho():
    import regsho
    last = ""
    for k in range(1, 5):
        d = _bday(k).strftime("%Y%m%d")
        code, text = regsho.fetch(regsho.URL.format(d=d))  # 대시보드와 같은 요청 방식
        last = f"HTTP {code}"
        n = len(regsho.parse(text)) if code == 200 else 0
        if n:
            return True, f"{d} 명단 {n}종목"
    return False, last + " · 명단을 읽지 못함"


def nasdaq_listed():
    import universe
    r = requests.get(universe.LISTED_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    n = r.text.count("\n") if r.status_code == 200 and "Symbol|" in r.text[:300] else 0
    return n > 1000, f"HTTP {r.status_code} · 나스닥 상장 종목 {n}줄(스캐너 종목 목록)"


def nasdaq_halts():
    import halts
    rows = halts._fetch_nasdaq(requests.Session(), 20)
    return True, f"거래정지 RSS {len(rows)}건(장 마감·주말엔 0건일 수 있음)"


def finra():
    for k in range(1, 5):
        d = _bday(k).strftime("%Y%m%d")
        r = requests.get(f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d}.txt", headers=BROWSER, timeout=20)
        if r.status_code == 200 and "|" in r.text[:200]:
            return True, f"{d} 공매도 거래량 {r.text.count(chr(10))}줄"
    return False, f"HTTP {r.status_code}"


def prn():
    r = requests.get("https://www.prnewswire.com/rss/news-releases-list.rss", headers=BROWSER, timeout=20)
    return r.status_code == 200 and "<item>" in r.text, f"HTTP {r.status_code} · 기사 {r.text.count('<item>')}개"


def cnn():
    r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", headers=BROWSER, timeout=20)
    ok = r.status_code == 200 and "fear_and_greed" in r.text
    return ok, f"HTTP {r.status_code}"


def bls():
    import macro
    d = macro.fetch_imp()  # BLS 먼저, 막히면 FRED 예비(대시보드와 같은 경로)
    return True, f"{d['month']} 전월비 {d['mom']:+.1f}% · 출처 {d.get('source', 'BLS')}"


def telegram():
    tok = getattr(config, "TELEGRAM_TOKEN", "") if config else ""
    if not tok:
        return False, "텔레그램 토큰이 .env 에 없어요(건너뜀)"
    r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=20)
    return r.status_code == 200 and r.json().get("ok"), f"HTTP {r.status_code}"


def anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return False, "ANTHROPIC_API_KEY 가 없어요(건너뜀)"
    r = requests.get("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=20)
    return r.status_code == 200, f"HTTP {r.status_code}"


def toss():
    cid = getattr(config, "TOSS_CLIENT_ID", "") if config else ""
    sec_ = getattr(config, "TOSS_CLIENT_SECRET", "") if config else ""
    if not (cid and sec_):
        return False, "토스 키가 .env 에 없어요(건너뜀)"
    import toss as tc
    c = tc.TossClient(cid, sec_, getattr(config, "TOSS_BASE_URL", "https://openapi.tossinvest.com"))
    try:
        q = c.daily_candles("AAPL", 5)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        hint = " → 토스 WTS 설정 > Open API > 허용 IP 에 이 서버의 공인 IP 를 등록하세요" if "403" in msg else ""
        return False, msg[:100] + hint
    return bool(q), f"AAPL 일봉 {len(q) if q else 0}개 · ⚠️ 토스는 한 곳에서만 쓰세요(PC·서버 동시 사용 시 토큰 충돌)"


def public_ip():
    r = requests.get("https://api.ipify.org", timeout=10)
    return True, r.text.strip()


if __name__ == "__main__":
    print("🌐 접속 시험 — 대시보드가 쓰는 외부 자료\n")
    check("이 컴퓨터의 공인 IP", public_ip)
    check("야후 일봉(차단 여부)", yf_daily)
    check("야후 5분봉(시간외)", yf_intraday)
    check("SEC EDGAR", sec)
    check("나스닥 상장 종목 목록", nasdaq_listed)
    check("나스닥 Reg SHO 명단", nasdaq_regsho)
    check("나스닥 거래정지 RSS", nasdaq_halts)
    check("FINRA 공매도 거래량", finra)
    check("PR Newswire 뉴스", prn)
    check("CNN 공포·탐욕", cnn)
    check("수입물가(BLS·FRED)", bls)
    check("텔레그램", telegram)
    check("Anthropic(Claude) API", anthropic)
    check("토스 Open API", toss)
    bad = [n for n, ok, m in results if not ok and "건너뜀" not in m]
    print("\n" + ("🎉 모두 정상이에요." if not bad else "⚠️ 확인이 필요한 곳: " + ", ".join(bad)))
    print("야후가 막히면 서버 업체·지역을 바꾸거나(시간제 서버는 지우고 다시 만들면 IP 가 바뀜), 다른 시세 출처를 붙여야 해요.")
