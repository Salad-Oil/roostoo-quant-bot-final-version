# Roostoo Quant Trading Strategy

## 1. How we developed the strategy

### From mean reversion to momentum

We started with a mean-reversion idea: buy when a coin falls far below its recent average, and short when it rises far above it. We expected prices to move back toward the average.

Our early backtests kept losing money. We found that a large price move could keep going instead of reversing soon enough. Trading against that move also meant paying fees while waiting for a recovery.

We then tested the opposite direction: go long where the mean-reversion idea would short, and go short where it would buy. This led to our current **momentum continuation strategy**. We buy an upward move only when it is still getting stronger, and short a downward move only when it is still getting weaker.

The reported two-year test supports this change. With the template settings, the out-of-sample return improved from −19.25% for mean reversion to −2.51% for momentum. This was an improvement, but it did not yet show a profitable out-of-sample strategy.

### Balancing risk, costs, and participation

The competition score is:

```text
Score = 0.40 × Sortino + 0.30 × Sharpe + 0.30 × Calmar
```

These measures reward returns relative to risk, including downside risk and drawdown. We therefore focused on controlled exposure and selective entries, rather than taking large positions or trading as often as possible.

Fees also matter. A market order costs 0.10% per side, so entry and exit together cost 0.20% before slippage. With our backtest assumption of 0.05% slippage per side, the estimated round-trip cost is about 0.30%. Small, frequent trades can lose much of their return to these costs. We therefore require a meaningful price move and use several filters before entering.

However, the competition also requires at least eight active trading days. Being too selective could leave us inactive for too long. We made two changes to increase opportunities:

- **Secondary regime:** after 24 hours without a new entry signal, lower the z-score entry threshold from 2.0 to 1.8. Keep the other filters in place.
- **Wider universe:** expand the candidate pool from 12 to 16 coins in the team's later deployment, while keeping the same signal filters.

The goal is to balance trade quality with participation. These changes increase the chance of finding a trade; they do not force trades or guarantee enough active days.

We also changed the exits to reduce profit giveback. The strategy now exits when momentum weakens, before waiting for price to cross fully through its average. A trailing stop provides another exit for long positions after a pullback from their peak.

## 2. Main trading rules

### Coin selection and entry filters

We rank tradable coins by their 24-hour turnover and reject spreads above **0.1%**. The later deployment uses a candidate cap of **16 coins**. This is the pool we search for signals, not the number of positions we must hold.

Signals use closed **30-minute candles**. We compare the closing price with its average over **48 candles**, or 24 hours:

```text
Z = (Close − 48-bar average) / 48-bar standard deviation
ΔZ = current Z − previous Z
```

| Rule | Setting | Why we use it |
|---|---|---|
| Long entry | Previous Z ≥ +2.0 and ΔZ > +0.5 | Buy a strong upward move that is still growing |
| Short entry | Previous Z ≤ −2.0 and ΔZ < −0.5 | Short a strong downward move that is still growing |
| ADX filter | ADX(14) < 25 | Avoid the strongest established trends |
| Price-distance filter | Price is more than 0.6% from its 48-bar average | Avoid very small moves relative to trading costs |
| Relative-volume filter | Between 1.0 and 3.0 | Require activity within the chosen range |
| Secondary regime | Use ±1.8 instead of ±2.0 after 24 hours without an entry signal | Reduce long periods without opportunities |

The secondary-regime timer follows **generated entry signals**, not completed trades. A signal may still be rejected by the portfolio risk checks.

### Exits and risk control

| Rule | Setting | Why we use it |
|---|---|---|
| Long signal exit | Z ≤ +0.75 | Leave when upward momentum weakens |
| Short signal exit | Z ≥ −0.75 | Leave when downward momentum weakens |
| Initial stop | 2.5 × ATR(14) from entry | Set the stop using recent volatility |
| Long trailing stop | Exit after a 3% fall from the tracked peak | Reduce giveback after a favorable move |
| Time limit | 49 bars, about 24.5 hours | Limit how long capital stays in one trade |
| Risk per trade | Size against a 0.5% NAV loss budget at the stop | Keep planned trade risk small |
| Position limits | Up to 4 positions, each capped at 15% NAV; gross exposure capped at 60% | Limit concentration and total exposure |
| Daily loss limit | A 2% daily loss stops new entries for that risk day | Prevent further risk-taking after losses |
| Portfolio drawdown limit | At 20% drawdown, halt and work to close positions | Provide an emergency portfolio limit |
| Cooldown | Wait two bars after an exit | Avoid immediate re-entry |

The earlier code-default Z exits were −0.25 for longs and +0.25 for shorts. Moving them to +0.75 and −0.75 allows an earlier exit as momentum fades. The 3% trailing stop applies only to longs in the current code. These exits aim to protect gains, but cannot guarantee a profitable trade.

Position size also depends on the stop distance. The bot can take less than the position cap, and fees or price gaps can make the actual loss larger than the planned loss budget.

**Configuration note:** the position limits above are verified in the committed code and template. The committed universe cap is still 12; the 16-coin setting is the team's later reported deployment change. A server-only change to eight positions at 10% each is not present in the reviewed repository.
