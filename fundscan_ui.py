"""💰 펀드스캔 화면 — 카드 목록(신호 점수순) + 자세히(펌핑 유인 막대 · 대기 물량 · 근거 자료: 주식 수 변동 · 희석 · 현금 사정 · 워런트 돈 · 조달 내역 · 발행 증권)."""
import pandas as pd
import streamlit as st

import access
import db
import fundscan as fs
import tosslink
import ui_kit as ui

LABEL_COLOR = {"펌핑 유인": "red", "양면 신호": "orange", "관망": "gray"}
PRESS_COLOR = {"매우 높음": "red", "높음": "orange", "보통": "gray", "낮음": "green"}


def _fx() -> float:
    try:
        return float((db.get_meta("usdkrw") or {}).get("value") or 1350.0)
    except (TypeError, ValueError):
        return 1350.0


def money(v, cur: str, fx: float, unit_price: bool = False) -> str:
    if v is None:
        return "-"
    if cur == "원":
        w = v * fx
        return f"{w:,.0f}원" if unit_price else (f"약 {w / 1e8:,.0f}억원" if abs(w) >= 1e8 else f"약 {w / 1e4:,.0f}만원")
    return f"${v:,.4f}" if unit_price else f"${v / 1e6:,.2f}M"


@st.cache_data(ttl=120, show_spinner=False)
def _scan():
    """🔥 화면 캐시 'fundscan'(quant-warm 10분마다)에서 꺼냄 — 없거나 오래됐으면 직접 계산해 넣어 둠(2026-10-30: 첫 화면 3.9초 → 즉시)."""
    import pagecache
    return pagecache.get_or_build("fundscan")



def _rw_txt(r: dict) -> str:
    """런웨이 칸 글자 — 재무가 오래됐으면 그렇다고(예전엔 0.0개월·현금 음수로 보였음)."""
    info = r.get("runway_info") or {}
    if r.get("runway_now") is not None:
        return f"{r['runway_now']:.1f}개월"
    if info.get("stale"):
        return f"재무 오래됨({info.get('cash_asof') or '-'})"
    if info.get("profitable"):
        return "흑자(소모 없음)"
    return "-"

def render() -> None:
    ui.title("펀드스캔", "자금조달 공시의 워런트 행사가와 회사 현금으로 '회사가 주가를 띄울 이유'를 계산합니다. 조건 충족 여부이지 예측이 아닙니다.")
    c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 1])
    q = c1.text_input("검색", key="fs_q", placeholder="티커 검색 (예: SMSI)", label_visibility="collapsed").strip().upper()
    order = c2.selectbox("정렬", ["신호 점수순", "런웨이 짧은순", "필요 상승 작은순"], key="fs_sort", label_visibility="collapsed")
    only = c3.toggle("부양 유인만", False, key="fs_only")
    cur = c4.radio("단위", ["원", "$"], horizontal=True, key="fs_cur", label_visibility="collapsed")
    rows = _scan()
    if not rows:
        st.info("아직 해석한 자금조달 공시가 없어요. 매일 아침 갱신 작업이 최근 1년 424B·8-K(1.01·3.02)를 하루 60건씩 해석해요.")
        return
    fx = _fx()
    ui.cards([{"t": "추적 종목", "v": f"{len(rows)}", "s": "최근 1년 자금조달 공시가 있는 종목", "accent": True},
              {"t": "주가 부양 유인 충족", "v": f"{sum(r['cond'] for r in rows)}", "s": "현금 4개월 이하 + 행사가까지 +20~100%"},
              {"t": "조달압력 높음 이상", "v": f"{sum(r['pressure'] in ('높음', '매우 높음') for r in rows)}", "s": "추정 현재현금 런웨이 3개월 이하"},
              {"t": "대기 물량 보유", "v": f"{sum((r['overhang'] or 0) > 0 for r in rows)}", "s": "워런트·프리펀디드 > 0"}])
    v = [r for r in rows if (not q or q in r["ticker"]) and (not only or r["cond"])]
    if order == "런웨이 짧은순":
        v.sort(key=lambda r: (r["runway_now"] is None, r["runway_now"] or 0))
    elif order == "필요 상승 작은순":
        v.sort(key=lambda r: (r["need"] is None, abs(r["need"] or 0)))
    st.caption(f"{len(v)}종목 · 카드의 '자세히'를 누르면 근거 자료까지 볼 수 있어요.")
    for i in range(0, min(len(v), 60), 3):
        cols = st.columns(3)
        for col, r in zip(cols, v[i:i + 3]):
            with col.container(border=True):
                ld = r["latest_deal"]
                head = (f'<span class="qk-tk">{ui.esc(r["ticker"])}</span> {ui.chip(f"{r["label"]} {r["score"]}", LABEL_COLOR[r["label"]])}{ui.chip(r["grade"], "green" if r["grade"] == "A" else "gray")}'
                        + (ui.chip("RS", "orange") if r["rs"] else "") + ("" if not r["pressure"] else ui.chip(r["pressure"], PRESS_COLOR[r["pressure"]]))
                        + f'<br><span class="qk-sub">조달 {ld["filed"]} · {ld["form"]}</span>')
                qty = f'<b style="font-size:1.1rem">{r["overhang"]:,.0f}주</b> <span class="qk-sub">{"워런트·PFW" if r["pfw"] else "워런트 물량 · PFW 없음"}</span>'
                kv = ui.kv([("런웨이(추정)", _rw_txt(r)), ("필요 상승", "-" if r["need"] is None else ("도달" if r["need"] <= 0 else f"+{r['need']:.1f}%")),
                            ("최저 행사가", money(r["min_ex"], cur, fx, True)), ("현재가", money(r["price"], cur, fx, True))])
                st.markdown(head + "<br>" + qty + ("&nbsp;" + ui.chip("부양 유인", "red") if r["cond"] else "") + kv, unsafe_allow_html=True)
                if st.button("자세히", key=f"fs_d_{r['ticker']}", width="stretch"):
                    detail(r["ticker"], cur)


@st.dialog("💰 펀드스캔 상세", width="large")
def detail(t: str, cur: str = "원") -> None:
    render_detail(t, cur)



def _similar_box(r: dict) -> None:
    """📊 비슷한 과거 딜: 매도 가능일 뒤 5·20·60거래일 등락 분포(중앙값·가운데 50% 범위·오른 비율)."""
    import dealpaths as dp
    ld = r.get("latest_deal") or {}
    kind = ld.get("kind") or ""
    prior = r.get("price")
    disc = None if not (ld.get("unit_price") and prior) else (float(ld["unit_price"]) / float(prior) - 1) * 100
    sim = dp.similar(kind, prior, disc, exclude=ld.get("accession"))
    st.markdown("**📊 비슷한 과거 딜** — 딜 물량이 풀릴 수 있는 날(매도 가능일) 뒤 주가가 어떻게 됐나")
    if not sim["n"]:
        st.caption("아직 계산된 과거 딜이 없어요. 매일 아침 갱신이 쌓아요.")
        return
    st.caption(f"기준: {sim['key']} → {sim['level']} 기준 {sim['n']}건(8건 미만이면 한 단계씩 넓힘). "
               "⚠️ 딜이 1년치라 표본이 작고, 상장폐지된 회사는 주가가 없어 빠져서 실제는 더 나쁠 수 있어요. 과거 분포일 뿐 예측이 아니에요.")
    rows = []
    for h in dp.HORIZONS:
        x = sim["stats"].get(h)
        rows.append({"기간": f"{h}거래일 뒤", "건수": "-" if not x else x["n"], "중앙값(%)": "-" if not x else f"{x['median']:+.1f}",
                     "가운데 50% 범위(%)": "-" if not x else f"{x['q25']:+.1f} ~ {x['q75']:+.1f}", "오른 비율(%)": "-" if not x else f"{x['up']:.0f}"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if sim.get("min60") is not None:
        st.caption(f"60거래일 안 최저 중앙값 {sim['min60']:+.1f}% · 최고 중앙값 {sim['max60']:+.1f}% (매도 가능일 종가 대비)")
    with st.expander(f"표본 딜 {sim['n']}건 보기"):
        v = sim["rows"].sort_values("filed", ascending=False)[["ticker", "kind", "filed", "avail", "avail_note", "discount", "ret5", "ret20", "ret60", "min60", "max60"]]
        st.dataframe(ui.tidy(v.rename(columns={"ticker": "티커", "kind": "종류", "filed": "접수일", "avail": "매도 가능일", "avail_note": "매도 가능일 근거",
                                               "discount": "할인율(%)", "ret5": "5일 뒤(%)", "ret20": "20일 뒤(%)", "ret60": "60일 뒤(%)",
                                               "min60": "60일 최저(%)", "max60": "60일 최고(%)"})), hide_index=True, width="stretch")

def render_detail(t: str, cur: str = "원") -> None:
    r = fs.analyze(t)
    if not r:
        st.info("자금조달 기록이 없어요.")
        return
    fx = _fx()
    ld = r["latest_deal"]
    a, b = st.columns([3, 1])
    a.markdown(f'<span class="qk-tk" style="font-size:1.5rem">{ui.esc(t)}</span> {ui.chip("데이터 " + r["grade"], "green" if r["grade"] == "A" else "gray")}'
               + ("" if not r["pressure"] else ui.chip("조달압력 " + r["pressure"], PRESS_COLOR[r["pressure"]])) + (ui.chip("주가 부양 유인 구간", "red") if r["cond"] else "")
               + f'<br><span class="qk-sub">최근 자금조달 {ld["filed"]} · {ld["form"]} · 현재가 {money(r["price"], cur, fx, True)}</span>'
               + "".join(f'<br><span class="qk-sub" style="color:#F76B15">{ui.esc(n)} — 수량·가격은 병합 후 현재 주식 기준</span>' for n in r["adj_note"][:2]), unsafe_allow_html=True)
    b.link_button("📲 토스", tosslink.url(t), width="stretch")
    ui.cards([{"t": "미행사 프리펀디드", "v": f"{r['pfw']:,.0f}주" if r["pfw"] else "-"},
              {"t": "현금 버틸 기간", "v": _rw_txt(r),
               "s": "-" if r["runway_report"] is None else f"보고서 기준 {r['runway_report']:.1f}개월 → 경과 반영", "accent": (r["runway_now"] or 99) <= 4},
              {"t": "행사가까지 남은 상승폭", "v": "-" if r["need"] is None else f"{r['need']:+.1f}%", "s": f"최저 행사가 {money(r['min_ex'], cur, fx, True)}"},
              {"t": "대기 물량 ÷ 하루 거래량", "v": "-" if not r["overhang_days"] else f"{r['overhang_days']:.1f}일", "s": "물량 크기 지표(소화 예측 아님)"}])
    pos = None if not (r["price"] and r["min_ex"]) else max(0.0, min(100.0, r["price"] / r["min_ex"] * 100))
    bar = "" if pos is None else (f'<div style="display:flex;justify-content:space-between" class="qk-sub"><span>현재가 <b>{money(r["price"], cur, fx, True)}</b></span>'
                                  f'<span>워런트 행사 최소 주가 <b>{money(r["min_ex"], cur, fx, True)}</b> ({r["need"]:+.1f}%)</span></div>'
                                  f'<div style="height:8px;border-radius:6px;background:rgba(128,128,128,.25);margin:6px 0 12px"><div style="width:{pos:.0f}%;height:100%;border-radius:6px;background:#E5484D"></div></div>')
    wl = [f"{w['name']} @ {money(w['price'], cur, fx, True)} — {w['qty']:,.0f}주 ({w['deal']} {w['form']})" for w in r["warrants"]] + ([f"프리펀디드 워런트 — {r['pfw']:,.0f}주(행사 현금 유입 거의 없음)"] if r["pfw"] else [])
    st.markdown(f'<div class="qk-verdict" style="border-color:#E5484D55">{ui.chip(f"{r["label"]} {r["score"]}점", LABEL_COLOR[r["label"]])}'
                f'<span class="qk-sub" style="float:right">예측이 아니라 조건 충족 여부입니다</span><div style="margin-top:10px">{bar}</div>'
                + ui.kv([("남은 현금(추정)", _rw_txt(r) if r["runway_now"] is None else f"약 {r['runway_now']:.1f}개월 ({money(r['cash_now'], cur, fx)})"),
                         (f"대기 물량 합계 ({r['warrant_src']})", f"{r['overhang']:,.0f}주")]) + "</div>", unsafe_allow_html=True)
    st.markdown(ui.box("대기 물량", wl or ["확인된 워런트가 없어요"], "#E5484D"), unsafe_allow_html=True)
    if r["sentence"]:
        st.info(r["sentence"].replace("$", "＄"))
    _similar_box(r)
    with st.expander("근거 자료 전체 보기 (검증·전문가용)"):
        sc = r["share_change"]
        c1, c2 = st.columns(2)
        c1.markdown("**주식 수 변동 원인 추적**" + ("" if not sc else ui.kv([("자금조달 직전 주식 수", f"{sc['before']:,.0f}주 ({sc['before_asof']})"), ("최신 공시 주식 수", f"{sc['latest']:,.0f}주 ({sc['latest_asof']})"),
                                                                         ("늘어난 주식", f"{sc['increase']:,.0f}주"), ("딜로 설명되는 증가", f"{sc['explained']:,.0f}주"),
                                                                         ("원인불명 증가", f"{sc['unknown']:,.0f}주"), ("원인 확인율", "-" if sc["rate"] is None else f"{sc['rate']:.1f}%")])), unsafe_allow_html=True)
        if not sc:
            c1.caption("SEC 표지 주식 수 이력이 부족해요.")
        c2.markdown("**물량 부담 · 지분 희석**" + ui.kv([("현재 총 주식 수", "-" if not r["shares"] else f"{r['shares']:,.0f}주"), ("주식 수 출처", r["shares_tag"]),
                                                     ("대기 물량 ÷ 현재 주식", "-" if r["dil_pct"] is None else f"{r['dil_pct']:.1f}%"),
                                                     ("전부 행사 시 지분 희석", "-" if not r["shares"] else f"{r['overhang'] / (r['shares'] + r['overhang']) * 100:.1f}%"),
                                                     ("희석 위험 등급", "-" if r["dil_pct"] is None else ("높음" if r["dil_pct"] >= 25 else "중간" if r["dil_pct"] >= 10 else "낮음"))]), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.markdown("**회사 현금 사정**" + ui.kv([("보유 현금(공시)", f"{money(r['cash'], cur, fx)} ({r['asof'] or '-'})"), ("한 달 지출", money(r["burn"], cur, fx)),
                                               ("보고 후 경과", "-" if r["months_elapsed"] is None else f"{r['months_elapsed']:.1f}개월"),
                                               ("보고 후 조달금(공시)", money(r["raised_after"], cur, fx)), ("지금 시점 추정 현금", money(r["cash_now"], cur, fx)),
                                               ("현금 바닥나는 시점", r["floor"] or "-"), ("자금조달 예상 구간", "-" if not r["raise_window"] else f"{r['raise_window'][0]} ~ {r['raise_window'][1]}")]),
                    unsafe_allow_html=True)
        c2.markdown("**워런트로 들어올 수 있는 돈**" + ui.kv([("최저 행사가 vs 현재가", f"{money(r['min_ex'], cur, fx, True)} vs {money(r['price'], cur, fx, True)}"),
                                                       ("행사가까지 남은 상승폭", "-" if r["need"] is None else f"{r['need']:+.1f}%"), ("전부 행사되면 들어올 돈", money(r["money_in"], cur, fx)),
                                                       ("주가 부양 유인", "조건 충족" if r["cond"] else "조건 미충족")]), unsafe_allow_html=True)
        st.markdown("**자금조달 내역**")
        for d in r["deals"][:8]:
            import json as _j
            ws = _j.loads(d["warrants"] or "[]")
            st.markdown(ui.box(f"{d['filed']} 자금조달 ({d['form']}) · {d['kind']}" + (" · 매도가능(재판매 등록)" if d["resale"] else ""),
                               [f"묶음 판매가 {money(d['unit_price'], cur, fx, True)}", f"조달한 돈 {money(d['proceeds'], cur, fx)}", f"주관사·배치대리인 {d['agent'] or '-'}",
                                f"직접 발행 주식 {d['shares'] or 0:,.0f}주 · 프리펀디드 {d['pfw'] or 0:,.0f}주", "워런트: " + (", ".join(f"{w.get('name')} {w['qty']:,.0f}주 @ ${w['price']}" for w in ws) or "-"),
                                f"추출 방식: {d['source']}"]), unsafe_allow_html=True)
        if not access.is_guest() and st.button("🤖 AI 정밀 추출(최근 딜 3건 표지, 약 30원)", key=f"fs_ai_{t}"):
            import config
            import sec
            try:
                n = fs.ai_extract(t, sec.SecClient(config.SEC_USER_AGENT))
                _scan.clear()
                st.success(f"{n}건 다시 추출했어요. 창을 닫았다 다시 열면 반영돼요.")
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
