"""스승님 꿀팁 — 거래량 캔들(분산·털기)과 장외(다크풀) 움직임. 모든 종목에 공통 데이터로 적용.

분산(매도 차익실현): 전일 대비 거래량 급증(기본 2배 이상) + 음봉 마감 → 좋지 않은 신호(PR 뿌리고 ATM 돌리는 종목에서 자주)
털기(저점 매집): 전일 대비 거래량 급증 + 양봉 마감 → 다음날도 양봉이어야 '확인', 음봉이면 '실패', 아직 다음날이 없으면 '확인 대기'
장외 움직임: 대차(공매도 가용잔고) 넉넉한데 장외(다크풀) 비중이 월등히 높음(기본 60% 이상) → 하락 주체가 공매도가 아닌 세력의 장외 덤핑 또는 매집.
  악재·펀더멘탈 훼손·다른 위험을 철저히 확인하라는 경고.
판정은 마감된 일봉으로만 기록한다(장중 값은 거래량·캔들이 확정되지 않음). 누가 사고팔았는지는 데이터로 알 수 없어 모양에 따른 추정이다.
"""
from __future__ import annotations

from contextlib import closing

import pandas as pd

import db

TIP_TITLE = "스승님 꿀팁 — 더 오를까 더 내릴까(분산·털기·장외 움직임)"
TIP_TEXT = """첫번째는 '분산'입니다. 다른 말로 매도 차익실현이라고 보시면 됩니다.
전일대비 거래량이 급증하고 음봉 마감이면 좋은 신호가 아닙니다. (PR홍보 던지고 ATM돌리는 악랄한 종목에서 많이 보입니다)
두번째는 '털기'입니다. 다른말로는 저점매집 이라고 보시면 됩니다.
전일대비 거래량이 급증하고 양봉마감입니다. 이런경우 고점에서 되돌림이 나오는 패턴입니다.
다만 다음날도 양봉 마감추세는 유지가 되어야 합니다.
이건 간단히 파악을 하는 것이고, 사실 다크풀을 통한 움직임도 보아야 합니다.
공매도 가용잔고가 많았는데 다크풀이 월등히 높다는건 주가하락의 주체가 공매도가 아닌 '세력'의 장외 덤핑이거나 매집입니다.
이경우 악재가 발생을 했는지, 펀더멘탈의 파괴가 있었는지, 다른 리스크가 있는지를 철저히 파악해야 합니다.
(이경우는 시장이 모르게 덤핑으로 물량 떠넘기는 신호 입니다) 아니면 덤핑에 당하는 수가 있고 아니면 털기매집에 당하는 수가 있습니다."""
VOL_X = 2.0       # 전일 대비 거래량 '급증' 기준(출발값)
DARK_HIGH = 60.0  # 장외 비중 '월등히 높음' 기준(출발값)
DDL = "CREATE TABLE IF NOT EXISTS vc_events (date TEXT NOT NULL, ticker TEXT NOT NULL, kind TEXT, status TEXT, price REAL, vol_ratio REAL, at TEXT, PRIMARY KEY (date, ticker))"


def classify(df: pd.DataFrame | None, vol_x: float = VOL_X, lookback: int = 5) -> dict | None:
    """마감된 일봉(df)에서 최근 lookback 일 안의 가장 최근 분산/털기. 없으면 None."""
    if df is None or len(df) < 3:
        return None
    d = df.dropna(subset=["Open", "Close", "Volume"])
    if len(d) < 3:
        return None
    o, c, v = (d[k].to_numpy(float) for k in ("Open", "Close", "Volume"))
    last = len(c) - 1
    for k in range(last, max(0, last - lookback), -1):
        if v[k - 1] <= 0 or v[k] / v[k - 1] < vol_x or c[k] == o[k]:
            continue
        kind = "분산" if c[k] < o[k] else "털기"
        status = None
        if kind == "털기":
            status = "확인 대기" if k == last else ("확인" if c[k + 1] > o[k + 1] else "실패")
        return {"kind": kind, "status": status, "date": d.index[k].strftime("%Y-%m-%d"), "vol_ratio": float(v[k] / v[k - 1]),
                "chg_pct": float((c[k] / c[k - 1] - 1) * 100) if c[k - 1] > 0 else None, "price": float(c[k]), "days_ago": int(last - k)}
    return None


def label(vc: dict | None) -> str:
    if not vc:
        return ""
    d = vc["date"][5:]
    if vc["kind"] == "분산":
        return f"⚠️ 분산 {d} (거래량 {vc['vol_ratio']:.1f}배·음봉)"
    icon = {"확인": "🟢 털기 확인", "확인 대기": "⏳ 털기 확인 대기", "실패": "❌ 털기 실패"}[vc["status"]]
    return f"{icon} {d} (거래량 {vc['vol_ratio']:.1f}배·양봉)"


def dark_flag(dark: dict | None, short: dict | None, high: float = DARK_HIGH) -> dict | None:
    """대차 넉넉 + 장외 비중 높음 → 세력 장외 덤핑·매집 경고."""
    if not dark:
        return None
    sh = short or {}
    roomy = bool(sh.get("borrow_avail_capped") or (sh.get("borrow_avail") or 0) >= 50_000) and not sh.get("borrow_stale")
    hit = dark["dark_pct"] >= high and roomy
    return {"dark_pct": dark["dark_pct"], "days": dark["days"], "roomy": roomy, "flag": hit,
            "text": ("대차 넉넉한데 장외 비중 {:.0f}% — 하락 주체가 공매도가 아닌 세력의 장외 덤핑·매집일 수 있음. 악재·펀더멘탈·다른 위험을 철저히 확인".format(dark["dark_pct"])
                     if hit else f"장외 비중 {dark['dark_pct']:.0f}% ({dark['days']}일 평균)" + ("" if roomy else " · 대차 정보 없음/빠듯"))}


def record(conn, ticker: str, vc: dict | None) -> str | None:
    """완성된 일봉 기준 이벤트를 기록. 새로 생겼거나 상태가 바뀌면 그 상태 문자열을 돌려준다(알림용)."""
    if not vc:
        return None
    conn.execute(DDL)
    st = vc["status"] or vc["kind"]
    row = conn.execute("SELECT status FROM vc_events WHERE date=? AND ticker=?", (vc["date"], ticker)).fetchone()
    if row and row["status"] == st:
        return None
    conn.execute("INSERT OR REPLACE INTO vc_events (date, ticker, kind, status, price, vol_ratio, at) VALUES (?,?,?,?,?,?,?)",
                 (vc["date"], ticker, vc["kind"], st, vc["price"], vc["vol_ratio"], db.utcnow_iso()))
    conn.commit()
    return st


def events() -> pd.DataFrame:
    with closing(db.connect()) as c:
        c.execute(DDL)
    return db.read_df("SELECT date, ticker, kind, status, price, vol_ratio FROM vc_events ORDER BY date DESC, ticker")
