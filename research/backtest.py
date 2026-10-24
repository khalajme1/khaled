#!/usr/bin/env python3
"""
Timeframe study + backtester for GoldScalperPro (mirrors mql5/Experts/GoldScalperPro.mq5).

Input : M1 CSV exported from MT5 with mql5/Scripts/ExportM1Bars.mq5
        columns: time,open,high,low,close[,tick_volume,spread_points]   (bid prices)
Usage :
    python research/backtest.py data/XAUUSD_M1.csv --spread 0.26
    python research/backtest.py data/XAUUSD_M1.csv --spread 0.26 --optimize
    python research/backtest.py data/XAUUSD_M1.csv --spread 0.26 --tf 5 --risk 0.5

Fill model (conservative):
  * signal on bar close, entry at next bar open; buy fills at ask = bid + spread
  * buy exits on bid, sell exits on ask
  * if SL and TP are both inside one bar, the SL is assumed to be hit first
  * break-even / trailing are updated on bar close (EA does it per tick)
"""
import argparse
import itertools
import sys
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- data
def load_m1(path):
    # accepts ExportM1Bars.mq5 output (comma) or MT5 Symbols -> Bars -> Export (tab, <DATE> <TIME> ...)
    df = pd.read_csv(path, sep=None, engine="python", encoding_errors="ignore")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    if "date" in df.columns and "time" in df.columns:
        df["time"] = df["date"].astype(str) + " " + df["time"].astype(str)
    if "time" not in df.columns:
        raise SystemExit("CSV needs a 'time' column")
    df["time"] = pd.to_datetime(df["time"].astype(str).str.replace(".", "-", regex=False))
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated()]
    return df[["open", "high", "low", "close"]].astype(float)


def resample(m1, minutes):
    if minutes == 1:
        return m1.copy()
    rule = f"{minutes}min"
    out = m1.resample(rule, label="left", closed="left", origin="start_day").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    return out.dropna()


# --------------------------------------------------------------------- indicators
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def true_range(df):
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df, n):
    # MT5 iATR = simple average of true range
    return true_range(df).rolling(n).mean()


def adx(df, n):
    # MT5 iADX smooths +DM/-DM/TR with an EMA of the same period
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = ema(true_range(df), n)
    pdi = 100 * ema(pd.Series(pdm, index=df.index), n) / tr
    mdi = 100 * ema(pd.Series(mdm, index=df.index), n) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return ema(dx.fillna(0), n)


# ------------------------------------------------------------------------ params
@dataclass(frozen=True)
class Params:
    tf: int = 5
    htf: int = 15
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    htf_ema: int = 50
    rsi_period: int = 7
    rsi_buy: float = 45.0
    rsi_sell: float = 55.0
    adx_period: int = 14
    adx_min: float = 20.0
    atr_period: int = 14
    pullback_atr: float = 0.30
    sl_atr: float = 1.5
    tp_r: float = 1.5
    be_r: float = 0.8
    trail_start_r: float = 1.0
    trail_atr: float = 1.0
    max_spread: float = 0.35
    min_atr_spread: float = 4.0
    risk_pct: float = 0.50
    daily_target: float = 3.0
    daily_loss: float = 3.0
    max_dd: float = 9.0
    max_trades: int = 12
    max_consec_losses: int = 4
    cooldown_bars: int = 3
    start_hour: int = 9
    end_hour: int = 20
    friday_close_hour: int = 20


def build_features(m1, p):
    df = resample(m1, p.tf)
    c = df["close"]
    df["ema_f"] = ema(c, p.ema_fast)
    df["ema_s"] = ema(c, p.ema_slow)
    df["ema_t"] = ema(c, p.ema_trend)
    df["rsi"] = rsi(c, p.rsi_period)
    df["atr"] = atr(df, p.atr_period)
    df["adx"] = adx(df, p.adx_period)

    # HTF: value of the last *closed* HTF bar at the moment the working bar closes
    h = resample(m1, p.htf)
    h_avail = pd.DataFrame({"htf_close": h["close"], "htf_ema": ema(h["close"], p.htf_ema)})
    h_avail.index = h_avail.index + pd.Timedelta(minutes=p.htf)
    bar_close_time = df.index + pd.Timedelta(minutes=p.tf)
    hv = h_avail.reindex(h_avail.index.union(bar_close_time)).ffill().reindex(bar_close_time)
    df["htf_close"] = hv["htf_close"].values
    df["htf_ema"] = hv["htf_ema"].values
    return df.iloc[max(p.ema_trend, 50):]


def signals(df, p, spread):
    c, o, h, l = df["close"], df["open"], df["high"], df["low"]
    f, s, t, a = df["ema_f"], df["ema_s"], df["ema_t"], df["atr"]
    up = (f > s) & (s > t) & (c > t) & (df["htf_close"] > df["htf_ema"])
    dn = (f < s) & (s < t) & (c < t) & (df["htf_close"] < df["htf_ema"])
    r, r_prev = df["rsi"], df["rsi"].shift()
    base = (df["adx"] >= p.adx_min) & (a >= spread * p.min_atr_spread) & (spread <= p.max_spread)
    buy = base & up & (l <= f + a * p.pullback_atr) & (c > o) & (c > f) & (r_prev < p.rsi_buy) & (r >= p.rsi_buy)
    sell = base & dn & (h >= f - a * p.pullback_atr) & (c < o) & (c < f) & (r_prev > p.rsi_sell) & (r <= p.rsi_sell)
    return buy.fillna(False).values, sell.fillna(False).values


# ---------------------------------------------------------------------- simulator
def simulate(df, p, spread):
    buy, sell = signals(df, p, spread)
    O, H, L, C, A = (df[k].values for k in ("open", "high", "low", "close", "atr"))
    idx = df.index
    days = idx.normalize().values
    hours = idx.hour.values
    dows = idx.dayofweek.values  # Mon=0 .. Fri=4
    n = len(df)

    sig_idx = np.flatnonzero(buy | sell)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    halted = False
    trades = []
    day_eq = {}  # day -> equity at end of day

    cur_day = None
    day_start = equity
    day_locked = False
    trades_today = 0
    consec = 0
    cooldown_until = -1  # bar index from which entries are allowed again
    i_free = 0           # first bar index at which we are flat

    def roll_day(d):
        nonlocal cur_day, day_start, day_locked, trades_today, consec
        if cur_day is not None:
            day_eq[cur_day] = equity
        cur_day, day_start, day_locked, trades_today, consec = d, equity, False, 0, 0

    for si in sig_idx:
        e = si + 1  # entry bar
        if halted:
            break
        if e >= n or e < i_free:
            continue
        if days[e] != cur_day:
            roll_day(days[e])
        if day_locked or trades_today >= p.max_trades or consec >= p.max_consec_losses:
            continue
        if e < cooldown_until:
            continue
        hr = hours[e]
        if hr < p.start_hour or hr >= p.end_hour:
            continue
        if dows[e] == 4 and hr >= p.friday_close_hour - 1:
            continue

        is_buy = bool(buy[si])
        sl_dist = A[si] * p.sl_atr
        risk_dist = sl_dist + spread
        risk_frac = p.risk_pct / 100.0
        if is_buy:
            entry = O[e] + spread
            sl, tp = entry - sl_dist, entry + sl_dist * p.tp_r
        else:
            entry = O[e]
            sl, tp = entry + sl_dist, entry - sl_dist * p.tp_r
        eq_entry = equity
        trades_today += 1

        exit_px, exit_i, reason = None, None, None
        j = e
        while j < n:
            if days[j] != cur_day:  # held over midnight: close at previous close
                exit_px, exit_i, reason = (C[j - 1] if is_buy else C[j - 1] + spread), j - 1, "eod"
                break
            if is_buy:
                lo, hi, cl = L[j], H[j], C[j]
                if lo <= sl:
                    exit_px, reason = min(sl, O[j]) if j > e else sl, "sl"
                elif hi >= tp:
                    exit_px, reason = tp, "tp"
            else:
                lo, hi, cl = L[j] + spread, H[j] + spread, C[j] + spread
                if hi >= sl:
                    exit_px, reason = max(sl, O[j] + spread) if j > e else sl, "sl"
                elif lo <= tp:
                    exit_px, reason = tp, "tp"
            if exit_px is not None:
                exit_i = j
                break

            # bar-close equity, risk guards
            pnl_px = (cl - entry) if is_buy else (entry - cl)
            eq_now = eq_entry * (1 + risk_frac * pnl_px / risk_dist)
            peak = max(peak, eq_now)
            dd = (peak - eq_now) / peak * 100
            max_dd = max(max_dd, dd)
            day_pct = (eq_now - day_start) / day_start * 100
            if dd >= p.max_dd:
                exit_px, exit_i, reason, halted = cl, j, "maxdd", True
                break
            if day_pct >= p.daily_target or day_pct <= -p.daily_loss:
                exit_px, exit_i, reason, day_locked = cl, j, "daylock", True
                break
            if dows[j] == 4 and hours[j] >= p.friday_close_hour:
                exit_px, exit_i, reason = cl, j, "friday"
                break

            # break-even / trailing (applies from next bar)
            profit_r = pnl_px / sl_dist
            if is_buy:
                if profit_r >= p.be_r:
                    sl = max(sl, entry)
                if profit_r >= p.trail_start_r:
                    sl = max(sl, cl - A[j] * p.trail_atr)
            else:
                if profit_r >= p.be_r:
                    sl = min(sl, entry)
                if profit_r >= p.trail_start_r:
                    sl = min(sl, cl + A[j] * p.trail_atr)
            j += 1
        if exit_px is None:
            exit_px, exit_i, reason = (C[-1] if is_buy else C[-1] + spread), n - 1, "end"

        pnl_px = (exit_px - entry) if is_buy else (entry - exit_px)
        r_mult = pnl_px / risk_dist
        equity = eq_entry * (1 + risk_frac * r_mult)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
        if dd >= p.max_dd:
            halted = True
        day_pct = (equity - day_start) / day_start * 100
        if day_pct >= p.daily_target or day_pct <= -p.daily_loss:
            day_locked = True
        if r_mult < 0:
            consec += 1
            cooldown_until = exit_i + p.cooldown_bars
        else:
            consec = 0
        i_free = exit_i + 1
        trades.append((idx[e], "buy" if is_buy else "sell", entry, exit_px, r_mult, reason, idx[exit_i]))

    if cur_day is not None:
        day_eq[cur_day] = equity
    return metrics(trades, day_eq, df, equity, max_dd, halted)


def metrics(trades, day_eq, df, equity, max_dd, halted):
    # daily returns over every trading day in the data (flat days count as 0%)
    all_days = pd.DatetimeIndex(pd.unique(df.index.normalize()))
    eq = pd.Series(day_eq).reindex(all_days).ffill().fillna(1.0)
    daily = eq.pct_change().fillna(eq.iloc[0] - 1.0) * 100
    t = pd.DataFrame(trades, columns=["entry_time", "side", "entry", "exit", "r", "reason", "exit_time"])
    wins = t[t.r > 0].r.sum() if len(t) else 0.0
    losses = -t[t.r < 0].r.sum() if len(t) else 0.0
    n_days = max(len(all_days), 1)
    return {
        "trades": len(t),
        "trades_per_day": len(t) / n_days,
        "win_rate": float((t.r > 0).mean() * 100) if len(t) else 0.0,
        "avg_r": float(t.r.mean()) if len(t) else 0.0,
        "profit_factor": float(wins / losses) if losses > 0 else float("inf") if wins > 0 else 0.0,
        "total_return_pct": (equity - 1) * 100,
        "avg_daily_pct": float(daily.mean()),
        "median_daily_pct": float(daily.median()),
        "days_ge_2_5_pct": float((daily >= 2.5).mean() * 100),
        "losing_days_pct": float((daily < 0).mean() * 100),
        "worst_day_pct": float(daily.min()),
        "max_dd_pct": max_dd,
        "halted_by_dd": halted,
        "days": n_days,
        "_trades": t,
        "_daily": daily,
    }


# -------------------------------------------------------------- timeframe study
def timeframe_study(m1, spread):
    rows = []
    for tf in (1, 3, 5):
        df = resample(m1, tf)
        a = atr(df, 14)
        rng = df["high"] - df["low"]
        ret = np.log(df["close"]).diff().dropna()
        ac1 = ret.autocorr(1)
        # variance ratio over 10 bars: >1 trending, <1 mean-reverting
        r10 = np.log(df["close"]).diff(10).dropna()
        vr = r10.var() / (10 * ret.var())
        rows.append({
            "TF": f"M{tf}",
            "median_ATR14": a.median(),
            "spread_%_of_ATR": spread / a.median() * 100,
            "bars_range>=4x_spread_%": (rng >= 4 * spread).mean() * 100,
            "autocorr_lag1": ac1,
            "variance_ratio_10": vr,
        })
    study = pd.DataFrame(rows).set_index("TF")

    m5 = resample(m1, 5)
    by_hour = (m5["high"] - m5["low"]).groupby(m5.index.hour).median().rename("median_M5_range")
    return study, by_hour


# ------------------------------------------------------------------ optimization
GRID = {
    "sl_atr": [1.0, 1.5, 2.0],
    "tp_r": [1.0, 1.5, 2.0],
    "adx_min": [15.0, 20.0, 25.0],
    "rsi_levels": [(40.0, 60.0), (45.0, 55.0), (50.0, 50.0)],
}


def optimize(m1, base, spread, split=0.7, dd_cap=8.0):
    cut = m1.index[int(len(m1) * split)].normalize()
    m1_is, m1_oos = m1[m1.index < cut], m1[m1.index >= cut]
    results = []
    for tf in (1, 3, 5):
        p_tf = replace(base, tf=tf)
        df_is = build_features(m1_is, p_tf)
        for sl, tp, ax, (rb, rs) in itertools.product(*GRID.values()):
            p = replace(p_tf, sl_atr=sl, tp_r=tp, adx_min=ax, rsi_buy=rb, rsi_sell=rs)
            r = simulate(df_is, p, spread)
            results.append((p, r))
            print(f"  IS  M{tf} sl={sl} tp={tp} adx={ax} rsi={rb}/{rs} -> "
                  f"avg/day {r['avg_daily_pct']:+.3f}%  maxDD {r['max_dd_pct']:.2f}%  trades {r['trades']}",
                  file=sys.stderr)

    ok = [(p, r) for p, r in results if r["max_dd_pct"] < dd_cap and r["trades"] >= 30]
    if not ok:
        print("\nNo in-sample parameter set met the drawdown cap with >= 30 trades.")
        return None
    best_per_tf = {}
    for p, r in ok:
        score = r["avg_daily_pct"] / max(r["max_dd_pct"], 1.0)
        if p.tf not in best_per_tf or score > best_per_tf[p.tf][2]:
            best_per_tf[p.tf] = (p, r, score)

    print(f"\nIn-sample: {m1_is.index[0].date()} .. {m1_is.index[-1].date()}   "
          f"Out-of-sample: {m1_oos.index[0].date()} .. {m1_oos.index[-1].date()}")
    for tf, (p, r_is, _) in sorted(best_per_tf.items()):
        r_oos = simulate(build_features(m1_oos, p), p, spread)
        print(f"\nBest M{tf}: sl_atr={p.sl_atr} tp_r={p.tp_r} adx_min={p.adx_min} rsi={p.rsi_buy}/{p.rsi_sell}")
        print_report("in-sample", r_is)
        print_report("OUT-OF-SAMPLE", r_oos)
    return best_per_tf


# ------------------------------------------------------------------------ report
def print_report(label, r):
    print(f"  [{label}] trades {r['trades']} ({r['trades_per_day']:.1f}/day) | win {r['win_rate']:.1f}% | "
          f"avgR {r['avg_r']:+.3f} | PF {r['profit_factor']:.2f}")
    print(f"  [{label}] total {r['total_return_pct']:+.2f}% | avg/day {r['avg_daily_pct']:+.3f}% | "
          f"median/day {r['median_daily_pct']:+.3f}% | days>=2.5% {r['days_ge_2_5_pct']:.1f}% | "
          f"losing days {r['losing_days_pct']:.1f}% | worst day {r['worst_day_pct']:+.2f}% | "
          f"maxDD {r['max_dd_pct']:.2f}%{' (HALTED)' if r['halted_by_dd'] else ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="M1 CSV (bid) exported from MT5")
    ap.add_argument("--spread", type=float, default=0.26, help="spread in price units (default 0.26)")
    ap.add_argument("--tf", type=int, choices=(1, 3, 5), help="run one timeframe only")
    ap.add_argument("--risk", type=float, default=0.5, help="risk per trade %% (default 0.5)")
    ap.add_argument("--optimize", action="store_true", help="grid search in-sample, report out-of-sample")
    ap.add_argument("--trades-csv", help="write the trade list of the last run here")
    args = ap.parse_args()

    m1 = load_m1(args.csv)
    print(f"Loaded {len(m1):,} M1 bars  {m1.index[0]} .. {m1.index[-1]}   spread={args.spread}")

    study, by_hour = timeframe_study(m1, args.spread)
    pd.set_option("display.width", 160)
    print("\n=== Timeframe study (cost vs. movement) ===")
    print(study.round(3).to_string())
    print("\n=== Median M5 bar range by server hour ===")
    print(by_hour.round(2).to_string())

    base = Params(risk_pct=args.risk)
    if args.optimize:
        optimize(m1, base, args.spread)
        return

    tfs = [args.tf] if args.tf else [1, 3, 5]
    print("\n=== Backtest with default EA inputs ===")
    last = None
    for tf in tfs:
        p = replace(base, tf=tf)
        r = simulate(build_features(m1, p), p, args.spread)
        print(f"\nM{tf}")
        print_report("full", r)
        last = r
    if args.trades_csv and last is not None:
        last["_trades"].to_csv(args.trades_csv, index=False)
        print(f"\nTrades written to {args.trades_csv}")


if __name__ == "__main__":
    main()
