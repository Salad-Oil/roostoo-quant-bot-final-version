# roostoo-quant-bot

An autonomous trading bot for the HK/AU/IN Quant Trading Hackathon on
[Roostoo](https://luma.com/coghwiyt)'s mock crypto exchange, plus the backtester
and diagnostic scripts we used to build it.

Two things worth knowing before you read any further.

The competition scores a portfolio as `0.40 x Sortino + 0.30 x Sharpe + 0.30 x
Calmar`, so we optimised for downside rather than return. Position sizing, the
order the exits fire in, and the kill switch are all written to bound a loss
first. The entry signal was the last thing we worried about.

And the strategy loses money out of sample on every window we measured. We spent
most of the project working out why, and the answer is not a parameter value. The
measurements are in [Backtest results](#backtest-results); the full record,
including the ideas that failed, is in [`docs/FINDINGS.md`](docs/FINDINGS.md).

## Start here

Runtime is Python 3.9+ and the standard library. There is nothing to install:
`requirements.txt` exists only to document that, and `requirements-dev.txt` holds
the linting and CI extras.

```bash
git clone https://github.com/Salad-Oil/roostoo-quant-bot-final-version
cd roostoo-quant-bot-final-version

# whole chain against the offline simulator: no keys, no network
python run_live.py --mock --cycles 20

# real 30m candles from Binance (public endpoint, no key needed)
python scripts/fetch_history.py --days 365 --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,LINKUSDT,AVAXUSDT

# backtest with the last 25% held out
python run_backtest.py --data-dir data --oos-frac 0.25

# why did it lose? split P&L by exit reason
python scripts/analyze_backtest.py reports/trades_out-of-sample.csv

# the measurement that decided the whole design
python scripts/edge_analysis.py --data-dir data --folds 5
```

To run against the venue, copy `.env.example` to `.env` (`copy` on Windows, `cp`
elsewhere), fill in `ROOSTOO_API_KEY` and `ROOSTOO_SECRET_KEY`, then run
`python run_live.py --check`. That path is read-only: it verifies the signature,
the clock and the universe, and sends no orders.

One warning about `data/`. It holds two 1200-bar synthetic samples (seed 7, about
25 days) that exist so the simulator and the backtester work offline. It does not
hold the datasets the tables below were produced from; those are fetched, because
market data is git-ignored. See
[Reproducing the numbers](#reproducing-the-numbers).

## What it trades

Five decisions, in the order the engine makes them.

| # | Decision | Code |
|---|---|---|
| 1 | Which coins may we hold? Rank by 24h turnover, apply a spread ceiling and a depth screen | `roostoo/universe.py` |
| 2 | When do we buy? A z-score entry, confirmed by a turn in the z-score, by ADX, and by a deviation gate that has to clear costs | `roostoo/strategies/mean_reversion.py` |
| 3 | How much? A 0.5% NAV loss budget per trade, sized from the actual stop distance | `roostoo/risk.py` (`PositionSizer`) |
| 4 | When do we sell? The z-score target, an ATR stop, a time stop | `roostoo/risk.py` (`protective_exits`) |
| 5 | What does it cost? 0.1% taker per side plus slippage, priced into every fill and into the entry gate itself | `roostoo/backtest.py`, `roostoo/strategies/mean_reversion.py` |

The portfolio is concentrated but capped: at most 4 positions, at most 15% of NAV
in one coin, at most 60% of NAV gross. Since `0.15 x 4 == 0.60`, equal weight
across four slots satisfies Rules 8, 9 and 10 at the same moment. The remaining
40% stays in cash. That is a deliberate choice rather than idle capital: cash is
what keeps the drawdown term of the score small.

## Strategy

### The entry signal

```
SMA48 = mean of the last 48 closes        (48 x 30min = 24h)
Std48 = standard deviation of those closes
Z     = (Close - SMA48) / Std48
```

The entry rides the stretch rather than fading it:

```
LONG   Z[t-1] >= +X   and   Z[t] - Z[t-1] >  min_delta_z
SHORT  Z[t-1] <= -X   and   Z[t] - Z[t-1] < -min_delta_z
```

So a long is taken when the z-score was already `X` standard deviations *above*
the mean and is still moving up. `X` is `z_entry`, 2.8 in the code and 2.0 in the
shipped template. The confirmation is `require_continuation` (`|dZ| > min_delta_z`,
0.5): it asks for the move to still be going, not to turn. That setting used to be
called `require_turn`, which said the opposite of what it does; the old key is
still accepted if you have it in a `.env`, and the new one wins when both are set.

Two gates then apply. `ADX(14)` must be below `adx_max` (20 in the code, 25 in the
template, and 25 in the rulebook), so the bot stays out of the strongest trends.
And Rule 4's deviation gate requires `|Close - SMA48| / Close` above
`min_abs_deviation` (1.2% in the code, 0.6% in the template), so the move being bet
on is at least plausibly worth the cost of a round trip.

If `enable_secondary_regime` is on (off in the code, on in the template) and no
entry has fired for `secondary_after_hours`, the threshold relaxes to
`secondary_z_entry` (1.8) so the bot does not sit out a quiet stretch entirely.

### Which way round

Rule 2's clause reads *"Z[t-1] >= X and Delta Z < 0"*, which mixes a momentum level
with a reversion sign. A long entry conventionally wants price *below* the mean,
and `Z >= +2` is the opposite, so the sentence can be read two ways. This snapshot
takes the momentum reading and hardwires it: there is no `direction` switch, and
reversing the policy means editing the entry conditions.

The choice was measured rather than argued. Two years of 30m data, ten pairs, final
183 days held out:

| policy | in-sample | out-of-sample (183d) | in-sample drawdown | round trips (IS/OOS) |
|---|---|---|---|---|
| reversion, engine defaults | -19.65% | -13.72% | 19.85% | 315 / 498 |
| reversion + the shipped `.env` | -19.85% | -19.25% | 19.97% | 488 / 317 |
| **momentum + the shipped `.env`** (shipped) | -19.32% | **-2.51%** | 19.71% | 310 / 145 |
| momentum + stricter entry params | +2.65% | **-1.51%** | 3.05% | 57 / 31 |

Entering with the stretch beat fading it by 11 to 17 percentage points out of
sample. That is why the momentum reading is the one in the code. The reversion rows
come from a development branch that reverses the entry conditions; there is no
switch for them in this snapshot.

A few things that table does not say.

- Nothing here is profitable. The best out-of-sample cell is -1.51% over 183 days.
  Momentum turns a large loss into a small one; it does not produce a gain.
- The best cell trades too little. 31 round trips in 183 days is roughly 2 per
  14-day window, against a competition requirement of 8 active trading days. The
  configurations that trade enough lose more, so we ship the middle row on purpose
  rather than the row with the nicest number.
- Magnitudes do not transfer between datasets. The same comparison reads -0.55% vs
  -4.22% on the 120-day set and -2.51% vs -19.25% on two years. The ordering is the
  stable part, so we report both.
- The two-year dataset behind this table is not in the repository. Market data is
  git-ignored; `scripts/fetch_history.py --days 730` rebuilds an equivalent one.
- The drawdown column is in-sample, because that is what we tabulated. We are not
  claiming an out-of-sample drawdown improvement from this table.

**A stale description you may still find in older output.** The module docstring
and the `reason=` strings attached to the entry and exit signals were copied from
the *fade* version and described the opposite reading, so a journal line could
contradict the order it explained. Both are corrected here; the executable
conditions were always the momentum ones quoted above, so no result changes. Any
journal or report written before that fix still shows the old wording.

### Exits and sizing

A long is closed once the z-score falls back to `z_exit_long`, and a short once it
rises to `z_exit_short`. Because the entry rides the stretch, those levels decide
how far the position has to travel: with the code's `-0.25 / +0.25` a momentum long
entered at `+2.8` has to cross roughly three sigma, while the template's
`+0.75 / -0.75` closes it after about one and a quarter. Entry and exit have to be
chosen together; change one without the other and the z-exit either never fires or
fires immediately.

Protective exits run in a fixed order: kill switch, ATR stop, trailing stop, time
stop. All of them are evaluated before any new entry in the same cycle, so freeing
a slot always beats wanting one. The trailing stop is not in the rulebook and ships
off.

A position is sized so that the distance to its stop, times the quantity, equals
0.5% of NAV. The stop distance is an input to the size rather than a check applied
afterwards. When the risk budget binds before the portfolio caps do, the caps win
and the binding constraint is written to the journal.

We are not settled on the stop, and it is the least comfortable line in the config.
Splitting P&L by exit reason on the default run makes the point:

| exit | n | gross P&L | avg bars held | win rate |
|---|---|---|---|---|
| z-exit (the target) | 86 | +12,176 | 6.0 | 100% |
| time stop | 102 | +2,955 | 12.0 | 49% |
| ATR stop | 145 | **-19,460** | 4.2 | **0%** |

The stop fired after 4.2 bars on average and cost more than everything else earned
combined. That is what a stop sitting inside the noise looks like, and widening it
improves the score monotonically in the sweep. The template widens it to 2.5x ATR
and lengthens the time stop to 49 bars; the code keeps the rulebook's 1.5 and 12.
Either way it is a one-line change, and it is the first thing we would revisit.

### Which configuration is which

There are two configurations in this repository and they are not the same one.
`roostoo/config.py` and the strategy's `default_params()` are what you get from a
bare `python run_live.py`; `.env.example` is what you get after copying it to
`.env`, which is what our own runs did.

| setting | code default | shipped `.env.example` |
|---|---|---|
| `z_entry` | 2.8 | 2.0 |
| `adx_max` | 20.0 | 25.0 |
| `min_abs_deviation` (Rule 4) | 0.012 (1.2%), gate on | 0.006 (0.6%), gate on |
| `z_exit_long` / `z_exit_short` | -0.25 / +0.25 | +0.75 / -0.75 |
| `min_delta_z` | 0.5 | 0.5 |
| `STOP_ATR_MULT` | 1.5 | 2.5 |
| `MAX_HOLD_BARS` | 12 | 49 |
| `ROOSTOO_MAX_PAIRS` | 8 | 12 |
| supplementary filters and secondary regime | all off | relative-volume on, secondary regime on |

The measurements in this document were taken with the **looser entry settings**
(`z_entry` 2.0, `adx_max` 25, deviation gate at 0.6%), which is the template's
configuration. Treat them as numbers for the strategy family rather than for the
exact bot you get from a bare `run_live.py`, and re-run the backtest to get the
numbers for whichever configuration you intend to run.

### If you are picking this up

In rough order of what we think is worth the most: turn the short leg off
(`allow_short: false`, worth about 10 points in-sample, and note the organisers
confirmed shorts are permitted, so this is a performance question rather than a
compliance one), widen or replace the ATR stop, and keep the ADX and deviation
gates. [`docs/FINDINGS.md`](docs/FINDINGS.md) section 6 has the reasoning, and
section 6b has the test any change has to pass: a change that only improves
full-sample return has been fitted, not demonstrated.

## Engine

`roostoo/engine.py` is the loop. Four constraints shaped it:

1. Rules 2 and 3 are defined on closed 30-minute bars, so the strategy runs once
   per bar, not once per loop.
2. Rule 5's stop is a price level, so protective exits are checked on every loop.
3. Exits matter more than entries. Flattening has to work even when the risk layer
   has stopped new business.
4. A 14-day unattended run will restart. Position state is persisted, and every
   cycle reconciles the local book against the exchange's balances. The exchange is
   the source of truth for quantity.

Live and backtest share the code. The backtester reuses `RiskManager`,
`PositionSizer`, `PositionBook` and the same `Strategy.generate` call instead of
reimplementing them. Both evaluate the strategy once per closed bar and check stops
on every iteration, so what is left between them is the fill model: a signal on bar
*t* fills at the open of *t+1*, against a synthetic spread. Those are assumptions,
and they are stated rather than hidden.

Orders are handled around the failure that costs the most. A transport failure
leaves an order genuinely unknown, so `place_order` is never blind-retried. The
client returns `status="UNKNOWN"` and the engine reconciles against the order
history. A history row only counts as ours when it is genuinely `FILLED`, matches
the side, matches the quantity to within one lot, and reports something filled.
Matching on side and recency alone once accepted a cancelled order of an unrelated
size.

Other failure modes we closed, each with a regression test:

- An absent balance row is not a zero balance. Only an explicit zero closes a
  position. A truncated payload used to read as "the exchange holds nothing" and
  delete the whole book.
- A failed short-position query is not "no shorts". An empty result once deleted
  every short, along with its collateral and its stop.
- A stop that cannot be computed refuses the trade (`REFUSE_ENTRY_WITHOUT_STOP`).
  The alternative was a full-size position with no stop at all, which is the
  opposite of risk-first.
- A position is always closable. The time stop is evaluated before the mark is
  validated, and execution falls back to the live quote and then the entry price,
  so a holding whose mark is zero can still be exited.
- A partial balance snapshot is journalled and skipped rather than priced at zero,
  which would otherwise trip the permanent kill switch.

Every decision, rejection and reconciliation is appended to a JSONL journal plus a
trades CSV, so a live result can be reconstructed afterwards.

## Backtest results

### The ablation

120 days of Binance 30m data, 8 majors. Each row adds one change to the row above
it, so the table doubles as the ablation record:

| configuration | in-sample | out-of-sample | in-sample drawdown | round trips (IS/OOS) |
|---|---|---|---|---|
| reversion, engine defaults | -17.50% | -12.61% | 17.50% | 421 / 178 |
| + Rule 4 deviation gate | -13.45% | -11.86% | 5.60% | 333 / 144 |
| + no shorts | -5.13% | -5.27% | 5.60% | 163 / 55 |
| **momentum + shipped `.env`** | **-2.20%** | **-0.55%** | **2.50%** | 37 / 29 |

Fees paid in-sample fall from 11,273 to 1,102 across those rows, purely because the
strategy trades less. Every row is still negative out of sample. The three
reversion rows were produced by reversing the entry conditions on a development
branch, since this snapshot has no switch for it.

### The measurement that decided the design

`scripts/edge_analysis.py` measures the edge itself rather than the strategy's P&L,
by walking forward from every entry with no stop at all, so the exit policy cannot
be blamed:

```
570 Rule 2 long entries, ADX < 25
  Z reaches the -0.25 exit target within 24 bars   64.9%
  median bars to revert                            9   (~4.5 hours)
  mean gross completed move                        -0.036%
  round trip at market prices                       0.30%
```

The mean completed move is smaller than the round-trip cost, and it is already
slightly negative before costs. Split the timeline into five folds and four entry
thresholds and you get 20 cells, 19 of them negative. Loosening the threshold makes
things worse monotonically; tightening it to `z >= 3` finally produces a positive
gross move of +0.030%, still an order of magnitude short of the 0.30% it has to
clear.

That is why the cost model and the deviation gate matter more than the entry
threshold. The binding constraint is the fee, not the signal strength.

One measurement trap, recorded because it nearly fooled us: filling at the signal
bar's own close instead of the next bar's gives +0.095% where the honest figure is
-0.036%. That one-bar difference is four times the entire edge being measured, and
enough to flip the conclusion. Any measurement of this strategy has to state its
fill assumption.

### Passive entries

`LIMIT_ENTRIES=1` posts the entry as a resting bid and pays 0.05% instead of 0.1%.
Exits always cross, because a stop that rests is not a stop.

| entry | filled | mean net |
|---|---|---|
| market order (what ships) | 100% | -0.336% |
| limit, `touch` | 98.8% | -0.285% |
| limit, `through` | 95.3% | -0.289% |

That is worth about +0.047% per trade: real, and roughly one seventh of the loss,
not a fix. `touch` assumes we are first in the queue at our price, `through`
demands that the bar trade strictly through it, and we quote `through` when
deciding because "the low touched my bid" does not mean we were filled. Both fill
rates come from OHLC bars and are the softest numbers in this document; a real
resting bid only fills if someone sells into it. Watch `orders_posted` against
`orders_cancelled` in the journal before trusting the saving.

## Costs

The venue charges 0.1% taker and 0.05% maker. We model both rather than leaving
them to the broker:

```
market round trip = 2 x (0.1% taker + 0.05% slippage)              = 0.30%
maker entry       = 0.1% taker + 0.05% maker + 2 x 0.05% slippage  = 0.25%
```

| Term | Value | Where |
|---|---|---|
| `TAKER_FEE` | 0.1% per side | `roostoo/config.py`, charged in `backtest._fill` |
| `MAKER_FEE` | 0.05% per side | `config.fee_for(order_type)` picks by order type |
| `SLIPPAGE_BPS` | 5 bps per side | applied as an adverse price move on every fill |
| `--spread-bps` | 5 bps assumed | a synthetic bid and ask around each close |

Fees are charged on both legs, on the filled notional, not once per round trip.

The entry gate uses a smaller number on purpose. 0.2% is two takers and nothing
else: it is the fee-only bound. The 0.30% figure is what a completed round trip
costs once slippage is included, and it is the number the strategy has to beat.
Where you see 0.2% in a comment, that is the fee-only reading.

## Risk rules

Rules 4 to 12 ship as defaults in `roostoo/risk.py` and `roostoo/config.py`, because
the engine cannot run without a risk layer, a sizing policy and some exit. Nothing
in `engine.py` or `backtest.py` assumes the current policy:

| Rule | Implementation | State |
|---|---|---|
| 1: top-8 by 24h turnover, spread <= 0.1%, depth | `roostoo/universe.py` | implemented; the template raises the cap to 12 pairs, and depth needs a provider |
| 2: SMA48/Std48 z-score entry, momentum reading | `roostoo/strategies/mean_reversion.py` | implemented and hardwired; `z_entry` 2.8 code / 2.0 template |
| 3: ADX(14) < 25 trend filter | `roostoo/indicators.py` | implemented; `adx_max` 20 code / 25 template |
| 4: `abs(Close-SMA48)/Close` above a floor | `roostoo/indicators.py` | implemented and on; 1.2% code / 0.6% template |
| 5: stop at 1.5 x ATR(14) | `risk.protective_exits`, `PositionSizer` | `STOP_ATR_MULT`; code 1.5, template 2.5 |
| 6: time stop at 12 bars | `risk.protective_exits` | `MAX_HOLD_BARS`; code 12, template 49 |
| 7: max loss 0.5% of NAV per trade | `PositionSizer` | the sizing rule |
| 8: <= 15% NAV per coin | `RiskManager.evaluate` | `MAX_PAIR_WEIGHT` |
| 9: <= 60% NAV gross | `RiskManager.evaluate` | `MAX_GROSS_EXPOSURE` |
| 10: <= 4 positions | `RiskManager.evaluate` | `MAX_OPEN_POSITIONS` |
| 11: -2% day halts entries | `RiskManager.observe` | `MAX_DAILY_LOSS_PCT`, UTC+8 day boundary |
| 12: no re-entry for 2 bars | `RiskManager.record_exit` | `COOLDOWN_BARS` |
| supplementary: ReturnShock, VWAPGap, RelVolume, VolExpansion | `roostoo/indicators.py` | implemented and tested; off in the code |

Kill switches are persisted, so a restart cannot silently clear a halt. A permanent
drawdown halt stops new business but keeps managing what is held, and Rule 11's
daily halt lasts until the next UTC+8 day. The process exit status distinguishes
"deliberately halted" from "crashed", which is what the systemd unit reads.

## Data

The Roostoo public API exposes one market-data endpoint, `/v3/ticker`, and it
returns a snapshot: `LastPrice`, `MaxBid`, `MinAsk`, 24h `Change`, 24h
`CoinTradeValue` and `UnitTradeValue`. That is not enough for the rules.

| The rules need | Roostoo gives | What we do |
|---|---|---|
| 30-minute OHLCV candles | nothing | `CandleBuilder` samples the ticker into bars live; `scripts/fetch_history.py` pulls Binance history for backtests |
| Per-bar volume | rolling 24h turnover | live: the change in `UnitTradeValue` between samples; backtest: real Binance volume |
| Order-book depth within 0.5% | no endpoint | a pluggable `DepthProvider`; Binance L2 as a proxy |
| ADX, ATR, VWAP, VolExpansion | nothing | computed from the bars above, in pure Python |

The organisers confirmed that the mock venue's prices follow Binance. That is the
premise the whole design rests on, so we measure it rather than assume it:
`roostoo/basis.py` compares every quoted pair against Binance on each bar, journals
the readings, and drops any pair whose basis exceeds `BASIS_MAX_PCT` (1% by
default). A wide basis means the wrong symbol, the wrong pair or a stale feed, and
fading a z-score computed against it is trading noise.

Two caveats here. Rule 1's depth clause is only testable against Binance's book,
which measures market liquidity rather than the mock venue's own depth: it answers
"is this asset liquid", not "can Roostoo absorb my order". That check fails closed,
so `DEPTH_PROVIDER=none` ships. If the depth endpoint is unreachable, every pair is
excluded and the bot stops trading without saying much, which is a bad failure mode
inside a scored window. And a live candle built from periodic ticker samples can
miss intrabar highs and lows, which makes the volume-derived indicators the least
trustworthy ones we compute.

## Running it for real

```bash
python run_live.py --check             # read-only: signing, clock, universe
python run_live.py --no-seed           # cold start, build bars from live samples
python run_live.py --flatten-on-exit   # deliberate stop: close the book
```

The competition requires at least 8 active trading days, so the bot runs under
systemd with `Restart=always`, per [`deploy/AWS_DEPLOY.md`](deploy/AWS_DEPLOY.md).
The unit deliberately does not pass `--flatten-on-exit`, because a crash loop must
never liquidate the book. The host clock has to be within 60 seconds of the exchange
or every signed request is rejected; `--check` verifies that, and the deploy guide
sorts it out with `chrony`.

Pair names use the venue's own quoting, `/USD` and not `/USDT`, so
`ROOSTOO_PAIRS=BTC/USD,ETH/USD,...`. If none of the configured pairs are tradable,
the engine says so and falls back to turnover-based discovery. That fallback changes
the universe silently, so the warning is worth reading.

## Reproducing the numbers

Every command here runs from a fresh clone.

```bash
# 1) no keys, no network: exercise the whole chain against the simulator
python run_live.py --mock --cycles 20

# 2) real history, no API key. Pin a window with --start/--end for anything you
#    intend to compare against a table; closed klines are immutable
python scripts/fetch_history.py --days 365 --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,LINKUSDT,AVAXUSDT --verify

# 3) the ablation: first 75% in-sample, last 25% out-of-sample
python run_backtest.py --data-dir data --oos-frac 0.25

# 4) per-exit-reason forensics
python scripts/analyze_backtest.py reports/trades_out-of-sample.csv

# 5) the edge measurement and its stability test
python scripts/edge_analysis.py --data-dir data
python scripts/edge_analysis.py --data-dir data --folds 5
python scripts/edge_analysis.py --data-dir data --maker

# 6) parameter sweeps. On Windows pass the grid as @file: PowerShell strips the
#    quotes from inline JSON, and reports/grid_stop.json is a worked example
python run_sweep.py --config-grid "@reports/grid_stop.json"

# 7) with keys: verify before you send anything
python run_live.py --check
```

A table row is a configuration, not a command. Each row differs by strategy params
or by a config value, and the settings behind a given run are recorded in the dated
`reports_*` directory next to that run's output. `docs/FINDINGS.md` states the
window each table used.

Because the code defaults and the template disagree (see
[Which configuration is which](#which-configuration-is-which)), decide which one you
mean before comparing anything. `--params` overrides the strategy for a single run,
and `--env` lets the backtester read a different dotenv file. The ratio figures in
`docs/FINDINGS.md` are also clamped at +/-10 for reporting: a capped number is a
lower bound rather than a measurement, and the clamp compresses configurations that
differ in reality onto the same printed value.

## Limitations

- The strategy loses money out of sample on every window we measured. One in-sample
  cell is positive (+2.65%), from the strictest parameter set, which is also the one
  that trades least. Every entry threshold the fold test covers loses in four of
  five folds, so we treat that cell as noise rather than a lead.
- Live execution has not been validated end to end. Signing, clock sync and universe
  selection are verified; real fills, the live flatten path and a multi-day
  unattended run are not. The state-safety tests pin what happens when the stored
  book cannot be loaded, not what happens when the venue misbehaves during a
  flatten.
- The backtest datasets are not committed, so absolute returns here are only
  comparable to runs on the same window. The numbers quoted were produced with the
  template's looser entries, not with the code defaults.
- Stops are detected against a bar's high and low and filled at the stop level plus
  slippage, which still understates a real gap through the stop.
- `stdev` uses the sample (n-1) denominator and ADX follows Wilder's original
  seeding. Both are defensible, and either can flip a trade sitting exactly on a
  threshold.
- Every trade that reached the z-exit target was profitable. That is a selection on
  the exit outcome and says nothing about the entry, so we do not cite it as
  evidence. The edge measurement in [Backtest results](#backtest-results) is the
  test we rely on.
- This targets a mock exchange with a virtual portfolio. It is not investment advice
  and it is not ready for real capital.

## Layout

```
run_live.py                 live loop (--check does read-only verification)
run_backtest.py             in-sample / out-of-sample backtest and report
run_sweep.py                parameter sweep and ablation, holdout-aware
scripts/fetch_history.py    Binance 30m klines -> CSV (pagination, retries, verify)
scripts/analyze_backtest.py round-trip forensics: exit reasons, fee drag, holding time
scripts/edge_analysis.py    measures the edge itself against the round-trip cost
scripts/scan_secrets.py     content and history secret scanner, used by CI
deploy/                     systemd unit and the AWS EC2 guide
roostoo/
  client.py       signed REST (HMAC-SHA256), retries, throttle, server-time sync
  simulator.py    in-process mock exchange: same surface, same fees, offline
  candles.py      OHLCV bars, live bar building and CSV loading
  basis.py        cross-venue basis monitor against Binance
  indicators.py   SMA/EMA/RSI/z-score plus Wilder ADX, ATR, VWAP, VolExpansion
  metrics.py      Sharpe / Sortino / Calmar / drawdown and the competition composite
  universe.py     Rule 1: turnover ranking, spread ceiling, depth provider
  risk.py         NAV, position book, sizing, caps, protective exits, kill switch
  strategies/     strategy interface and the z-score strategy
  engine.py       the decision loop
  journal.py      append-only audit trail (JSONL and trades.csv)
  backtest.py     event-driven backtester sharing the live objects
tests/            unittest suite, stdlib only, no network
docs/FINDINGS.md  measurements, ablations and negative results
docs/SECURITY.md  credential handling and incident response
data/             two synthetic samples for offline runs
```

Some of the tree is archive rather than code. The dated `data_*` and `reports_*`
directories are snapshots kept for provenance, `run_6_backtests.py` and
`params_exit025.json` are scratch files from particular experiments, and the IDE
directory is a leftover we would drop in a cleanup pass. Nothing the bot imports
depends on any of them.

Never commit a key. `.env` is git-ignored and is the only place credentials live;
`.env.example` is committed with empty values. Three guards enforce that: a
pre-commit hook, `scripts/publish.ps1`, and a `secret-scan` CI job, all described in
[`docs/SECURITY.md`](docs/SECURITY.md).

## Tests and CI

```bash
python -m unittest discover -s tests -t .
```

The suite is stdlib-only and needs no network and no sleeping. It includes the HMAC
signature reproduced byte-for-byte from Roostoo's published test vector, which is
the failure that would otherwise cost a day of the competition to diagnose on live
keys, and the state-safety tests, which pin the guarantees that a bad startup or a
malformed balance response cannot destroy the stored book. Unreadable state is
handled explicitly: a row or field the engine cannot parse is dropped and the run
continues on defaults, but a book that was never successfully loaded is never
overwritten, and state belonging to another run mode or venue is refused for writing
as well as for reading.

CI runs on every push and pull request: the unit suite on Python 3.10 and 3.13, a
compile pass, a check that text files are BOM-free UTF-8, a configuration test that
a missing key is rejected, and two secret scanners, one over the working tree and
one over git history. `main` is protected by a ruleset requiring a pull request, one
approval and a green `ci` check.

## License

MIT, see [`LICENSE`](LICENSE). The competition requires the submitted repository to
be open source, and a public repository without a licence is legally "all rights
reserved", so this file is what makes that claim true. Swap it for Apache-2.0 or GPL
if the team prefers, but do not remove it.
