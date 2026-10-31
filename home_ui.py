"""🏠 홈 — 시장 지표 · 오늘의 브리핑 · 도구 바로가기."""
from contextlib import closing
from datetime import date, timedelta

import streamlit as st

import access
import db
import ui_kit as ui


def _box(title: str, lines: list[str], color: str = "") -> None:
    st.markdown(ui.box(title, lines or ["없음"], color), unsafe_allow_html=True)


@st.cache_data(ttl=120, show_spinner=False)
def _briefing_cached(guest: bool) -> dict:
    return briefing(guest)


def briefing(guest: bool | None = None) -> dict:
    """오늘의 브리핑 재료(화면과 테스트에서 같이 씀). 화면은 _briefing_cached 로 2분 동안 기억(예전엔 홈을 열 때마다 새로 계산해 5~10초)."""
    guest = access.is_guest() if guest is None else guest
    out = {}
    try:
        import rank_ui
        df = rank_ui.table()
        out["rank"] = [] if df.empty else [f"{r['rank']}. {r['ticker']} · 종합 {r['score']:g} · {r['when']}" for r in df.head(5).to_dict("records")]
    except Exception:  # noqa: BLE001
        out["rank"] = []
    since = (date.today() - timedelta(days=3)).isoformat()  # 최근 3일(예전엔 어제부터라 주말엔 늘 0건)
    with closing(db.connect()) as conn:
        def q(sql, p=()):
            try:
                return [dict(r) for r in conn.execute(sql, p)]
            except Exception:  # noqa: BLE001
                return []
        news = q("SELECT ticker, form, sentiment, tags FROM sec_feed WHERE COALESCE(filed, substr(updated,1,10)) >= ? ORDER BY updated DESC", (since,))
        cnt = {k: sum(1 for n in news if n["sentiment"] in v) for k, v in {"호재": ("호재", "약한 호재"), "악재": ("악재", "주의")}.items()}
        out["news_count"] = {"전체": len(news), **cnt}
        out["news"] = [f"{n['ticker']} {n['form']} · {n['sentiment']}" + (f" · {', '.join(__import__('json').loads(n['tags'] or '[]')[:2])}" if n["tags"] else "")
                       for n in news if n["sentiment"] in ("호재", "악재")][:4]
        try:
            import regsho
            ds = regsho.dates(conn)
            sm = regsho.summary(conn, ds[0]) if ds else None
            st_ = regsho.streaks_at(conn, ds[0]) if ds else {}
        except Exception:  # noqa: BLE001
            sm, st_ = None, {}
        out["regsho"] = None if not sm else {**sm["cur"], "top": [f"{t} {n}일째" for t, n in sorted(st_.items(), key=lambda x: -x[1])[:3]]}
        out["accum"] = [f"{r['ticker']} 합계 {r['score']:g}" for r in q("SELECT ticker, score FROM accum WHERE period='일간' AND date=(SELECT MAX(date) FROM accum) ORDER BY score DESC LIMIT 3")]
        ev = [] if guest else q("SELECT ticker, date, kind, title FROM events WHERE date >= ? AND date <= ? ORDER BY date LIMIT 6",
                                              (date.today().isoformat(), (date.today() + timedelta(days=7)).isoformat()))
        out["events"] = [f"D-{(date.fromisoformat(e['date']) - date.today()).days} {e['ticker']} {e['kind']} — {e['title']}" for e in ev]
    return out


def render(pages: list[tuple], page_obj: dict | None = None) -> None:
    import macro_ui
    ui.title("🏠 홈", f"{date.today():%Y-%m-%d} · 시장 지표와 오늘의 브리핑을 한눈에, 아래 카드로 원하는 도구로 바로 가요.")
    macro_ui.render_strip()
    macro_ui.render_light()   # 🚦 소형주 장세 신호등(2026-10-27, ANO 거시 관점)
    st.markdown("### 📰 오늘의 브리핑")
    b = _briefing_cached(access.is_guest())
    c1, c2, c3 = st.columns(3)
    with c1:
        _box("🏁 종합 순위 TOP 5", b["rank"], "#8E4EC6")
        _box("🧲 오늘 매집 의심 TOP 3", b["accum"], "#8E4EC6")
    with c2:
        nc = b["news_count"]
        _box(f"🔔 최근 3일 공시 {nc['전체']}건 · 호재 {nc['호재']} · 악재 {nc['악재']}", b["news"], "#3678F6")
        rg = b["regsho"]
        _box("📛 Reg SHO", [] if not rg else [f"등록 {rg['등록']} · 고위험 {rg['고위험']} · 신규 {rg['신규']}"] + rg["top"], "#E5484D")
    with c3:
        if not access.is_guest():
            _box("🗓 7일 안 일정", b["events"], "#F76B15")
        _box("📖 처음이라면", ["🏁 종합 순위 → 📄 리포트 → 🏢 종목(기업 분석) 순서로 보세요", "용어가 어려우면 📖 가이드북의 용어 사전"], "#30A46C")
    try:   # 🆕 업데이트 노트(2026-10-31): 배포마다 바뀐 점을 쉬운 말로 — 방문객은 방문객 화면에 관련된 줄만
        import updates
        nts = updates.latest(access.is_guest())
        if nts:
            with st.expander(f"🆕 업데이트 노트 · {nts[0]['date']} {nts[0]['title']}"):
                for nt in nts:
                    st.markdown(f"**{ui.esc(nt['title'])}** <span class='qk-sub'>{nt['date']}</span>", unsafe_allow_html=True)
                    st.markdown("\n".join(f"- {ui.md_safe(x)}" for x in nt["lines"]))
    except Exception:  # noqa: BLE001
        pass
    if not access.is_guest():   # 🛠 운영 현황(2026-10-31): 점검표·자동 작업 일정·작업 기록 — 조용한 고장을 화면에서 바로
        try:
            import jobs_ui
            jobs_ui.render()
        except Exception as e:  # noqa: BLE001
            st.caption(f"운영 현황을 그리지 못했어요: {e}")
    st.markdown("### 🧰 도구 바로가기")
    secs = list(dict.fromkeys(p[4] for p in pages if p[0] != "home"))
    for sec in secs:
        items = [p for p in pages if p[4] == sec and p[0] != "home"]
        st.markdown(f'<div class="qk-sub" style="margin:.6rem 0 .2rem"><b>{ui.esc(sec)}</b></div>', unsafe_allow_html=True)
        cols = st.columns(4)
        for i, (k, title, icon, desc, _) in enumerate(items):
            with cols[i % 4].container(border=True):
                if page_obj and k in page_obj:
                    st.page_link(page_obj[k], label=title, icon=icon)
                else:
                    st.markdown(f"{icon} **{title}**")
                st.caption(desc)
