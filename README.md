# Roostoo Momentum Trading Bot

A systematic cryptocurrency trading bot built for the Roostoo Quant Trading Hackathon. The strategy targets **short-term momentum continuation** on 30-minute candles, combining directional signals with liquidity filters, volatility-based position sizing, and portfolio risk limits.

## 1. Strategy design

### Capturing momentum continuation

Our strategy is built around a simple hypothesis: a strong price move can continue when directional pressure remains active. We look for upward moves that are still strengthening and downward moves that are still extending.

To measure that pressure, we express price relative to its rolling 24-hour average using a z-score. A large positive z-score identifies an upward price extension; a large negative z-score identifies a downward extension. We then require the z-score to keep moving in the same direction before entering.

The strategy combines three elements:

- **Directional strength:** the previous candle's z-score must exceed the entry threshold in the intended direction.
- **Continuation confirmation:** the current z-score must extend that move by more than the required increment.
- **Selective participation:** liquidity, ADX, price-distance, and relative-volume filters must pass before a signal reaches the portfolio risk checks.

This is a selective momentum approach. The ADX ceiling restricts entries to moves outside the strongest established trend conditions, while the z-score increment confirms short-term directional continuation.

### Balancing returns, risk, and trading costs

The competition score combines three risk-adjusted performance measures:

```text
Score = 0.40 × Sortino + 0.30 × Sharpe + 0.30 × Calmar
```

Our design therefore emphasizes controlled exposure, limited drawdowns, and selective entries. Position sizing uses a loss budget at the initial stop, and portfolio limits constrain concentration and total exposure.

Trading costs also shape the entry rules. The configured taker fee is 0.10% per side. Adding assumed slippage of 0.05% per side gives approximately 0.30% for a market-order round trip before any additional spread effects. The price-distance filter excludes small price extensions, although passing it does not guarantee that a trade will cover its costs.

### Maintaining participation

The competition requires at least eight active trading days. To reduce extended periods without opportunities, the strategy includes a secondary entry regime: after 24 hours without a generated entry signal, the z-score threshold falls from ±2.0 to ±1.8. Continuation confirmation and the remaining filters stay in place.

The timer tracks generated entry signals, not completed trades. Portfolio risk checks can still reject a signal, so this mechanism does not guarantee a minimum number of active days.

## 2. Trading rules

The settings below describe the committed `.env.example` configuration. Copying that template to `.env` is necessary to use these settings; internal code defaults differ for several parameters.

### Universe and signal calculation

Tradable pairs are ranked by 24-hour turnover. The configured candidate pool contains up to **12 pairs**, with quoted spreads no wider than **0.1%**. The pool is searched for opportunities; it is not a target number of open positions.

Signals use closed **30-minute candles** and a **48-candle** rolling window, equivalent to 24 hours:

```text
SMA48 = average of the last 48 closing prices
Std48 = standard deviation of those closing prices
Z[t]  = (Close[t] − SMA48[t]) / Std48[t]
ΔZ[t] = Z[t] − Z[t−1]
```

### Entry conditions

| Rule | Setting | Purpose |
|---|---|---|
| Long entry | Z[t−1] ≥ +2.0 and ΔZ[t] > +0.5 | Enter an upward extension with continued directional strength |
| Short entry | Z[t−1] ≤ −2.0 and ΔZ[t] < −0.5 | Enter a downward extension with continued directional strength |
| ADX filter | ADX(14) < 25 | Restrict entries outside the strongest established trend conditions |
| Price-distance filter | Absolute distance from SMA48, divided by the closing price, > 0.6% | Exclude small price extensions |
| Relative-volume filter | Between 1.0 and 3.0, inclusive | Require volume within the selected activity range |
| Secondary regime | Entry threshold becomes ±1.8 after 24 hours without an entry signal | Allow more opportunities during prolonged inactivity |

All enabled filters must pass. Short entries are enabled in the template, and every entry remains subject to position sizing and portfolio risk checks.

### Exits

| Rule | Setting | Purpose |
|---|---|---|
| Long signal exit | Z ≤ +0.75 | Exit as upward momentum fades |
| Short signal exit | Z ≥ −0.75 | Exit as downward momentum fades |
| Initial stop | 2.5 × ATR(14) from entry | Adapt the initial stop distance to recent volatility |
| Long trailing stop | 3% decline from the tracked peak | Limit giveback after a favorable move |
| Maximum holding period | 49 bars, approximately 24.5 hours | Bound the time allocated to a position |
| Re-entry cooldown | Two bars after an exit | Avoid immediate re-entry in the same pair |

The trailing stop applies to long positions only. Signal exits, stops, and holding limits work together; none guarantees a profitable exit or a fill at the intended price.

### Position sizing and portfolio limits

| Control | Setting |
|---|---|
| Planned risk per trade | 0.5% of portfolio net asset value (NAV), sized using the initial stop distance |
| Maximum position weight | 15% of NAV per pair |
| Maximum open positions | 4 |
| Maximum gross exposure | 60% of NAV |
| Daily loss limit | 2%; halt new entries for the risk day |
| Risk-day boundary | Midnight UTC+8 |
| Portfolio drawdown limit | 20%; halt trading and attempt to close positions |
| Missing stop information | Refuse entry when a configured stop distance cannot be computed |

Position size is constrained by both the stop-based risk budget and portfolio caps. Fees, gaps, and execution slippage can make realized losses larger than the planned loss budget.

## 3. Running the bot

### Set up

```bash
git clone https://github.com/Salad-Oil/roostoo-quant-bot-final-version.git
cd roostoo-quant-bot-final-version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

The bot core uses the Python standard library. Edit `.env` to configure credentials, pairs, strategy parameters, and risk limits. Keep API credentials out of version control.

### Run the built-in simulator

```bash
python run_live.py --mock --cycles 20
```

### Backtest historical candles

```bash
python run_backtest.py --data-dir data --oos-frac 0.25
```

The backtester holds out the final 25% of the timeline for out-of-sample evaluation and writes results to `reports/`. Use historical data with aligned coverage across pairs when comparing configurations. The small sample files in `data/` are suitable for checking the workflow, not establishing strategy performance.

### Check connectivity and start live execution

After entering the Roostoo credentials in `.env`, run the read-only connectivity check:

```bash
python run_live.py --check
```

Start the trading loop with:

```bash
python run_live.py
```

Live execution can place orders. Review the configured risk limits and connectivity results before starting it.

## 4. Evaluation approach

We evaluate the momentum strategy using return, drawdown, Sharpe, Sortino, Calmar, trading costs, and activity. Out-of-sample results are assessed separately from the data used for parameter selection.

The design hypothesis is not evidence of profitability. Evaluation must account for fees, spread, slippage, execution delay, and differences between simulated and live fills. Parameter settings should be judged by their out-of-sample behavior and risk profile.

## 5. Repository structure

| Path | Contents |
|---|---|
| `roostoo/` | Strategy signals, trading engine, risk controls, exchange client, and backtesting components |
| `run_live.py` | Live trading loop, simulator mode, and connectivity checks |
| `run_backtest.py` | Historical backtesting and out-of-sample evaluation |
| `run_sweep.py` | Parameter sweep runner |
| `scripts/` | Data collection and supporting utilities |
| `tests/` | Automated tests |
| `deploy/` | Deployment resources |
| `.env.example` | Configuration template |
| `reports/` | Committed research and backtest outputs |

## License

This project is licensed under the [MIT License](LICENSE).
