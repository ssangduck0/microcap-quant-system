"""🐷 저금통 — 저가(1000원 미만) 박스권 종목 발굴·관리.

후보 찾기: 전체 종목(과거 사례 수집 대상 목록) 중 최근 종가가 기준 원화 가격 미만인 종목의 일봉(Yahoo, 6개월)으로
  박스 지표를 계산한다: 지지(최근 N일 저가 10백분위)·저항(고가 90백분위), 박스 폭, 박스 안 체류 비율, 추세(월 %),
  지지선 반등 횟수, 지지 이탈 횟수, 박스 위치, 상단까지 여유, 20일 평균 거래대금 → 안정성 점수(0~100).
내 저금통: 카테고리별로 20~30개를 담고, 현재가의 박스 위치로 🟢 저점 / 🔴 고점 / ⚠️ 박스 이탈 / ⏸ 중간을 표시.
  박스 가격은 자동 계산값을 쓰되 직접 고칠 수 있다. 저금통 종목은 스캐너가 항상 우선 분석한다(블랙 제외 워치리스트와 같은 방식).
※ $1 미만 종목은 나스닥 최저호가 요건(30거래일 연속 $1 미만 → 미달 통지 → 역분할 위험) 때문에 박스가 깨질 수 있어 함께 표시한다.
"""
from __future__ import annotations

import json
import logging
from contextlib import closing
from datetime import date, timedelta

import numpy as np
import pandas as pd

import db

log = logging.getLogger("piggy")
DDL = [
    """CREATE TABLE IF NOT EXISTS piggy_list (ticker TEXT PRIMARY KEY, category TEXT, box_low REAL, box_high REAL, budget_krw REAL DEFAULT 1000000,
        note TEXT DEFAULT '', added_at TEXT, updated_at TEXT)""",
    "CREATE TABLE IF NOT EXISTS piggy_scan (date TEXT NOT NULL, ticker TEXT NOT NULL, price REAL, metrics TEXT, PRIMARY KEY (date, ticker))",
    "CREATE TABLE IF NOT EXISTS piggy_events (date TEXT NOT NULL, ticker TEXT NOT NULL, price REAL, box_low REAL, box_high REAL, PRIMARY KEY (date, ticker))",
    """CREATE TABLE IF NOT EXISTS piggy_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, ticker TEXT, buy REAL, sell REAL, qty REAL,
        fee_pct REAL DEFAULT 0, note TEXT DEFAULT '')""",
]
DEFAULT_CATEGORIES = ["좁은 박스(15~30%)", "넓은 박스(30% 이상)", "바이오·헬스", "중국·아시아", "에너지·자원", "기술", "기타"]
BAND = 0.2  # 박스 아래·위 20% 구간을 저점·고점으로 본다


def ensure_tables(conn=None) -> None:
    if conn is None:
        with closing(db.connect()) as c:
            ensure_tables(c)
        return
    for d in DDL:
        conn.execute(d)
    have = {r[1] for r in conn.execute("PRAGMA table_info(piggy_list)")}
    for col in ("catalyst", "catalyst_date"):  # 스승님 꿀팁: 준비된 호재(내용·날짜)
        if col not in have:
            conn.execute(f"ALTER TABLE piggy_list ADD COLUMN {col} TEXT")
    conn.commit()


# ---------------------------------------------------------------- 박스 지표 (순수 함수)
def box_metrics(df: pd.DataFrame | None, n: int = 60, recent: int = 10) -> dict | None:
    """박스는 최근 n일 중 '최근 recent일을 뺀 기준 구간'의 저가 10백분위(지지)·고가 90백분위(저항)로 정한다.
    최근 구간까지 넣으면 무너진 가격이 박스 안으로 들어와 지지선이 같이 내려가서 이탈을 못 잡기 때문이다."""
    if df is None or df.empty:
        return None
    d = df.dropna(subset=["High", "Low", "Close"]).tail(n)
    if len(d) < max(30, int(n * 0.8)):
        return None
    h, l, c = (d[k].to_numpy(float) for k in ("High", "Low", "Close"))
    v = d["Volume"].to_numpy(float) if "Volume" in d else np.zeros(len(c))
    if (c <= 0).any():
        return None
    k = min(recent, len(c) // 3)
    hb, lb = h[:-k], l[:-k]
    sup, res = float(np.percentile(lb, 10)), float(np.percentile(hb, 90))
    if sup <= 0 or res <= sup:
        return None
    width = (res / sup - 1) * 100
    inside = float(np.mean((c >= sup * 0.97) & (c <= res * 1.03)) * 100)
    slope = float(np.polyfit(np.arange(len(c)), np.log(c), 1)[0])
    trend_month = float((np.exp(slope * 21) - 1) * 100)
    bounces, i, mid = 0, 0, sup + 0.6 * (res - sup)
    while i < len(l):  # 지지선 근처(3% 이내)까지 내려온 뒤 10거래일 안에 박스 60% 높이까지 반등한 횟수
        if l[i] <= sup * 1.03:
            j = min(len(l), i + 11)
            if i + 1 < j and h[i + 1:j].max() >= mid:
                bounces += 1
                i = j
                continue
        i += 1
    breaks = int(np.sum(c < sup * 0.93))  # 지지선 아래 7% 넘게 마감한 날(전체 구간)
    rc = c[-k:]
    recent_break = bool(np.any(rc < sup * 0.95))      # 최근 구간에 박스 아래로 이탈
    recent_breakout = bool(np.any(rc > res * 1.05))   # 최근 구간에 박스 위로 돌파(박스가 바뀌었을 수 있음)
    price = float(c[-1])
    pos = (price - sup) / (res - sup)
    dvol = float(np.mean(c[-20:] * v[-20:]))
    flat = max(0.0, 1 - abs(trend_month) / 10)
    width_ok = 1.0 if 15 <= width <= 60 else (max(0.0, width / 15) if width < 15 else max(0.0, 1 - (width - 60) / 60))
    score = 100 * (0.40 * inside / 100 + 0.25 * flat + 0.20 * min(bounces, 4) / 4 + 0.15 * width_ok)
    if breaks >= 3 or recent_break:
        score *= 0.5
    below1 = 0
    for x in reversed(c):
        if x < 1.0:
            below1 += 1
        else:
            break
    return {"n": int(len(c)), "support": sup, "resistance": res, "width_pct": float(width), "inside_pct": inside, "trend_month_pct": trend_month,
            "bounces": bounces, "breaks": breaks, "recent_break": recent_break, "recent_breakout": recent_breakout, "price": price, "pos": float(pos),
            "upside_pct": float((res / price - 1) * 100), "dollar_vol": dvol, "below1_days": below1, "score": float(score)}


def zone(price: float | None, low: float | None, high: float | None, band: float = BAND) -> str:
    if price is None or low is None or high is None or high <= low or price <= 0:
        return "확인 불가"
    if price < low * 0.95:
        return "⚠️ 박스 이탈"
    pos = (price - low) / (high - low)
    if pos <= band:
        return "🟢 저점 구간"
    if pos >= 1 - band:
        return "🔴 고점 구간"
    return "⏸ 중간"


# ---------------------------------------------------------------- 후보 찾기
def universe() -> list[str]:
    """과거 사례 수집 대상(토스 거래 가능 나스닥 + 수동) 목록 — 토스를 다시 부르지 않는다."""
    try:
        df = db.read_df("SELECT ticker FROM case_progress WHERE status='done'")
        return sorted(df["ticker"])
    except Exception:  # noqa: BLE001
        return []


def screen(tickers: list[str], fx: float, max_krw: float = 1000.0, n: int = 60, chunk: int = 200, progress=None) -> pd.DataFrame:
    """1) 5일 일봉으로 가격 필터 → 2) 통과 종목만 6개월 일봉으로 박스 지표. 결과는 piggy_scan 에 오늘 날짜로 저장."""
    import market
    limit_usd = max_krw / fx
    cheap: list[str] = []
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        data = market.download_daily(part, period="5d", chunk=chunk)
        cheap += [t for t, df in data.items() if df is not None and not df.empty and 0 < float(df["Close"].dropna().iloc[-1]) < limit_usd]
        if progress:
            progress(min(1.0, (i + chunk) / max(len(tickers), 1)) * 0.4, f"가격 확인 {min(i + chunk, len(tickers))}/{len(tickers)}")
    rows = []
    today = date.today().isoformat()
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        for i in range(0, len(cheap), chunk):
            part = cheap[i:i + chunk]
            data = market.download_daily(part, period="6mo", chunk=chunk)
            for t in part:
                m = box_metrics(data.get(t), n)
                if m:
                    m.update(spike_stats(data.get(t)))  # 스승님 꿀팁: 급등 이력·간간이 발작
                    conn.execute("INSERT OR REPLACE INTO piggy_scan (date, ticker, price, metrics) VALUES (?,?,?,?)", (today, t, m["price"], json.dumps(m)))
                    rows.append({"ticker": t, **m})
            conn.commit()
            if progress:
                progress(0.4 + 0.6 * min(1.0, (i + chunk) / max(len(cheap), 1)), f"박스 분석 {min(i + chunk, len(cheap))}/{len(cheap)}")
        conn.execute("DELETE FROM piggy_scan WHERE date < ?", ((date.today() - timedelta(days=30)).isoformat(),))
        conn.commit()
    return pd.DataFrame(rows)


def latest_scan() -> tuple[str | None, pd.DataFrame]:
    ensure_tables()
    df = db.read_df("SELECT date, ticker, metrics FROM piggy_scan WHERE date=(SELECT MAX(date) FROM piggy_scan)")
    if df.empty:
        return None, pd.DataFrame()
    m = pd.DataFrame([{"ticker": r.ticker, **json.loads(r.metrics)} for r in df.itertuples()])
    return df["date"].iloc[0], m


# ---------------------------------------------------------------- 내 저금통
def items() -> pd.DataFrame:
    ensure_tables()
    return db.read_df("SELECT ticker, category, box_low, box_high, budget_krw, note, added_at, catalyst, catalyst_date FROM piggy_list ORDER BY category, ticker")


def add(ticker: str, category: str = "기타", box_low: float | None = None, box_high: float | None = None, budget_krw: float = 1_000_000, note: str = "") -> None:
    ensure_tables()
    with closing(db.connect()) as c:
        c.execute("""INSERT INTO piggy_list (ticker, category, box_low, box_high, budget_krw, note, added_at, updated_at) VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(ticker) DO UPDATE SET category=excluded.category, updated_at=excluded.updated_at""",
                  (ticker.strip().upper(), category or "기타", box_low, box_high, budget_krw, note, db.utcnow_iso(), db.utcnow_iso()))
        c.commit()


def update(ticker: str, **fields) -> None:
    keys = [k for k in fields if k in ("category", "box_low", "box_high", "budget_krw", "note", "catalyst", "catalyst_date")]
    if not keys:
        return
    ensure_tables()
    with closing(db.connect()) as c:
        c.execute(f"UPDATE piggy_list SET {', '.join(f'{k}=?' for k in keys)}, updated_at=? WHERE ticker=?",
                  (*[fields[k] for k in keys], db.utcnow_iso(), ticker.upper()))
        c.commit()


def remove(ticker: str) -> None:
    ensure_tables()
    with closing(db.connect()) as c:
        c.execute("DELETE FROM piggy_list WHERE ticker=?", (ticker.upper(),))
        c.commit()


def tickers() -> list[str]:
    import access
    if access.is_guest():  # 👥 방문객에게는 저금통 종목을 보이지 않음
        return []
    try:
        return list(items()["ticker"])
    except Exception:  # noqa: BLE001
        return []


def box_of(row: dict, metrics: dict | None) -> tuple[float | None, float | None, str]:
    """저금통 종목의 박스: 직접 입력값이 있으면 그것, 없으면 최근 분석값."""
    lo, hi = row.get("box_low"), row.get("box_high")
    lo = None if lo is None or pd.isna(lo) else float(lo)
    hi = None if hi is None or pd.isna(hi) else float(hi)
    if lo and hi:
        return lo, hi, "직접"
    if metrics:
        return lo or metrics["support"], hi or metrics["resistance"], "자동" if not (lo or hi) else "일부 직접"
    return lo, hi, "없음"


def metrics_map() -> dict[str, dict]:
    """{티커: 최근 박스 지표} — 저금통·알림용."""
    _, sc = latest_scan()
    return {r["ticker"]: r for r in sc.to_dict("records")} if not sc.empty else {}


# ---------------------------------------------------------------- 매매 기록 (전략이 실제로 되는지 검증)
def trades() -> pd.DataFrame:
    ensure_tables()
    return db.read_df("SELECT id, date, ticker, buy, sell, qty, fee_pct, note FROM piggy_trades ORDER BY date DESC, id DESC")


def save_trades(df: pd.DataFrame) -> None:
    ensure_tables()
    with closing(db.connect()) as c:
        c.execute("DELETE FROM piggy_trades")
        for r in df.to_dict("records"):
            t = str(r.get("ticker") or "").strip().upper()
            buy = r.get("buy")
            if not t or buy is None or pd.isna(buy):
                continue
            sell, qty, fee = r.get("sell"), r.get("qty"), r.get("fee_pct")
            c.execute("INSERT INTO piggy_trades (date, ticker, buy, sell, qty, fee_pct, note) VALUES (?,?,?,?,?,?,?)",
                      (str(r.get("date") or "")[:10], t, float(buy), None if sell is None or pd.isna(sell) else float(sell),
                       None if qty is None or pd.isna(qty) else float(qty), 0.0 if fee is None or pd.isna(fee) else float(fee), r.get("note") or ""))
        c.commit()


def trade_stats(df: pd.DataFrame, fx: float) -> dict:
    """청산된 거래(매도가 있음)만: 수익률 = 매도/매수 - 1 - 수수료(왕복 %), 손익(원) = 수량 × (매도-매수) × 환율 - 수수료."""
    d = df.dropna(subset=["buy", "sell"])
    d = d[(d["buy"] > 0)]
    if d.empty:
        return {"n": 0, "open": int(df["sell"].isna().sum()) if "sell" in df else 0}
    fee = d["fee_pct"].fillna(0)
    ret = (d["sell"] / d["buy"] - 1) * 100 - fee
    pnl = (d["qty"].fillna(0) * (d["sell"] - d["buy"]) * fx) - (d["qty"].fillna(0) * d["buy"] * fx * fee / 100)
    return {"n": int(len(d)), "open": int(df["sell"].isna().sum()), "win_rate": float((ret > 0).mean() * 100), "avg_ret": float(ret.mean()),
            "median_ret": float(ret.median()), "best": float(ret.max()), "worst": float(ret.min()), "pnl_krw": float(pnl.sum())}


# ---------------------------------------------------------------- 🤖 자동 담기·빼기 (2026-10-27)
# '저금통 기준' = 후보 찾기 기본 필터와 같다: 주가 < 기준 원화 · 안정성 ≥ · 반등 ≥ · 박스 폭 15~80% · 20일 거래대금 ≥ · 최근 이탈 없음 · 시장가 희석(ATM·ELOC·CB) 아님.
# 매일 아침 후보 분석 뒤: 기준에 맞는 종목을 안정성 순으로 최대 N개 '🤖 자동' 카테고리로 담고, 자동으로 담았던 종목이 기준에서 벗어나면 뺀다(직접 담은 종목은 안 뺌).
# 🧪 가상매매 저금통 전략은 기준에서 벗어난 종목(직접 담은 것 포함)을 그날 종가로 정리한다(익절이든 손절이든).
AUTO_CAT = "🤖 자동"
AUTO_WIDTH = (15.0, 80.0)


def rules() -> dict:
    import config
    return {"max_krw": float(getattr(config, "PIGGY_MAX_KRW", 1000.0)), "score": float(getattr(config, "PIGGY_AUTO_SCORE", 60)),
            "bounces": int(getattr(config, "PIGGY_AUTO_BOUNCES", 2)), "dvol": float(getattr(config, "PIGGY_AUTO_DVOL", 20000.0)),
            "n": int(getattr(config, "PIGGY_AUTO_N", 20)), "on": bool(getattr(config, "PIGGY_AUTO_ADD", True))}


def rule_ok(m: dict | None, dil_status: str | None, fx: float, r: dict | None = None) -> bool:
    """후보 분석 지표 한 줄이 저금통 기준에 맞는지."""
    r = r or rules()
    if not m or not m.get("price"):
        return False
    ok = (float(m["price"]) * fx < r["max_krw"] and float(m.get("score") or 0) >= r["score"] and int(m.get("bounces") or 0) >= r["bounces"]
          and AUTO_WIDTH[0] <= float(m.get("width_pct") or 0) <= AUTO_WIDTH[1] and float(m.get("dollar_vol") or 0) >= r["dvol"]
          and not bool(m.get("recent_break")) and dil_status not in ("ATM", "ELOC", "CB"))
    if ok and m.get("ticker"):   # ⑥ 주식수가 90일에 +20% 넘게 늘었으면(이력이 있을 때만) 자동 담기에서 제외
        try:
            with closing(db.connect()) as c:
                sc = shares_change(c, m["ticker"])
            if sc is not None and sc["pct"] > SHARES_MAX_PCT:
                return False
        except Exception:  # noqa: BLE001
            pass
    return ok


def _dil_map() -> dict:
    try:
        return dict(db.read_df("SELECT ticker, status FROM dilution").values)
    except Exception:  # noqa: BLE001
        return {}


def _fx() -> float:
    m = db.get_meta("usdkrw")
    return float((m or {}).get("value") or 1350.0)


def tickers_all() -> list[str]:
    """방문객 가림 없이 저금통 전체 티커(아침 작업·스캐너용)."""
    try:
        return list(items()["ticker"])
    except Exception:  # noqa: BLE001
        return []


def rule_breakers(fx: float | None = None) -> set[str]:
    """지금 저금통에 있는 종목 중 최근 후보 분석에서 기준에 벗어난 것(분석에 없는 종목은 판단 보류 → 넣지 않음)."""
    fx = fx or _fx()
    _d, sc = latest_scan()
    if sc.empty:
        return set()
    mm = {r["ticker"]: r for r in sc.to_dict("records")}
    dil, r = _dil_map(), rules()
    return {t for t in tickers_all() if t in mm and not rule_ok(mm[t], dil.get(t), fx, r)}


def auto_sync(fx: float | None = None, out=print) -> dict:
    """아침: 기준에 맞는 후보를 '🤖 자동'으로 담고, 자동으로 담았던 것 중 기준에서 벗어난 것을 뺀다. {"added": [...], "removed": [...], "breakers": [...]}"""
    r = rules()
    fx = fx or _fx()
    _d, sc = latest_scan()
    res: dict = {"added": [], "removed": [], "breakers": []}
    if not r["on"] or sc.empty:
        return res
    dil = _dil_map()
    it = items()
    have = dict(zip(it["ticker"], it["category"])) if not it.empty else {}
    ok = sc[[rule_ok(m, dil.get(m["ticker"]), fx, r) for m in sc.to_dict("records")]].sort_values("score", ascending=False)
    ok_set, scanned = set(ok["ticker"]), set(sc["ticker"])
    for t, cat in have.items():
        if cat == AUTO_CAT and t not in ok_set and t in scanned:   # 분석에 아예 없으면(데이터 못 받음) 보류
            remove(t)
            res["removed"].append(t)
    n_auto = sum(1 for t, cat in have.items() if cat == AUTO_CAT and t not in res["removed"])
    for t in ok["ticker"]:
        if n_auto >= r["n"]:
            break
        if t in have and t not in res["removed"]:
            continue
        add(t, AUTO_CAT, note="자동 담기(저금통 기준 통과)")
        res["added"].append(t)
        n_auto += 1
    res["breakers"] = sorted(rule_breakers(fx))
    out(f"저금통 자동: 담음 {', '.join(res['added']) or '-'} · 뺌 {', '.join(res['removed']) or '-'} · 기준 이탈 {', '.join(res['breakers']) or '-'}")
    return res



# ---------------------------------------------------------------- 알림 (스캐너가 사이클마다 호출)
ALERT_ZONES = ("🟢 저점 구간", "🔴 고점 구간", "⚠️ 박스 이탈")


def alerts(price_map: dict[str, float], today: str | None = None) -> list[str]:
    """저금통 종목이 저점·고점·이탈 구간에 새로 들어가면 알림 문구. 같은 날 같은 구간은 한 번만."""
    if not price_map:
        return []
    today = today or date.today().isoformat()
    st = json.loads((db.get_meta("piggy_alert_state") or {}).get("value") or "{}")
    mm = metrics_map()
    msgs = []
    for r in items().to_dict("records"):
        t = r["ticker"]
        p = price_map.get(t)
        if p is None:
            continue
        lo, hi, _ = box_of(r, mm.get(t))
        z = zone(p, lo, hi)
        prev = st.get(t) or {}
        if z in ALERT_ZONES and not (prev.get("date") == today and prev.get("zone") == z):
            act = {"🟢 저점 구간": "매수 검토", "🔴 고점 구간": "매도 검토", "⚠️ 박스 이탈": "손절·제외 검토"}[z]
            msgs.append(f"🐷 {t} {z} — {act}\n현재 ${p:.4f} · 박스 ${lo:.4f}~${hi:.4f} ({r.get('category') or ''})")
            if z == "🟢 저점 구간":  # 성과 공표: 저점 진입 뒤 박스 상단까지 갔는지 검증
                with closing(db.connect()) as c:
                    c.execute("INSERT OR IGNORE INTO piggy_events (date, ticker, price, box_low, box_high) VALUES (?,?,?,?,?)", (today, t, p, lo, hi))
                    c.commit()
            st[t] = {"date": today, "zone": z}
        elif z not in ALERT_ZONES:
            st[t] = {"date": today, "zone": z}
    db.set_meta("piggy_alert_state", json.dumps(st, ensure_ascii=False))
    return msgs


# ---------------------------------------------------------------- 스승님 꿀팁: 손익비 좋은 종목 고르기 (저금통 기준 5가지 + 발사대 + 종배 이력)
PROFIT_TIP_TITLE = "스승님 꿀팁 — 손익비 좋은 종목 고르기(저금통·종배)"
PROFIT_TIP_TEXT = """일단 손익비 좋은 종목을 고르세요. 동전주라도 상관없습니다.
1.상폐당할 위험 없고 2.펀더멘탈 단단하고 3.과거 급등이력 있고 4.시장가 희석없고 5.간간이 발작이 일어나는 종목이면 더 좋습니다.
(예: 제가 저금통으로 쓰는 종목 중 하나는 RMSG)
이런종목을 10~20개를 찾으세요. 그리고 리스트 만들어서 관리를 하세요.
이후엔 저점진입패턴을 스스로 정해보세요. 과거에 어느주가에서 횡보하다가 튀었는지 그 위치들을 잡아보심 됩니다.
그리고 준비된 호재가 있는지 체크 해보세요. AI에 물어보면 다 대답해 줍니다.
그렇게 해서 10~20개 종목을 컨트롤하시구요.
(예: DRMA 리스팅 후 관찰 중 이유없이 30% 빠진 뒤 다음날 50% 넘게 폭등)
나스닥 4000개중에서 찾으세요. 있습니다. 없을수가 없습니다.
그리고 포모가 너무 오면 10%정도의 시드로만 움직이세요. 그러면 잃어도 복구가 가능합니다.
그리고 종배 스킬을 익히세요. 장마감후 유난히 잘튀는 종목들이 있습니다.
그런 종목들이 공모나 시장가희석으로 주가가 파괴되었다면 피하세요. 장마감 이후에도 역시 눌릴 가능성 높습니다.
희석이 공백이거나 워런트정도의 희석밖에 없다면 공략하기가 좋습니다. 하락율에서 일단 찾으시구요.
(예: FBGL — 희석공백에 과매도라 장마감후 30%정도 튐)"""
SEED_TIP = "포모가 너무 오면 시드의 10% 정도로만 움직이세요. 그러면 잃어도 복구가 가능합니다. — 스승님"


def spike_stats(df: pd.DataFrame | None, days: int = 126, big: float = 30.0, small: float = 20.0) -> dict:
    """최근 days거래일: 고가가 전일 종가 대비 +small% 이상(발작)·+big% 이상(급등)인 날 수, 최대 폭."""
    if df is None or len(df) < 3:
        return {"spikes20": None, "spikes30": None, "max_spike": None}
    d = df.dropna(subset=["High", "Close"]).tail(days + 1)
    up = (d["High"] / d["Close"].shift(1) - 1).dropna() * 100
    return {"spikes20": int((up >= small).sum()), "spikes30": int((up >= big).sum()), "max_spike": float(up.max()) if len(up) else None}


def launch_zones(df: pd.DataFrame | None, spike: float = 30.0, base_days: int = 10, merge_pct: float = 10.0) -> list[dict]:
    """발사대: 과거 급등일(고가 ≥ 전일 종가 +spike%) 직전 base_days 동안 횡보하던 가격(종가 중앙값). 가까운 자리(±merge_pct%)는 합친다."""
    if df is None or len(df) < base_days + 2:
        return []
    d = df.dropna(subset=["High", "Close"])
    c, h = d["Close"].to_numpy(float), d["High"].to_numpy(float)
    raw = []
    for i in range(base_days + 1, len(d)):
        if c[i - 1] > 0 and (h[i] / c[i - 1] - 1) * 100 >= spike:
            base = float(np.median(c[i - base_days:i]))
            raw.append({"date": d.index[i].strftime("%Y-%m-%d"), "level": base, "spike_pct": (h[i] / c[i - 1] - 1) * 100})
    zones: list[dict] = []
    for r in sorted(raw, key=lambda x: x["level"]):
        if zones and r["level"] <= zones[-1]["level"] * (1 + merge_pct / 100):
            z = zones[-1]
            z["dates"].append(r["date"])
            z["level"] = float(np.mean([z["level"]] * (len(z["dates"]) - 1) + [r["level"]]))
            z["max_spike"] = max(z["max_spike"], r["spike_pct"])
        else:
            zones.append({"level": r["level"], "dates": [r["date"]], "max_spike": r["spike_pct"]})
    return zones


def near_zone(price: float | None, zones: list[dict], above_pct: float = 10.0) -> dict | None:
    """현재가가 발사대 자리 근처(자리 ~ 자리 +above_pct%)인지. 가장 가까운 자리를 돌려준다."""
    if not price or not zones:
        return None
    best = min(zones, key=lambda z: abs(price / z["level"] - 1))
    dist = (price / best["level"] - 1) * 100
    return {**best, "dist_pct": dist, "near": -5.0 <= dist <= above_pct}


def close_bounce(conn, ticker: str) -> dict | None:
    """종배 이력: 과거 급락일(-10% 이하) 다음날 시가·고가·종가(과거 사례 DB). '장마감 후 잘 튀는 종목'을 다음날 시가 갭으로 본다."""
    try:
        rows = conn.execute("SELECT next_open_pct, next_high_pct, next_close_pct FROM case_events WHERE ticker=? AND next_open_pct IS NOT NULL", (ticker.upper(),)).fetchall()
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    o = np.array([r[0] for r in rows], float)
    hi = np.array([r[1] for r in rows if r[1] is not None], float)
    return {"n": int(len(o)), "gap_up_rate": float((o > 0).mean() * 100), "open_avg": float(o.mean()), "high_avg": float(hi.mean()) if len(hi) else None,
            "open_ge10_rate": float((o >= 10).mean() * 100)}


def quality(ticker: str, conn, df_long: pd.DataFrame | None, dilution_status: str | None = None) -> list[dict]:
    """스승님의 손익비 기준 5가지. 결과 True=통과, False=미달, "주의"=경계(①만), None=확인 불가."""
    t = ticker.upper()
    out = []
    below1 = 0
    if df_long is not None and not df_long.empty:
        for x in reversed(df_long["Close"].dropna().tolist()):
            if x < 1.0:
                below1 += 1
            else:
                break
    rep = db.get_report(t) or {}
    notices = ((rep.get("company") or {}).get("delisting_notices") or [])
    recent_notice = [n for n in notices if n.get("filed", "") >= (date.today() - timedelta(days=365)).isoformat()]
    try:
        ev = conn.execute("SELECT date, kind FROM events WHERE ticker=? AND kind IN ('상장유지 미달','상장유지 기한')", (t,)).fetchall()
    except Exception:  # noqa: BLE001
        ev = []
    # 나스닥: $1 미만 30거래일 → 미달 통지 → 180일 회복 기간. 동전주라도 바로 상폐는 아니므로 단계로 본다(❌ 위험 / ⚠️ 주의 / ✅ 통과)
    soon = (date.today() + timedelta(days=60)).isoformat()
    deadline_near = any(e["kind"] == "상장유지 기한" and e["date"] <= soon for e in ev)
    if below1 >= 180 or (recent_notice and deadline_near):
        res1 = False
    elif below1 >= 30 or recent_notice or any(e["kind"] == "상장유지 미달" and e["date"] >= (date.today() - timedelta(days=365)).isoformat() for e in ev):
        res1 = "주의"
    else:
        res1 = True
    out.append({"기준": "① 상폐 위험 없음", "결과": None if df_long is None else res1,
                "값": f"$1 미만 {below1}거래일" + (f" · 미달 통지 {recent_notice[0]['filed']}" if recent_notice else "")
                     + (" · 회복 기한 60일 이내/지남" if deadline_near else (" · 일정에 상장유지 항목 있음" if ev else ""))})
    rw = (rep.get("runway") or {}).get("runway_months")
    out.append({"기준": "② 펀더멘탈 단단(런웨이 12개월 이상)", "결과": None if rw is None else rw >= 12, "값": "종목 리포트 없음" if rw is None else f"런웨이 {rw:.1f}개월"})
    sp_y = spike_stats(df_long, days=252)
    out.append({"기준": "③ 과거 급등 이력(1년 안에 +30% 이상)", "결과": None if sp_y["spikes30"] is None else sp_y["spikes30"] >= 1,
                "값": "-" if sp_y["spikes30"] is None else f"{sp_y['spikes30']}회 · 최대 +{(sp_y['max_spike'] or 0):.0f}%"})
    out.append({"기준": "④ 시장가 희석 없음(ATM·ELOC·전환사채 아님)", "결과": None if dilution_status in (None, "UNKNOWN") else dilution_status not in ("ATM", "ELOC", "CB"),
                "값": dilution_status or "미확인"})
    sp_h = spike_stats(df_long, days=126)
    out.append({"기준": "⑤ 간간이 발작(6개월에 +20% 이상 3회 이상)", "결과": None if sp_h["spikes20"] is None else sp_h["spikes20"] >= 3,
                "값": "-" if sp_h["spikes20"] is None else f"{sp_h['spikes20']}회"})
    # 2026-10-27 스승님 '반복 흐름 주의사항': ⑥ 주식수 변동이 크지 않을 것 · ⑦ 희석 구조가 변하지 않았을 것(③ 펀더멘털은 ② 런웨이가 맡음)
    sc = shares_change(conn, t)
    out.append({"기준": "⑥ 주식수 변동 작음(90일 +20% 이내)", "결과": None if sc is None else sc["pct"] <= SHARES_MAX_PCT,
                "값": _hold_text(conn, t) if sc is None else f"{sc['pct']:+.1f}% ({sc['d0']}→{sc['d1']} · {sc.get('src', 'ChartExchange')})"})
    dc = dilution_changed(conn, t, dilution_status)
    out.append({"기준": "⑦ 희석 구조 변화 없음(45일)", "결과": None if dc is None else not dc["changed"],
                "값": "이력 부족" if dc is None else ("변화 없음 · " + (dilution_status or "미확인") if not dc["changed"] else f"{dc['from']} → {dc['to']} ({dc['date']})")})
    return out


SHARES_MAX_PCT = 20.0   # ⑥ 90일 발행주식 증가 상한
DIL_WINDOW_DAYS = 45    # ⑦ 희석 상태 변화를 보는 기간


def shares_change(conn, ticker: str, days: int = 90) -> dict | None:
    """⑥ 주식수 변동률. ① ChartExchange 일별 이력(cx_shares — 우리 요금제(Tier 1)는 주식수 엔드포인트가 403 이라 비어 있음)
    → ② SEC 분기 표지 이력(shares_hist, 2026-10-28 추가: 직전 두 분기 표지 비교·사이 분할 반영 = shares.change). 둘 다 없으면 None(판정 보류 ➖)."""
    try:
        rows = conn.execute("SELECT date, shares_out FROM cx_shares WHERE ticker=? AND shares_out > 0 AND date >= date('now', ?) ORDER BY date",
                            (ticker.upper(), f"-{days} day")).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    if len(rows) >= 2:
        (d0, s0), (d1, s1) = rows[0], rows[-1]
        if (date.fromisoformat(d1) - date.fromisoformat(d0)).days >= 30:
            return {"pct": (s1 / s0 - 1) * 100, "d0": d0, "d1": d1, "from": s0, "to": s1, "src": "ChartExchange"}
    try:
        import shares
        return shares.change(ticker, conn)
    except Exception:  # noqa: BLE001
        return None


def _hold_text(conn, ticker: str) -> str:
    """⑥ 판정 보류(➖) 일 때 화면 값: 이유별 문구(shares.hold_reason). 2026-10-28: 20-F 연 1회 보고 종목이 '표지 2개 미만' 으로 잘못 나오던 것을 고침."""
    try:
        import shares
        return "판정 보류 — " + shares.hold_reason(ticker, conn)
    except Exception:  # noqa: BLE001
        return "주식수 이력 없음(SEC 표지 2개 미만 · ChartExchange 없음)"


def share_targets(conn, days: int = 30) -> list[str]:
    """🐷 ⑥ 용 SEC 표지 이력을 받아 둘 종목: 담은 종목(piggy_list) 먼저, 그다음 최근 days 일 스캔 후보(piggy_scan). 아침 작업(cases.update)이 shares.build_missing 에 넘긴다."""
    out: list[str] = []
    try:
        out += [r[0] for r in conn.execute("SELECT ticker FROM piggy_list ORDER BY ticker")]
        out += [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM piggy_scan WHERE date >= date('now', ?) ORDER BY ticker", (f"-{days} day",))]
    except Exception:  # noqa: BLE001
        pass
    seen, res = set(), []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            res.append(t)
    return res


def dilution_changed(conn, ticker: str, cur_status: str | None, days: int = DIL_WINDOW_DAYS) -> dict | None:
    """희석 상태 이력(dilution_hist)에서 최근 days 일 안 상태가 바뀌었는지. 이력이 기간 밖까지 없으면 None."""
    try:
        rows = conn.execute("SELECT date, status FROM dilution_hist WHERE ticker=? ORDER BY date", (ticker.upper(),)).fetchall()
    except Exception:  # noqa: BLE001
        return None
    since = (date.today() - timedelta(days=days)).isoformat()
    older = [r for r in rows if r[0] < since]
    recent = [r for r in rows if r[0] >= since]
    if not older and len(recent) < 2:
        return None
    seq = ([older[-1]] if older else []) + recent
    for a, b in zip(seq, seq[1:]):
        if (a[1] or "UNKNOWN") != (b[1] or "UNKNOWN") and "UNKNOWN" not in (a[1] or "UNKNOWN", b[1] or "UNKNOWN"):
            return {"changed": True, "from": a[1], "to": b[1], "date": b[0]}
    return {"changed": False, "from": seq[0][1], "to": seq[-1][1], "date": seq[-1][0]}


def seed_krw() -> float | None:
    m = db.get_meta("piggy_seed_krw")
    try:
        return float(m["value"]) if m and m.get("value") else None
    except (TypeError, ValueError):
        return None


def set_seed_krw(v: float) -> None:
    db.set_meta("piggy_seed_krw", str(float(v)))
