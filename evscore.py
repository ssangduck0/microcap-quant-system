"""🧮 과거 성과 기반 공시 점수 — 🔬 이벤트 연구(약 5만 건)의 실제 주가 반응으로 공시마다 점수를 매긴다.

- 칸: 사건 종류 × 가격대($1 미만 / $1~5 / $5 이상) × 시점(장전·장중·장후)
- 값: 그 칸의 'D+5 시장(IWM) 대비 이긴 확률'. 표본이 적은 칸은 상위(종류×가격대) → 전체 기준선 쪽으로 당김(K건만큼 기준선을 섞음)
- 점수 = (칸 확률 − 기준선) %p. +면 과거에 비슷한 공시 뒤 시장보다 잘했고, −면 못했다
- 검증: 앞 기간으로 점수표를 만들고 최근 365일에 맞춰 봄. 지금 규칙(호재 +, 악재 −)보다 나을 때만 🏁 순위에 씀
매일 아침 갱신이 다시 만든다(이벤트 수집기가 새 공시를 쌓음). 지금 바로: python evscore.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

import pandas as pd

import db

K = 200                  # 표본이 이 정도면 칸 값과 기준선을 반반 믿음
HOLDOUT_DAYS = 365       # 검증용으로 떼어 두는 최근 기간
TIMINGS = ("장전", "장중", "장후")


def band(price) -> str:
    if price is None or pd.isna(price):
        return "가격 미상"
    return "$1 미만" if price < 1 else ("$1~5" if price < 5 else "$5 이상")


def _tm(t: str | None) -> str:
    return t if t in TIMINGS else "장후"  # 시각 미상(17건)은 가장 보수적인 장후로


def build_table(df: pd.DataFrame, k: int = K) -> dict:
    d = df.dropna(subset=["abn5"]).copy()
    if d.empty:
        return {}
    d["win"] = d["abn5"] > 0
    d["band"] = [band(p) for p in d["price"]]
    d["tm"] = [_tm(t) for t in d["timing"]]
    p0 = float(d["win"].mean())
    parent, cell, typ = {}, {}, {}
    for ty, g in d.groupby("type"):  # 가격을 모를 때 쓰는 종류 전체 값
        typ[ty] = [int(len(g)), float((g["win"].sum() + k * p0) / (len(g) + k))]
    for (ty, bd), g in d.groupby(["type", "band"]):
        parent[f"{ty}|{bd}"] = [int(len(g)), float((g["win"].sum() + k * p0) / (len(g) + k))]
    for (ty, bd, tm), g in d.groupby(["type", "band", "tm"]):
        pp = parent[f"{ty}|{bd}"][1]
        cell[f"{ty}|{bd}|{tm}"] = [int(len(g)), float((g["win"].sum() + k * pp) / (len(g) + k))]
    return {"p0": p0, "k": k, "n": int(len(d)), "parent": parent, "cell": cell, "type": typ}


def score(tbl: dict, ty: str, price, timing: str | None) -> float:
    """%p (칸 확률 − 기준선). 점수표에 없는 칸은 0."""
    if not tbl:
        return 0.0
    bd, tm = band(price), _tm(timing)
    v = tbl["cell"].get(f"{ty}|{bd}|{tm}") or tbl["parent"].get(f"{ty}|{bd}") or (tbl.get("type") or {}).get(ty)
    return 0.0 if not v else round((v[1] - tbl["p0"]) * 100, 2)


def info(tbl: dict, ty: str, price, timing: str | None) -> dict | None:
    """화면용: 점수 + 근거(칸 이름·건수·이긴 확률·기준선)."""
    if not tbl:
        return None
    bd, tm = band(price), _tm(timing)
    key = f"{ty}|{bd}|{tm}"
    v, lvl = tbl["cell"].get(key), "칸"
    if not v:
        v, lvl, key = tbl["parent"].get(f"{ty}|{bd}"), "종류×가격대", f"{ty}|{bd}"
    if not v:
        v, lvl, key = (tbl.get("type") or {}).get(ty), "종류 전체(가격 미상)", f"{ty}|가격 미상"
    if not v:
        return None
    return {"pp": round((v[1] - tbl["p0"]) * 100, 1), "n": v[0], "p": round(v[1] * 100, 1), "p0": round(tbl["p0"] * 100, 1), "key": key, "level": lvl}


def for_feed_row(tbl: dict, r: dict, price, conn=None) -> dict | None:
    """공시 알림 한 줄(dict: form·items·tags·updated·accession) → info. 8-K·6-K 가 아니면 None."""
    ty = feed_type(r.get("items"), r.get("tags"), r.get("form"), r.get("accession"), conn)
    return None if ty is None else info(tbl, ty, price, feed_timing(r.get("updated")))


def chip_color(pp: float) -> str:
    return "green" if pp >= 3 else ("red" if pp <= -3 else "gray")


def _old(sent: str) -> float:  # 지금 규칙: 호재 가산 · 악재 감점 · 나머지 0
    return 1.0 if sent == "호재" else (-1.0 if sent == "악재" else 0.0)


def _metrics(s: pd.Series, abn: pd.Series) -> dict:
    """순위 상관(점수가 높을수록 D+5 초과수익이 높은가) · 위 20% vs 아래 20% 이긴 확률 차이."""
    win = abn > 0
    rho = float(s.rank().corr(abn.rank())) if s.nunique() > 1 else 0.0
    order = s.sort_values(kind="mergesort").index
    n5 = max(1, len(order) // 5)
    lo, hi = order[:n5], order[-n5:]
    return {"rho": round(rho, 4), "top": round(float(win.loc[hi].mean()) * 100, 1), "bottom": round(float(win.loc[lo].mean()) * 100, 1),
            "spread": round(float(win.loc[hi].mean() - win.loc[lo].mean()) * 100, 1)}


def validate(df: pd.DataFrame, holdout_days: int = HOLDOUT_DAYS, k: int = K) -> dict:
    d = df.dropna(subset=["abn5"]).copy()
    if d.empty:
        return {"ok": False, "why": "라벨된 사건 없음"}
    d["day0"] = pd.to_datetime(d["day0"])
    cut = d["day0"].max() - pd.Timedelta(days=holdout_days)
    train, test = d[d["day0"] <= cut], d[d["day0"] > cut].copy()
    if len(train) < 2000 or len(test) < 1000:
        return {"ok": False, "why": f"자료 부족(학습 {len(train):,} · 검증 {len(test):,})"}
    tbl = build_table(train, k)
    test["new"] = [score(tbl, ty, p, tm) for ty, p, tm in zip(test["type"], test["price"], test["timing"])]
    test["old"] = [_old(x) for x in test["sentiment"]]
    # 같은 사건으로 비교: 지금 규칙은 점수가 세 가지뿐이라 '호재 무리 vs 악재 무리' 차이로 본다
    old_good, old_bad = test[test["old"] > 0], test[test["old"] < 0]
    old = {"rho": round(float(test["old"].rank().corr(test["abn5"].rank())), 4),
           "top": round(float((old_good["abn5"] > 0).mean()) * 100, 1), "bottom": round(float((old_bad["abn5"] > 0).mean()) * 100, 1)}
    old["spread"] = round(old["top"] - old["bottom"], 1)
    new = _metrics(test["new"], test["abn5"])
    ok = new["rho"] > old["rho"] and new["spread"] > old["spread"]
    return {"ok": ok, "cut": cut.date().isoformat(), "train": int(len(train)), "test": int(len(test)), "new": new, "old": old,
            "why": ("지금 규칙보다 나음 → 순위에 씀" if ok else "지금 규칙보다 낫지 않음 → 지금 규칙 유지")}


def build(save: bool = True) -> dict:
    import eventlab
    df = eventlab.table()
    out = {"built": datetime.now().isoformat(timespec="seconds"), "validation": validate(df), "table": build_table(df)}
    if save:
        db.set_meta("evscore", json.dumps(out, ensure_ascii=False))
    return out


def load() -> dict | None:
    try:
        m = db.get_meta("evscore")
        return json.loads(m["value"]) if m and m.get("value") else None
    except Exception:  # noqa: BLE001
        return None


def active() -> dict | None:
    """순위에 쓸 점수표(검증 통과 + 관리 모드에서 끄지 않음). 아니면 None → 지금 규칙."""
    import config
    if not getattr(config, "RANK_NEWS_EVIDENCE", True):
        return None
    x = load()
    return x["table"] if x and x.get("table") and (x.get("validation") or {}).get("ok") else None


# 공시 알림(secfeed)의 한글 태그 → 이벤트 연구 사건 종류. (예전엔 영어 원문용 분류기에 한글 태그를 넣어 거의 다 '기타'가 됐음 →
#  희석 공시가 '기타' 칸의 좋은 점수를 받는 버그)
TAG_TYPE = {"희석 위험": "공모·사모(희석)", "ATM/ELOC": "공모·사모(희석)", "희석 임박": "공모·사모(희석)", "주식 병합": "주식 병합",
            "상장유지": "상장유지 통지", "파산": "파산·존속 위험", "계속기업 의문": "파산·존속 위험", "FDA 승인": "FDA·임상",
            "인수합병": "인수·합병", "계약": "계약·수주", "수주": "계약·수주", "파트너십·계약": "제휴·라이선스",
            "실적": "실적 발표", "실적 개선": "실적 발표", "경영진 변경": "경영진·이사회"}
SCORED_FORMS = ("8-K", "6-K")  # 점수표는 8-K·6-K 로 만들었으므로 이 둘만 점수(투자설명서 424B·S-1 등은 표에 없는 종류)


def feed_type(items, tags, form: str | None = None, accession: str | None = None, conn=None) -> str | None:
    """공시 알림 한 건의 사건 종류(이벤트 연구와 같은 이름). 점수 대상이 아닌 서류면 None.
    1) 이벤트 연구가 원문으로 이미 분류한 공시면 그 분류 2) 8-K 항목 번호 3) 한글 태그 — 가장 앞선(희석이 먼저) 종류."""
    import eventlab
    if form is not None and not str(form).upper().startswith(SCORED_FORMS):
        return None
    if accession and conn is not None:
        try:
            r = conn.execute("SELECT types FROM ev_docs WHERE accession=? AND ok=1", (accession,)).fetchone()
            if r and r[0]:
                ts = json.loads(r[0])
                if ts:
                    return ts[0]
        except Exception:  # noqa: BLE001
            pass
    tg = tags
    if isinstance(tg, str):
        try:
            tg = json.loads(tg) if tg.startswith("[") else [tg]
        except ValueError:
            tg = [tg]
    it = items or ""
    if isinstance(it, str) and it.startswith("["):
        try:
            it = json.loads(it)
        except ValueError:
            pass
    if isinstance(it, str):
        it = [x.strip() for x in it.replace(";", ",").split(",")]
    found = {eventlab.ITEM_TYPES[i] for i in it if i in eventlab.ITEM_TYPES} | {TAG_TYPE[t] for t in (tg or []) if t in TAG_TYPE}
    if not found:
        return "기타"
    order = {n: p for n, _, p in eventlab.TYPES}
    return sorted(found, key=lambda n: order.get(n, 99))[0]


def feed_timing(updated: str | None) -> str:
    """EDGAR 'updated'(미국 동부 시각, 예: 2026-10-23T16:05:12-04:00) → 장전·장중·장후."""
    try:
        hm = int(updated[11:13]) * 100 + int(updated[14:16])
    except (TypeError, ValueError):
        return "장후"
    return "장후" if hm >= 1600 else ("장전" if hm < 930 else "장중")


def recent(conn, tbl: dict, price: dict, days: int = 5, today=None) -> dict[str, list[tuple[float, str]]]:
    """{티커: [(점수 %p, 설명)]} — 최근 days일 공시 알림."""
    from datetime import date
    today = today or date.today()
    out: dict[str, list] = {}
    try:
        rows = conn.execute("SELECT ticker, items, tags, updated, form, accession FROM sec_feed WHERE ticker IS NOT NULL AND COALESCE(filed, substr(updated,1,10)) >= ?",
                            ((today - timedelta(days=days)).isoformat(),)).fetchall()
    except Exception:  # noqa: BLE001
        return out
    for t, items, tags, upd, form, acc in rows:
        ty = feed_type(items, tags, form, acc, conn)
        if ty is None:  # 8-K·6-K 가 아닌 서류는 점수 없음(순위는 예전 악재 규칙이 처리)
            continue
        tm, px = feed_timing(upd), price.get(t)
        out.setdefault(t, []).append((score(tbl, ty, px, tm), f"{ty}·{band(px)}·{tm}"))
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    import config
    config.apply_overrides()
    r = build()
    v = r["validation"]
    print(f"점수표: 사건 {r['table'].get('n', 0):,}건 · 기준선(시장보다 이긴 확률) {r['table'].get('p0', 0) * 100:.1f}%")
    if "new" in v:
        print(f"검증(학습 ~{v['cut']} {v['train']:,}건 → 최근 {v['test']:,}건)")
        print(f"  새 점수: 순위 상관 {v['new']['rho']:+.3f} · 위 20% 이긴 확률 {v['new']['top']}% vs 아래 20% {v['new']['bottom']}% (차이 {v['new']['spread']:+.1f}%p)")
        print(f"  지금 규칙: 순위 상관 {v['old']['rho']:+.3f} · 호재 {v['old']['top']}% vs 악재 {v['old']['bottom']}% (차이 {v['old']['spread']:+.1f}%p)")
    print("판정: " + v["why"])
    cells = sorted(r["table"].get("cell", {}).items(), key=lambda kv: kv[1][1])
    if cells:
        p0 = r["table"]["p0"]
        print("\n가장 나쁜 칸 8개 (종류|가격대|시점 · 건수 · 점수)")
        for kk, (n, p) in cells[:8]:
            print(f"  {kk} · {n:,}건 · {(p - p0) * 100:+.1f}%p")
        print("가장 좋은 칸 8개")
        for kk, (n, p) in cells[-8:][::-1]:
            print(f"  {kk} · {n:,}건 · {(p - p0) * 100:+.1f}%p")
