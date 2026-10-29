"""⚙️ 관리 모드 — 알림·기능 켜기/끄기, 숫자 설정, 항상 감시할 종목, 텔레그램 테스트, 캐시 비우기, 데이터 현황·로그."""
from contextlib import closing
from pathlib import Path

import pandas as pd
import streamlit as st

import chartpop
import config
import db
import ui_kit as ui


def render_ai_cost() -> None:
    """🤖 AI 비용(2026-10-28): 월 예산 지갑을 어느 기능이 얼마나 쓰는지 — 이번 달·오늘·건당, 남은 예산, 월말 예상, 날짜별 막대. 기능별 기록은 10/28 부터(그 전은 합계만)."""
    import aipick
    s = aipick.spend_summary()
    st.markdown("**🤖 AI 비용** — 월 예산 지갑을 어느 기능이 쓰는지 (기능별 기록은 2026-10-28 부터)")
    ui.cards([{"t": "이번 달 지출", "v": f"{s['spent_krw']:,.0f}원", "s": f"예산 {s['budget_krw']:,.0f}원"},
              {"t": "남은 예산", "v": f"{s['left_krw']:,.0f}원", "s": "20% 아래면 강조", "accent": s["left_krw"] < s["budget_krw"] * 0.2},
              {"t": "월말 예상", "v": f"{s['forecast_krw']:,.0f}원", "s": f"{s['elapsed']}일 평균 × {s['days_in']}일"},
              {"t": "오늘 지출", "v": f"{s['today_krw']:,.0f}원"}])
    rows = s["rows"]
    if rows:
        df = pd.DataFrame([{"기능": r["label"], "이번 달(원)": r["month_usd"] * aipick.FX, "건수": r["month_n"], "건당(원)": r["month_usd"] * aipick.FX / max(r["month_n"], 1),
                            "오늘(원)": r["today_usd"] * aipick.FX, "오늘 건수": r["today_n"], "입력 토큰": r["in_tok"], "출력 토큰": r["out_tok"]} for r in rows])
        st.dataframe(ui.tidy(df), hide_index=True, width="stretch")
        top = rows[0]
        st.caption(f"가장 많이 쓰는 기능: {top['label']} — 건당 약 {top['month_usd'] * aipick.FX / max(top['month_n'], 1):,.0f}원. 줄이려면: {aipick.SAVE_HINT.get(top['kind'], '-')}")
        if s["untracked_krw"] > 1:
            st.caption(f"기능별 기록 전(10/28 이전) 지출 {s['untracked_krw']:,.0f}원은 합계에만 들어 있어요")
    else:
        st.caption("아직 기능별 기록이 없어요 — 10/28 배포 뒤 첫 AI 호출부터 쌓입니다(그 전 지출은 위 '이번 달 지출' 합계에만)")
    days = aipick.spend_days()
    if days:
        chartpop.bar(pd.Series({k[5:]: v * aipick.FX for k, v in days.items()}, name="원"), key="adm_ai_days", title="날짜별 AI 지출(원)", height=160, fmt=",.0f")


def render_pagecache() -> None:
    """🔥 화면 캐시(pagecache, 2026-10-28) — 느린 화면 계산을 quant-warm.timer 가 10분마다 미리 해 둔 상태. 비어 있으면 서버에 타이머가 없는 것(deploy/install_warm_timer.sh)."""
    import pagecache
    with st.expander("🔥 화면 캐시 — 🏁 종합 순위 · 🎯 장마감 체크리스트 · ⚡ EFFECT · 📚 과거 사례가 바로 뜨게 미리 계산해 둔 것"):
        rows = pagecache.status()
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("아직 비어 있어요. 서버에 `quant-warm.timer` 가 있으면 10분 안에 채워지고(없으면 `bash deploy/install_warm_timer.sh`), 화면은 캐시가 없어도 예전처럼(느리게) 동작해요.")
        st.caption("주기: 순위·3대 조건 10분 · 일봉 20분 · 공시 플래그 12시간(아침 갱신 끝에 전부 다시). 화면은 '지난 시간'이 순위 25분 · 일봉 45분 · 플래그 36시간을 넘으면 캐시를 버리고 직접 계산해요.")
        if st.button("🔥 지금 데우기(1~2분)", key="adm_warm"):
            with st.spinner("순위 · 일봉 · 3대 조건 · 공시 플래그 계산 중…"):
                logs = []
                pagecache.warm(force=True, out=logs.append)
            st.success(" · ".join(logs) or "끝")
            st.rerun()


def _count(conn, table: str, where: str = "") -> str:
    try:
        return f"{conn.execute(f'SELECT COUNT(*) FROM {table} {where}').fetchone()[0]:,}"
    except Exception:  # noqa: BLE001
        return "-"


def render() -> None:
    ui.title("관리 모드", "대시보드에서 바로 바꾸는 설정. 저장하면 스캐너는 다음 사이클(몇 분 안)부터, 아침 갱신 작업은 다음 실행부터 따릅니다.")
    config.apply_overrides()
    ov = config.overrides()
    vals = {}
    for group in ("알림", "기능", "숫자", "AI"):
        st.markdown(f"**{group}**")
        names = [k for k, v in config.SETTINGS.items() if v[3] == group]
        cols = st.columns(2)
        for i, k in enumerate(names):
            kind, lo, hi, _, desc = config.SETTINGS[k]
            cur = getattr(config, k)
            tag = " · 변경됨" if k in ov else ""
            col = cols[i % 2]
            if kind is bool:
                vals[k] = col.toggle(desc + tag, value=bool(cur), key=f"adm_{k}")
            elif kind is str:
                opts = getattr(config, "AI_MODELS", [cur])
                vals[k] = col.selectbox(desc + tag, opts, index=opts.index(cur) if cur in opts else 0, key=f"adm_{k}")
            elif kind is int:
                vals[k] = col.number_input(desc + tag, min_value=lo, max_value=hi, value=int(cur), step=1, key=f"adm_{k}")
            else:
                vals[k] = col.number_input(desc + tag, min_value=float(lo), max_value=float(hi), value=float(cur), step=0.05 if hi <= 1 else 1.0, key=f"adm_{k}")
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("💾 저장", type="primary", key="adm_save", width="stretch"):
        changed = {k: v for k, v in vals.items() if v != config._DEFAULTS.get(k)}
        config.save_overrides(changed)
        st.success(f"저장했습니다({len(changed)}개가 기본값과 다름). 스캐너는 다음 사이클부터 적용합니다.")
    if b2.button("↩️ 기본값으로", key="adm_reset", width="stretch"):
        config.save_overrides({})
        for k in config.SETTINGS:
            st.session_state.pop(f"adm_{k}", None)
        st.rerun()
    st.divider()
    render_ai_cost()
    st.divider()
    render_pagecache()
    st.divider()
    render_papertrade()
    st.divider()
    import broker_ui   # 💵 실매매(4단계 1주 모드, 2026-10-29)
    broker_ui.render()
    st.divider()
    l, r = st.columns(2)
    with l:
        st.markdown("**📌 항상 감시할 종목** (manual_tickers.txt — 한 줄에 하나)")
        p = Path(config.MANUAL_TICKERS_FILE)
        cur = p.read_text(encoding="utf-8") if p.exists() else ""
        txt = st.text_area("종목", cur, height=160, key="adm_manual", label_visibility="collapsed")
        if st.button("저장", key="adm_manual_save"):
            lines = [x.strip().upper() for x in txt.splitlines() if x.strip() and not x.strip().startswith("#")]
            p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            st.success(f"{len(lines)}종목 저장 — 스캐너가 다음 사이클부터 감시합니다.")
    with r:
        st.markdown("**🛠 도구**")
        if st.button("📨 텔레그램 테스트 보내기", key="adm_tg", width="stretch"):
            import notify
            ok = notify.send_telegram("✅ 퀀트 대시보드 텔레그램 테스트입니다.")
            (st.success if ok else st.error)("보냈습니다." if ok else "실패 — .env 의 TELEGRAM_TOKEN·TELEGRAM_CHAT_ID 를 확인하세요.")
        if st.button("🧹 화면 캐시 비우기(가격 등 다시 받기)", key="adm_cache", width="stretch"):
            st.cache_data.clear()
            st.success("비웠습니다.")
    st.divider()
    render_macro()
    st.divider()
    render_guests()
    st.divider()
    st.markdown("**📦 데이터 현황**")
    with closing(db.connect()) as conn:
        ui.cards([{"t": "스캐너 기록(종목-일)", "v": _count(conn, "daily_snapshots")}, {"t": "과거 급락 사례", "v": _count(conn, "case_events")},
                  {"t": "SEC 공시 기록", "v": _count(conn, "sec_hist")}, {"t": "공시 알림", "v": _count(conn, "sec_feed")},
                  {"t": "내부자 매수", "v": _count(conn, "insider_tx", "WHERE code='P'")}, {"t": "Reg SHO 받은 날", "v": _count(conn, "regsho_files", "WHERE status='ok'")},
                  {"t": "종목 리포트", "v": _count(conn, "reports")}, {"t": "예측(성과 공표)", "v": _count(conn, "pred_outcomes")}])
    st.caption(f"DB 파일: {config.DB_PATH}")
    import filelog   # 2026-10-30: 서버는 journalctl 뿐이라 예전 파일 목록이 전부 "없습니다" 였음 → 아침 작업·스캐너·수집기가 DB 폴더에 직접 남김
    warns = filelog.warnings("cases", days=7)
    with st.expander(f"⚠️ 아침 작업 경고·실패(최근 7일) {len(warns)}건", expanded=bool(warns)):
        st.code("\n".join(warns) if warns else "(없음 — cases.log 가 생긴 뒤부터 모여요)", language=None)
    logs = {"스캐너": "scanner", "아침 작업": "cases", "수집기": "collector", "대시보드": "dashboard", "휴대폰 터널": "tunnel"}
    which = st.radio("로그 보기", list(logs), horizontal=True, key="adm_log")
    tail = filelog.tail(logs[which], 30)
    if tail is None:
        st.caption(f"{filelog.path(logs[which])} 파일이 없습니다(서버에선 아침 작업·스캐너·수집기만 파일로 남겨요 — 나머지는 journalctl).")
    else:
        st.code("\n".join(tail) or "(비어 있음)", language=None)


def render_papertrade() -> None:
    """🧪 가상매매 전략별 규칙 — 바꾸면 '새 매수부터' 적용(지난 거래는 매수 때 규칙 그대로)."""
    import papertrade as pt
    st.markdown("**🧪 가상매매 전략별 규칙** — 저장하면 다음 매수부터 적용돼요(이미 산 종목은 살 때 규칙 그대로). 익절·손절은 %, 보유는 거래일, 금액은 $.")
    cur = pt.settings()
    vals: dict[str, dict] = {}
    for k, meta in pt.STRATEGIES.items():
        c = cur[k]
        with st.expander(f"{meta['name']} — {pt.rule_text(c, k)}" + ("" if c["on"] else " · ⏸ 꺼짐"), expanded=False):
            st.caption(meta["desc"])
            cols = st.columns(6)
            v = {"on": cols[0].toggle("켜기", value=bool(c["on"]), key=f"adm_pt_{k}_on")}
            v["tp"] = cols[1].number_input("익절(%)", 0.0, 200.0, float(c["tp"]), step=1.0, key=f"adm_pt_{k}_tp", help="저금통은 0 = 박스 상단")
            v["sl"] = cols[2].number_input("손절(%)", 0.0, 90.0, float(c["sl"]), step=1.0, key=f"adm_pt_{k}_sl", help="저금통은 0 = 박스 이탈(하단 −5%)")
            v["hold"] = cols[3].number_input("보유(거래일)", 0, 60, int(c["hold"]), step=1, key=f"adm_pt_{k}_hold", help="0 = 제한 없음(애프터는 항상 당일 마감)",
                                             disabled=(k == "after"))
            v["usd"] = cols[4].number_input("금액($)", 10.0, 100000.0, float(c["usd"]), step=100.0, key=f"adm_pt_{k}_usd")
            v["n"] = cols[5].number_input("하루 최대 개수", 1, 20, int(c["n"]), step=1, key=f"adm_pt_{k}_n")
            vals[k] = v
    if st.button("💾 가상매매 규칙 저장", key="adm_pt_save", type="primary"):
        pt.save_settings(vals)
        st.success("저장했습니다. 다음 매수부터 새 규칙으로 삽니다(🏆 검증 → 가상매매에서 전략별 결과 비교).")
        st.rerun()


def render_guests() -> None:
    """👥 방문객 링크: 만들기(방문객 전용 주소 · 한 기기 전용) · 목록 · 취소 · 접속 기록."""
    import pandas as pd
    import access
    st.markdown("**👥 방문객 링크** — 비밀번호 없이 열람만 가능한 임시 링크(관리·워치리스트·저금통·노트·일정과 변경 버튼은 안 보임)")
    gtun = (db.get_meta("guest_tunnel_url") or {}).get("value") or ""
    alive, why = _alive(gtun) if gtun else (False, "주소 없음")
    if gtun and not alive:
        st.error(f"❌ 방문객 전용 주소가 지금 응답하지 않아요({why}). 터널이 다시 켜지는 중이면 1~2분 뒤 새 주소가 텔레그램으로 오고 여기 자동으로 바뀝니다. "
                 "계속 이러면 start_guest_dashboard.bat · start_guest_tunnel.bat 가 켜져 있는지 확인하세요.")
        if st.button("🔄 다시 확인", key="gu_recheck"):
            _alive.clear()
            st.rerun()
    if gtun and alive:
        st.caption("✅ 방문객 전용 서버 주소를 씁니다 — 내 주소는 방문객에게 나가지 않고, 이 서버엔 비밀번호 입력창도 없어요.")
    else:
        st.warning("방문객 전용 서버가 꺼져 있어요. start_guest_dashboard.bat · start_guest_tunnel.bat 를 켜면(또는 install_autostart.bat 다시 실행) "
                   "방문객 전용 주소가 텔레그램으로 오고 여기 자동으로 들어갑니다. 그 전에는 링크를 만들지 않는 걸 권해요(내 주소가 노출됨).")
    c1, c2, c3 = st.columns([2, 1, 1])
    name = c1.text_input("이름(누구에게 보내는지)", key="gu_name", placeholder="예: 스터디 민수")
    dur = c2.selectbox("기간", list(access.DURATIONS), index=2, key="gu_dur")
    single = c3.toggle("한 기기 전용", True, key="gu_single", help="처음 연 기기(브라우저)에서만 열리고, 다른 기기에서 열면 막고 알려 줘요")
    base = st.text_input("방문객 링크 주소", value=gtun, key="gu_base", help="방문객 전용 터널 주소가 자동으로 들어갑니다")
    if st.button("🔗 방문객 링크 만들기", key="gu_make", type="primary", disabled=not base or (base == gtun and not alive)):
        tok = access.create(name, access.DURATIONS[dur], single)
        st.session_state["gu_last"] = access.link(base, tok)
    if st.session_state.get("gu_last"):
        st.code(st.session_state["gu_last"], language=None)
        st.caption("오른쪽 위 복사 버튼으로 복사해 보내세요. 사람마다 따로 만들면 누가 퍼뜨렸는지 접속 기록으로 알 수 있어요.")
    df = access.all_links()
    if not df.empty:
        show = df.assign(**{"만든 때": df["created_at"].str[:16].str.replace("T", " "), "마지막 접속": df["last_seen"].fillna("").str[:16].str.replace("T", " "),
                            "기기": ["한 기기" if x else "제한 없음" for x in df.get("single_device", [1] * len(df))]})
        st.dataframe(show[["name", "상태", "남은 시간", "기기", "마지막 접속", "visits", "만든 때"]].rename(columns={"name": "이름", "visits": "접속 횟수"}),
                     hide_index=True, width="stretch")
        live = df[df["상태"] == "사용 가능"]
        if not live.empty:
            d1, d2 = st.columns([3, 1])
            pick = d1.selectbox("취소할 링크", list(live["token"]), key="gu_pick",
                                format_func=lambda t: f"{live.set_index('token').loc[t, 'name']} · 남은 {live.set_index('token').loc[t, '남은 시간']}")
            if d2.button("🚫 취소", key="gu_revoke", width="stretch"):
                access.revoke(pick)
                st.rerun()
            st.markdown("**🔁 현재 주소로 링크 다시 보기** — 터널 주소가 바뀌어도 링크(토큰)는 그대로 유효해요. 아래 링크를 다시 보내면 돼요.")
            st.code(access.link(base or gtun, pick), language=None)
    with st.expander("⚠️ 방문객 경고 문구(입장 전 동의 화면)"):
        txt = st.text_area("문구", access.notice(), height=150, key="gu_notice")
        n1, n2 = st.columns(2)
        if n1.button("저장", key="gu_notice_save", width="stretch"):
            access.set_notice(txt)
            st.success("저장했어요. 다음 방문객부터 보입니다.")
        if n2.button("기본 문구로", key="gu_notice_reset", width="stretch"):
            access.set_notice(access.DEFAULT_NOTICE)
            st.session_state.pop("gu_notice", None)
            st.rerun()
        st.caption("방문객 화면에는 이름·접속 시각·IP 가 옅은 워터마크로 깔려서, 캡처가 퍼지면 누구 화면인지 알 수 있어요.")
    v = access.visits()
    st.markdown("**🕵️ 방문객 접속 기록**")
    if v.empty:
        st.caption("아직 접속 기록이 없습니다.")
        return
    when = pd.to_datetime(v["at"], utc=True).dt.tz_convert("Asia/Seoul").dt.strftime("%m-%d %H:%M")
    flag = ["🚫 차단(다른 기기)" if b else ("⚠️ 새 기기" if n else "") for b, n in zip(v["blocked"], v["new_device"])]
    agreed = pd.to_datetime(v["agreed_at"], utc=True, errors="coerce").dt.tz_convert("Asia/Seoul").dt.strftime("%H:%M") if "agreed_at" in v else None
    st.dataframe(pd.DataFrame({"시간": when, "링크 이름": v["name"], "기기·브라우저": v["device"], "IP": v["ip"], "국가": v["country"],
                               "경고 동의": (agreed.fillna("—") if agreed is not None else "—"), "표시": flag}),
                 hide_index=True, width="stretch")
    n_bad = int(((v["blocked"] == 1) | (v["new_device"] == 1)).sum())  # 한 접속에 두 표시가 겹쳐도 1건
    if n_bad:
        st.error(f"다른 기기 접속 시도·새 기기 {n_bad}건 — 링크가 퍼졌을 수 있어요. 해당 링크를 취소하고 새로 보내세요.")



@st.cache_data(ttl=60, show_spinner=False)
def _alive(url: str) -> tuple[bool, str]:
    """방문객 주소가 실제로 열리는지(1분 캐시)."""
    import requests
    try:
        r = requests.get(url, timeout=6)
        return r.status_code < 500, f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__



def render_macro() -> None:
    """🌎 시장 지표: 수입물가지수 예상치·다음 발표일 직접 입력, 지금 새로 받기."""
    import macro
    st.markdown("**🌎 시장 지표** — 수입물가지수 예상치(컨센서스)는 무료 공식 출처가 없어 직접 입력해요(경제 캘린더 참고)")
    man, d = macro.manual(), macro.get()
    c1, c2, c3 = st.columns(3)
    nd = c1.text_input("다음 발표일(YYYY-MM-DD, 비우면 BLS 일정표 자동)", man.get("next_date") or "", key="mc_date")
    fc = c2.text_input("예상치: 전월비 %(예: 0.2, 비우면 표시 안 함)", "" if man.get("forecast") is None else str(man["forecast"]), key="mc_fc")
    c3.write("")
    if c3.button("저장", key="mc_save", width="stretch"):
        try:
            macro.set_manual(nd.strip() or None, float(fc) if fc.strip() else None)
            st.success("저장했어요.")
        except ValueError:
            st.error("예상치는 숫자로 입력해 주세요(예: 0.2 또는 -0.1).")
    if st.button("🔄 지금 새로 받기(VIX·공포·탐욕·수입물가지수)", key="mc_refresh"):
        with st.spinner("받는 중..."):
            d = macro.refresh(force=True)
    errs = [f"{k}: {v['_err']}" for k, v in d.items() if isinstance(v, dict) and v.get("_err")]
    if errs:
        st.caption("⚠️ 받기 실패: " + " · ".join(errs))
