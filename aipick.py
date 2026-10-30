"""🤖 AI PICK — Claude 가 우리 자료(PICK·회사 압박·희석·런웨이·공시·주가 흐름·Reg SHO·3대 조건)를 요약본으로 읽고
'가장 빨리 의미 있게(+30%) 오를' 순서 · 시점 · 확신 · 근거 · 주의점을 매긴다. 규칙 기반 PICK 과 달리 '언제'와 뉘앙스를 본다.

· 하루 한 번(아침 갱신) · 대상 최대 AI_PICK_MAX(기본 25, PICK 통과 우선 + 종합 순위 상위) · 답은 상위 TOP(15)
· 월 예산(AI_MONTHLY_BUDGET_KRW, 기본 1만 원)을 넘으면 실행하지 않음(환율 1,400원으로 넉넉히 계산)
· 상위 10개를 확신(높음·중간·낮음)별로 🏆 성과 공표에 기록 → '확신 높음'이 정말 더 맞는지 데이터로 검증
· 공시 원문 전체가 아니라 우리가 이미 정리한 요약만 보냄(비용) · Claude 판단은 추정이며 투자 권유가 아님
요금(2026-10 공식 요금표 기준, 100만 토큰당 입력/출력): Sonnet 5.5 $2/$10 · Haiku 5.5 $0.10/$0.50 · Opus 5.5 $4/$20
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import config
import db

API_URL = "https://api.anthropic.com/v1/messages"
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-opus-5-5": (4.0, 20.0)}  # USD / 100만 토큰
FX = 1400.0          # 예산 계산용 환율(넉넉하게)
TOP = 15
SIG_TOP = 10         # 성과 공표 기록: 상위 N
SIG_GAP = 10         # 같은 종목은 N일에 한 번
TIMINGS = ("진행 중", "이번 주", "다음 주", "나중")
CONFS = ("높음", "중간", "낮음")
DDL = ["""CREATE TABLE IF NOT EXISTS ai_pick (date TEXT, ticker TEXT, rank INTEGER, timing TEXT, confidence TEXT, reason TEXT, risk TEXT, price REAL, model TEXT,
          PRIMARY KEY (date, ticker))""",
       "CREATE TABLE IF NOT EXISTS ai_pick_sig (date TEXT, ticker TEXT, price REAL, confidence TEXT, timing TEXT, rank INTEGER, PRIMARY KEY (date, ticker))"]

SYSTEM = """당신은 나스닥 초소형주(주로 $5 미만) 단기 트레이딩을 돕는 분석가입니다.
각 종목에 대해 사용자의 시스템이 정리한 '요약 자료'만 보고, 앞으로 가장 빨리 의미 있는 상승(+30% 이상)이 나올 가능성이 큰 순서를 매깁니다.
판단 순서:
1) 희석 위험: 최근 희석 서류(S-1·F-1·424B·ATM·ELOC), 매도 가능일이 다가오는 사모 딜, 행사가 근처 워런트, 현금 바닥(런웨이 3개월 미만), 반복 병합은 상승을 팔아 치울 가능성 → 크게 감점
2) 회사가 주가를 올려야 할 이유와 기한: 상장유지 $1 기한, 증자 전 주가 관리, 워런트 행사 유도, 주총·병합 투표
3) 이벤트 시점: events(일정)·filings·news 의 날짜 — 시점 판단의 핵심
4) 수급: 거래량+OBV 동반 증가, 과매도(RSI ≤ 25), 공매도 비율·커버 일수 높음, Reg SHO, 내부자 매수
확신 기준(엄격히):
- 높음 = (희석 위험 낮음) AND [(2주 안 기한·이벤트가 자료에 날짜로 있음 — pick.imm_days 의 회사 기한 포함) OR (이미 진행 중인 강한 수급: d1 또는 d5 급등 + 거래량·OBV 동반 상승)] AND (4번 근거 2개 이상) — 셋 다
- 중간 = 셋 중 둘
- 낮음 = 하나 이하, 또는 자료가 부족함
시점 기준: 진행 중 = 이미 급등이 시작됐거나 이벤트가 오늘·어제 / 이번 주 = 5거래일 안 이벤트·기한 / 다음 주 = 6~10거래일 / 나중 = 그 밖
규칙: 자료에 없는 사실·날짜를 지어내지 말 것. reason 에는 판단에 쓴 구체적 숫자·날짜를 넣을 것.
reason·risk 는 사용자가 읽는 한국어 문장이므로 d1·d5·dv20k·si_pct 같은 자료 키 이름 대신 '1일 +35%', '5일 +129%', '공매도 22%'처럼 우리말로 쓸 것.
forensic(덕구 공시분석 요약)이 있으면 원문을 깊게 읽은 결과이므로 희석 위험 판단에 가장 무게를 둘 것.
반드시 아래 JSON 만 출력(설명·마크다운 금지):
{"picks":[{"ticker":"ABCD","rank":1,"timing":"진행 중|이번 주|다음 주|나중","confidence":"높음|중간|낮음","reason":"한국어 80자 이내 핵심 근거(숫자·날짜)","risk":"한국어 50자 이내 가장 큰 위험"}]}
상위 """ + str(TOP) + """개만, rank 1 부터 차례로."""


# ---------------------------------------------------------------- 대상 · 요약
def candidates(conn, scan: dict | None = None, limit: int | None = None, ranking: pd.DataFrame | None = None) -> list[dict]:
    """PICK 통과(유력→가능→대기) 우선 + 🏁 종합 순위 상위로 채움. [{ticker, src, pick(행 또는 None), rank(자리·점수 또는 None)}]"""
    limit = limit or int(getattr(config, "AI_PICK_MAX", 25))
    if scan is None:
        try:
            import pick30
            scan = pick30.scan()
        except Exception:  # noqa: BLE001
            scan = {"pass": []}
    if ranking is None:
        try:
            import rank
            ranking = rank.compute()
        except Exception:  # noqa: BLE001
            ranking = pd.DataFrame()
    rk = {}
    if ranking is not None and not ranking.empty:
        for i, r in enumerate(ranking.head(200).to_dict("records"), 1):
            parts = r.get("parts") if isinstance(r.get("parts"), dict) else {}
            rk[r["ticker"]] = {"pos": i, "score": round(float(r.get("score") or 0), 1), "parts": {k: v for k, v in list(parts.items())[:6] if v}}
    try:
        import pick30
        rows = pick30.sort(scan.get("pass", []), "유력·임박 순")
    except Exception:  # noqa: BLE001
        rows = scan.get("pass", [])
    out, seen = [], set()
    for r in rows:
        if r["ticker"] not in seen:
            out.append({"ticker": r["ticker"], "src": "PICK", "pick": r, "rank": rk.get(r["ticker"])})
            seen.add(r["ticker"])
    for t, v in rk.items():
        if len(out) >= limit:
            break
        if t not in seen:
            out.append({"ticker": t, "src": "순위", "pick": None, "rank": v})
            seen.add(t)
    return out[:limit]


def _prices(conn, t: str) -> pd.DataFrame:
    q = conn.execute("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 130", (t,)).fetchall()
    if not q:
        return pd.DataFrame()
    d = pd.DataFrame(q, columns=["date", "Open", "High", "Low", "Close", "Volume"]).iloc[::-1].set_index("date")
    return d


def _chg(c: pd.Series, n: int):
    return None if len(c) <= n or not c.iloc[-1 - n] else round((c.iloc[-1] / c.iloc[-1 - n] - 1) * 100, 1)


def brief(conn, cand: dict, regsho: dict | None = None) -> dict:
    """종목 한 개의 요약(짧게). 없는 값은 빼서 토큰을 아낌."""
    t = cand["ticker"]
    b: dict = {"t": t, "src": cand["src"]}
    p = cand.get("pick")
    if p:
        b["pick"] = {k: p.get(k) for k in ("status", "target_name", "target", "pct", "imm_days", "imm_kind", "pressure", "runway") if p.get(k) not in (None, "", [])}
        if p.get("weak"):
            b["pick"]["weak"] = True
        why = p.get("why")
        if why:
            b["pick"]["why"] = (why if isinstance(why, str) else " · ".join(map(str, why)))[:160]
    d = _prices(conn, t)
    if not d.empty and len(d) >= 5:
        c = d["Close"].astype(float)
        b["px"] = {"last": round(float(c.iloc[-1]), 4), "d1": _chg(c, 1), "d5": _chg(c, 5), "d20": _chg(c, 20), "d60": _chg(c, 60),
                   "dv20k": round(float((c * d["Volume"].astype(float)).tail(20).mean()) / 1000, 0)}
        try:
            import setup3
            s, m = setup3.support_or_oversold(d), setup3.money_flow(d)
            if s.get("rsi") is not None:
                b["px"]["rsi"] = round(float(s["rsi"]), 0)
            b["px"]["flow"] = "거래량+OBV 동반↑" if m.get("strong") else ("OBV↑" if m.get("obv_up") else "-")
        except Exception:  # noqa: BLE001
            pass
    try:
        import setup3
        dl = setup3.dilution_absent(t, conn)
        b["dil"] = dl.get("label", "")[:80]
    except Exception:  # noqa: BLE001
        pass
    since = (date.today() - timedelta(days=30)).isoformat()
    try:
        fl = conn.execute("SELECT filed, form, tags, sentiment FROM sec_feed WHERE ticker=? AND filed >= ? ORDER BY filed DESC LIMIT 6", (t, since)).fetchall()
        if fl:
            b["filings"] = [f"{str(f[0])[:10]} {f[1]} {f[3] or ''} {(f[2] or '')[:40]}".strip() for f in fl]
    except Exception:  # noqa: BLE001
        pass
    if regsho and regsho.get(t):
        b["regsho_days"] = int(regsho[t])
    if cand.get("rank"):
        b["rank"] = cand["rank"]
    today = date.today()

    def q(sql, params):
        try:
            return conn.execute(sql, params).fetchall()
        except Exception:  # noqa: BLE001
            return []
    ev = q("SELECT date, kind, title FROM events WHERE ticker=? AND date BETWEEN ? AND ? ORDER BY date LIMIT 6",
           (t, (today - timedelta(days=7)).isoformat(), (today + timedelta(days=30)).isoformat()))
    if ev:
        b["events"] = [f"{e[0]}(D{(date.fromisoformat(str(e[0])[:10]) - today).days:+d}) {e[1] or ''} {(e[2] or '')[:40]}".strip() for e in ev]
    dl_ = q("SELECT filed, kind, proceeds, unit_price, warrants, resale FROM fs_deals WHERE ticker=? AND filed >= ? ORDER BY filed DESC LIMIT 3",
            (t, (today - timedelta(days=180)).isoformat()))
    if dl_:
        b["deals"] = [f"{str(d[0])[:10]} {d[1] or ''} " + (f"${d[2] / 1e6:.1f}M " if d[2] else "") + (f"@${d[3]:.3g} " if d[3] else "")
                      + ("워런트 " + str(d[4])[:40] + " " if d[4] and str(d[4]) not in ("[]", "{}", "None") else "") + ("재판매등록" if d[5] else "") for d in dl_]
    av = q("SELECT avail, kind FROM fs_deal_paths WHERE ticker=? AND avail >= ? ORDER BY avail LIMIT 2", (t, today.isoformat()))
    if av:
        b["sell_open"] = [f"{a_[0]} {a_[1] or ''} 매도 가능" for a_ in av]
    nw = q("SELECT published, title, sentiment FROM news WHERE ticker=? AND published >= ? ORDER BY published DESC LIMIT 4", (t, (today - timedelta(days=7)).isoformat()))
    if nw:
        b["news"] = [f"{str(n[0])[:10]} {n[2] or ''} {(n[1] or '')[:60]}".strip() for n in nw]
    ins = q("SELECT COUNT(*), SUM(value) FROM insider_tx WHERE ticker=? AND code='P' AND date >= ?", (t, (today - timedelta(days=60)).isoformat()))
    if ins and ins[0][0]:
        b["insider_buy"] = f"{ins[0][0]}건 ${(ins[0][1] or 0) / 1000:,.0f}K(60일)"
    si = q("SELECT si_pct, dtc, float_sh, si_date FROM short_interest WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
    try:  # 📡 ChartExchange FTD(결제 실패) — 있으면 brief 에 ftd_k(천 주)·ftd_date
        fr = q("SELECT settle_date, fails FROM cx_ftd WHERE ticker=? ORDER BY settle_date DESC LIMIT 1", (t,))
        if fr and fr[0][1]:
            b["ftd"] = {"ftd_k": round(fr[0][1] / 1e3, 1), "ftd_date": fr[0][0]}
    except Exception:  # noqa: BLE001
        pass
    if si and (si[0][0] or si[0][1]):
        b["short"] = {k: v for k, v in (("si_pct", None if si[0][0] is None else round(si[0][0], 1)), ("dtc", None if si[0][1] is None else round(si[0][1], 1)),
                                         ("float_m", None if not si[0][2] else round(si[0][2] / 1e6, 1)), ("as_of", si[0][3])) if v is not None}
    sn = q("SELECT float_shares, win_score, pump_score, buy_pressure, volume_mult FROM daily_snapshots WHERE ticker=? ORDER BY date DESC LIMIT 1", (t,))
    if sn:
        b["snap"] = {k: v for k, v in (("float_m", None if not sn[0][0] else round(sn[0][0] / 1e6, 1)), ("win", None if sn[0][1] is None else round(sn[0][1])),
                                        ("squeeze", None if sn[0][2] is None else round(sn[0][2])), ("buy_press", None if sn[0][3] is None else round(sn[0][3])),
                                        ("vol_x", None if sn[0][4] is None else round(sn[0][4], 1))) if v is not None}
    rs_ = q("SELECT COUNT(*), MAX(date) FROM rs_events WHERE ticker=? AND date >= ?", (t, (today - timedelta(days=730)).isoformat()))
    if rs_ and rs_[0][0]:
        b["reverse_splits_2y"] = f"{rs_[0][0]}회(최근 {rs_[0][1]})"
    tr = q("SELECT tier FROM s3_tier_signals WHERE ticker=? AND date >= ? ORDER BY date DESC LIMIT 1", (t, (today - timedelta(days=10)).isoformat()))
    if tr:
        b["s3_tier"] = int(tr[0][0])
    try:  # 🧾 덕구 공시분석(최근 45일 보고서)의 적색경보·런웨이 요약
        import forensic_ai
        fz = forensic_ai.latest_brief(conn, t)
        if fz:
            b["forensic"] = fz
        fm = forensic_ai.metrics_at(conn, t)
        if fm and fm.get("fd_ratio"):
            b["fd_ratio"] = round(float(fm["fd_ratio"]), 2)  # 완전희석 ÷ 기본 주식수(1.5배↑ = 큰 대기 물량)
    except Exception:  # noqa: BLE001
        pass
    return b


def refresh_events(tickers: list[str], out=print, client=None, days_gap: int = 7) -> int:
    """🗓 대상 종목의 최근 공시에서 일정(주총·상장유지 기한·역분할·워런트 만기·락업)을 뽑아 저장 — 종목당 days_gap 일에 한 번.
    워치리스트에만 돌던 공시 스캔을 AI PICK 대상에도 — 시점 판단의 재료."""
    import watch
    if client is None:
        if "@" not in (config.SEC_USER_AGENT or ""):
            return 0
        import sec
        client = sec.SecClient(config.SEC_USER_AGENT)
    today = date.today()
    n = 0
    for t in tickers:
        m = db.get_meta(f"ev_scan:{t}")
        if m and m.get("value") and m["value"] >= (today - timedelta(days=days_gap)).isoformat():
            continue
        try:
            watch.scan_ticker(client, t, days=365, max_docs=8)
            n += 1
        except Exception as e:  # noqa: BLE001
            out(f"일정 스캔 실패 {t}: {e}")
        db.set_meta(f"ev_scan:{t}", today.isoformat())
    if n:
        out(f"AI PICK 대상 공시 일정 스캔: {n}종목")
    return n


# ---------------------------------------------------------------- 예산
def _month() -> str:
    return date.today().strftime("%Y-%m")


def spent_usd(month: str | None = None) -> float:
    m = db.get_meta(f"ai_spend:{month or _month()}")
    try:
        return float(m["value"]) if m and m.get("value") else 0.0
    except (TypeError, ValueError):
        return 0.0


KINDS = {"pick": "🤖 AI PICK(아침 판단)", "forensic": "🧾 공시분석(11섹션 + 📰 요약)", "review": "🔍 Claude 복기(주 1회)", "card": "📇 스크리너 카드",
         "digest": "📨 공시 요약(Haiku)", "translate": "🌐 뉴스 번역(Haiku)", "summary": "🏢 종목 AI 요약", "other": "기타(빈 답 등)"}
SAVE_HINT = {"forensic": "관리 모드 '서버 공시분석 하루 종목 수'(FORENSIC_PER_RUN)를 줄이거나 자동 대기열을 끄면 가장 크게 줄어요",
             "card": "스크리너 카드는 버튼을 누를 때만 만들어지니 필요한 종목만", "pick": "AI PICK 모델을 Haiku 로 바꾸면 1/20 비용",
             "review": "주 1회라 거의 안 듦", "digest": "공시 요약 대상 폼을 줄이기", "translate": "뉴스 번역 건수 제한", "summary": "종목 AI 요약은 손으로 누를 때만"}
SPEND_DDL = ("CREATE TABLE IF NOT EXISTS ai_spend (date TEXT NOT NULL, kind TEXT NOT NULL, usd REAL NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0, "
             "in_tok INTEGER NOT NULL DEFAULT 0, out_tok INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (date, kind))")


def _add_spend(usd: float, kind: str = "other", tin: int = 0, tout: int = 0) -> None:
    """월 지갑 합계(meta, 예산 판정용) + 기능별 하루 기록(ai_spend, 2026-10-28 부터 — 관리 모드 '🤖 AI 비용' 표)."""
    db.set_meta(f"ai_spend:{_month()}", f"{spent_usd() + usd:.6f}")
    try:
        with closing(db.connect()) as conn:
            conn.execute(SPEND_DDL)
            conn.execute("INSERT INTO ai_spend (date, kind, usd, n, in_tok, out_tok) VALUES (?,?,?,1,?,?) "
                         "ON CONFLICT(date, kind) DO UPDATE SET usd=usd+excluded.usd, n=n+1, in_tok=in_tok+excluded.in_tok, out_tok=out_tok+excluded.out_tok",
                         (date.today().isoformat(), kind if kind in KINDS else "other", float(usd), int(tin or 0), int(tout or 0)))
            conn.commit()
    except Exception:  # noqa: BLE001
        pass


def _blank(kind: str) -> dict:
    return {"kind": kind, "label": KINDS.get(kind, kind), "month_usd": 0.0, "month_n": 0, "today_usd": 0.0, "today_n": 0, "in_tok": 0, "out_tok": 0}


def spend_rows(month: str | None = None) -> list[dict]:
    """기능별 이번 달·오늘 지출(달러·건수), 많이 쓴 순. 🏢 종목 AI 요약은 ai_reports 표에서 더한다."""
    m = month or _month()
    today = date.today().isoformat()
    rows = {k: _blank(k) for k in KINDS}
    with closing(db.connect()) as conn:
        conn.execute(SPEND_DDL)
        for k, d0, usd, n, ti, to in conn.execute("SELECT kind, date, usd, n, in_tok, out_tok FROM ai_spend WHERE substr(date,1,7)=?", (m,)):
            r = rows.get(k) or rows["other"]
            r["month_usd"] += usd or 0
            r["month_n"] += n or 0
            r["in_tok"] += ti or 0
            r["out_tok"] += to or 0
            if d0 == today:
                r["today_usd"] += usd or 0
                r["today_n"] += n or 0
        try:
            for d0, usd in conn.execute("SELECT day, COALESCE(cost_usd,0) FROM ai_reports WHERE substr(day,1,7)=?", (m,)):   # day = 현지 날짜(created_at 은 UTC)
                r = rows["summary"]
                r["month_usd"] += usd
                r["month_n"] += 1
                if d0 == today:
                    r["today_usd"] += usd
                    r["today_n"] += 1
        except Exception:  # noqa: BLE001
            pass
    return sorted([r for r in rows.values() if r["month_n"]], key=lambda r: -r["month_usd"])


def spend_days(month: str | None = None) -> dict[str, float]:
    """날짜별 지출(달러) — ai_spend + ai_reports."""
    m = month or _month()
    out: dict[str, float] = {}
    with closing(db.connect()) as conn:
        conn.execute(SPEND_DDL)
        for d0, usd in conn.execute("SELECT date, SUM(usd) FROM ai_spend WHERE substr(date,1,7)=? GROUP BY date", (m,)):
            out[d0] = out.get(d0, 0.0) + (usd or 0)
        try:
            for d0, usd in conn.execute("SELECT day, SUM(COALESCE(cost_usd,0)) FROM ai_reports WHERE substr(day,1,7)=? GROUP BY day", (m,)):
                out[d0] = out.get(d0, 0.0) + (usd or 0)
        except Exception:  # noqa: BLE001
            pass
    return dict(sorted(out.items()))


def spend_summary(month: str | None = None) -> dict:
    """관리 모드 카드용: 이번 달 지출·남은 예산·월말 예상(지금까지 하루 평균 × 그달 일수)·오늘·기능별 표. 금액은 원(FX)."""
    import calendar
    m = month or _month()
    today = date.today()
    y, mo = int(m[:4]), int(m[5:7])
    days_in = calendar.monthrange(y, mo)[1]
    elapsed = today.day if m == _month() else days_in
    total_usd = spent_usd(m)
    rows = spend_rows(m)
    tracked = sum(r["month_usd"] for r in rows if r["kind"] != "summary")   # 종목 AI 요약은 지갑(meta)에 안 더해지는 별도 표라 '기록 전' 계산에서 제외
    budget = float(getattr(config, "AI_MONTHLY_BUDGET_KRW", 50000))
    return {"month": m, "budget_krw": budget, "spent_krw": total_usd * FX, "left_krw": budget - total_usd * FX, "today_krw": sum(r["today_usd"] for r in rows) * FX,
            "forecast_krw": total_usd / max(elapsed, 1) * days_in * FX, "days_in": days_in, "elapsed": elapsed, "tracked_krw": tracked * FX,
            "untracked_krw": max(total_usd - tracked, 0.0) * FX, "top": rows[0] if rows else None, "rows": rows}


def cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    pi, po = PRICES.get(model, PRICES["claude-sonnet-5-5"])
    return in_tok / 1e6 * pi + out_tok / 1e6 * po


def estimate_usd(model: str, prompt: str, max_out: int) -> float:
    """보내기 전 예상 비용(한국어·숫자가 섞여 글자 2개≈토큰 1개로 넉넉히)."""
    return cost_usd(model, len(prompt) // 2 + 600, max_out)


def budget_left_krw() -> float:
    return float(getattr(config, "AI_MONTHLY_BUDGET_KRW", 10000)) - spent_usd() * FX


# ---------------------------------------------------------------- 호출 · 해석
def parse(text: str) -> list[dict]:
    s = re.sub(r"```(?:json)?", "", text or "").strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("JSON 이 아닌 답")
    picks = json.loads(s[i:j + 1]).get("picks") or []
    out, seen = [], set()
    for k, p in enumerate(picks, 1):
        t = str(p.get("ticker", "")).upper().strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append({"ticker": t, "rank": int(p.get("rank") or k), "timing": p.get("timing") if p.get("timing") in TIMINGS else "나중",
                    "confidence": p.get("confidence") if p.get("confidence") in CONFS else "낮음",
                    "reason": str(p.get("reason", ""))[:120], "risk": str(p.get("risk", ""))[:90]})
    out.sort(key=lambda r: r["rank"])
    return out[:TOP]


def call_claude(prompt: str, model: str, max_out: int = 4000, post=None, system: str | None = None, effort: str | None = None,
                thinking: dict | None = None, timeout: int = 300, kind: str = "other") -> tuple[str, int, int]:
    """Claude API 호출 → (글, 입력 토큰, 출력 토큰). 출력 토큰엔 '생각(thinking)' 토큰도 들어가 요금이 붙음.
    Sonnet 5.5 는 생각이 기본으로 켜져 있어(effort 기본 high) 한도를 생각에 다 쓰면 글이 비어 옴 → effort 로 깊이를 줄이고 한도를 넉넉히.
    Haiku 5.5 는 thinking={"type": "disabled"} 가능(effort high 이하)."""
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key and post is None:
        raise RuntimeError("ANTHROPIC_API_KEY 가 .env 에 없어요")
    if post is None:
        import requests
        post = requests.post
    r = post(API_URL, headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
             json=_body(model, max_out, system or SYSTEM, prompt, effort, thinking), timeout=timeout)
    if getattr(r, "status_code", 200) >= 400:
        import aiguard   # 2026-10-30: 충전 부족·키 오류는 기록 + 하루 한 번 텔레그램(10/30 하루 종일 모르고 지나감)
        aiguard.note(getattr(r, "status_code", None), str(getattr(r, "text", "")))
        raise RuntimeError(f"HTTP {r.status_code}: {str(getattr(r, 'text', ''))[:200]}")
    j = r.json()
    try:
        import aiguard
        aiguard.ok()
    except Exception:  # noqa: BLE001
        pass
    text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    u = j.get("usage") or {}
    tin, tout = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
    if not text.strip():  # 빈 답: 이유를 알려 줌(생각에 한도를 다 씀 · 거절 등) — 요금은 이미 나갔으니 기록
        _add_spend(cost_usd(model, tin, tout), kind, tin, tout)
        why = j.get("stop_reason")
        think = (u.get("output_tokens_details") or {}).get("thinking_tokens")
        raise RuntimeError(f"빈 답(멈춘 이유 {why}, 출력 {tout}토큰 중 생각 {think}) — " +
                           ("생각에 한도를 다 썼어요(max_tokens 를 늘리거나 effort 를 낮추세요)" if why == "max_tokens" else "블록 " + str([b.get("type") for b in j.get("content", [])])))
    return text, tin, tout


def _body(model: str, max_out: int, system: str, prompt: str, effort: str | None, thinking: dict | None) -> dict:
    b = {"model": model, "max_tokens": max_out, "system": system, "messages": [{"role": "user", "content": prompt}]}
    if thinking:
        b["thinking"] = thinking
    if effort:
        b["output_config"] = {"effort": effort}
    return b


# ---------------------------------------------------------------- 실행
def run(today: date | None = None, scan: dict | None = None, out=print, post=None, force: bool = False) -> dict:
    """하루 한 번 판단. 결과 {ok, n, cost_usd, msg}."""
    today = today or date.today()
    if not getattr(config, "AI_PICK_ENABLED", True) and not force:
        return {"ok": False, "msg": "AI PICK 꺼짐(관리 모드)"}
    model = getattr(config, "AI_PICK_MODEL", "claude-sonnet-5-5")
    with closing(db.connect()) as conn:
        for d in DDL:
            conn.execute(d)
        if not force and conn.execute("SELECT 1 FROM ai_pick WHERE date=? LIMIT 1", (today.isoformat(),)).fetchone():
            return {"ok": True, "msg": "오늘 이미 판단함", "n": 0}
        cands = candidates(conn, scan)
        if not cands:
            return {"ok": False, "msg": "판단할 종목이 없어요(PICK·종합 순위 비어 있음)"}
        try:
            import regsho
            rs = regsho.streaks(conn)
        except Exception:  # noqa: BLE001
            rs = {}
    refresh_events([c["ticker"] for c in cands], out=out)
    with closing(db.connect()) as conn:
        briefs = [brief(conn, c, rs) for c in cands]
    prompt = (f"오늘 {today.isoformat()} (미국 동부 기준 전 거래일 종가까지). 종목 {len(briefs)}개 요약 — 키: t 티커, src 출처(PICK/순위), "
              "pick(status 유력·가능·대기, target_name 회사 목표, pct 목표까지 %, imm_days 기한까지 일, pressure 압박 점수, runway 개월, why 근거), "
              "rank(pos 종합 순위, score 점수, parts 구성), px(last 종가, d1·d5·d20·d60 등락 %, rsi, flow 수급, dv20k 20일 평균 거래대금 천$), "
              "dil 희석 판정, filings 최근 30일 공시, events 일정(D-n 남은 일), deals 최근 180일 자금조달, sell_open 사모 주식 매도 가능일, news 최근 7일, "
              "insider_buy 내부자 매수, short(si_pct 공매도 %, dtc 커버 일수, float_m 유통 백만주), ftd(ftd_k 결제 실패 천 주, ftd_date — 많고 최근이면 숏 압박), snap(win 승률 점수, squeeze 스퀴즈 점수, buy_press 매수 압력, vol_x 거래량 배수), "
              "reverse_splits_2y 2년 병합 횟수, s3_tier 3대 조건 검증 순위(1이 최고), regsho_days Reg SHO 연속일, forensic 덕구 공시분석 요약(🔴 높음 🟠 주의 🟢 양호).\n"
              + "\n".join(json.dumps(b, ensure_ascii=False, separators=(",", ":")) for b in briefs))
    est = estimate_usd(model, prompt, 16000)
    left = budget_left_krw()
    if est * FX > left:
        msg = f"이번 달 AI 예산이 부족해 건너뜀(남은 {left:,.0f}원 · 예상 {est * FX:,.0f}원) — 관리 모드에서 예산을 올릴 수 있어요"
        out(msg)
        return {"ok": False, "msg": msg}
    text, tin, tout = call_claude(prompt, model, 16000, post, effort="medium", kind="pick")
    usd = cost_usd(model, tin, tout)
    _add_spend(usd, "pick", tin, tout)
    picks = parse(text)
    pmap = {b["t"]: (b.get("px") or {}).get("last") for b in briefs}
    known = set(pmap)
    picks = [p for p in picks if p["ticker"] in known]  # 보낸 적 없는 티커(지어낸 것)는 버림
    with closing(db.connect()) as conn:
        conn.execute("DELETE FROM ai_pick WHERE date=?", (today.isoformat(),))
        conn.execute("DELETE FROM ai_pick_sig WHERE date=?", (today.isoformat(),))  # 같은 날 다시 판단하면 그날 기록은 새 판단으로(하루 판단은 하나)
        conn.executemany("INSERT INTO ai_pick VALUES (?,?,?,?,?,?,?,?,?)",
                         [(today.isoformat(), p["ticker"], p["rank"], p["timing"], p["confidence"], p["reason"], p["risk"], pmap.get(p["ticker"]), model) for p in picks])
        recent = {r[0] for r in conn.execute("SELECT ticker FROM ai_pick_sig WHERE date >= ?", ((today - timedelta(days=SIG_GAP)).isoformat(),))}
        n_sig = 0
        for p in picks[:SIG_TOP]:
            if p["ticker"] not in recent and pmap.get(p["ticker"]):
                conn.execute("INSERT OR IGNORE INTO ai_pick_sig VALUES (?,?,?,?,?,?)", (today.isoformat(), p["ticker"], pmap[p["ticker"]], p["confidence"], p["timing"], p["rank"]))
                n_sig += 1
        conn.commit()
    try:  # 🧾 상위 5개 중 최근 공시분석이 없는 종목은 대기열에(다음 아침부터 서버가 깊게 읽음)
        import forensic
        import forensic_ai
        with closing(db.connect()) as conn:
            need = [p["ticker"] for p in picks[:5] if not forensic_ai.latest_brief(conn, p["ticker"])]
        if need:
            forensic.queue_add(need)
    except Exception:  # noqa: BLE001
        pass
    db.set_meta("ai_pick_last", json.dumps({"date": today.isoformat(), "model": model, "in": tin, "out": tout, "usd": round(usd, 4), "n": len(picks),
                                            "sent": len(briefs), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, ensure_ascii=False))
    msg = f"AI PICK: {len(briefs)}종목 판단 → 상위 {len(picks)} · 성과 공표 새 기록 {n_sig} · 비용 ${usd:.3f}(약 {usd * FX:,.0f}원) · 이번 달 {spent_usd() * FX:,.0f}원"
    out(msg)
    return {"ok": True, "n": len(picks), "cost_usd": usd, "msg": msg}


def latest(conn) -> tuple[list[dict], dict]:
    """가장 최근 판단 + 직전 판단의 순위(변동 ▲▼용)."""
    for d in DDL:
        conn.execute(d)
    ds = [r[0] for r in conn.execute("SELECT DISTINCT date FROM ai_pick ORDER BY date DESC LIMIT 2")]
    if not ds:
        return [], {}
    cur = [dict(zip(["date", "ticker", "rank", "timing", "confidence", "reason", "risk", "price", "model"], r))
           for r in conn.execute("SELECT * FROM ai_pick WHERE date=? ORDER BY rank", (ds[0],))]
    prev = {r[0]: r[1] for r in conn.execute("SELECT ticker, rank FROM ai_pick WHERE date=?", (ds[1],))} if len(ds) > 1 else {}
    return cur, prev


if __name__ == "__main__":
    import sys
    import quiet  # noqa: F401
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    config.apply_overrides()
    r = run(force="--force" in sys.argv)  # 결과 메시지는 run 이 한 번 출력
    if not r.get("ok"):
        sys.exit(1)
