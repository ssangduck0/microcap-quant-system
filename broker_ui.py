"""⚙️ 관리 모드 '💵 실매매' 구역(4단계 1주 모드 2부, 2026-10-29) — 상태 · 두 단계 스위치 · 한도 · 보유/미체결/요청 · 킬 스위치 · 1주 왕복 테스트.
주문 자체는 스캐너 프로세스(토큰 1개)가 낸다. 여기서는 설정을 저장하고 요청 표(live_requests)에 넣기만 한다."""
from contextlib import closing

import pandas as pd
import streamlit as st

import broker
import config
import db
import ui_kit as ui

CONFIRM = "실계좌 주문을 켭니다"
LIMIT_KEYS = [k for k in broker.LIVE_KEYS if k != "LIVE_TRADING"]


def _save(values: dict) -> None:
    """기본값과 같은 것은 지우고 다른 것만 저장(관리 모드 다른 설정과 같은 규칙)."""
    ov = config.overrides()
    for k, v in values.items():
        if v == config._DEFAULTS.get(k):
            ov.pop(k, None)
        else:
            ov[k] = v
    config.save_overrides(ov)


def render() -> None:
    with st.expander("💵 실매매(4단계 · 1주 모드) — 저금통 🟢 저점 구간에 1주 지정가 매수 · 익절/손절은 토스 OCO · 기본은 dry-run(기록만)", expanded=False):
        with closing(db.connect()) as conn:
            s = broker.status(conn)
            lim = s["limits"]
            chips = ui.chip("실주문 켜짐" if s["live"] else "dry-run(기록만)", "red" if s["live"] else "gray")
            if s["killed"]:
                chips += ui.chip(f"🛑 킬 스위치 {s['killed']}", "red")
            chips += ui.chip("1주 모드" if lim["LIVE_ONE_SHARE"] else f"종목당 ${lim['LIVE_USD_PER_TRADE']:g}", "blue") + ui.chip(f"전략 {lim['LIVE_STRATEGIES']}", "blue")
            st.markdown(chips, unsafe_allow_html=True)
            a, b, c, d = st.columns(4)
            a.metric("오늘 매수 주문", f"{s['day']['buys']} / {lim['LIVE_MAX_ORDERS_PER_DAY']}")
            b.metric("보유", f"{s['day']['open']} / {lim['LIVE_MAX_OPEN']}")
            c.metric("노출", f"${s['day']['exposure']:,.2f} / ${lim['LIVE_MAX_EXPOSURE_USD']:g}")
            d.metric("오늘 실현손익", f"${s['day']['realized']:+.2f}", help=f"−${lim['LIVE_DAILY_LOSS_USD']:g} 넘으면 킬 스위치")
            # ---- 스위치(두 단계)
            st.markdown("**실주문 스위치** — 켜려면 아래 문구를 그대로 입력하고 2단계 버튼을 누르세요. 끄는 건 한 번에.")
            k1, k2, k3 = st.columns([2, 1, 1])
            txt = k1.text_input(f"확인 문구: `{CONFIRM}`", key="live_confirm", placeholder=CONFIRM)
            if k2.button("실주문 켜기(2단계)", key="live_on2", disabled=bool(s["live"]) or txt.strip() != CONFIRM):
                _save({"LIVE_TRADING": True})
                st.success("실주문 켜짐 — 스캐너가 다음 주기부터 정규장 저금통 저점 구간에 1주 매수를 냅니다.")
                st.rerun()
            if k3.button("실주문 끄기", key="live_off", disabled=not bool(config.LIVE_TRADING)):
                _save({"LIVE_TRADING": False})
                st.info("실주문 꺼짐(dry-run). 보유 종목의 OCO 는 토스에 그대로 남아 있어요.")
                st.rerun()
            if s["killed"]:
                if st.button("킬 스위치 해제(그 뒤 다시 켜야 함)", key="live_unkill"):
                    broker.unkill()
                    st.rerun()
            elif st.button("🛑 킬 스위치(미체결 전부 취소 + 끄기)", key="live_kill"):
                broker.request(conn, "kill", "", "관리 화면")
                _save({"LIVE_TRADING": False})
                st.warning("스캐너가 1분 안에 미체결을 취소합니다. 실주문은 지금 꺼졌어요.")
                st.rerun()
            # ---- 보유·미체결
            if s["positions"]:
                st.markdown("**보유(실계좌)** — 팔 종목을 체크하고 한 번에(2026-10-29: 한 줄씩 누르던 것을 고침)")
                picked = []
                for p in s["positions"]:
                    if st.checkbox(f"{p['ticker']} · {p['qty']:g}주 @${p['avg_px']:g} · 익절 ${p.get('tp_px') or 0:g} / 손절 ${p.get('sl_px') or 0:g} · OCO {p.get('cond_id') or '없음'} · {p.get('strategy')}",
                                   key=f"live_pick_{p['ticker']}"):
                        picked.append(p["ticker"])
                b1, b2, _ = st.columns([1, 1, 3])
                if b1.button(f"선택한 {len(picked)}종목 지금 팔기", key="live_sell_sel", disabled=not picked):
                    for t in picked:
                        broker.request(conn, "sell", t, "관리 화면(선택)")
                    st.info(f"{', '.join(picked)} 매도 요청 — 스캐너가 다음 주기에 OCO 를 취소하고 지정가(−{lim['LIVE_LIMIT_SLIP_PCT']:g}%)로 냅니다.")
                if b2.button(f"전부 팔기({len(s['positions'])}종목)", key="live_sell_all"):
                    for p in s["positions"]:
                        broker.request(conn, "sell", p["ticker"], "관리 화면(전부)")
                    st.info("보유 전부 매도 요청 — 스캐너가 다음 주기에 냅니다.")
            else:
                st.caption("보유 없음")
            if s["pending"]:
                st.markdown("**미체결(실주문)**")
                st.dataframe(pd.DataFrame(s["pending"])[["ticker", "side", "qty", "limit_px", "status", "created_at", "note"]], hide_index=True, width="stretch")
            # ---- 계좌 확인(읽기만)
            if st.button("계좌·달러 매수가능금액 확인(읽기만 · 실주문 꺼져 있어도 됨)", key="live_check"):
                broker.request(conn, "check", "", "관리 화면")
                st.info("스캐너가 1분 안에 확인해 아래 요청 표와 텔레그램에 결과를 적습니다. 키가 계좌 API 를 못 쓰면 여기서 오류 코드가 나와요.")
            # ---- 1주 왕복 테스트
            st.markdown("**1주 왕복 테스트** — 1주를 사서 체결되면 바로 되팝니다(정규장 · 실주문 켜져 있어야 함). 첫 실주문 전에 한 번.")
            p1, p2 = st.columns([2, 1])
            pt = p1.text_input("티커", key="live_probe_t", placeholder="예: AAPL (유동성 좋은 저가 대형주)")
            if p2.button("1주 왕복 요청", key="live_probe", disabled=not pt.strip()):
                if not s["live"]:
                    st.error("실주문이 꺼져 있어요. 먼저 두 단계로 켜 주세요.")
                else:
                    broker.request(conn, "probe", pt.strip().upper(), "관리 화면 1주 왕복")
                    st.success(f"{pt.strip().upper()} 1주 왕복 요청 — 진행은 텔레그램과 아래 요청 표로.")
            # ---- 한도 설정
            with st.form("live_limits"):
                st.markdown("**한도 설정**(저장하면 다음 주기부터)")
                vals = {}
                cols = st.columns(3)
                for i, k in enumerate(LIMIT_KEYS):
                    kind, lo, hi, _, desc = config.SETTINGS[k]
                    cur = getattr(config, k)
                    col = cols[i % 3]
                    if kind is bool:
                        vals[k] = col.checkbox(desc, value=bool(cur), key=f"live_{k}")
                    elif kind is str:
                        vals[k] = col.text_input(desc, value=str(cur or ""), key=f"live_{k}")
                    elif kind is int:
                        vals[k] = int(col.number_input(desc, min_value=int(lo), max_value=int(hi), value=int(cur), step=1, key=f"live_{k}"))
                    else:
                        vals[k] = float(col.number_input(desc, min_value=float(lo), max_value=float(hi), value=float(cur), key=f"live_{k}"))
                if st.form_submit_button("한도 저장"):
                    _save(vals)
                    st.success("저장했어요.")
            # ---- 최근 기록·요청
            if s["recent"]:
                st.markdown("**최근 주문 기록**(dry = 기록만 · live = 실주문)")
                st.dataframe(pd.DataFrame(s["recent"])[["created_at", "mode", "status", "strategy", "ticker", "side", "qty", "limit_px", "filled_qty", "avg_px", "code", "note"]],
                             hide_index=True, width="stretch")
            try:
                req = db.read_df("SELECT id, kind, ticker, created_at, done_at, result FROM live_requests ORDER BY id DESC LIMIT 10")
            except Exception:  # noqa: BLE001
                req = pd.DataFrame()
            if not req.empty:
                st.markdown("**요청 표**(화면 → 스캐너)")
                st.dataframe(req, hide_index=True, width="stretch")
            st.caption("설계·절차: docs/broker_design_2026-10.md · 사람이 할 일은 처음 한 번(WTS 키 주문 권한 · $50 환전 · 1주 왕복 · 스위치). 11월 말 가상매매 성적과 체결 통계를 보고 $100 으로 올릴지 결정.")
