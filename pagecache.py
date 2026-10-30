"""🔥 화면 캐시 데우기(2026-10-28) — 느린 계산 결과를 DB(page_cache 표)에 미리 만들어 두고 화면은 꺼내 쓰기만 한다.

왜: 서버에서 재 보니 🏁 종합 순위 계산이 20~27초(종목 2,214개마다 DB 를 새로 열어 1만 2천 번), 🎯 장마감 체크리스트의 '종합 N위' 열도 같은 계산,
    ⚡ EFFECT 는 야후 일봉 127종목 내려받기 22초, 📚 과거 사례는 공시 플래그 계산 21초 + 공시 90만 줄 읽기 3초(캐시가 없어 매번).
    Streamlit 의 st.cache_data 는 프로세스 안 기억이라 5~15분마다 다시 느려지고, 아침 갱신(다른 프로세스)이 데워 줄 수도 없다.
어떻게: quant-warm.timer(10분마다, deploy/install_warm_timer.sh) 가 `python pagecache.py warm` 을 돌려 ENTRIES 중 만든 지 오래된 것만 다시 만든다.
    화면은 get() 으로 꺼내 쓰고, 없거나 너무 오래됐으면 예전처럼 직접 계산한 뒤 put() 으로 넣어 둔다 → 캐시가 없어도 화면은 똑같이 동작한다.
    아침 갱신(cases.py update) 끝에서는 force=True 로 전부 다시 만든다(새 사건·공시·순위 반영).
항목: rank(순위 표) · px(EFFECT 60일 종목 + 순위 상위 60 의 6개월 일봉) · rank_s3(상위 60 의 ✅ 3대 조건 판정) · secflags(과거 사건 전체의 급락일 전후 공시 플래그)
보관: pickle BLOB(같은 venv 의 pandas 로만 읽음). 못 읽으면 없는 것으로 치고 다시 계산한다. 관리 모드 '🔥 화면 캐시'에서 상태를 본다.
"""
from __future__ import annotations

import logging
import pickle
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import db

log = logging.getLogger(__name__)
DDL = "CREATE TABLE IF NOT EXISTS page_cache (name TEXT PRIMARY KEY, built_at TEXT NOT NULL, secs REAL, blob BLOB NOT NULL)"
RANK_MIN_SCORE = 20   # 🏁 화면 '종합 ≥' 슬라이더 기본값(rank_ui) — 상위 60(3대 조건·일봉 대상)은 이 기준으로 고른다
TOP_N = 60
EFFECT_DAYS = 60      # ⚡ EFFECT 화면 기간 슬라이더의 최대값 — 그 안의 종목 일봉을 다 받아 두면 7·14·30·60일 어느 선택이든 캐시로 된다


# ---------------------------------------------------------------- 저장소
def ensure(conn) -> None:
    conn.execute(DDL)


def put(name: str, obj, secs: float | None = None, conn=None) -> None:
    blob = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)

    def _w(c):
        ensure(c)
        c.execute("INSERT OR REPLACE INTO page_cache (name, built_at, secs, blob) VALUES (?,?,?,?)", (name, db.utcnow_iso(), secs, blob))
        c.commit()
    import sqlite3
    import time
    for i in range(4):   # 2026-10-30: 아침 작업이 스캐너와 겹칠 때 'database is locked' 로 px 캐시가 빠지던 것 → 0.5·1·1.5초 쉬고 다시
        try:
            if conn is not None:
                _w(conn)
            else:
                with closing(db.connect()) as c:
                    _w(c)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and i < 3:
                time.sleep(0.5 * (i + 1))
                continue
            raise


def _row(name: str, conn=None, blob: bool = True):
    cols = "built_at, secs" + (", blob" if blob else "")

    def _r(c):
        ensure(c)
        return c.execute(f"SELECT {cols} FROM page_cache WHERE name=?", (name,)).fetchone()
    try:
        if conn is not None:
            return _r(conn)
        with closing(db.connect()) as c:
            return _r(c)
    except Exception as e:  # noqa: BLE001
        log.warning("page_cache 읽기 실패(%s): %s", name, e)
        return None


def _age(built_at: str | None) -> float | None:
    """만든 지 몇 분 지났나(UTC 기준)."""
    try:
        t = datetime.fromisoformat(str(built_at))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 60


def age_min(name: str, conn=None) -> float | None:
    r = _row(name, conn, blob=False)
    return _age(r["built_at"]) if r else None


def get(name: str, max_age_min: float | None = None, conn=None):
    """캐시 값. 없거나 max_age_min 분보다 오래됐거나 못 읽으면 None(→ 화면이 직접 계산)."""
    r = _row(name, conn)
    if not r:
        return None
    if max_age_min is not None:
        a = _age(r["built_at"])
        if a is None or a > max_age_min:
            return None
    try:
        return pickle.loads(r["blob"])
    except Exception as e:  # noqa: BLE001
        log.warning("page_cache %s 풀기 실패(다시 계산): %s", name, e)
        return None


def invalidate(name: str) -> None:
    with closing(db.connect()) as c:
        ensure(c)
        c.execute("DELETE FROM page_cache WHERE name=?", (name,))
        c.commit()


def status() -> list[dict]:
    """관리 모드 표: 항목·설명·만든 시각(KST)·지난 분·걸린 초·크기."""
    from zoneinfo import ZoneInfo
    with closing(db.connect()) as c:
        ensure(c)
        rows = c.execute("SELECT name, built_at, secs, length(blob) AS size FROM page_cache ORDER BY name").fetchall()
    out = []
    for r in rows:
        a = _age(r["built_at"])
        try:
            t = datetime.fromisoformat(r["built_at"])
            kst = (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo("Asia/Seoul")).strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            kst = str(r["built_at"])[:16]
        out.append({"항목": r["name"], "설명": ENTRIES.get(r["name"], ("(옛 항목)",))[0], "만든 시각(KST)": kst,
                    "지난 시간(분)": None if a is None else round(a), "걸린 초": None if r["secs"] is None else round(r["secs"], 1), "크기(KB)": round((r["size"] or 0) / 1024)})
    return out


# ---------------------------------------------------------------- 무엇을 미리 만드나
def effect_tickers(conn, days: int = EFFECT_DAYS) -> list[str]:
    """⚡ EFFECT 화면(accum_ui.render_effect)과 같은 규칙: 최근 days 일 안에 EFFECT 공시가 있는 종목."""
    import accum
    since = (date.today() - timedelta(days=days)).isoformat()
    f = accum.filings_map(conn, [], (date.today() - timedelta(days=days + 120)).isoformat())
    return sorted({t for t, fl in f.items() for d, fm in fl if str(fm).upper() == "EFFECT" and str(d) >= since})


def rank_top(df: pd.DataFrame | None, n: int = TOP_N, min_score: float = RANK_MIN_SCORE) -> list[str]:
    """🏁 화면 기본 보기(전체 · 종합 ≥ 20)에서 카드로 그리는 상위 n 종목."""
    if df is None or df.empty or "score" not in df:
        return []
    return [str(t) for t in df[df["score"] >= min_score].head(n)["ticker"]]


def _build_rank():
    import rank
    return rank.compute()


def _build_px():
    import market
    with closing(db.connect()) as conn:
        tk = set(effect_tickers(conn))
    tk |= set(rank_top(get("rank")))
    tk = sorted(t for t in tk if t)
    return market.download_daily(tk, period="6mo") if tk else {}


def _build_rank_s3():
    import setup3
    tickers = rank_top(get("rank"))
    px = prices(tuple(tickers))
    with closing(db.connect()) as conn:
        data = setup3.marks(tickers, px, conn)
    return {"tickers": tuple(tickers), "data": data}


def _build_secflags():
    import secbackfill as sb
    if not sb.status()["done"]:
        return pd.DataFrame()
    ev = db.read_df("SELECT ticker, date FROM case_events ORDER BY ticker, date")
    if ev.empty:
        return pd.DataFrame()
    hist = db.read_df("SELECT ticker, form, filed, items FROM sec_hist")   # 사건 종목이 거의 전체라 통째로 읽는다
    fl = sb.event_flags(ev, hist)
    fl.index = pd.MultiIndex.from_arrays([ev["ticker"].values, ev["date"].values], names=["ticker", "date"])
    return fl


def _build_pick30():
    import pick30
    return pick30.scan()


# 이름: (설명, 다시 만드는 주기(분), 화면이 믿고 쓰는 최대 나이(분), 만드는 함수) — 순서대로 만든다(px·rank_s3 는 rank 를 쓴다)
ENTRIES = {
    "rank": ("🏁 종합 순위 표(🎯 장마감 체크리스트의 '종합 N위' 열도 같이 씀)", 10, 25, _build_rank),
    "px": (f"⚡ EFFECT {EFFECT_DAYS}일 종목 + 순위 상위 {TOP_N} 의 6개월 일봉(야후)", 20, 45, _build_px),
    "rank_s3": (f"🏁 순위 상위 {TOP_N} 의 ✅ 3대 조건 판정", 10, 30, _build_rank_s3),
    "secflags": ("📚 과거 사건 전체의 급락일 전후 공시 플래그", 12 * 60, 36 * 60, _build_secflags),
    # 2026-10-30: 🎯 PICK 스캔이 1,800종목 압력·펀드 분석으로 12초(10분 캐시가 끝날 때마다 첫 화면이 기다림) → 미리 만들어 둠
    "pick30": ("🎯 PICK +30% 후보 스캔(압력·펀드 분석)", 10, 25, _build_pick30),
}


def _count(obj) -> str:
    if isinstance(obj, dict) and "data" in obj:
        return f"{len(obj['data'])}건"
    try:
        return f"{len(obj):,}건"
    except TypeError:
        return "-"


def warm(names: list[str] | None = None, force: bool = False, out=print) -> dict:
    """오래된 항목만(force 면 전부) 다시 만든다. 반환 {이름: 걸린 초 | None(건너뜀) | -1(실패)}."""
    res: dict[str, float | None] = {}
    for name, (desc, every, _, build) in ENTRIES.items():
        if names and name not in names:
            continue
        a = age_min(name)
        if not force and a is not None and a < every:
            res[name] = None
            continue
        t0 = time.time()
        try:
            obj = build()
            secs = time.time() - t0
            put(name, obj, secs)
            out(f"🔥 {name}: {secs:.1f}초 · {_count(obj)}")
            res[name] = secs
        except Exception as e:  # noqa: BLE001
            log.warning("화면 캐시 %s 실패: %s", name, e)
            out(f"🔥 {name} 실패: {e}")
            res[name] = -1
    return res


# ---------------------------------------------------------------- 화면이 쓰는 꺼내기
def prices(tickers: tuple) -> dict:
    """{티커: 6개월 일봉} — 캐시(px)에 있는 종목은 거기서, 없는 종목만 야후에서 받는다(watch_ui.prices 와 같은 모양)."""
    if not tickers:
        return {}
    px = get("px", ENTRIES["px"][2]) or {}
    out = {t: px[t] for t in tickers if t in px}
    miss = [t for t in tickers if t not in px]
    if miss:
        import market
        try:
            out.update(market.download_daily(list(miss), period="6mo"))
        except Exception as e:  # noqa: BLE001
            log.warning("일봉 받기 실패(%s…): %s", miss[:3], e)
    return out


def s3_data(tickers: tuple) -> dict:
    """🏁 ✅ 3대 조건 판정 데이터 — 캐시(rank_s3)가 요청 종목을 다 덮으면 그걸, 아니면 직접 계산(일봉은 px 캐시 우선)."""
    c = get("rank_s3", ENTRIES["rank_s3"][2])
    if isinstance(c, dict) and set(tickers) <= set(c.get("tickers", ())):
        return c.get("data", {})
    import setup3
    px = prices(tuple(tickers))
    with closing(db.connect()) as conn:
        return setup3.marks(list(tickers), px, conn)


def _hist(tickers) -> pd.DataFrame:
    tk = [str(t) for t in tickers]
    if not tk:
        return pd.DataFrame(columns=["ticker", "form", "filed", "items"])
    return db.read_df(f"SELECT ticker, form, filed, items FROM sec_hist WHERE ticker IN ({','.join('?' * len(tk))})", tuple(tk))


def secflags(cs: pd.DataFrame) -> pd.DataFrame:
    """📚 사건 표(cs: ticker·date 열)에 맞춘 공시 플래그(secbackfill.FLAGS 열, cs 와 같은 index).
    캐시(secflags)에서 꺼내고, 캐시보다 새 사건만 그 자리에서 계산한다. 캐시가 없으면 예전처럼 전부 계산."""
    import secbackfill as sb
    cols = list(sb.FLAGS)
    allf = get("secflags", ENTRIES["secflags"][2])
    if allf is None or allf.empty or cs.empty:
        return sb.event_flags(cs, _hist(cs["ticker"].unique()) if not cs.empty else pd.DataFrame())
    allf = allf[~allf.index.duplicated()]
    key = pd.MultiIndex.from_arrays([cs["ticker"].values, cs["date"].values])
    fl = allf.reindex(key)[cols]
    fl.index = cs.index
    miss = ~key.isin(allf.index)
    if miss.any():
        sub = cs[miss]
        fl.loc[sub.index, cols] = sb.event_flags(sub, _hist(sub["ticker"].unique())).values
    return fl


# ---------------------------------------------------------------- 명령줄: python pagecache.py warm [--force] [이름...] · python pagecache.py status
def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="🔥 화면 캐시 데우기")
    ap.add_argument("cmd", nargs="?", choices=["warm", "status"], default="warm")
    ap.add_argument("names", nargs="*", help="데울 항목 이름(비우면 전부)")
    ap.add_argument("--force", action="store_true", help="오래되지 않아도 다시 만든다")
    a = ap.parse_args(argv)
    import config
    config.apply_overrides()   # 관리 모드에서 바꾼 값(순위 비중 등)을 화면과 똑같이 쓴다
    db.init_db()
    if a.cmd == "status":
        rows = status()
        print(pd.DataFrame(rows).to_string(index=False) if rows else "(비어 있음)")
        return 0
    t0 = time.time()
    r = warm(a.names or None, a.force)
    print(f"끝 — {sum(1 for v in r.values() if v is not None and v >= 0)}개 만듦 · {sum(1 for v in r.values() if v is None)}개 건너뜀 · {sum(1 for v in r.values() if v == -1)}개 실패 · {time.time() - t0:.0f}초")
    return 0


if __name__ == "__main__":
    import quiet  # noqa: F401  (Streamlit 경고 줄 끄기)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    sys.exit(main(sys.argv[1:]))
