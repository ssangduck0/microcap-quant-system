"""스승님 꿀팁 — 더 오를까 더 내릴까: 분산·털기·다크풀 덤핑.

분산(차익실현): 거래량이 전일 대비 급증 + 하락 마감 → 좋지 않은 신호(PR 홍보 후 ATM 돌리는 종목에서 자주).
털기(저점 매집): 거래량이 전일 대비 급증 + 상승 마감 → 고점에서 되돌림이 나오는 패턴. 다음날도 상승 마감해야 확인.
다크풀: 대차(공매도 가용잔고)가 넉넉한데 장외 비중이 월등히 높고 주가가 빠지면 → 공매도가 아니라 '세력'의 장외 덤핑 또는 매집.
  이때는 악재·펀더멘탈 파괴·다른 리스크를 철저히 확인해야 한다(덤핑에 당하거나 털기에 당할 수 있음).
※ 양봉/음봉은 스승님 예시대로 '전일 대비 상승/하락 마감'(국내 앱의 빨강/파랑)으로 판정하고, 시가 대비 결과도 함께 보여 준다.
"""
from __future__ import annotations

from contextlib import closing

import numpy as np
import pandas as pd

import db

TIP_TITLE = "스승님 꿀팁 — 더 오를까 더 내릴까(분산·털기·다크풀)"
TIP_TEXT = """더 오를까 더 내릴까 판단에 도움되는 꿀팁
첫번째는 '분산'입니다. 다른 말로 매도 차익실현이라고 보시면 됩니다.
전일대비 거래량이 급증하고 음봉 마감이면 좋은 신호가 아닙니다.
(PR홍보 던지고 ATM돌리는 악랄한 종목에서 많이 보입니다)
두번째는 '털기'입니다. 다른말로는 저점매집 이라고 보시면 됩니다.
전일대비 거래량이 급증하고 양봉마감입니다. 이런경우 고점에서 되돌림이 나오는 패턴입니다.
다만 다음날도 양봉 마감추세는 유지가 되어야 합니다.
이건 간단히 파악을 하는 것이고, 사실 다크풀을 통한 움직임도 보아야 합니다.
공매도 가용잔고가 많았는데 다크풀이 월등히 높다는건 주가하락의 주체가 공매도가 아닌 '세력'의 장외 덤핑이거나 매집입니다.
이경우 악재가 발생을 했는지, 펀더멘탈의 파괴가 있었는지, 다른 리스크가 있는지를 철저히 파악해야 합니다.
(이경우는 시장이 모르게 덤핑으로 물량 떠넘기는 신호 입니다)
아니면 덤핑에 당하는 수가 있고 아니면 털기매집에 당하는 수가 있습니다.
(예시: 분산 06.03 253원 -8.05% 거래량 13,052,497 ← 전일 4,429,653 / 털기 06.04 2,461원 +13.38% 거래량 53,207,826 ← 전일 7,835,865, 시가 3,424 고가 3,943 저가 2,415)"""
DEFAULTS = {"spike": 2.5, "dark_high": 60.0, "fall_days": 5}
KINDS = {"dist": "🔻 분산(차익실현)", "shake": "🔺 털기(저점 매집)", "ok": "✅ 털기 확인(다음날도 상승)", "fail": "⚠️ 털기 실패(다음날 하락)"}
DDL = "CREATE TABLE IF NOT EXISTS flowread_events (date TEXT NOT NULL, ticker TEXT NOT NULL, kind TEXT NOT NULL, price REAL, at TEXT, PRIMARY KEY (date, ticker, kind))"


def classify(df: pd.DataFrame | None, params: dict | None = None, n: int = 15) -> pd.DataFrame:
    """최근 n거래일의 일별 판정. 열: 날짜, 종가, 등락(%), 거래량, 전일 대비 거래량(배), 시가 대비, 고점 되돌림(%), 판정."""
    p = {**DEFAULTS, **(params or {})}
    if df is None or len(df) < 3:
        return pd.DataFrame()
    d = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).tail(n + 1)
    o, h, l, c, v = (d[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    rows, prev_kind = [], None
    for i in range(1, len(d)):
        chg = (c[i] / c[i - 1] - 1) * 100 if c[i - 1] > 0 else None
        ratio = v[i] / v[i - 1] if v[i - 1] > 0 else None
        retr = (h[i] - c[i]) / (h[i] - l[i]) * 100 if h[i] > l[i] else None
        kind = ""
        if ratio is not None and chg is not None and ratio >= p["spike"]:
            kind = KINDS["dist"] if chg < 0 else KINDS["shake"] if chg > 0 else ""
        if prev_kind == KINDS["shake"] and chg is not None and not kind:  # 털기 다음날: 상승 마감 유지 여부
            kind = KINDS["ok"] if chg > 0 else KINDS["fail"]
        rows.append({"날짜": d.index[i].strftime("%Y-%m-%d"), "종가": c[i], "등락(%)": chg, "거래량": v[i], "전일 대비 거래량(배)": ratio,
                     "시가 대비": "상승" if c[i] > o[i] else "하락" if c[i] < o[i] else "보합", "고점 되돌림(%)": retr, "판정": kind})
        prev_kind = kind
    return pd.DataFrame(rows)


def verdict(tb: pd.DataFrame) -> str:
    """가장 최근 판정(최근 3거래일 안)."""
    if tb.empty:
        return ""
    for k in reversed(tb.tail(3)["판정"].tolist()):
        if k:
            return {KINDS["dist"]: "🔻 분산 — 내릴 쪽", KINDS["shake"]: "🔺 털기 — 다음날 상승 마감 확인 필요",
                    KINDS["ok"]: "🔺 털기 확인 — 오를 쪽", KINDS["fail"]: "⚠️ 털기 실패 — 주의"}[k]
    return "–"


def dumping(df: pd.DataFrame | None, dark: dict | None, short: dict | None, params: dict | None = None) -> dict:
    """대차 넉넉 + 장외 비중 높음 + 최근 하락 → 장외 덤핑·매집 의심. 판정 불가면 status=None."""
    p = {**DEFAULTS, **(params or {})}
    sh = short or {}
    chg = None
    if df is not None and len(df) > p["fall_days"]:
        c = df["Close"].dropna()
        chg = (float(c.iloc[-1]) / float(c.iloc[-1 - p["fall_days"]]) - 1) * 100
    roomy = None
    if sh and not sh.get("borrow_stale") and (sh.get("borrow_avail") is not None or sh.get("borrow_avail_capped")):
        roomy = bool(sh.get("borrow_avail_capped") or (sh.get("borrow_avail") or 0) >= 50_000) and (sh.get("borrow_avail_chg_pct") is None or sh["borrow_avail_chg_pct"] > -20)
    dk = None if not dark else dark.get("dark_pct")
    if dk is None or roomy is None or chg is None:
        status = None
    else:
        status = bool(roomy and dk >= p["dark_high"] and chg < 0)
    return {"status": status, "dark_pct": dk, "roomy": roomy, "chg": chg,
            "text": ("장외 비중 " + ("-" if dk is None else f"{dk:.0f}%") + " · 대차 " + ("정보 없음" if roomy is None else "넉넉" if roomy else "빠듯")
                     + " · 최근 " + str(p["fall_days"]) + "일 " + ("-" if chg is None else f"{chg:+.1f}%"))}


def risk_checks(ticker: str, conn, df: pd.DataFrame | None = None) -> list[dict]:
    """'악재·펀더멘탈 파괴·다른 리스크' 중 자동으로 볼 수 있는 것. 결과: True=문제 있음, False=없음, None=확인 불가."""
    import json
    out = []
    try:
        import pumpsetup
        got = pumpsetup.cached(conn, ticker)
        neg = (got[1].get("negatives") if got and "error" not in got[1] else None)
        out.append({"항목": "8-K 악재(최근 90일)", "문제": None if got is None else bool(neg),
                    "값": "세력·셋업 분석 전" if got is None else (", ".join(f"{n['date']} {n['name']}" for n in neg) or "없음(6-K 회사는 판정 어려움)")})
    except Exception:  # noqa: BLE001
        out.append({"항목": "8-K 악재(최근 90일)", "문제": None, "값": "확인 불가"})
    rep = db.get_report(ticker) or {}
    rw = (rep.get("runway") or {}).get("runway_months")
    out.append({"항목": "펀더멘탈: 런웨이 6개월 미만", "문제": None if rw is None else rw < 6, "값": "리포트 없음" if rw is None else f"{rw:.1f}개월"})
    dil = conn.execute("SELECT status FROM dilution WHERE ticker=?", (ticker,)).fetchone()
    ds = dil["status"] if dil else None
    out.append({"항목": "희석 리스크: ATM·ELOC·전환사채", "문제": None if ds in (None, "UNKNOWN") else ds in ("ATM", "ELOC", "CB"), "값": ds or "미확인"})
    b1 = None
    if df is not None and not df.empty:
        b1 = 0
        for x in reversed(df["Close"].dropna().tolist()):
            if x < 1.0:
                b1 += 1
            else:
                break
    out.append({"항목": "상장유지: $1 미만 30거래일 이상", "문제": None if b1 is None else b1 >= 30, "값": "-" if b1 is None else f"{b1}거래일"})
    try:
        r = conn.execute("SELECT data FROM ticker_intel WHERE ticker=? ORDER BY date DESC LIMIT 1", (ticker,)).fetchone()
        h = (json.loads(r["data"]).get("halt") or {}) if r else None
        out.append({"항목": "최근 하킷(하한 정지)", "문제": None if h is None else bool(h.get("halt_down")), "값": "-" if h is None else f"{h.get('halt_down', 0)}회"})
    except Exception:  # noqa: BLE001
        out.append({"항목": "최근 하킷(하한 정지)", "문제": None, "값": "확인 불가"})
    return out


def record(conn, ticker: str, day: str, kind: str, price: float | None) -> bool:
    conn.execute(DDL)
    cur = conn.execute("INSERT OR IGNORE INTO flowread_events (date, ticker, kind, price, at) VALUES (?,?,?,?,?)", (day, ticker, kind, price, db.utcnow_iso()))
    conn.commit()
    return cur.rowcount > 0


def events() -> pd.DataFrame:
    with closing(db.connect()) as c:
        c.execute(DDL)
    return db.read_df("SELECT date, ticker, kind, price FROM flowread_events ORDER BY date DESC, ticker")
