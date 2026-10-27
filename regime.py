"""🚦 소형주 장세 신호등 — ANO 거시 관점(docs/chart_masters.md 2-6): "돈이 안 돌면 소형주는 종목이 안 나온다".
재료: 야후(^VIX · ^VIX9D · ^VIX3M · SPY · ^IXIC 일봉) + FRED(키 없이 CSV: 하이일드 스프레드 BAMLH0A0HYM2 · 2년물 DGS2 · 10년물 DGS10).
점수(위험 점): VIX 18.5↑ +1 / 20↑ +2 / 30↑ +3 · VIX 하루 +15% +1 · 단기 VIX(9일) ≥ 3개월 VIX(백워데이션) +1 · 하이일드 스프레드 5일 +0.3pp 또는 20일 +0.5pp +1(5%↑ +1)
       · 2년물 5일 −0.15pp 이면서 SPY 5일 하락(주식 팔아 채권) +1 · 2년·10년 5일 동시 +0.15pp +1 · SPY 200일선 아래 +2 · 나스닥 20일선 아래 & 기울기↓ +1
신호등: 0~1 🟢 소형주 장세 좋음 · 2~3 🟡 보수적(소액·쌀먹·타점만) · 4↑ 🔴 쉬어라. 스캐너가 30분마다 받아 meta 'regime' 에 저장, 화면은 읽기만.
"""
from __future__ import annotations

import io
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pandas as pd

import db

TTL_MIN = 30
YAHOO = ["^VIX", "^VIX9D", "^VIX3M", "SPY", "^IXIC", "HYG", "IEF"]   # HYG/IEF = 하이일드 스프레드 대체(FRED 가 막힐 때)
FRED = {"hy": "BAMLH0A0HYM2", "dgs2": "DGS2", "dgs10": "DGS10"}
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
DBN = {"dgs2": "FED/H15/RIFLGFCY02_N.B", "dgs10": "FED/H15/RIFLGFCY10_N.B"}   # DBnomics(FRED 복사본·연준 H.15) — 한국에서 FRED 가 시간 초과일 때
DBN_URL = "https://api.db.nomics.world/v22/series/{id}?observations=1"
VIX_WATCH, VIX_SQUEEZE, VIX_CRASH = 18.5, 20.0, 30.0
LIGHTS = {"green": "🟢 소형주 장세 좋음(돈이 돎)", "yellow": "🟡 보수적으로(소액 · 쌀먹 · 타점만)", "red": "🔴 쉬어라(돈이 안 돎 · 숏이 활개)"}
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_fred(series_id: str, http_get=None) -> pd.Series:
    """FRED CSV(observation_date,value · '.' = 없음) → 날짜 인덱스 숫자열."""
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": BROWSER_UA}, timeout=15))
    r = get(FRED_URL.format(id=series_id))
    text = r.text if hasattr(r, "text") else str(r)
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().lower() for c in df.columns]
    dcol = "observation_date" if "observation_date" in df.columns else df.columns[0]
    vcol = [c for c in df.columns if c != dcol][0]
    s = pd.to_numeric(df[vcol].replace(".", None), errors="coerce")
    s.index = pd.to_datetime(df[dcol])
    return s.dropna()


def fetch_dbnomics(series_id: str, http_get=None) -> pd.Series:
    """DBnomics JSON(series.docs[0].period/value) → 날짜 인덱스 숫자열."""
    import requests
    get = http_get or (lambda u: requests.get(u, headers={"User-Agent": BROWSER_UA}, timeout=15))
    r = get(DBN_URL.format(id=series_id))
    j = r.json() if hasattr(r, "json") else json.loads(r.text if hasattr(r, "text") else str(r))
    doc = j["series"]["docs"][0]
    s = pd.to_numeric(pd.Series(doc["value"]), errors="coerce")
    s.index = pd.to_datetime(doc["period"])
    return s.dropna()


def fetch(download=None, http_get=None) -> dict:
    """재료 받기. 반환 {"vix","vix9d","vix3m","spy","ixic","hyg_ief": 종가 열, "hy","dgs2","dgs10": FRED(없으면 DBnomics) 열} — 못 받은 건 None."""
    import market
    dl = download or (lambda: market.download_daily(YAHOO, period="1y"))
    out: dict = {}
    try:
        frames = dl() or {}
    except Exception:  # noqa: BLE001
        frames = {}

    def close_of(sym):
        df = frames.get(sym)
        return None if df is None or "Close" not in df or df["Close"].dropna().empty else df["Close"].dropna().astype(float)
    for key, sym in (("vix", "^VIX"), ("vix9d", "^VIX9D"), ("vix3m", "^VIX3M"), ("spy", "SPY"), ("ixic", "^IXIC")):
        out[key] = close_of(sym)
    hyg, ief = close_of("HYG"), close_of("IEF")
    out["hyg_ief"] = None if hyg is None or ief is None else (hyg / ief).dropna()
    for key, sid in FRED.items():
        try:
            out[key] = fetch_fred(sid, http_get)
        except Exception:  # noqa: BLE001
            out[key] = None
        if out[key] is None and key in DBN:
            try:
                out[key] = fetch_dbnomics(DBN[key], http_get)
            except Exception:  # noqa: BLE001
                out[key] = None
    return out


def _chg(s: pd.Series | None, n: int) -> float | None:
    if s is None or len(s) <= n:
        return None
    return float(s.iloc[-1] - s.iloc[-1 - n])


def evaluate(x: dict) -> dict:
    """재료 → 점수·신호등·이유·숫자."""
    pts, reasons, ok = 0, [], []
    m: dict = {}
    vix = x.get("vix")
    if vix is not None and len(vix):
        v = float(vix.iloc[-1]); m["vix"] = v
        m["vix_chg_pct"] = None if len(vix) < 2 or vix.iloc[-2] <= 0 else (v / float(vix.iloc[-2]) - 1) * 100
        if v >= VIX_CRASH:
            pts += 3; reasons.append(f"VIX {v:.1f} ≥ 30 — 폭락권")
        elif v >= VIX_SQUEEZE:
            pts += 2; reasons.append(f"VIX {v:.1f} ≥ 20 — 스퀴즈 조건(만기 전 넘지 말아야)")
        elif v >= VIX_WATCH:
            pts += 1; reasons.append(f"VIX {v:.1f} ≥ 18.5 — 급락 전조 경계")
        else:
            ok.append(f"VIX {v:.1f} 안정")
        if m["vix_chg_pct"] is not None and m["vix_chg_pct"] >= 15:
            pts += 1; reasons.append(f"VIX 하루 {m['vix_chg_pct']:+.0f}%")
    v9, v3 = x.get("vix9d"), x.get("vix3m")
    if v9 is not None and v3 is not None and len(v9) and len(v3) and float(v3.iloc[-1]) > 0:
        r = float(v9.iloc[-1]) / float(v3.iloc[-1]); m["term_ratio"] = r
        if r >= 1.0:
            pts += 1; reasons.append(f"9일 VIX ≥ 3개월 VIX({r:.2f}) — 백워데이션(당장 공포)")
        else:
            ok.append(f"VIX 기간 구조 콘탱고({r:.2f})")
    hy = x.get("hy")
    if hy is not None and len(hy) >= 21:
        m["hy"], m["hy_chg5"], m["hy_chg20"] = float(hy.iloc[-1]), _chg(hy, 5), _chg(hy, 20)
        if (m["hy_chg5"] or 0) >= 0.30 or (m["hy_chg20"] or 0) >= 0.50:
            pts += 1; reasons.append(f"하이일드 스프레드 급증(5일 {m['hy_chg5']:+.2f}pp · 20일 {m['hy_chg20']:+.2f}pp) — 단기 유동성 경색")
        else:
            ok.append(f"하이일드 스프레드 {m['hy']:.2f}% 안정")
        if m["hy"] >= 5.0:
            pts += 1; reasons.append(f"하이일드 스프레드 {m['hy']:.2f}% ≥ 5%")
    elif x.get("hyg_ief") is not None and len(x["hyg_ief"]) >= 21:   # FRED 못 받으면 HYG/IEF 비율(하이일드 ETF ÷ 국채 ETF)로 대체 — 비율↓ = 스프레드 확대
        hi = x["hyg_ief"]
        m["hy_proxy_chg5"], m["hy_proxy_chg20"] = (float(hi.iloc[-1]) / float(hi.iloc[-6]) - 1) * 100, (float(hi.iloc[-1]) / float(hi.iloc[-21]) - 1) * 100
        if m["hy_proxy_chg5"] <= -1.0 or m["hy_proxy_chg20"] <= -2.0:
            pts += 1; reasons.append(f"HYG/IEF 비율 5일 {m['hy_proxy_chg5']:+.1f}% · 20일 {m['hy_proxy_chg20']:+.1f}% — 하이일드 스프레드 확대(대체 지표)")
        else:
            ok.append(f"HYG/IEF 비율 안정(5일 {m['hy_proxy_chg5']:+.1f}%, 스프레드 대체 지표)")
    d2, d10, spy = x.get("dgs2"), x.get("dgs10"), x.get("spy")
    spy5 = None
    if spy is not None and len(spy) > 5:
        spy5 = (float(spy.iloc[-1]) / float(spy.iloc[-6]) - 1) * 100; m["spy_5d_pct"] = spy5
    if d2 is not None and len(d2) > 5:
        m["dgs2"], m["dgs2_chg5"] = float(d2.iloc[-1]), _chg(d2, 5)
        if m["dgs2_chg5"] is not None and m["dgs2_chg5"] <= -0.15 and spy5 is not None and spy5 < 0:
            pts += 1; reasons.append(f"2년물 5일 {m['dgs2_chg5']:+.2f}pp ↓ + SPY {spy5:+.1f}% — 주식 팔아 채권 매수(조정)")
    if d10 is not None and len(d10) > 5:
        m["dgs10"], m["dgs10_chg5"] = float(d10.iloc[-1]), _chg(d10, 5)
        if m.get("dgs2_chg5") is not None and m["dgs2_chg5"] >= 0.15 and m["dgs10_chg5"] >= 0.15:
            pts += 1; reasons.append("2년·10년 금리 5일 동시 상승 — 시장 불안정")
    if spy is not None and len(spy) >= 200:
        ma = float(spy.tail(200).mean()); m["spy"], m["spy_ma200"], m["spy_vs200_pct"] = float(spy.iloc[-1]), ma, (float(spy.iloc[-1]) / ma - 1) * 100
        if m["spy"] < ma:
            pts += 2; reasons.append(f"SPY 200일선 아래({m['spy_vs200_pct']:+.1f}%) — 강세장 아님")
        else:
            ok.append(f"SPY 200일선 위(+{m['spy_vs200_pct']:.1f}%)")
    ix = x.get("ixic")
    if ix is not None and len(ix) >= 26:
        ma20 = ix.rolling(20).mean()
        m["ixic"], m["ixic_ma20"], m["ixic_slope"] = float(ix.iloc[-1]), float(ma20.iloc[-1]), (float(ma20.iloc[-1]) / float(ma20.iloc[-6]) - 1) * 100
        if m["ixic"] < m["ixic_ma20"] and m["ixic_slope"] < 0:
            pts += 1; reasons.append(f"나스닥 20일선 아래 · 기울기 {m['ixic_slope']:+.1f}% — 단기 추세 꺾임")
        else:
            ok.append("나스닥 20일선 " + ("위" if m["ixic"] >= m["ixic_ma20"] else "아래(기울기는 아직 위)"))
    light = "green" if pts <= 1 else ("yellow" if pts <= 3 else "red")
    date = None
    for k in ("vix", "spy", "ixic"):
        s = x.get(k)
        if s is not None and len(s):
            date = s.index[-1].strftime("%Y-%m-%d")
            break
    return {"points": pts, "light": light, "label": LIGHTS[light], "reasons": reasons, "ok": ok, "metrics": m, "date": date,
            "n_inputs": sum(1 for k in ("vix", "vix9d", "vix3m", "spy", "ixic", "hy", "dgs2", "dgs10", "hyg_ief") if x.get(k) is not None)}


def get() -> dict:
    mm = db.get_meta("regime")
    try:
        return json.loads(mm["value"]) if mm and mm.get("value") else {}
    except (TypeError, ValueError):
        return {}


def refresh(force: bool = False, download=None, http_get=None) -> dict:
    """TTL(30분)이 지났으면 다시 받아 평가·저장. 실패하면 예전 값에 오류만 기록."""
    cur = get()
    now = _now()
    at = cur.get("_at")
    if not force and at and now - datetime.fromisoformat(at) < timedelta(minutes=TTL_MIN):
        return cur
    try:
        res = evaluate(fetch(download, http_get))
        if res["n_inputs"] == 0:
            raise RuntimeError("재료 없음")
        res.update({"_at": now.isoformat(), "_err": None})
    except Exception as e:  # noqa: BLE001
        res = {**{k: v for k, v in cur.items() if not k.startswith("_")}, "_at": now.isoformat(), "_err": f"{type(e).__name__}: {str(e)[:120]}"}
    db.set_meta("regime", json.dumps(res, ensure_ascii=False))
    if res.get("light"):
        try:  # 🔍 부검용 날짜별 기록(그날 장세를 나중에 알 수 있게)
            import autopsy
            with closing(db.connect()) as conn:
                autopsy.record_regime(conn, res.get("date") or now.strftime("%Y-%m-%d"), res["light"], res.get("points", 0))
                conn.commit()
        except Exception:  # noqa: BLE001
            pass
    return res


if __name__ == "__main__":
    r = refresh(force=True)
    print(r.get("label"), r.get("points"), r.get("reasons"), r.get("_err"))
