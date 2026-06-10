#!/usr/bin/env python3
"""
run.py — SPX 0DTE Signal Pipeline

Orchestrates signal_grabber → analyzer → formatted output.
Runs at 10:30 AM ET via cron.

Usage:
  uv run run.py                # Full pipeline, print JSON to stdout
  uv run run.py --text          # Human-readable output for messaging
"""

import json
import subprocess
import sys
import os

# Paths — relative to this script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GRABBER = os.path.join(SCRIPT_DIR, "signal_grabber.py")
ANALYZER = os.path.join(SCRIPT_DIR, "analyzer.py")
PYTHON = sys.executable or os.path.join(SCRIPT_DIR, ".venv", "bin", "python3")


def run_pipeline() -> dict:
    """Run signal_grabber → analyzer, return combined result dict."""
    # Step 1: grab signals
    grab = subprocess.run(
        [PYTHON, GRABBER],
        capture_output=True, text=True, timeout=60
    )
    if grab.returncode != 0:
        err_msg = grab.stderr.strip()
        # Try to get structured error from stdout (if error was written there)
        try:
            err_data = json.loads(grab.stdout)
            if "error" in err_data:
                err_msg = err_data["error"]
        except (json.JSONDecodeError, TypeError):
            pass
        return {"error": f"signal_grabber failed: {err_msg}"}

    try:
        signals = json.loads(grab.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from signal_grabber: {e}"}

    if "error" in signals:
        return signals

    # Step 2: run analysis
    analyze = subprocess.run(
        [PYTHON, ANALYZER],
        input=grab.stdout, capture_output=True, text=True, timeout=30
    )
    if analyze.returncode != 0:
        return {"error": f"analyzer failed: {analyze.stderr.strip()}"}

    try:
        analysis = json.loads(analyze.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from analyzer: {e}"}

    if "error" in analysis:
        return analysis

    # Merge
    return {"signals": signals, "analysis": analysis}


def format_bias(bias: str) -> str:
    """Emoji-rich bias label."""
    mapping = {
        "bullish": "\U0001f7e2 Bullish",
        "leaning_bullish": "\U0001f7e1 Leaning Bullish",
        "neutral": "\u26aa Neutral",
        "leaning_bearish": "\U0001f7e0 Leaning Bearish",
        "bearish": "\U0001f534 Bearish",
    }
    return mapping.get(bias, bias)


def format_conviction(pct: int) -> str:
    """Label for conviction level."""
    if pct >= 70:
        return "High"
    elif pct >= 40:
        return "Moderate"
    else:
        return "Low"


def format_text(result: dict) -> str:
    """Format the full result as human-readable text for messaging."""
    if "error" in result:
        return f"\u26a0\ufe0f SPX 0DTE Signal Error\n\n{result['error']}"

    signals = result.get("signals", {})
    analysis = result.get("analysis", {})

    if not signals or not analysis:
        return "\u26a0\ufe0f Incomplete data \u2014 skipping signal."

    target_date = signals.get("target_date", "Unknown")
    spx_price = signals.get("spx_price")
    gap_pct = signals.get("gap_pct")
    prior_close = signals.get("prior_close")

    bias = analysis.get("bias", "neutral")
    conviction = analysis.get("conviction", 0)
    move_pct = analysis.get("estimated_move_pct", 0)
    recs = analysis.get("recommendations", [])

    evals = analysis.get("evaluations", {})

    # Round raw prices
    spx_rnd = round(spx_price, 1) if spx_price else "?"
    prior_rnd = round(prior_close, 1) if prior_close else "?"

    # Header
    lines = [
        f"**SPX 0DTE Signal \u2014 {target_date}**",
        f"SPX: {spx_rnd:,}",
    ]
    if gap_pct is not None and prior_close:
        gap_label = f" ({gap_pct:+.2f}% from {prior_rnd:,} prior close)"
        lines[-1] += gap_label

    lines.append("")

    # Conviction & Bias
    move_pts = spx_price * move_pct / 100 if spx_price else 0
    lines.append(f"**{format_bias(bias)}** | Conviction: {format_conviction(conviction)} ({conviction}%)")
    lines.append(f"Estimated full-day move: **{move_pct}%** (~{move_pts:,.0f} SPX pts)")
    lines.append("")

    # Key Signals
    ib_eval = evals.get("ib_range", {})
    ib_break_eval = evals.get("ib_break", {})
    vix_eval = evals.get("vix", {})
    vol_eval = evals.get("volume", {})
    gap_eval = evals.get("gap", {})

    lines.append("**Key Signals:**")
    lines.append(f"  \u2022 IB Range: {ib_eval.get('detail', 'N/A')}")
    lines.append(f"  \u2022 IB Break: {ib_break_eval.get('detail', 'N/A')}")
    lines.append(f"  \u2022 VIX: {vix_eval.get('detail', 'N/A')}")
    lines.append(f"  \u2022 Volume: {vol_eval.get('detail', 'N/A')}")
    lines.append(f"  \u2022 Gap: {gap_eval.get('detail', 'N/A')}")
    lines.append("")

    # Recommendations
    if recs:
        lines.append("**Recommendations:**")
        for r in recs:
            typ = r.get("type", "").replace("_", " ").title()
            if typ == "No Trade":
                lines.append(f"  \u23f8 **{typ}** \u2014 {r['rationale']}")
            else:
                payoff = r.get("max_payoff", "")
                rationale = r.get("rationale", "")
                lines.append(f"  \u2022 **{typ}**: {payoff} \u2014 {rationale}")
        lines.append("")

    # Raw Data
    vix_at_1030 = signals.get("vix_at_1030")
    vix_chg = signals.get("vix_change_1030_pct")
    vix_str = f"VIX: @10:30={vix_at_1030:.1f}" if vix_at_1030 else "VIX: N/A"
    if vix_chg is not None:
        vix_str += f" (chg: {vix_chg:+.1f}%)"

    ib_high = signals.get("ib_high")
    ib_low = signals.get("ib_low")
    ib_range = signals.get("ib_range")
    ib_str = f"IB H/L: {ib_high:,.0f} / {ib_low:,.0f} (range: {ib_range})" if ib_high else "IB: N/A"

    vol_ratio = signals.get("ib_volume_ratio")

    lines.append("**Raw Data:**")
    lines.append(f"  SPX: {spx_rnd:,}")
    lines.append(f"  {vix_str}")
    lines.append(f"  {ib_str}")
    if vol_ratio:
        lines.append(f"  IB vol ratio: {vol_ratio}x avg")
    if signals.get("ib_break_direction"):
        d = signals["ib_break_direction"].upper()
        m = signals["ib_break_minutes_after"]
        lines.append(f"  IB break: {d} at {m:.0f} min post-IB")

    return "\n".join(lines)


def main():
    result = run_pipeline()
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if "--text" in sys.argv:
        print(format_text(result))
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
