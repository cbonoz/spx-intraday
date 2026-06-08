#!/usr/bin/env python3
"""
signal_grabber.py — Fetch all SPX 0DTE signals at 10:30 AM ET

Pulls:
  1. SPX price data (yfinance, 5m bars)
  2. VIX price data (yfinance, 5m bars, normalized to ET)
  3. /ES futures (yfinance, for pre-market context)
  4. Calculated metrics: IB range, VIX change, gap, volume ratio

Output: JSON to stdout for piping into analyzer or direct consumption.

Strategy: uv-managed project — deps in pyproject.toml, run via `uv run run.py --text`.
API calls per run: 2 yfinance batch requests + 1 finnhub request = 3 total.
"""

import json
import os
import sys
import warnings

import finnhub
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

# ── Constants ──────────────────────────────────────────────────────────────
SPX_TICKER = "^GSPC"
VIX_TICKER = "^VIX"
ES_TICKER = "ES=F"

ET = "America/New_York"

# ── Data Fetching ──────────────────────────────────────────────────────────


def fetch_market_data():
    """Fetch SPX, VIX, and /ES data via yfinance in one batch call per period.

    Returns:
        spx: SPX DataFrame (10d, 5m intervals), tz=ET
        vix: VIX DataFrame (10d, 5m intervals), tz=ET
        es: /ES futures DataFrame (5d, 5m intervals), tz=ET, or None
    """
    # Batch SPX + VIX together (same period/interval)
    combined = yf.download(
        [SPX_TICKER, VIX_TICKER],
        period="10d",
        interval="5m",
        group_by="ticker",
        progress=False,
        auto_adjust=False,
    )

    if combined.empty:
        raise RuntimeError("No market data returned from yfinance")

    spx = combined[SPX_TICKER]
    vix = combined[VIX_TICKER]

    if spx.empty:
        raise RuntimeError("No SPX data returned")
    if vix.empty:
        raise RuntimeError("No VIX data returned")

    spx.index = spx.index.tz_convert(ET)
    vix.index = vix.index.tz_convert(ET)

    # /ES futures (separate call — different period + format)
    es = None
    try:
        es_ticker = yf.Ticker(ES_TICKER)
        es_raw = es_ticker.history(period="5d", interval="5m")
        if not es_raw.empty:
            es_raw.index = es_raw.index.tz_convert(ET)
            es = es_raw
    except Exception:
        pass

    return spx, vix, es


# ── Signal Calculations ────────────────────────────────────────────────────


def calculate_signals(spx, vix, es):
    """Calculate all trading signals from fetched data.

    Args:
        spx: SPX DataFrame (5m OHLCV, indexed by ET datetime)
        vix: VIX DataFrame (5m OHLCV, indexed by ET datetime)
        es: /ES futures DataFrame or None

    Returns:
        dict with all signal fields
    """
    now_ts = pd.Timestamp.now(tz=ET)
    today = now_ts.normalize()

    # Find today's data (may be partial during the day)
    spx_today = spx[spx.index.normalize() == today] if today in spx.index.normalize().values else pd.DataFrame()

    # ── Determine the most recent full trading day ──
    if not spx_today.empty:
        target_date = today
    else:
        available = sorted(spx.index.normalize().unique(), reverse=True)
        target_date = available[0] if len(available) > 0 else today

    spx_day = spx[spx.index.normalize() == target_date]
    vix_day = vix[vix.index.normalize() == target_date] if not vix.empty else pd.DataFrame()

    result = {
        "timestamp": now_ts.isoformat(),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "is_today_active": len(spx_today) > 0,
    }

    # ── Prior day close ──
    prior_dates = [d for d in sorted(spx.index.normalize().unique(), reverse=True)
                   if d < target_date]
    prior_close = None
    if prior_dates:
        prior_day = spx[spx.index.normalize() == prior_dates[0]]
        if not prior_day.empty:
            prior_close = float(prior_day["Close"].dropna().iloc[-1])
    result["prior_close"] = prior_close

    # ── Current SPX price ──
    current_price = float(spx_day["Close"].dropna().iloc[-1]) if not spx_day.empty else None
    result["spx_price"] = current_price

    # ── Gap from prior close ──
    if prior_close and current_price:
        result["gap_pct"] = round(((current_price / prior_close) - 1) * 100, 2)
        result["gap_points"] = round(current_price - prior_close, 2)
    else:
        result["gap_pct"] = None
        result["gap_points"] = None

    # ── Initial Balance (9:30-10:30 ET) ──
    ib = spx_day.between_time("09:30", "10:30")
    result["ib_window_available"] = len(ib) > 0

    if len(ib) > 0:
        ib_high = float(ib["High"].max())
        ib_low = float(ib["Low"].min())
        ib_range = round(ib_high - ib_low, 2)
        ib_mid = round((ib_high + ib_low) / 2, 2)
        ib_volume = int(ib["Volume"].dropna().sum())

        result["ib_high"] = ib_high
        result["ib_low"] = ib_low
        result["ib_range"] = ib_range
        result["ib_mid"] = ib_mid
        result["ib_volume"] = ib_volume
    else:
        result["ib_high"] = None
        result["ib_low"] = None
        result["ib_range"] = None
        result["ib_mid"] = None
        result["ib_volume"] = None

    # ── Average IB range over last 10 trading days (excluding today) ──
    ib_ranges = []
    for d in sorted(spx.index.normalize().unique(), reverse=True):
        if d == target_date:
            continue
        day_data = spx[spx.index.normalize() == d]
        day_ib = day_data.between_time("09:30", "10:30")
        day_ib = day_ib.dropna()  # filter out extended-hours NaN rows
        if len(day_ib) >= 6:
            ib_ranges.append(float(day_ib["High"].max() - day_ib["Low"].min()))
        if len(ib_ranges) >= 10:
            break

    avg_ib_range = round(sum(ib_ranges) / len(ib_ranges), 2) if ib_ranges else None
    result["ib_avg_range_10d"] = avg_ib_range

    if result["ib_range"] and avg_ib_range and avg_ib_range > 0:
        result["ib_range_ratio"] = round(result["ib_range"] / avg_ib_range, 2)
    else:
        result["ib_range_ratio"] = None

    # ── Position within IB at 10:30 ──
    if len(ib) > 0:
        ib_last_close = float(ib["Close"].dropna().iloc[-1])
        result["spx_at_1030"] = ib_last_close
        if result["ib_high"] and ib_last_close > result["ib_high"]:
            result["ib_position_1030"] = "above"
        elif result["ib_low"] and ib_last_close < result["ib_low"]:
            result["ib_position_1030"] = "below"
        else:
            result["ib_position_1030"] = "inside"
    else:
        result["spx_at_1030"] = None
        result["ib_position_1030"] = None

    # ── Post-IB break (10:30 onward) ──
    if len(ib) > 0:
        post_ib = spx_day[spx_day.index >= ib.index[-1]]
        if not post_ib.empty and result["ib_high"] and result["ib_low"]:
            ib_high_val = result["ib_high"]
            ib_low_val = result["ib_low"]
            break_time = None
            break_direction = None

            for idx, row in post_ib.iterrows():
                if row["Close"] > ib_high_val:
                    break_time = idx
                    break_direction = "up"
                    break
                elif row["Close"] < ib_low_val:
                    break_time = idx
                    break_direction = "down"
                    break

            if break_time:
                elapsed = (break_time - ib.index[-1]).total_seconds() / 60
                result["ib_break_at"] = break_time.isoformat()
                result["ib_break_minutes_after"] = round(elapsed, 0)
                result["ib_break_direction"] = break_direction
            else:
                result["ib_break_at"] = None
                result["ib_break_minutes_after"] = None
                result["ib_break_direction"] = None
        else:
            result["ib_break_at"] = None
            result["ib_break_minutes_after"] = None
            result["ib_break_direction"] = None
    else:
        result["ib_break_at"] = None
        result["ib_break_minutes_after"] = None
        result["ib_break_direction"] = None

    # ── Volume analysis ──
    total_day_volume = int(spx_day["Volume"].dropna().sum()) if not spx_day.empty else 0
    result["total_day_volume"] = total_day_volume
    if result["ib_volume"] and total_day_volume > 0:
        result["ib_volume_pct_of_day"] = round(result["ib_volume"] / total_day_volume * 100, 1)

    # Average IB volume over last 10 days
    ib_volumes = []
    for d in sorted(spx.index.normalize().unique(), reverse=True):
        if d == target_date:
            continue
        day_data = spx[spx.index.normalize() == d]
        day_ib = day_data.between_time("09:30", "10:30")
        day_ib = day_ib.dropna()
        if len(day_ib) >= 6:
            ib_volumes.append(int(day_ib["Volume"].sum()))
        if len(ib_volumes) >= 10:
            break

    avg_ib_vol = round(sum(ib_volumes) / len(ib_volumes)) if ib_volumes else None
    result["ib_avg_volume_10d"] = avg_ib_vol

    if result["ib_volume"] and avg_ib_vol and avg_ib_vol > 0:
        result["ib_volume_ratio"] = round(result["ib_volume"] / avg_ib_vol, 1)
    else:
        result["ib_volume_ratio"] = None

    # ── VIX analysis ──
    if not vix_day.empty:
        vix_1030 = vix_day.between_time("10:25", "10:35")
        vix_open = vix_day.between_time("09:28", "09:32")

        vix_1030_val = float(vix_1030["Close"].dropna().mean()) if len(vix_1030) > 0 else None
        vix_open_val = float(vix_open["Open"].dropna().iloc[0]) if len(vix_open) > 0 else None
        vix_curr_val = float(vix_day["Close"].dropna().iloc[-1]) if not vix_day.empty else None

        result["vix_open"] = vix_open_val
        result["vix_at_1030"] = vix_1030_val
        result["vix_current"] = vix_curr_val

        if vix_open_val and vix_1030_val and vix_open_val > 0:
            result["vix_change_1030_pct"] = round(
                ((vix_1030_val / vix_open_val) - 1) * 100, 1
            )
        else:
            result["vix_change_1030_pct"] = None

        if vix_open_val and vix_curr_val and vix_open_val > 0:
            result["vix_change_day_pct"] = round(
                ((vix_curr_val / vix_open_val) - 1) * 100, 1
            )
        else:
            result["vix_change_day_pct"] = None

        # VIX/SPX divergence
        if (result["vix_change_1030_pct"] is not None
            and result["gap_pct"] is not None):
            if result["vix_change_1030_pct"] > 3 and result["gap_pct"] > -0.3:
                result["vix_divergence"] = "bearish"
            elif result["vix_change_1030_pct"] < -3 and result["gap_pct"] < 0.3:
                result["vix_divergence"] = "bullish"
            else:
                result["vix_divergence"] = "neutral"
        else:
            result["vix_divergence"] = None
    else:
        result["vix_open"] = None
        result["vix_at_1030"] = None
        result["vix_current"] = None
        result["vix_change_1030_pct"] = None
        result["vix_change_day_pct"] = None
        result["vix_divergence"] = None

    # ── Pre-market /ES futures ──
    if es is not None and not es.empty:
        es_today = es[es.index.normalize() == target_date]
        if not es_today.empty:
            es_premarket = es_today[es_today.index < pd.Timestamp(target_date.strftime("%Y-%m-%d") + " 09:30", tz=ET)]
            if not es_premarket.empty:
                es_pre_high = float(es_premarket["High"].max())
                es_pre_low = float(es_premarket["Low"].min())
                es_pre_first = float(es_premarket["Open"].iloc[0])
                result["es_premarket_high"] = es_pre_high
                result["es_premarket_low"] = es_pre_low
                result["es_premarket_open"] = es_pre_first
                if prior_close:
                    result["es_premarket_range_pct"] = round(
                        (es_pre_high - es_pre_low) / prior_close * 100, 2
                    )
            else:
                result["es_premarket_high"] = None
                result["es_premarket_low"] = None
                result["es_premarket_open"] = None
                result["es_premarket_range_pct"] = None
        else:
            result["es_premarket_high"] = None
            result["es_premarket_low"] = None
            result["es_premarket_open"] = None
            result["es_premarket_range_pct"] = None
    else:
        result["es_premarket_high"] = None
        result["es_premarket_low"] = None
        result["es_premarket_open"] = None
        result["es_premarket_range_pct"] = None

    return result


def load_finnhub_key():
    """Read FINNHUB_API_KEY from workspace .env file."""
    env_path = os.path.expanduser("~/.hermes/workspaces/.env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("FINNHUB_API_KEY="):
                    return line.split("=", 1)[1]
    except Exception:
        pass
    return os.environ.get("FINNHUB_API_KEY", "")


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    if "--version" in sys.argv:
        print("signal_grabber.py v1.0")
        return

    try:
        spx, vix, es = fetch_market_data()
        signals = calculate_signals(spx, vix, es)

        # ── Market open check (Finnhub) ──
        try:
            finnhub_client = finnhub.Client(api_key=load_finnhub_key())
            status = finnhub_client.market_status("US")
            signals["market_open"] = bool(status.get("isOpen", False))
        except Exception:
            signals["market_open"] = None

        print(json.dumps(signals, indent=2, default=str))
    except Exception as e:
        error = {"error": str(e), "timestamp": str(pd.Timestamp.now(tz=ET))}
        print(json.dumps(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
