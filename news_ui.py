"""📰 뉴스 모음 화면 — 보도자료 피드(PR Newswire 등) · 우리 종목 · 나스닥 · 호재/악재 필터.

2026-10-29 개편(사용자: "보기가 너무 불편해 · 누르면 요약 · 래빗스탁 뉴스 화면 참고 · 호재 점수로 시장 반응 데이터를 쌓자"):
· 뉴스 한 건 = 접힌 줄(분류 · 종목 · 한국어 제목 · 몇 분 전) → 누르면 요약 · 원문 · 📊 뉴스 뒤 주가 · 이 종류의 과거 반응 · 리포트 버튼
· 맨 위 '📊 뉴스 반응 통계'(newsfx: 분류×AI 등급별 당일 고가·종가·+5일 중앙값 · +10% 비율) — 아침 작업이 일봉으로 쌓음
"""
import json
from contextlib import closing
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import access
import db
import news
import newsfx
import ui_kit as ui

SENT = {"호재": "green", "악재": "red", "혼재": "orange", "중립": "gray"}
STAT_COLS = ["분류", "등급", "건수", "당일 고가 중앙값(%)", "당일 종가 중앙값(%)", "+5일 중앙값(%)", "+10% 넘은 비율(%)", "확정"]


def _ago(published) -> str:
    try:
        d = datetime.now(timezone.utc) - pd.Timestamp(published).tz_convert("UTC").to_pydatetime()
    except Exception:  # noqa: BLE001
        return ""
    m = int(d.total_seconds() // 60)
    if m < 60:
        return f"{max(m, 0)}분 전"
    if m < 60 * 24:
        return f"{m // 60}시간 전"
    return f"{m // (60 * 24)}일 전"


def _pct(x) -> str:
    return "-" if x is None or pd.isna(x) else f"{float(x):+.1f}%"


def _react_line(rx: dict | None, t: str | None) -> str:
    if not rx or rx.get("prev_close") is None:
        return "📊 뉴스 뒤 주가: 다음 아침 작업부터(일봉이 쌓이면 당일 고가·종가·+1일·+5일을 적어요)" if t else ""
    s = f"📊 뉴스 뒤 주가(기준 {rx['day']} 직전 종가 ${float(rx['prev_close']):.2f}): 당일 고가 **{_pct(rx['d0_high_pct'])}** · 종가 {_pct(rx['d0_close_pct'])}"
    if rx.get("d1_close_pct") is not None:
        s += f" · +1일 {_pct(rx['d1_close_pct'])}"
    if rx.get("d5_close_pct") is not None:
        s += f" · +5일 {_pct(rx['d5_close_pct'])}"
    return s + ("" if rx.get("done") else " · 진행 중")


def _hist_line(h: dict | None) -> str:
    if not h:
        return ""
    return (f"🔎 이 종류({h['분류']} · {h['등급']}등급)의 과거 반응 {int(h['건수'])}건: 당일 고가 중앙값 {_pct(h['당일 고가 중앙값(%)'])} · 종가 {_pct(h['당일 종가 중앙값(%)'])}"
            + (f" · +5일 {_pct(h['+5일 중앙값(%)'])}" if h.get("+5일 중앙값(%)") is not None and not pd.isna(h.get("+5일 중앙값(%)")) else "")
            + f" · +10% 넘은 비율 {float(h['+10% 넘은 비율(%)']):.0f}%")


def render() -> None:
    ui.title("뉴스 모음", "보도자료 배포사 공식 피드(PR Newswire 등)에서 상장사 뉴스를 모아요. 호재·악재는 키워드 판정이라 원문 확인이 필요해요. 줄을 누르면 요약·뉴스 뒤 주가가 펼쳐져요.")
    df = news.recent(14)
    _tr, _ai, _rx, _st = {}, {}, {}, pd.DataFrame()
    try:  # 🌐 한국어 번역(스캐너가 받은 직후 번역해 둠) · 📊 반응
        import translate
        with closing(db.connect()) as _c:
            translate.ensure(_c)
            _tr = {r[0]: (r[1], r[2]) for r in _c.execute("SELECT id, title_ko, summary_ko FROM news WHERE title_ko IS NOT NULL AND title_ko != ''")}
            _ai = {r[0]: (r[1], r[2], r[3]) for r in _c.execute("SELECT id, category, ai_grade, ai_score FROM news WHERE ai_grade IS NOT NULL OR category IS NOT NULL")}
            _rx = newsfx.reactions(_c)
            _st = newsfx.stats(_c)
    except Exception:  # noqa: BLE001
        pass
    ko_on = st.toggle("🌐 한국어로 보기", True, key="nw_ko", help="제목·요약을 한국어로(번역은 Claude Haiku · 원문 링크는 그대로)")
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1.2, 1])
    q = c1.text_input("검색", key="nw_q", placeholder="티커·단어 검색 (예: FDA, offering, ABCD)", label_visibility="collapsed").strip()
    mine = c2.toggle("우리 종목만", False, key="nw_mine", help="스캐너가 최근 30일 안에 본 종목")
    nas = c3.toggle("나스닥만", True, key="nw_nas")
    no_ad = c4.toggle("소송 광고 숨기기", True, key="nw_noad", help="법무법인의 집단소송 모집 광고(Class Action·Application Deadline 등)")
    sent = c5.selectbox("판정", ["전체", "호재", "악재", "혼재", "중립"], key="nw_sent", label_visibility="collapsed")
    if df.empty:
        st.info("아직 받은 뉴스가 없어요. 스캐너가 10분마다 피드를 받아요(관리 모드에서 피드 주소 확인).")
    else:
        try:
            from datetime import date as _d, timedelta as _td  # '우리 종목' = 스캐너가 최근 30일 안에 본 종목(예전엔 10년 과거 사례까지 넣어 사실상 나스닥 전체)
            uni = set(db.read_df("SELECT DISTINCT ticker FROM daily_snapshots WHERE date >= ?", ((_d.today() - _td(days=30)).isoformat(),))["ticker"])
        except Exception:  # noqa: BLE001
            uni = set()
        ad = [news.is_lawsuit_ad(t_, s_) for t_, s_ in zip(df["title"], df["summary"])]
        v = df[[not x for x in ad]] if no_ad else df
        if nas:
            v = v[v["exchange"].fillna("").str.startswith("NASDAQ")]
        if mine:
            v = v[v["ticker"].isin(uni)]
        if sent != "전체":
            v = v[v["sentiment"] == sent]
        if q:
            _ko = v["id"].map(lambda i: " ".join(_tr.get(i, ("", ""))) if i in _tr else "")
            v = v[v["title"].str.contains(q, case=False, na=False) | v["ticker"].fillna("").str.upper().eq(q.upper()) | v["summary"].str.contains(q, case=False, na=False)
                  | _ko.str.contains(q, case=False, na=False)]
        n_rx = sum(1 for i in df["id"] if i in _rx)
        ui.cards([{"t": "최근 14일 뉴스", "v": f"{len(df)}", "accent": True}, {"t": "나스닥 종목 표기", "v": f"{df['exchange'].fillna('').str.startswith('NASDAQ').sum()}"},
                  {"t": "호재", "v": f"{(df['sentiment'] == '호재').sum()}"}, {"t": "악재(희석 등)", "v": f"{(df['sentiment'] == '악재').sum()}"},
                  {"t": "반응 기록", "v": f"{n_rx}", "s": "뉴스 뒤 주가를 잰 건수"}])
        with st.expander("📊 뉴스 반응 통계 — 분류 × AI 등급별 '뉴스 뒤 주가'(쌓이는 중)", expanded=False):
            st.caption("아침 작업이 종목 있는 뉴스마다 일봉으로 재요: 기준 = 뉴스가 처음 반영되는 거래일 직전 종가 → 당일 고가 · 당일 종가 · +1일 · +5일(5거래일째, 확정). "
                       f"건수가 {newsfx.MIN_N}건 넘는 종류부터 아래 뉴스 줄에 '이 종류의 과거 반응'이 붙어요. 보도자료 피드는 10/23 부터라 몇 주 쌓여야 뜻이 있어요. "
                       "'분류'는 번역 때 Haiku 가 붙인 것(없으면 키워드 판정). 과거 움직임의 통계일 뿐 예측은 아니에요.")
            if _st is None or _st.empty:
                st.caption("아직 반응 기록이 없어요 — 뉴스가 들어오고 다음 아침 작업(07:30)부터 쌓여요.")
            else:
                st.dataframe(_st[STAT_COLS], width="stretch", hide_index=True, height=min(420, 40 + 35 * len(_st)))
        st.caption(f"{len(v)}건 표시" + (f" · 소송 광고 {sum(ad)}건 숨김" if no_ad and sum(ad) else ""))
        for r in v.head(80).to_dict("records"):
            t = r["ticker"]
            rid = r["id"]
            when = pd.Timestamp(r["published"]).tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")
            tko, sko = _tr.get(rid, (None, None))
            cat, gr, sc = _ai.get(rid, (None, None, None))
            use_ko = bool(ko_on and tko)
            title = tko if use_ko else r["title"]
            label = f"{'🏷 ' + cat if cat else r['sentiment']} · {t or '종목 없음'} · {title[:80]}{'…' if len(title) > 80 else ''} · {_ago(r['published'])}"
            chips = (ui.chip(f"{t} · {r['exchange'] or ''}", "blue") if t else "") + ui.chip(r["sentiment"], SENT.get(r["sentiment"], "gray")) + "".join(
                ui.chip(x, "gray") for x in json.loads(r["tags"] or "[]")[:4]) + (ui.chip("우리 종목", "purple") if t in uni else "")
            if cat:
                chips = ui.chip(f"🏷 {cat}", "gray", tip="Claude Haiku 가 번역하며 붙인 분류") + chips
            if gr:  # 🤖 Haiku 의 초소형주 주가 영향 등급(A 큼 · B 보통 · C 작음)·점수·분류 — 래빗스탁의 'AI 점수 평가'와 같은 역할
                chips = ui.chip(f"{gr}등급 · {sc if sc is not None else ''}점" + (f" · {cat}" if cat else ""), {"A": "red", "B": "orange"}.get(gr, "gray"),
                                tip="Claude Haiku 가 매긴 주가 영향 등급(A 큼·B 보통·C 작음)·점수(호재 높음·악재 낮음) — 참고용") + chips
            if ko_on and not tko:   # 아직 번역이 안 온 글은 영어 그대로 — 그 이유가 보이게(예전엔 말없이 영어라 '고장'처럼 보였음)
                chips += ui.chip("번역 대기", "gray", tip="스캐너가 10분마다 10건씩 번역해요(종목 있는 뉴스 먼저 · 3번 실패하면 영어로 둠)")
            with st.expander(label, expanded=False):
                a, b = st.columns([6, 1])
                if use_ko:
                    a.markdown(f'<span class="qk-sub">{when}</span> {chips}<br><a href="{ui.esc(r["link"])}" target="_blank" style="font-weight:700">{ui.esc(tko)}</a>'
                               f'<br><span>{ui.esc((sko or "")[:260])}</span><br><span class="qk-sub" style="opacity:.6">원문: {ui.esc(r["title"])}</span>', unsafe_allow_html=True)
                else:
                    a.markdown(f'<span class="qk-sub">{when}</span> {chips}<br><a href="{ui.esc(r["link"])}" target="_blank" style="font-weight:700">{ui.esc(r["title"])}</a>'
                               f'<br><span class="qk-sub">{ui.esc(r["summary"][:220])}{"…" if len(r["summary"]) > 220 else ""}</span>', unsafe_allow_html=True)
                line = _react_line(_rx.get(rid), t)
                if line:
                    a.markdown(line)
                hist = _hist_line(newsfx.lookup(_st, cat, r["sentiment"], gr)) if t else ""
                if hist:
                    a.caption(hist)
                if t:
                    import report_dialog
                    report_dialog.button(t, f"nw_{abs(hash(rid)) % 10 ** 8}", b)
    m = db.get_meta("news_status")
    if m and m.get("value"):
        stt = json.loads(m["value"])
        def _nm(u: str) -> str:  # 피드 주소 → 짧은 이름
            tail = u.rstrip("/").split("/")[-1].split("?")[0]
            return (u.split("/feedTitle/")[-1].replace("%20", " ") if "/feedTitle/" in u else f"{u.split('//')[-1].split('/')[0].replace('www.', '')} · {tail}")[:48]
        st.caption("피드 상태: " + " · ".join(f"{_nm(u)} → {v}" for u, v in stt.items()))
    if not access.is_guest():
        with st.expander("⚙️ 피드 주소(한 줄에 하나)"):
            txt = st.text_area("피드", "\n".join(news.feeds()), height=120, key="nw_feeds", label_visibility="collapsed")
            st.caption("PR Newswire 사이트의 RSS 페이지(prnewswire.com/rss)에서 원하는 주제·업종 피드 주소를 복사해 넣을 수 있어요. 다른 배포사의 RSS 도 됩니다. GlobeNewswire 는 프로그램 접속을 막아(403) 쓸 수 없어요. 보도자료 상당수는 8-K로도 나오니 🔔 공시 알림도 함께 보세요.")
            d1, d2 = st.columns(2)
            if d1.button("저장", key="nw_save", width="stretch"):
                news.set_feeds(txt.splitlines())
                st.success("저장했어요.")
            if d2.button("지금 받기", key="nw_now", width="stretch"):
                st.write(news.refresh(force=True))
