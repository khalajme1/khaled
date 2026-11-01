# khaled

## Gann Cycle Levels (Price & Time) — TradingView indicator

The file `gann_cycle_levels.pine` (Pine Script v6) draws price levels by degree (0°…360°…) and time-cycle lines.

### Installation
1. In TradingView, open **Pine Editor**.
2. Paste the contents of `gann_cycle_levels.pine`, then click **Add to chart**.

### How it works
Put the indicator on any chart (gold, indices, stocks…) and it works automatically, with no need to enter numbers:
- It finds the most recent cycle by itself: the highest high and lowest low within the chosen number of bars (the older one = 0°, the newer = 360°).
- It draws the price levels by degree, and vertical time-cycle lines labeled with the date.
- **Scenario panel** at the top of the chart: cycle direction, the current price's degree within the cycle, nearest support and resistance, momentum (EMA + RSI), the expected scenario, first and second targets, the invalidation condition, and the next time date.
- **Yellow arrow** for the expected path from the current price to the first target, ending at the next time date.

### Settings
- Anchor mode: `Auto` (default) or `Manual` to enter the 0° and 360° points yourself.
- Price method: `Range` (splits the swing into 360° by the square root of price) or `Square of 9`.
- Degree step (default 36°), timezone (default Riyadh), and position of the scenario panel.
- Alerts: create an alert with "Any alert() function call" to be notified when price crosses any level.

> The scenario is generated from simple rules (degree levels + momentum). For education only, not investment advice.
