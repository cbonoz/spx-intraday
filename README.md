# SPX 0DTE Signal Pipeline

Evaluates 5 signals from SPX, VIX, and /ES data to produce a directional bias and suggested 0DTE option strikes. Designed to run at 10:30 AM ET when the Initial Balance window closes.

## Signals

| Signal | Weight | Source |
|--------|--------|--------|
| IB Range | 25% | SPX 5m bars — range vs 10-day avg |
| IB Break | 30% | Breakout direction + timing after IB lock |
| VIX | 20% | VIX change — divergence detection |
| Volume | 15% | IB volume vs 10-day avg |
| Gap | 10% | Gap fill behavior by 10:30 |

## Quick Start

```bash
uv sync
uv run run.py --text
```

## Requirements

- **Finnhub API key** — set `FINNHUB_API_KEY` in the `HERMES_HOME/workspaces/.env` file. Only used for the market status (holiday check) endpoint on the free tier.

## API Calls Per Run

- 1 yfinance batch download (`^GSPC` + `^VIX`)
- 1 yfinance ticker call (`ES=F`)
- 1 Finnhub market status check

No HTML scraping. All data from structured APIs.

## Files

- `signal_grabber.py` — Data fetching + signal calculation
- `analyzer.py` — Signal scoring, bias, strike recommendations
- `run.py` — Orchestrator, outputs JSON or formatted text

## Stack

- Python 3.11+ via uv
- yfinance (market data)
- finnhub-python (market status)
