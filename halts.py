"""미국 거래정지(상킷·하킷 등).

기본 출처: 업킷 UpCuit OpenAPI (https://upcuit.com/api/v1/halts — 무료·무인증, IP당 분당 약 60회, SLA 없음, 나스닥 공개 피드 기반)
  필드: symbol, name, market, status(halted/quote_resumed/resumed), reasons[{code,title}], pause_threshold_price,
        halted_at / resumed_at / quote_resumed_at (ISO+오프셋, 없으면 *_local 의 동부시간)
백업 출처: Nasdaq Trader 공식 RSS — 업킷이 응답하지 않거나(503 준비 중 등) 형식이 어긋나면 자동으로 사용.
환경 변수 HALTS_SOURCE=upcuit(기본) | nasdaq(RSS 만 사용).

피드: https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts  (나스닥 상장 + 다른 거래소 종목의 정지·일시정지)
항목(ndaq: 네임스페이스): HaltDate, HaltTime(동부시간), IssueSymbol, IssueName, Market, ReasonCode, PauseThresholdPrice,
                        ResumptionDate, ResumptionQuoteTime, ResumptionTradeTime
LULD 변동성 정지 사유 코드: LUDP(정지), LUDS(밴드 걸침), M(변동성). T1(뉴스 대기)·T12(정보 요청)·H10(SEC 정지) 등은 사유만 표시.
피드에는 '상한/하한' 구분이 없어서, 정지 기준가(PauseThresholdPrice)를 정지 직전 1분봉 종가(토스)와 비교해 추정한다
(기준가 > 직전 가격 → 상한(상킷), < → 하한(하킷)). 기준가나 직전 가격이 없으면 '미상'.
"""
from __future__ import annotations

import logging
import os
import time as _time
import xml.etree.ElementTree as ET_XML
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

log = logging.getLogger("halts")
URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
UPCUIT_URL = "https://upcuit.com/api/v1/halts"
SOURCE = (os.environ.get("HALTS_SOURCE") or "upcuit").strip().lower()
last_source: str | None = None  # 마지막으로 성공한 출처 ("upcuit" / "nasdaq")
NS = {"ndaq": "http://www.nasdaqtrader.com/"}
ET = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (quant-system halt monitor)"
LULD_CODES = {"LUDP", "LUDS", "M"}
CODE_KO = {"LUDP": "변동성 정지(LULD)", "LUDS": "변동성 정지(LULD)", "M": "변동성 정지(LULD)", "T1": "뉴스 대기", "T2": "뉴스 공개",
           "T3": "뉴스 공개·재개 대기", "T5": "단일 종목 정지", "T6": "비정상 시장 활동", "T7": "호가만 재개", "T8": "ETF 정지",
           "T12": "추가 정보 요청", "H4": "상장 요건 미충족", "H9": "공시 지연", "H10": "SEC 거래 정지", "H11": "규제 우려",
           "O1": "운영 정지", "IPO1": "IPO 거래 전", "M1": "기업 조치", "M2": "호가 불가", "D": "상장폐지"}
_cache: dict = {"t": 0.0, "data": None}
_etag: dict = {"etag": None, "data": None}


def _txt(item, tag: str) -> str | None:
    el = item.find(tag, NS)
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _dt(d: str | None, t: str | None) -> datetime | None:
    if not d or not t:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(f"{d} {t}", fmt).replace(tzinfo=ET)
        except ValueError:
            continue
    return None


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 원문 → 정지 목록. 깨진 XML 은 ParseError 를 그대로 올린다(호출하는 쪽에서 '확인 불가' 처리)."""
    root = ET_XML.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        sym = _txt(item, "ndaq:IssueSymbol") or (item.findtext("title") or "").strip()
        if not sym:
            continue
        thr = _txt(item, "ndaq:PauseThresholdPrice")
        try:
            threshold = float(thr) if thr else None
        except ValueError:
            threshold = None
        rd = _txt(item, "ndaq:ResumptionDate")
        out.append({"symbol": sym.upper(), "name": _txt(item, "ndaq:IssueName"), "market": _txt(item, "ndaq:Market"),
                    "code": (_txt(item, "ndaq:ReasonCode") or "").upper(), "threshold": threshold,
                    "halt": _dt(_txt(item, "ndaq:HaltDate"), _txt(item, "ndaq:HaltTime")),
                    "resume": _dt(rd, _txt(item, "ndaq:ResumptionTradeTime")) or _dt(rd, _txt(item, "ndaq:ResumptionQuoteTime"))})
    return out


def _iso(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(ET)
    except ValueError:
        return None


def _local(v) -> datetime | None:
    return _dt(v.get("date"), v.get("time")) if isinstance(v, dict) else None


def parse_upcuit(j) -> list[dict]:
    """업킷 응답({api_version, data, meta}) → parse_feed 와 같은 모양의 목록. 형식이 어긋나면 ValueError."""
    if not isinstance(j, dict) or not isinstance(j.get("data"), list):
        raise ValueError("업킷 응답 형식이 예상과 다릅니다(data 목록 없음)")
    out = []
    for x in j["data"]:
        if not isinstance(x, dict) or not x.get("symbol"):
            continue
        codes = [str(r.get("code") or "").upper() for r in (x.get("reasons") or []) if isinstance(r, dict)]
        code = next((c for c in codes if c in LULD_CODES), codes[0] if codes else "")  # 사유가 여러 개면 LULD 코드를 우선
        title = next((r.get("title") for r in (x.get("reasons") or []) if isinstance(r, dict) and str(r.get("code") or "").upper() == code), None)
        thr = x.get("pause_threshold_price")
        try:
            thr = float(thr) if thr is not None else None
        except (TypeError, ValueError):
            thr = None
        out.append({"symbol": str(x["symbol"]).upper(), "name": x.get("name"), "market": x.get("market"), "code": code, "title": title,
                    "threshold": thr, "status": x.get("status"),
                    "halt": _iso(x.get("halted_at")) or _local(x.get("halted_at_local")),
                    "resume": _iso(x.get("resumed_at")) or _local(x.get("resumed_at_local")),
                    "quote_resume": _iso(x.get("quote_resumed_at"))})
    return out


def _fetch_upcuit(s, timeout: float) -> list[dict]:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if _etag["etag"]:
        headers["If-None-Match"] = _etag["etag"]
    r = s.get(UPCUIT_URL, headers=headers, timeout=timeout)
    if r.status_code == 304 and _etag["data"] is not None:  # 바뀐 게 없으면 이전 응답 재사용
        return _etag["data"]
    r.raise_for_status()
    data = parse_upcuit(r.json())
    _etag.update(etag=(getattr(r, "headers", None) or {}).get("ETag"), data=data)
    return data


def _fetch_nasdaq(s, timeout: float) -> list[dict]:
    r = s.get(URL, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return parse_feed(r.text)


def fetch(session=None, ttl: float = 30.0, timeout: float = 15.0, source: str | None = None) -> list[dict]:
    """오늘 거래정지 목록. 기본은 업킷, 실패하면 나스닥 RSS 로 자동 전환. ttl 초 동안은 캐시 재사용. 둘 다 실패하면 예외."""
    global last_source
    now = _time.time()
    if _cache["data"] is not None and now - _cache["t"] < ttl:
        return _cache["data"]
    s = session or requests
    src = (source or SOURCE).lower()
    data = None
    if src == "upcuit":
        try:
            data, last_source = _fetch_upcuit(s, timeout), "upcuit"
        except Exception as e:  # noqa: BLE001 (503 준비 중·형식 변경·네트워크)
            log.warning("업킷 거래정지 API 실패, 나스닥 RSS 로 전환: %s", e)
    if data is None:
        data, last_source = _fetch_nasdaq(s, timeout), "nasdaq"
    _cache.update(t=now, data=data)
    return data


def direction(h: dict, price_before: float | None) -> str | None:
    """LULD 정지의 방향. LULD 가 아니면 None, 판단 불가면 '미상'."""
    if h.get("code") not in LULD_CODES:
        return None
    thr = h.get("threshold")
    if thr is None or price_before is None or thr == price_before:
        return "미상"
    return "상한" if thr > price_before else "하한"


def summarize(hs: list[dict] | None, symbol: str, day: date, reg: pd.DataFrame | None) -> dict:
    """한 종목의 오늘 정지(+ 전날 걸려 아직 재개되지 않은 이월 정지) 요약. reg = 오늘 정규장 1분봉(토스)."""
    symbol = symbol.upper()
    rows = []
    for h in sorted((x for x in hs or [] if x["symbol"] == symbol and x["halt"] is not None), key=lambda x: x["halt"]):  # 시간순
        hd = h["halt"].date()
        if hd == day:
            carry = False
        elif hd < day and (h["resume"] is None or h["resume"].date() >= day):
            carry = True
        else:
            continue
        price_before = None
        if reg is not None and len(reg):
            before = reg[reg.index < h["halt"].replace(second=0, microsecond=0)]  # 정지가 걸린 분 이전의 마지막 1분봉
            if len(before):
                price_before = float(before["Close"].iloc[-1])
        rows.append({"time": h["halt"].strftime("%m-%d %H:%M:%S"), "code": h["code"], "reason": CODE_KO.get(h["code"]) or h.get("title") or h["code"] or "기타",
                     "threshold": h["threshold"], "price_before": price_before, "dir": direction(h, price_before),
                     "resume": h["resume"].strftime("%H:%M:%S") if h["resume"] else None, "carry": carry,
                     "quote_resumed": h.get("status") == "quote_resumed"})
    up = sum(1 for r in rows if r["dir"] == "상한")
    down = sum(1 for r in rows if r["dir"] == "하한")
    return {"halts": rows, "halt_up": up, "halt_down": down, "halt_other": len(rows) - up - down,
            "halt_active": any(r["resume"] is None for r in rows)}
