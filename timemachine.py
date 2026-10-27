"""🕰 타임머신 — 지금 만든 조건(스승님 3대 조건)을 '과거의 그날'로 돌아가 적용해 보고, 실제로 급등했는지로 적중률을 잰다.

컨닝(미래 정보) 금지 규칙:
 1) 날짜 d 의 판정에는 d 일까지의 일봉만 쓴다(지표는 d 시점까지의 값).
 2) 공시는 d 일 '전에' 접수된 것만 본다(당일 공시는 접수 시각을 몰라 뺌).
 3) 결과(d 다음 날부터 H 거래일 안 최고가)는 판정이 끝난 뒤에만 붙인다.
대상: daily_prices(일봉 저장소)에 있는 종목 중 그날 가격 $MAX_PRICE 미만 · 20일 평균 거래대금 $MIN_DV 이상.
결과: 조건 조합별 신호 수 · 급등(+30%)·+10% 적중률(정밀도) · 기준(전체) 대비 배수 · 재현율(전체 급등 중 잡은 비율).
⚠️ 일봉 저장소에 상장폐지 종목이 거의 없으면(생존 편향) 적중률이 실제보다 좋게 나온다. 분봉(60분·5분) OBV 는 과거 분봉이 없어 일봉으로만 검증.
결과는 DB meta 'timemachine' 에 저장 · 🕰 타임머신 화면 · 매주 토요일 아침 갱신에서 다시 계산.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, timedelta

import numpy as np
import pandas as pd

import db
import setup3 as s3

H = 10                 # 결과를 보는 거래일 수
BIG, SMALL = 30.0, 10.0
MAX_PRICE = 20.0
MIN_DV = 50_000.0
STEP = 5               # 며칠마다 판정할지(거래일)
COMBOS = [("전체(기준)", ()), ("③ 희석 없음", ("dil",)), ("① 돈 들어옴(OBV만)", ("money",)), ("💰 강한 유입(거래량+OBV)", ("strong",)),
          ("② 지지·과매도", ("sup",)), ("②a 지지선만", ("supl",)), ("②b 과매도만", ("ovs",)),
          ("①+③ 돈+희석 없음", ("money", "dil")), ("✅ 3대 조건 모두(OBV만)", ("money", "sup", "dil")),
          ("💰 강한 유입+③", ("strong", "dil")), ("💰 강한 유입+지지선", ("strong", "supl")), ("💰 강한 유입+과매도", ("strong", "ovs")),
          ("💰 강한 유입+②+③", ("strong", "sup", "dil")), ("💰 강한 유입+지지선+③", ("strong", "supl", "dil")), ("💰 강한 유입+과매도+③", ("strong", "ovs", "dil")),
          ("🧲 매집형(가격↓·OBV↑)", ("accum",)), ("🧲 매집형+③", ("accum", "dil")),
          ("②b 과매도+③", ("ovs", "dil")), ("②b 과매도+매집형+③", ("ovs", "accum", "dil")),
          ("RSI≤25", ("ovs25",)), ("RSI≤25+③", ("ovs25", "dil")), ("RSI≤20+③", ("ovs20", "dil")),
          ("과매도+투매 끝", ("ovs", "climax")), ("과매도+투매 끝+③", ("ovs", "climax", "dil")),
          ("📰 호재 공시(5일 안)", ("good",)), ("과매도+호재 공시", ("ovs", "good")), ("과매도+호재 공시+③", ("ovs", "good", "dil")),
          ("🌀 거래량 진공", ("vac",)), ("🌀 폭풍의 눈(진공+52주 바닥)", ("vac", "low52")), ("🌀 폭풍의 눈+③", ("vac", "low52", "dil")),
          # 📡 숏 데이터(ChartExchange, 2026-10-27 C단계) — 공개된 뒤에만 켜짐(잔고 보고 +9거래일 · FTD 결제일 +15거래일 · 숏볼륨 다음 날)
          ("📡 숏 잔고 보고 +30%↑", ("si_up",)), ("📡 숏 잔고 급증+③", ("si_up", "dil")), ("📡 숏 잔고 급증+과매도+③", ("si_up", "ovs", "dil")),
          ("📡 FTD 급증(20일 평균 3배↑)", ("ftd_spike",)), ("📡 FTD 급증+③", ("ftd_spike", "dil")),
          ("📡 숏볼륨 60%↑", ("sv60",)), ("📡 숏볼륨 60%↑+③", ("sv60", "dil")), ("📡 숏볼륨 60%↑+과매도+③", ("sv60", "ovs", "dil")),
          ("📡 숏 신호 아무거나+③", ("short_any", "dil")),
          # 📐 스승 관점(2026-10-27, 일봉만 — 그날까지 자료): 일봉 5/20 골크 3일 안 · 기준봉 뒤 무릎~허리 눌림(생명선 위)
          ("📐 일봉 5/20 골든크로스", ("gc3",)), ("📐 골크+③", ("gc3", "dil")), ("📐 골크+💰 강한 유입", ("gc3", "strong")),
          ("📐 급등 후 허리 눌림(무릎~허리)", ("pb",)), ("📐 허리 눌림+③", ("pb", "dil")), ("📐 허리 눌림+① 돈 들어옴", ("pb", "money")), ("📐 허리 눌림+과매도+③", ("pb", "ovs", "dil"))]
SHORT_LAG = {"si": 9, "ftd": 15, "sv": 1}     # 공개 지연(거래일): FINRA 잔고 보고 → 약 9거래일 뒤 공개 · SEC FTD → 월 2회, 약 15거래일 뒤 · 숏볼륨 → 다음 날 아침
SHORT_ACTIVE = {"si": 10, "ftd": 10, "sv": 1}  # 공개된 뒤 조건이 켜져 있는 거래일 수
SI_UP_PCT, FTD_SPIKE_X, FTD_MIN, SV60 = 30.0, 3.0, 10_000, 60.0
GOOD_TYPES = ("FDA·임상", "계약·수주", "제휴·라이선스")   # 이벤트 연구에서 장전·$1 미만 등에서 좋았던 공시 종류
KEY_COMBOS = ["전체(기준)", "③ 희석 없음", "💰 강한 유입(거래량+OBV)", "②b 과매도+③", "RSI≤25+③", "RSI≤20+③", "과매도+호재 공시+③", "📡 숏 신호 아무거나+③", "📐 허리 눌림+③"]
COST = 2.0             # 비용 가정(왕복 %, 수수료·호가 차이·환전) — '비용 뺀 수익' 계산용
LIQ_DV = 500_000.0     # 거래가 활발한 종목: 20일 평균 거래대금 $50만↑
HS = (5, 10, 20, 40)   # 기간별 결과(거래일)
# ⚡ 단타 기준(매집 의심·애프터·장마감·3대 조건): 장마감에 사서 5거래일 안에 무조건 탈출. 목표에 닿으면 그 가격에 팔고, 못 닿으면 5일째 종가.
SHORT_EXIT = 5
SHORT_TARGETS = (10, 20, 30, 50)
SPLIT_TARGETS = (10, 20, 30)   # 분할 매도: 각 1/3
EXIT_DAYS = (1, 2, 3, 5)       # 못 튀면 며칠째 종가에 정리할지(실험)
EXIT_KEYS = ["전체(기준)", "②b 과매도만", "②b 과매도+③", "RSI≤25+③", "RSI≤20+③", "과매도+투매 끝+③", "과매도+호재 공시+③", "💰 강한 유입(거래량+OBV)", "💰 강한 유입+③", "💰 강한 유입+과매도+③", "🧲 매집형+③", "③ 희석 없음"]
SPLIT_YEAR = "2026"
HOLD_KEYS = ["전체(기준)", "③ 희석 없음", "②b 과매도+③", "RSI≤25+③", "RSI≤20+③", "과매도+호재 공시+③", "🌀 폭풍의 눈(진공+52주 바닥)", "🌀 폭풍의 눈+③"]            # 이 해 전(고르는 기간) vs 이 해부터(확인 기간)
STOP = -20.0           # '+30% 먼저' 판정: 이 손실에 먼저 닿으면 실패


def _covered(conn) -> set[str]:
    """공시 이력(sec_hist)이 있는 종목 — 없는 종목은 희석 '없음'이 아니라 '모름'."""
    try:
        return {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM sec_hist")}
    except Exception:  # noqa: BLE001
        return set()


def _dil_dates(conn, tickers: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    try:
        for t, f, fm, it in conn.execute("SELECT ticker, filed, form, COALESCE(items,'') FROM sec_hist"):
            if t in tickers and (str(fm).upper().startswith(s3.DIL_FORMS) or (str(fm).upper().startswith("8-K") and "3.02" in str(it))):
                out.setdefault(t, []).append(f)
    except Exception:  # noqa: BLE001
        pass
    return {k: sorted(v) for k, v in out.items()}


def _support_at(lows: np.ndarray, pos: list[int], i: int, px: float, lookback: int = 120, level: bool = False):
    """i 시점의 지지선 판정 — i-lookback ~ i-3 사이의 확정된 저점만(컨닝 없음). level=True 면 (판정, 가격대, 닿은 횟수)."""
    cand = [lows[j] for j in pos if i - lookback <= j <= i - 3]
    best, touches = None, 0
    for lv in cand:
        n = sum(1 for x in cand if abs(x / lv - 1) <= s3.SUPPORT_BAND)
        if n > touches or (n == touches and best is not None and lv > best):
            best, touches = lv, n
    ok = bool(best is not None and touches >= s3.SUPPORT_TOUCHES and best * 0.97 <= px <= best * (1 + s3.SUPPORT_ABOVE))
    return (ok, best, touches) if level else ok


SPLIT_JUMP = 5.0       # 하루 가격 변화가 이 배수를 넘고(또는 1/배수 아래)
SPLIT_DV = 3.0         # 거래 금액(가격×거래량)은 이 배수 안이면 → 병합 단위가 섞인 날(가짜 급등·가짜 거래량 폭발)
SPLIT_PAD = (140, 40)  # 그런 날 앞 140봉·뒤 40봉은 검증에서 뺌(지표 계산 구간 + 결과 구간)


def split_artifacts(c: np.ndarray, v: np.ndarray) -> list[int]:
    """병합(역분할) 전후 단위가 섞인 날의 위치. 진짜 폭등·폭락은 거래 금액이 크게 변하지만, 단위만 섞이면 가격은 N배·거래량은 1/N 이라 금액은 그대로."""
    out = []
    for i in range(1, len(c)):
        if c[i - 1] <= 0 or c[i] <= 0 or v[i - 1] <= 0 or v[i] <= 0:
            continue
        r = c[i] / c[i - 1]
        dv = (c[i] * v[i]) / (c[i - 1] * v[i - 1])
        if (r >= SPLIT_JUMP or r <= 1 / SPLIT_JUMP) and 1 / SPLIT_DV <= dv <= SPLIT_DV:
            out.append(i)
    return out


def _bday_shift(d0: str, n: int) -> str:
    return (pd.Timestamp(d0) + pd.offsets.BDay(n)).strftime("%Y-%m-%d")


def short_flags(conn, tickers) -> dict[str, dict[str, set]]:
    """{티커: {"si_up": {켜진 날짜…}, "ftd_spike": {...}, "sv60": {...}}} — 📡 ChartExchange 자료를 '공개된 뒤'부터 SHORT_ACTIVE 거래일 동안 켠다(컨닝 없음)."""
    out: dict[str, dict[str, set]] = {}
    tk = set(tickers)

    def on(t, key, d0, lag, active):
        s = out.setdefault(t, {"si_up": set(), "ftd_spike": set(), "sv60": set()})[key]
        a = _bday_shift(d0, lag)
        for j in range(active):
            s.add(_bday_shift(a, j))
    try:
        for t, d0, chg in conn.execute("SELECT ticker, date, change_pct FROM cx_short_interest WHERE reported=1 AND change_pct >= ?", (SI_UP_PCT,)):
            if t in tk:
                on(t, "si_up", d0, SHORT_LAG["si"], SHORT_ACTIVE["si"])
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = [(r[0], r[1], r[2] or 0) for r in conn.execute("SELECT ticker, settle_date, fails FROM cx_ftd ORDER BY ticker, settle_date")]
        hist: dict[str, list] = {}
        for t, d0, f in rows:
            if t not in tk:
                continue
            h = hist.setdefault(t, [])
            if len(h) >= 5 and f >= FTD_MIN:
                avg = sum(h[-20:]) / len(h[-20:])
                if avg > 0 and f >= FTD_SPIKE_X * avg:
                    on(t, "ftd_spike", d0, SHORT_LAG["ftd"], SHORT_ACTIVE["ftd"])
            h.append(f)
    except Exception:  # noqa: BLE001
        pass
    try:
        for t, d0 in conn.execute("SELECT ticker, date FROM cx_short_volume WHERE short_pct >= ? AND total >= 100000", (SV60,)):
            if t in tk:
                on(t, "sv60", d0, SHORT_LAG["sv"], SHORT_ACTIVE["sv"])
    except Exception:  # noqa: BLE001
        pass
    return out


def ticker_rows(t: str, d: pd.DataFrame, dil: list[str], start: str, end: str, step: int = STEP, covered: bool = True, ext: dict | None = None,
                good: list[str] | None = None, shorts: dict | None = None) -> list[dict]:
    """한 종목의 판정 날짜별 행: 조건(그날까지 정보) + 결과(그 뒤 H 거래일). shorts = short_flags()[티커]."""
    d = d.dropna(subset=["Close"]).sort_index()
    if len(d) < 60:
        return []
    c, v = d["Close"].astype(float).to_numpy(), d["Volume"].fillna(0).astype(float).to_numpy()
    hi = d["High"].astype(float).to_numpy() if "High" in d else c
    lo = d["Low"].astype(float).to_numpy() if "Low" in d else c
    n, pr = s3.N_RECENT, s3.N_PRIOR
    step_sign = np.sign(np.diff(c, prepend=c[0]))
    ob = np.cumsum(step_sign * v)
    import ta
    rsi = ta.rsi(pd.Series(c), 14).to_numpy()
    import chartview
    op = d["Open"].astype(float).to_numpy() if "Open" in d else np.r_[c[0], c[:-1]]
    gc3_arr, pb_arr = chartview.tm_flags(op, hi, lo, c, v)   # 📐 스승 관점 깃발(그날까지 자료만)
    mid = pd.Series(c).rolling(20).mean().to_numpy()
    sd = pd.Series(c).rolling(20).std().to_numpy()
    dv20 = pd.Series(c * v).rolling(20).mean().to_numpy()
    pos = [j for j in range(3, len(lo) - 3) if lo[j] == lo[j - 3:j + 4].min()]   # 저점(확정되려면 뒤 3봉이 필요 → _support_at 에서 i-3 까지만)
    days = [x.strftime("%Y-%m-%d") for x in d.index]
    hi_reg = hi.copy()                                                                  # 정규장 고가(비교용)
    if ext:  # 🌙 세션별 고점 기록이 있는 날은 하루 최고가 = 데이마켓·프리·정규·애프터 중 최고(결과 판정에만 쓰임 — 조건 계산엔 안 씀)
        hi = hi.copy()
        for k, dd in enumerate(days):
            e = ext.get(dd)
            if e and e > hi[k] and e < hi[k] * 20:   # 단위가 다른 값(병합 등) 방지
                hi[k] = e
    bad = split_artifacts(c, v)
    blocked = np.zeros(len(c), dtype=bool)
    for b in bad:                                                                        # 단위가 섞인 날 주변은 판정하지 않음
        blocked[max(0, b - SPLIT_PAD[1]):min(len(c), b + SPLIT_PAD[0])] = True
    out = []
    i0 = max(n + pr + 1, 30)
    for i in range(i0, len(c) - 1, step):
        day = days[i]
        if day < start or day > end or c[i] <= 0 or c[i] >= MAX_PRICE or not (dv20[i] >= MIN_DV) or blocked[i]:
            continue
        rv = v[i - n + 1:i + 1].sum()
        obv_ratio = (ob[i] - ob[i - n]) / rv if rv > 0 else None
        base = v[i - n - pr + 1:i - n + 1].mean()
        vol_ratio = v[i - n + 1:i + 1].mean() / base if base > 0 else None
        money = obv_ratio is not None and obv_ratio >= s3.OBV_MIN
        strong = money and vol_ratio is not None and vol_ratio >= s3.VOL_UP
        accum = money and c[i] <= c[i - n] * 1.02          # 🧲 매집형: 가격은 제자리·하락인데 OBV 는 오름(다이버전스)
        overs = bool((not np.isnan(rsi[i]) and rsi[i] <= s3.RSI_OVERSOLD) or (not np.isnan(sd[i]) and c[i] < mid[i] - 2 * sd[i]))
        supl, sup_lv, touches = _support_at(lo, pos, i, c[i], level=True)
        ovs25 = bool(not np.isnan(rsi[i]) and rsi[i] <= 25)
        ovs20 = bool(not np.isnan(rsi[i]) and rsi[i] <= 20)
        climax = False                                          # 투매 끝: 최근 10봉 안 '거래량 3배↑ + −10%↓' 날 뒤 최근 2봉 거래량이 그날의 절반 아래
        for j in range(max(21, i - 9), i):
            base_v = v[j - 20:j].mean()
            if base_v > 0 and v[j] >= 3 * base_v and c[j - 1] > 0 and c[j] / c[j - 1] - 1 <= -0.10 and v[i - 1:i + 1].mean() <= 0.5 * v[j]:
                climax = True
                break
        ref60 = v[max(0, i - 60):i].max() if i > 0 else 0
        vac = bool(ref60 > 0 and v[i] / ref60 * 100 <= 15)               # 🌀 거래량 진공: 오늘 거래량 ≤ 최근 60일 최대의 15%
        low52 = bool(c[i] <= lo[max(0, i - 249):i + 1].min() * 1.15)      # 52주(가능한 만큼) 최저가의 1.15배 이내
        g0 = (date.fromisoformat(day) - timedelta(days=5)).isoformat()
        good_ok = bool(good) and any(g0 <= g < day for g in good)  # 그날 '전' 5일 안 호재 공시(당일은 시각을 몰라 뺌)
        sup = overs or supl
        d0 = (date.fromisoformat(day) - timedelta(days=s3.DIL_DAYS)).isoformat()
        dil_ok = not any(d0 <= f < day for f in dil)                                   # 그날 '전에' 접수된 것만
        if i + 1 >= len(c):
            continue
        sh = shorts or {}
        si_up, ftd_sp, sv60 = day in sh.get("si_up", ()), day in sh.get("ftd_spike", ()), day in sh.get("sv60", ())
        row = {"ticker": t, "date": day, "price": c[i], "money": money, "strong": strong, "accum": accum, "sup": sup, "supl": supl, "ovs": overs,
               "ovs25": ovs25, "ovs20": ovs20, "climax": climax, "good": good_ok, "liq": bool(dv20[i] >= LIQ_DV), "vac": vac, "low52": low52,
               "si_up": si_up, "ftd_spike": ftd_sp, "sv60": sv60, "short_any": si_up or ftd_sp or sv60, "gc3": bool(gc3_arr[i]), "pb": bool(pb_arr[i]),
               "dil": dil_ok and covered, "covered": covered, "rsi": None if np.isnan(rsi[i]) else float(rsi[i]), "obv_r": obv_ratio, "vol_r": vol_ratio,
               "sup_lv": sup_lv, "touches": touches}
        for h in HS:                                                                     # ↓ 결과는 판정 뒤에만
            fut, flo = hi[i + 1:i + 1 + h], lo[i + 1:i + 1 + h]
            first, ex = False, None
            for h_, l_ in zip(fut, flo):                                                 # 같은 날 둘 다 닿으면 보수적으로 손절
                if l_ <= c[i] * (1 + STOP / 100):
                    ex = STOP
                    break
                if h_ >= c[i] * (1 + BIG / 100):
                    first, ex = True, BIG
                    break
            done = len(fut) == h and i + h < len(c)
            if ex is None and done:
                ex = (c[i + h] / c[i] - 1) * 100                                         # 익절·손절 없으면 기간 끝 종가에 팖
            row.update({f"up{h}": (fut.max() / c[i] - 1) * 100 if len(fut) else None, f"first{h}": first, f"exit{h}": ex,
                        f"ret{h}": (c[i + h] / c[i] - 1) * 100 if done else None, f"done{h}": done,
                        f"dn{h}": (flo.min() / c[i] - 1) * 100 if len(flo) else None})
        row.update({"max_up": row[f"up{H}"], "first": row[f"first{H}"], "min_dn": row[f"dn{H}"], "ret_h": row[f"ret{H}"], "complete": row[f"done{H}"]})
        # ⚡ 단타 기준: D+1·3·5 안 고점, 목표 매도 or 5일째 종가
        fh = hi[i + 1:i + 1 + SHORT_EXIT]
        fr = hi_reg[i + 1:i + 1 + SHORT_EXIT]
        row["ext_days"] = int(sum(1 for dd in days[i + 1:i + 1 + SHORT_EXIT] if ext and dd in ext))
        for dd_ in (1, 3, 5):
            row[f"p{dd_}"] = (fh[:dd_].max() / c[i] - 1) * 100 if len(fh) >= dd_ else None
            row[f"p{dd_}r"] = (fr[:dd_].max() / c[i] - 1) * 100 if len(fr) >= dd_ else None   # 정규장만
        row["done5"] = len(fh) == SHORT_EXIT and i + SHORT_EXIT < len(c)
        c5 = (c[i + SHORT_EXIT] / c[i] - 1) * 100 if row["done5"] else None
        row["c5"] = c5
        if row["done5"]:
            pk = row["p5"]
            for tg in SHORT_TARGETS:
                row[f"ev{tg}"] = float(tg) if pk >= tg else c5
            row["ev_split"] = sum((float(tg) if pk >= tg else c5) for tg in SPLIT_TARGETS) / len(SPLIT_TARGETS)
        for x in EXIT_DAYS:  # 못 튀면 x일째 종가에 정리: 그때까지 닿은 목표는 그 가격, 나머지는 x일째 종가
            if len(fh) >= x and i + x < len(c):
                px_ = fh[:x].max()
                cx = (c[i + x] / c[i] - 1) * 100
                pkx = (px_ / c[i] - 1) * 100
                row[f"evx{x}"] = sum((float(tg) if pkx >= tg else cx) for tg in SPLIT_TARGETS) / len(SPLIT_TARGETS)
            else:
                row[f"evx{x}"] = None
        if row["max_up"] is None:
            continue
        out.append(row)
    return out


MIN_BARS = 80


def fill_history(years: float = 3.0, limit: int | None = None, download=None, out=print) -> int:
    """과거 일봉 채우기: 과거 사례 종목(나스닥 전체)·스캐너 종목 중 일봉이 부족한 종목을 years 년치 받아 daily_prices 에 저장.
    (스캐너는 최근 3개월치만 쌓아서 타임머신이 '종목 0' 이 되던 문제) limit = 한 번에 받을 종목 수(아침 갱신은 300)."""
    import math
    since = (date.today() - timedelta(days=int(365 * years))).isoformat()
    need = int(230 * years * 0.8)
    with closing(db.connect()) as conn:
        uni = []
        for sql in ("SELECT ticker FROM case_progress", "SELECT DISTINCT ticker FROM daily_snapshots"):
            try:
                uni += [r[0] for r in conn.execute(sql)]
            except Exception:  # noqa: BLE001
                pass
        have = {r[0]: r[1] for r in conn.execute("SELECT ticker, COUNT(*) FROM daily_prices WHERE date >= ? GROUP BY ticker", (since,))}
        tried = set()
        m = db.get_meta("tm_fill_tried")
        try:
            tried = set(json.loads(m["value"])) if m and m.get("value") else set()
        except (TypeError, ValueError):
            tried = set()
    todo = [t for t in dict.fromkeys(uni) if have.get(t, 0) < need and t not in tried]
    if limit:
        todo = todo[:limit]
    if not todo:
        out("타임머신 일봉 채우기: 더 받을 종목 없음")
        return 0
    if download is None:
        import market
        download = lambda ts: market.download_daily(ts, period=f"{math.ceil(years)}y")  # noqa: E731
    n = 0
    for i in range(0, len(todo), 100):
        part = todo[i:i + 100]
        data = download(part) or {}
        with closing(db.connect()) as conn:
            for t, df in data.items():
                if df is not None and not df.empty:
                    n += db.upsert_daily_prices(conn, t, df) > 0
        tried |= set(part)  # 못 받은 종목(상장폐지 등)도 다시 시도하지 않게 기록
        db.set_meta("tm_fill_tried", json.dumps(sorted(tried)))
        out(f"타임머신 일봉 채우기: {min(i + 100, len(todo))}/{len(todo)}종목 · 저장 {n}")
    return n


def run(years: float = 2.0, max_tickers: int = 3000, step: int = STEP, out=print, load=None) -> dict:
    """과거 years 년을 판정해 조합별 성과를 저장. load(tickers, since) → {ticker: df} 를 주면 그걸로(테스트)."""
    end = (date.today() - timedelta(days=21)).isoformat()   # 결과(H 거래일)가 다 나온 날까지만
    start = (date.today() - timedelta(days=int(365 * years))).isoformat()
    since = (date.fromisoformat(start) - timedelta(days=200)).isoformat()
    with closing(db.connect()) as conn:
        tick = [r[0] for r in conn.execute("SELECT ticker FROM daily_prices WHERE date >= ? GROUP BY ticker HAVING COUNT(*) >= ? LIMIT ?", (since, MIN_BARS, max_tickers))]
        dil = _dil_dates(conn, set(tick))
        cov = _covered(conn)
        import exthilo
        exh = exthilo.day_highs(conn, tick, since)
        shorts = short_flags(conn, tick)   # 📡 숏 조건(ChartExchange 2년치)
        goods: dict[str, list[str]] = {}
        try:
            for t_, f_, ty_ in conn.execute("SELECT ticker, filed, types FROM ev_docs WHERE ok=1 AND filed >= ?", (since,)):
                if ty_ and any(g in ty_ for g in GOOD_TYPES):
                    goods.setdefault(t_, []).append(str(f_)[:10])
        except Exception:  # noqa: BLE001
            pass
        if load is None:
            def load(ts, sc):
                q = db.read_df(f"SELECT ticker, date, open, high, low, close, volume FROM daily_prices WHERE date >= ? AND ticker IN ({','.join('?' * len(ts))})",
                               (sc, *ts))
                res = {}
                for t, g in q.groupby("ticker"):
                    res[t] = g.set_index(pd.to_datetime(g["date"])).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
                return res
    rows, n_art = [], 0
    for k in range(0, len(tick), 300):
        part = tick[k:k + 300]
        for t, df in load(part, since).items():
            dd = df.dropna(subset=["Close"])
            if split_artifacts(dd["Close"].astype(float).to_numpy(), dd["Volume"].fillna(0).astype(float).to_numpy()):
                n_art += 1
            rows += ticker_rows(t, df, dil.get(t, []), start, end, step, covered=t in cov, ext=exh.get(t), good=goods.get(t), shorts=shorts.get(t))
        out(f"타임머신: {min(k + 300, len(tick))}/{len(tick)}종목")
    res = summarize(pd.DataFrame(rows)) if rows else {"combos": [], "n": 0}
    res.update({"start": start, "end": end, "n_tickers": len(tick), "h": H, "step": step, "max_price": MAX_PRICE, "min_dv": MIN_DV,
                "with_sec": int(sum(1 for t in tick if t in cov)), "split_artifact_tickers": n_art, "at": date.today().isoformat()})
    if not tick:
        res["hint"] = f"일봉 저장소에 종목당 {MIN_BARS}일 넘는 과거 일봉이 없어요(스캐너는 최근 3개월만 쌓음). PC에서 `python timemachine.py 2 --fill` 로 과거 일봉을 받으세요(처음 10~30분). 아침 갱신도 하루 300종목씩 채워요."
        out("타임머신: 과거 일봉 부족 → " + res["hint"])
        return res  # 빈 결과로 예전 결과를 덮지 않음
    db.set_meta("timemachine", json.dumps(res, ensure_ascii=False))
    out(f"타임머신 완료: 판정 {res['n']:,}건 · 종목 {len(tick):,}")
    return res


def _mask(df: pd.DataFrame, keys) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for k in keys:
        m &= df[k].astype(bool)
    return m


def summarize(df: pd.DataFrame) -> dict:
    """조합별(10거래일) 표 + 기간별(5·10·20·40일) 표 + 연도별 표. 기대값 = +30% 익절·−20% 손절·기간 끝 종가 매도 규칙의 평균 수익."""
    full = df
    df = df[df["complete"]] if "complete" in df else df
    if df.empty:
        return {"combos": [], "n": 0}
    big_all = int((df["max_up"] >= BIG).sum())
    base_big = float((df["max_up"] >= BIG).mean() * 100)
    base_small = float((df["max_up"] >= SMALL).mean() * 100)
    base_first = float(df["first"].mean() * 100) if "first" in df else None
    ex_col = f"exit{H}"
    base_ev = float(pd.to_numeric(df[ex_col], errors="coerce").mean()) if ex_col in df else None
    combos = []
    for name, keys in COMBOS:
        if any(k not in df for k in keys):
            continue
        sub = df[_mask(df, keys)]
        if sub.empty:
            combos.append({"조합": name, "신호 수": 0})
            continue
        hb = float((sub["max_up"] >= BIG).mean() * 100)
        row = {"조합": name, "신호 수": int(len(sub)), "종목 수": int(sub["ticker"].nunique()),
               f"+{BIG:g}% 적중(%)": round(hb, 2), "기준 대비(배)": round(hb / base_big, 2) if base_big else None,
               f"+{SMALL:g}% 적중(%)": round(float((sub["max_up"] >= SMALL).mean() * 100), 2),
               f"재현율 +{BIG:g}%(%)": round(float((sub["max_up"] >= BIG).sum()) / big_all * 100, 1) if big_all else None,
               "최고 상승 중앙값(%)": round(float(sub["max_up"].median()), 1)}
        if "first" in sub:
            rh = pd.to_numeric(sub["ret_h"], errors="coerce").dropna()
            row.update({f"+{BIG:g}% 먼저(−{-STOP:g}% 전)(%)": round(float(sub["first"].mean() * 100), 2),
                        "먼저 기준 대비(배)": round(float(sub["first"].mean() * 100) / base_first, 2) if base_first else None,
                        "10일 뒤 종가 중앙값(%)": None if rh.empty else round(float(rh.median()), 1),
                        "10일 뒤 오른 비율(%)": None if rh.empty else round(float((rh > 0).mean() * 100), 1),
                        "10일 최저 중앙값(%)": round(float(sub["min_dn"].median()), 1),
                        f"−{-STOP:g}% 이상 빠진 비율(%)": round(float((sub["min_dn"] <= STOP).mean() * 100), 1)})
        if ex_col in sub:
            ev = float(pd.to_numeric(sub[ex_col], errors="coerce").mean())
            row.update({"기대값(%)": round(ev, 2), "기대값 기준 대비(%p)": None if base_ev is None else round(ev - base_ev, 2)})
        combos.append(row)
    horizons = []
    for name, keys in COMBOS:
        if name not in KEY_COMBOS or any(k not in full for k in keys):
            continue
        sub_all = full[_mask(full, keys)]
        for h in HS:
            if f"done{h}" not in sub_all:
                continue
            sub = sub_all[sub_all[f"done{h}"].astype(bool)]
            if sub.empty:
                continue
            exv = pd.to_numeric(sub[f"exit{h}"], errors="coerce")
            rt = pd.to_numeric(sub[f"ret{h}"], errors="coerce").dropna()
            horizons.append({"조합": name, "기간(거래일)": h, "신호 수": int(len(sub)), f"+{BIG:g}% 먼저(%)": round(float(sub[f"first{h}"].mean() * 100), 2),
                             "기대값(%)": round(float(exv.mean()), 2), "종가 중앙값(%)": None if rt.empty else round(float(rt.median()), 1),
                             "종가 오른 비율(%)": None if rt.empty else round(float((rt > 0).mean() * 100), 1)})
    by_year = []
    for name, keys in COMBOS:
        if name not in KEY_COMBOS or any(k not in df for k in keys):
            continue
        for y, g in df[_mask(df, keys)].groupby(df["date"].str[:4]):
            by_year.append({"조합": name, "연도": y, "신호 수": int(len(g)), f"+{BIG:g}% 먼저(%)": round(float(g["first"].mean() * 100), 2),
                            "기대값(%)": round(float(pd.to_numeric(g[ex_col], errors="coerce").mean()), 2) if ex_col in g else None,
                            "⚡ 5일 분할 수익(%)": round(float(pd.to_numeric(g["ev_split"], errors="coerce").mean()), 2) if "ev_split" in g else None,
                            "⚡ D+1 +10%(%)": round(float((pd.to_numeric(g["p1"], errors="coerce") >= 10).mean() * 100), 1) if "p1" in g else None})
    short = []
    if "done5" in full:
        s5 = full[full["done5"].astype(bool)]
        base = {}
        for name, keys in COMBOS:
            if any(k not in s5 for k in keys):
                continue
            sub = s5[_mask(s5, keys)]
            if sub.empty:
                continue
            r_ = {"조합": name, "신호 수": int(len(sub)),
                  "D+1 +10%(%)": round(float((sub["p1"] >= 10).mean() * 100), 1), "D+3 +20%(%)": round(float((sub["p3"] >= 20).mean() * 100), 1),
                  "D+5 +30%(%)": round(float((sub["p5"] >= 30).mean() * 100), 1), "D+5 +50%(%)": round(float((sub["p5"] >= 50).mean() * 100), 1)}
            for tg in SHORT_TARGETS:
                r_[f"수익 +{tg}% 목표(%)"] = round(float(pd.to_numeric(sub[f"ev{tg}"], errors="coerce").mean()), 2)
            r_["수익 분할 10·20·30(%)"] = round(float(pd.to_numeric(sub["ev_split"], errors="coerce").mean()), 2)
            r_["5일째 종가 중앙값(%)"] = round(float(pd.to_numeric(sub["c5"], errors="coerce").median()), 1)
            r_[f"분할 수익 −비용{COST:g}%(%)"] = round(r_["수익 분할 10·20·30(%)"] - COST, 2)
            if "liq" in sub:
                lq = sub[sub["liq"].astype(bool)]
                r_["거래 활발 종목 신호"] = int(len(lq))
                r_["거래 활발 종목 분할 수익(%)"] = None if lq.empty else round(float(pd.to_numeric(lq["ev_split"], errors="coerce").mean()), 2)
            if name == "전체(기준)":
                base = r_
            else:
                r_["분할 수익 기준 대비(%p)"] = round(r_["수익 분할 10·20·30(%)"] - base.get("수익 분할 10·20·30(%)", 0), 2) if base else None
            short.append(r_)
    exit_tb = []
    if "evx1" in full:
        for name, keys in COMBOS:
            if name not in EXIT_KEYS or any(k not in full for k in keys):
                continue
            sub = full[_mask(full, keys)]
            if sub.empty:
                continue
            early, late = sub[sub["date"] < SPLIT_YEAR], sub[sub["date"] >= SPLIT_YEAR]
            r_ = {"조합": name, "신호 수": int(len(sub))}
            for x in EXIT_DAYS:
                col = f"evx{x}"
                r_[f"{x}일째 정리 · 전체(%)"] = round(float(pd.to_numeric(sub[col], errors="coerce").mean()), 2)
                r_[f"{x}일째 · ~{int(SPLIT_YEAR) - 1}(%)"] = None if early.empty else round(float(pd.to_numeric(early[col], errors="coerce").mean()), 2)
                r_[f"{x}일째 · {SPLIT_YEAR}~(%)"] = None if late.empty else round(float(pd.to_numeric(late[col], errors="coerce").mean()), 2)
            exit_tb.append(r_)
    hold_tb = []  # ⭐ 반등형: 보유 기간(5·10·20·40) × ~2025 / 2026~ — +30% 익절·−20% 손절·기간 끝 종가
    for name, keys in COMBOS:
        if name not in HOLD_KEYS or any(k not in full for k in keys):
            continue
        sub_all = full[_mask(full, keys)]
        r_ = {"조합": name}
        for h in HS:
            if f"done{h}" not in sub_all:
                continue
            sub = sub_all[sub_all[f"done{h}"].astype(bool)]
            e_, l_ = sub[sub["date"] < SPLIT_YEAR], sub[sub["date"] >= SPLIT_YEAR]
            r_[f"{h}일 · ~{int(SPLIT_YEAR) - 1}(%)"] = None if e_.empty else round(float(pd.to_numeric(e_[f"exit{h}"], errors="coerce").mean()), 2)
            r_[f"{h}일 · {SPLIT_YEAR}~(%)"] = None if l_.empty else round(float(pd.to_numeric(l_[f"exit{h}"], errors="coerce").mean()), 2)
            r_[f"{h}일 · {SPLIT_YEAR}~ 신호"] = int(len(l_))
        hold_tb.append(r_)
    ext_share = float((full["ext_days"] > 0).mean() * 100) if "ext_days" in full else 0.0
    ext_cmp = []
    if "ext_days" in full and "p1r" in full:
        e = full[(full["ext_days"] >= SHORT_EXIT) & full["done5"].astype(bool)]     # 5일 모두 시간외 기록이 있는 판정만
        for name, keys in COMBOS:
            if name not in KEY_COMBOS or any(k not in e for k in keys):
                continue
            sub = e[_mask(e, keys)]
            if len(sub) < 30:
                continue
            r_ = {"조합": name, "판정 수": int(len(sub))}
            for dd_, tg in ((1, 10), (3, 20), (5, 30), (5, 50)):
                a_ = float((pd.to_numeric(sub[f"p{dd_}r"], errors="coerce") >= tg).mean() * 100)
                b_ = float((pd.to_numeric(sub[f"p{dd_}"], errors="coerce") >= tg).mean() * 100)
                r_[f"D+{dd_} +{tg}% 정규장만(%)"] = round(a_, 1)
                r_[f"D+{dd_} +{tg}% 시간외 포함(%)"] = round(b_, 1)
            ext_cmp.append(r_)
    cov_share = float(df["covered"].mean() * 100) if "covered" in df else None
    return {"short": short, "exit_days": exit_tb, "hold": hold_tb, "ext_pct": round(ext_share, 2), "ext_cmp": ext_cmp, "combos": combos, "n": int(len(df)), "base_big": round(base_big, 2), "base_small": round(base_small, 2), "by_year": by_year, "horizons": horizons,
            "base_first": None if base_first is None else round(base_first, 2), "base_ev": None if base_ev is None else round(base_ev, 2),
            "covered_pct": None if cov_share is None else round(cov_share, 1)}


def replay(t: str, years: float = 2.0, conn=None) -> pd.DataFrame:
    """🕰 종목 하나 되돌려 보기: 그 종목의 매일 판정(그날까지 정보만)과 이후 결과. 급등 직전 조건이 켜져 있었는지 보는 용도."""
    since = (date.today() - timedelta(days=int(365 * years) + 200)).isoformat()
    q = db.read_df("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? AND date >= ? ORDER BY date", (t, since))
    if q.empty:
        return pd.DataFrame()
    d = q.set_index(pd.to_datetime(q["date"])).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    with closing(db.connect()) as c:
        dil = _dil_dates(c, {t}).get(t, [])
        cov = t in _covered(c)
    old_p, old_dv = globals()["MAX_PRICE"], globals()["MIN_DV"]
    globals()["MAX_PRICE"], globals()["MIN_DV"] = 1e9, 0.0          # 한 종목 보기는 가격·거래대금 거름 없이
    try:
        rows = ticker_rows(t, d, dil, (date.today() - timedelta(days=int(365 * years))).isoformat(), date.today().isoformat(), step=1, covered=cov)
    finally:
        globals()["MAX_PRICE"], globals()["MIN_DV"] = old_p, old_dv
    return pd.DataFrame(rows)


def load_result() -> dict | None:
    m = db.get_meta("timemachine")
    try:
        return json.loads(m["value"]) if m and m.get("value") else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    import sys
    import quiet  # noqa: F401
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    import config
    config.apply_overrides()
    if "--ticker" in sys.argv:
        tk = sys.argv[sys.argv.index("--ticker") + 1].upper()
        rp = replay(tk)
        if rp.empty:
            print(f"{tk}: 일봉 저장소에 자료가 없어요(먼저 timemachine.py 2 --fill)")
            sys.exit(0)
        _q = db.read_df("SELECT date, close, volume FROM daily_prices WHERE ticker=? ORDER BY date", (tk,))
        _bad = split_artifacts(_q["close"].astype(float).to_numpy(), _q["volume"].fillna(0).astype(float).to_numpy())
        if _bad:
            print(f"⚠️ 병합 단위가 섞인 날 {len(_bad)}개: " + ", ".join(str(_q['date'].iloc[b]) for b in _bad[:8]) + " — 그 앞뒤 구간은 판정에서 빠짐")
        big = rp[rp["up10"] >= BIG]
        print(f"{tk}: 판정 {len(rp)}일 · 10거래일 안 +{BIG:g}% 오른 '급등 직전 날' {len(big)}일 · 공시 이력 {'있음' if rp['covered'].iloc[0] else '없음'}")
        for k, nm in (("money", "① OBV 상승"), ("strong", "💰 강한 유입"), ("supl", "②a 지지선"), ("ovs", "②b 과매도"), ("dil", "③ 희석 없음")):
            print(f"  급등 직전 날 중 {nm}: {int(big[k].sum())}/{len(big)}일 · 전체 날 중 {int(rp[k].sum())}/{len(rp)}일")
        cols = ["date", "price", "up10", "first10", "exit10", "money", "strong", "supl", "sup_lv", "touches", "ovs", "rsi", "obv_r", "vol_r", "dil"]
        print(big[cols].round(3).to_string(index=False) if not big.empty else "(급등 직전 날 없음)")
        print("최근 30일:")
        print(rp[cols].tail(30).round(3).to_string(index=False))
        sys.exit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    yrs = float(args[0]) if args else 2.0
    if "--fill" in sys.argv:  # 과거 일봉부터 받기(검증 기간 + 120일 지표용 여유 → years+1 년)
        fill_history(years=yrs + 1)
    r = run(years=yrs)
    print(f"병합 단위가 섞인 날이 있는 종목 {r.get('split_artifact_tickers')}개(그 앞뒤 구간은 뺌)")
    print(f"공시 이력 있는 판정 비율 {r.get('covered_pct')}% (③ 희석 없음은 이 종목들만) · 기준: +30% {r.get('base_big')}% · +30% 먼저 {r.get('base_first')}% · 기대값 {r.get('base_ev')}%")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    if r.get("short"):
        print(f"\n[⚡ 단타 기준 · 장마감 매수 → 5거래일 안 탈출 · 시간외 고점 반영 판정 {r.get('ext_pct', 0)}%]")
        print(pd.DataFrame(r["short"]).to_string(index=False))
    if r.get("by_year"):
        print("\n[📅 연도별 · 주요 조합 — 해마다 비슷해야 우연이 아님]")
        print(pd.DataFrame(r["by_year"]).to_string(index=False))
    if r.get("hold"):
        print(f"\n[⭐ 반등형 보유 기간 검증 · +30% 익절·−20% 손절·기간 끝 종가 · ~{int(SPLIT_YEAR) - 1}년 vs {SPLIT_YEAR}년]")
        print(pd.DataFrame(r["hold"]).to_string(index=False))
    if r.get("exit_days"):
        print(f"\n[⏱ 못 튀면 며칠째 정리? · 분할 매도(+10·20·30% 1/3씩) 수익 · ~{int(SPLIT_YEAR) - 1}년으로 고르고 {SPLIT_YEAR}년으로 확인]")
        print(pd.DataFrame(r["exit_days"]).to_string(index=False))
    if r.get("ext_cmp"):
        print("\n[🌙 정규장만 vs 시간외(프리·애프터·데이마켓) 포함 — 5일 모두 시간외 기록이 있는 판정만]")
        print(pd.DataFrame(r["ext_cmp"]).to_string(index=False))
    cb = pd.DataFrame(r.get("combos", []))
    if not cb.empty:
        print("\n[참고: 조합별 · 10거래일 · +30% 익절/−20% 손절]")
        print(cb[[c for c in ["조합", "신호 수", "+30% 먼저(−20% 전)(%)", "먼저 기준 대비(배)", "기대값(%)", "기대값 기준 대비(%p)", "10일 뒤 종가 중앙값(%)",
                              "−20% 이상 빠진 비율(%)"] if c in cb]].to_string(index=False))
    if r.get("horizons"):
        print("\n[기간별 · 주요 조합]")
        print(pd.DataFrame(r["horizons"]).to_string(index=False))

