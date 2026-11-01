# khaled

## Gann Cycle Levels (Price & Time) — TradingView indicator

The file `gann_cycle_levels.pine` (Pine Script v6) draws price levels by degree (0°…360°…) and time-cycle lines.

### Installation
1. In TradingView, open **Pine Editor**.
2. Paste the contents of `gann_cycle_levels.pine`, then click **Add to chart**.

### Settings
- **Anchor mode**:
  - `Auto`: uses the highest high and lowest low within the chosen number of bars. Whichever came first is 0° and the other is 360°.
  - `Manual`: you enter the price and time of the starting point (0°) and of the cycle end (360°).
- **Price method**:
  - `Range`: splits the distance between the two points into 360°, using the square root of price. Defaults 0° = 4696.83 and 360° = 3869.93 reproduce the screenshot levels exactly (252° = 4109.6, 288° = 4028.91, 324° = 3949.02).
  - `Square of 9`: the classic Gann method starting from the 0° point, where every 180° = one unit of the square root of price.
- **Time cycle**: vertical lines for the expected dates, labeled with the date and time.
- **Alerts**: create an alert on the indicator with "Any alert() function call" to be notified when price crosses any level.

> For education only, not investment advice.
