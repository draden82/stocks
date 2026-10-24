"""Fetch Swedish stock prices and fundamentals for the Spotlight page.
Usage: pip install yfinance pandas; python fetch_prices.py [config.json]
Then open the page and use "Load price data" with the generated prices.json.
Pass the JSON from "Show config JSON" as config.json to fetch your own constituents.
"""
import json, sys
import yfinance as yf

DEFAULT = ("SEB-A SHB-A SWED-A NDA-SE ATCO-A SAND VOLV-B ALFA EPI-A ABB ERIC-B HEXA-B EVO SINCH "
           "TELIA TEL2-B GETI-B SOBI ELEK-B AZN INVE-B ESSITY-B HM-B ASSA-B SKF-B BOL").split()
EXTRA = []          # add any tickers here, e.g. "VOLCAR-B.ST"
BENCHMARK = "^OMX"  # OMXS30

tickers = {t + ".ST" for t in DEFAULT} | set(EXTRA)
if len(sys.argv) > 1:
    cfg = json.load(open(sys.argv[1]))
    tickers |= {t for idx in cfg.values() for t in idx["m"]}

df = yf.download(sorted(tickers) + [BENCHMARK], period="6y", auto_adjust=True, progress=False)["Close"]
df = df[df[BENCHMARK].notna()]
nn = lambda s: [None if v != v else round(float(v), 2) for v in s]
def info(t):
    try:
        i = yf.Ticker(t).info
    except Exception:
        return {}
    px, div = i.get("currentPrice"), i.get("dividendRate")
    de = i.get("debtToEquity")
    m = {"mcap": i.get("marketCap"), "pe": i.get("trailingPE"), "fpe": i.get("forwardPE"),
         "pb": i.get("priceToBook"), "eve": i.get("enterpriseToEbitda"), "evs": i.get("enterpriseToRevenue"),
         "dy": div / px if div and px else None, "roe": i.get("returnOnEquity"),
         "om": i.get("operatingMargins"), "rg": i.get("revenueGrowth"), "de": de / 100 if de else None}
    return {k: v for k, v in m.items() if v is not None}

out = {
    "meta": {t: info(t) for t in sorted(tickers)},
    "dates": [d.strftime("%Y-%m-%d") for d in df.index],
    "benchmark": nn(df[BENCHMARK]),
    "prices": {t: nn(df[t]) for t in df.columns if t != BENCHMARK and df[t].notna().any()},
}
json.dump(out, open("prices.json", "w"))
print(f"Wrote prices.json: {len(out['prices'])} stocks, {len(out['dates'])} days")
