import type { BullBearEntry } from "./types";

export interface CrispBullBear {
  condition: string;
  verdict: "Good" | "Bad";
}

export function formatCrispBullBear(
  entry: BullBearEntry,
  tone: "up" | "down"
): CrispBullBear {
  const interp = entry.interpretation || "";
  const metric = entry.metric_name || "";

  // 1. Valuation percentiles (P/E, P/B, EV/EBITDA, P/S)
  const valMatch = interp.match(/(P\/E|P\/B|EV\/EBITDA|P\/S)\s+is\s+cheaper\s+than\s+(\d+)%/i);
  if (valMatch) {
    const label = valMatch[1];
    const pct = parseInt(valMatch[2], 10);
    if (pct >= 50) {
      return {
        condition: `${label} cheaper than ${pct}% of peers (> 50% discount)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `${label} expensive (cheaper than only ${pct}% of peers)`,
        verdict: "Bad",
      };
    }
  }

  // 2. Sector Relative Strength (3M)
  const rsMatch = interp.match(/3-month\s+return\s+is\s+([+-]?\d+\.?\d*)\s+percentage\s+points\s+vs\s+sector/i);
  if (rsMatch) {
    const ret = parseFloat(rsMatch[1]);
    return {
      condition: `3M Return vs Sector = ${rsMatch[1]}% (${ret > 0 ? "> 0% outperforming" : "< 0% lagging"})`,
      verdict: ret >= 0 ? "Good" : "Bad",
    };
  }

  // 3. RSI(14)
  const rsiMatch = interp.match(/RSI\(14\)\s+is\s+(\d+\.?\d*)/i);
  if (rsiMatch) {
    const rsi = parseFloat(rsiMatch[1]);
    if (rsi >= 70) {
      return {
        condition: `RSI(14) = ${rsi} (> 70 Bullish Momentum)`,
        verdict: "Good",
      };
    } else if (rsi >= 55) {
      return {
        condition: `RSI(14) = ${rsi} (> 55 Upward Momentum)`,
        verdict: "Good",
      };
    } else if (rsi <= 30) {
      return {
        condition: `RSI(14) = ${rsi} (< 30 Bearish Oversold)`,
        verdict: "Bad",
      };
    } else {
      return {
        condition: `RSI(14) = ${rsi} (< 45 Downward Momentum)`,
        verdict: "Bad",
      };
    }
  }

  // 4. YoY Growth (Revenue, PAT, EPS, EBITDA)
  const growthMatch = interp.match(/(Revenue|PAT|EPS|EBITDA)\s+(grew|declined)\s+([+-]?\d+\.?\d*)%\s+year-over-year/i);
  if (growthMatch) {
    const label = growthMatch[1];
    const val = parseFloat(growthMatch[3]);
    if (val >= 15) {
      return {
        condition: `${label} Growth YoY = ${growthMatch[3]}% (> 15% Strong Expansion)`,
        verdict: "Good",
      };
    } else if (val > 0) {
      return {
        condition: `${label} Growth YoY = ${growthMatch[3]}% (> 0% Positive Growth)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `${label} Growth YoY = ${growthMatch[3]}% (< 0% Contraction)`,
        verdict: "Bad",
      };
    }
  }

  // 5. Price vs Moving Averages (50 DMA, 200 DMA, 20 EMA)
  const maMatch = interp.match(/Price\s+is\s+(\d+\.?\d*)%\s+(above|below)\s+the\s+([^,]+)/i);
  if (maMatch) {
    const pct = maMatch[1];
    const dir = maMatch[2].toLowerCase();
    const ma = maMatch[3].trim();
    if (dir === "above") {
      return {
        condition: `Price > ${ma} (+${pct}% above trend line)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `Price < ${ma} (-${pct}% below trend line)`,
        verdict: "Bad",
      };
    }
  }

  // 6. Moving Average Crosses (Golden Cross / Death Cross)
  const crossMatch = interp.match(/([0-9A-Z\s]+?)\s+is\s+(above|below)\s+the\s+([0-9A-Z\s]+?)\s+\(([+-]?\d+\.?\d*)%/i);
  if (crossMatch) {
    const fast = crossMatch[1].trim();
    const dir = crossMatch[2].toLowerCase();
    const slow = crossMatch[3].trim();
    const pct = crossMatch[4];
    if (dir === "above") {
      return {
        condition: `${fast} > ${slow} (${pct}%, Golden Cross)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `${fast} < ${slow} (${pct}%, Death Cross)`,
        verdict: "Bad",
      };
    }
  }

  // 7. Breakout / Breakdown (20-day)
  if (metric === "breakout_20d" || interp.includes("20-day high (breakout)")) {
    return {
      condition: "Price broke 20-Day High (Fresh Breakout)",
      verdict: "Good",
    };
  }
  if (metric === "breakdown_20d" || interp.includes("20-day low (breakdown)")) {
    return {
      condition: "Price broke 20-Day Low (Support Breakdown)",
      verdict: "Bad",
    };
  }

  // 8. ADX(14)
  const adxMatch = interp.match(/ADX\(14\)\s+is\s+(\d+\.?\d*)/i);
  if (adxMatch) {
    const adx = parseFloat(adxMatch[1]);
    if (adx >= 25) {
      return {
        condition: `ADX(14) = ${adx} (≥ 25 Strong Trend Strength)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `ADX(14) = ${adx} (< 15 Weak Trend / Choppy)`,
        verdict: "Bad",
      };
    }
  }

  // 9. MACD Histogram
  const macdMatch = interp.match(/MACD\s+histogram\s+is\s+(positive|negative)\s*\(([+-]?\d+\.?\d*)\)/i);
  if (macdMatch) {
    const sign = macdMatch[1].toLowerCase();
    const val = macdMatch[2];
    if (sign === "positive") {
      return {
        condition: `MACD Histogram > 0 (+${val} Bullish Momentum)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `MACD Histogram < 0 (${val} Bearish Momentum)`,
        verdict: "Bad",
      };
    }
  }

  // 10. Rate of Change (ROC 12)
  const rocMatch = interp.match(/12-period\s+rate\s+of\s+change\s+is\s+([+-]?\d+\.?\d*)%/i);
  if (rocMatch) {
    const roc = parseFloat(rocMatch[1]);
    return {
      condition: `12-Period ROC = ${rocMatch[1]}% (${roc > 0 ? "> 0% Positive Momentum" : "< 0% Negative Momentum"})`,
      verdict: roc > 0 ? "Good" : "Bad",
    };
  }

  // 11. Stochastic %K
  const stochMatch = interp.match(/Stochastic\s+%K\s+is\s+(\d+\.?\d*)/i);
  if (stochMatch) {
    const k = parseFloat(stochMatch[1]);
    if (k > 80) {
      return {
        condition: `Stochastic %K = ${k} (> 80 Strong Momentum Range)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `Stochastic %K = ${k} (< 20 Weak Momentum Range)`,
        verdict: "Bad",
      };
    }
  }

  // 12. Profitability (ROE, Simplified ROCE, ROA)
  const profMatch = interp.match(/(ROE|Simplified ROCE|ROA)\s+is\s+(\d+\.?\d*)%/i);
  if (profMatch) {
    const label = profMatch[1];
    const val = parseFloat(profMatch[2]);
    if (label.toUpperCase() === "ROA") {
      return {
        condition: `ROA = ${val}% (${val >= 3.0 ? "≥ 3.0% Healthy" : "< 3.0% Low Return"})`,
        verdict: val >= 3.0 ? "Good" : "Bad",
      };
    } else {
      return {
        condition: `${label} = ${val}% (${val >= 12.0 ? "> 12% High Return" : val >= 8.0 ? "≥ 8% Healthy" : "< 8% Low Return"})`,
        verdict: val >= 8.0 ? "Good" : "Bad",
      };
    }
  }

  // 13. Net Profit Margin
  const marginMatch = interp.match(/Net\s+profit\s+margin\s+is\s+(\d+\.?\d*)%/i);
  if (marginMatch) {
    const val = parseFloat(marginMatch[1]);
    return {
      condition: `Net Margin = ${val}% (${val >= 15 ? "> 15% Strong Profitability" : val >= 5 ? "≥ 5% Positive" : "< 5% Low Margin"})`,
      verdict: val >= 5 ? "Good" : "Bad",
    };
  }

  // 14. Debt to Equity
  const deMatch = interp.match(/Debt\/Equity\s+is\s+(\d+\.?\d*)x/i);
  if (deMatch) {
    const de = parseFloat(deMatch[1]);
    if (de < 0.6) {
      return {
        condition: `Debt/Equity = ${de}x (< 0.6x Conservative Leverage)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `Debt/Equity = ${de}x (≥ 1.0x Elevated Debt Load)`,
        verdict: "Bad",
      };
    }
  }

  // 15. Net Debt to EBITDA
  const ndMatch = interp.match(/Net\s+Debt\/EBITDA\s+is\s+(\d+\.?\d*)x/i);
  if (ndMatch) {
    const val = parseFloat(ndMatch[1]);
    return {
      condition: `Net Debt/EBITDA = ${val}x (${val < 2.0 ? "< 2.0x Safe Leverage" : "≥ 3.5x Elevated Debt"})`,
      verdict: val < 2.0 ? "Good" : "Bad",
    };
  }

  // 16. Interest Coverage
  const icMatch = interp.match(/Interest\s+coverage\s+is\s+(\d+\.?\d*)x/i);
  if (icMatch) {
    const val = parseFloat(icMatch[1]);
    return {
      condition: `Interest Coverage = ${val}x (${val >= 4.0 ? "≥ 4.0x Safe Cushion" : "< 1.5x Strained Coverage"})`,
      verdict: val >= 4.0 ? "Good" : "Bad",
    };
  }

  // 17. Current Ratio
  const crMatch = interp.match(/Current\s+ratio\s+is\s+(\d+\.?\d*)x/i);
  if (crMatch) {
    const val = parseFloat(crMatch[1]);
    return {
      condition: `Current Ratio = ${val}x (${val >= 1.2 ? "≥ 1.2x Healthy Liquidity" : "< 1.0x Liquidity Deficit"})`,
      verdict: val >= 1.2 ? "Good" : "Bad",
    };
  }

  // 18. Asset Turnover
  const atMatch = interp.match(/Asset\s+turnover\s+is\s+(\d+\.?\d*)x/i);
  if (atMatch) {
    const val = parseFloat(atMatch[1]);
    if (val >= 0.5) {
      return {
        condition: `Asset Turnover = ${val}x (≥ 0.5x Efficient Asset Use)`,
        verdict: "Good",
      };
    } else {
      return {
        condition: `Asset Turnover = ${val}x (< 0.5x Low Asset Productivity)`,
        verdict: "Bad",
      };
    }
  }

  // 19. Rolling Volatility (20D)
  const volMatch = interp.match(/20-day\s+annualized\s+volatility\s+is\s+(\d+\.?\d*)%/i);
  if (volMatch) {
    const val = parseFloat(volMatch[1]);
    if (val > 35) {
      return {
        condition: `20D Volatility = ${val}% (> 35% Elevated Turbulence)`,
        verdict: "Bad",
      };
    } else {
      return {
        condition: `20D Volatility = ${val}% (< 20% Calm Price Action)`,
        verdict: "Good",
      };
    }
  }

  // 20. ATR % of Price
  const atrMatch = interp.match(/ATR\s+is\s+(\d+\.?\d*)%\s+of\s+price/i);
  if (atrMatch) {
    const val = parseFloat(atrMatch[1]);
    if (val >= 3.0) {
      return {
        condition: `ATR = ${val}% of price (≥ 3.0% Volatility Noise)`,
        verdict: "Bad",
      };
    } else {
      return {
        condition: `ATR = ${val}% of price (< 1.5% Tight Daily Swings)`,
        verdict: "Good",
      };
    }
  }

  // 21. Max Drawdown
  const ddMatch = interp.match(/Max\s+drawdown\s+over\s+available\s+history\s+is\s+([+-]?\d+\.?\d*)%/i);
  if (ddMatch) {
    const val = parseFloat(ddMatch[1]);
    if (Math.abs(val) > 30) {
      return {
        condition: `Max Drawdown = ${val}% (> 30% Deep Historical Decline)`,
        verdict: "Bad",
      };
    } else {
      return {
        condition: `Max Drawdown = ${val}% (< 15% Shallow Drawdown)`,
        verdict: "Good",
      };
    }
  }

  // 22. Market Regime
  const regMatch = interp.match(/The\s+broader\s+market\s+regime\s+is\s+([A-Z_]+)/i);
  if (regMatch) {
    const reg = regMatch[1];
    if (reg === "BULLISH_TREND") {
      return {
        condition: "Market Regime = BULLISH_TREND (Broad Market Tailwind)",
        verdict: "Good",
      };
    } else if (reg === "BEARISH_TREND") {
      return {
        condition: "Market Regime = BEARISH_TREND (Broad Market Headwind)",
        verdict: "Bad",
      };
    } else {
      return {
        condition: `Market Regime = ${reg} (Market Consolidation)`,
        verdict: tone === "up" ? "Good" : "Bad",
      };
    }
  }

  // Fallback: extract the first clause before dash / parens
  const firstClause = interp.split(" - ")[0].split("(")[0].trim();
  return {
    condition: firstClause || metric,
    verdict: tone === "up" ? "Good" : "Bad",
  };
}
