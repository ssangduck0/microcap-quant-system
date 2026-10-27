"""감시 종목 수집. 토스 랭킹(비공식 API) + yfinance 하락률 스크리너 + 수동 목록(manual_tickers.txt)을 합칩니다."""
from __future__ import annotations

import json
import logging
import re
import time

import requests
import yfinance as yf

import config

log = logging.getLogger("universe")
VALID = re.compile(r"^[A-Z]{1,5}$")
FALLBACK = ["WHLR", "CLDI", "BNAI", "WCT", "EDSA", "NIVF", "JLHL", "DKI", "GCDT", "NIKI", "RMSG", "SPHL", "HCAI", "GSUN", "MI"]


def from_toss() -> list[str]:
    try:
        url = "https://wts-view.tossinvest.com/api/v1/ranking/stock/fluctuation?type=DECREASE&displayCount=40"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://tossinvest.com/"}
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()
        items = res.json().get("result", {}).get("stocks", [])
        return [s for s in (i.get("symbol") or i.get("ticker") for i in items) if s and VALID.match(s)]
    except Exception as e:  # noqa: BLE001
        log.info("토스 랭킹 사용 불가: %s", e)
        return []


def from_screener() -> list[str]:
    try:
        quotes = yf.screen("day_losers", count=50).get("quotes", [])
        return [q["symbol"] for q in quotes
                if VALID.match(q.get("symbol", "")) and (q.get("marketCap") or 0) < 500e6]
    except Exception as e:  # noqa: BLE001
        log.info("yfinance 스크리너 사용 불가: %s", e)
        return []


def from_manual() -> list[str]:
    if not config.MANUAL_TICKERS_FILE.exists():
        return []
    lines = config.MANUAL_TICKERS_FILE.read_text(encoding="utf-8").splitlines()
    return [x.strip().upper() for x in lines if x.strip() and not x.startswith("#")]


LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
EXCLUDED_TYPES = {"ETF", "FOREIGN_ETF", "ETN", "STOCK_WARRANTS", "INFRASTRUCTURE_FUND"}


def _cache_path(key: str):
    return config.BASE_DIR / ("universe_cache_" + re.sub(r"[^a-z0-9]+", "_", key.lower()) + ".json")
# 워런트/권리/유닛/채권/우선주 등은 주식이 아니므로 제외
EXCLUDE_NAME = re.compile(r"\b(warrants?|rights?|units?|notes?|preferred|subordinated|debentures?)\b", re.I)


def _parse_pipe(text: str) -> list[dict]:
    lines = [l for l in text.strip().splitlines() if l and not l.startswith("File Creation Time")]
    header = lines[0].split("|")
    return [dict(zip(header, l.split("|"))) for l in lines[1:]]


def _fetch_listed(include_amex: bool) -> list[str]:
    headers = {"User-Agent": "Mozilla/5.0"}
    tickers: list[str] = []
    r = requests.get(LISTED_URL, headers=headers, timeout=20)
    r.raise_for_status()
    for row in _parse_pipe(r.text):
        sym, name = row.get("Symbol", ""), row.get("Security Name", "")
        if row.get("Test Issue") != "N" or row.get("ETF") != "N":
            continue
        if VALID.match(sym) and not EXCLUDE_NAME.search(name):
            tickers.append(sym)
    if include_amex:
        r = requests.get(OTHER_URL, headers=headers, timeout=20)
        r.raise_for_status()
        for row in _parse_pipe(r.text):
            sym, name = row.get("ACT Symbol", ""), row.get("Security Name", "")
            if row.get("Exchange") != "A" or row.get("ETF") != "N" or row.get("Test Issue") != "N":
                continue
            if VALID.match(sym) and not EXCLUDE_NAME.search(name):
                tickers.append(sym)
    return sorted(set(tickers))


def load_listed(include_amex: bool) -> list[str]:
    """상장 종목 목록. 하루에 한 번만 받아서 캐시하고, 실패하면 오래된 캐시라도 사용합니다."""
    key = "nasdaq+amex" if include_amex else "nasdaq"
    return _cached_listing(key, lambda: _fetch_listed(include_amex))


def _cached_listing(key: str, fetch, min_count: int = 500) -> list[str]:
    path, cache = _cache_path(key), None
    if path.exists():
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = None
    if cache and time.time() - cache.get("ts", 0) < config.UNIVERSE_CACHE_HOURS * 3600:
        return cache["tickers"]
    try:
        tickers = fetch()
        if len(tickers) < min_count:
            raise ValueError(f"종목 수가 비정상적으로 적음({len(tickers)})")
        path.write_text(json.dumps({"ts": time.time(), "tickers": tickers}), encoding="utf-8")
        log.info("상장 종목 목록 갱신: %d개 (%s)", len(tickers), key)
        return tickers
    except Exception as e:  # noqa: BLE001
        log.warning("상장 종목 목록 조회 실패(%s): %s", key, e)
        if cache:
            log.warning("이전 캐시(%d개)를 사용합니다.", len(cache["tickers"]))
            return cache["tickers"]
        return []


def load_listed_toss(tc, include_amex: bool) -> list[str]:
    """토스증권에서 실제 거래 가능한 종목만. ETF·워런트·우선주 제외."""
    key = "toss:nasdaq+amex" if include_amex else "toss:nasdaq"

    def fetch() -> list[str]:
        out: list[str] = []
        for market in (["NASDAQ", "AMEX"] if include_amex else ["NASDAQ"]):
            for it in tc.stocks_all(market):
                sym = it.get("symbol", "")
                if (VALID.match(sym) and it.get("securityType") not in EXCLUDED_TYPES
                        and it.get("isCommonShare") is not False):
                    out.append(sym)
        return sorted(set(out))
    return _cached_listing(key, fetch)


def load_delisted_toss(tc) -> list[str]:
    """토스에 등록된 나스닥 상장폐지 종목 목록(생존편향 완화용). 가격 데이터가 남아 있는 종목만 실제로 쓰인다."""
    def fetch() -> list[str]:
        out = [it.get("symbol", "") for it in tc.stocks_all("NASDAQ", status="DELISTED")
               if it.get("securityType") not in EXCLUDED_TYPES and it.get("isCommonShare") is not False]
        return sorted({s for s in out if VALID.match(s)})
    return _cached_listing("toss:nasdaq:delisted", fetch, min_count=1)


def from_toss_rankings(tc) -> set[str]:
    """토스 공식 랭킹: 미국 급하락(1일) + 실시간 거래량 상위. 가격대 필터만 적용해서 우선 분석 대상으로 올린다."""
    out: set[str] = set()
    for rank_type, duration in (("TOP_LOSERS", "1d"), ("MARKET_TRADING_VOLUME", "realtime")):
        try:
            items = tc.rankings(rank_type, "US", duration, 100)
        except Exception as e:  # noqa: BLE001
            log.warning("토스 랭킹(%s) 조회 실패: %s", rank_type, e)
            continue
        for it in items:
            try:
                sym, price = it["symbol"], float(it["price"]["lastPrice"])
            except (KeyError, TypeError, ValueError):
                continue
            if VALID.match(sym) and config.MIN_PRICE_USD <= price <= config.MAX_PRICE_USD:
                out.add(sym)
        log.info("토스 랭킹 %s/%s: 누적 후보 %d개", rank_type, duration, len(out))
    if out:  # 랭킹에는 ETF·ETN 등이 섞여 있으므로 종목 정보로 한 번 더 거른다
        try:
            info = {x["symbol"]: x for x in tc.stocks(sorted(out))}
            bad = {s for s, x in info.items() if x.get("securityType") in EXCLUDED_TYPES or x.get("isCommonShare") is False
                   or x.get("status", "ACTIVE") != "ACTIVE"}
            if bad:
                log.info("랭킹 종목 중 ETF/ETN/워런트/우선주 등 %d개 제외", len(bad))
            out -= bad
        except Exception as e:  # noqa: BLE001
            log.warning("랭킹 종목 유형 확인 실패(필터 없이 사용): %s", e)
    return out


def from_watchlist() -> list[str]:
    """대시보드 ⭐ 워치리스트(블랙 제외)와 🐷 저금통. DB 를 못 읽으면 빈 목록."""
    try:
        import piggy
        import watch
        return list(dict.fromkeys(watch.scanner_priority() + piggy.tickers()))  # 워치리스트(블랙 제외) + 저금통
    except Exception:  # noqa: BLE001
        return []


def _paper_open() -> list[str]:
    """🧪 가상매매 열린 포지션 — 1분봉을 꼭 받아 와야 실시간 익절·손절 판정이 된다."""
    try:
        import papertrade
        return papertrade.open_tickers()
    except Exception:  # noqa: BLE001
        return []


def get_universe(toss_client=None) -> tuple[list[str], set[str]]:
    """(전체 감시 대상, 우선 종목). 우선 종목(manual_tickers.txt + 워치리스트 + 토스 랭킹)은 1단계 필터를 건너뛰고 항상 정밀 분석합니다."""
    manual = list(dict.fromkeys(from_manual() + from_watchlist() + _paper_open()))
    extra = from_toss_rankings(toss_client) if toss_client is not None else set()
    mode = config.SCAN_UNIVERSE
    if mode in ("nasdaq", "nasdaq+amex"):
        include_amex = mode == "nasdaq+amex"
        listed = load_listed_toss(toss_client, include_amex) if toss_client is not None else []
        if not listed:
            listed = load_listed(include_amex=include_amex)
        if listed:
            prio = set(manual) | extra
            return sorted(set(listed) | prio), prio
        log.warning("전체 목록을 못 구해 manual 모드로 대체합니다.")
    tickers = get_tickers(use_legacy_toss=toss_client is None)
    prio = set(tickers) | extra
    return sorted(prio), prio


def get_tickers(use_legacy_toss: bool = True) -> list[str]:
    tickers = list(dict.fromkeys(from_manual() + (from_toss() if use_legacy_toss else []) + from_screener()))
    if not tickers:
        log.warning("종목 소스가 모두 실패해 기본 목록을 사용합니다. manual_tickers.txt 를 만들어 두세요.")
        tickers = FALLBACK
    return tickers[:config.MAX_TICKERS]
