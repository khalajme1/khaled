"""Backtest of the Khaled Scalp indicator logic on intraday OHLC(V) data.

Usage:
    python backtest/backtest.py data.csv                         # default settings
    python backtest/backtest.py data.csv --preset gold           # a market preset (same as the indicator)
    python backtest/backtest.py data.csv --tf 3 --session ny     # resample 1m data to 3m, trade New York only
    python backtest/backtest.py data.csv --preset dow --grid     # search settings, train/test split

The CSV can be a TradingView "Export chart data" file: it needs time, open,
high, low, close columns (volume optional). Time may be unix seconds or a date string.
Results are in R (1R = the stop distance of the trade = the amount risked) after
costs, so they compare across markets and map directly to "% of account" via the
risk per trade.
"""
import argparse
import itertools

import numpy as np
import pandas as pd

DEFAULTS = dict(
    fast_len=9, slow_len=21, trend_len=50,
    use_htf=False, htf_minutes=5, htf_len=50,
    rsi_len=7, rsi_pull_low=40, rsi_pull_high=60, pullback_bars=3,
    use_vwap=True, atr_len=14, min_atr_ratio=0.7, cooldown=0,
    tp_mult=1.5, sl_mult=1.0, max_bars=20,
    session="all", cost=0.0,
    # strategy: "pullback" (EMA trend pullback) or "orb" (session opening-range breakout)
    strategy="pullback", orb_minutes=30, orb_sl="range", orb_tp_r=2.0, orb_trend=False,
    # Daily money management, in R. 0 = off.
    daily_target_r=0.0, daily_loss_r=0.0, max_trades_day=0,
)

# Must match the session inputs of the Pine indicator.
SESSIONS = {
    "all": None,
    "asia": ("Asia/Tokyo", 9 * 60, 15 * 60),
    "london": ("Europe/London", 8 * 60, 12 * 60),
    "ny": ("America/New_York", 8 * 60 + 30, 12 * 60),
    "ny_cash": ("America/New_York", 9 * 60 + 30, 16 * 60),
}

# Market presets: chart timeframe, session, settings and an assumed round-trip
# cost (spread + commission + slippage) in price units. Mirrors the "Preset"
# input of the Pine indicator.
PRESETS = {
    "gold":   dict(tf=3, cost=0.25, session="all", strategy="pullback", htf_minutes=15,
                   tp_mult=1.5, sl_mult=1.5, pullback_bars=5, min_atr_ratio=0.7, use_htf=False),
    "gold_1m":  dict(tf=1, cost=0.25, session="asia", strategy="pullback", htf_minutes=5,
                     tp_mult=2.0, sl_mult=2.0, pullback_bars=3, min_atr_ratio=0.0, use_htf=True),
    "gold_5m":  dict(tf=5, cost=0.25, session="london", strategy="orb", orb_minutes=30, orb_sl="mid",
                     orb_tp_r=2.0, orb_trend=False, max_bars=0, max_trades_day=1),
    "gold_15m": dict(tf=15, cost=0.25, session="london", strategy="orb", orb_minutes=15, orb_sl="range",
                     orb_tp_r=1.5, orb_trend=True, max_bars=0, max_trades_day=1),
    "nasdaq": dict(tf=5, cost=0.75, session="all", strategy="pullback", htf_minutes=15,
                   tp_mult=1.5, sl_mult=1.5, pullback_bars=3, min_atr_ratio=0.7, use_htf=True),
    "dow":    dict(tf=5, cost=2.0, session="ny", strategy="orb", orb_minutes=30, orb_sl="range",
                   orb_tp_r=3.0, orb_trend=True, max_bars=0, max_trades_day=1),
    "silver": dict(tf=5, cost=0.012, session="london", strategy="orb", orb_minutes=30, orb_sl="mid",
                   orb_tp_r=1.5, orb_trend=False, max_bars=0, max_trades_day=1),
    "btc":    dict(tf=15, cost=15.0, session="all", strategy="pullback", htf_minutes=60,
                   tp_mult=3.0, sl_mult=1.5, pullback_bars=5, min_atr_ratio=0.0, use_htf=False),
}


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


def resample(df, minutes):
    if minutes <= 1:
        return df
    agg = dict(open="first", high="max", low="min", close="last", volume="sum")
    out = df.set_index("time").resample(f"{minutes}min", label="left", closed="left").agg(agg)
    return out.dropna(subset=["open"]).reset_index()


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


def session_info(times, name):
    """(in_session, day_key) arrays. day_key groups bars into trading days for the daily limits."""
    spec = SESSIONS[name]
    if spec is None:
        return np.ones(len(times), bool), times.dt.date.to_numpy()
    tz, start, end = spec
    local = times.dt.tz_convert(tz)
    mins = (local.dt.hour * 60 + local.dt.minute).to_numpy()
    return (mins >= start) & (mins < end), local.dt.date.to_numpy()


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
    atr = d.atr.to_numpy(float)
    return (long_.fillna(False).to_numpy(), short.fillna(False).to_numpy(),
            atr * p["sl_mult"], atr * p["tp_mult"], atr * p["sl_mult"], atr * p["tp_mult"])


def orb_signals(d, p):
    """Opening-range breakout: the range is the first orb_minutes of the session; the first
    close outside it is the entry. Stop at the other side (or the middle) of the range."""
    tz, start, _ = SESSIONS[p["session"]]
    local = d["time"].dt.tz_convert(tz)
    mins = (local.dt.hour * 60 + local.dt.minute).to_numpy()
    day = local.dt.date
    in_range = (mins >= start) & (mins < start + p["orb_minutes"])
    hi = d.high.where(in_range).groupby(day).transform("max").to_numpy()
    lo = d.low.where(in_range).groupby(day).transform("min").to_numpy()
    after = mins >= start + p["orb_minutes"]
    c = d.close.to_numpy(float)
    pc = np.roll(c, 1)
    long_ = after & (c > hi) & (pc <= hi)
    short = after & (c < lo) & (pc >= lo)
    if p["orb_trend"]:
        long_ &= (c > d.emaT.to_numpy(float))
        short &= (c < d.emaT.to_numpy(float))
    stop_l = lo if p["orb_sl"] == "range" else (hi + lo) / 2
    stop_s = hi if p["orb_sl"] == "range" else (hi + lo) / 2
    risk_l, risk_s = c - stop_l, stop_s - c
    long_ &= risk_l > 0
    short &= risk_s > 0
    return (np.nan_to_num(long_).astype(bool), np.nan_to_num(short).astype(bool),
            risk_l, risk_l * p["orb_tp_r"], risk_s, risk_s * p["orb_tp_r"])


def simulate(d, p):
    long_, short, risk_l, tp_l, risk_s, tp_s = (orb_signals if p["strategy"] == "orb" else signals)(d, p)
    h, l, c = (d[k].to_numpy(float) for k in ("high", "low", "close"))
    in_sess, day_key = session_info(d["time"], p["session"])
    trades = []
    pos, last_exit = 0, -10**9
    cur_day, day_r, day_n, day_done = None, 0.0, 0, False
    for i in range(len(d)):
        if day_key[i] != cur_day:
            cur_day, day_r, day_n, day_done = day_key[i], 0.0, 0, False
        if pos != 0 and i > ebar:
            hit_sl = l[i] <= sl if pos == 1 else h[i] >= sl
            hit_tp = h[i] >= tp if pos == 1 else l[i] <= tp
            timed = p["max_bars"] > 0 and i - ebar >= p["max_bars"]
            # Close at the end of the session so every trade stays inside it
            sess_end = not in_sess[i] or i + 1 == len(d) or not in_sess[i + 1]
            if hit_sl or hit_tp or timed or sess_end:
                exit_px = sl if hit_sl else tp if hit_tp else c[i]
                r = ((exit_px - entry) * pos - p["cost"]) / risk
                trades.append((d.time.iloc[ebar], tday, pos, entry, exit_px, r))
                pos, last_exit = 0, i
                if tday == cur_day:
                    day_r += r
                    if (p["daily_target_r"] > 0 and day_r >= p["daily_target_r"]) or \
                       (p["daily_loss_r"] > 0 and day_r <= -p["daily_loss_r"]) or \
                       (p["max_trades_day"] > 0 and day_n >= p["max_trades_day"]):
                        day_done = True
        if pos == 0 and not day_done and in_sess[i] and i - last_exit > p["cooldown"] and (long_[i] or short[i]):
            if i + 1 < len(d) and not in_sess[i + 1]:
                continue  # no entries on the last bar of the session
            pos = 1 if long_[i] else -1
            entry, ebar, tday = c[i], i, cur_day
            risk = risk_l[i] if pos == 1 else risk_s[i]
            tp = entry + pos * (tp_l[i] if pos == 1 else tp_s[i])
            sl = entry - pos * risk
            day_n += 1
    return pd.DataFrame(trades, columns=["time", "day", "dir", "entry", "exit", "r"])


def summary(t, days):
    if t.empty:
        return dict(trades=0, per_day=0.0, win_rate=0.0, net_r=0.0, avg_r=0.0, pf=0.0, max_dd_r=0.0, green_days=0.0)
    gross_win = t.r[t.r > 0].sum()
    gross_loss = -t.r[t.r < 0].sum()
    eq = t.r.cumsum()
    daily = t.groupby("day").r.sum()
    return dict(
        trades=len(t), per_day=round(len(t) / max(days, 1), 1),
        win_rate=round(float((t.r > 0).mean()) * 100, 1),
        net_r=round(float(t.r.sum()), 1), avg_r=round(float(t.r.mean()), 3),
        pf=round(float(gross_win / gross_loss), 2) if gross_loss > 0 else float("inf"),
        max_dd_r=round(float((eq.cummax() - eq).max()), 1),
        green_days=round(float((daily > 0).mean()) * 100, 0),
    )


def run(df, p):
    d = indicators(df, p)
    return summary(simulate(d, p), df.time.dt.date.nunique())


GRID = dict(
    session=["all", "asia", "london", "ny"],
    tp_mult=[1.0, 1.5, 2.0], sl_mult=[1.0, 1.5],
    pullback_bars=[3, 5, 8], min_atr_ratio=[0.0, 0.7],
    use_htf=[False, True],
)


ORB_GRID = dict(
    session=["london", "ny", "ny_cash"],
    orb_minutes=[15, 30, 60], orb_sl=["range", "mid"],
    orb_tp_r=[1.0, 1.5, 2.0, 3.0], orb_trend=[False, True],
)


def grid_search(df, base, grid=GRID, min_trades=20):
    cache, rows = {}, []
    for combo in itertools.product(*grid.values()):
        p = dict(base, **dict(zip(grid, combo)))
        key = p["use_htf"]  # indicators only depend on inputs that are not in the grid
        if key not in cache:
            cache[key] = indicators(df, p)
        t = simulate(cache[key], p)
        rows.append(dict(zip(grid, combo), **summary(t, df.time.dt.date.nunique())))
    res = pd.DataFrame(rows)
    return res[res.trades >= min_trades]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--strategy", choices=["pullback", "orb"])
    ap.add_argument("--tf", type=int, help="resample to this many minutes")
    ap.add_argument("--session", choices=sorted(SESSIONS))
    ap.add_argument("--cost", type=float, help="round-trip cost in price units")
    ap.add_argument("--target-r", type=float, help="daily target in R (stop trading after it)")
    ap.add_argument("--loss-r", type=float, help="daily max loss in R (stop trading after it)")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--train", type=float, default=0.6, help="train share of the data for --grid")
    args = ap.parse_args()

    base = dict(DEFAULTS)
    tf = 1
    if args.preset:
        preset = dict(PRESETS[args.preset])
        tf = preset.pop("tf")
        base.update(preset)
    tf = args.tf or tf
    for k, v in (("strategy", args.strategy), ("session", args.session), ("cost", args.cost),
                 ("daily_target_r", args.target_r), ("daily_loss_r", args.loss_r)):
        if v is not None:
            base[k] = v
    if base["strategy"] == "orb" and base["session"] == "all":
        base["session"] = "ny"
    grid = ORB_GRID if base["strategy"] == "orb" else GRID

    df = resample(load(args.csv), tf)
    days = df.time.dt.date.nunique()
    print(f"{len(df)} bars of {tf}m, {days} days, {df.time.iloc[0]} -> {df.time.iloc[-1]}")
    print("Settings:", {k: base[k] for k in ("strategy", "cost", *grid)})
    print("Result:", run(df, base))
    if not args.grid:
        return

    cut = df.time.iloc[int(len(df) * args.train)]
    train, test = df[df.time < cut].reset_index(drop=True), df[df.time >= cut].reset_index(drop=True)
    res = grid_search(train, base, grid, min_trades=10)
    pd.set_option("display.width", 220)
    best = res[res.pf > 1].sort_values("net_r", ascending=False).head(10)
    print(f"\nTop 10 on train (before {cut:%Y-%m-%d}) by net R:")
    print(best.to_string(index=False))
    print("\nSame settings on the unseen test period:")
    out = []
    for _, row in best.iterrows():
        p = dict(base, **{k: row[k] for k in grid})
        out.append(dict({k: row[k] for k in grid}, **run(test, p)))
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()
