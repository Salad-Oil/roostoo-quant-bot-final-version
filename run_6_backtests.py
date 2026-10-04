import subprocess
import sys
import re
import csv
from pathlib import Path


PYTHON = sys.executable

# 注意：end 是 exclusive，所以想测到 7/15 全天，要写 7/16
periods = [
    ("2026-07-01", "2026-07-16", "2026-07-01_to_07-15"),
    ("2026-07-16", "2026-08-01", "2026-07-16_to_07-31"),
    ("2026-08-01", "2026-08-16", "2026-08-01_to_08-15"),
    ("2026-08-16", "2026-09-01", "2026-08-16_to_08-31"),
    ("2026-09-01", "2026-09-16", "2026-09-01_to_09-15"),
    ("2026-09-16", "2026-10-01", "2026-09-16_to_09-30"),
]

base_report_dir = Path("reports") / "half_month_backtests"
base_report_dir.mkdir(parents=True, exist_ok=True)


def run_command(cmd):
    print("\n" + "=" * 100)
    print("RUN:", " ".join(str(x) for x in cmd))
    print("=" * 100)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    print(result.stdout)

    if result.stderr.strip():
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with return code {result.returncode}"
        )

    return result.stdout


def get_float(pattern, text):
    match = re.search(pattern, text, re.MULTILINE)

    if not match:
        return None

    return float(match.group(1).replace(",", ""))


def get_int(pattern, text):
    match = re.search(pattern, text, re.MULTILINE)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


results = []

for i, (start, end, label) in enumerate(periods, start=1):

    print("\n")
    print("#" * 100)
    print(f"BACKTEST {i}/6")
    print(f"PERIOD: {label}")
    print("#" * 100)

    report_dir = base_report_dir / label

    # ---------------------------------------------------------
    # 1. Fetch data
    # ---------------------------------------------------------

    run_command([
        PYTHON,
        "scripts/fetch_history.py",
        "--start", start,
        "--end", end,
        "--interval", "30m",
        "--verify",
    ])

    # ---------------------------------------------------------
    # 2. Run backtest
    # ---------------------------------------------------------

    backtest_output = run_command([
        PYTHON,
        "run_backtest.py",
        "--data-dir", "data",
        "--out-dir", str(report_dir),
    ])

    # ---------------------------------------------------------
    # 3. Analyze trades
    # ---------------------------------------------------------

    trade_file = report_dir / "trades_full-sample.csv"

    analyze_output = ""

    if trade_file.exists():
        analyze_output = run_command([
            PYTHON,
            "scripts/analyze_backtest.py",
            str(trade_file),
        ])

    # ---------------------------------------------------------
    # Extract important statistics
    # ---------------------------------------------------------

    final_equity = get_float(
        r"equity\s+[\d,.+-]+\s*->\s*([\d,.+-]+)",
        backtest_output,
    )

    total_return = get_float(
        r"total return\s+([+-]?\d+(?:\.\d+)?)%",
        backtest_output,
    )

    max_dd = get_float(
        r"max drawdown\s+([+-]?\d+(?:\.\d+)?)%",
        backtest_output,
    )

    sharpe = get_float(
        r"Sharpe\s+([+-]?\d+(?:\.\d+)?)",
        backtest_output,
    )

    sortino = get_float(
        r"Sortino\s+([+-]?\d+(?:\.\d+)?)",
        backtest_output,
    )

    fees = get_float(
        r"fees paid\s+([\d,.+-]+)",
        backtest_output,
    )

    round_trips = get_int(
        r"round trips\s+(\d+)",
        analyze_output,
    )

    net_pnl = get_float(
        r"net P&L\s+([\d,.+-]+)",
        analyze_output,
    )

    win_rate = get_float(
        r"winners\s+\d+\s*/\s*\d+\s*\(([+-]?\d+(?:\.\d+)?)%\)",
        analyze_output,
    )

    avg_bars = get_float(
        r"avg bars held\s+([\d.]+)",
        analyze_output,
    )

    results.append({
        "Period": label,
        "Return %": total_return,
        "Final Equity": final_equity,
        "Max DD %": max_dd,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "Trades": round_trips,
        "Win Rate %": win_rate,
        "Net P&L": net_pnl,
        "Fees": fees,
        "Avg Bars": avg_bars,
    })


# =====================================================================
# FINAL SUMMARY TABLE
# =====================================================================

print("\n\n")
print("=" * 145)
print("FINAL 6-PERIOD BACKTEST SUMMARY")
print("=" * 145)

header = (
    f"{'Period':<24}"
    f"{'Return':>10}"
    f"{'Equity':>13}"
    f"{'MaxDD':>10}"
    f"{'Sharpe':>10}"
    f"{'Sortino':>10}"
    f"{'Trades':>9}"
    f"{'Win%':>9}"
    f"{'Net P&L':>13}"
    f"{'Fees':>11}"
    f"{'AvgBars':>10}"
)

print(header)
print("-" * 145)


def fmt(value, decimals=2):
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}"


for r in results:

    print(
        f"{r['Period']:<24}"
        f"{fmt(r['Return %']):>9}%"
        f"{fmt(r['Final Equity']):>13}"
        f"{fmt(r['Max DD %']):>9}%"
        f"{fmt(r['Sharpe'], 3):>10}"
        f"{fmt(r['Sortino'], 3):>10}"
        f"{str(r['Trades'] if r['Trades'] is not None else 'N/A'):>9}"
        f"{fmt(r['Win Rate %']):>8}%"
        f"{fmt(r['Net P&L']):>13}"
        f"{fmt(r['Fees']):>11}"
        f"{fmt(r['Avg Bars'], 1):>10}"
    )

print("=" * 145)


# =====================================================================
# EXTRA SUMMARY
# =====================================================================

valid_returns = [
    r["Return %"]
    for r in results
    if r["Return %"] is not None
]

valid_pnl = [
    r["Net P&L"]
    for r in results
    if r["Net P&L"] is not None
]

valid_trades = [
    r["Trades"]
    for r in results
    if r["Trades"] is not None
]

if valid_returns:

    positive = sum(1 for x in valid_returns if x > 0)
    negative = sum(1 for x in valid_returns if x < 0)

    print()
    print("OVERALL SUMMARY")
    print("-" * 60)
    print(f"Positive periods : {positive} / {len(valid_returns)}")
    print(f"Negative periods : {negative} / {len(valid_returns)}")
    print(f"Average return   : {sum(valid_returns) / len(valid_returns):+.2f}%")
    print(f"Best period      : {max(valid_returns):+.2f}%")
    print(f"Worst period     : {min(valid_returns):+.2f}%")

if valid_pnl:
    print(f"Total net P&L    : {sum(valid_pnl):+,.2f}")

if valid_trades:
    print(f"Total trades     : {sum(valid_trades)}")


# =====================================================================
# SAVE SUMMARY CSV
# =====================================================================

summary_file = base_report_dir / "summary.csv"

with summary_file.open(
    "w",
    newline="",
    encoding="utf-8-sig",
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=results[0].keys(),
    )

    writer.writeheader()
    writer.writerows(results)

print()
print(f"Summary saved to: {summary_file}")