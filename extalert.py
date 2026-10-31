"""🌙 시간외 급등 알림 — 관심 종목이 프리·애프터·데이마켓에서 직전 정규장 종가 대비 +N% 이상 찍으면 텔레그램.

🕰 타임머신(2,623종목·최근 60일): '다음날 +10%' 급등의 약 40%는 프리·애프터에서만 일어났다(정규장만 7.5% → 시간외 포함 13.0%).
장마감에 사서 튈 때 파는 방식이라 그 순간을 놓치지 않게 한다.
대상: 워치리스트·저금통 · 최근 2일 🎯 장마감 체크리스트 고정 목록 · 최근 5일 ✅ 3대 조건 신호 · 🧪 가상매매 보유.
같은 종목·같은 세션은 하루 한 번. 스캐너가 매 사이클 check() 를 부른다(관리 모드에서 끄기·기준 % 바꾸기).
⚠️ 시간외는 거래가 얇아 그 가격에 다 팔리지 않을 수 있어요.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

ET = "America/New_York"
SESSION_NAME = {"pre": "프리마켓", "post": "애프터마켓", "night": "데이마켓·야간"}


def interest(conn, today: date | None = None) -> dict[str, str]:
    """알림 대상 {티커: 이유}."""
    today = today or date.today()
    out: dict[str, str] = {}

    def add(ts, why):
        for t in ts:
            if t and t not in out:
                out[t] = why
    try:
        import watch
        add(watch.scanner_priority(), "⭐ 워치리스트·저금통")
    except Exception:  # noqa: BLE001
        pass
    import setup3
    for sql, why, d in (("SELECT DISTINCT ticker FROM close_watchlist WHERE kind='frozen' AND date >= ?", "🎯 장마감 체크리스트", 3),
                        ("SELECT DISTINCT ticker FROM s3_tier_signals WHERE date >= ?" + setup3.not_held(conn), "⭐ 깊은 과매도+희석 없음(검증 순위)", 7),   # 보류(U1·U2) 제외
                        ("SELECT DISTINCT ticker FROM setup3_signals WHERE date >= ?", "✅ 3대 조건 신호", 7),
                        ("SELECT DISTINCT ticker FROM pt_trades WHERE status='open' AND day >= ?", "🧪 가상매매 보유", 30)):
        try:
            add([r[0] for r in conn.execute(sql, ((today - timedelta(days=d)).isoformat(),))], why)
        except Exception:  # noqa: BLE001
            pass
    return out


def _session(ts: pd.Timestamp) -> str:
    et = ts.tz_convert(ET) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(ET)
    m = et.hour * 60 + et.minute
    if m >= 20 * 60 or m < 4 * 60:
        return "night"
    if m < 9 * 60 + 30:
        return "pre"
    if m < 16 * 60:
        return "reg"
    return "post"


def prev_close(conn, t: str, before: str) -> float | None:
    r = conn.execute("SELECT close FROM daily_prices WHERE ticker=? AND date < ? ORDER BY date DESC LIMIT 1", (t, before)).fetchone()
    return float(r[0]) if r and r[0] else None


def check(conn, frames: dict, pct: float = 10.0, send=None, now: datetime | None = None, download=None) -> list[str]:
    """지금 세션이 시간외이고 관심 종목의 이번 세션 고점이 직전 정규장 종가 대비 +pct% 이상이면 알림. 보낸 종목 목록."""
    now = now or datetime.now(timezone.utc)
    sess = _session(pd.Timestamp(now))
    if sess == "reg":
        return []
    tgt = interest(conn, today=pd.Timestamp(now).tz_convert(ET).date())   # 관심 종목은 알림 시각(now) 기준으로 — 벽시계 기준이면 테스트의 고정 날짜가 며칠 지나 비어 버림(2026-10-30 발견)
    if not tgt:
        return []
    et_now = pd.Timestamp(now).tz_convert(ET)
    day = et_now.date()
    if sess == "night" and et_now.hour >= 20:   # 20시 이후 데이마켓은 다음 거래일 몫
        day = day + timedelta(days=1)
    while day.weekday() >= 5:
        day = day + timedelta(days=1)
    missing = [t for t in tgt if t not in (frames or {})]
    frames = dict(frames or {})
    if missing:
        try:
            if download is None:
                import market
                download = market.download_intraday
            frames.update(download(missing[:80]) or {})
        except Exception:  # noqa: BLE001
            pass
    import db
    m = db.get_meta("extalert_sent")
    try:
        sent = json.loads(m["value"]) if m and m.get("value") else {}
    except (TypeError, ValueError):
        sent = {}
    sent = {k: v for k, v in sent.items() if v >= (day - timedelta(days=3)).isoformat()}
    if send is None:
        import notify
        send = notify.send_telegram
    done = []
    since = pd.Timestamp(now) - pd.Timedelta(hours=10)
    for t, why in tgt.items():
        f = frames.get(t)
        if f is None or f.empty or "High" not in f:
            continue
        idx = pd.DatetimeIndex(f.index)
        idx = idx.tz_localize("UTC") if idx.tz is None else idx
        g = f.set_axis(idx)[idx >= since]
        g = g[[_session(x) == sess for x in g.index]]
        if g.empty:
            continue
        pc = prev_close(conn, t, (day + timedelta(days=1)).isoformat() if sess == "post" else day.isoformat())
        if not pc:
            continue
        hi = float(g["High"].max())
        last = float(g["Close"].dropna().iloc[-1]) if "Close" in g and g["Close"].notna().any() else hi
        up = (hi / pc - 1) * 100
        key = f"{t}|{day.isoformat()}|{sess}"
        if up < pct or key in sent or hi > pc * 20:
            continue
        msg = (f"🌙 시간외 급등 {t} +{up:.1f}% ({SESSION_NAME[sess]})\n"
               f"직전 정규장 종가 ${pc:.4g} → 이번 세션 고점 ${hi:.4g} · 지금 ${last:.4g}({(last / pc - 1) * 100:+.1f}%)\n"
               f"대상 이유: {why}\n⚠️ 시간외는 거래가 얇아 그 가격에 다 팔리지 않을 수 있어요.")
        if send(msg):
            sent[key] = day.isoformat()
            done.append(t)
    db.set_meta("extalert_sent", json.dumps(sent))
    return done
