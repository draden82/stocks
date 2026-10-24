"""Fetch Swedish stock prices and fundamentals for the Spotlight page.
Usage: pip install yfinance pandas; python fetch_prices.py [config.json]
Then open the page and use "Load price data" with the generated prices.json.
Pass the JSON from "Show config JSON" as config.json to fetch your own constituents.
"""
import json, os, sys
import pandas as pd
import yfinance as yf

DEFAULT = ("SEB-A SHB-A SWED-A NDA-SE ATCO-A SAND VOLV-B ALFA EPI-A ABB ERIC-B HEXA-B EVO SINCH "
           "TELIA TEL2-B GETI-B SOBI ELEK-B AZN INVE-B ESSITY-B HM-B ASSA-B SKF-B BOL").split()
EXTRA = []          # add any tickers here, e.g. "VOLCAR-B.ST"
BENCHMARK = "^OMX"  # OMXS30

tickers = {t + ".ST" for t in DEFAULT} | set(EXTRA)
UNI = json.load(open("universe.json")) if os.path.exists("universe.json") else None
if UNI:  # the stock universe (index, sector) that drives the page's filters
    tickers |= {x.split("|")[0] + ".ST" for x in UNI["stocks"]}
if len(sys.argv) > 1:
    cfg = json.load(open(sys.argv[1]))
    tickers |= {t for idx in cfg.values() for t in idx["m"]}

df = yf.download(sorted(tickers) + [BENCHMARK], period="6y", auto_adjust=True, progress=False)["Close"]
df = df[df[BENCHMARK].notna()]
old = json.load(open("prices.json")) if os.path.exists("prices.json") else {}
if old.get("dates"):  # keep everything already stored; fresh values win where both exist
    o = pd.DataFrame({**old["prices"], BENCHMARK: old["benchmark"]}, index=pd.to_datetime(old["dates"]))
    df = df.combine_first(o).sort_index()
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

def safe(f):
    try:
        return f()
    except Exception:
        return None

def ext(t):
    """Reports, dividends, news, analyst data, insider trades and annual figures for the Overview/News/Key figures/Analysts tabs."""
    tk, e = yf.Ticker(t), {}
    ed = safe(lambda: tk.get_earnings_dates(limit=24))
    if ed is not None and len(ed):
        ix = [d.tz_localize(None) if d.tzinfo else d for d in ed.index]
        now = pd.Timestamp.now()
        fut, past = sorted(d for d in ix if d > now), sorted((d for d in ix if d <= now), reverse=True)
        e["nx"] = fut[0].strftime("%Y-%m-%d") if fut else None
        e["rp"] = [d.strftime("%Y-%m-%d") for d in past[:4]]
        f = lambda v: None if v is None or v != v else float(v)
        e["eq"] = [{"d": d.strftime("%Y-%m-%d"), "est": f(r.get("EPS Estimate")), "act": f(r.get("Reported EPS")), "sp": f(r.get("Surprise(%)"))}
                   for d, (_, r) in zip(ix, ed.iterrows()) if d <= now and f(r.get("Reported EPS")) is not None]
    re = safe(lambda: tk.revenue_estimate)
    if re is not None and "0q" in re.index and e.get("nx"):
        e["rvs"] = {e["nx"]: float(re.loc["0q", "avg"])}  # estimate recorded before the report
    qi = safe(lambda: row(tk.quarterly_income_stmt, ["Total Revenue"]))
    if qi is not None:
        e["qrev"] = {c.strftime("%Y-%m-%d"): float(v) for c, v in qi.dropna().items()}
    dv = safe(lambda: tk.dividends)
    if dv is not None and len(dv):
        e["dv"] = {"a": float(dv.iloc[-1]), "d": dv.index[-1].strftime("%Y-%m-%d")}
    e["nw"] = []
    for n in safe(lambda: tk.news) or []:
        c = n.get("content", n)
        e["nw"].append({"h": c.get("title"), "p": (c.get("provider") or {}).get("displayName") or c.get("publisher"),
                        "d": (c.get("pubDate") or "")[:10], "u": (c.get("canonicalUrl") or {}).get("url") or c.get("link")})
    rs = safe(lambda: tk.recommendations_summary)
    if rs is not None and len(rs):
        e["rec"] = {k: int(rs.iloc[0][k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    pt = safe(lambda: tk.analyst_price_targets)
    if pt:
        e["pt"] = {k: pt.get(k) for k in ("current", "high", "low", "mean")}
    def insider():
        it = tk.insider_transactions
        it = it[pd.to_datetime(it["Start Date"]) > pd.Timestamp.now() - pd.Timedelta(days=365)]
        tx = it["Transaction"].astype(str).str.lower()
        b, s = tx.str.contains("purchase|buy"), tx.str.contains("sale|sell")
        return {"b": float(it.loc[b, "Value"].sum()), "s": float(it.loc[s, "Value"].sum()), "nb": int(b.sum()), "ns": int(s.sum())}
    e["ins"] = safe(insider)
    bs, inc = safe(lambda: tk.balance_sheet), safe(lambda: tk.income_stmt)
    ys = sorted({c.year for df in (bs, inc) if df is not None for c in df.columns})
    def ser(df, names):
        s = row(df, names)
        d = {c.year: float(v) for c, v in s.dropna().items()} if s is not None else {}
        return [d.get(y) for y in ys]
    e["fin"] = {"y": ys, "rev": ser(inc, ["Total Revenue"]), "ni": ser(inc, ["Net Income"]), "oi": ser(inc, ["Operating Income"]),
                "eb": ser(inc, ["EBITDA"]), "as": ser(bs, ["Total Assets"]), "li": ser(bs, ["Total Liabilities Net Minority Interest"]),
                "eq": ser(bs, ["Stockholders Equity", "Common Stock Equity"]), "nd": ser(bs, ["Net Debt"])}
    return e

wd = df.index[4::5]

out = {
    "uni": UNI,
    "meta": {t: info(t) for t in sorted(tickers)},
    "ext": {t: ext(t) for t in sorted(tickers)},
    "hist": {"dates": [d.strftime("%Y-%m-%d") for d in wd], "v": {t: history(t, df[t], wd) for t in sorted(tickers) if t in df.columns}},
    "dates": [d.strftime("%Y-%m-%d") for d in df.index],
    "benchmark": nn(df[BENCHMARK]),
    "prices": {t: nn(df[t]) for t in df.columns if t != BENCHMARK and df[t].notna().any()},
}
def mdict(a, b):
    return {**(a or {}), **(b or {})}

def mlist(o, n, key):
    m = {key(x): x for x in (o or [])}
    m.update({key(x): x for x in (n or [])})
    return list(m.values())

def snap(o, new):
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    return ([x for x in (o or []) if x["d"] != today] + ([{"d": today, **new}] if new else []))[-800:]

def merge_ext(o, n):
    o, e = o or {}, dict(n)
    for k in ("nx", "dv", "rec", "pt", "ins"):
        if e.get(k) is None and o.get(k) is not None:
            e[k] = o[k]
    cut = (pd.Timestamp.now() - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    nw = [x for x in mlist(o.get("nw"), n.get("nw"), lambda x: x.get("u") or x.get("h")) if (x.get("d") or "9") >= cut]
    e["nw"] = sorted(nw, key=lambda x: x.get("d") or "", reverse=True)[:40]
    e["rp"] = sorted(set(o.get("rp", [])) | set(n.get("rp", [])), reverse=True)[:12]
    e["eq"] = sorted(mlist(o.get("eq"), n.get("eq"), lambda x: x["d"]), key=lambda x: x["d"], reverse=True)[:24]
    e["rvs"], e["qrev"] = mdict(o.get("rvs"), n.get("rvs")), mdict(o.get("qrev"), n.get("qrev"))
    today, rq = pd.Timestamp.now().strftime("%Y-%m-%d"), {x["d"]: x for x in o.get("rq", [])}
    for nx, est in e["rvs"].items():  # compare the stored estimate with the actual once the report is out
        pe = [d for d in e["qrev"] if d <= (pd.Timestamp(nx) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")]
        if nx < today and pe and nx not in rq and est:
            act = e["qrev"][max(pe)]
            rq[nx] = {"d": nx, "est": est, "act": act, "sp": round((act / est - 1) * 100, 2)}
    e["rq"] = sorted(rq.values(), key=lambda x: x["d"], reverse=True)
    e["rec_h"], e["pt_h"], e["ins_h"] = snap(o.get("rec_h"), n.get("rec")), snap(o.get("pt_h"), n.get("pt")), snap(o.get("ins_h"), n.get("ins"))
    of, nf = o.get("fin") or {}, n.get("fin") or {}
    g = lambda f, k: dict(zip(f.get("y", []), f.get(k, [])))
    ys = sorted(set(of.get("y", [])) | set(nf.get("y", [])))
    e["fin"] = {"y": ys, **{k: [g(nf, k).get(y) if g(nf, k).get(y) is not None else g(of, k).get(y) for y in ys]
                            for k in ("rev", "ni", "oi", "eb", "as", "li", "eq", "nd")}}
    return e

def merge(old, out):
    """Fold the previous prices.json into the new one so history only ever grows."""
    if not old:
        return out
    om, oe = old.get("meta", {}), old.get("ext", {})
    out["meta"] = {t: mdict(om.get(t), out["meta"].get(t)) for t in set(om) | set(out["meta"])}
    out["ext"] = {t: merge_ext(oe.get(t), out["ext"].get(t, {})) for t in set(oe) | set(out["ext"])}
    oh, nh = old.get("hist") or {}, out["hist"]
    ds = sorted(set(oh.get("dates", [])) | set(nh["dates"]))
    def mh(t, k):
        m = dict(zip(oh.get("dates", []), (oh.get("v", {}).get(t) or {}).get(k, [])))
        m.update({d: v for d, v in zip(nh["dates"], (nh["v"].get(t) or {}).get(k, [])) if v is not None})
        return [m.get(d) for d in ds]
    ks = ("pb", "pe", "dy", "evs", "eve", "om", "roe")
    out["hist"] = {"dates": ds, "v": {t: {k: mh(t, k) for k in ks} for t in set(oh.get("v", {})) | set(nh["v"])}}
    return out

out = merge(old, out)
json.dump(out, open("prices.json", "w"))
print(f"Wrote prices.json (merged with the previous file): {len(out['prices'])} stocks, {len(out['dates'])} days")
