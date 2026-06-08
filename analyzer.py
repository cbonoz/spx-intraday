#!/usr/bin/env python3
"""
analyzer.py — Interpret signals from signal_grabber and produce actionable 0DTE recommendations.

Signal interpretation rules (derived from research + historical analysis):

SIGNAL 1: IB Range Ratio
  - >1.3x average → elevated volatility, expect larger day range
  - >1.5x average → confirmed expansion day
  - <0.7x average → narrow range, either quiet day or squeeze setup

SIGNAL 2: IB Breakout (10:30-11:30 window)
  - Break above IB high on volume → bullish continuation
  - Break below IB low on volume → bearish continuation
  - No break by 11:30 → indecision, skip or play mean-reversion

SIGNAL 3: VIX Change by 10:30
  - VIX up >3% with SPX flat → bearish divergence (institutional hedging)
  - VIX down >3% with SPX flat → bullish divergence
  - VIX up >5% suggests volatility expansion regardless of direction

SIGNAL 4: Volume Ratio
  - IB volume >1.5x average → institutional participation, likely trend day
  - IB volume <0.8x average → retail-driven, lower conviction

SIGNAL 5: Gap Fill
  - Gap >0.5% that gets fully filled by 10:30 → rejection, likely continuation
  - Gap holds → support/resistance at gap level
"""

import json
import sys




def evaluate_ib_range(signals: dict) -> dict:
    """Score IB range relative to 10-day average."""
    ratio = signals.get("ib_range_ratio")
    if ratio is None:
        return {"score": 0, "max_score": 20, "signal": "neutral",
                "detail": "No IB range data"}

    if ratio > 1.5:
        return {"score": 18, "max_score": 20, "signal": "high_vol",
                "detail": f"IB range {ratio}x avg — confirmed expansion day"}
    elif ratio > 1.3:
        return {"score": 14, "max_score": 20, "signal": "elevated",
                "detail": f"IB range {ratio}x avg — elevated volatility"}
    elif ratio > 0.85:
        return {"score": 8, "max_score": 20, "signal": "neutral",
                "detail": f"IB range {ratio}x avg — normal range"}
    else:
        return {"score": 4, "max_score": 20, "signal": "narrow",
                "detail": f"IB range {ratio}x avg — narrow range, possible squeeze"}


def evaluate_ib_break(signals: dict) -> dict:
    """Score IB breakout direction and timing."""
    direction = signals.get("ib_break_direction")
    minutes_after = signals.get("ib_break_minutes_after")

    if direction is None:
        return {"score": 0, "max_score": 30, "signal": "no_break",
                "detail": "No IB break yet — monitor 10:30-11:30 window"}

    # Earlier breaks are more significant
    confidence = 0
    if minutes_after is not None:
        if minutes_after <= 15:
            confidence = 30  # Immediate break
        elif minutes_after <= 30:
            confidence = 25  # Quick break
        elif minutes_after <= 60:
            confidence = 18  # Within the window
        else:
            confidence = 10  # Late break, less conviction
    else:
        confidence = 22  # Break detected, timing unknown

    if direction == "up":
        return {"score": confidence, "max_score": 30, "signal": "bullish_break",
                "detail": f"Broke above IB {minutes_after:.0f} min after close — bullish"}
    else:
        return {"score": confidence, "max_score": 30, "signal": "bearish_break",
                "detail": f"Broke below IB {minutes_after:.0f} min after close — bearish"}


def evaluate_vix(signals: dict) -> dict:
    """Score VIX action by 10:30."""
    vix_chg = signals.get("vix_change_1030_pct")
    div = signals.get("vix_divergence")

    if vix_chg is None:
        return {"score": 0, "max_score": 20, "signal": "neutral",
                "detail": "No VIX data"}

    if div == "bearish":
        return {"score": 18, "max_score": 20, "signal": "bearish_divergence",
                "detail": f"VIX up {vix_chg}% with SPX flat — bearish divergence"}
    elif div == "bullish":
        return {"score": 18, "max_score": 20, "signal": "bullish_divergence",
                "detail": f"VIX down {vix_chg}% with SPX flat — bullish divergence"}

    # No divergence but VIX moving
    if vix_chg > 5:
        return {"score": 10, "max_score": 20, "signal": "volatile",
                "detail": f"VIX up {vix_chg}% — volatility expansion, direction unclear"}
    elif vix_chg < -5:
        return {"score": 12, "max_score": 20, "signal": "calming",
                "detail": f"VIX down {vix_chg}% — fear receding, supportive for bulls"}
    else:
        return {"score": 4, "max_score": 20, "signal": "neutral",
                "detail": f"VIX {vix_chg:+.1f}% — no strong signal"}


def evaluate_volume(signals: dict) -> dict:
    """Score volume confirmation."""
    vol_ratio = signals.get("ib_volume_ratio")
    if vol_ratio is None:
        return {"score": 0, "max_score": 15, "signal": "neutral",
                "detail": "No volume data"}

    if vol_ratio > 1.8:
        return {"score": 14, "max_score": 15, "signal": "high_volume",
                "detail": f"IB volume {vol_ratio}x avg — strong institutional participation"}
    elif vol_ratio > 1.3:
        return {"score": 10, "max_score": 15, "signal": "elevated_volume",
                "detail": f"IB volume {vol_ratio}x avg — elevated participation"}
    elif vol_ratio > 0.8:
        return {"score": 5, "max_score": 15, "signal": "normal_volume",
                "detail": f"IB volume {vol_ratio}x avg — normal activity"}
    else:
        return {"score": 2, "max_score": 15, "signal": "low_volume",
                "detail": f"IB volume {vol_ratio}x avg — low conviction"}


def evaluate_gap(signals: dict) -> dict:
    """Score gap behavior."""
    gap_pct = signals.get("gap_pct")
    spx_at_1030 = signals.get("spx_at_1030")
    prior_close = signals.get("prior_close")

    if gap_pct is None or spx_at_1030 is None or prior_close is None:
        return {"score": 0, "max_score": 10, "signal": "neutral",
                "detail": "No gap data"}

    # Determine if gap was filled by 10:30
    # If we opened above prior close (gap up) and now below, gap filled
    # If we opened below prior close (gap down) and now above, gap filled
    if gap_pct > 0 and spx_at_1030 < prior_close:
        return {"score": 9, "max_score": 10, "signal": "gap_filled_up",
                "detail": f"Gapped up {gap_pct:+.2f}%, filled by 10:30 — bearish rejection"}
    elif gap_pct < 0 and spx_at_1030 > prior_close:
        return {"score": 9, "max_score": 10, "signal": "gap_filled_down",
                "detail": f"Gapped down {gap_pct:+.2f}%, filled by 10:30 — bullish rejection"}
    elif abs(gap_pct) > 0.5:
        # Large gap holding
        if gap_pct > 0:
            return {"score": 7, "max_score": 10, "signal": "gap_holds_up",
                    "detail": f"Gap up {gap_pct:+.2f}% holding — support at gap level"}
        else:
            return {"score": 7, "max_score": 10, "signal": "gap_holds_down",
                    "detail": f"Gap down {gap_pct:+.2f}% holding — resistance at gap level"}
    else:
        return {"score": 3, "max_score": 10, "signal": "small_gap",
                "detail": f"Small gap {gap_pct:+.2f}% — neutral"}


def get_directional_bias(evaluations, vix_div):
    """Determine overall directional bias from all evaluations."""
    bullish_signals = 0
    bearish_signals = 0

    # IB break
    ib_break_signal = evaluations.get("ib_break", {}).get("signal", "")
    if ib_break_signal == "bullish_break":
        bullish_signals += 3
    elif ib_break_signal == "bearish_break":
        bearish_signals += 3

    # VIX
    if vix_div == "bearish":
        bearish_signals += 2
    elif vix_div == "bullish":
        bullish_signals += 2

    # Gap
    gap_signal = evaluations.get("gap", {}).get("signal", "")
    if "gap_filled_up" in gap_signal:
        bearish_signals += 1
    elif "gap_filled_down" in gap_signal:
        bullish_signals += 1
    elif "gap_holds_up" in gap_signal:
        bullish_signals += 1
    elif "gap_holds_down" in gap_signal:
        bearish_signals += 1

    diff = bullish_signals - bearish_signals
    if diff >= 3:
        return "bullish"
    elif diff <= -3:
        return "bearish"
    elif diff >= 1:
        return "leaning_bullish"
    elif diff <= -1:
        return "leaning_bearish"
    else:
        return "neutral"


def estimate_move_pct(signals: dict) -> float:
    """Estimate the expected full-day range as a percentage of SPX price.

    Uses IB range as a base and scales by volume/volatility factors.
    """
    ib_range = signals.get("ib_range")
    spx_price = signals.get("spx_price")
    ib_ratio = signals.get("ib_range_ratio")
    vol_ratio = signals.get("ib_volume_ratio")

    if not ib_range or not spx_price:
        return 1.0  # default guess

    base_range = ib_range / spx_price * 100  # IB as % of price

    # Scale: on average the day range is ~2.5x the IB range
    # But this varies significantly with IB width
    multiplier = 2.5
    if ib_ratio:
        # Empirical: wide IB days (ratio > 1.3) can produce 3-5x expansion
        # Standard days (ratio ~1.0) produce ~2.5x
        multiplier = 2.0 + (ib_ratio * 1.2)
        multiplier = min(5.0, max(1.5, multiplier))
    if vol_ratio and vol_ratio > 1.3:
        multiplier *= 1.1

    return round(base_range * multiplier, 2)


def generate_strike_recommendations(signals: dict, bias: str, move_pct: float) -> list:
    """Generate suggested 0DTE strikes based on bias and estimated move.

    Returns list of dicts with strike, type, and rationale.
    """
    spx_price = signals.get("spx_price")
    if not spx_price:
        return []

    recommendations = []
    move_points = spx_price * move_pct / 100

    if bias in ("bullish", "leaning_bullish"):
        # Bull call spread or long call
        strike_1 = round(spx_price + move_points * 0.5, 0)
        strike_2 = round(spx_price + move_points * 0.8, 0)
        recommendations.append({
            "type": "long_call",
            "strike": strike_1,
            "max_payoff": f"SPX > {strike_1:,.0f}",
            "rationale": f"Aggressive entry at {strike_1:,.0f} (50% of est. move)"
        })
        recommendations.append({
            "type": "call_spread",
            "strike_buy": strike_1,
            "strike_sell": strike_2,
            "max_payoff": f"SPX > {strike_2:,.0f}",
            "rationale": f"Bull call spread {strike_1:,.0f}/{strike_2:,.0f} — defined risk"
        })

    elif bias in ("bearish", "leaning_bearish"):
        strike_1 = round(spx_price - move_points * 0.5, 0)
        strike_2 = round(spx_price - move_points * 0.8, 0)
        recommendations.append({
            "type": "long_put",
            "strike": strike_1,
            "max_payoff": f"SPX < {strike_1:,.0f}",
            "rationale": f"Aggressive entry at {strike_1:,.0f} (50% of est. move)"
        })
        recommendations.append({
            "type": "put_spread",
            "strike_buy": strike_1,
            "strike_sell": strike_2,
            "max_payoff": f"SPX < {strike_2:,.0f}",
            "rationale": f"Bear put spread {strike_1:,.0f}/{strike_2:,.0f} — defined risk"
        })

    else:
        # Neutral / no clear bias — suggest iron condor
        r1 = round(spx_price + move_points * 0.3, 0)
        r2 = round(spx_price - move_points * 0.3, 0)
        recommendations.append({
            "type": "iron_condor",
            "strikes": f"{r2:,.0f}/{r1:,.0f}",
            "max_payoff": f"SPX between {r2:,.0f} and {r1:,.0f}",
            "rationale": "No clear bias — play range-bound expectations"
        })
        recommendations.append({
            "type": "no_trade",
            "rationale": "Mixed signals suggest waiting for clearer setup"
        })

    return recommendations


# ── Main Analysis ──────────────────────────────────────────────────────────

def analyze(signals: dict) -> dict:
    """Run full analysis on a signal dict. Returns analysis dict with
    evaluations, total conviction score, bias, and recommendations."""
    
    # Evaluate each signal
    evaluations = {
        "ib_range": evaluate_ib_range(signals),
        "ib_break": evaluate_ib_break(signals),
        "vix": evaluate_vix(signals),
        "volume": evaluate_volume(signals),
        "gap": evaluate_gap(signals),
    }
    
    # Total conviction score (out of 100)
    total_score = sum(e["score"] for e in evaluations.values())
    max_possible = sum(e["max_score"] for e in evaluations.values())
    conviction_pct = round(total_score / max_possible * 100) if max_possible > 0 else 0

    # Directional bias
    vix_div = signals.get("vix_divergence")
    bias = get_directional_bias(evaluations, vix_div)

    # Estimated move
    move_pct = estimate_move_pct(signals)

    # Strike recommendations
    recs = generate_strike_recommendations(signals, bias, move_pct)

    # Build result
    analysis = {
        "conviction": conviction_pct,
        "bias": bias,
        "estimated_move_pct": move_pct,
        "evaluations": evaluations,
        "recommendations": recs,
        "signals_summary": {
            "ib_range_ratio": signals.get("ib_range_ratio"),
            "ib_break_direction": signals.get("ib_break_direction"),
            "vix_change_1030_pct": signals.get("vix_change_1030_pct"),
            "vix_divergence": vix_div,
            "gap_pct": signals.get("gap_pct"),
            "ib_volume_ratio": signals.get("ib_volume_ratio"),
        }
    }

    return analysis


def main():
    # Read signals from stdin (piped from signal_grabber.py)
    try:
        raw = sys.stdin.read()
        if not raw:
            print(json.dumps({"error": "No input data"}, indent=2))
            sys.exit(1)
        signals = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON input: {e}"}, indent=2))
        sys.exit(1)

    if "error" in signals:
        print(json.dumps(signals, indent=2))
        sys.exit(1)

    result = analyze(signals)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
