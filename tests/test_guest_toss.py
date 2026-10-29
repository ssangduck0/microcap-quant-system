import os as _os_qs; _os_qs.environ.setdefault("QS_ROOT", _os_qs.path.dirname(_os_qs.path.dirname(_os_qs.path.abspath(__file__))))  # 프로젝트 폴더(어느 PC 에서나)
"""토스 데이터 정책 B안(2026-10-29): 방문객에게 토스 자료 화면 3곳 숨김 — 메뉴(HIDDEN_PAGES) · 탭(HIDDEN_TABS) · 화면 첫 줄 가드. 주인은 그대로."""
import os, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["QUANT_DB"] = os.path.join(tmp, "q.db"); os.environ["SEC_USER_AGENT"] = "T t@e.com"
os.environ.pop("QUANT_TEST_ALL_PAGES", None)
sys.path.insert(0, os.environ["QS_ROOT"])
import db, access, tabs
db.init_db()

# 1) 숨길 목록: 메뉴 2개(움직임·애프터) + 수급의 장마감 체크리스트 탭
assert {"movers", "after"} <= access.HIDDEN_PAGES and {"admin", "watch", "piggy", "notes", "events"} <= access.HIDDEN_PAGES
assert access.HIDDEN_TABS == {"accum": {"close"}} and "토스" in access.GUEST_HIDDEN_NOTE

# 2) 탭 거르기(순수 함수): 방문객이면 close 탭이 빠지고, 주인·다른 화면은 그대로
items = [("accum", "🧲 매집 의심", lambda: None), ("setup", "🕵️ 세력·셋업", lambda: None), ("close", "🎯 장마감 체크리스트", lambda: None)]
assert [k for k, _, _ in tabs.visible_items("accum", items, True)] == ["accum", "setup"]
assert tabs.visible_items("accum", items, False) == items and tabs.visible_items("alerts", items, True) == items

# 3) 화면 3곳: 방문객이면 안내 한 줄만(위젯·제목 없음) · 주인이면 예전 그대로
from streamlit.testing.v1 import AppTest


def _app(mod, guest):
    import os, sys, importlib
    sys.path.insert(0, os.environ["QS_ROOT"])
    import streamlit as st
    if guest:
        st.session_state["_guest"] = {"token": "t", "name": "손님", "left_min": 60}
    importlib.import_module(mod).render()


for mod in ("mover_ui", "afterscalp_ui", "closewatch_ui"):
    g = AppTest.from_function(_app, kwargs={"mod": mod, "guest": True}, default_timeout=120).run()
    assert not g.exception, (mod, [e.value for e in g.exception])
    assert any("방문객" in c.value and "토스" in c.value for c in g.caption), (mod, [c.value for c in g.caption])
    assert not g.radio and not g.metric and not g.selectbox and not g.slider, mod
    o = AppTest.from_function(_app, kwargs={"mod": mod, "guest": False}, default_timeout=120).run()
    assert not o.exception, (mod, [e.value for e in o.exception])
    assert not any("방문객 화면에서는" in c.value for c in o.caption), mod
    assert o.radio or o.metric or o.selectbox or o.slider or any(x.value for x in o.markdown) or o.info, mod   # 주인은 뭔가 그려짐

# 4) 방문객 도우미: 주인은 False·아무것도 안 그림
def _owner():
    import os, sys
    sys.path.insert(0, os.environ["QS_ROOT"])
    import access, streamlit as st
    st.write("blocked" if access.guest_block() else "shown")


a = AppTest.from_function(_owner, default_timeout=60).run()
assert not a.exception and any("shown" in m.value for m in a.markdown) and not a.caption
print("ALL OK")
