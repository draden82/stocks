"""Fetch Swedish stock prices and fundamentals for the Spotlight page.
Usage: pip install yfinance pandas; python fetch_prices.py [config.json]
Then open the page and use "Load price data" with the generated prices.json.
Pass the JSON from "Show config JSON" as config.json to fetch your own constituents.
"""
import json, sys
import pandas as pd
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

def row(df, names):
    for n in names:
        if df is not None and n in df.index:
            return df.loc[n]

def at(s, d):
    """Latest annual value reported at least 60 days before d (approximate point-in-time)."""
    if s is None:
        return None
    s = s.dropna()
    s = s[[c + pd.Timedelta(days=60) <= d for c in s.index]]
    return float(s[s.index.max()]) if len(s) else None

def history(t, close, wd):
    tk = yf.Ticker(t)
    try:
        bs, inc, div = tk.balance_sheet, tk.income_stmt, tk.dividends.tz_localize(None)
    except Exception:
        return {}
    R = {"eq": row(bs, ["Stockholders Equity", "Common Stock Equity"]), "sh": row(bs, ["Ordinary Shares Number", "Share Issued"]),
         "debt": row(bs, ["Total Debt"]), "cash": row(bs, ["Cash And Cash Equivalents"]), "rev": row(inc, ["Total Revenue"]),
         "oi": row(inc, ["Operating Income"]), "ni": row(inc, ["Net Income"]), "eb": row(inc, ["EBITDA"]),
         "eps": row(inc, ["Diluted EPS", "Basic EPS"])}
    out = {k: [] for k in ("pb", "pe", "dy", "evs", "eve", "om", "roe")}
    r = lambda a, b: round(a / b, 4) if a is not None and b else None
    for d in wd:
        p = close.get(d)
        p = None if p is None or p != p else float(p)
        g = lambda k: at(R[k], d)
        eq, sh, rev, oi, ni, eb, eps = (g(k) for k in ("eq", "sh", "rev", "oi", "ni", "eb", "eps"))
        mc = p * sh if p and sh else None
        ev = mc + (g("debt") or 0) - (g("cash") or 0) if mc else None
        dv = float(div[(div.index > d - pd.Timedelta(days=365)) & (div.index <= d)].sum())
        out["pb"].append(r(mc, eq)); out["pe"].append(r(p, eps)); out["dy"].append(r(dv, p) if p else None)
        out["evs"].append(r(ev, rev)); out["eve"].append(r(ev, eb)); out["om"].append(r(oi, rev)); out["roe"].append(r(ni, eq))
    return out

wd = df.index[4::5]

out = {
    "meta": {t: info(t) for t in sorted(tickers)},
    "hist": {"dates": [d.strftime("%Y-%m-%d") for d in wd], "v": {t: history(t, df[t], wd) for t in sorted(tickers) if t in df.columns}},
    "dates": [d.strftime("%Y-%m-%d") for d in df.index],
    "benchmark": nn(df[BENCHMARK]),
    "prices": {t: nn(df[t]) for t in df.columns if t != BENCHMARK and df[t].notna().any()},
}
json.dump(out, open("prices.json", "w"))
print(f"Wrote prices.json: {len(out['prices'])} stocks, {len(out['dates'])} days")
