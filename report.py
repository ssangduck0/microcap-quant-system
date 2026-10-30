"""종목별 상세 리포트: SEC EDGAR + yfinance 에서 '자동으로 정확히 뽑을 수 있는 항목'만 모읍니다.

자동화되는 것 : 회사 개요/역분할/상장유지 경고, 조달 이력과 주가 반응, 런웨이(XBRL), 내부자 거래(Form 4), 타임라인
자동화 안 되는 것: 워런트·락업 상세 수량, 진입가 사다리, 상단 돌파 가능성, 예정 이벤트 해석 같은 '원문을 읽고 판단하는' 항목
                  -> 이런 건 챗봇에서 티커별 SEC 포렌식 스캔으로 만들고 대시보드 '내 메모'에 붙여 넣으세요.

섹션별로 실패를 격리합니다: 한 섹션이 실패해도 나머지는 만들어지고, 실패 사유는 errors 에 남습니다.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd

import db
import market
import sec

log = logging.getLogger("report")

FIN_TAGS = {"ATM", "ELOC", "CB", "OFFERING", "WARRANT"}
REG_FORMS = {"S-1", "S-1/A", "F-1", "F-1/A", "S-3", "S-3/A", "S-3ASR", "F-3", "F-3/A"}
FORM4_DAYS = 120

CASH_CONCEPTS = [("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
                 ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
                 ("ifrs-full", "CashAndCashEquivalents")]
# 현금처럼 쓸 수 있는 단기 투자(국채·MMF 등) — 바이오 소형주는 현금 대부분을 여기 둠. 현금과 같은 기준일 값만 더함
INVEST_CONCEPTS = [("us-gaap", "ShortTermInvestments"), ("us-gaap", "MarketableSecuritiesCurrent"),
                   ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"), ("us-gaap", "HeldToMaturitySecuritiesCurrent"),
                   ("ifrs-full", "CurrentInvestments"), ("ifrs-full", "OtherCurrentFinancialAssets")]
OCF_CONCEPTS = [("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
                ("ifrs-full", "CashFlowsFromUsedInOperatingActivities")]


def _num(x, nd=None):
    try:
        if x is None or pd.isna(x):
            return None
        v = float(x)
        return round(v, nd) if nd is not None else v
    except (TypeError, ValueError):
        return None


def _age(filed: str, today: date) -> int:
    return (today - date.fromisoformat(filed)).days


def _prices(ticker: str):
    d = market.download_daily([ticker], period="2y").get(ticker)
    if d is None or d.empty:
        return None
    d = d.dropna(subset=["Close"]).copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    return d


# ------------------------------------------------------------------ 1. 회사
def company_section(conn, ticker, df, filings, today) -> dict:
    fund = db.get_fundamentals(conn, ticker)
    if not fund or not db.is_fresh(fund.get("updated_at"), 24):
        fresh = market.fetch_fundamentals(ticker)
        if fresh:
            db.save_fundamentals(conn, ticker, fresh)
            fund = fresh
    fund = fund or {}
    out = {"name": fund.get("name"), "exchange": fund.get("exchange"), "market_cap": _num(fund.get("market_cap")),
           "shares_out": _num(fund.get("shares_out")), "float_shares": _num(fund.get("float_shares"))}
    if out["float_shares"] and out["shares_out"]:
        out["float_ratio"] = out["float_shares"] / out["shares_out"] * 100

    if df is not None and len(df) >= 21:
        high20 = float(df["High"].tail(20).max())
        price = float(df["Close"].iloc[-1])
        prior = float(df["Volume"].iloc[-21:-1].mean())
        out.update(price=price, price_date=df.index[-1].strftime("%Y-%m-%d"), high_20d=high20,
                   drawdown_pct=(price - high20) / high20 * 100 if high20 > 0 else None,
                   volume_mult=_num(df["Volume"].iloc[-1] / prior) if prior > 0 else None)
        out["closes"] = [{"date": i.strftime("%Y-%m-%d"), "close": _num(v, 4)} for i, v in df["Close"].tail(60).items()]
        ratio = df["Volume"] / df["Volume"].shift(1).rolling(20).mean()
        chg = df["Close"].pct_change() * 100
        sp = ratio[(ratio >= 5) & df["Volume"].gt(0)].tail(8)
        out["volume_spikes"] = [{"date": i.strftime("%Y-%m-%d"), "volume_mult": _num(v, 1), "change_pct": _num(chg.loc[i], 1)}
                                for i, v in sp.items()]
    try:
        out["splits"] = market.fetch_splits(ticker)
    except Exception as e:  # noqa: BLE001
        out["splits"] = []
        out["splits_error"] = str(e)
    out["delisting_notices"] = [
        {"filed": f["filed"], "url": f["url"]} for f in filings
        if "3.01" in {x.strip() for x in f["items"].split(",")} and _age(f["filed"], today) <= 1095]
    return out


# ------------------------------------------------------------------ 2. 조달 이력
def _reaction(df, filed: str):
    if df is None:
        return {}
    idx = int(df.index.searchsorted(pd.Timestamp(filed)))
    if idx < 25 or idx >= len(df):
        return {}
    prev = float(df["Close"].iloc[idx - 1])
    base20 = float(df["Close"].iloc[idx - 21])
    prior_avg = float(df["Volume"].iloc[idx - 25:idx - 5].mean())
    r = {"pre20_pct": _num((prev / base20 - 1) * 100, 1) if base20 > 0 else None,
         "vol_mult": _num(df["Volume"].iloc[idx - 5:idx].max() / prior_avg, 1) if prior_avg > 0 else None}
    if idx + 5 < len(df) and prev > 0:
        r["after5_pct"] = _num((float(df["Close"].iloc[idx + 5]) / prev - 1) * 100, 1)
    return r


def financing_section(client, conn, ticker, cik, filings, df, today) -> dict:
    cands = [f for f in filings if _age(f["filed"], today) <= 730 and (
        f["form"].startswith("424B") or f["form"] == "6-K" or
        (f["form"] in ("8-K", "8-K/A") and sec.RELEVANT_8K_ITEMS & {x.strip() for x in f["items"].split(",")}))][:40]
    events, errors = [], 0
    for f in cands:
        cached = db.get_filing(conn, f["accession"])
        if cached:
            tags = json.loads(cached["tags"] or "[]")
        else:
            try:
                tags = sec.scan_text(client.fetch_text(f["url"]), f["form"])
                db.save_filing(conn, ticker, cik, f, tags)
            except Exception as e:  # noqa: BLE001
                errors += 1
                log.warning("%s %s 확인 실패: %s", ticker, f["accession"], e)
                continue
        fin = [t for t in tags if t in FIN_TAGS]
        if fin:
            events.append({"date": f["filed"], "form": f["form"], "tags": fin, "url": f["url"], **_reaction(df, f["filed"])})
    for f in filings:
        if f["form"] in REG_FORMS and _age(f["filed"], today) <= 730:
            events.append({"date": f["filed"], "form": f["form"], "tags": ["REGISTRATION"], "url": f["url"]})
    events.sort(key=lambda e: e["date"], reverse=True)

    dates = sorted({e["date"] for e in events if e["tags"] != ["REGISTRATION"]})
    summary = {"count": len(dates), "errors": errors}
    if len(dates) >= 2:
        gaps = sorted((date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(dates, dates[1:]))
        summary["median_gap_days"] = gaps[len(gaps) // 2]
    if dates:
        summary["last_date"] = dates[-1]
    return {"events": events, "summary": summary}


# ------------------------------------------------------------------ 3. 런웨이
def _facts(cf: dict, concepts):
    """후보 항목 중 '가장 최근 기준일'이 있는 항목(예전엔 목록의 첫 항목 → 회사가 몇 년 전 다른 항목 이름으로 바꿨으면
    옛 항목의 오래된 값(예: 2022년 현금)을 써서 런웨이가 0.0개월·현금 −4,637억 원 같은 엉터리가 됐음). 같으면 목록 앞 항목."""
    best, best_end = (None, []), ""
    for taxo, name in concepts:
        node = cf.get("facts", {}).get(taxo, {}).get(name)
        if node and node.get("units"):
            unit, arr = next(iter(node["units"].items()))
            end = max((x.get("end", "") for x in arr), default="")
            if end > best_end:
                best, best_end = (unit, arr), end
    return best


def runway_section(client, cik) -> dict:
    out = runway_from_facts(client.companyfacts(cik))
    if "cash" not in out and "ocf" not in out:
        raise ValueError("XBRL 재무 데이터 없음 (해외기업 일부는 20-F 원문 확인 필요)")
    return out


def _ttm(dur: list[dict], months) -> tuple[float, str] | None:
    """최근 12개월 영업현금흐름 = 마지막 연간 + 올해 누적 − 작년 같은 기간 누적. 계산 못 하면 None."""
    annual = [x for x in dur if 11.5 <= months(x) <= 12.5]
    if not annual:
        return None
    fy = max(annual, key=lambda x: (x["end"], x.get("filed", "")))
    ytd = [x for x in dur if x["end"] > fy["end"] and 2.5 <= months(x) <= 9.5]
    if not ytd:
        return (float(fy["val"]), fy["end"]) if (date.today() - date.fromisoformat(fy["end"])).days <= 400 else None
    cur = max(ytd, key=lambda x: (x["end"], months(x), x.get("filed", "")))
    m = months(cur)
    prior = [x for x in dur if abs(months(x) - m) < 0.6 and abs((date.fromisoformat(cur["end"]) - date.fromisoformat(x["end"])).days - 365) <= 20]
    if not prior:
        return None
    p = max(prior, key=lambda x: x.get("filed", ""))
    return float(fy["val"]) + float(cur["val"]) - float(p["val"]), cur["end"]


def runway_from_facts(cf: dict) -> dict:
    """SEC companyfacts → 현금·영업현금흐름·월 소모량·런웨이(리포트·🪙 런웨이 저장소가 같이 씀). 자료가 없으면 빈 칸."""
    unit, cash_arr = _facts(cf, CASH_CONCEPTS)
    _, ocf_arr = _facts(cf, OCF_CONCEPTS)
    out = {"currency": unit}
    inst = [x for x in cash_arr if "start" not in x]
    if inst:
        c = max(inst, key=lambda x: x["end"])
        out["cash"] = c["val"]
        out["cash_asof"] = c["end"]
        out["cash_source"] = {"accn": c.get("accn"), "form": c.get("form")}
        inv = 0.0
        for taxo, name in INVEST_CONCEPTS:  # 같은 기준일 단기 투자를 현금에 더함(개념마다 한 번, 중복 개념은 가장 큰 값 하나)
            node = cf.get("facts", {}).get(taxo, {}).get(name) or {}
            vals = [float(x["val"]) for u in (node.get("units") or {}).values() for x in u if "start" not in x and x["end"] == c["end"]]
            if vals:
                inv = max(inv, max(vals))
        if inv > 0:
            out["cash_only"] = c["val"]
            out["investments"] = inv
            out["cash"] = c["val"] + inv
    def _m(x):
        return (date.fromisoformat(x["end"]) - date.fromisoformat(x["start"])).days / 30.44

    dur = [x for x in ocf_arr if "start" in x]
    best = None
    for x in dur:
        months = _m(x)
        if any(lo <= months <= hi for lo, hi in ((2.5, 3.5), (5.5, 6.5), (8.5, 9.5), (11.5, 12.5))):
            key = (x["end"], months)
            if best is None or key > best[0]:
                best = (key, x, months)
    if best:
        _, x, months = best
        out["ocf"] = x["val"]
        out["ocf_period"] = f"{x['start']} ~ {x['end']} ({months:.0f}개월)"
        out["ocf_source"] = {"accn": x.get("accn"), "form": x.get("form")}
        burn_val, burn_m, basis = x["val"], months, "최근 보고 기간"
        ttm = _ttm(dur, _m)
        if ttm is not None:  # 계절성 있는 회사(소매·재고)가 한 분기 마이너스로 '현금 소진'으로 잡히지 않게 최근 12개월로
            burn_val, burn_m, basis = ttm[0], 12.0, f"최근 12개월(~{ttm[1]})"
            out["ocf_ttm"] = ttm[0]
        out["burn_basis"] = basis
        out["monthly_burn"] = -burn_val / burn_m if burn_val < 0 else 0.0
        if out.get("cash") is not None and out["monthly_burn"] > 0:
            out["runway_months"] = out["cash"] / out["monthly_burn"]
    out["v"] = 4  # 계산 방식 버전(🪙 런웨이 저장소가 예전 값을 다시 받게) — 3: 단기 투자 포함 · 4: 가장 최근 항목 고르기
    return out


# ------------------------------------------------------------------ 4. 내부자 거래 (Form 4)
def _truthy(x) -> bool:
    return (x or "").strip().lower() in ("1", "true")


def parse_form4(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    owners = []
    for ro in root.findall("reportingOwner"):
        roles = []
        rel = ro.find("reportingOwnerRelationship")
        if rel is not None:
            if _truthy(rel.findtext("isDirector")):
                roles.append("이사")
            if _truthy(rel.findtext("isOfficer")):
                roles.append(rel.findtext("officerTitle") or "임원")
            if _truthy(rel.findtext("isTenPercentOwner")):
                roles.append("10%+ 주주")
        owners.append((ro.findtext("reportingOwnerId/rptOwnerName") or "?", ", ".join(roles) or "기타"))
    name, role = owners[0] if owners else ("?", "기타")
    rows = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        shares = _num(t.findtext("transactionAmounts/transactionShares/value"))
        rows.append({
            "date": t.findtext("transactionDate/value"), "owner": name, "role": role,
            "code": t.findtext("transactionCoding/transactionCode"),
            "direction": t.findtext("transactionAmounts/transactionAcquiredDisposedCode/value"),
            "shares": shares, "price": _num(t.findtext("transactionAmounts/transactionPricePerShare/value"), 4),
            "after": _num(t.findtext("postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
        })
    return rows


def insiders_section(client, filings, today) -> dict:
    f4 = [f for f in filings if f["form"] in ("4", "4/A") and _age(f["filed"], today) <= FORM4_DAYS][:15]
    rows, errors = [], 0
    for f in f4:
        try:
            # 렌더링된 경로(.../xslF345X05/doc.xml)에서 xsl 폴더를 빼야 원본 XML
            parts = f["url"].split("/")
            url = "/".join(parts[:-2] + [parts[-1]]) if "xsl" in parts[-2].lower() else f["url"]
            for r in parse_form4(client.fetch_raw(url, limit=200_000)):
                rows.append({**r, "filed": f["filed"], "url": f["url"]})
        except Exception as e:  # noqa: BLE001
            errors += 1
            log.warning("Form 4 %s 확인 실패: %s", f["accession"], e)
    rows.sort(key=lambda r: (r.get("date") or "", r.get("filed") or ""), reverse=True)
    buys = [r for r in rows if r["code"] == "P"]
    sells = [r for r in rows if r["code"] == "S"]
    return {"rows": rows, "errors": errors, "days": FORM4_DAYS,
            "summary": {"open_market_buys": len(buys), "open_market_sells": len(sells),
                        "buy_shares": sum(r["shares"] or 0 for r in buys), "sell_shares": sum(r["shares"] or 0 for r in sells)}}


# ------------------------------------------------------------------ 6. 타임라인
TAG_KO = {"ATM": "ATM", "ELOC": "ELOC", "CB": "전환사채", "OFFERING": "공모/사모", "WARRANT": "워런트", "REGISTRATION": "등록서류"}


def timeline(company, financing, insiders) -> list[dict]:
    ev = []
    for s in (company or {}).get("splits", []):
        ev.append({"date": s["date"], "type": "분할", "text": s["text"]})
    for n in (company or {}).get("delisting_notices", []):
        ev.append({"date": n["filed"], "type": "상장유지", "text": "Nasdaq 상장유지 관련 공시(8-K Item 3.01)", "url": n["url"]})
    for v in (company or {}).get("volume_spikes", []):
        ev.append({"date": v["date"], "type": "거래량", "text": f"거래량 ×{v['volume_mult']} · 등락 {v['change_pct']}%"})
    for e in (financing or {}).get("events", []):
        ev.append({"date": e["date"], "type": "조달", "text": f"{e['form']} · " + ", ".join(TAG_KO.get(t, t) for t in e["tags"]), "url": e["url"]})
    for r in (insiders or {}).get("rows", []):
        if r["code"] in ("P", "S"):
            ev.append({"date": r["date"] or r["filed"], "type": "내부자",
                       "text": f"{r['owner']}({r['role']}) {'매수' if r['code'] == 'P' else '매도'} {r['shares']:,.0f}주"
                               + (f" @ ${r['price']}" if r["price"] else ""), "url": r["url"]})
    return sorted(ev, key=lambda e: e["date"] or "", reverse=True)


# ------------------------------------------------------------------ 진입점
def build_report(client, conn, ticker: str, today: date | None = None) -> dict:
    today = today or date.today()
    rep: dict = {"ticker": ticker, "generated_at": db.utcnow_iso(), "errors": {}}

    def section(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            log.warning("%s 섹션 %s 실패: %s", ticker, name, e)
            rep["errors"][name] = str(e)
            return None

    cik, filings = None, []
    try:
        cik = client.cik_for(ticker)
        if cik:
            filings = sec.recent_filings(client.submissions(cik), cik)
        else:
            rep["errors"]["sec"] = "SEC CIK 없음 (ETF/ADR/신규상장/티커변경 가능성)"
    except Exception as e:  # noqa: BLE001
        rep["errors"]["sec"] = f"공시 목록 조회 실패: {e}"
    rep["cik"] = cik

    df = section("prices", lambda: _prices(ticker))
    rep["company"] = section("company", lambda: company_section(conn, ticker, df, filings, today))
    if cik:
        rep["financing"] = section("financing", lambda: financing_section(client, conn, ticker, cik, filings, df, today))
        rep["runway"] = section("runway", lambda: runway_section(client, cik))
        rep["insiders"] = section("insiders", lambda: insiders_section(client, filings, today))
    rep["timeline"] = timeline(rep.get("company"), rep.get("financing"), rep.get("insiders"))
    return rep
