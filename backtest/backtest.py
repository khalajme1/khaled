"""Backtest of the Khaled Scalp 1m indicator logic on 1-minute OHLC(V) data.

Usage:
    python backtest/backtest.py data.csv            # default settings
    python backtest/backtest.py data.csv --grid     # search for the best settings

The CSV can be a TradingView "Export chart data" file: it needs time, open,
high, low, close columns (volume optional). Time may be unix seconds or a date string.
"""
import argparse
import itertools

import numpy as np
import pandas as pd

DEFAULTS = dict(
    fast_len=9, slow_len=21, trend_len=50,
    use_htf=True, htf_minutes=5, htf_len=50,
    rsi_len=7, rsi_pull_low=40, rsi_pull_high=60, pullback_bars=5,
    use_vwap=True, atr_len=14, min_atr_ratio=0.7, cooldown=2,
    tp_mult=1.0, sl_mult=1.5, max_bars=20,
)


def load(path):
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    t = df["time"]
    if np.issubdtype(t.dtype, np.number):
        df["time"] = pd.to_datetime(t, unit="s", utc=True)
    else:
        df["time"] = pd.to_datetime(t, utc=True)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df.sort_values("time").reset_index(drop=True)[["time", "open", "high", "low", "close", "volume"]]


def ema(s, n):
    # Pine ta.ema: seeded with the SMA of the first n values
    out = np.full(len(s), np.nan)
    v = s.to_numpy(float)
    if len(v) < n:
        return pd.Series(out, index=s.index)
    out[n - 1] = v[:n].mean()
    a = 2 / (n + 1)
    for i in range(n, len(v)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return pd.Series(out, index=s.index)


def rma(s, n):
    out = np.full(len(s), np.nan)
    v = s.to_numpy(float)
    start = np.argmax(~np.isnan(v))
    if len(v) - start < n:
        return pd.Series(out, index=s.index)
    out[start + n - 1] = v[start:start + n].mean()
    for i in range(start + n, len(v)):
        out[i] = (out[i - 1] * (n - 1) + v[i]) / n
    return pd.Series(out, index=s.index)


def indicators(df, p):
    d = df.copy()
    c, h, l = d["close"], d["high"], d["low"]
    d["emaF"], d["emaS"], d["emaT"] = ema(c, p["fast_len"]), ema(c, p["slow_len"]), ema(c, p["trend_len"])
    ch = c.diff()
    up, dn = rma(ch.clip(lower=0), p["rsi_len"]), rma(-ch.clip(upper=0), p["rsi_len"])
    d["rsi"] = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / dn)))
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    tr.iloc[0] = h.iloc[0] - l.iloc[0]
    d["atr"] = rma(tr, p["atr_len"])
    d["atrAvg"] = d["atr"].rolling(50).mean()

    # Session VWAP, reset each day
    day = d["time"].dt.date
    pv = (d[["high", "low", "close"]].mean(axis=1) * d["volume"]).groupby(day).cumsum()
    vol = d["volume"].groupby(day).cumsum()
    d["vwap"] = np.where(vol > 0, pv / vol.replace(0, np.nan), np.nan)

    # HTF: previous closed bar of the higher timeframe
    bucket = d["time"].dt.floor(f"{p['htf_minutes']}min")
    htf_close = d.groupby(bucket)["close"].last()
    htf = pd.DataFrame({"c": htf_close, "e": ema(htf_close, p["htf_len"])}).shift(1)
    d["htfClose"] = bucket.map(htf["c"])
    d["htfEma"] = bucket.map(htf["e"])
    return d


def barssince_le(cond, n):
    # True where cond happened within the last n bars (including current)
    return cond.astype(int).rolling(n + 1, min_periods=1).max().astype(bool)


def signals(d, p):
    n = p["pullback_bars"]
    htf_up = (not p["use_htf"]) | (d["htfClose"] > d["htfEma"])
    htf_dn = (not p["use_htf"]) | (d["htfClose"] < d["htfEma"])
    trend_up = (d.emaF > d.emaS) & (d.emaS > d.emaT) & (d.close > d.emaT) & htf_up
    trend_dn = (d.emaF < d.emaS) & (d.emaS < d.emaT) & (d.close < d.emaT) & htf_dn
    pulled_l = barssince_le(d.low <= d.emaS, n) & (d.rsi.rolling(n).min() < p["rsi_pull_low"])
    pulled_s = barssince_le(d.high >= d.emaS, n) & (d.rsi.rolling(n).max() > p["rsi_pull_high"])
    trig_l = (d.close > d.emaF) & (d.close > d.open) & (d.close > d.high.shift()) & (d.rsi > 50) & (d.rsi < 80)
    trig_s = (d.close < d.emaF) & (d.close < d.open) & (d.close < d.low.shift()) & (d.rsi < 50) & (d.rsi > 20)
    novwap = d.vwap.isna() | (not p["use_vwap"])
    vol_ok = d.atr >= d.atrAvg * p["min_atr_ratio"]
    long_ = trend_up & pulled_l & trig_l & (novwap | (d.close > d.vwap)) & vol_ok
    short = trend_dn & pulled_s & trig_s & (novwap | (d.close < d.vwap)) & vol_ok
    return long_.fillna(False).to_numpy(), short.fillna(False).to_numpy()


def simulate(d, p):
    long_, short = signals(d, p)
    o, h, l, c, atr = (d[k].to_numpy(float) for k in ("open", "high", "low", "close", "atr"))
    trades = []
    pos, last_exit = 0, -10**9
    for i in range(len(d)):
        if pos != 0 and i > ebar:
            hit_sl = l[i] <= sl if pos == 1 else h[i] >= sl
            hit_tp = h[i] >= tp if pos == 1 else l[i] <= tp
            timed = p["max_bars"] > 0 and i - ebar >= p["max_bars"]
            if hit_sl or hit_tp or timed:
                exit_px = sl if hit_sl else tp if hit_tp else c[i]
                pnl = (exit_px - entry) * pos
                trades.append((d.time.iloc[ebar], pos, entry, exit_px, pnl, pnl > 0))
                pos, last_exit = 0, i
        if pos == 0 and i - last_exit > p["cooldown"] and (long_[i] or short[i]):
            pos = 1 if long_[i] else -1
            entry, ebar = c[i], i
            tp = entry + pos * atr[i] * p["tp_mult"]
            sl = entry - pos * atr[i] * p["sl_mult"]
    return pd.DataFrame(trades, columns=["time", "dir", "entry", "exit", "pnl", "win"])


def summary(t, days):
    if t.empty:
        return dict(trades=0, per_day=0.0, win_rate=0.0, net=0.0, pf=0.0)
    gross_win = t.pnl[t.pnl > 0].sum()
    gross_loss = -t.pnl[t.pnl < 0].sum()
    return dict(
        trades=len(t), per_day=round(len(t) / max(days, 1), 1),
        win_rate=round(float(t.win.mean()) * 100, 1), net=round(float(t.pnl.sum()), 2),
        pf=round(float(gross_win / gross_loss), 2) if gross_loss > 0 else float("inf"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--grid", action="store_true")
    args = ap.parse_args()
    df = load(args.csv)
    days = df.time.dt.date.nunique()
    print(f"{len(df)} bars, {days} days, {df.time.iloc[0]} -> {df.time.iloc[-1]}")

    base = dict(DEFAULTS)
    print("Default settings:", summary(simulate(indicators(df, base), base), days))
    if not args.grid:
        return

    grid = dict(
        tp_mult=[0.5, 0.75, 1.0, 1.5], sl_mult=[1.0, 1.5, 2.0],
        pullback_bars=[3, 5, 8], min_atr_ratio=[0.0, 0.7, 1.0],
        use_htf=[True, False], cooldown=[0, 2],
    )
    cache = {}
    rows = []
    for combo in itertools.product(*grid.values()):
        p = dict(base, **dict(zip(grid, combo)))
        key = p["use_htf"]  # indicators only depend on inputs that are not in the grid
        if key not in cache:
            cache[key] = indicators(df, p)
        rows.append(dict(zip(grid, combo), **summary(simulate(cache[key], p), days)))
    res = pd.DataFrame(rows)
    res = res[res.trades >= 10]
    pd.set_option("display.width", 200)
    print("\nTop 15 by net profit (profit factor > 1):")
    print(res[res.pf > 1].sort_values("net", ascending=False).head(15).to_string(index=False))
    print("\nTop 10 by win rate (with net > 0):")
    print(res[res.net > 0].sort_values(["win_rate", "net"], ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
