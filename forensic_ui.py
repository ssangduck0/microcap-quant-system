"""종목 상세의 '🧾 공시분석' 섹션 — 공시 분석 프로젝트(덕구 스캔) 보고서를 종목별로 보관·표시."""
import pandas as pd
import streamlit as st

import access

import forensic


def _kst(iso: str) -> str:
    try:
        return pd.to_datetime(iso, utc=True).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(iso)[:16]


def render(ticker: str, key: str = "fx") -> None:
    st.markdown(f"#### 🧾 {ticker} 공시분석 (공시 분석 프로젝트 · 덕구 스캔)")
    df = forensic.reports(ticker)
    url = forensic.project_url()
    if not access.is_guest():  # 👥 방문객: 요청·저장·삭제 버튼 숨김
        c1, c2, c4, c3 = st.columns([2, 1, 2, 3])
        queued = ticker in forensic.queue_list()
        if queued:
            if c4.button("⏰ 자동 스캔 대기 중 · 빼기", key=f"{key}_unq_{ticker}", width="stretch", help="Cowork 예약 작업이 아직 처리하지 않은 요청입니다"):
                forensic.queue_remove(ticker)
                st.rerun()
        elif c4.button("⏰ 자동 스캔 요청 (Cowork)", key=f"{key}_q_{ticker}", width="stretch",
                       help="대기열(queue.txt)에 넣으면 Cowork 예약 작업이 덕구 스캔을 돌려 결과를 자동 저장합니다. 설정은 ⭐ 워치리스트 탭 위쪽 패널"):
            forensic.queue_add(ticker)
            st.rerun()
        if url:
            c1.link_button("🔗 공시 분석 프로젝트 열기", url, width="stretch")
        else:
            new_url = c1.text_input("공시 분석 프로젝트 주소", key=f"{key}_url_{ticker}", placeholder="https://claude.ai/project/...",
                                    help="한 번만 저장하면 모든 종목에 '프로젝트 열기' 버튼이 생깁니다")
            if new_url.startswith("https://claude.ai/"):
                forensic.set_project_url(new_url)
                st.rerun()
        c2.code(ticker, language=None)
        c3.caption("프로젝트에서 티커를 입력해 스캔한 뒤, 결과를 아래 **📥 저장**에 붙여넣으세요(오른쪽 위 복사 버튼으로 티커 복사). "
                   "claude.ai 대화는 외부 프로그램이 직접 가져올 수 없어서 저장해 둔 보고서를 보여 줍니다.")
    if df.empty:
        st.info(f"{ticker} 의 저장된 공시분석이 없습니다.")
    else:
        opts = {f"{_kst(r.created_at)} 저장 · {r.source}" + (f" · 기준일 {r.as_of}" if r.as_of else ""): r for r in df.itertuples()}
        label = st.selectbox("저장본", list(opts), key=f"{key}_ver_{ticker}", label_visibility="collapsed") if len(opts) > 1 else next(iter(opts))
        r = opts[label]
        b = forensic.risk_badges(r.content)
        st.caption(f"**{label}** · 위험 표시 🔴 {b['🔴']} · 🟠 {b['🟠']} · 🟢 {b['🟢']}" + (f" · [원 대화 열기]({r.chat_url})" if r.chat_url else "")
                   + (" · 저장본이 오래됐으면 프로젝트에서 다시 스캔하세요" if len(opts) == 1 else f" · 저장본 {len(opts)}개"))
        paged(r.content, key=f"{key}_{ticker}_{getattr(r, 'id', 0)}")
        if not access.is_guest():  # 👥 방문객: 요청·저장·삭제 버튼 숨김
            with st.expander("🗑 이 저장본 삭제"):
                ok = st.checkbox("정말 삭제합니다", key=f"{key}_delok_{ticker}_{r.id}")
                if st.button("삭제", disabled=not ok, key=f"{key}_del_{ticker}_{r.id}"):
                    forensic.delete(r.id)
                    st.rerun()
    if not access.is_guest():
        with st.expander("📥 공시분석 결과 저장 (붙여넣기 또는 .md/.txt 파일)", expanded=df.empty):
            with st.form(f"{key}_form_{ticker}", clear_on_submit=True):
                text = st.text_area("보고서 내용", height=220, placeholder="공시 분석 프로젝트의 응답 전체를 붙여넣으세요(표·이모지 그대로)", key=f"{key}_text_{ticker}")
                f = st.file_uploader("또는 파일", type=["md", "txt"], key=f"{key}_file_{ticker}")
                chat = st.text_input("원 대화 링크(선택)", placeholder="https://claude.ai/chat/...", key=f"{key}_chat_{ticker}")
                if st.form_submit_button("💾 저장"):
                    body, src = text, "붙여넣기"
                    if f is not None:
                        raw = f.getvalue()
                        for enc in ("utf-8-sig", "cp949"):
                            try:
                                body, src = raw.decode(enc), f"파일({f.name})"
                                break
                            except UnicodeDecodeError:
                                continue
                    if body and body.strip():
                        forensic.add(ticker, body, source=src, chat_url=chat)
                        st.rerun()
                    else:
                        st.warning("내용이 비어 있습니다.")


def render_cowork_setup() -> None:
    """⭐ 워치리스트 탭 위쪽: Cowork 자동 공시분석 설정·대기열·최근 가져오기."""
    import json

    import db
    import watch
    q = forensic.queue_list()
    last = json.loads((db.get_meta("forensic_last_import") or {}).get("value") or "{}")
    import access
    import config as _cfg
    with st.expander(f"🧾 자동 공시분석 — 대기열 {len(q)}개 · 서버가 매일 아침 {_cfg.FORENSIC_PER_RUN}종목 분석", expanded=False):
        st.info(f"🖥 **서버 자동 분석 {'켜짐' if _cfg.FORENSIC_AI else '꺼짐'}** — 서버가 SEC 원문을 직접 받아 Claude 로 덕구 포렌식 스캔(11개 섹션)을 해요. "
                f"매일 아침 갱신 때 대기열에서 {_cfg.FORENSIC_PER_RUN}종목(종목당 약 100~200원, AI 월 예산 안에서). PC 의 Cowork 는 이제 필요 없어요. "
                "AI PICK 상위 5개 중 보고서가 없는 종목은 자동으로 대기열에 들어가요.")
        if q and not access.is_guest() and st.button(f"🤖 지금 서버에서 분석 (대기열 앞 {min(len(q), _cfg.FORENSIC_PER_RUN)}종목 · 1~3분)", key="fa_run"):
            import forensic_ai
            with st.spinner("SEC 원문을 받고 Claude 가 분석하는 중…"):
                try:
                    r = forensic_ai.run(out=lambda *_: None)
                    (st.success if r.get("n") else st.warning)(r.get("msg"))
                except Exception as e:  # noqa: BLE001
                    st.error(f"실패: {e}")
        st.markdown(f"**폴더**: `{forensic.root_dir()}` · 대기열 `queue.txt` → Cowork 가 스캔 → `inbox\\<티커>_<YYYYMMDD>.md` → 대시보드·스캐너가 자동 저장 후 `archive` 로 이동")
        c1, c2 = st.columns([3, 2])
        c1.write("**대기열**: " + (", ".join(q) if q else "비어 있음"))
        wl = watch.scanner_priority()
        if c2.button(f"⭐ 워치리스트 전체({len(wl)})를 대기열에", key="cw_q_all", disabled=not wl):
            n = forensic.queue_add(wl)
            st.success(f"{n}개 추가했습니다.")
            st.rerun()
        if q:
            rm = st.multiselect("대기열에서 뺄 종목", q, key="cw_q_rm")
            if rm and st.button("선택 종목 빼기", key="cw_q_rm_btn"):
                for t in rm:
                    forensic.queue_remove(t)
                st.rerun()
        if last:
            st.caption(f"최근 가져오기 {str(last.get('at', ''))[:16]} UTC · 저장: {', '.join(last.get('imported') or []) or '없음'}")
        for t, e in forensic.errors().items():  # 성공하거나 대기열에서 뺄 때까지 계속 표시
            st.warning(f"{t} 분석 실패({str(e.get('at', ''))[:16]} UTC): {e.get('why', '')}")
        if not st.toggle("🖥 PC Cowork 로 분석하는 방법 보기(예전 방식 · 서버 자동 분석이 있으면 필요 없음)", False, key="cw_show"):
            return
        per_run = st.slider("한 번 실행에 처리할 종목 수", 1, 10, 3, key="cw_per_run", help="많을수록 Cowork 사용량을 많이 씁니다")
        st.markdown("**Cowork 예약 작업 설정 (처음 한 번)**")
        st.markdown(
            "1. **Claude 데스크톱 앱** → 왼쪽 **Scheduled(예약)** → 새 작업\n"
            f"2. 작업 폴더로 **`{forensic.root_dir()}`** 를 고르고(파일 접근 허용), 아래 지시문을 그대로 붙여넣기\n"
            "3. **\"Require this computer\" 를 켜기** — 안 켜면 클라우드에서 실행되어 PC 폴더를 못 읽습니다(대기열은 그대로 남음)\n"
            "4. 반복 주기 정하기(예: 매일 06:30). 저장 후 **Run now** 로 한 번 실행해 폴더 접근을 허용(데스크톱 앱 업데이트 뒤 다시 물을 수 있음)\n"
            "5. 결과가 들어오면 다음 스캐너 사이클이나 대시보드 새로고침 때 자동 저장\n"
            "6. **sec-dilution-scan(덕구) 스킬**이 Cowork 에서 쓸 수 있게 설치되어 있어야 합니다(설정의 스킬·플러그인)")
        st.code(forensic.cowork_task_text(per_run), language=None)
        st.caption("예약 작업이 PC 폴더를 쓰기 때문에 **PC가 켜져 있고 Claude 데스크톱 앱이 열려 있을 때만** 실행됩니다. Cowork 작업은 일반 채팅보다 사용량을 많이 씁니다. "
                   "결과는 Claude 가 만든 분석이라 원문 확인이 필요합니다.")


def pages(md: str) -> list[tuple[str, str]]:
    """덕구 보고서를 섹션별로 나눈다: '## 1. 무슨 회사인지 요약' 같은 번호 제목 기준(앞부분은 '개요')."""
    import re
    lines = (md or "").splitlines()
    heads = [i for i, ln in enumerate(lines) if re.match(r"^#{1,3}\s*\d{1,2}[.)]\s*\S", ln)]
    if not heads:
        heads = [i for i, ln in enumerate(lines) if re.match(r"^##\s+\S", ln)]
    if not heads:
        return [("전체", md or "")]
    out = []
    pre = "\n".join(lines[: heads[0]]).strip()
    if pre:
        out.append(("개요", pre))
    for a, b in zip(heads, heads[1:] + [len(lines)]):
        title = re.sub(r"^#{1,3}\s*", "", lines[a]).strip()
        out.append((title[:28], "\n".join(lines[a:b]).strip()))
    return out


def paged(md: str, key: str) -> None:
    """섹션 이름 버튼으로 바로 가기 + ◀ ▶ 넘기기(한없이 스크롤하지 않게)."""
    import ui_kit as ui
    pg = pages(md)
    titles = [t for t, _ in pg]
    sk = f"{key}_page"
    if st.session_state.get(sk) not in titles:
        st.session_state[sk] = titles[0]

    def move(d):
        i = titles.index(st.session_state.get(sk, titles[0]))
        st.session_state[sk] = titles[max(0, min(len(titles) - 1, i + d))]
    if len(pg) > 1:
        st.pills("섹션", titles, key=sk, label_visibility="collapsed")
    cur = st.session_state.get(sk) or titles[0]
    i = titles.index(cur) if cur in titles else 0
    with st.container(border=True):
        st.markdown(ui.md_safe(pg[i][1]))
    if len(pg) > 1:
        a, b, c = st.columns([1, 2, 1])
        a.button("◀ 이전", key=f"{key}_prev", on_click=move, args=(-1,), disabled=i == 0, width="stretch")
        b.markdown(f'<div style="text-align:center" class="qk-sub">{i + 1} / {len(pg)} · {ui.esc(titles[i])}</div>', unsafe_allow_html=True)
        c.button("다음 ▶", key=f"{key}_next", on_click=move, args=(1,), disabled=i == len(pg) - 1, width="stretch")
