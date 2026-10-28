"""PC: 종목 목록(universe_tickers.txt)의 야후 일봉 10년치 + 분할(Stock Splits) 을 받아 pickle 로 저장. 사용: python yahoo_dl.py <dir>"""
import os, sys, time, pickle, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import yfinance as yf
D = sys.argv[1]
tickers = [t.strip().upper() for t in open(os.path.join(D, "universe_tickers.txt"), encoding="utf-8") if t.strip()]
out: dict[str, pd.DataFrame] = {}
t0 = time.time()
CH = 150
for i in range(0, len(tickers), CH):
    chunk = tickers[i:i + CH]
    try:
        df = yf.download(chunk, period="10y", group_by="ticker", progress=False, threads=True, auto_adjust=False, actions=True)
    except Exception as e:  # noqa: BLE001
        print(f"chunk {i} ERR {type(e).__name__}: {str(e)[:100]}", flush=True)
        continue
    for t in chunk:
        try:
            d = df[t] if isinstance(df.columns, pd.MultiIndex) else df
            d = d[["Close", "Volume", "Stock Splits"]].dropna(subset=["Close"])
            if len(d):
                out[t] = d
        except Exception:  # noqa: BLE001
            pass
    print(f"{i + len(chunk)}/{len(tickers)} · got {len(out)} · {time.time()-t0:.0f}s", flush=True)
pickle.dump(out, open(os.path.join(D, "yahoo_px.pkl"), "wb"))
rows = sum(len(d) for d in out.values())
print(f"saved {len(out)} tickers · {rows:,} rows · {time.time()-t0:.0f}s", flush=True)
print("DONE")
