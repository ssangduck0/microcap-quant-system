"""Streamlit 대시보드:  streamlit run dashboard.py"""
import json
import os
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import time as _time_mod
_T0 = _time_mod.perf_counter()  # ⏱ 이번 화면을 그리는 데 걸린 시간(관리 모드 '화면 속도')

import numpy as np
import pandas as pd
import requests
import streamlit as st

import analytics
import cases_ui
import closewatch_ui
import config
config.apply_overrides()  # ⚙️ 관리 모드 설정
import db
import dist_ui
import timeline_ui
import tosslink_ui
import ui_kit
import chartpop
import tabs  # 🗂 한 메뉴 아래 탭 묶음(메뉴 정리 2026-10-26)
import forensic
import flowread_ui
import forensic_ui
import intel_ui
import pick
import afterscalp_ui
import piggy_ui
import rsplit_ui
import scoreboard_ui
import pumpsetup_ui
import watch_ui
import notes_ui
import report
import score_ui
import sec
import similar
import tracking_ui
import winmodel
from scoring import STATUS_LABEL, baby_shelf

db.init_db()  # 오래된 DB에도 새 테이블(리포트/메모)이 생기도록


@st.cache_resource
def _seed_notes_once() -> bool:
    """스승님 꿀팁 원문을 📝 노트에 보관(없을 때). 서버가 켜진 뒤 한 번만(예전엔 버튼 하나 누를 때마다 DB를 여러 번 읽었음)."""
    try:
        _seed_notes()
    except Exception:  # noqa: BLE001
        pass
    return True


def _seed_notes() -> None:
    import shortflow as _sf
    if _sf.TIP_TITLE not in notes_ui.list_titles():
        notes_ui.save(_sf.TIP_TITLE, _sf.TIP_TEXT + "\n\n" + _sf.CAVEAT)
    import piggy as _pg
    if _pg.PROFIT_TIP_TITLE not in notes_ui.list_titles():
        notes_ui.save(_pg.PROFIT_TIP_TITLE, _pg.PROFIT_TIP_TEXT)
    import afterscalp as _af
    if _af.TIP_TITLE not in notes_ui.list_titles():
        notes_ui.save(_af.TIP_TITLE, _af.TIP_TEXT)
    import flowread as _fr
    if _fr.TIP_TITLE not in notes_ui.list_titles():
        notes_ui.save(_fr.TIP_TITLE, _fr.TIP_TEXT)
    import pumpsetup as _ps
    for _title, _text in _ps.TIPS.items():
        if _title not in notes_ui.list_titles():
            notes_ui.save(_title, _text)


_seed_notes_once()


@st.cache_data(ttl=60, show_spinner=False)
def _import_inbox_throttled(_minute: int) -> dict:
    """Cowork 자동 공시분석 결과(inbox) 가져오기 — 1분에 한 번만 폴더를 봄(예전엔 매 화면마다)."""
    return forensic.import_inbox()


try:
    _fx_new = _import_inbox_throttled(int(_time_mod.time() // 60))
    _fx_seen = st.session_state.setdefault("_fx_toasted", set())
    for _t in _fx_new["imported"]:
        if _t not in _fx_seen:
            _fx_seen.add(_t)
            st.toast(f"🧾 공시분석 자동 저장: {_t}")
    for _t, _why in _fx_new["errors"]:
        if ("err", _t) not in _fx_seen:
            _fx_seen.add(("err", _t))
            st.toast(f"🧾 {_t} 자동 스캔 실패: {_why[:80]}")
except Exception:  # noqa: BLE001
    pass
st.set_page_config(layout="wide", page_title="초소형주 퀀트 대시보드", page_icon="🚀")
DISCLAIMER = "점수·참고 레벨·희석 판정은 규칙 기반 계산값이며 투자 권유가 아닙니다. 희석 상태는 SEC 공시 키워드 검출 결과로, 원문 확인이 필요합니다."


@st.cache_data(ttl=60)
def exchange_rate() -> tuple[float, str]:
    """스캐너가 토스에서 받아 DB에 기록한 환율을 우선 사용하고, 오래됐거나 없으면 공개 API, 그것도 실패하면 기본값."""
    m = db.get_meta("usdkrw")
    if m and db.is_fresh(m["updated_at"], 0.25):
        return float(m["value"]), "토스"
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=3)
        r.raise_for_status()
        return float(r.json()["rates"]["KRW"]), "open.er-api"
    except Exception:  # noqa: BLE001
        return 1380.0, "기본값(조회 실패)"


@st.cache_data(ttl=30)
def us_session() -> str:
    m = db.get_meta("us_session")
    return m["value"] if m and db.is_fresh(m["updated_at"], 0.25) else "확인 불가"


@st.cache_data(ttl=15)
def load_snapshots() -> pd.DataFrame:
    return db.read_df("SELECT * FROM daily_snapshots ORDER BY date DESC, last_seen DESC")


@st.cache_data(ttl=15)
def load_dilution() -> dict:
    df = db.read_df("SELECT * FROM dilution")
    return {r["ticker"]: r for r in df.to_dict("records")}


@st.cache_data(ttl=60)
def load_forward() -> pd.DataFrame:
    return analytics.forward_returns()


@st.cache_data(ttl=30)
def load_filings() -> pd.DataFrame:
    return db.read_df("SELECT ticker, filed, form, items, tags, url FROM filing_cache WHERE tags != '[]' ORDER BY filed DESC LIMIT 300")


@st.cache_data(ttl=120)
def load_model_cached(name: str):
    return winmodel.load_model(name)


@st.cache_data(ttl=300)
def load_events_cached() -> pd.DataFrame:
    return similar.load_events()


@st.cache_resource
def _speed_store() -> list:
    return []


def _speed_log() -> list:
    return list(_speed_store())


def kst(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert("Asia/Seoul").dt.strftime("%m-%d %H:%M")


def label(status: str) -> str:
    return STATUS_LABEL.get(status, status)


try:
    snaps = load_snapshots()
except Exception:  # noqa: BLE001
    snaps = pd.DataFrame()
if snaps.empty:
    st.info("아직 스캐너 데이터가 없습니다. `python scanner.py` 를 실행하세요. (SEC_USER_AGENT 환경변수 필요) — 과거 사례는 아래에서 볼 수 있습니다.")
    st.caption(f"지금 여는 DB 파일: `{config.DB_PATH}` — 예전 데이터가 안 보이면 이 경로가 `.env` 의 QUANT_DB 와 같은지 확인하세요.")
    st.markdown("---")
    cases_ui.render()
    st.stop()

NAV_CSS = """
<style>
/* 공통: 링크 칸의 음수 여백 제거(설명 줄 겹침 방지) · 글자 크기 */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
section[data-testid="stSidebar"] [data-testid="stElementContainer"], section[data-testid="stSidebar"] .stElementContainer,
section[data-testid="stSidebar"] .element-container, section[data-testid="stSidebar"] div:has(> .stPageLink),
section[data-testid="stSidebar"] div:has(> [data-testid="stPageLink"]) { margin-top: 0 !important; margin-bottom: 0 !important; }
section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] { padding: .45rem .5rem !important; margin: 0 !important; white-space: nowrap; border-radius: .5rem; }
section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p, section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] span,
section[data-testid="stSidebar"] .stPageLink a p, section[data-testid="stSidebar"] .stPageLink a span { font-size: 1.05rem !important; line-height: 1.35 !important; }
section[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p { font-weight: 600 !important; }
.navdesc { font-size: .82rem; line-height: 1.3; opacity: .62; margin: -.15rem 0 .55rem 2.65rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.navsec { font-size: .8rem; font-weight: 700; opacity: .55; letter-spacing: .03em; margin: .9rem 0 .35rem .35rem; padding-top: .6rem;
  border-top: 1px solid rgba(128,128,128,.25); white-space: nowrap; }
.navsec.first { border-top: none; margin-top: .2rem; padding-top: 0; }
.navfoot { font-size: .8rem; opacity: .6; margin: 1rem 0 0 .35rem; padding-top: .6rem; border-top: 1px solid rgba(128,128,128,.25); white-space: nowrap; }
section[data-testid="stSidebar"] [data-testid="stTextInput"] { margin-bottom: .4rem; }
/* PC(넓은 화면): 왼쪽 아이콘 줄 — 평소 아이콘만, 마우스를 올리면 펼쳐져 화면 위에 겹침 */
@media (min-width: 900px) {
  [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarHeader"], [data-testid="stSidebarResizeHandle"] { display: none !important; }
  section[data-testid="stSidebar"] { position: fixed !important; top: 0; left: 0; bottom: 0; height: 100vh !important; width: 64px !important; min-width: 64px !important;
    max-width: 64px !important; transform: none !important; z-index: 999990; overflow-x: hidden !important; transition: all .18s ease; }
  section[data-testid="stSidebar"]:hover { width: 360px !important; min-width: 360px !important; max-width: 360px !important; box-shadow: 6px 0 24px rgba(0,0,0,.35); }
  section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { width: 360px !important; padding-top: .6rem; }
  section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: .4rem .7rem 3rem .7rem !important; }
  [data-testid="stMain"], section.main { margin-left: 64px !important; }
  section[data-testid="stSidebar"]:not(:hover) .navdesc, section[data-testid="stSidebar"]:not(:hover) .navsec, section[data-testid="stSidebar"]:not(:hover) .navfoot,
  section[data-testid="stSidebar"]:not(:hover) [data-testid="stTextInput"],
  section[data-testid="stSidebar"]:not(:hover) [data-testid="stPageLink-NavLink"] p,
  section[data-testid="stSidebar"]:not(:hover) [data-testid="stPageLink-NavLink"] [data-testid="stMarkdownContainer"] { opacity: 0; }
}
/* 휴대폰(좁은 화면): Streamlit 기본 메뉴(왼쪽 위 버튼으로 열고 닫기), 설명은 줄바꿈 허용 */
@media (max-width: 899px) {
  .navdesc { white-space: normal; }
  [data-testid="stMainBlockContainer"], .block-container { padding-left: .7rem !important; padding-right: .7rem !important; }
}
</style>
"""

import access  # 👥 방문객 링크(?guest=토큰): 비밀번호 없이 열람만, 기간 제한
_gq = st.query_params.get("guest")
if _gq and not st.session_state.get("_pw_ok"):
    _gi = access.check(_gq)
    if not _gi:
        st.error("이 방문객 링크는 만료됐거나 취소됐어요. 링크를 보낸 사람에게 새 링크를 받아 주세요.")
        st.stop()
    if st.session_state.get("_guest", {}).get("token") != _gi["token"]:  # 이 창에서 처음 열 때: 접속 기록 · 기기 확인 · 알림
        try:
            _hd = dict(st.context.headers)
        except Exception:  # noqa: BLE001
            _hd = {}
        _ci = access.client_info(_hd)
        _vr = access.record_visit(_gi["token"], _ci)
        st.session_state["_guest_ip"] = access.short_ip(_ci["ip"]) if not _ci["ip"].startswith("로컬") else ""
        import notify as _nt
        if not _vr["allowed"]:
            if config.GUEST_ALERTS:
                _nt.send_telegram(f"🚫 방문객 링크 '{_gi['name']}' 를 다른 기기에서 열려고 해서 막았어요 · {_ci['device']} · {_ci['ip']} ({_ci['country']}) — 링크가 퍼졌을 수 있어요")
            st.error("이 방문객 링크는 처음 연 기기에서만 열 수 있어요. 링크를 보낸 사람에게 문의해 주세요.")
            st.stop()
        access.touch(_gi["token"])
        if config.GUEST_ALERTS:
            _nt.send_telegram(("⚠️ 새 기기에서 방문객 접속" if _vr["new_device"] else "👥 방문객 접속") + f" · {_gi['name']} · {_ci['device']} · {_ci['ip']} ({_ci['country']})")
    st.session_state["_guest"] = _gi
elif st.session_state.get("_guest"):
    _gi = access.check(st.session_state["_guest"]["token"])
    if not _gi:
        st.session_state.pop("_guest", None)
        st.error("방문객 이용 시간이 끝났어요. 계속 보려면 새 링크를 받아 주세요.")
        st.stop()
    st.session_state["_guest"] = _gi
if access.is_guest():  # 화면을 옮기면 주소의 ?guest= 가 빠져 새로고침 때 잠기던 문제 → 언제나 주소에 토큰 유지
    try:
        if st.query_params.get("guest") != st.session_state["_guest"]["token"]:
            st.query_params["guest"] = st.session_state["_guest"]["token"]
    except Exception:  # noqa: BLE001
        pass
if access.guest_only() and not access.is_guest():  # 방문객 전용 서버: 비밀번호 입력창 없이 링크로만
    st.warning("이 주소는 방문객 링크로만 열 수 있어요. 받은 링크를 그대로 열어 주세요.")
    st.stop()
if access.is_guest() and not st.session_state.get("_guest_ok"):  # 입장 전 경고·동의
    st.markdown("### ⚠️ 방문객 안내")
    st.warning(access.notice())
    st.caption(f"초대 이름: {st.session_state['_guest']['name']} · 남은 시간 {access.left_text(st.session_state['_guest']['left_min'])}")
    if st.button("위 내용에 동의하고 보기", key="_guest_agree", type="primary"):
        access.agree(st.session_state["_guest"]["token"])
        st.session_state["_guest_ok"] = True
        st.rerun()
    st.stop()
if access.is_guest():  # 화면 전체 워터마크(캡처하면 누가 퍼뜨렸는지 남음)
    _wm_ip = st.session_state.get("_guest_ip", "")
    st.markdown(access.watermark_css(f"{st.session_state['_guest']['name']} · {datetime.now(timezone.utc).astimezone().strftime('%m/%d %H:%M')}"
                                     + (f" · {_wm_ip}" if _wm_ip else "") + " · 무단 배포 금지"), unsafe_allow_html=True)
def _guest_banner(lite: bool) -> None:
    g = st.session_state["_guest"]
    if lite:  # 휴대폰: 한 줄(예전 세 줄이 화면마다 위쪽을 차지)
        st.caption(f"👀 방문객 · 열람 전용 · 남은 {access.left_text(g['left_min'])}")
    else:
        st.info(f"👀 방문객 모드 · 열람 전용 · {g['name']} · 남은 시간 {access.left_text(g['left_min'])} "
                "— 개인 화면(관리·워치리스트·저금통·노트·일정)과 변경 버튼은 보이지 않아요. 처음이면 왼쪽 메뉴의 📖 가이드북부터 보세요.")
_PW = os.environ.get("DASH_PASSWORD", "").strip()
if _PW and not st.session_state.get("_pw_ok") and not access.is_guest() and access.pw_locked():  # 비밀번호를 계속 틀리면 잠금
    st.error(f"비밀번호를 여러 번 틀려서 잠시 잠겼어요. {access.pw_locked():.0f}분 뒤에 다시 시도하세요.")
    st.stop()
if _PW and not st.session_state.get("_pw_ok") and not access.is_guest():
    _in = st.text_input("대시보드 비밀번호", type="password", key="_pw_in")
    if _in and _in == _PW:
        st.session_state["_pw_ok"] = True
        st.rerun()
    if _in:
        import time as _t
        _t.sleep(1.5)  # 틀린 비밀번호를 빠르게 여러 번 넣지 못하게
        if access.pw_fail():  # 10분 안 10번 → 15분 잠금 + 알림
            import notify as _nt
            _nt.send_telegram("🔒 대시보드 비밀번호를 10분 안에 10번 틀려서 15분 동안 잠갔어요. 본인이 아니면 비밀번호를 바꾸세요.")
            st.rerun()
        st.error("비밀번호가 다릅니다.")
    st.stop()

ui_kit.inject()  # 깔끔한 화면(글꼴·카드·칩)
FX, FX_SRC = exchange_rate()
dil_map = load_dilution()
snaps["희석상태"] = snaps["dilution_status"].map(label)

last_seen = pd.to_datetime(snaps["last_seen"], utc=True).max()
age_min = (datetime.now(timezone.utc) - last_seen).total_seconds() / 60


def scanner_status(age_min: float, beat_raw: str | None, now: datetime | None = None) -> tuple[bool, str]:
    """(동작 중?, 설명). 💓 스캐너 신호(scanner_beat)로 판단 — 한 회차가 10분을 넘겨도 '멈춤'으로 잘못 보이지 않게."""
    now = now or datetime.now(timezone.utc)
    if age_min < 10:
        return True, ""
    try:
        b = json.loads(beat_raw) if beat_raw else None
    except (TypeError, ValueError):
        b = None
    if not b or not b.get("at"):
        return False, ""
    at = datetime.fromisoformat(b["at"])
    beat_min = (now - at).total_seconds() / 60
    if b.get("phase") == "쉬는 중" and b.get("next"):
        nxt = datetime.fromisoformat(b["next"])
        if now <= nxt + timedelta(minutes=15):
            return True, f"쉬는 중 · 다음 {nxt.astimezone(ZoneInfo('Asia/Seoul')):%H:%M}"
        return False, ""
    if beat_min < 45:
        return True, f"{b.get('phase', '작업 중')} · {beat_min:,.0f}분째"
    return False, ""


SCANNER_OK, SCANNER_NOTE = scanner_status(age_min, (db.get_meta("scanner_beat") or {}).get("value"))


def _header() -> None:
    """🏠 홈 고정 정보(제목·안내·세션·스캐너·발견 종목·환율) — 홈에서만 크게. 다른 화면은 안내 한 줄만."""
    st.title("🚀 초소형주 퀀트 대시보드")
    st.caption(DISCLAIMER)
    ui_kit.cards([{"t": "미국장 세션", "v": us_session(), "s": "토스 장 캘린더 기준", "accent": True},
                  {"t": "스캐너", "v": "🟢 동작 중" if SCANNER_OK else "🔴 멈춤", "s": f"마지막 갱신 {last_seen.tz_convert('Asia/Seoul'):%m-%d %H:%M}"
                   + ("" if age_min < 10 else f" · {age_min:,.0f}분 전") + (f" · {SCANNER_NOTE}" if SCANNER_NOTE else "")},
                  {"t": "발견 종목", "v": f"{snaps['ticker'].nunique():,}", "s": f"누적 종목-일 {len(snaps):,}"},
                  {"t": "환율", "v": f"{FX:,.1f}원", "s": f"1 USD · {FX_SRC}"}])

def fill_prev_scores(v: pd.DataFrame, allsnaps: pd.DataFrame) -> pd.DataFrame:
    """오늘 승률 점수(정규장에서만 계산)가 비어 있는 행은 같은 종목의 가장 최근 이전 거래일 점수로 채우고 '점수 기준'에 날짜를 적는다."""
    out = v.copy()
    out["score_basis"] = np.where(out["win_score"].notna(), "오늘 정규장", "")
    prev = allsnaps[allsnaps["win_score"].notna()][["date", "ticker", "win_score", "win_p"]]
    need = out["win_score"].isna()
    if prev.empty or not need.any():
        return out
    prev = prev.sort_values("date")
    for i in out.index[need]:
        p = prev[(prev["ticker"] == out.at[i, "ticker"]) & (prev["date"] < out.at[i, "date"])]
        if not p.empty:
            r = p.iloc[-1]
            out.at[i, "win_score"], out.at[i, "win_p"] = r["win_score"], r["win_p"]
            out.at[i, "score_basis"] = f"전 거래일 {r['date'][5:]}"
    return out


FILTER_DEFAULTS = {"flt_period": "최신 거래일", "flt_status": list(STATUS_LABEL), "flt_minq": 0, "flt_succ": 10}


def filtered_view():
    """📊 화면의 필터(마지막으로 쓴 값)로 거른 스냅샷과 성공 기준. 🎯 화면의 참고 보드도 같은 값을 쓴다."""
    g = lambda k: st.session_state.get(k, st.session_state.get("_" + k, FILTER_DEFAULTS[k]))  # noqa: E731
    dates = sorted(snaps["date"].unique(), reverse=True)
    dates = dates[:1] if g("flt_period") == "최신 거래일" else (dates[:7] if g("flt_period") == "최근 7거래일" else dates)
    v = snaps[snaps["date"].isin(dates) & snaps["dilution_status"].isin(g("flt_status")) & (snaps["quant_score"] >= g("flt_minq"))].copy()
    return v, g("flt_succ")


view, succ_target = filtered_view()

PAGES = [  # (키, 제목, 아이콘, 설명, 묶음) — 김곰 워치리스트처럼 카테고리로. 2026-10-26 메뉴 정리 36 → 27: 옛 키(lite.ALIAS)는 새 화면의 탭으로 자동 이동
    ("home", "홈", "🏠", "시장 지표 · 오늘의 브리핑 · 도구 바로가기", "홈"),
    ("guide", "가이드북", "📖", "처음 쓰는 분을 위한 사용법·화면 설명·용어 사전", "홈"),
    ("rank", "종합 순위", "🏁", "신호 강도 × 출발 임박도(⏱ 3일 이내·1~2주) 순위", "오늘"),
    ("alerts", "공시 알림", "🔔", "SEC 실시간 공시 호재·악재·태그 피드와 리포트", "오늘"),
    ("news", "뉴스 모음", "📰", "보도자료 피드(PR Newswire 등) · 우리 종목 · 호재/악재", "오늘"),
    ("movers", "급상승/급하락", "📈", "토스 순위 상위 100 · 희석 배지 · 산업 · 뉴스/공시 수(B단계 2026-10-27)", "오늘"),
    ("accum", "수급", "🧲", "매집 의심 · 세력·셋업 · 장마감 펌핑 체크리스트(탭)", "발굴"),
    ("themes", "테마", "🏷", "오늘 움직인 테마·테마별 종목·직접 지정", "발굴"),
    ("fundscan", "펀드스캔", "💰", "워런트 행사가·현금 런웨이로 본 주가 부양 유인", "발굴"),
    ("effect", "EFFECT 감지", "⚡", "등록 효력 → 희석 임박 종목", "발굴"),
    ("insider", "내부자 매수", "👤", "임원·이사·10% 주주의 장내 매수(Form 4)", "발굴"),
    ("regsho", "Reg SHO 감시", "📛", "공매도 결제 실패 명단 순위·연속일수·공매도 현황", "발굴"),
    ("squeeze", "스퀴즈 랭크", "🧨", "Reg SHO·대차·공매도 비중으로 본 숏스퀴즈 압력", "발굴"),
    ("darkpool", "다크풀", "🕶", "장외(다크풀) 거래 비중 상위 · 5일 추이 · 급등·연속상승·매집 동반(B단계 2026-10-27)", "발굴"),
    ("rsplit", "병합 후 레이더", "🔁", "역분할 후 반등 확률·예상 가격 + 병합 예정(시장 전체 · 공시 요약에서)", "발굴"),
    ("holders", "대량 보유", "🏦", "13D(경영개입형)·13G(단순투자형) 기관 대량 보유", "발굴"),
    ("pick", "PICK +30%", "🎯", "회사 목표가 +30~150% · PICK 변동 · AI PICK · 전체 후보(회사 압박)", "선별"),
    ("setup3", "3대 조건", "✅", "돈 들어온 거래량(OBV)·지지/과매도·희석 없음", "선별"),
    ("piggy", "저금통", "🐷", "저가 박스권 종목 담기·저점 알림·매매 기록", "선별"),
    ("after", "애프터 스캘핑", "🌙", "애프터마켓 급등 후 이동평균 눌림 진입", "선별"),
    ("lookup", "종목", "🏢", "기업 분석 · 종목 리포트 · 퀀트 스냅샷 · 차트(탭) — 티커 하나를 한 곳에서", "종목"),
    ("score", "검증", "🏆", "성과 공표 · 점수 검증 · 타임머신 · 가상매매(탭)", "추적"),
    ("eventlab", "이벤트 연구", "🔬", "3년치 공시·보도자료 뒤 주가 반응 · 사건 종류별 성과 · 가중치 제안", "추적"),
    ("cases", "과거 사례", "📚", "10년 급락 사건·분포·공시별 결과", "추적"),
    ("filings", "희석 공시 타임라인", "📅", "희석 키워드 공시 시간축", "추적"),
    ("watch", "워치리스트", "⭐", "관심 종목·물량 장부·Cowork 자동 공시분석", "관리"),
    ("events", "일정", "🗓", "주총·상장유지 기한·만기·락업·호재", "관리"),
    ("notes", "노트", "📝", "메모·스승님 꿀팁 원문", "관리"),
    ("admin", "관리 모드", "⚙️", "알림·기능·숫자 설정, 감시 종목, 텔레그램 테스트, 로그", "관리"),
]
if access.is_guest():  # 👥 방문객: 개인 화면 빼기
    PAGES = [p for p in PAGES if p[0] not in access.HIDDEN_PAGES]
_CAT_ORDER = {}
for _p in PAGES:
    _CAT_ORDER.setdefault(_p[4], len(_CAT_ORDER))
PAGES = sorted(PAGES, key=lambda p: _CAT_ORDER[p[4]])  # 같은 묶음끼리 붙게(안정 정렬 — 묶음 안 순서는 그대로)
ALL_PAGES = os.environ.get("QUANT_TEST_ALL_PAGES") == "1"  # 테스트: 예전처럼 모든 화면을 한 번에(탭)
import lite  # 📱 간략 모드(휴대폰 기본): 꼭 필요한 화면만
try:
    _UA = dict(st.context.headers).get("User-Agent", "") or dict(st.context.headers).get("user-agent", "")
except Exception:  # noqa: BLE001
    _UA = ""
LITE = False if ALL_PAGES else lite.decide(st.session_state, st.query_params.get("v"), _UA)
if not ALL_PAGES and "v" in st.query_params:  # 주소의 ?v= 는 한 번만 적용(남아 있으면 버튼으로 바꿔도 되돌아감)
    del st.query_params["v"]
FULL_PAGES = PAGES
if access.is_guest():
    _guest_banner(LITE)
if LITE:
    _lk = set(lite.pages())
    PAGES = [p for p in PAGES if p[0] == "home" or p[0] in _lk]
if ALL_PAGES:
    _TABS = dict(zip([p[0] for p in PAGES], st.tabs([f"{p[2]} {p[1]}" for p in PAGES])))
    PAGE = None
else:
    # 화면은 전부 등록(간략 모드에서도 '종목 보기' 버튼·주소로 기업 분석 등에 갈 수 있게), 메뉴에는 PAGES(간략이면 일부)만 그림
    _PG = {p[0]: st.Page(lambda: None, title=p[1], icon=p[2], url_path=p[0], default=(p[0] == "home")) for p in FULL_PAGES}
    _TITLE = {p[0]: (p[1], p[2]) for p in FULL_PAGES}
    for _old, (_new, _tab) in lite.ALIAS.items():  # 🔀 옛 주소(/snap, /report …)도 열리게 숨은 화면으로 등록 → 아래에서 새 위치의 탭으로 보냄
        if _new in _TITLE:
            _PG[_old] = st.Page(lambda: None, title=_TITLE[_new][0], icon=_TITLE[_new][1], url_path=_old)
    _cur = st.navigation(list(_PG.values()), position="hidden")  # 메뉴는 아래 왼쪽 아이콘 줄로 직접 그림
    PAGE = next((k for k, v in _PG.items() if v.url_path == _cur.url_path), "home")
    _env_page = os.environ.get("QUANT_TEST_PAGE")
    PAGE = _env_page or PAGE  # 테스트에서 화면 지정
    if PAGE in lite.ALIAS:  # 옛 화면 키 → 새 화면 + 탭
        _new, _tab = lite.ALIAS[PAGE]
        if _tab:
            st.session_state[f"_want_tab_{_new}"] = _tab
        if _env_page or _new not in _PG:
            PAGE = _new
        else:
            st.switch_page(_PG[_new])
    st.session_state["_pages"] = _PG  # 다른 화면에서 tabs.go() 로 옮길 때
    st.session_state["_pg_lookup"] = _PG["lookup"]  # 다른 화면에서 '종목 보기'로 이동할 때
    st.markdown(NAV_CSS, unsafe_allow_html=True)
    with st.sidebar:
        _q = st.text_input("🔎 종목 검색", key="nav_search", placeholder="티커 입력 후 Enter", label_visibility="collapsed")
        if _q.strip() and _q.strip().upper() != st.session_state.get("_nav_last"):
            st.session_state["_nav_last"] = _q.strip().upper()
            st.session_state["lookup_ticker"] = _q.strip().upper()
            st.switch_page(_PG["lookup"])
        _sec = None
        for _k, _t, _i, _desc, _s in PAGES:
            if _s != _sec:
                st.markdown(f'<div class="navsec{" first" if _sec is None else ""}">{_s}</div>', unsafe_allow_html=True)
                _sec = _s
            st.page_link(_PG[_k], label=_t, icon=_i)
            st.markdown(f'<div class="navdesc">{_desc}</div>', unsafe_allow_html=True)
        _tun = "" if access.is_guest() else ((db.get_meta("tunnel_url") or {}).get("value") or "")
        st.markdown(f'<div class="navfoot">💱 환율 1 USD = {FX:,.2f} KRW · {FX_SRC}'
                    + (f'<br>📱 휴대폰 주소: <a href="{_tun}" target="_blank">{_tun.replace("https://", "")}</a>' if _tun else "") + f'<br>메뉴 v4 · {"📱 간략 모드" if LITE else "🖥 전체 모드"}</div>', unsafe_allow_html=True)


if ALL_PAGES or PAGE == "home":  # 🏠 홈 고정 정보는 홈에서만
    _header()
else:
    st.caption("⚠️ 규칙 기반 추정이며 투자 권유가 아닙니다.")
try:  # 🌎 시장 지표: 홈에서는 크게(홈 화면이 그림), 다른 화면에서는 한 줄로(간략 모드는 생략)
    import macro_ui
    if not ALL_PAGES and PAGE != "home" and not LITE:
        macro_ui.render_line()
except Exception as _e:  # noqa: BLE001
    st.caption(f"시장 지표를 표시하지 못했어요: {_e}")


MOBILE_TABS = [("home", "홈", "🏠"), ("rank", "오늘", "🏁"), ("themes", "발굴", "🏷"), ("pick", "선별", "🎯"), ("lookup", "종목", "🏢"),
               ("score", "추적", "🏆"), ("admin", "관리", "⚙️")]
if not ALL_PAGES and LITE:  # 📱 간략 모드: 아래 메뉴 = 묶음(홈·오늘·발굴·선별·추적), 화면 위 = 그 묶음의 화면들
    MOBILE_TABS = [(k, c, i) for c, i, k in lite.categories(PAGES, list(_PG))]
    _cat = next((p[4] for p in PAGES if p[0] == PAGE), "홈")
    _same = [p for p in PAGES if p[4] == _cat and p[0] != "home"]
    if PAGE != "home" and len(_same) > 1:
        try:
            _subnav = st.container(key="qk_subnav", horizontal=True, gap="small")
        except TypeError:  # 옛 Streamlit: 가로 상자 없음 → 세로로라도
            _subnav = st.container(key="qk_subnav")
        with _subnav:
            for _k, _t, _i, _d, _s in _same:
                st.page_link(_PG[_k], label=_t, icon=_i)
    _cur_tab = next((k for c, i, k in lite.categories(PAGES, list(_PG)) if c == _cat), "home")
if not ALL_PAGES:  # 📱 휴대폰 화면에서만 보이는 아래 고정 메뉴(누르면 새로고침 없이 이동)
    _mt = [x for x in MOBILE_TABS if x[0] in _PG]
    if LITE and _cur_tab != PAGE and _cur_tab in [x[0] for x in _mt]:  # 같은 묶음의 다른 화면에 있어도 아래 메뉴 칸을 켜진 것으로 표시
        _n = [x[0] for x in _mt].index(_cur_tab) + 1
        st.markdown(f'<style>.st-key-qk_bottomnav [data-testid="stColumn"]:nth-child({_n}) [data-testid="stPageLink-NavLink"]'
                    '{ background: rgba(128,128,128,.22); }</style>', unsafe_allow_html=True)
    with st.container(key="qk_bottomnav"):
        for _c, (_k, _l, _i) in zip(st.columns(len(_mt)), _mt):
            _c.page_link(_PG[_k], label=_l, icon=_i)
    if "lookup" in _PG:
        st.session_state["_pg_lookup"] = _PG["lookup"]


def page(key: str):
    """for _ in page(키): — 선택된 화면만 그린다(테스트에서는 모든 화면을 탭으로)."""
    if access.is_guest() and key in access.HIDDEN_PAGES:
        return
    if ALL_PAGES:
        with _TABS[key]:
            yield
    elif key == PAGE:
        yield

# ----------------------------------------------------------------- 📊 퀀트 스냅샷(🏢 종목 화면의 탭)
def _render_snap() -> None:
    for _k in FILTER_DEFAULTS:  # 다른 화면에 다녀와도 필터 값 유지(화면에 없던 위젯 값은 지워지므로 따로 보관)
        if _k not in st.session_state and "_" + _k in st.session_state:
            st.session_state[_k] = st.session_state["_" + _k]
    with st.expander("필터", expanded=False):
        _f1, _f2, _f3, _f4 = st.columns(4)
        _f1.selectbox("기간", ["최신 거래일", "최근 7거래일", "전체"], key="flt_period")
        _f2.multiselect("희석 상태", list(STATUS_LABEL), default=list(STATUS_LABEL), format_func=label, key="flt_status")
        _f3.slider("최소 퀀트 점수", 0, 100, 0, key="flt_minq")
        _f4.slider("유사 사례 성공 기준: 다음날 고가 +N%", 1, 50, 10, key="flt_succ",
                   help="과거 급락 사건 중 다음날 고가가 사건일 종가 대비 이 값 이상 오른 비율을 '성공률'로 봅니다.")
    for _k in FILTER_DEFAULTS:
        st.session_state["_" + _k] = st.session_state[_k]
    view, succ_target = filtered_view()
    st.subheader("퀀트 스냅샷 (종목-거래일당 1행)")
    if view.empty:
        st.info("조건에 맞는 종목이 없습니다.")
    else:
        ev_all = load_events_cached()
        view = fill_prev_scores(view, snaps)  # 정규장 전(프리·애프터)에는 오늘 승률 점수가 없으므로 전 거래일 점수를 보여 줌
        view = similar.annotate(view, ev_all, succ_target)
        f52a, f52b, f52c = st.columns([2, 1, 1])
        only52 = f52a.checkbox("52주 바닥권 + 거래량 급증만 보기", False, key="f52_on", help="1년 일봉 최저가 근처이면서 오늘 거래량이 평소보다 크게 터진 종목")
        near52 = f52b.slider("52주 저점 +% 이내", 5, 50, 15, key="f52_near", disabled=not only52)
        vol52 = f52c.slider("거래량 배수 ≥", 1.5, 20.0, 3.0, 0.5, key="f52_vol", disabled=not only52)
        if only52:
            import piggy_ui
            _p1 = piggy_ui.prices_1y(tuple(sorted(view["ticker"].unique())))
            _low = {k: float(v["Low"].dropna().min()) for k, v in _p1.items() if v is not None and not v.empty}
            view = view.assign(_low52=view["ticker"].map(_low))
            view = view[(view["price"] <= view["_low52"] * (1 + near52 / 100)) & (view["volume_mult"] >= vol52)]
            st.caption(f"52주 바닥권(+{near52}% 이내) + 거래량 {vol52:g}배 이상: {len(view)}행")
            if view.empty:
                st.info("조건에 맞는 종목이 없습니다.")
                st.stop()
        t = pd.DataFrame({
            "거래일": view["date"], "갱신(KST)": kst(view["last_seen"]), "티커": view["ticker"],
            "거래소": view["exchange"], "현재가($)": view["price"], "현재가(원)": (view["price"] * FX).round(0),
            "낙폭(%)": view["drawdown_pct"], "오늘 등락(%)": view["day_change_pct"], "거래량 배수": view["volume_mult"],
            "매수체결 비중(%)": view["buy_pressure"], "유통주식(백만)": view["float_shares"] / 1e6,
            "퀀트점수": view["quant_score"], "승률 점수": view["win_score"], "예상 성공확률(%)": view["win_p"] * 100,
            "유사 사례 수": view["sim_n"], "유사 성공률(%)": view["sim_success"], "희석상태": view["희석상태"],
            "진입참고($)": view["entry_ref"], "손절참고($)": view["stop_ref"], "목표참고($)": view["target_ref"],
        })
        t.insert(list(t.columns).index("승률 점수") + 1, "점수 기준", view["score_basis"].values if "score_basis" in view else "")
        t.insert(list(t.columns).index("유사 성공률(%)") + 1, "예상 다음날 고가(원)",
                 [("" if pd.isna(a) or pd.isna(b) else f"{p * (1 + a / 100) * FX:,.0f}~{p * (1 + b / 100) * FX:,.0f}") for p, a, b in zip(view["price"], view["sim_hi_q25"], view["sim_hi_q75"])])
        t.insert(list(t.columns).index("예상 다음날 고가(원)") + 1, "5일 내 기대 최고(원)", [None if pd.isna(u) else p * (1 + u / 100) * FX for p, u in zip(view["price"], view["sim_up5_med"])])
        if "_low52" in view:
            t.insert(list(t.columns).index("현재가(원)") + 1, "52주 저점 대비(%)", ((view["price"] / view["_low52"] - 1) * 100).values)
        import regsho as _rg
        with closing(db.connect()) as _c:
            _sho = _rg.streaks(_c)
        t.insert(list(t.columns).index("희석상태") + 1, "Reg SHO", [_rg.label(_sho.get(x)) for x in view["ticker"]])
        import multisignal as _msig
        _ms = _msig.collect()
        t.insert(list(t.columns).index("티커") + 1, "멀티 시그널", [_msig.label(_ms.get(x)) for x in view["ticker"]])
        import rank_ui as _rku
        t.insert(list(t.columns).index("티커") + 1, "종합 순위", _rku.column(view["ticker"]))
        _lm = watch_ui.watch.lists_map()
        t.insert(list(t.columns).index("티커") + 1, "워치", [watch_ui.LIST_ICON.get(_lm.get(x), "") for x in view["ticker"]])
        _ins = list(t.columns).index("희석상태") + 1  # 공통 인텔(체결강도·거래정지·공매도·장중 공시) 요약 열
        t = pd.concat([t.iloc[:, :_ins], intel_ui.summary_frame(view), t.iloc[:, _ins:]], axis=1)
        _fx = forensic.latest_dates()
        t.insert(list(t.columns).index("워치") + 1, "공시분석", [_fx.get(x, "") for x in view["ticker"]])
        t.insert(list(t.columns).index("티커") + 1, "토스", tosslink_ui.links(view["ticker"]))
        _ids = list(view["ticker"]) if view["ticker"].is_unique else [f"{a}|{b}" for a, b in zip(view["ticker"], view["date"])]
        _pick = pick.clickable(t, _ids, "snap_table", hide_index=True, width="stretch", column_config={**intel_ui.COLUMN_CONFIG, "토스": tosslink_ui.COLUMN,
            "공시분석": st.column_config.TextColumn(help="공시 분석 프로젝트(덕구 스캔) 보고서를 저장한 날짜. 행을 누르면 아래 종목 상세에서 볼 수 있음"),
            "현재가($)": st.column_config.NumberColumn(format="%.4f"),
            "현재가(원)": st.column_config.NumberColumn(format="%d"),
            "낙폭(%)": st.column_config.NumberColumn(format="%.1f", help="20일 고점 대비"),
            "오늘 등락(%)": st.column_config.NumberColumn(format="%.1f", help="전일 종가 대비"),
            "유사 사례 수": st.column_config.NumberColumn(format="%d", help="오늘 등락률 ±5%p, 거래량 배수 ×/÷2 이내인 과거 급락 사건 수(오늘 등락률이 -10% 이하일 때만 계산)"),
            "유사 성공률(%)": st.column_config.NumberColumn(format="%.1f", help="그 사건들 중 다음날 고가가 +N%(사이드바) 이상이었던 비율. 생존편향으로 낙관적일 수 있음."),
            "예상 다음날 고가(원)": st.column_config.TextColumn(help="비슷한 과거 급락 사건들의 다음날 고가 중간 50%(25~75%) 범위를 지금 가격에 적용"),
            "5일 내 기대 최고(원)": st.column_config.NumberColumn(format="%,.0f", help="비슷한 과거 사건의 5거래일 안 최고 상승 중앙값을 지금 가격에 적용"),
            "52주 저점 대비(%)": st.column_config.NumberColumn(format="%+.0f"),
            "Reg SHO": st.column_config.TextColumn(help="나스닥 Reg SHO 기준 미달 종목 목록에 연속으로 올라 있는 거래일 수(결제 불이행 누적 — 공매도 상환 압박 신호로 보는 사람이 많음)"),
            "거래량 배수": st.column_config.NumberColumn(format="%.2f"),
            "매수체결 비중(%)": st.column_config.NumberColumn(format="%.1f", help="1분봉 종가 방향 기반 추정치(틱룰). 실제 체결강도 아님."),
            "유통주식(백만)": st.column_config.NumberColumn(format="%.2f"),
            "퀀트점수": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
            "펌핑점수": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "승률 점수": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f",
                help="과거 급락 사건으로 학습한 성공확률 모델의 점수(백분위, 희석 상태 가정 보정 포함). 정규장 마지막 스캔 값. 장중엔 거래량이 덜 쌓여 낮게 보일 수 있음. '점수 검증' 탭에서 실제로 맞는지 확인하세요."),
            "예상 성공확률(%)": st.column_config.NumberColumn(format="%.1f", help="희석 보정 전 모델 확률. 성공 기준은 모델별로 다름(점수 검증 탭)"),
            "진입참고($)": st.column_config.NumberColumn(format="%.4f", help="현재가 - 0.5×ATR(14)"),
            "손절참고($)": st.column_config.NumberColumn(format="%.4f", help="진입참고 - 1×ATR"),
            "목표참고($)": st.column_config.NumberColumn(format="%.4f", help="진입참고 + 2×ATR"),
        })

        st.markdown("---")
        st.markdown("### 🔍 종목 상세")
        tickers = list(dict.fromkeys(view["ticker"]))
        row = view.iloc[_ids.index(_pick)]
        sel = row["ticker"]
        st.markdown(f"#### {sel}")
        tosslink_ui.button(sel, key="snap")
        watch_ui.add_button(sel, None if pd.isna(row["price"]) else float(row["price"]), key="snap")
        intel_ui.render_ticker(sel, row["date"], key="snap")
        timeline_ui.render(sel, key="snap")
        pumpsetup_ui.render_panel(sel, None, key="snap")
        flowread_ui.render_panel(sel, watch_ui.prices((sel,)).get(sel), key="snap")
        forensic_ui.render(sel, key="snap")
        st.markdown("---")
        dil = dil_map.get(sel)
        flags = json.loads(dil["flags"]) if dil and dil.get("flags") else {}
        evidence = json.loads(dil["evidence"]) if dil and dil.get("evidence") else []
        status = row["dilution_status"]

        left, right = st.columns([2, 1])
        with left:
            verdict = {
                "ATM": ("error", "ATM 관련 공시가 감지되어 신규 진입 후보에서 제외됩니다. 잔여 한도는 원문으로 확인해야 합니다."),
                "CB": ("warning", "전환사채/전환우선주 관련 공시가 감지되었습니다. 전환 물량이 매물로 나올 수 있습니다."),
                "ELOC": ("info", "ELOC(지분매입 약정) 정황이 있습니다. 약정 한도 내 주식이 시장에 나올 수 있습니다."),
                "OFFERING": ("warning", "최근 공모/사모/워런트 관련 공시가 감지되었습니다."),
                "UNKNOWN": ("warning", f"SEC 공시를 확인하지 못했습니다 ({dil.get('error') if dil else '조회 기록 없음'}). '희석 없음'이 아닙니다."),
                "CLEAN": ("success", "최근 검사한 공시 범위에서 희석 키워드가 검출되지 않았습니다. 이는 희석이 없다는 보장이 아닙니다."),
            }.get(status, ("info", status))
            getattr(st, verdict[0])(f"**[{sel}] {label(status)}** — {verdict[1]}")

            st.markdown("#### 점수 구성")
            q_detail = json.loads(row["quant_detail"] or "{}")
            if q_detail:
                chartpop.bar(pd.Series(q_detail, name="점수"), key="snap_score", title="점수 구성", horizontal=True, height=200)

            st.markdown("#### 근거 공시 (SEC 원문)")
            if evidence:
                for ev in evidence:
                    st.markdown(f"- [{ev['form']} · {ev['filed']}]({ev['url']}) — `{', '.join(ev['tags'])}`")
            else:
                st.caption("검출된 근거 공시가 없습니다.")
            if flags.get("PARTIAL_CHECK"):
                st.warning("일부 공시의 본문 확인에 실패해 부분 검사 결과입니다.")
        with right:
            st.markdown("#### 🛡️ 희석 플래그")
            f1, f2, f3 = st.columns(3)
            f1.metric("ATM", "ON" if flags.get("ATM") else "OFF")
            f2.metric("ELOC", "ON" if flags.get("ELOC") else "OFF")
            f3.metric("CB", "ON" if flags.get("CB") else "OFF")
            f4, f5, f6 = st.columns(3)
            f4.metric("워런트", "ON" if flags.get("WARRANT") else "OFF")
            f5.metric("역분할", "ON" if flags.get("REVERSE_SPLIT") else "OFF")
            f6.metric("계속기업", "ON" if flags.get("GOING_CONCERN") else "OFF")
            st.caption(f"S-3 선반등록: {'있음' if flags.get('SHELF_S3') else '미확인'}"
                       f"{' · 해외기업(6-K)' if flags.get('FOREIGN_FILER') else ''}")

            st.markdown("#### 유통주식 · Baby Shelf(근사)")
            fs = row["float_shares"]
            st.metric("Float", f"{fs / 1e6:,.2f}백만 주" if fs and not pd.isna(fs) else "확인 불가")
            bs = baby_shelf(None if pd.isna(fs) else fs, row["price"])
            if bs:
                st.write(f"유통시총 ≈ ${bs['public_float_value'] / 1e6:,.1f}M")
                if bs["is_baby_shelf"]:
                    st.write(f"Baby Shelf 대상(<$75M): S-3 1차 발행 12개월 상한 ≈ ${bs['cap'] / 1e6:,.1f}M")
                else:
                    st.write("Baby Shelf 비대상(≥$75M)")
                st.caption("현재가×yfinance float 기반 근사치. 실제 규정은 비계열 주식 기준·최근 60일 최고가를 사용합니다.")

        st.markdown("---")
        st.markdown("### 🎯 승률 점수")
        wm_name = row.get("win_model") if isinstance(row.get("win_model"), str) else config.WIN_MODEL
        wmodel = load_model_cached(wm_name)
        ws, wp = row.get("win_score"), row.get("win_p")
        if ws is None or pd.isna(ws):
            why = ("학습된 모델이 없습니다 — `python winmodel.py fit`" if wmodel is None else
                   "오늘 등락률이 -10% 이하일 때만 계산됩니다" if (row.get("day_change_pct") is None or pd.isna(row.get("day_change_pct")) or row.get("day_change_pct") > -10) else
                   "정규장(미국 동부시간 09:30~16:00) 스캔이 아직 없었거나, 입력값(거래량·20일 기록)이 부족합니다")
            st.info(f"승률 점수 없음: {why}")
        else:
            w1, w2, w3, w4 = st.columns(4)
            w1.metric("승률 점수", f"{ws:.0f} / 100", help="예상 확률이 과거 급락 사건 분포의 몇 번째 백분위인지(희석 상태 가정 보정 포함)")
            w2.metric("예상 성공확률", "-" if wp is None or pd.isna(wp) else f"{wp * 100:.1f}%", help="희석 보정 전 모델 확률")
            mult = config.DILUTION_MULT.get(status, 1.0) if config.DILUTION_ADJUST else 1.0
            w3.metric("희석 보정 배수", f"×{mult:.2f}", help="가정값입니다. '점수 검증' 탭의 희석 상태별 실측으로 교체하세요.")
            if wmodel and "thresholds" in wmodel["metrics"]:
                tr = [t for t in wmodel["metrics"]["thresholds"] if t["score"] <= ws]
                if tr and tr[-1]["success"] is not None:
                    t_ = tr[-1]
                    w4.metric(f"과거 검증: 점수 ≥ {t_['score']}", f"{t_['success']:.1f}%",
                              delta=f"기준 {wmodel['metrics']['base_rate_test']:.1f}% · {t_['n']:,}건", delta_color="off",
                              help="학습에 쓰지 않은 최근 구간에서 이 점수 이상의 사건이 실제로 성공한 비율")
            if wmodel:
                st.caption(f"모델 `{wm_name}` ({winmodel.LABELS[wmodel['label']][1]} ≥ +{wmodel['target']:g}%) · "
                           + (f"표본 외 AUC {wmodel['metrics']['auc_test']:.3f}" if "auc_test" in wmodel["metrics"] else "표본 외 검증 없음")
                           + f" · 가격·거래량·시장 지표 {len(wmodel['features'])}개 입력으로만 계산하며 공시 정보는 반영되지 않습니다. 과거 성과가 앞으로를 보장하지 않습니다.")

        st.markdown("---")
        st.markdown("### 📚 비슷한 과거 사례")
        if ev_all.empty:
            st.info("과거 사례 DB가 비어 있습니다. `python cases.py build --years 10` 으로 먼저 만드세요.")
        else:
            day, vm = row.get("day_change_pct"), row.get("volume_mult")
            has_day = day is not None and not pd.isna(day)
            vm = None if vm is None or pd.isna(vm) else float(vm)
            if not has_day:
                st.caption("이 스냅샷에는 오늘 등락률이 기록돼 있지 않습니다(이전 버전 스캐너가 저장한 데이터). 아래 급락률을 직접 조정하세요.")
            elif day > -10:
                st.info(f"오늘 등락률은 {day:.1f}% 입니다. 과거 사례는 '전일 종가 대비 -10% 이하 급락일'만 있어서, 비교할 급락률을 -20%로 가정해 보여줍니다. 아래에서 바꿀 수 있어요.")
            default_drop = float(day) if has_day and day <= -10 else -20.0
            k0 = f"sim_{sel}_{row['date']}"
            s1, s2, s3, s4 = st.columns(4)
            drop = s1.number_input("비교할 급락률(%)", -99.0, -10.0, float(max(default_drop, -99.0)), step=1.0, key=k0 + "_drop")
            band = s2.select_slider("허용 범위 ±(%p)", [2, 3, 5, 8, 10, 15], 5, key=k0 + "_band")
            vkey = s3.select_slider("거래량 배수 허용 범위", list(similar.VOL_FACTORS), "×/÷2", key=k0 + "_vol",
                                    help=f"이 종목의 거래량 배수: {vm:.2f}배" if vm else "이 종목의 거래량 배수를 알 수 없어 적용되지 않습니다.")
            use_price = s4.checkbox("가격대도 비슷한 것만(×/÷2)", False, key=k0 + "_price",
                                    help="오래된 사건의 가격은 분할 보정값이라, 역분할이 많았던 종목은 실제보다 높게 기록되어 있어 기본은 끔.")
            sub = similar.select(ev_all, drop, band, vm, similar.VOL_FACTORS[vkey],
                                 float(row["price"]) if use_price else None, 2.0 if use_price else None, before=row["date"])
            base = similar.stats(ev_all, succ_target)
            sm = similar.stats(sub, succ_target)
            pct = lambda x: "-" if x is None else f"{x:.1f}%"  # noqa: E731
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("비슷한 사건", f"{sm['n']:,}", help=f"같은 종목의 과거 사건 {int((sub['ticker'] == sel).sum())}건 포함")
            m2.metric("결과 확인", f"{sm['known']:,}")
            m3.metric(f"성공률 (다음날 고가 ≥ +{succ_target}%)", pct(sm["success"]),
                      delta=None if sm["success"] is None or base["success"] is None else f"{sm['success'] - base['success']:+.1f}%p vs 전체 {base['success']:.1f}%",
                      delta_color="off")
            m4.metric("다음날 종가 중앙값", pct(sm["next_close"]))
            m5.metric("5일 후 중앙값", pct(sm["fwd_5d"]))
            m6.metric("5일 내 최저 중앙값", pct(sm["max_down_5d"]))
            if sm["n"] == 0:
                st.info("조건에 맞는 사건이 없습니다. 허용 범위를 넓혀 보세요.")
            else:
                if sm["n"] < 30:
                    st.warning(f"비슷한 사건이 {sm['n']}건뿐이라 통계가 불안정합니다. 허용 범위를 넓혀 보세요.")
                st.markdown(f"**수익률 분포 — 비슷한 사건 {sm['n']:,}건** (성공률 뒤에 숨은 극단적 펌핑과 하방 깊이)")
                dist_ui.render(sub, succ_target, key=k0 + "_dist")
                near = similar.nearest(sub, drop, vm, 10)
                st.markdown("**가장 비슷한 사건 10건**")
                st.dataframe(pd.DataFrame({
                    "거래일": near["date"], "티커": near["ticker"], "종가($)": near["close"], "급락(%)": near["drop_pct"],
                    "거래량 배수": near["vol_mult"], "다음날 시가(%)": near["next_open_pct"], "다음날 고가(%)": near["next_high_pct"],
                    "다음날 종가(%)": near["next_close_pct"], "5일 후(%)": near["fwd_5d"], "5일 내 최저(%)": near["max_down_5d"]}),
                    hide_index=True, width="stretch",
                    column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                                   ["급락(%)", "거래량 배수", "다음날 시가(%)", "다음날 고가(%)", "다음날 종가(%)", "5일 후(%)", "5일 내 최저(%)"]})
            st.caption("과거 사건은 yfinance 일봉 기준이며 상장폐지 종목이 거의 없어 성공률이 낙관적일 수 있습니다. 같은 종목의 과거 사건도 포함됩니다. "
                       "'성공'은 다음날 고가 기준이라 장중 고가/저가의 순서를 알 수 없고, 과거 성과가 앞으로를 보장하지 않습니다.")

# ----------------------------------------------------------------- 탭2
def _snapshot_board():
    st.markdown("##### 퀀트 스냅샷 기준 후보 보드 (ATM 정황 종목 자동 제외)")
    sess = us_session()
    if sess == "정규장":
        st.success("지금은 **미국 정규장**입니다. 값은 이번 사이클 스캔 기준이며, **마감 30분 전**(한국시간 04:30~05:00, 11월 이후 05:30~06:00)부터의 값이 가장 의미 있습니다.")
    elif sess == "확인 불가":
        st.info("미국장 세션을 확인하지 못했습니다(토스 연동이 꺼져 있거나 스캐너가 멈춤). 아래 숫자는 마지막 스캔 기준입니다.")
    else:
        st.warning(f"지금은 **{sess}**입니다. 거래량 배수·종가 위치·승률 점수는 미국 **정규장 값**을 기준으로 만들어져서, 정규장이 아닐 때는 거래량이 거의 0으로 나오거나 "
                   "정규장 마지막 스캔 값이 남아 있는 상태입니다. 후보는 **정규장 마감 30분 전부터**(한국시간 04:30~05:00, 11월 이후 05:30~06:00)의 값으로 보세요.")

    cand = view.copy()
    if "sim_n" not in cand:
        cand = similar.annotate(cand, load_events_cached(), succ_target)
    ok = cand[cand["excluded"] == 0].copy()
    cut = cand[cand["excluded"] == 1]

    f1, f2, f3, f4, f5 = st.columns(5)
    sort_by = f1.selectbox("정렬 기준", ["승률 점수", "유사 성공률", "펌핑점수(참고)", "거래량 배수", "낙폭(깊은 순)"], key="cl_sort")
    min_ws = f2.slider("승률 점수 ≥", 0, 100, 0, key="cl_ws")
    min_chk = f3.slider("체크리스트 충족 ≥ (7개 중)", 0, 7, 0, key="cl_chk")
    max_float = f4.number_input("유통주식 ≤ (백만 주, 0=제한 없음)", 0.0, 5000.0, 0.0, step=5.0, key="cl_float")
    crash = f5.checkbox("오늘 등락 -10% 이하만", False, key="cl_crash", help="승률 점수와 유사 사례는 이 조건의 종목에만 계산됩니다")

    def checks_of(js: str) -> list:
        return json.loads(js or "{}").get("checks", [])
    ok["_checks"] = ok["pump_detail"].map(checks_of)
    ok["충족"] = ok["_checks"].map(lambda c: sum(1 for _, v in c if v))
    ok["_total"] = ok["_checks"].map(len)
    shown = ok[ok["충족"] >= min_chk]
    if min_ws > 0:
        shown = shown[shown["win_score"] >= min_ws]
    if max_float > 0:
        shown = shown[shown["float_shares"] <= max_float * 1e6]
    if crash:
        shown = shown[shown["day_change_pct"] <= -10]
    sort_col, asc = {"승률 점수": ("win_score", False), "유사 성공률": ("sim_success", False), "펌핑점수(참고)": ("pump_score", False),
                     "거래량 배수": ("volume_mult", False), "낙폭(깊은 순)": ("drawdown_pct", True)}[sort_by]
    shown = shown.sort_values([sort_col, "pump_score"], ascending=[asc, False], na_position="last")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("후보(ATM 제외 후)", f"{len(ok)} 개", help="사이드바 필터(기간·희석 상태·퀀트 점수)를 통과한 종목")
    m2.metric("아래 표에 표시", f"{len(shown)} 개")
    m3.metric("승률 점수 있는 종목", f"{int(ok['win_score'].notna().sum())} 개", help="정규장 스캔에서 오늘 등락 -10% 이하이고 입력값이 있는 종목만")
    m4.metric("ATM 정황으로 제외", f"{len(cut)} 개")

    if shown.empty:
        st.info("조건에 맞는 종목이 없습니다. 필터를 풀어 보세요.")
    else:
        names = [k for k, _ in shown["_checks"].iloc[0]]
        short = {"낙폭 -20% 이하": "낙폭≤-20%", "유통주식 2천만 이하": "유통≤2천만", "거래량 2배 이상": "거래량≥2배",
                 "매수체결 55% 이상": "매수≥55%", "ATM 미검출": "ATM 없음", "CB 미검출": "CB 없음", "희석 상태 확인됨": "희석 확인"}
        p = pd.DataFrame({
            "거래일": shown["date"], "티커": shown["ticker"], "승률 점수": shown["win_score"],
            "충족": shown.apply(lambda r: f"{r['충족']}/{r['_total']}", axis=1),
        })
        for n in names:  # 체크리스트 항목마다 열을 따로 둬서 어떤 항목이 ❌인지 바로 보이게 한다
            p[short.get(n, n)] = shown["_checks"].map(lambda c, n=n: "✅" if dict(c).get(n) else "❌")
        p = p.assign(**{
            "예상 확률(%)": shown["win_p"] * 100, "유사 사례 수": shown["sim_n"], "유사 성공률(%)": shown["sim_success"],
            "희석상태": shown["희석상태"], "낙폭(%)": shown["drawdown_pct"], "오늘 등락(%)": shown["day_change_pct"],
            "거래량 배수": shown["volume_mult"], "시가 갭(%)": shown["gap_pct"], "종가 위치": shown["close_loc"],
            "매수체결(%)": shown["buy_pressure"], "유통주식(백만)": shown["float_shares"] / 1e6, "현재가($)": shown["price"],
            "진입참고($)": shown["entry_ref"], "손절참고($)": shown["stop_ref"], "목표참고($)": shown["target_ref"],
            "펌핑점수(참고)": shown["pump_score"]})
        cfg = {
            "승률 점수": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f",
                help="검증된 승률 모델의 점수(정규장 값). 점수 검증 탭에서 실제로 맞는지 확인하세요."),
            "충족": st.column_config.TextColumn(width="small", help="체크리스트 7개 중 충족한 개수"),
            "예상 확률(%)": st.column_config.NumberColumn(format="%.1f", help="희석 보정 전 모델 확률"),
            "유사 사례 수": st.column_config.NumberColumn(format="%d"),
            "유사 성공률(%)": st.column_config.NumberColumn(format="%.1f", help="오늘 등락·거래량이 비슷한 과거 급락 사건 중 다음날 고가가 +N%(사이드바) 이상이었던 비율"),
            "낙폭(%)": st.column_config.NumberColumn(format="%.1f", help="20일 고점 대비"),
            "오늘 등락(%)": st.column_config.NumberColumn(format="%.1f", help="전일 종가 대비"),
            "거래량 배수": st.column_config.NumberColumn(format="%.2f", help="정규장이 아닐 때는 0에 가깝게 나옴"),
            "시가 갭(%)": st.column_config.NumberColumn(format="%.1f", help="오늘 정규장 시가 vs 전일 종가"),
            "종가 위치": st.column_config.NumberColumn(format="%.2f", help="오늘 고저 범위 중 현재가 위치: 0=저가, 1=고가"),
            "매수체결(%)": st.column_config.NumberColumn(format="%.1f", help="1분봉 방향 기반 추정치"),
            "유통주식(백만)": st.column_config.NumberColumn(format="%.2f"),
            "현재가($)": st.column_config.NumberColumn(format="%.4f"),
            "진입참고($)": st.column_config.NumberColumn(format="%.4f", help="ATR 기반 참고값(현재가 - 0.5ATR)"),
            "손절참고($)": st.column_config.NumberColumn(format="%.4f"),
            "목표참고($)": st.column_config.NumberColumn(format="%.4f"),
            "펌핑점수(참고)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f", help="사람이 정한 가중치 점수(검증되지 않음)"),
        }
        for n in names:
            cfg[short.get(n, n)] = st.column_config.TextColumn(width="small", help=f"체크리스트: {n}  (✅ 충족 / ❌ 미충족)")
        st.dataframe(p, hide_index=True, width="stretch", column_config=cfg)
        st.caption("체크리스트: " + " · ".join(f"**{short.get(n, n)}** = {n}" for n in names) + "   (✅ 충족 / ❌ 미충족)")

        # 선택한 종목의 체크리스트 상세: 항목별 현재 값과 기준
        st.markdown("#### 🔎 체크리스트 상세")
        multi_day = shown["date"].nunique() > 1
        opts = [f"{t} ({dt})" if multi_day else t for t, dt in zip(shown["ticker"], shown["date"])]
        pick_i = opts.index(st.selectbox("종목 선택", opts, key="cl_pick"))
        r = shown.iloc[pick_i]

        def fmt(x, f):
            return "확인 불가" if x is None or pd.isna(x) else f.format(x)

        def check_value(name: str) -> str:
            if name.startswith("낙폭"):
                return fmt(r["drawdown_pct"], "{:.1f}% (20일 고점 대비)")
            if name.startswith("유통주식"):
                return fmt(None if pd.isna(r["float_shares"]) else r["float_shares"] / 1e6, "{:.2f}백만 주")
            if name.startswith("거래량"):
                return fmt(r["volume_mult"], "{:.2f}배 (20일 평균 대비)")
            if name.startswith("매수체결"):
                return fmt(r["buy_pressure"], "{:.1f}% (추정치)")
            return label(r["dilution_status"])  # ATM / CB / 희석 확인

        items = pd.DataFrame([{"항목(기준)": n, "현재 값": check_value(n), "결과": "✅ 충족" if v else "❌ 미충족"} for n, v in r["_checks"]])
        failed = [f"{n} → {check_value(n)}" for n, v in r["_checks"] if not v]
        if failed:
            st.warning(f"**{r['ticker']}** 미충족 {len(failed)}개: " + " / ".join(failed))
        else:
            st.success(f"**{r['ticker']}** 체크리스트 {len(items)}개 모두 충족")
        st.dataframe(items, hide_index=True, width="stretch")
        st.caption("점수·참고가는 규칙 기반 계산값이며 투자 권유가 아닙니다. 종목 상세·근거 공시는 📊 퀀트 스냅샷 탭, 선택한 후보의 이후 결과는 📒 발견 종목 추적 탭에서 확인하세요.")
    if not cut.empty:
        with st.expander(f"제외된 종목 {len(cut)}개 보기 (ATM 정황 — 키워드 검출이라 잔여 한도는 원문 확인 필요)"):
            st.dataframe(cut.sort_values("drawdown_pct")[["date", "ticker", "희석상태", "drawdown_pct", "day_change_pct", "volume_mult"]].rename(
                columns={"date": "거래일", "ticker": "티커", "drawdown_pct": "낙폭(%)", "day_change_pct": "오늘 등락(%)", "volume_mult": "거래량 배수"}),
                hide_index=True, width="stretch")


def _render_close() -> None:
    """🎯 장마감 펌핑 체크리스트(🧲 수급 화면의 탭)."""
    closewatch_ui.render()
    with st.expander("📋 (참고) 퀀트 스냅샷 기준 후보 보드 — 위 토스 기준 체크리스트와는 기준이 다릅니다"):
        _snapshot_board()


# ----------------------------------------------------------------- 📈 신호 성과 통계(🏆 검증 > 성과 공표 안)
def _render_signals() -> None:
    st.subheader("신호 이후 성과 통계")
    st.caption("기준: 신호가 잡힌 날 종가 → N거래일 뒤 종가 (daily_prices 기준). 표본이 적은 구간은 해석하지 마세요.")
    st.markdown("**일별 포착 종목 수**")
    chartpop.bar(snaps.groupby("date").size().sort_index().rename("종목 수"), key="sig_daily", title="일별 포착 종목 수")
    fr = load_forward()
    if fr[[c for c in fr.columns if c.startswith("fwd_")]].notna().sum().sum() == 0:
        st.info("성과를 계산할 가격 데이터가 아직 없습니다. 신호 이후 거래일이 지나야 하고, "
                "`python backfill.py --years 10` 으로 일봉을 채우면 과거 신호도 계산됩니다.")
    else:
        st.markdown("**희석 상태별**")
        s1 = analytics.summarize(fr.assign(희석상태=fr["dilution_status"].map(label)), "희석상태")
        st.dataframe(ui_kit.tidy(s1), hide_index=True, width="stretch")  # 자릿수 정리
        st.markdown("**낙폭 구간별**")
        bins = pd.cut(fr["drawdown_pct"], [-100, -50, -30, -20, -12, 0], labels=["≤-50%", "-50~-30%", "-30~-20%", "-20~-12%", "> -12%"])
        s2 = analytics.summarize(fr.assign(낙폭구간=bins), "낙폭구간")
        st.dataframe(ui_kit.tidy(s2), hide_index=True, width="stretch")
        st.warning("생존편향 주의: 상장폐지된 종목이 데이터에 없으면 성과가 실제보다 좋게 보입니다. "
                   "또 일봉 종가 기준이라 장중 슬리피지·호가 공백·거래정지는 반영되지 않습니다.")

# ----------------------------------------------------------------- 탭4
for _ in page("filings"):
    st.subheader("희석 관련 공시 타임라인 (키워드 검출된 공시만)")
    fl = load_filings()
    if fl.empty:
        st.info("검출된 공시가 없거나 아직 SEC 검사가 실행되지 않았습니다.")
    else:
        fl["태그"] = fl["tags"].map(lambda s: ", ".join(json.loads(s)))
        import altair as alt
        _c = fl.assign(날짜=pd.to_datetime(fl["filed"], errors="coerce"), 첫태그=fl["tags"].map(lambda s: (json.loads(s) or ["기타"])[0])).dropna(subset=["날짜"])
        _top = _c["ticker"].value_counts().head(30).index
        _c = _c[_c["ticker"].isin(_top)]
        if not _c.empty:
            chartpop.show(alt.Chart(_c).mark_point(size=90, filled=True, opacity=0.8).encode(
                x=alt.X("날짜:T", title=None), y=alt.Y("ticker:N", title=None, sort="-x"), color=alt.Color("첫태그:N", title="태그", legend=alt.Legend(orient="bottom", columns=4)),  # 범례가 최근 점을 가리지 않게 아래로
                tooltip=[alt.Tooltip("날짜:T", format="%Y-%m-%d"), "ticker:N", "form:N", "items:N", "태그:N"]).properties(height=24 * _c["ticker"].nunique() + 60).interactive(),
                key="filings_tags", title="종목별 공시 태그 타임라인", data=_c, click=False)
            st.caption("희석 키워드가 나온 공시를 종목별로 시간축에 찍었습니다(공시가 많은 30종목). 점을 가리키면 서류·태그가 보이고, 드래그·휠로 확대할 수 있어요. "
                       "종목별 락업·워런트 만기 같은 앞으로의 일정은 각 종목 상세의 🗓 타임라인에서 보세요.")
        st.dataframe(fl[["filed", "ticker", "form", "items", "태그", "url"]].rename(
            columns={"filed": "공시일", "ticker": "티커", "form": "서류", "items": "8-K Item", "url": "원문"}),
            hide_index=True, width="stretch",
            column_config={"원문": st.column_config.LinkColumn(display_text="열기")})


# ----------------------------------------------------------------- 🗂 종목 리포트(🏢 종목 화면의 탭)
def fmt_money(x, unit="$"):
    if x is None:
        return "확인 불가"
    a = abs(x)
    return f"{unit}{x / 1e9:,.2f}B" if a >= 1e9 else f"{unit}{x / 1e6:,.2f}M" if a >= 1e6 else f"{unit}{x:,.0f}"


def fmt_num(x, nd=1, suffix=""):
    return "확인 불가" if x is None else f"{x:,.{nd}f}{suffix}"


def _render_report() -> None:
    st.subheader("🗂 종목 리포트")
    st.caption("SEC 공시·가격 데이터에서 자동으로 뽑을 수 있는 항목만 담았습니다. 워런트·락업 상세 수량, 진입가 사다리, "
               "돌파 가능성 같은 해석 항목은 챗봇의 SEC 포렌식 스캔 결과를 아래 '내 메모'에 붙여 넣어 보관하세요.")
    known = sorted(snaps["ticker"].unique())
    pc1, pc2, pc3 = st.columns([2, 2, 1])
    _cur = str(st.session_state.get("lookup_ticker") or "").upper()   # 2026-10-28: 기본 종목 = 🏢 종목 화면에서 지금 보는 티커(예전엔 알파벳 첫 종목)
    pick = pc1.selectbox("종목", known, index=known.index(_cur) if _cur in known else 0, key="rep_pick")
    extra = pc2.text_input("목록에 없는 티커 직접 입력", "" if (_cur in known or not _cur) else _cur, key="rep_extra").strip().upper()
    ticker = extra or pick
    rep = db.get_report(ticker)
    with st.expander(f"📇 {ticker} 스크리너 카드 — 제외 사유 · 실적 일정 · 이벤트 로그 · 레벨 맵 · AI 시나리오", expanded=bool(extra)):
        import screener_ui
        screener_ui.render(ticker)

    with pc3:
        st.write("")
        run = st.button("🔄 리포트 생성/갱신", width="stretch")
    if run:
        if "@" not in config.SEC_USER_AGENT:
            st.error("SEC_USER_AGENT 가 .env 에 설정되어 있지 않습니다.")
        else:
            from contextlib import closing
            with st.spinner(f"{ticker} 리포트 생성 중... (SEC 공시를 읽는 중이라 30초~1분 걸릴 수 있어요)"):
                with closing(db.connect()) as _conn:
                    rep = report.build_report(sec.SecClient(config.SEC_USER_AGENT), _conn, ticker)
                db.save_report(ticker, rep)
            st.rerun()

    watch_ui.add_button(ticker, None, key="rep")
    with st.expander("🧾 공시분석 (공시 분석 프로젝트 · 덕구 스캔)", expanded=True):
        forensic_ui.render(ticker, key="rep")
    with st.expander("📡 체결강도 · 거래정지 · 공매도 · 장중 공시 (스캐너 공통 데이터)", expanded=True):
        intel_ui.render_ticker(ticker, None, key="rep")
    if not rep:
        st.info(f"[{ticker}] 아직 생성된 리포트가 없습니다. 위의 **리포트 생성/갱신** 버튼을 눌러 주세요.")
    else:
        co = rep.get("company") or {}
        gen = pd.to_datetime(rep["generated_at"], utc=True).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M")
        dstat = (dil_map.get(ticker) or {}).get("status")
        st.markdown(f"## {ticker}  ·  {co.get('name') or ''}  `{co.get('exchange') or '거래소 미확인'}`"
                    + (f"  ·  {label(dstat)}" if dstat else ""))
        st.caption(f"생성: {gen} (KST) · 데이터는 이 시각 기준이며 자동 갱신되지 않습니다.")
        for k, v in rep.get("errors", {}).items():
            st.warning(f"⚠️ {k} 섹션을 만들지 못했습니다: {v}")

        # ---- 1. 회사
        st.markdown("### 1. 회사")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("종가", f"${co['price']:,.4f}" if co.get("price") else "확인 불가", help=co.get("price_date"))
        m2.metric("시가총액", fmt_money(co.get("market_cap")))
        m3.metric("발행주식", fmt_num(co["shares_out"] / 1e6 if co.get("shares_out") else None, 2, "M"))
        m4.metric("유통주식", fmt_num(co["float_shares"] / 1e6 if co.get("float_shares") else None, 2, "M"),
                  delta=f"{co['float_ratio']:.0f}%" if co.get("float_ratio") else None, delta_color="off")
        m5.metric("20일 고점 대비", fmt_num(co.get("drawdown_pct"), 1, "%"))
        m6.metric("오늘 거래량 배수", fmt_num(co.get("volume_mult"), 1, "배"))
        if co.get("closes"):
            chartpop.line(pd.DataFrame(co["closes"]).set_index("date")["close"].rename("종가"), key="co_close", title="종가 추이", height=160)
        if co.get("splits"):
            st.markdown("**분할 이력** — " + " · ".join(f"{s['date']} {s['text']}" for s in co["splits"]))
            rs = [s for s in co["splits"] if s["ratio"] < 1]
            if len(rs) >= 2:
                st.warning(f"역분할이 {len(rs)}회 있었습니다. 반복되는 역분할은 희석과 주가 하락의 반복 패턴일 수 있습니다.")
        if co.get("delisting_notices"):
            st.error("**상장유지 관련 공시(8-K Item 3.01)가 최근 3년 내 있습니다:** " +
                     " · ".join(f"[{n['filed']}]({n['url']})" for n in co["delisting_notices"]))
        if co.get("volume_spikes"):
            st.markdown("**최근 거래량 폭발일(20일 평균 대비 5배↑):** " +
                        " · ".join(f"{v['date']} ×{v['volume_mult']} ({v['change_pct']}%)" for v in co["volume_spikes"][::-1]))

        # ---- 2. 희석 · 조달
        st.markdown("### 2. 희석 · 조달")
        dil = dil_map.get(ticker)
        if dil:
            fl = json.loads(dil["flags"]) if dil.get("flags") else {}
            cols = st.columns(6)
            for c, (k, nm) in zip(cols, [("ATM", "ATM"), ("ELOC", "ELOC"), ("CB", "전환사채"), ("WARRANT", "워런트"),
                                         ("REVERSE_SPLIT", "역분할 언급"), ("GOING_CONCERN", "계속기업 의구심")]):
                c.metric(nm, "ON" if fl.get(k) else "OFF")
            st.caption(f"S-3 선반등록: {'있음' if fl.get('SHELF_S3') else '미확인'} · 키워드 검출 결과이며 원문 확인이 필요합니다.")
        bs = baby_shelf(co.get("float_shares"), co.get("price"))
        if bs:
            st.write(f"**Baby Shelf(근사)** 유통시총 ≈ ${bs['public_float_value'] / 1e6:,.1f}M → "
                     + (f"대상(<$75M), S-3 1차 발행 12개월 상한 ≈ ${bs['cap'] / 1e6:,.1f}M" if bs["is_baby_shelf"] else "비대상(≥$75M)"))
        fin = rep.get("financing")
        if fin and fin["events"]:
            sm = fin["summary"]
            line = f"최근 24개월 조달 정황 {sm['count']}건"
            if sm.get("median_gap_days"):
                line += f" · 간격 중앙값 {sm['median_gap_days']}일"
            if sm.get("last_date"):
                line += f" · 마지막 {sm['last_date']}"
            st.markdown(f"**{line}**")
            ev = pd.DataFrame(fin["events"])
            for c in ("pre20_pct", "vol_mult", "after5_pct"):
                if c not in ev:
                    ev[c] = None
            tbl = pd.DataFrame({"날짜": ev["date"], "형태": ev["tags"].map(lambda t: ", ".join(report.TAG_KO.get(x, x) for x in t)),
                                "서류": ev["form"], "직전 20일(%)": ev["pre20_pct"], "거래량 배수": ev["vol_mult"],
                                "5일 후(%)": ev["after5_pct"], "원문": ev["url"]})
            st.dataframe(tbl, hide_index=True, width="stretch", column_config={
                "원문": st.column_config.LinkColumn(display_text="열기"),
                "직전 20일(%)": st.column_config.NumberColumn(format="%.1f", help="공시 전날 종가 / 20거래일 전 종가"),
                "거래량 배수": st.column_config.NumberColumn(format="%.1f", help="공시 직전 5일 최대 거래량 / 그 앞 20일 평균"),
                "5일 후(%)": st.column_config.NumberColumn(format="%.1f", help="공시일+5거래일 종가 / 공시 전날 종가")})
            st.caption("공시 본문 키워드로 자동 분류한 결과라 형태가 애매하면 원문 링크로 확인하세요. 워런트·전환사채의 구체적 수량은 제공하지 않습니다.")
            if fin["summary"].get("errors"):
                st.warning(f"공시 {fin['summary']['errors']}건은 본문 확인에 실패해 빠져 있습니다.")
        elif fin is not None:
            st.info("최근 24개월 내 검출된 조달 정황이 없습니다. (검출 안 됨 ≠ 없음)")

        # ---- 3. 런웨이
        st.markdown("### 3. 런웨이")
        rw = rep.get("runway")
        if rw:
            cur = rw.get("currency") or ""
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("현금", fmt_money(rw.get("cash"), "") + f" {cur}" if rw.get("cash") is not None else "확인 불가",
                      help=f"기준일 {rw.get('cash_asof')}")
            r2.metric("월 소모량(영업CF)", fmt_money(rw.get("monthly_burn"), "") + f" {cur}" if rw.get("monthly_burn") is not None else "확인 불가")
            r3.metric("런웨이", fmt_num(rw.get("runway_months"), 1, "개월") if rw.get("runway_months") is not None
                      else ("영업CF 플러스/확인 불가" if rw.get("monthly_burn") == 0 else "확인 불가"))
            r4.metric("현금 기준일", rw.get("cash_asof") or "확인 불가")
            st.caption(f"영업현금흐름 기간: {rw.get('ocf_period', '확인 불가')} · 출처: SEC XBRL "
                       f"({(rw.get('cash_source') or {}).get('form')} {(rw.get('cash_source') or {}).get('accn') or ''}). "
                       "가장 최근 공시 기간의 평균 소모량이며, 이후 조달·상환은 반영되지 않았습니다.")
        elif "runway" not in rep.get("errors", {}):
            st.info("런웨이 데이터가 없습니다.")

        # ---- 4. 내부자
        st.markdown("### 4. 내부자 거래 (Form 4)")
        ins = rep.get("insiders")
        if ins and ins["rows"]:
            sm = ins["summary"]
            st.write(f"최근 {ins['days']}일 · 장내 매수 {sm['open_market_buys']}건({sm['buy_shares']:,.0f}주) · "
                     f"장내 매도 {sm['open_market_sells']}건({sm['sell_shares']:,.0f}주)")
            code_ko = {"P": "장내 매수", "S": "장내 매도", "A": "부여(Award)", "M": "옵션 행사", "F": "세금 원천징수", "G": "증여"}
            t4 = pd.DataFrame(ins["rows"])
            st.dataframe(pd.DataFrame({
                "거래일": t4["date"], "보고자": t4["owner"], "직책": t4["role"], "구분": t4["code"].map(lambda c: code_ko.get(c, c)),
                "수량": t4["shares"], "가격($)": t4["price"], "거래 후 보유": t4["after"], "원문": t4["url"]}),
                hide_index=True, width="stretch", column_config={
                    "원문": st.column_config.LinkColumn(display_text="열기"),
                    "수량": st.column_config.NumberColumn(format="%d"), "거래 후 보유": st.column_config.NumberColumn(format="%d"),
                    "가격($)": st.column_config.NumberColumn(format="%.4f")})
            st.caption("Form 4(미국 내국 법인 임원·이사·10% 주주)만 대상입니다. 13D/G 지분 보유자와 락업 조건은 포함하지 않습니다.")
        elif ins is not None:
            st.info(f"최근 {ins['days']}일 내 Form 4 거래가 없거나 해외기업(Form 4 제출 대상 아님)입니다.")

        # ---- 5. 내 메모
        st.markdown("### 5. 내 메모")
        nk = f"note_{ticker}"
        if nk not in st.session_state:
            st.session_state[nk] = db.get_note(ticker)

        def _save_ticker_note(t=ticker, k=nk):
            db.save_note(t, st.session_state[k])

        st.text_area("이 종목에 대한 메모 (챗봇 SEC 포렌식 결과 붙여넣기 등)", height=200, key=nk, on_change=_save_ticker_note)
        st.caption("입력창 밖을 클릭하거나 Ctrl+Enter 를 누르면 자동 저장됩니다.")

        # ---- 6. 타임라인
        st.markdown("### 6. 타임라인")
        tl = rep.get("timeline") or []
        if tl:
            tdf = pd.DataFrame(tl)
            if "url" not in tdf:
                tdf["url"] = None
            st.dataframe(tdf.rename(columns={"date": "날짜", "type": "구분", "text": "내용", "url": "원문"}),
                         hide_index=True, width="stretch", column_config={"원문": st.column_config.LinkColumn(display_text="열기")})
        else:
            st.caption("표시할 이벤트가 없습니다.")

for _ in page("cases"):
    cases_ui.render()

for _ in page("notes"):
    notes_ui.render()

for _ in page("watch"):
    watch_ui.render_watchlist()

for _ in page("piggy"):
    piggy_ui.render(FX)

for _ in page("after"):
    afterscalp_ui.render()

for _ in page("rsplit"):
    rsplit_ui.render()

for _ in page("holders"):
    import newtools
    newtools.render_holders()

@st.cache_data(ttl=600, show_spinner=False)
def _rank_top1() -> str:
    """🏢 종목 화면 기본 티커 = 종합 순위 1위(없으면 빈칸)."""
    try:
        import rank_ui
        df = rank_ui.table()
        return str(df.iloc[0]["ticker"]) if df is not None and len(df) else ""
    except Exception:  # noqa: BLE001
        return ""


def _render_scoreboard() -> None:
    """🏆 성과 공표 + 📒 발견 종목 추적 · 📈 신호 성과 통계(켤 때만 계산 — 메뉴 정리로 흡수)."""
    scoreboard_ui.render()
    st.divider()
    _c1, _c2 = st.columns(2)
    if _c1.toggle("📒 발견 종목 추적 보기", key="sc_show_tracking", help="스캐너가 발견한 종목의 다음날·5일 결과") or ALL_PAGES:
        tracking_ui.render()
    if _c2.toggle("📈 신호 성과 통계 보기", key="sc_show_signals", help="희석 상태·낙폭 구간별 과거 성과") or ALL_PAGES:
        _render_signals()


def _render_timemachine() -> None:
    import setup3_ui
    setup3_ui.render_time()


def _render_autopsy() -> None:   # 🔍 부검(1단계 2026-10-28): 놓친 펌핑 · 실패 신호 원인
    import autopsy_ui
    autopsy_ui.render()


def _render_journal() -> None:   # 📒 실제 매매 일지(2026-10-28): 실전 손익 · 신호별 성적 · 가상매매 비교
    import journal_ui
    journal_ui.render()


for _ in page("score"):
    import papertrade_ui
    tabs.select("score", [("score", "🏆 성과 공표", _render_scoreboard), ("scorecheck", "🧪 점수 검증", score_ui.render),
                          ("timemachine", "🕰 타임머신", _render_timemachine), ("papertrade", "🧪 가상매매", papertrade_ui.render),
                          ("autopsy", "🔍 부검", _render_autopsy), ("journal", "📒 매매 일지", _render_journal)])

for _ in page("events"):
    watch_ui.render_events()

for _ in page("lookup"):
    import lookup_ui
    import chart_ui
    if not st.session_state.get("lookup_ticker"):  # 기본 종목 = 종합 순위 1위
        st.session_state["lookup_ticker"] = _rank_top1()
    tabs.select("lookup", [("lookup", "🏢 기업 분석", lookup_ui.render), ("report", "🗂 종목 리포트", _render_report),
                           ("snap", "📊 퀀트 스냅샷", _render_snap), ("chart", "📈 차트", chart_ui.render)])

for _ in page("squeeze"):
    import squeeze_ui
    squeeze_ui.render(FX)

for _ in page("regsho"):
    import regsho_ui
    regsho_ui.render()

for _ in page("darkpool"):
    import darkpool_ui
    darkpool_ui.render()

for _ in page("movers"):
    import mover_ui
    mover_ui.render()

for _ in page("alerts"):
    import alerts_ui
    import alertlog_ui
    tabs.select("alerts", [("alerts", "🔔 공시 알림", alerts_ui.render), ("sent", "📨 보낸 알림", alertlog_ui.render)])   # 📨 2026-10-28: 텔레그램으로 나간 알림 기록

for _ in page("accum"):
    import accum_ui
    tabs.select("accum", [("accum", "🧲 매집 의심", accum_ui.render), ("setup", "🕵️ 세력·셋업", pumpsetup_ui.render_tab), ("close", "🎯 장마감 체크리스트", _render_close)])

for _ in page("effect"):
    import accum_ui
    accum_ui.render_effect()

for _ in page("insider"):
    import insider_ui
    insider_ui.render()

for _ in page("admin"):
    import admin_ui
    admin_ui.render()
    st.divider()
    st.markdown("**📱 간략 보기 화면 구성** — 휴대폰으로 열면 기본으로 간략 보기(홈은 항상 포함)")
    _opts = [p[0] for p in FULL_PAGES if p[0] not in lite.NOT_ALLOWED and p[0] not in ("admin",)]
    _lbl = {p[0]: f"{p[2]} {p[1]} · {p[4]}" for p in FULL_PAGES}
    _sel = st.multiselect("간략 보기에 넣을 화면", _opts, default=[k for k in lite.pages() if k in _opts], format_func=lambda k: _lbl.get(k, k), key="adm_lite_pages")
    _a1, _a2, _ = st.columns([1, 1, 3])
    if _a1.button("💾 간략 화면 저장", key="adm_lite_save", width="stretch"):
        lite.save_pages(_sel)
        st.success(f"저장했어요({len(_sel)}개 + 홈).")
    if _a2.button("↩️ 기본 구성", key="adm_lite_reset", width="stretch"):
        lite.reset_pages()
        st.session_state.pop("adm_lite_pages", None)
        st.rerun()
    st.caption("관리 모드는 간략 보기에 없어요. 홈 맨 아래 '🖥 전체 보기로' 버튼으로 돌아오세요.")
    st.markdown("**⏰ 예약 알림** — 미뤄 둔 일을 때가 되면 텔레그램으로 한 번 알려 줘요(매일 아침 갱신이 확인)")
    try:
        import reminders
        with closing(db.connect()) as _c:
            _rs = reminders.status(_c)
        st.dataframe(pd.DataFrame([{"알림": r["title"], "가장 이른 날": r["earliest"], "늦어도": r["latest"],
                                    "상태": ("✅ 보냄 " + r["sent"]) if r["sent"] else ("🔔 오늘 보낼 차례" if r["due"] else "⏳ 기다리는 중"),
                                    "준비 조건": r["detail"]} for r in _rs]), hide_index=True, width="stretch")
    except Exception as _e:  # noqa: BLE001
        st.caption(f"예약 알림을 읽지 못했어요: {_e}")
    st.markdown("**⏱ 화면 속도** — 서버가 화면을 만드는 데 걸린 시간(최근 기록, 휴대폰까지 오는 인터넷 시간은 빠짐)")
    _sp = _speed_log()
    if _sp:
        _spd = pd.DataFrame(_sp, columns=["시각", "화면", "모드", "초"])
        _agg = _spd.groupby("화면")["초"].agg(["count", "median", "max"]).rename(columns={"count": "횟수", "median": "보통(초)", "max": "가장 느림(초)"})
        st.dataframe(_agg.sort_values("보통(초)", ascending=False).round(2), width="stretch")
    else:
        st.caption("아직 기록이 없어요. 화면을 몇 번 넘겨 본 뒤 다시 보세요.")

for _ in page("themes"):
    import themes_ui
    themes_ui.render()

for _ in page("rank"):
    import rank_ui
    rank_ui.render()

for _ in page("guide"):
    import guide_ui
    guide_ui.render()

def _mode_switch(where: str) -> None:
    """📱 간략 ↔ 🖥 전체 보기(같은 창에서 바로 바뀜, 비밀번호·방문객 링크 유지)."""
    if ALL_PAGES:
        return
    if st.button("🖥 전체 보기로" if LITE else "📱 간략 보기로", key=f"mode_sw_{where}",
                 help="간략 보기 = 휴대폰용으로 꼭 필요한 화면만(홈·오늘·발굴·선별·추적). 화면 구성은 ⚙️ 관리 모드에서 바꿀 수 있어요."):
        st.session_state["_lite"] = not LITE
        st.rerun()


for _ in page("home"):
    import home_ui
    home_ui.render(PAGES, None if ALL_PAGES else _PG)
    st.divider()
    st.caption(("지금은 📱 간략 보기예요 — 휴대폰에서 꼭 필요한 화면만 보여 줘요." if LITE else "지금은 🖥 전체 보기예요.")
               + (" 아래 버튼으로 바꿀 수 있어요." if access.is_guest() else " 주소 끝에 ?v=lite / ?v=full 을 붙여 열어도 바뀌어요."))
    _mode_switch("home")

for _ in page("fundscan"):
    import fundscan_ui
    fundscan_ui.render()

for _ in page("news"):
    import news_ui
    news_ui.render()

for _ in page("eventlab"):
    import eventlab_ui
    eventlab_ui.render()

for _ in page("pick"):
    import pick30_ui
    pick30_ui.render()

for _ in page("setup3"):
    import setup3_ui
    setup3_ui.render()


try:  # ⏱ 이번 화면 시간 기록(최근 300건, 서버 메모리에만)
    _store = _speed_store()
    _store.append((datetime.now().strftime("%m-%d %H:%M:%S"), PAGE or "전체(테스트)", "간략" if LITE else "전체", round(_time_mod.perf_counter() - _T0, 3)))
    del _store[:-300]
except Exception:  # noqa: BLE001
    pass
