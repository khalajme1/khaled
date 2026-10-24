#!/usr/bin/env python3
"""
Strategy-family exploration on real broker data with an in-sample / out-of-sample split.

    python research/explore.py --spread 0.26 --split 0.6

Each timeframe is loaded from its own MT5 export (data/XAUUSD-STD_M{1,3,5}.csv).
Families: trend pullback (current EA), Bollinger/RSI mean reversion, N-bar breakout.
Edge is measured per trade in R, net of spread, with daily guards disabled;
selection uses in-sample only, then the chosen sets are re-run out-of-sample.
"""
import argparse
import itertools
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd

from backtest import Params, build_features, load_m1, signals, simulate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {tf: os.path.join(ROOT, "data", f"XAUUSD-STD_M{tf}.csv") for tf in (1, 3, 5)}

LOOSE = dict(daily_target=100.0, daily_loss=100.0, max_dd=100.0, max_trades=40,
             max_consec_losses=99, cooldown_bars=0, be_r=99.0, trail_start_r=99.0)


def add_extra(df):
    c = df["close"]
    m, sd = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_mid"], df["bb_sd"] = m, sd
    for n in (10, 20, 40):
        df[f"hh{n}"] = df["high"].rolling(n).max().shift()
        df[f"ll{n}"] = df["low"].rolling(n).min().shift()
    return df


def fam_signals(df, fam, q, spread):
    a = df["atr"]
    ok = (a >= spread * 4)
    if fam == "pullback":
        return None, None
    if fam == "meanrev":
        lo = df["bb_mid"] - q["k"] * df["bb_sd"]
        hi = df["bb_mid"] + q["k"] * df["bb_sd"]
        calm = df["adx"] < q["adx_max"]
        buy = ok & calm & (df["close"] < lo) & (df["rsi"] < q["rsi"])
        sell = ok & calm & (df["close"] > hi) & (df["rsi"] > 100 - q["rsi"])
    elif fam == "breakout":
        n = q["look"]
        strong = df["adx"] >= q["adx_min"]
        buy = ok & strong & (df["close"] > df[f"hh{n}"]) & (df["close"] > df["ema_s"])
        sell = ok & strong & (df["close"] < df[f"ll{n}"]) & (df["close"] < df["ema_s"])
    return buy.fillna(False).values, sell.fillna(False).values


GRIDS = {
    "pullback": dict(sl_atr=[1.0, 1.5, 2.0], tp_r=[0.75, 1.0, 1.5, 2.0], adx_min=[15.0, 20.0, 25.0],
                     rsi_levels=[(40.0, 60.0), (45.0, 55.0), (50.0, 50.0)], max_hold=[0, 24]),
    "meanrev": dict(k=[2.0, 2.5, 3.0], rsi=[20.0, 25.0, 30.0], adx_max=[25.0, 35.0, 100.0],
                    sl_atr=[1.0, 1.5, 2.0], tp_r=[0.5, 0.75, 1.0, 1.5], max_hold=[6, 12, 24]),
    "breakout": dict(look=[10, 20, 40], adx_min=[20.0, 25.0, 30.0], sl_atr=[1.0, 1.5, 2.0],
                     tp_r=[0.75, 1.0, 1.5, 2.0], max_hold=[0, 12, 24]),
}
SESSIONS = [(9, 20), (1, 22)]

_DATA = {}


def _load(tf, split):
    if tf not in _DATA:
        m = load_m1(FILES[tf])
        cut = m.index[int(len(m) * split)].normalize()
        p = Params(tf=tf)
        df_is = add_extra(build_features(m[m.index < cut], p))
        df_oos = add_extra(build_features(m[m.index >= cut], p))
        _DATA[tf] = (df_is, df_oos)
    return _DATA[tf]


def run_one(args):
    tf, fam, q, sess, spread, split, which = args
    df = _load(tf, split)[0 if which == "is" else 1]
    p = Params(tf=tf, start_hour=sess[0], end_hour=sess[1], **LOOSE)
    p = replace(p, sl_atr=q["sl_atr"], tp_r=q["tp_r"], max_hold=q["max_hold"])
    if fam == "pullback":
        rb, rs = q["rsi_levels"]
        p = replace(p, adx_min=q["adx_min"], rsi_buy=rb, rsi_sell=rs)
        r = simulate(df, p, spread)
    else:
        b, s = fam_signals(df, fam, q, spread)
        r = simulate(df, p, spread, b, s)
    t = r["_trades"]
    return dict(tf=tf, fam=fam, sess=f"{sess[0]}-{sess[1]}", **{k: (str(v) if isinstance(v, tuple) else v) for k, v in q.items()},
                which=which, n=r["trades"], per_day=r["trades_per_day"], win=r["win_rate"], avg_r=r["avg_r"],
                pf=r["profit_factor"], tstat=(t.r.mean() / t.r.std() * np.sqrt(len(t))) if len(t) > 2 else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spread", type=float, default=0.26)
    ap.add_argument("--split", type=float, default=0.6)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default="research/results")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    jobs = []
    for tf in (1, 3, 5):
        for fam, grid in GRIDS.items():
            for vals in itertools.product(*grid.values()):
                q = dict(zip(grid.keys(), vals))
                for sess in SESSIONS:
                    jobs.append((tf, fam, q, sess, a.spread, a.split, "is"))
    print(f"{len(jobs)} in-sample runs ...")
    with ProcessPoolExecutor() as ex:
        is_res = pd.DataFrame(list(ex.map(run_one, jobs, chunksize=16)))
    is_res.to_csv(f"{a.out}/explore_is.csv", index=False)

    # pick top in-sample sets per (tf, family) by t-stat, min 60 trades
    picks = []
    for (tf, fam), g in is_res[is_res.n >= 60].groupby(["tf", "fam"]):
        picks += [j for j in g.sort_values("tstat", ascending=False).head(a.top).index]
    oos_jobs = [jobs[i][:-1] + ("oos",) for i in picks]
    with ProcessPoolExecutor() as ex:
        oos_res = pd.DataFrame(list(ex.map(run_one, oos_jobs)))
    oos_res.index = picks
    both = is_res.loc[picks, ["tf", "fam", "sess", "n", "win", "avg_r", "pf", "tstat"]].join(
        oos_res[["n", "win", "avg_r", "pf", "tstat"]], rsuffix="_oos")
    params = is_res.loc[picks].drop(columns=["tf", "fam", "sess", "which", "n", "per_day", "win", "avg_r", "pf", "tstat"])
    both = both.join(params.apply(lambda r: " ".join(f"{k}={v}" for k, v in r.dropna().items()), axis=1).rename("params"))
    both.to_csv(f"{a.out}/explore_top_oos.csv", index=False)
    pd.set_option("display.width", 250, "display.max_colwidth", 90, "display.max_rows", 200)
    print(both.round(3).to_string(index=False))

    print("\nShare of in-sample winners still positive out-of-sample, per tf/family:")
    print(both.assign(pos=both.avg_r_oos > 0).groupby(["tf", "fam"]).pos.mean().round(2).to_string())


if __name__ == "__main__":
    main()
