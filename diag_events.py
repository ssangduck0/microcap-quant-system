"""🔬 이벤트 연구 · 🧪 가상매매 점검 — 가중치를 조정하기 전에 실제로 쌓인 자료를 요약한다(읽기만 함, 아무것도 바꾸지 않음).

실행(프로젝트 폴더에서):  python diag_events.py
"""
import os
import sys

os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
import logging
try:
    import streamlit.logger as _stl
    _stl.set_log_level("error")
except Exception:  # noqa: BLE001
    pass
logging.getLogger().addFilter(lambda rec: not rec.name.startswith("streamlit"))

from contextlib import closing

import pandas as pd

import config
config.apply_overrides()
import db

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 22)


def show(df: pd.DataFrame, cols: list[str] | None = None, n: int = 12) -> None:
    if df is None or df.empty:
        print("    (없음)")
        return
    d = df[cols] if cols else df
    print("    " + d.head(n).round(1).to_string(index=False).replace("\n", "\n    "))


def main() -> None:
    import eventlab
    print(f"== 이벤트·가상매매 점검 · DB {config.DB_PATH}")
    with closing(db.connect()) as conn:
        eventlab.ensure_tables(conn)
        d = conn.execute("SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(filed), MAX(filed) FROM ev_docs").fetchone()
        l = conn.execute("SELECT COUNT(*), SUM(ret5 IS NOT NULL), MIN(day0), MAX(day0) FROM ev_labels").fetchone()
    print(f"\n[1] 수집: 공시 {d[0]:,}건 · {d[1]:,}종목 · {d[2]} ~ {d[3]}")
    print(f"    라벨(주가 반응 계산): {l[0]:,}건 · D+5 까지 끝난 것 {l[1] or 0:,}건 · {l[2]} ~ {l[3]}")

    df = eventlab.table()
    if df.empty:
        print("\n아직 라벨된 사건이 없어 통계를 낼 수 없어요. 끝.")
        return
    cols = ["type", "건수", "당일 상승 확률(%)", "+20% 이상 확률(%)", "D+5 초과수익(%)", "D+5 초과 중앙값(%)", "D+5 초과 절사평균(%)", "D+5 초과>0 확률(%)"]
    print("\n    ※ 초과수익(%) = 평균(극단값에 끌림) · 중앙값 · 절사평균(양 끝 5% 제외) — 판단은 중앙값·절사평균으로")
    print("\n[2] 사건 종류별 (절사평균 순, 5건 이상)")
    show(eventlab.stats(df, "type"), cols, 25)
    print("\n[3] 호재·악재 판정별")
    s = eventlab.stats(df, "sentiment", 1)
    show(s, ["sentiment"] + cols[1:])
    for lo, hi, nm in ((None, 1.0, "$1 미만"), (1.0, 5.0, "$1~5"), (5.0, None, "$5 이상")):
        sub = eventlab.table(min_price=lo, max_price=hi)
        print(f"\n[4] 가격대 {nm}: {len(sub):,}건 — 호재·악재별")
        show(eventlab.stats(sub, "sentiment", 1), ["sentiment"] + cols[1:])
    print("\n[5] 장중·장외 시점별")
    show(eventlab.stats(df, "timing", 1), ["timing"] + cols[1:])
    print("\n[5b] '호재' 공시만 — 시점별(장전 호재가 실제로 나은지)")
    show(eventlab.stats(df[df["sentiment"] == "호재"], "timing", 1), ["timing"] + cols[1:])
    print("\n[6] 가중치 제안(공시 호재 비중)")
    sg = eventlab.suggest(df)
    print("    " + ("\n    ".join(f"{x['key']}: {x['cur']} → {x['new']} · {x['why']}" for x in sg) if sg else "호재 사건이 30건 미만이라 아직 제안 없음"))

    import papertrade as pt
    t = pt.trades()
    sm = pt.summary(t)
    print(f"\n[7] 가상매매: 전체 {sm['n']}건 · 청산 {sm['closed']} · 보유 {sm['open']}"
          + ("" if sm["win"] is None else f" · 승률 {sm['win']:.0f}% · 평균 {sm['avg']:+.1f}% · 누적 {sm['ret']:+.1f}%"))
    if not t.empty:
        print(f"    기간: {t['day'].min()} ~ {t['day'].max()} · 장부 {t['book'].nunique()}개")
    print("    신호별(그 신호가 있었던 거래 vs 없었던 거래):")
    show(pt.by_signal(t), n=20)
    print("\n[8] 지금 순위 가중치: " + ", ".join(f"{k} {getattr(config, k)}" for k in
                                         ("RANK_W_STRENGTH", "RANK_W_ACC", "RANK_W_PR", "RANK_W_SQ", "RANK_W_MS", "RANK_W_NEWS", "RANK_W_INS")))
    import evscore
    print("\n[9] 🧮 과거 성과 기반 공시 점수 — 지금 다시 만들고 최근 1년으로 검증")
    r = evscore.build()
    v = r["validation"]
    if "new" in v:
        print(f"    학습 ~{v['cut']} {v['train']:,}건 → 검증 {v['test']:,}건")
        print(f"    새 점수 : 순위 상관 {v['new']['rho']:+.3f} · 위 20% {v['new']['top']}% vs 아래 20% {v['new']['bottom']}% (차이 {v['new']['spread']:+.1f}%p)")
        print(f"    지금 규칙: 순위 상관 {v['old']['rho']:+.3f} · 호재 {v['old']['top']}% vs 악재 {v['old']['bottom']}% (차이 {v['old']['spread']:+.1f}%p)")
    print(f"    판정: {v['why']} · 관리 모드 설정 RANK_NEWS_EVIDENCE={config.RANK_NEWS_EVIDENCE}")
    tb = r["table"]
    if tb.get("cell"):
        cells = sorted(tb["cell"].items(), key=lambda kv: kv[1][1])
        print("    가장 나쁜 칸: " + " / ".join(f"{k} {(p - tb['p0']) * 100:+.1f}%p({n})" for k, (n, p) in cells[:5]))
        print("    가장 좋은 칸: " + " / ".join(f"{k} {(p - tb['p0']) * 100:+.1f}%p({n})" for k, (n, p) in cells[-5:][::-1]))
    print("\n끝. 이 결과를 그대로 복사해 붙여 주세요.")


if __name__ == "__main__":
    main()
