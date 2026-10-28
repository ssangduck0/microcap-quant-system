"""🏁 종합 순위 — 신호 강도 × 출발 임박도로 모든 후보에 순위를 매긴다(예: 곧 출발할 종목을 몇 주 뒤 종목보다 위로).

강도(0~100) = 매집 25% + 회사 압박 20% + 스퀴즈 20% + 멀티 시그널 15% + 공시 호재 10% + 내부자 매수 10%
             − ATM·ELOC 열림 15 − 최근 30일 희석 서류(424B·S-1·F-1·S-3·F-3·EFFECT) 15 − 최근 3일 악재 공시 10
임박도: 최근 2일 강한 매집·오늘 장마감 BEST/후보·오늘 애프터 진입·3일 안 일정·Reg SHO 10~12일째 → 100(⏱ 3일 이내)
        4~14일 안 일정·Reg SHO 13일↑ → 60(⏱ 1~2주) · 매집만 → 25(⏱ 수주) · 그 외 10(⏱ 미정)
종합 = 강도 × 0.7 + 임박도 × 0.3. 규칙 기반 추정이며 매수·매도 권유가 아니다.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import date, timedelta

import pandas as pd

import db

LABEL = {100: "⏱ 3일 이내", 60: "⏱ 1~2주", 25: "⏱ 수주", 10: "⏱ 미정"}
DIL = ("424B", "S-1", "F-1", "S-3", "F-3", "EFFECT")


def _q(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001
        return []


def compute(today: date | None = None) -> pd.DataFrame:
    import multisignal
    today = today or date.today()
    d3, d14, d30 = (today + timedelta(days=3)).isoformat(), (today + timedelta(days=14)).isoformat(), (today - timedelta(days=30)).isoformat()
    ms = multisignal.collect()
    with closing(db.connect()) as conn:
        acc_w = {r[0]: json.loads(r[1]) for r in _q(conn, "SELECT ticker, data FROM accum WHERE period='주간' AND date=(SELECT MAX(date) FROM accum)")}
        acc_d = {r[0]: json.loads(r[1]) for r in _q(conn, "SELECT ticker, data FROM accum WHERE period='일간' AND date=(SELECT MAX(date) FROM accum)")}
        try:
            import squeeze
            sq = {r["ticker"]: r["score"] for r in squeeze.rows()}
        except Exception:  # noqa: BLE001
            sq = {}
        try:
            import regsho
            sho = regsho.streaks(conn)
        except Exception:  # noqa: BLE001
            sho = {}
        ins = {}
        for t, v in _q(conn, "SELECT ticker, SUM(value) FROM insider_tx WHERE code='P' AND date >= ? GROUP BY ticker", (d30,)):
            ins[t] = v or 0
        news: dict[str, list] = {}
        for t, s in _q(conn, "SELECT ticker, sentiment FROM sec_feed WHERE COALESCE(filed, substr(updated,1,10)) >= ?", ((today - timedelta(days=3)).isoformat(),)):
            news.setdefault(t, []).append(s)
        dil_recent = {r[0] for r in _q(conn, "SELECT DISTINCT ticker FROM sec_hist WHERE filed >= ? AND (" + " OR ".join("form LIKE ?" for _ in DIL) + ")", (d30, *[f"{x}%" for x in DIL]))}
        dil_recent |= {r[0] for r in _q(conn, "SELECT DISTINCT ticker FROM sec_feed WHERE COALESCE(filed, substr(updated,1,10)) >= ? AND (" + " OR ".join("form LIKE ?" for _ in DIL) + ")",
                                          (d30, *[f"{x}%" for x in DIL]))}
        ev = {}
        for t, d, k, ti in _q(conn, "SELECT ticker, date, kind, title FROM events WHERE date >= ? AND date <= ?", (today.isoformat(), d14)):
            ev.setdefault(t, []).append((d, k, ti))
        close_today = set()
        try:
            import closewatch as cw
            for t, m in _q(conn, "SELECT w.ticker, s.metrics FROM close_watchlist w JOIN close_state s ON s.date=w.date AND s.ticker=w.ticker WHERE w.kind='frozen' AND w.date >= ?",
                           ((today - timedelta(days=1)).isoformat(),)):
                if m and cw.evaluate(json.loads(m))["grade"] in ("BEST", "후보"):
                    close_today.add(t)
        except Exception:  # noqa: BLE001
            pass
        after_today = {r[0] for r in _q(conn, "SELECT ticker FROM after_signals WHERE date >= ?", ((today - timedelta(days=1)).isoformat(),))}
        dil_status = {r[0]: r[1] for r in _q(conn, "SELECT ticker, dilution_status FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots)")}
        evt, evs = None, {}
        try:  # 🧮 과거 성과 기반 공시 점수(검증 통과 때만) — 아니면 예전 호재/악재 규칙
            import evscore
            evt = evscore.active()
            if evt:
                px = {r[0]: r[1] for r in _q(conn, "SELECT ticker, price FROM daily_snapshots WHERE date=(SELECT MAX(date) FROM daily_snapshots)")}
                evs = evscore.recent(conn, evt, px, days=5, today=today)
        except Exception:  # noqa: BLE001
            evt, evs = None, {}
        try:
            import pressure
            cand = set(pressure.candidates(conn))
        except Exception:  # noqa: BLE001
            cand = set()
        universe = set(acc_w) | set(acc_d) | {t for t, s in sq.items() if s >= 30} | set(sho) | set(ins) | set(news) | set(evs) | close_today | after_today | cand
        rows = []
        for t in sorted(universe):
            pr = None
            if t in cand:
                try:
                    pr = pressure.evaluate(t, conn, None, None)
                except Exception:  # noqa: BLE001
                    pr = None
            a = acc_w.get(t) or acc_d.get(t)
            c_acc = min(100.0, (a["score"] / 11 * 100) if a else 0.0)
            c_pr = (pr["score"] / 10 * 100) if pr else 0.0
            c_sq = float(sq.get(t) or 0.0)
            c_ms = min(100.0, len(ms.get(t, [])) * 20.0)
            ns = news.get(t, [])
            ev_best = ev_worst = None
            if evt:  # 최근 5일 공시 중 과거 성과가 가장 좋은 것(가산)·가장 나쁜 것(감점)
                sc = evs.get(t, [])
                ev_best = max(sc, default=None)
                ev_worst = min(sc, default=None)
                c_news = min(100.0, max(0.0, ev_best[0] * 12.5)) if ev_best else 0.0   # +8%p → 100
                if c_news and "악재" in ns:  # 같은 기간에 악재 서류(희석 등)도 있으면 가산 안 함
                    c_news = 0.0
            else:
                c_news = 100.0 if "호재" in ns else 60.0 if "약한 호재" in ns else 0.0
            v = ins.get(t, 0)
            c_ins = 100.0 if v >= 100_000 else 60.0 if v >= 20_000 else 30.0 if v > 0 else 0.0
            import config as _cf
            _w = [_cf.RANK_W_ACC, _cf.RANK_W_PR, _cf.RANK_W_SQ, _cf.RANK_W_MS, _cf.RANK_W_NEWS, _cf.RANK_W_INS]
            _sw = sum(_w) or 1.0  # 비중 합이 1이 아니어도 비율로 맞춤
            strength = sum(w * v for w, v in zip(_w, (c_acc, c_pr, c_sq, c_ms, c_news, c_ins))) / _sw
            why, risk = [], []
            if a:
                why.append(f"매집 {a['level']} 합계 {a['score']:g}(흡수일 {a['n_absorb']}일)")
            if pr and pr["score"]:
                why.append(f"회사 압박 {pr['score']:g}점({', '.join(pr['parts'])})")
            if c_sq >= 30:
                why.append(f"스퀴즈 {c_sq:.0f}점")
            if ms.get(t):
                why.append(f"멀티 시그널 {len(ms[t])}개({', '.join(ms[t][:4])})")
            if c_news and evt:
                why.append(f"최근 5일 공시 과거 성과 좋음 {ev_best[0]:+.1f}%p({ev_best[1]})")
            elif c_news:
                why.append("최근 3일 호재 공시")
            if v:
                why.append(f"내부자 매수 ${v:,.0f}(30일)")
            try:
                import shares as _sh
                _to = _sh.turnover(t, conn=conn)   # 2026-10-28: 같은 연결 재사용(연결마다 열면 2,200종목에 수 초)
                if _to and _to["pct"] >= 100:
                    why.append(f"회전율 {_to['pct']:.0f}% — 하루에 주식 전체가 한 번 넘게 손바뀜")
            except Exception:  # noqa: BLE001
                pass
            # 🔬 ⑥ 직전 분기 주식수 변동(SEC 표지 이력, 2026-10-28 검증 docs/studies: +20% 초과는 60일 중앙값 −16%·급락 터치 52%, 20% 이내 −5%·35%, 급등 기회는 같음)
            # 본 점수(score)는 그대로 두고 표시(칩) + 변형 점수(score6: ❌ −10 · ⚠️ −5, 희석 감점이 이미 있으면 절반)만 만든다 → 🧪 가상매매 '🏁 순위(⑥ 반영)' 전략으로 4주 비교 뒤 감점 여부 결정(사용자 결정 10/28)
            sc6, cls6 = None, None
            try:
                sc6 = _sh.change(t, conn)
                if sc6:
                    _p6 = round(sc6["pct"], 6)
                    cls6 = "bad" if _p6 > 20 else "warn" if _p6 > 10 else "ok"
            except Exception:  # noqa: BLE001
                sc6, cls6 = None, None
            dil_pen = False
            if dil_status.get(t) in ("ATM", "ELOC") or (pr and pr.get("atm_open")):
                strength -= 15
                risk.append("ATM·ELOC 열림")
                dil_pen = True
            if t in dil_recent:
                strength -= 15
                risk.append("최근 30일 희석 서류")
                dil_pen = True
            penalized = False
            if evt and ev_worst and ev_worst[0] < -1:  # −1%p 넘게 나쁜 칸만 감점(−7.5%p 이하면 최대 15)
                strength -= min(15.0, -ev_worst[0] * 2)
                risk.append(f"최근 5일 공시 과거 성과 나쁨 {ev_worst[0]:+.1f}%p({ev_worst[1]})")
                penalized = True
            if "악재" in ns and not penalized:  # 점수표로 감점 안 된 악재(투자설명서 등 8-K 가 아닌 서류 포함)는 예전 규칙
                strength -= 10
                risk.append("최근 3일 악재 공시")
            strength = max(0.0, min(100.0, strength))
            pen6 = 10.0 if cls6 == "bad" else 5.0 if cls6 == "warn" else 0.0
            if pen6 and dil_pen:   # ATM·ELOC·희석 서류 감점이 이미 있으면 절반(이중 감점 방지)
                pen6 /= 2
            strength6 = max(0.0, strength - pen6)
            u, when = 10, []
            ad = acc_d.get(t)
            if ad and ad.get("n_strong"):
                u, when = 100, when + [f"최근 강한 매집({ad['top_day']})"]
            if t in close_today:
                u, when = 100, when + ["장마감 체크리스트 BEST·후보"]
            if t in after_today:
                u, when = 100, when + ["애프터 진입 신호"]
            n = sho.get(t)
            if n and 10 <= n < 13:
                u, when = 100, when + [f"Reg SHO {n}일째 — 13일 강제 상환까지 {13 - n}일"]
            elif n and n >= 13 and u < 60:
                u, when = 60, when + [f"Reg SHO {n}일째(강제 상환 구간)"]
            for d, k, ti in sorted(ev.get(t, [])):
                dd = (date.fromisoformat(d) - today).days
                if d <= d3:
                    u = 100
                    when.append(f"D-{dd} {k}")
                elif u < 60:
                    u = 60
                    when.append(f"D-{dd} {k}")
            if u == 10 and a:
                u = 25
            total = round(strength * _cf.RANK_W_STRENGTH + u * (1 - _cf.RANK_W_STRENGTH), 1)
            rows.append({"ticker": t, "score": total, "score6": round(strength6 * _cf.RANK_W_STRENGTH + u * (1 - _cf.RANK_W_STRENGTH), 1),
                         "share_pct": (round(sc6["pct"], 1) if sc6 else None), "share_cls": cls6, "share_d": (f"{sc6['d0']}→{sc6['d1']}" if sc6 else None),
                         "strength": round(strength, 1), "urgency": u, "when": LABEL[u], "why": why, "when_why": when[:3], "risk": risk,
                         "parts": {"매집": round(c_acc), "압박": round(c_pr), "스퀴즈": round(c_sq), "멀티": round(c_ms), "공시": round(c_news), "내부자": round(c_ins)}})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["score", "urgency"], ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    df["top_pct"] = [max(1, int(round(r / len(df) * 100))) for r in df["rank"]]  # 순위 대상 중 상위 몇 %(1위가 50점대여도 위치가 보이게)
    df["rank6"] = 0
    df.loc[df.sort_values(["score6", "urgency"], ascending=False).index, "rank6"] = range(1, len(df) + 1)   # ⑥ 반영 순위(가상매매 비교용)
    return df
