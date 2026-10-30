"""🏆 성과 공표 — 시스템의 모든 예측을 같은 기준으로 성공·실패 판정해 일간·주간·월간·연간으로 쌓는다(스캐너 개선용 근거 데이터).

예측(신호)마다: 진입가(신호 때 기록된 가격, 없으면 신호일 종가) → 신호일 다음 거래일부터 기간(horizon) 동안의 일봉으로
  오를 신호: 기간 안 최고가 ≥ 진입가 × (1 + 목표%) 이면 성공, 기간이 끝났는데 못 닿으면 실패, 아직이면 대기
  내릴 신호(청산·분산): 기간 뒤 종가 < 진입가 이면 성공(신호대로 내려감), 아니면 실패
  애프터 스캘핑: 분봉 기준 +5%가 -5%보다 먼저 닿았으면 성공(스캐너가 기록한 결과 사용)
결과는 pred_outcomes 에 저장(매일 아침 갱신 작업 + 화면 버튼). 일봉 기준이라 체결 비용·호가 간격은 반영되지 않는다.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

import db

SOURCES = {  # 키: (이름, 방향 +1 오름/-1 내림, 목표 %, 기간 거래일)
    "close": ("🎯 장마감 체크리스트(BEST·후보)", 1, 10.0, 1),
    "score": ("📊 승률 점수 상위(≥70점)", 1, 10.0, 1),
    "shortflow_up": ("🩳 공매도 흐름 ②③(진입·커버)", 1, 10.0, 5),
    "shortflow_exit": ("🩳 공매도 흐름 ④(청산)", -1, 0.0, 5),
    "flow_up": ("📈 털기·털기 확인", 1, 10.0, 5),
    "flow_down": ("📈 분산·털기 실패", -1, 0.0, 5),
    "after": ("🌙 애프터 진입 구간", 1, 5.0, 0),
    "setup": ("🕵️ 강한 셋업(+4 이상)", 1, 30.0, 20),
    "piggy": ("🐷 저금통 저점 구간", 1, None, 10),
    "rsplit": ("🔁 병합 후 레이더", 1, 20.0, 10),
    "pick_strong": ("🎯 PICK 강한 목표(상장유지·워런트·시총)", 1, None, 60),
    "pick_bs": ("🎯 PICK baby shelf 목표(약한 목표)", 1, None, 60),
    "setup3": ("✅ 스승님 3대 조건(돈·지지·희석 없음)", 1, 30.0, 10),
    "scr": ("📇 스크리너 카드(외부·직접 후보)", 1, 30.0, 20),   # 남이 추천하거나 직접 넣은 종목 — 추천이 맞는지 검증
    "ai_hi": ("🤖 AI PICK · 확신 높음", 1, 30.0, 20),   # Claude 판단 상위 10 · 20거래일 안 +30%
    "ai_mid": ("🤖 AI PICK · 확신 중간", 1, 30.0, 20),
    "ai_lo": ("🤖 AI PICK · 확신 낮음", 1, 30.0, 20),
    "s3_t1": ("⭐ 1순위 · RSI≤20 + 희석 없음", 1, 30.0, 40),   # 반등형(기본 40거래일 안 +30%, 관리 모드에서 변경)
    "s3_t2": ("2순위 · RSI≤25 + 희석 없음", 1, 30.0, 40),
    "s3_t3": ("3순위 · 과매도 + 희석 없음(참고)", 1, 30.0, 40),
    "cx_si_up": ("📡 공매도 잔고 보고 +30%↑(ChartExchange)", 1, 30.0, 10),      # 숏이 급히 쌓인 뒤 10거래일 안 +30%(스퀴즈 가설) — 신호일 = 자료 받은 날
    "cx_ftd_spike": ("📡 FTD 급증(20일 평균 3배↑)", 1, 30.0, 10),
    "toxic_drop": ("⚠️ 대폭 할인 전환(40%↑) → 60일 안 −50%", -1, 50.0, 60),     # 내림 예측: 저가가 −50% 에 닿으면 성공(OMH 패턴 검증)
    "toxic_bottom": ("⚠️ 할인 전환 바닥(계약 뒤 −70%) 반등", 1, 30.0, 20),
    # 📐 스승 관점(2026-10-27, docs/chart_masters.md) — 신호일 = 기록한 날(그날까지 자료만)
    "chart_pullback": ("📐 급등 후 눌림 타점(무릎~허리 지지)", 1, 10.0, 5),
    # 🎲 매매 전 시뮬레이션(2026-10-29): 판정별로 같은 목표(+30% · 40거래일)를 재서 "🟢 가 정말 더 잘됐나"를 봄. 🔴 는 "못 간다"는 뜻이라 성공률이 낮게 나와야 맞음
    "presim_g": ("🎲 매매 전 시뮬레이션 🟢 유리", 1, 30.0, 40),
    "presim_c": ("🎲 매매 전 시뮬레이션 🪙 동전", 1, 30.0, 40),
    "presim_r": ("🎲 매매 전 시뮬레이션 🔴 불리(낮아야 맞음)", 1, 30.0, 40),
    # 보강 C(C안 2026-10-30): '오늘과 같은 장세 날만' 판정 — 위의 2년 전체 판정과 같은 목표로 재서 어느 쪽이 더 잘 맞는지 2~3주 뒤 비교(docs/TASK_presim.md 12절)
    "presim_rg": ("🎲 시뮬레이션(장세 반영) 🟢 유리", 1, 30.0, 40),
    "presim_rc": ("🎲 시뮬레이션(장세 반영) 🪙 동전", 1, 30.0, 40),
    "presim_rr": ("🎲 시뮬레이션(장세 반영) 🔴 불리(낮아야 맞음)", 1, 30.0, 40),
    "chart_h60": ("📐 60분봉 200선 돌파 지지", 1, 20.0, 10),
    "chart_gc": ("📐 일봉 5/20 골든크로스", 1, 20.0, 10),
    "chart_turn": ("📐 연속 하락 뒤 전환(ANO)", 1, 10.0, 5),
    "chart_top": ("📐 고점 윗꼬리 캔들 → 5일 안 하락", -1, 0.0, 5),
    "chart_life": ("📐 생명선 이탈 → 5일 안 하락", -1, 0.0, 5),
}
CHART_SRC = {"pullback": "chart_pullback", "h60_200": "chart_h60", "gc520": "chart_gc", "turn3": "chart_turn", "top_candle": "chart_top", "life_break": "chart_life"}
SCORE_MIN = 70.0
DDL = """CREATE TABLE IF NOT EXISTS pred_outcomes (source TEXT NOT NULL, date TEXT NOT NULL, ticker TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '',
          entry REAL, max_up REAL, max_down REAL, close_h REAL, bars INTEGER, status TEXT, updated_at TEXT, PRIMARY KEY (source, date, ticker, ref))"""


def _q(conn, sql: str, params: tuple = ()) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    except Exception:  # noqa: BLE001  (아직 없는 테이블)
        return []


def collect(conn) -> pd.DataFrame:
    """모든 출처의 예측을 한 표로: source, date, ticker, ref, entry(없으면 None), target, horizon, direction, note."""
    rows = []

    def add(src, d, t, entry=None, ref="", note="", target=None, horizon=None):
        name, direction, tgt, hz = SOURCES[src]
        rows.append({"source": src, "출처": name, "date": d, "ticker": t, "ref": ref, "entry": entry, "target": target if target is not None else tgt,
                     "horizon": horizon if horizon is not None else hz, "direction": direction, "note": note})
    try:
        import closewatch as cw
        for r in _q(conn, "SELECT w.date, w.ticker, w.rank, s.metrics FROM close_watchlist w LEFT JOIN close_state s ON s.date=w.date AND s.ticker=w.ticker WHERE w.kind='frozen'"):
            if r["metrics"]:
                g = cw.evaluate(json.loads(r["metrics"]))["grade"]
                if g in ("BEST", "후보"):
                    add("close", r["date"], r["ticker"], note=f"{g} · 토스 {r['rank']}위")
    except Exception:  # noqa: BLE001
        pass
    for r in _q(conn, "SELECT date, ticker, win_score, price FROM daily_snapshots WHERE win_score >= ?", (SCORE_MIN,)):
        add("score", r["date"], r["ticker"], note=f"종합 {r['win_score']:.0f}점")
    for r in _q(conn, "SELECT date, ticker, stage, price FROM shortflow_events"):
        add("shortflow_exit" if r["stage"].startswith("④") else "shortflow_up", r["date"], r["ticker"], r["price"], ref=r["stage"][:1], note=r["stage"])
    for r in _q(conn, "SELECT date, ticker, kind, price FROM flowread_events"):
        down = r["kind"].startswith(("🔻", "⚠️"))
        add("flow_down" if down else "flow_up", r["date"], r["ticker"], r["price"], ref=r["kind"][:2], note=r["kind"])
    for r in _q(conn, "SELECT date, ticker, price, first_hit, exit_price FROM after_signals"):
        add("after", r["date"], r["ticker"], r["price"], note=r["first_hit"] or "")
    for r in _q(conn, "SELECT ticker, date, price, score FROM setup_first WHERE score >= 4"):
        add("setup", r["date"], r["ticker"], r["price"], note=f"+{r['score']} 신호")
    for r in _q(conn, "SELECT date, ticker, price, box_high FROM piggy_events"):
        tgt = (r["box_high"] / r["price"] - 1) * 100 if r["price"] and r["box_high"] else 10.0
        add("piggy", r["date"], r["ticker"], r["price"], note=f"박스 상단 ${r['box_high']:.4f}" if r["box_high"] else "", target=max(tgt, 1.0))
    for r in _q(conn, "SELECT date, ticker, target_name, target, price, pct, status, weak FROM pick_signals"):  # 목표가 도달 = 성공(목표 %는 신호마다 다름)
        add("pick_bs" if r["weak"] else "pick_strong", r["date"], r["ticker"], r["price"], ref=r["target_name"][:12],
            note=f"{r['target_name']} ${r['target']:.4f} · {r['status']}", target=max(r["pct"] or 1.0, 1.0))
    for r in _q(conn, "SELECT filed, ticker, kind, discount_pct, note FROM toxic_deals WHERE level='악성'"):   # ⚠️ 할인 전환 → 폭락 검증
        add("toxic_drop", r["filed"], r["ticker"], note=f"{r['kind']} 할인 {r['discount_pct'] or 0:.0f}%")
    try:
        import toxic
        for r in toxic.bottom_signals(conn):
            add("toxic_bottom", r["date"], r["ticker"], r["price"], note=r["note"])
    except Exception:  # noqa: BLE001
        pass
    for r in _q(conn, "SELECT date, ticker, kind, value, note FROM cx_signals"):   # 📡 ChartExchange 숏 신호(진입가 = 신호일 종가는 update 가 채움)
        add("cx_si_up" if r["kind"] == "si_up" else "cx_ftd_spike", r["date"], r["ticker"], note=r["note"] or "")
    for r in _q(conn, "SELECT date, ticker, price, source FROM screener_sig"):
        add("scr", r["date"], r["ticker"], r["price"], note=r["source"] or "")
    for r in _q(conn, "SELECT date, ticker, price, confidence, timing, rank FROM ai_pick_sig"):
        import config as _cfgA
        add({"높음": "ai_hi", "중간": "ai_mid"}.get(r["confidence"], "ai_lo"), r["date"], r["ticker"], r["price"], note=f"{r['rank']}위 · {r['timing']}",
            horizon=int(_cfgA.AI_PICK_HORIZON))
    for r in _q(conn, "SELECT date, ticker, price, tier, rsi, note FROM s3_tier_signals"):
        import config as _cfgT  # 반등형: 보유 기간·익절 % 는 관리 모드 설정(기본 20거래일 안 +30%)
        add(f"s3_t{int(r['tier'])}", r["date"], r["ticker"], r["price"], note=(f"RSI {r['rsi']:.0f}" if r["rsi"] is not None else "") + f" · 반등형 {_cfgT.TIER_HOLD_DAYS}일",
            target=float(_cfgT.TIER_TARGET), horizon=int(_cfgT.TIER_HOLD_DAYS))
    for r in _q(conn, "SELECT date, ticker, kind, price, note FROM chart_signals"):   # 📐 스승 관점
        if r["kind"] in CHART_SRC:
            add(CHART_SRC[r["kind"]], r["date"], r["ticker"], entry=r["price"], note=r["note"] or "")
    for r in _q(conn, "SELECT date, ticker, price, strong, note FROM setup3_signals"):  # 10거래일 안 +30% = 성공(타임머신과 같은 기준)
        add("setup3", r["date"], r["ticker"], r["price"], note=("💰 강한 유입 · " if r["strong"] else "") + (r["note"] or "")[:60])
    for r in _q(conn, "SELECT date, ticker, price, success_pct, n FROM rs_signals"):
        add("rsplit", r["date"], r["ticker"], r["price"], note=f"유사 {r['n']}건 · 성공률 {r['success_pct']:.0f}%")
    try:  # 🎲 매매 전 시뮬레이션: 같은 날 같은 종목은 출처(저금통>PICK>순위) 하나만 기록되므로 그대로
        _pv = {"🟢": "presim_g", "🪙": "presim_c", "🔴": "presim_r"}
        for r in _q(conn, "SELECT day, ticker, entry, verdict, p_tp, p_sl, own_p_tp, own_p_sl, key, source FROM presim_log"):
            src = _pv.get(r["verdict"])
            if src:
                p_tp = r["p_tp"] if r["p_tp"] is not None else r["own_p_tp"]
                p_sl = r["p_sl"] if r["p_sl"] is not None else r["own_p_sl"]
                add(src, r["day"], r["ticker"], r["entry"], note=f"{r['source']} · 익절 {p_tp:.0f}% · 손절 {p_sl:.0f}% ({r['key']})" if p_tp is not None else str(r["source"]))
    except Exception:  # noqa: BLE001  (표가 아직 없음)
        pass
    try:  # 보강 C: 장세 판정(verdict_reg 열이 생긴 뒤 기록부터) — ❔(표본 부족·기록 없음)은 빼고
        _pr = {"🟢": "presim_rg", "🪙": "presim_rc", "🔴": "presim_rr"}
        for r in _q(conn, "SELECT day, ticker, entry, verdict_reg, regime, ev_reg, n_eff_reg, key, source FROM presim_log WHERE verdict_reg IN ('🟢','🪙','🔴')"):
            add(_pr[r["verdict_reg"]], r["day"], r["ticker"], r["entry"],
                note=f"{r['source']} · 장세 {r['regime'] or '-'} · 기대값 {r['ev_reg'] if r['ev_reg'] is not None else '-'}% · 표본 {r['n_eff_reg'] or 0:.0f} ({r['key']})")
    except Exception:  # noqa: BLE001  (열이 아직 없음)
        pass
    return pd.DataFrame(rows)


def outcome(df: pd.DataFrame | None, day: str, entry: float | None, horizon: int, direction: int, target: float) -> dict:
    if df is None or df.empty:
        return {"status": "대기", "bars": 0}
    d = df.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    if entry is None or pd.isna(entry) or entry <= 0:  # 기록된 가격이 없으면(빈 값은 NaN 으로 들어옴) 신호일 종가
        on = d[d.index == pd.Timestamp(day)]
        if on.empty:
            return {"status": "대기", "bars": 0}
        entry = float(on["Close"].iloc[-1])
    a = d[d.index > pd.Timestamp(day)].head(horizon)
    if a.empty:
        return {"status": "대기", "bars": 0, "entry": entry}
    mu, md = float((a["High"].max() / entry - 1) * 100), float((a["Low"].min() / entry - 1) * 100)
    ch = float((a["Close"].iloc[-1] / entry - 1) * 100)
    done = len(a) >= horizon
    if direction > 0:
        st = "성공" if mu >= target else ("실패" if done else "대기")
    elif target and target > 0:   # 내림 예측에 목표 % 가 있으면: 저가가 −목표% 에 닿으면 성공(toxic_drop)
        st = "성공" if md <= -target else ("실패" if done else "대기")
    else:
        st = ("성공" if ch < 0 else "실패") if done else "대기"
    return {"status": st, "bars": int(len(a)), "entry": entry, "max_up": mu, "max_down": md, "close_h": ch}


def pv_grace() -> int:
    import pricevault
    return pricevault.GONE_GRACE_DAYS


def settle_gone(o: dict, direction: int) -> dict:
    """주가가 끊긴(상장폐지·거래정지 추정) 종목의 '대기' 예측을 있는 데까지로 확정.
    오름 예측: 끊기기 전에 목표를 못 넘었으면 실패(사라진 종목은 보통 더 떨어진 뒤 사라짐). 내림 예측: 마지막 종가가 진입가보다 낮으면 성공."""
    o = dict(o)
    if direction > 0:
        o["status"] = "실패"  # 목표 도달이었다면 outcome 이 이미 '성공'
    else:
        o["status"] = "성공" if (o.get("close_h") is not None and o["close_h"] < 0) else "실패"
    o["gone"] = True
    return o


def after_outcome(r: dict, today: str) -> dict:
    hit = r.get("note") or ""
    if hit.startswith("목표"):
        return {"status": "성공"}
    if hit.startswith("손절") or (r["date"] < today):
        return {"status": "실패"}
    return {"status": "대기"}


def update(conn, today: date | None = None, out=print, download=None) -> dict:
    """대기 중인 예측의 결과를 일봉으로 계산해 저장."""
    import market
    conn.execute(DDL)
    conn.commit()
    today = today or date.today()
    p = collect(conn)
    if p.empty:
        return {"rows": 0, "updated": 0}
    # 끝난 결과는 다시 안 봄. 단 최고 상승 +150% 이상 '성공'은 병합 때문에 부풀었을 수 있어 다시 판정(진입가 병합 보정)
    done = {(r["source"], r["date"], r["ticker"], r["ref"]) for r in _q(conn, "SELECT source, date, ticker, ref FROM pred_outcomes WHERE status IN ('성공','실패') "
                                                                        "AND NOT (status='성공' AND COALESCE(max_up, 0) >= 150)")}
    p = p[[(s, d, t, rf) not in done for s, d, t, rf in zip(p["source"], p["date"], p["ticker"], p["ref"])]]
    p = p[p["date"] >= (today - timedelta(days=400)).isoformat()]
    need = sorted(set(p.loc[p["source"] != "after", "ticker"]))
    dl = download or (lambda tk: market.download_daily(tk, period="1y"))
    data: dict = {}
    for i in range(0, len(need), 100):
        data.update(dl(need[i:i + 100]))
    import pricevault as pv  # 🗄 못 받은 종목은 보관소 일봉으로 · 끊긴 종목은 마지막 가격으로 확정
    filled = pv.fill(data, need, conn)
    gone = pv.gone(conn)
    n = n_fix = n_gone = 0
    for r in p.to_dict("records"):
        if r["source"] == "after":
            o = after_outcome(r, today.isoformat())
        else:
            df = data.get(r["ticker"])
            entry, why = pv.fix_entry(r["ticker"], r["date"], r["entry"], df, conn)  # 병합 뒤 가격 단위 맞춤
            n_fix += bool(why)
            o = outcome(df, r["date"], entry, r["horizon"], r["direction"], r["target"])
            g = gone.get(r["ticker"])
            if g and o["status"] == "대기" and (g.get("detected") or "9999") <= (today - timedelta(days=pv_grace())).isoformat():
                # 주가가 끊긴 지 7일 넘게 그대로(거래정지가 풀리지 않음) → 평가 기간을 못 채운 채 있는 데까지로 확정
                o = settle_gone(o, r["direction"])
                n_gone += 1
        conn.execute("""INSERT OR REPLACE INTO pred_outcomes (source, date, ticker, ref, entry, max_up, max_down, close_h, bars, status, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (r["source"], r["date"], r["ticker"], r["ref"], o.get("entry", r["entry"]), o.get("max_up"), o.get("max_down"),
                                                             o.get("close_h"), o.get("bars"), o["status"], db.utcnow_iso()))
        n += 1
    conn.commit()
    out(f"성과 공표: 예측 {len(p):,}건 결과 갱신 · 보관소로 채움 {len(filled)}종목 · 병합 진입가 맞춤 {n_fix}건 · 주가 끊김 확정 {n_gone}건")
    return {"rows": int(len(p)), "updated": n}


def _with_probs(conn, m: pd.DataFrame) -> pd.DataFrame:
    """🧠 신호 승률 모델 확률(sig_prob: p30 = 10일 +30% · p10 = 5일 +10%)을 붙인다. 없으면 빈 열."""
    pr = pd.DataFrame(_q(conn, "SELECT source, date, ticker, p30, p10 FROM sig_prob"))
    if m.empty or pr.empty:
        m["p30"], m["p10"] = None, None
        return m
    return m.merge(pr, on=["source", "date", "ticker"], how="left")


def table(conn) -> pd.DataFrame:
    """예측 + 결과(없으면 대기) + 🧠 AI 확률."""
    conn.execute(DDL)
    p = collect(conn)
    if p.empty:
        return p
    o = pd.DataFrame(_q(conn, "SELECT * FROM pred_outcomes"))
    if o.empty:
        p["status"] = "대기"
        for c in ("max_up", "max_down", "close_h", "bars"):
            p[c] = None
        return _with_probs(conn, p)
    m = p.merge(o.drop(columns=["updated_at"]), on=["source", "date", "ticker", "ref"], how="left", suffixes=("", "_o"))
    m["entry"] = m["entry"].fillna(m.get("entry_o"))
    m["status"] = m["status"].fillna("대기")
    return _with_probs(conn, m.drop(columns=[c for c in m.columns if c.endswith("_o")]))


def period_key(d: pd.Series, unit: str) -> pd.Series:
    t = pd.to_datetime(d)
    if unit == "일간":
        return t.dt.strftime("%Y-%m-%d")
    if unit == "주간":
        iso = t.dt.isocalendar()
        return iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    if unit == "월간":
        return t.dt.strftime("%Y-%m")
    return t.dt.strftime("%Y")


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("출처")
    s = pd.DataFrame({"신호": g.size(), "성공": g["status"].apply(lambda x: (x == "성공").sum()), "실패": g["status"].apply(lambda x: (x == "실패").sum()),
                      "대기": g["status"].apply(lambda x: (x == "대기").sum()), "평균 최고 상승(%)": g["max_up"].mean(), "평균 기간 끝 등락(%)": g["close_h"].mean()})
    s["성공률(%)"] = s["성공"] / (s["성공"] + s["실패"]).where(lambda x: x > 0) * 100
    s["성공률 범위(95%)"] = [wilson_text(int(k), int(k) + int(f)) for k, f in zip(s["성공"], s["실패"])]   # 2026-10-30: 표본이 작으면 성공률이 요동 → 신뢰구간을 옆에
    return s.reset_index()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """성공 k / 판정 n 의 성공률 95% 신뢰구간(윌슨, %). n=0 이면 None. 예: 5/10 → 24~76%, 50/100 → 40~60%."""
    if n <= 0:
        return None
    import math
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d * 100, (c + r) / d * 100)


def wilson_text(k: int, n: int) -> str:
    w = wilson(k, n)
    return "-" if w is None else f"{w[0]:.0f}~{w[1]:.0f}%"
