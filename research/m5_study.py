#!/usr/bin/env python3
"""
M5 strategy shoot-out with anchored walk-forward.

    python research/m5_study.py --spread 0.26 --folds 5

Every parameter set of every family is simulated once over the full M5 history
(daily guards off, one position at a time). Walk-forward then works on the trade
lists: for each test window, the best set per family is chosen on all data
before the window only (by t-stat of R, min trades), and its trades inside the
window are kept. Stitching the windows gives an honest out-of-sample record.
"""
import argparse
import itertools
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd

from backtest import Params, build_features, load_m1, simulate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "XAUUSD-STD_M5.csv")

LOOSE = dict(daily_target=100.0, daily_loss=100.0, max_dd=100.0, max_trades=40,
             max_consec_losses=99, cooldown_bars=0, be_r=99.0, trail_start_r=99.0)
SESSIONS = [(9, 20), (1, 22), (13, 20), (9, 16)]

GRIDS = {
    "pullback": dict(sl_atr=[1.0, 1.5, 2.0], tp_r=[1.0, 1.5, 2.0], adx_min=[15.0, 20.0, 25.0],
                     rsi=[(40.0, 60.0), (45.0, 55.0), (50.0, 50.0)], be=[0.8, 99.0]),
    "breakout": dict(look=[10, 20, 40], adx_min=[20.0, 25.0, 30.0], sl_atr=[1.5, 2.0], tp_r=[1.0, 1.5, 2.0]),
    "bb_touch": dict(k=[2.0, 2.5, 3.0], rsi=[25.0, 30.0, 100.0], adx_max=[25.0, 35.0, 100.0],
                     sl_atr=[1.5, 2.0, 3.0], tp_r=[0.5, 0.75, 1.0], exit_mid=[True, False]),
    "bb_confirm": dict(k=[2.0, 2.5, 3.0], adx_max=[25.0, 35.0, 100.0], sl_atr=[1.0, 1.5, 2.0],
                       tp_r=[0.5, 0.75, 1.0, 1.5], exit_mid=[True, False]),
    "stretch": dict(m=[2.0, 3.0, 4.0], rsi=[25.0, 30.0, 100.0], sl_atr=[1.5, 2.0, 3.0],
                    tp_r=[0.5, 0.75, 1.0], exit_ema=[True, False]),
}

_DF = None


def features():
    global _DF
    if _DF is None:
        df = build_features(load_m1(DATA), Params(tf=5))
        c = df["close"]
        df["bb_mid"] = c.rolling(20).mean()
        df["bb_sd"] = c.rolling(20).std()
        for n in (10, 20, 40):
            df[f"hh{n}"] = df["high"].rolling(n).max().shift()
            df[f"ll{n}"] = df["low"].rolling(n).min().shift()
        df["z"] = (c - df["ema_s"]) / df["atr"]
        _DF = df
    return _DF


def family_signals(df, fam, q, spread):
    """returns buy, sell, exit_buy, exit_sell (numpy bool arrays or None)"""
    c, o = df["close"], df["open"]
    ok = df["atr"] >= spread * 4
    xb = xs = None
    if fam == "breakout":
        n = q["look"]
        strong = df["adx"] >= q["adx_min"]
        buy = ok & strong & (c > df[f"hh{n}"]) & (c > df["ema_s"])
        sell = ok & strong & (c < df[f"ll{n}"]) & (c < df["ema_s"])
    elif fam in ("bb_touch", "bb_confirm"):
        lo = df["bb_mid"] - q["k"] * df["bb_sd"]
        hi = df["bb_mid"] + q["k"] * df["bb_sd"]
        calm = df["adx"] < q["adx_max"]
        if fam == "bb_touch":
            buy = ok & calm & (c < lo) & (df["rsi"] < q["rsi"])
            sell = ok & calm & (c > hi) & (df["rsi"] > 100 - q["rsi"])
        else:  # previous bar closed outside, this bar closes back inside with a reversal body
            buy = ok & calm & (c.shift() < lo.shift()) & (c > lo) & (c > o)
            sell = ok & calm & (c.shift() > hi.shift()) & (c < hi) & (c < o)
        if q["exit_mid"]:
            xb, xs = (c >= df["bb_mid"]).values, (c <= df["bb_mid"]).values
    elif fam == "stretch":
        buy = ok & (df["z"] < -q["m"]) & (df["rsi"] < q["rsi"])
        sell = ok & (df["z"] > q["m"]) & (df["rsi"] > 100 - q["rsi"])
        if q["exit_ema"]:
            xb, xs = (c >= df["ema_f"]).values, (c <= df["ema_f"]).values
    return buy.fillna(False).values, sell.fillna(False).values, xb, xs


def run_combo(args):
    fam, q, sess, spread = args
    df = features()
    p = Params(tf=5, start_hour=sess[0], end_hour=sess[1], **LOOSE)
    p = replace(p, sl_atr=q["sl_atr"], tp_r=q["tp_r"])
    if fam == "pullback":
        p = replace(p, adx_min=q["adx_min"], rsi_buy=q["rsi"][0], rsi_sell=q["rsi"][1],
                    be_r=q["be"], trail_start_r=99.0 if q["be"] > 50 else 1.0)
        r = simulate(df, p, spread)
    else:
        b, s, xb, xs = family_signals(df, fam, q, spread)
        p = replace(p, max_hold=24)
        r = simulate(df, p, spread, b, s, xb, xs)
    t = r["_trades"]
    label = f"{fam} {sess[0]}-{sess[1]}h " + " ".join(f"{k}={v}" for k, v in q.items())
    return label, fam, t["entry_time"].values, t["r"].values


def stats(r):
    r = np.asarray(r, float)
    if len(r) < 3:
        return dict(n=len(r), win=np.nan, avg_r=np.nan, pf=np.nan, t=np.nan)
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=len(r), win=(r > 0).mean() * 100, avg_r=r.mean(), pf=pos / neg if neg > 0 else np.inf,
                t=r.mean() / r.std() * np.sqrt(len(r)))


def equity_report(times, rs, days, risk):
    """compound R-trades at `risk`% per trade; return avg daily %, maxDD %, worst day %"""
    s = pd.Series(np.asarray(rs) * risk / 100.0, index=pd.DatetimeIndex(times)).sort_index()
    eq = (1 + s).cumprod()
    peak = eq.cummax()
    dd = ((peak - eq) / peak).max() * 100 if len(eq) else 0.0
    daily = (1 + s).groupby(s.index.normalize()).prod().reindex(days).fillna(1.0) - 1
    total = (eq.iloc[-1] - 1) * 100 if len(eq) else 0.0
    return daily.mean() * 100, dd, daily.min() * 100, total, (daily * 100 >= 2.5).mean() * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spread", type=float, default=0.26)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--test-share", type=float, default=0.6, help="share of history used for test windows")
    ap.add_argument("--min-trades", type=int, default=50)
    ap.add_argument("--out", default=os.path.join(ROOT, "research", "results"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    jobs = []
    for fam, grid in GRIDS.items():
        for vals in itertools.product(*grid.values()):
            q = dict(zip(grid.keys(), vals))
            for sess in SESSIONS:
                jobs.append((fam, q, sess, a.spread))
    print(f"{len(jobs)} parameter sets over the full M5 history ...", flush=True)
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(run_combo, jobs, chunksize=8))

    df = features()
    t0, t1 = df.index[0], df.index[-1]
    test_start = t0 + (t1 - t0) * (1 - a.test_share)
    edges = [test_start + (t1 - test_start) * i / a.folds for i in range(a.folds + 1)]
    print(f"History {t0.date()} .. {t1.date()}; test windows from {test_start.date()}, {a.folds} folds\n")

    fams = list(GRIDS) + ["ALL"]
    oos = {f: ([], []) for f in fams}
    chosen = {f: [] for f in fams}
    for k in range(a.folds):
        w0, w1 = np.datetime64(edges[k]), np.datetime64(edges[k + 1])
        best = {}
        for label, fam, times, rs in res:
            m = times < w0
            st = stats(rs[m])
            if st["n"] < a.min_trades or not np.isfinite(st["t"]):
                continue
            for key in (fam, "ALL"):
                if key not in best or st["t"] > best[key][0]:
                    best[key] = (st["t"], label, times, rs)
        for f in fams:
            if f not in best:
                continue
            _, label, times, rs = best[f]
            m = (times >= w0) & (times < w1)
            oos[f][0].extend(times[m])
            oos[f][1].extend(rs[m])
            chosen[f].append((str(edges[k].date()), label, stats(rs[m])))

    days = pd.DatetimeIndex(pd.unique(df.index[df.index >= test_start].normalize()))
    rows = []
    for f in fams:
        st = stats(oos[f][1])
        row = dict(family=f, **st, per_day=st["n"] / len(days))
        for risk in (0.5, 1.0, 2.0):
            avg, dd, worst, total, hit = equity_report(oos[f][0], oos[f][1], days, risk)
            row.update({f"avg_day@{risk}%": avg, f"maxDD@{risk}%": dd, f"total@{risk}%": total})
        rows.append(row)
    table = pd.DataFrame(rows).set_index("family")
    pd.set_option("display.width", 250, "display.max_colwidth", 140)
    print("=== Stitched OUT-OF-SAMPLE results (walk-forward), spread", a.spread, "===")
    print(table.round(3).to_string())
    table.to_csv(os.path.join(a.out, "m5_walkforward.csv"))

    print("\n=== Parameter set chosen per fold (and its out-of-sample result) ===")
    for f in fams:
        print(f"\n[{f}]")
        for start, label, st in chosen[f]:
            print(f"  {start}: {label}  ->  n={st['n']} win={st['win']:.1f}% avgR={st['avg_r']:+.3f} PF={st['pf']:.2f}")

    # full-history ranking for reference (in-sample, optimistic)
    full = sorted(((stats(rs), label) for label, fam, times, rs in res), key=lambda x: -np.nan_to_num(x[0]["t"]))[:10]
    print("\n=== Top-10 on full history (IN-SAMPLE, optimistic, for reference only) ===")
    for st, label in full:
        print(f"  t={st['t']:.2f} n={st['n']} win={st['win']:.1f}% avgR={st['avg_r']:+.3f} PF={st['pf']:.2f}  {label}")


if __name__ == "__main__":
    main()
