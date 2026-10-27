"""토스증권 바로가기 버튼·표 열."""
import streamlit as st

import tosslink

COLUMN = st.column_config.LinkColumn("토스", display_text="📲 열기", help="토스증권 웹에서 이 종목 주문 화면 열기(새 탭). 로그인은 토스증권에서")


def links(tickers) -> list[str]:
    cmap = tosslink.codes()
    return [tosslink.url(t, cmap) for t in tickers]


def button(ticker: str, key: str = "tl") -> None:
    cmap = tosslink.codes()
    code = cmap.get(str(ticker).upper())
    c1, c2 = st.columns([1, 3])
    c1.link_button("📲 토스증권에서 열기", tosslink.url(ticker, cmap), width="stretch")
    if code:
        c2.caption(f"토스 코드 {code}")
        return
    import access
    if access.is_guest():
        return
    with c2.expander("토스 링크가 안 열리면: 토스증권 웹 주소 붙여넣기(한 번만)"):
        u = st.text_input("토스증권 웹에서 이 종목을 열고 주소창 주소를 붙여넣으세요", key=f"{key}_tossurl_{ticker}",
                          placeholder="https://tossinvest.com/stocks/US20220803004/order")
        if u:
            got = tosslink.from_url(u)
            if got:
                tosslink.save(ticker, got, "직접 입력")
                st.success(f"저장했습니다: {got}")
                st.rerun()
            else:
                st.warning("주소에서 토스 종목 코드(예: US20220803004)를 찾지 못했습니다.")


def with_links(df, col: str = "티커"):
    """표에 '토스' 열을 col 바로 뒤에 넣은 복사본."""
    if df is None or getattr(df, "empty", True) or col not in df.columns or "토스" in df.columns:
        return df
    out = df.copy()
    out.insert(list(out.columns).index(col) + 1, "토스", links(out[col]))
    return out
