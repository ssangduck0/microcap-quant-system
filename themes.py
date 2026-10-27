"""🏷 테마 — 종목을 업종(SEC SIC 코드)·키워드(회사 이름·최근 공시 문장) 테마로 묶고, 오늘 움직인 테마를 찾는다.

python themes.py build   SEC 회사 정보(이름·업종 코드)를 받아 테마 지정(처음 한 번 수 분, 이후 매일 아침 새 종목만)
자동 분류가 틀리면 화면에서 직접 고칠 수 있다(직접 지정이 우선).
"""
from __future__ import annotations

import json
import re
import sys
from contextlib import closing

import pandas as pd

import db

SIC_THEMES = [  # (시작, 끝, 테마)
    (2833, 2836, "바이오·제약"), (8731, 8731, "바이오·제약"), (3841, 3851, "의료기기"), (8000, 8099, "헬스케어 서비스"),
    (7370, 7379, "소프트웨어·IT"), (3570, 3579, "하드웨어·컴퓨터"), (3670, 3679, "반도체·전자부품"), (3660, 3669, "통신장비"), (4800, 4899, "통신"),
    (1000, 1099, "광물·자원"), (1040, 1040, "금·귀금속"), (1200, 1499, "광물·자원"), (1311, 1389, "석유·가스"), (2911, 2911, "석유·가스"), (4911, 4991, "전력·유틸리티"),
    (3711, 3716, "자동차·EV"), (3720, 3729, "항공우주·방산"), (3760, 3769, "항공우주·방산"), (3812, 3812, "항공우주·방산"),
    (4400, 4499, "해운"), (4500, 4599, "항공"), (4200, 4231, "물류·운송"), (6770, 6770, "SPAC·쉘"), (6798, 6798, "리츠·부동산"), (6500, 6599, "리츠·부동산"),
    (6020, 6036, "은행·금융"), (6100, 6299, "증권·금융"), (6300, 6411, "보험"), (5810, 5813, "외식"), (5900, 5999, "소매·이커머스"), (5961, 5961, "소매·이커머스"),
    (2000, 2099, "식품·음료"), (2080, 2086, "식품·음료"), (2100, 2111, "담배·대마"), (7900, 7999, "엔터·게임"), (7810, 7819, "엔터·게임"), (8200, 8299, "교육"),
    (3690, 3699, "전기장비"), (3620, 3629, "전기장비"), (2800, 2899, "화학·소재"), (3310, 3399, "철강·금속"), (1500, 1799, "건설"),
]
KEYWORDS = [  # (정규식, 테마) — 회사 이름·최근 공시 문장
    (r"\bAI\b|artificial intelligence|machine learning|\bLLM\b|generative", "AI"),
    (r"bitcoin|crypto|blockchain|digital asset|\bmining\b.*(?:bitcoin|crypto)|\bBTC\b|ethereum|\bETH\b|solana|token", "크립토·디지털자산"),
    (r"data ?center|\bGPU\b|\bHPC\b|high[- ]performance computing", "데이터센터·HPC"),
    (r"quantum", "퀀텀"), (r"\bdrone|\bUAV\b|unmanned aerial", "드론"), (r"nuclear|uranium|\bSMR\b", "원전·우라늄"),
    (r"robot", "로봇"), (r"\bspace\b|satellite|orbital|launch vehicle", "우주·위성"), (r"lithium|battery|batteries|energy storage", "배터리·ESS"),
    (r"hydrogen|fuel cell", "수소"), (r"solar|photovoltaic", "태양광"), (r"cannabis|hemp|\bCBD\b|marijuana", "담배·대마"),
    (r"\bEV\b|electric vehicle|charging station|charger", "자동차·EV"), (r"gold|silver|precious metal", "금·귀금속"), (r"shipping|vessel|tanker|dry bulk", "해운"),
    (r"cyber ?security", "사이버보안"), (r"\bgaming\b|esports|\bcasino", "엔터·게임"), (r"oncology|cancer|tumor|clinical trial|\bFDA\b", "바이오·제약"),
]
DDL = ["CREATE TABLE IF NOT EXISTS ticker_meta (ticker TEXT PRIMARY KEY, name TEXT, sic INTEGER, sic_desc TEXT, themes TEXT, updated TEXT)",
       "CREATE TABLE IF NOT EXISTS theme_manual (ticker TEXT PRIMARY KEY, themes TEXT, updated TEXT)",
       "CREATE TABLE IF NOT EXISTS daily_move (date TEXT NOT NULL, ticker TEXT NOT NULL, price REAL, chg REAL, vr REAL, r5 REAL, PRIMARY KEY (date, ticker))"]


def ensure_tables(conn) -> None:
    for d in DDL:
        conn.execute(d)
    if "vol" not in {r[1] for r in conn.execute("PRAGMA table_info(daily_move)")}:
        conn.execute("ALTER TABLE daily_move ADD COLUMN vol REAL")  # 오늘 거래량(회전율용)
    conn.commit()


def assign(name: str, sic: int | None, texts: list[str] | None = None) -> list[str]:
    out = []
    if sic:  # 업종 코드는 가장 좁은 범위 하나만(예: 2834 제약은 2800~2899 화학이 아니라 바이오·제약, 1040 금광은 금·귀금속)
        hits = sorted((b - a, t) for a, b, t in SIC_THEMES if a <= sic <= b)
        out += [hits[0][1]] if hits else []
    blob = " ".join([name or ""] + list(texts or []))
    for pat, t in KEYWORDS:
        if re.search(pat, blob, re.I) and t not in out:
            out.append(t)
    return list(dict.fromkeys(out))


def build(client, tickers: list[str] | None = None, limit: int | None = None, out=print) -> int:
    """회사 이름·업종 코드를 받아 테마 지정(이미 있는 종목은 건너뜀). 저장한 수."""
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        if tickers is None:
            tickers = sorted(set(db.read_df("SELECT ticker FROM case_progress WHERE status='done'")["ticker"]))
        have = {r[0] for r in conn.execute("SELECT ticker FROM ticker_meta")}
        todo = [t for t in tickers if t not in have][: limit or None]
        texts = {}
        try:
            for t, lead in conn.execute("SELECT ticker, lead FROM sec_feed WHERE lead IS NOT NULL AND lead != ''"):
                texts.setdefault(t, []).append(lead)
        except Exception:  # noqa: BLE001
            pass
        n = 0
        for i, t in enumerate(todo, 1):
            try:
                cik = client.cik_for(t)
                sub = client.submissions(cik) if cik else {}
            except Exception:  # noqa: BLE001
                sub = {}
            name, sic = sub.get("name") or "", int(sub["sic"]) if str(sub.get("sic") or "").isdigit() else None
            th = assign(name, sic, texts.get(t))
            conn.execute("INSERT OR REPLACE INTO ticker_meta VALUES (?,?,?,?,?,?)", (t, name, sic, sub.get("sicDescription") or "", json.dumps(th, ensure_ascii=False), db.utcnow_iso()))
            n += 1
            if i % 200 == 0:
                conn.commit()
                out(f"  테마 {i:,}/{len(todo):,}")
        conn.commit()
    out(f"테마: {n:,}종목 지정")
    return n


def table() -> pd.DataFrame:
    """ticker, name, sic_desc, themes(list) — 직접 지정이 있으면 그것을 씀."""
    with closing(db.connect()) as conn:
        ensure_tables(conn)
    m = db.read_df("SELECT ticker, name, sic, sic_desc, themes FROM ticker_meta")
    man = db.read_df("SELECT ticker, themes AS manual FROM theme_manual")
    if m.empty and man.empty:
        return pd.DataFrame(columns=["ticker", "name", "sic", "sic_desc", "themes", "manual"])
    m = m.merge(man, on="ticker", how="outer")
    m["themes"] = [json.loads(mn) if isinstance(mn, str) and mn else (json.loads(a) if isinstance(a, str) and a else []) for a, mn in zip(m["themes"], m["manual"])]
    m["manual"] = m["manual"].notna()
    return m


def set_manual(ticker: str, themes: list[str]) -> None:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
        if themes:
            conn.execute("INSERT OR REPLACE INTO theme_manual VALUES (?,?,?)", (ticker.upper(), json.dumps(themes, ensure_ascii=False), db.utcnow_iso()))
        else:
            conn.execute("DELETE FROM theme_manual WHERE ticker=?", (ticker.upper(),))
        conn.commit()


def all_themes(tb: pd.DataFrame | None = None) -> list[str]:
    tb = table() if tb is None else tb
    base = list(dict.fromkeys([t for *_, t in SIC_THEMES] + [t for _, t in KEYWORDS]))
    extra = sorted({x for th in tb["themes"] for x in th} - set(base)) if not tb.empty else []
    return base + extra


def save_moves(conn, day: str, rows: list[tuple]) -> None:
    ensure_tables(conn)
    conn.executemany("INSERT OR REPLACE INTO daily_move (date, ticker, price, chg, vr, r5, vol) VALUES (?,?,?,?,?,?,?)",
                     [(day, *r) if len(r) == 6 else (day, *r, None) for r in rows])
    conn.execute("DELETE FROM daily_move WHERE date < date(?, '-20 day')", (day,))
    conn.commit()


def moves() -> pd.DataFrame:
    with closing(db.connect()) as conn:
        ensure_tables(conn)
    return db.read_df("SELECT * FROM daily_move WHERE date=(SELECT MAX(date) FROM daily_move)")


def hot(tb: pd.DataFrame, mv: pd.DataFrame, chg_min: float = 10.0, vr_min: float = 3.0) -> pd.DataFrame:
    """테마별: 종목 수 · 오늘 움직인 종목 수(등락 ≥ chg_min% 또는 거래량 ≥ vr_min배) · 평균 등락 · 대표 종목."""
    if tb.empty or mv.empty:
        return pd.DataFrame(columns=["테마", "종목", "움직임", "평균 등락(%)", "대표"])
    x = tb.explode("themes").dropna(subset=["themes"]).merge(mv, on="ticker", how="inner")
    if x.empty:
        return pd.DataFrame(columns=["테마", "종목", "움직임", "평균 등락(%)", "대표"])
    x["moved"] = (x["chg"] >= chg_min) | (x["vr"] >= vr_min)
    g = x.groupby("themes")
    out = pd.DataFrame({"종목": g.size(), "움직임": g["moved"].sum(), "평균 등락(%)": g["chg"].mean(),
                        "대표": g.apply(lambda d: ", ".join(d.sort_values("chg", ascending=False)["ticker"].head(4)))}).reset_index().rename(columns={"themes": "테마"})
    return out.sort_values(["움직임", "평균 등락(%)"], ascending=False)


if __name__ == "__main__":
    import config
    import sec
    db.init_db()
    build(sec.SecClient(config.SEC_USER_AGENT))
    sys.exit(0)
