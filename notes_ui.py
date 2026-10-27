"""'노트' 탭: 전략 메모를 대시보드 안에 자동 저장한다 (입력창 밖을 클릭하거나 Ctrl+Enter 를 누르면 바로 DB 에 저장).

DB(quant.db)에 저장되므로 PC를 껐다 켜도 남고, 스캐너 데이터와 같은 곳에서 관리됩니다. db.py 가 이전 버전이어도 동작하도록 테이블은 여기서 직접 만듭니다.
"""
from contextlib import closing
from datetime import datetime

import streamlit as st

import db

DDL = "CREATE TABLE IF NOT EXISTS free_notes (title TEXT PRIMARY KEY, body TEXT, updated_at TEXT)"


def _conn():
    c = db.connect()
    c.execute(DDL)
    return c


def list_titles() -> list[str]:
    with closing(_conn()) as c:
        return [r["title"] for r in c.execute("SELECT title FROM free_notes ORDER BY updated_at DESC, title")]


def get(title: str) -> str:
    with closing(_conn()) as c:
        r = c.execute("SELECT body FROM free_notes WHERE title=?", (title,)).fetchone()
    return r["body"] if r else ""


def save(title: str, body: str) -> None:
    with closing(_conn()) as c:
        c.execute("INSERT OR REPLACE INTO free_notes (title, body, updated_at) VALUES (?,?,?)", (title, body, db.utcnow_iso()))
        c.commit()


def delete(title: str) -> None:
    with closing(_conn()) as c:
        c.execute("DELETE FROM free_notes WHERE title=?", (title,))
        c.commit()


def decode_text(raw: bytes) -> str:
    """메모장 파일 디코딩: UTF-8(BOM 포함) 먼저, 안 되면 한국어 윈도우 기본 인코딩(cp949)."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def export_all() -> str:
    with closing(_conn()) as c:
        rows = c.execute("SELECT title, body, updated_at FROM free_notes ORDER BY title").fetchall()
    return "\n\n".join(f"===== {r['title']}  (수정 {r['updated_at']}) =====\n{r['body']}" for r in rows)


def _create(title_key: str) -> None:
    """'만들기' 버튼 콜백: 위젯이 만들어지기 전에 실행되므로 입력창 값을 안전하게 비울 수 있다."""
    title = st.session_state.get(title_key, "").strip()
    if not title:
        return
    if title not in list_titles():
        save(title, "")
    st.session_state["note_pick"] = title
    st.session_state[title_key] = ""


def _on_change(title: str, key: str) -> None:
    save(title, st.session_state[key])
    st.session_state["note_saved_at"] = (title, datetime.now().strftime("%H:%M:%S"))


def render() -> None:
    st.subheader("📝 노트")
    st.caption("입력창 밖을 클릭하거나 Ctrl+Enter 를 누르면 **자동 저장**됩니다. DB에 저장되어 PC를 껐다 켜도 남아 있습니다.")

    c1, c2 = st.columns([2, 1])
    new = c1.text_input("새 노트 제목", key="note_new_title", placeholder="예: 장 마감 매매 방법")
    c2.write("")
    c2.button("➕ 만들기", width="stretch", on_click=_create, args=("note_new_title",))

    ups = st.file_uploader("메모장(.txt) 파일 가져오기 — 여러 개 선택 가능", type=["txt", "md"], accept_multiple_files=True, key="note_upload")
    if ups:
        have = set(list_titles())
        imported = [u.name.rsplit(".", 1)[0] for u in ups if u.name.rsplit(".", 1)[0] not in have]
        for u in ups:
            t = u.name.rsplit(".", 1)[0]
            if t not in have:
                save(t, decode_text(u.getvalue()))
        if imported:
            st.session_state["note_pick"] = imported[0]
            st.success(f"{len(imported)}개 가져왔습니다: " + ", ".join(imported) + "  (같은 제목이 이미 있으면 덮어쓰지 않고 건너뜁니다)")
            st.rerun()

    titles = list_titles()
    if not titles:
        st.info("노트가 없습니다. 위에서 제목을 입력하고 '만들기'를 누르거나, 메모장 파일을 가져오세요.")
        return
    pick = st.selectbox("노트 선택", titles, key="note_pick")
    key = f"note_body_{pick}"
    if key not in st.session_state:
        st.session_state[key] = get(pick)
    st.text_area("내용", key=key, height=420, on_change=_on_change, args=(pick, key))
    saved = st.session_state.get("note_saved_at")
    st.caption(f"마지막 자동 저장: {saved[1]} ({saved[0]})" if saved else "아직 수정하지 않았습니다.")

    b1, b2 = st.columns([1, 1])
    b1.download_button("⬇️ 전체 노트 백업(.txt)", export_all().encode("utf-8-sig"), file_name="notes_backup.txt", mime="text/plain")
    with b2.expander("이 노트 삭제"):
        ok = st.checkbox("정말 삭제합니다", key=f"note_del_ok_{pick}")
        if st.button("삭제", disabled=not ok, key=f"note_del_{pick}"):
            delete(pick)
            st.session_state.pop(key, None)
            st.rerun()
