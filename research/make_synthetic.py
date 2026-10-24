#!/usr/bin/env python3
"""
Generates SYNTHETIC gold-like M1 bars, only to smoke-test backtest.py.
Results on this data say nothing about real-market profitability.

    python research/make_synthetic.py out.csv --days 120
"""
import argparse

import numpy as np
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    idx = pd.date_range("2026-01-05", periods=a.days * 1440, freq="1min")
    idx = idx[(idx.dayofweek < 5) & (idx.hour != 23)]  # weekdays, daily break hour
    n = len(idx)

    # intraday volatility profile: quiet Asia, active London / NY
    hour_vol = np.array([0.6] * 7 + [0.9, 1.3, 1.4, 1.2, 1.1, 1.2, 1.6, 1.9, 1.7, 1.4, 1.1, 0.9, 0.8, 0.7, 0.6, 0.6, 0.5])
    vol = 0.55 * hour_vol[idx.hour] * np.exp(np.cumsum(rng.normal(0, 0.01, n)) % 0.6 - 0.3)
    drift = np.repeat(rng.normal(0, 0.02, n // 240 + 1), 240)[:n]  # slow regimes
    steps = drift + vol * rng.standard_t(4, n) / np.sqrt(2)
    close = 3300 + np.cumsum(steps)
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, vol * 0.6, (2, n)))
    high = np.maximum(open_, close) + wick[0]
    low = np.minimum(open_, close) - wick[1]
    pd.DataFrame({"time": idx.strftime("%Y.%m.%d %H:%M"), "open": open_, "high": high, "low": low,
                  "close": close}).round(2).to_csv(a.out, index=False)
    print(f"wrote {n:,} synthetic bars to {a.out}")


if __name__ == "__main__":
    main()
