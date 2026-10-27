"""🔍 부검 — 놓친 펌핑과 실패한 신호를 '그날 이전 정보'로 다시 보고, 특징과 원인 태그를 쌓는다 (1단계, 2026-10-28).

왜: 발굴(수급·애프터·저금통·3대 조건·PICK…)의 승률을 올리려면 "왜 틀렸나(실패)"와 "왜 못 잡았나(놓친 펌핑)"가 데이터로 남아야
     2단계 신호 승률 모델과 3단계 Claude 복기가 가능하다. 지금은 신호·결과만 있고 원인이 없다.
무엇을:
  1) 펌핑 부검 `pump_autopsy`: 어제 종가 +30%↑ 또는 고가(세션 포함) +50%↑ 종목 → 우리 신호(🏆 출처 전부, 오름 방향, 10일 안)·보유(저금통·가상매매·워치)가 있었나(적중/놓침)
     + 전날 기준 특징(가격대·거래대금·낙폭·RSI·📐 채널 위치·유통주식·시총·희석 상태·공매 잔고·숏볼륨·Reg SHO·7일 공시/뉴스·🚦 장세) + 촉매(그날 전후 공시·뉴스 제목) + 시작 세션
  2) 실패 부검 `signal_autopsy`: 🏆 성과 공표에서 '실패'로 판정된 신호 → 신호일 기준 특징 + 실패 유형 태그(규칙): 장세 나쁨 · 희석 출회 · 공매 눌림 · 거래량 없음 · 호재 없음 · 시간외 펌핑 되돌림 · 생명선 이탈 · 시장 하락
  3) `regime_hist`: 🚦 신호등 날짜별 기록(regime.refresh 가 넣음) — 과거 날짜의 장세를 알 수 있게
컨닝 금지: 특징은 as_of(전날/신호일)까지의 표만 쓴다. 실패 태그만 '그 뒤에 무슨 일이 있었나'를 본다(부검이니까).
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

import db

PUMP_PCT = 30.0        # 종가 기준 전일 대비 +30%
PUMP_HI_PCT = 50.0     # 고가(세션 포함) 기준 +50%
SIGNAL_LOOKBACK = 10   # 펌핑 전 며칠 안의 우리 신호를 '잡았다'로 볼지
MIN_PREV_DVOL = 20_000.0   # 전날 거래대금이 이보다 작은 종목(거래 없는 휴지)은 펌핑 목록에서 뺌
FEAT_KEYS = ["px", "bucket", "chg1", "dd20", "vol_x", "dvol20", "rsi", "zone", "stage", "base_days", "above50", "gc_days", "sar", "bb_sq", "float", "mcap",
             "dil", "si_pct", "dtc", "sv_pct", "regsho", "sec7", "sec_good7", "news7", "news_good7", "regime", "regime_pts"]
TAGS = {"regime": "🚦 장세 나쁨", "dilution": "🧾 희석 출회(424B·S-1·ATM)", "short": "🩳 공매 눌림(숏볼륨 60%↑)", "thin": "💧 거래량 없음", "nocat": "📰 호재 없음",
        "ext": "🌙 시간외 펌핑 되돌림", "life": "📐 생명선 이탈", "market": "📉 시장 하락", "other": "❓ 기타"}
DDL = [
    """CREATE TABLE IF NOT EXISTS pump_autopsy (date TEXT NOT NULL, ticker TEXT NOT NULL, pump_pct REAL, hi_pct REAL, session TEXT, prev_close REAL, volume REAL,
       caught INTEGER, caught_by TEXT, held TEXT, features TEXT, catalyst TEXT, created_at TEXT, PRIMARY KEY (date, ticker))""",
    """CREATE TABLE IF NOT EXISTS signal_autopsy (source TEXT NOT NULL, date TEXT NOT NULL, ticker TEXT NOT NULL, status TEXT, entry REAL, max_up REAL, max_down REAL,
       features TEXT, tags TEXT, created_at TEXT, PRIMARY KEY (source, date, ticker))""",
    "CREATE TABLE IF NOT EXISTS regime_hist (date TEXT PRIMARY KEY, light TEXT, points INTEGER, at TEXT)",
]


def ensure(conn) -> None:
    for d in DDL:
        conn.execute(d)


# ---------------------------------------------------------------- 🚦 장세 기록
def record_regime(conn, day: str, light: str, points: int) -> None:
    ensure(conn)
    conn.execute("INSERT OR REPLACE INTO regime_hist VALUES (?,?,?,?)", (day, light, int(points), db.utcnow_iso()))


def regime_on(conn, day: str) -> dict | None:
    """그날(없으면 5일 안 가장 가까운 전날)의 신호등."""
    try:
        ensure(conn)
        r = conn.execute("SELECT date, light, points FROM regime_hist WHERE date <= ? AND date >= date(?, '-5 day') ORDER BY date DESC LIMIT 1", (day, day)).fetchone()
        return None if not r else {"date": r[0], "light": r[1], "points": r[2]}
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 자료 꺼내기
def _daily(conn, ticker: str, asof: str, n: int = 140) -> pd.DataFrame:
    rows = conn.execute("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? AND date <= ? ORDER BY date DESC LIMIT ?", (ticker, asof, n)).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([tuple(r) for r in rows], columns=["date", "Open", "High", "Low", "Close", "Volume"]).iloc[::-1]
    df.index = pd.to_datetime(df["date"])
    return df.drop(columns=["date"])


def prev_trading_day(conn, day: str) -> str | None:
    r = conn.execute("SELECT MAX(date) FROM daily_prices WHERE date < ?", (day,)).fetchone()
    return r[0] if r and r[0] else None


def find_pumps(conn, day: str, tradable_only: bool = True) -> list[dict]:
    """그날 펌핑 종목: 종가 +30%↑ 또는 고가(정규장 고가·세션별 고점) +50%↑. 토스 급상승 순위(+30%↑)도 합친다."""
    prev = prev_trading_day(conn, day)
    rows = conn.execute("SELECT ticker, close, high, volume FROM daily_prices WHERE date=?", (day,)).fetchall()
    pv = {}
    if prev:
        for t, c, v in conn.execute("SELECT ticker, close, volume FROM daily_prices WHERE date=?", (prev,)):
            pv[t] = (c, v)
    ext = {}
    try:
        for t, nh, ph, rh, poh in conn.execute("SELECT ticker, night_high, pre_high, reg_high, post_high FROM ext_hilo WHERE date=?", (day,)):
            ext[t] = {"night": nh, "pre": ph, "reg": rh, "post": poh}
    except Exception:  # noqa: BLE001
        pass
    out: dict[str, dict] = {}
    for t, c, h, v in rows:
        p = pv.get(t)
        if not p or not p[0] or p[0] <= 0 or not c:
            continue
        pc, pvol = float(p[0]), float(p[1] or 0)
        if pc * pvol < MIN_PREV_DVOL and (v or 0) * float(c) < MIN_PREV_DVOL:
            continue
        hi = max([float(h or 0)] + [float(x) for x in (ext.get(t) or {}).values() if x])
        chg, hichg = (float(c) / pc - 1) * 100, (hi / pc - 1) * 100
        if chg >= PUMP_PCT or hichg >= PUMP_HI_PCT:
            sess = "reg"
            for s in ("night", "pre", "reg", "post"):
                x = (ext.get(t) or {}).get(s)
                if x and (float(x) / pc - 1) * 100 >= PUMP_PCT:
                    sess = s
                    break
            out[t] = {"ticker": t, "pump_pct": chg, "hi_pct": hichg, "session": sess, "prev_close": pc, "volume": float(v or 0)}
    try:  # 토스 급상승 순위(일봉이 아직 없는 종목 보완)
        for t, price, chg in conn.execute("SELECT ticker, price, change_pct FROM toss_rank WHERE date=? AND kind='up'", (day,)):
            if t and t not in out and chg is not None and float(chg) >= PUMP_PCT:
                out[t] = {"ticker": t, "pump_pct": float(chg), "hi_pct": float(chg), "session": "toss", "prev_close": (float(price) / (1 + float(chg) / 100)) if price else None, "volume": None}
    except Exception:  # noqa: BLE001
        pass
    if tradable_only:
        try:
            import tradable
            act = tradable.active(conn)
            if act:
                out = {t: r for t, r in out.items() if t in act}
        except Exception:  # noqa: BLE001
            pass
    return sorted(out.values(), key=lambda r: -r["pump_pct"])


def our_signals(conn) -> pd.DataFrame:
    """🏆 모든 출처의 '오름' 예측(source, date, ticker)."""
    try:
        import scoreboard as sb
        df = sb.collect(conn)
        return df[df["direction"] > 0][["source", "출처", "date", "ticker"]] if not df.empty else df
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["source", "출처", "date", "ticker"])


def held_sets(conn, day: str) -> dict[str, set]:
    """그날 이전에 들고 있던 종목: 저금통 · 가상매매(열린/그날 전 매수) · 워치."""
    out = {"저금통": set(), "가상매매": set(), "워치": set()}
    try:
        out["저금통"] = {r[0] for r in conn.execute("SELECT ticker FROM piggy_list")}
    except Exception:  # noqa: BLE001
        pass
    try:
        out["가상매매"] = {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM pt_trades WHERE day <= ? AND (exit_day IS NULL OR exit_day >= ?)", (day, day))}
    except Exception:  # noqa: BLE001
        pass
    try:
        out["워치"] = {r[0] for r in conn.execute("SELECT ticker FROM watchlist")}
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------- 특징(그날까지 정보만)
def features(conn, ticker: str, asof: str, download=None) -> dict:
    """as_of 날짜까지의 표만 써서 한 종목의 특징을 모은다. 일봉이 모자라면 download(ticker) 로 받아 보관(테스트에선 가짜)."""
    f: dict = {k: None for k in FEAT_KEYS}
    d = _daily(conn, ticker, asof)
    if len(d) < 60 and download is not None:
        try:
            full = download(ticker)
            if full is not None and len(full):
                db.upsert_daily_prices(conn, ticker, full)
                conn.commit()
                d = _daily(conn, ticker, asof)
        except Exception:  # noqa: BLE001
            pass
    if len(d) >= 2:
        c, v = d["Close"].astype(float), d["Volume"].fillna(0).astype(float)
        px = float(c.iloc[-1])
        f["px"] = px
        f["bucket"] = "$1 미만" if px < 1 else ("$1~5" if px < 5 else "$5 이상")
        f["chg1"] = (px / float(c.iloc[-2]) - 1) * 100 if c.iloc[-2] else None
        if len(d) >= 21:
            f["dd20"] = (px / float(d["High"].astype(float).tail(21).iloc[:-1].max()) - 1) * 100
            a20 = float(v.tail(21).iloc[:-1].mean())
            f["vol_x"] = float(v.iloc[-1]) / a20 if a20 > 0 else None
            f["dvol20"] = float((c * v).tail(20).mean())
        if len(d) >= 15:
            import ta
            r = ta.rsi(c, 14)
            f["rsi"] = None if pd.isna(r.iloc[-1]) else float(r.iloc[-1])
        if len(d) >= 25:
            try:
                import chartview as cv
                a = cv.analyze(d)
                if a:
                    rr, b, md = a.get("retrace"), a.get("base"), a.get("ma_d")
                    f["zone"] = rr["zone"] if rr else "기준봉 없음"
                    f["stage"] = rr["stage"] if rr else None
                    f["base_days"] = b["days_since"] if b else None
                    f["above50"] = bool(md["above"][50]) if md and md.get("ma50") else None
                    f["gc_days"] = md["gc_days"] if md else None
                    f["sar"] = a["sar_d"]["pos"] if a.get("sar_d") else None
                    f["bb_sq"] = bool(a["bb"]["squeeze"]) if a.get("bb") else None
            except Exception:  # noqa: BLE001
                pass
    try:
        r = conn.execute("SELECT float_shares, market_cap FROM fundamentals WHERE ticker=?", (ticker,)).fetchone()
        if r:
            f["float"], f["mcap"] = r[0], r[1]
    except Exception:  # noqa: BLE001
        pass
    r = None
    try:
        r = conn.execute("SELECT status FROM dilution_hist WHERE ticker=? AND date <= ? ORDER BY date DESC LIMIT 1", (ticker, asof)).fetchone()
    except Exception:  # noqa: BLE001  (이력 표가 아직 없을 때)
        r = None
    if not r:
        try:
            r = conn.execute("SELECT status FROM dilution WHERE ticker=?", (ticker,)).fetchone()
        except Exception:  # noqa: BLE001
            r = None
    f["dil"] = r[0] if r else None
    try:
        r = conn.execute("SELECT si_pct, dtc FROM short_interest WHERE ticker=? AND date <= ? ORDER BY date DESC LIMIT 1", (ticker, asof)).fetchone()
        if r:
            f["si_pct"], f["dtc"] = r[0], r[1]
    except Exception:  # noqa: BLE001
        pass
    try:
        r = conn.execute("SELECT short_pct FROM cx_short_volume WHERE ticker=? AND date <= ? ORDER BY date DESC LIMIT 1", (ticker, asof)).fetchone()
        f["sv_pct"] = r[0] if r else None
    except Exception:  # noqa: BLE001
        pass
    try:
        f["regsho"] = bool(conn.execute("SELECT 1 FROM regsho_list WHERE symbol=? AND date=(SELECT MAX(date) FROM regsho_list WHERE date <= ?)", (ticker, asof)).fetchone())
    except Exception:  # noqa: BLE001
        pass
    since = (date.fromisoformat(asof) - timedelta(days=7)).isoformat()
    try:
        rows = conn.execute("SELECT sentiment FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) BETWEEN ? AND ?", (ticker, since, asof)).fetchall()
        f["sec7"], f["sec_good7"] = len(rows), sum(1 for r in rows if "호재" in (r[0] or ""))   # '약한 호재'·'강한 호재' 도 호재로
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = conn.execute("SELECT sentiment FROM news WHERE ticker=? AND substr(published,1,10) BETWEEN ? AND ?", (ticker, since, asof)).fetchall()
        f["news7"], f["news_good7"] = len(rows), sum(1 for r in rows if "호재" in (r[0] or ""))
    except Exception:  # noqa: BLE001
        pass
    rg = regime_on(conn, asof)
    if rg:
        f["regime"], f["regime_pts"] = rg["light"], rg["points"]
    return f


def catalyst(conn, ticker: str, day: str) -> str:
    """펌핑 전후(전날~당일) 공시·뉴스 제목 한 줄 — 촉매 추정용(3단계 Claude 분류 재료)."""
    since = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    bits = []
    try:
        for form, tags, sent in conn.execute("SELECT form, tags, sentiment FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) BETWEEN ? AND ? ORDER BY updated DESC LIMIT 3",
                                             (ticker, since, day)):
            try:
                tg = ", ".join(json.loads(tags or "[]")[:3])
            except Exception:  # noqa: BLE001
                tg = ""
            bits.append(f"공시 {form} {sent or ''} {tg}".strip())
    except Exception:  # noqa: BLE001
        pass
    try:
        for title, sent in conn.execute("SELECT title, sentiment FROM news WHERE ticker=? AND substr(published,1,10) BETWEEN ? AND ? ORDER BY published DESC LIMIT 2", (ticker, since, day)):
            bits.append(f"뉴스 {sent or ''} {(title or '')[:60]}".strip())
    except Exception:  # noqa: BLE001
        pass
    return " · ".join(bits) if bits else "공시·뉴스 없음(수급·테마·세력 추정)"


# ---------------------------------------------------------------- 실패 원인 태그(신호 뒤를 봄 — 부검)
def failure_tags(conn, ticker: str, day: str, horizon: int, feats: dict, outcome: dict) -> list[str]:
    tags = []
    end = (date.fromisoformat(day) + timedelta(days=int(horizon * 1.6) + 3)).isoformat()
    if feats.get("regime") in ("red", "yellow"):
        tags.append("regime")
    try:
        n = conn.execute("SELECT COUNT(*) FROM sec_feed WHERE ticker=? AND COALESCE(filed, substr(updated,1,10)) BETWEEN ? AND ? AND (form LIKE '424B%' OR form LIKE 'S-1%' OR form LIKE 'S-3%' OR form LIKE 'F-1%' OR form LIKE 'F-3%' OR form='EFFECT')",
                         (ticker, day, end)).fetchone()[0]
        if n or (feats.get("dil") in ("ATM", "ELOC", "CB")):
            tags.append("dilution")
    except Exception:  # noqa: BLE001
        pass
    try:
        r = conn.execute("SELECT MAX(short_pct) FROM cx_short_volume WHERE ticker=? AND date BETWEEN ? AND ?", (ticker, day, end)).fetchone()
        if r and r[0] is not None and float(r[0]) >= 60:
            tags.append("short")
    except Exception:  # noqa: BLE001
        pass
    if feats.get("dvol20") is not None and feats["dvol20"] < 500_000:
        tags.append("thin")
    if not (feats.get("sec_good7") or feats.get("news_good7")):
        tags.append("nocat")
    try:
        r = conn.execute("SELECT night_high, pre_high, reg_high, post_high FROM ext_hilo WHERE ticker=? AND date=?", (ticker, day)).fetchone()
        if r and outcome.get("entry"):
            e = float(outcome["entry"])
            ext_hi = max([float(x) for x in (r[0], r[1], r[3]) if x] or [0])
            if ext_hi >= e * 1.15 and (r[2] or 0) < ext_hi * 0.85:
                tags.append("ext")
    except Exception:  # noqa: BLE001
        pass
    try:
        if conn.execute("SELECT 1 FROM chart_signals WHERE ticker=? AND kind IN ('life_break','waist_break') AND date BETWEEN ? AND ?", (ticker, day, end)).fetchone():
            tags.append("life")
    except Exception:  # noqa: BLE001
        pass
    try:
        r = conn.execute("SELECT MIN(points), MAX(points) FROM regime_hist WHERE date BETWEEN ? AND ?", (day, end)).fetchone()
        if r and r[1] is not None and r[1] >= 4:
            tags.append("market")
    except Exception:  # noqa: BLE001
        pass
    return tags or ["other"]


# ---------------------------------------------------------------- 실행
def run(conn, day: str | None = None, out=print, download=None, fail_days: int = 3) -> dict:
    """하루치 부검: 펌핑(어제) + 최근 fail_days 일 안 '실패'로 바뀐 신호."""
    ensure(conn)
    r = conn.execute("SELECT MAX(date) FROM daily_prices").fetchone()
    day = day or (r[0] if r and r[0] else date.today().isoformat())
    prev = prev_trading_day(conn, day) or day
    sig = our_signals(conn)
    held = held_sets(conn, day)
    pumps = find_pumps(conn, day)
    since = (date.fromisoformat(day) - timedelta(days=SIGNAL_LOOKBACK)).isoformat()
    n_new = n_caught = 0
    now = db.utcnow_iso()
    for p in pumps:
        t = p["ticker"]
        mine = sig[(sig["ticker"] == t) & (sig["date"] >= since) & (sig["date"] <= day)] if not sig.empty else sig
        by = sorted(set(mine["출처"])) if not mine.empty else []
        hs = [k for k, s in held.items() if t in s]
        caught = bool(by or hs)
        f = features(conn, t, prev, download)
        cur = conn.execute("INSERT OR IGNORE INTO pump_autopsy (date, ticker, pump_pct, hi_pct, session, prev_close, volume, caught, caught_by, held, features, catalyst, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",   # 열 이름 명시(뒤에 AI 열이 붙어도 깨지지 않게)
                           (day, t, p["pump_pct"], p["hi_pct"], p["session"], p["prev_close"], p["volume"], int(caught), json.dumps(by, ensure_ascii=False),
                            json.dumps(hs, ensure_ascii=False), json.dumps(f, ensure_ascii=False, default=str), catalyst(conn, t, day), now))
        n_new += cur.rowcount
        n_caught += int(caught and cur.rowcount)
    # 실패 신호
    n_fail = 0
    try:
        import scoreboard as sb
        rows = conn.execute("SELECT source, date, ticker, ref, entry, max_up, max_down, status FROM pred_outcomes WHERE status='실패' AND updated_at >= ? ORDER BY date",
                            ((datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=fail_days)).isoformat(),)).fetchall()   # utcnow() 경고 회피(같은 값)
        for s, d0, t, ref, entry, mu, md, st in rows:
            if conn.execute("SELECT 1 FROM signal_autopsy WHERE source=? AND date=? AND ticker=?", (s, d0, t)).fetchone():
                continue
            hz = sb.SOURCES.get(s, ("", 1, None, 10))[3] or 10
            f = features(conn, t, d0, download)
            tags = failure_tags(conn, t, d0, hz, f, {"entry": entry})
            conn.execute("INSERT OR REPLACE INTO signal_autopsy (source, date, ticker, status, entry, max_up, max_down, features, tags, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (s, d0, t, st, entry, mu, md, json.dumps(f, ensure_ascii=False, default=str), json.dumps(tags, ensure_ascii=False), now))
            n_fail += 1
    except Exception as e:  # noqa: BLE001
        out(f"부검: 실패 신호 처리 중 오류({e})")
    conn.commit()
    out(f"🔍 부검 {day}: 펌핑 {len(pumps)}종목(새로 {n_new} · 그중 우리 신호/보유 {n_caught}) · 실패 신호 부검 {n_fail}건")
    for p in pumps[:15]:
        row = conn.execute("SELECT caught, caught_by, held, catalyst FROM pump_autopsy WHERE date=? AND ticker=?", (day, p["ticker"])).fetchone()
        if row:
            out(f"  {p['ticker']} {p['pump_pct']:+.0f}%(고가 {p['hi_pct']:+.0f}%, {p['session']}) · {'✅ ' + (row[1] or '') + (row[2] or '') if row[0] else '❌ 놓침'} · {row[3][:80]}")
    return {"day": day, "pumps": len(pumps), "new": n_new, "caught": n_caught, "fails": n_fail}


def morning(out=print) -> dict:
    import market
    with closing(db.connect()) as conn:
        return run(conn, out=out, download=lambda t: market.download_daily([t], period="6mo").get(t))


# ---------------------------------------------------------------- 집계(화면)
def _load(conn, table: str, days: int) -> pd.DataFrame:
    ensure(conn)
    df = pd.read_sql_query(f"SELECT * FROM {table} WHERE date >= date('now', ?) ORDER BY date DESC", conn, params=(f"-{days} day",))
    if df.empty:
        return df
    feats = df["features"].map(lambda s: json.loads(s) if s else {})
    for k in FEAT_KEYS:
        df[k] = feats.map(lambda x, k=k: x.get(k))
    return df


def stats(conn, days: int = 30) -> dict:
    pumps, fails = _load(conn, "pump_autopsy", days), _load(conn, "signal_autopsy", days)
    out = {"pumps": pumps, "fails": fails, "n_pump": len(pumps), "n_caught": int(pumps["caught"].sum()) if not pumps.empty else 0}
    out["miss_rate"] = None if pumps.empty else (1 - out["n_caught"] / len(pumps)) * 100
    if not pumps.empty:
        pumps["결과"] = np.where(pumps["caught"] == 1, "✅ 잡음", "❌ 놓침")
        out["by_session"] = pumps.groupby(["session", "결과"]).size().unstack(fill_value=0)
        out["by_bucket"] = pumps.groupby(["bucket", "결과"]).size().unstack(fill_value=0)
        out["by_dil"] = pumps.fillna({"dil": "미확인"}).groupby(["dil", "결과"]).size().unstack(fill_value=0)
    if not fails.empty:
        ex = fails.assign(tag=fails["tags"].map(lambda s: json.loads(s) if s else [])).explode("tag")
        ex["태그"] = ex["tag"].map(lambda k: TAGS.get(k, k))
        out["tag_counts"] = ex.groupby("태그").size().sort_values(ascending=False)
        out["tag_by_source"] = ex.groupby(["source", "태그"]).size().unstack(fill_value=0)
    # 특징 비교(중앙값): 잡은 펌핑 · 놓친 펌핑 · 실패 신호
    comp = []
    num = ["dvol20", "float", "mcap", "dd20", "rsi", "vol_x", "si_pct", "sv_pct", "sec7", "news7"]
    for name, df in (("✅ 잡은 펌핑", pumps[pumps["caught"] == 1] if not pumps.empty else pumps), ("❌ 놓친 펌핑", pumps[pumps["caught"] == 0] if not pumps.empty else pumps), ("💥 실패 신호", fails)):
        if df is None or df.empty:
            continue
        row = {"구분": name, "건수": len(df)}
        for k in num:
            s = pd.to_numeric(df[k], errors="coerce").dropna()
            row[k] = None if s.empty else float(s.median())
        row["$1 미만 비율(%)"] = float((df["bucket"] == "$1 미만").mean() * 100) if "bucket" in df else None
        row["희석(ATM·ELOC·CB) 비율(%)"] = float(df["dil"].isin(["ATM", "ELOC", "CB"]).mean() * 100) if "dil" in df else None
        comp.append(row)
    out["compare"] = pd.DataFrame(comp)
    return out


if __name__ == "__main__":
    morning()
