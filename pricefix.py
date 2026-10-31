"""🩹 병합(역분할) 뒤 저장 일봉의 기준 섞임 수리 (2026-10-30).

왜: `daily_prices` 는 야후 일봉을 그때그때 덮어쓴 것이라 병합이 지나면
  (a) 아침 갱신 대상(case_progress done)이 아닌 종목은 병합 전 봉이 옛 기준 그대로 남아 병합일에 ×비율 점프가 생기고(스캐너는 최근 3봉만 씀),
  (b) 갱신 대상이라도 6개월 창 밖의 옛 봉은 옛 기준으로 남는다.
  운영 복사본(10/30 02:19) 조사: 병합일 경계 점프 16건·33종목(AXG 10/26 ×199 · ENLV ×14.8 · BTOC ×16 · DKI ×16.7 …).
  `daily_prices` 를 읽는 모듈이 17개(presim·screener·sigmodel·timemachine·aipick·autopsy…)라 가짜 급등·급락을 그대로 본다.
어떻게: 병합 종목의 2년 일봉을 야후에서 다시 받아 통째로 덮어쓴다(INSERT OR REPLACE — 지우지 않음, 야후에 없으면 그대로 둠).
  아침 작업: 처음 한 번은 2년 안 병합 종목 전부(meta `pricefix_2y_done`), 그 뒤로는 최근 10일 안 병합 종목 + 경계 점프가 보이는 종목만.
2026-10-31 계단 점검: 위 방식은 야후 병합 기록의 '그 날짜'만 봐서 운영 DB 최근 60일 계단 45곳 중 대부분을 놓쳤음 —
  ① 야후 병합 날짜가 실제 경계와 1~2일 어긋남(ENLV 기록 10/27 · 계단 10/26) ② 야후는 고쳤는데 병합 기록이 없어 다시 안 받음(ENHA·AMTD·MASK)
  ③ 야후 일봉도 아직 환산 전(ENLV ×15 · AXG ×92 · OMEX ×21 — 다시 받아도 그대로).
  → 일봉에서 직접 하루 ×3↑·÷3↓ 변화를 찾아 그 종목을 야후에서 다시 받고(②, ③ 은 야후가 고치는 날 해결),
    그래도 남은 '계단'(위로 뛰고 그대로 머묾 + 시가부터 새 단위)이 알려진 병합(야후 기록·SEC 🗓 역분할 시행, ±5일)의 비율과 맞으면 병합 전 봉을 직접 환산(①·③).
    병합 근거가 없는 계단(진짜 급등·모르는 병합)과 하루만 튄 값은 건드리지 않고 로그에만 남김.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

import db

RECENT_DAYS = 10
LOOKBACK_DAYS = 730
META_KEY = "pricefix_2y_done"
STEP_X = 3.0          # 하루 ×3↑ 또는 ÷3↓ 변화 = 다시 받을 종목
STEP_KEEP = 0.5       # 뒤 3봉 중앙값 ÷ 앞 3봉 중앙값이 점프의 0.5제곱(√) 이상이면 '계단', 아래면 하루 튐(MI 10/5 ×7.8 → 다음 날 제자리). 병합 뒤 급락(AXG ×142 → 사흘 −66%)도 계단으로 남게 √
STEP_DAYS = 60        # 매일 아침 보는 창(야후가 늦게 고치는 병합은 보통 몇 주 안에 고쳐짐)
SPLIT_NEAR = 5        # 병합 기록 날짜와 계단 날짜 차이 허용(일)
RATIO_TOL = 1.5       # 계단 크기가 병합 비율의 1/1.5 ~ 1.5배면 같은 병합(AXG 1:200 계단 ×142 · ENLV 1:16 ×14.8 · 병합일 실제 등락 포함)
STEPS_META = "pricefix_steps_2y_done"


def split_tickers(conn, lookback_days: int = LOOKBACK_DAYS, today: date | None = None) -> list[str]:
    since = ((today or date.today()) - timedelta(days=lookback_days)).isoformat()
    try:
        return sorted({r[0] for r in conn.execute("SELECT ticker FROM rs_events WHERE ratio > 0 AND ratio < 1 AND date >= ?", (since,))})
    except Exception:  # noqa: BLE001  (표가 없는 새 DB)
        return []


def recent_split_tickers(conn, days: int = RECENT_DAYS, today: date | None = None) -> list[str]:
    return split_tickers(conn, days, today)


def boundary_tickers(conn, lookback_days: int = LOOKBACK_DAYS, today: date | None = None) -> list[str]:
    """병합일 직전 종가 → 직후 종가가 √(1/비율) 넘게 튀면 병합 전 봉이 미환산(환산된 자료는 그런 점프가 없다)."""
    since = ((today or date.today()) - timedelta(days=lookback_days)).isoformat()
    out = set()
    try:
        ev = conn.execute("SELECT ticker, date, ratio FROM rs_events WHERE ratio > 0 AND ratio < 1 AND date >= ?", (since,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    for t, d, r in ev:
        before = conn.execute("SELECT close FROM daily_prices WHERE ticker=? AND date<? AND close>0 ORDER BY date DESC LIMIT 1", (t, d)).fetchone()
        after = conn.execute("SELECT close FROM daily_prices WHERE ticker=? AND date>=? AND close>0 ORDER BY date LIMIT 1", (t, d)).fetchone()
        if before and after and after[0] / before[0] > math.sqrt(1.0 / float(r)):
            out.add(t)
    return sorted(out)


def repair(conn, tickers: list[str], download=None, period: str = "2y", chunk: int = 50, drop: bool = True) -> dict:
    """야후 2년 일봉으로 다시 쓴다. 자료가 짧으면(20봉 미만) 건드리지 않음."""
    import pandas as pd

    import cases
    import market
    dl = download or (lambda ts: market.download_daily(ts, period=period, chunk=chunk))
    n_t = n_rows = 0
    changed: list[str] = []
    cover: dict[str, str] = {}   # 종목별 다시 쓴 첫 날짜(직접 환산을 다시 할 때 이 날짜부터만)
    edge: list[tuple[str, float, int]] = []   # 2년 창 밖 옛 봉에 야후 배수를 맞춘 종목(티커, 배수, 봉 수)
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        data = dl(part) or {}
        for t in part:
            df = cases.drop_incomplete_last_bar(data.get(t))
            if df is None or len(df) < 20:
                continue
            if _differs(conn, t, df):
                changed.append(t)
            head = df["Close"].dropna().iloc[:5]
            hd = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in head.index]
            old = dict(conn.execute(f"SELECT date, close FROM daily_prices WHERE ticker=? AND close > 0 AND date IN ({','.join('?' * len(hd))})", (t, *hd)).fetchall()) if hd else {}
            n_rows += db.retry_locked(db.upsert_daily_prices, conn, t, df)
            cover[t] = pd.Timestamp(df.index[0]).strftime("%Y-%m-%d")
            # 2026-10-31: 저장 일봉은 3년(2023-10~), 야후는 2년만 다시 받음 → 그 사이 야후가 병합을 반영했으면 2년 창 밖 옛 봉만 옛 단위로 남아 2년 전 날짜에 새 계단이 생김
            # (10월 병합 ENHA·MASK·AMTD 를 다시 받으면 바로 생김). 창 첫 5일의 새 값 ÷ 옛 값(= 야후가 그동안 적용한 배수)을 창 밖 봉에도 똑같이 — 우리가 직접 환산한 종목은 빼고
            ratios = sorted(float(c) / old[d] for d, c in zip(hd, head.to_numpy()) if d in old and c and c > 0)
            f = ratios[len(ratios) // 2] if ratios else 1.0
            if abs(math.log(f)) > math.log(1.15) and not _has_adj(conn, t):
                k = adjust(conn, t, cover[t], f)
                if k:
                    edge.append((t, f, k))
            n_t += 1
    dropped = _drop_presim(conn, changed) if drop else 0   # morning 은 직접 환산까지 끝낸 뒤 한 번에(되돌렸다 다시 환산한 종목은 빼고)
    return {"tickers": n_t, "rows": n_rows, "changed": changed, "presim_dropped": dropped, "cover": cover, "edge": edge}


def _has_adj(conn, t: str) -> bool:
    try:
        return conn.execute("SELECT 1 FROM price_adj WHERE ticker=? LIMIT 1", (t,)).fetchone() is not None
    except Exception:  # noqa: BLE001  (표 없음 = 직접 환산한 적 없음)
        return False


def _differs(conn, t: str, df, tol: float = 0.02) -> bool:
    """저장된 종가와 새 종가가 같은 날짜에서 2% 넘게 다른 날이 있으면 True(= 옛 기준 봉이 있었음)."""
    import pandas as pd
    old = dict(conn.execute("SELECT date, close FROM daily_prices WHERE ticker=? AND close > 0", (t,)).fetchall())
    if not old:
        return False
    for ts, c in df["Close"].dropna().items():
        o = old.get(pd.Timestamp(ts).strftime("%Y-%m-%d"))
        if o and c and abs(float(c) / float(o) - 1) > tol:
            return True
    return False


def _drop_presim(conn, tickers: list[str]) -> int:
    """일봉이 바뀐 종목의 🎲 사건(presim_ep)을 지움 → 같은 아침 presim.build_episodes 가 고친 일봉으로 다시 만듦(표 전체 재작성 없이)."""
    if not tickers:
        return 0
    try:
        q = ",".join("?" * len(tickers))
        def _d():
            cur = conn.execute(f"DELETE FROM presim_ep WHERE ticker IN ({q})", tickers)
            conn.commit()
            return max(0, cur.rowcount or 0)
        return db.retry_locked(_d)
    except Exception:  # noqa: BLE001  (presim 표가 아직 없는 DB)
        return 0


def find_jumps(bars: list[tuple], since: str = "") -> tuple[list[tuple[str, float]], list[str]]:
    """bars = 날짜순 [(날짜, 시가, 종가)] → (계단 [(날짜, 배수)], 하루 ×3↑·÷3↓ 변화가 있던 날 전부). since 이전 날짜는 앞 봉으로만 씀.
    계단 = 위로 ×3↑ 뛰고 뒤 3봉도 그 높이(되돌아오지 않음) + 시가부터 새 단위(시가 ÷ 전날 종가 > √배수 — 장중에 오른 진짜 급등과 구분)."""
    steps, days = [], []
    for i in range(1, len(bars)):
        d, o, c = bars[i]
        pc = bars[i - 1][2]
        if d < since or not c or not pc or pc <= 0:
            continue
        r = c / pc
        if r < STEP_X and r > 1 / STEP_X:
            continue
        days.append(d)
        if r < STEP_X or i + 1 >= len(bars):   # 아래 방향(대부분 진짜 폭락) · 마지막 봉(머무는지 아직 모름)은 계단 판단 안 함
            continue
        pre = sorted(b[2] for b in bars[max(0, i - 3):i])
        post = sorted(b[2] for b in bars[i:i + 3])
        keep = post[len(post) // 2] / pre[len(pre) // 2]
        gap = (o if o and o > 0 else c) / pc
        if keep >= r ** STEP_KEEP and gap > math.sqrt(r):
            steps.append((d, r))
    return steps, days


def scan(conn, days: int = STEP_DAYS, today: date | None = None, tickers: list[str] | None = None) -> dict[str, dict]:
    """창 안에 하루 ×3↑·÷3↓ 변화가 있는 종목 → {'steps': [(날짜, 배수)], 'days': [날짜]}."""
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    lo = (today - timedelta(days=days + 15)).isoformat()   # 창 첫날 앞 봉(중앙값용)
    if tickers is not None and len(tickers) > 400:   # SQLite 인자 개수 한도
        out_all: dict[str, dict] = {}
        for i in range(0, len(tickers), 400):
            out_all.update(scan(conn, days, today, tickers[i:i + 400]))
        return out_all
    q = "SELECT ticker, date, open, close FROM daily_prices WHERE date >= ? AND close > 0"
    args: list = [lo]
    if tickers is not None:
        if not tickers:
            return {}
        q += f" AND ticker IN ({','.join('?' * len(tickers))})"
        args += list(tickers)
    out: dict[str, dict] = {}
    cur_t, buf = None, []

    def _flush():
        if cur_t and buf:
            st, ds = find_jumps(buf, since)
            if ds:
                out[cur_t] = {"steps": st, "days": ds}
    for t, d, o, c in conn.execute(q + " ORDER BY ticker, date", args):
        if t != cur_t:
            _flush()
            cur_t, buf = t, []
        buf.append((d, o, c))
    _flush()
    return out


def known_ratios(conn, ticker: str) -> list[tuple[str, float]]:
    """알려진 병합 [(날짜, N)] — 야후 병합 기록(rs_events) + SEC 공시에서 뽑은 🗓 역분할 시행(1:N)."""
    got: list[tuple[str, float]] = []
    try:
        got += [(d, 1.0 / r) for d, r in conn.execute("SELECT date, ratio FROM rs_events WHERE ticker=? AND ratio > 0 AND ratio < 1", (ticker,))]
    except Exception:  # noqa: BLE001  (표 없음)
        pass
    try:
        for d, ti in conn.execute("SELECT date, title FROM events WHERE ticker=? AND kind='역분할 시행'", (ticker,)):
            m = re.search(r"1:(\d+(?:\.\d+)?)", ti or "")
            if m and float(m.group(1)) > 1:
                got.append((d, float(m.group(1))))
    except Exception:  # noqa: BLE001
        pass
    return got


def match_ratio(step_day: str, r: float, known: list[tuple[str, float]]) -> float | None:
    """계단(날짜·배수)에 맞는 병합 비율 N — 날짜 ±SPLIT_NEAR일 · 배수가 N 의 1/RATIO_TOL~RATIO_TOL 배. 여럿이면 배수에 가장 가까운 것."""
    sd = date.fromisoformat(step_day)
    best = None
    for d, n in known:
        try:
            near = abs((date.fromisoformat(d) - sd).days) <= SPLIT_NEAR
        except ValueError:
            continue
        if near and n / RATIO_TOL <= r <= n * RATIO_TOL:
            err = abs(math.log(r / n))
            if best is None or err < best[0]:
                best = (err, n)
    return best[1] if best else None


ADJ_DDL = "CREATE TABLE IF NOT EXISTS price_adj (ticker TEXT NOT NULL, step_day TEXT NOT NULL, n REAL, rows INTEGER, at TEXT, PRIMARY KEY (ticker, step_day))"


def adjust(conn, ticker: str, step_day: str, n: float, since: str | None = None) -> int:
    """병합 전 봉(step_day 이전, since 가 있으면 그날부터)을 새 기준으로: 가격 ×N · 거래량 ÷N(지우지 않음). 바꾼 봉 수."""
    q = "UPDATE daily_prices SET open=open*?, high=high*?, low=low*?, close=close*?, volume=volume/? WHERE ticker=? AND date<?"
    args: list = [n, n, n, n, n, ticker, step_day]
    if since:
        q += " AND date>=?"
        args.append(since)

    def _u():
        cur = conn.execute(q, args)
        conn.commit()
        return max(0, cur.rowcount or 0)
    return db.retry_locked(_u)


def fix_steps(conn, tickers: list[str], days: int, today: date | None = None, cover: dict[str, str] | None = None) -> dict:
    """다시 받은 뒤에도 남은 계단 중 알려진 병합과 맞는 것만 직접 환산.
    처음 고치는 경계는 그 앞 봉 전부, 예전에 고친 경계(price_adj 기록)는 오늘 야후에서 다시 쓴 구간(cover)만 — 3년치 봉 중 야후 2년 창 밖은 이미 환산돼 있어
    전부 다시 곱하면 ×N² 가 됨. 다시 받지 못한 종목의 예전 경계는 다음 날로 미룸.
    {'fixed': [(티커, 날짜, N, 봉 수)], 'again': [예전에 고친 경계를 다시 받아 되돌아가서 또 환산한 티커], 'unknown': [(티커, 날짜, 배수)], 'waiting': [(티커, 날짜)]}."""
    conn.execute(ADJ_DDL)
    cover = cover or {}
    fixed, unknown, waiting, again = [], [], [], []
    for t, v in scan(conn, days, today, tickers).items():
        known = known_ratios(conn, t)
        for d, r in sorted(v["steps"], reverse=True):
            n = match_ratio(d, r, known)
            if not n:
                unknown.append((t, d, r))
                continue
            seen = conn.execute("SELECT 1 FROM price_adj WHERE ticker=? AND step_day=?", (t, d)).fetchone()
            if seen and t not in cover:
                waiting.append((t, d))
                continue
            k = adjust(conn, t, d, n, cover[t] if seen else None)
            db.retry_locked(lambda: (conn.execute("INSERT OR REPLACE INTO price_adj VALUES (?,?,?,?,?)", (t, d, n, k, db.utcnow_iso())), conn.commit()))
            if seen:
                again.append(t)
            else:
                fixed.append((t, d, n, k))
    return {"fixed": fixed, "again": sorted(set(again)), "unknown": unknown, "waiting": waiting}


def morning(conn, out=print, download=None, today: date | None = None) -> dict:
    today = today or date.today()
    first = db.get_meta(META_KEY) is None
    steps_first = db.get_meta(STEPS_META) is None
    sdays = LOOKBACK_DAYS if steps_first else STEP_DAYS
    jumpy = scan(conn, sdays, today)
    base = split_tickers(conn, today=today) if first else sorted(set(recent_split_tickers(conn, today=today)) | set(boundary_tickers(conn, today=today)))
    tickers = sorted(set(base) | set(jumpy))
    res = repair(conn, tickers, download=download, drop=False) if tickers else {"tickers": 0, "rows": 0, "changed": [], "presim_dropped": 0, "cover": {}}
    # 다시 받은 종목 전부를 2년 창으로: 최근 병합으로 다시 받은 종목도 야후 미환산 봉이 돌아오므로(안 그러면 하루 걸러 깨짐) · 몇십 종목이라 빠름
    st = fix_steps(conn, tickers, LOOKBACK_DAYS, today, res.get("cover")) if tickers else {"fixed": [], "again": [], "unknown": [], "waiting": []}
    # 바뀐 종목 = 야후가 다른 값을 준 종목 − 되돌아갔다 다시 환산해 결국 그대로인 종목 + 처음 직접 환산한 종목(미리 보기 둘째 아침: 6종목이 매일 '바뀜'으로 잡혀 🎲 사건을 헛되이 다시 만들었음)
    net = sorted((set(res.get("changed", [])) - set(st["again"])) | {t for t, *_ in st["fixed"]})
    res["changed"], res["presim_dropped"] = net, _drop_presim(conn, net)
    left = boundary_tickers(conn, today=today)
    if first:
        db.set_meta(META_KEY, today.isoformat())
    if steps_first:
        db.set_meta(STEPS_META, today.isoformat())
    fx = ", ".join(f"{t}×{n:g}" for t, _, n, _ in st["fixed"][:8])
    uk = ", ".join(f"{t}×{r:.0f}" for t, _, r in st["unknown"][:8])
    out(f"병합 환산 수리: 대상 {len(tickers)}종목 → {res['tickers']}종목 {res['rows']:,}봉 다시 씀 · 실제로 바뀐 종목 {len(net)}개(🎲 사건 {res.get('presim_dropped', 0):,}건 다시 만들 예정)"
        + (" (처음 한 번: 2년 안 병합 종목 전부)" if first else "")
        + f" · 계단 점검({'처음 한 번 2년' if steps_first else f'최근 {sdays}일'}): 하루 ×3 변화 {len(jumpy)}종목 다시 받음"
        + (f" · 2년 창 밖 옛 봉 배수 맞춤 {len(res.get('edge', []))}종목" if res.get("edge") else "")
        + (f" · 직접 환산 {len(st['fixed'])}곳({fx})" if st["fixed"] else "")
        + (f" · 야후가 아직 환산 전이라 다시 맞춘 종목 {len(st['again'])}개" if st["again"] else "")
        + (f" · 병합 근거 없는 계단 {len(st['unknown'])}곳 그대로({uk})" if st["unknown"] else "")
        + (f" · 야후에서 못 받아 내일로 {len(st['waiting'])}곳" if st["waiting"] else "")
        + (f" · 아직 경계 점프 남음 {len(left)}종목({', '.join(left[:8])})" if left else ""))
    return {**res, "first": first, "asked": len(tickers), "left": left, "jumpy": sorted(jumpy),
            "steps_fixed": st["fixed"], "steps_again": st["again"], "steps_unknown": st["unknown"], "steps_waiting": st["waiting"]}
