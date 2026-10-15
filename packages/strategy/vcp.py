import pandas as pd
import numpy as np
from scipy.signal import find_peaks

def evaluate_vcp(df: pd.DataFrame) -> dict:
    """
    Evaluates the VCP (Volatility Contraction Pattern) setup for a single instrument's historical dataframe.
    Expects df to be sorted chronologically with columns: 'date', 'open', 'high', 'low', 'close', 'volume'
    """
    if df is None or len(df) < 260:
        return {"is_vcp_setup": False, "reason": "Insufficient history (< 260 days)"}
    
    # 1. Pre-requisite Filter — Minervini Trend Template
    last_idx = len(df) - 1
    
    # Calculate rolling metrics
    close_series = df['close']
    high_series = df['high']
    low_series = df['low']
    vol_series = df['volume']
    
    sma_50 = close_series.rolling(50).mean().iloc[last_idx]
    sma_150 = close_series.rolling(150).mean().iloc[last_idx]
    sma_200 = close_series.rolling(200).mean().iloc[last_idx]
    sma_200_20d_ago = close_series.rolling(200).mean().shift(20).iloc[last_idx]
    
    high_52w = high_series.rolling(260).max().iloc[last_idx]
    low_52w = low_series.rolling(260).min().iloc[last_idx]
    
    curr_close = close_series.iloc[last_idx]
    
    # Check conditions
    if pd.isna(sma_200_20d_ago):
        return {"is_vcp_setup": False, "reason": "NaN in SMA calculations"}
        
    if not (curr_close > sma_150 and curr_close > sma_200):
        return {"is_vcp_setup": False, "reason": "Close not above SMA150 & SMA200"}
    if not (sma_150 > sma_200):
        return {"is_vcp_setup": False, "reason": "SMA150 not above SMA200"}
    if not (sma_200 > sma_200_20d_ago):
        return {"is_vcp_setup": False, "reason": "SMA200 not trending up"}
    if not (sma_50 > sma_150 and sma_50 > sma_200):
        return {"is_vcp_setup": False, "reason": "SMA50 not above SMA150 & SMA200"}
    if not (curr_close >= 0.75 * high_52w):
        return {"is_vcp_setup": False, "reason": "Close not within 25% of 52w high"}
    if not (curr_close >= 1.30 * low_52w):
        return {"is_vcp_setup": False, "reason": "Close not 30% above 52w low"}
        
    # 2. Base Identification & Swing Peak/Trough Detection
    lookback_window = min(120, len(df))
    base_df = df.iloc[-lookback_window:].copy()
    base_high_prices = base_df['high'].values
    base_low_prices = base_df['low'].values
    
    # Detect peaks and troughs using scipy find_peaks
    # distance=5 implies at least 5 trading bars between peaks
    peaks, _ = find_peaks(base_high_prices, distance=5)
    troughs, _ = find_peaks(-base_low_prices, distance=5)
    
    if len(peaks) < 1 or len(troughs) < 1:
        return {"is_vcp_setup": False, "reason": "Insufficient swing points"}
        
    # We trace from the highest peak in the window down to current date
    highest_peak_idx = peaks[np.argmax(base_high_prices[peaks])]
    
    # Filter peaks and troughs that occur AFTER the highest peak
    valid_peaks = [p for p in peaks if p >= highest_peak_idx]
    valid_troughs = [t for t in troughs if t > highest_peak_idx]
    
    if len(valid_peaks) < 2 or len(valid_troughs) < 2:
        return {"is_vcp_setup": False, "reason": "Insufficient valid swings after base high"}
        
    # Pair peaks to subsequent troughs
    contractions = []
    # Simplified approach: for each peak, find the lowest trough before the next peak
    for i in range(len(valid_peaks)):
        p_idx = valid_peaks[i]
        next_p_idx = valid_peaks[i+1] if i + 1 < len(valid_peaks) else len(base_df)
        
        # Find all troughs between p_idx and next_p_idx
        t_between = [t for t in valid_troughs if p_idx < t < next_p_idx]
        if not t_between:
            continue
            
        t_idx = t_between[np.argmin(base_low_prices[t_between])]
        peak_val = base_high_prices[p_idx]
        trough_val = base_low_prices[t_idx]
        
        depth = (peak_val - trough_val) / peak_val
        contractions.append({
            'peak_idx': p_idx,
            'trough_idx': t_idx,
            'peak': peak_val,
            'trough': trough_val,
            'depth': depth
        })
        
    num_c = len(contractions)
    
    # 3. Strict Contraction Conditions
    if not (2 <= num_c <= 4):
        return {"is_vcp_setup": False, "reason": f"Invalid number of contractions ({num_c})"}
        
    depths = [c['depth'] for c in contractions]
    
    # Strictly diminishing depth (allow 1% tolerance)
    for i in range(1, num_c):
        if depths[i] > depths[i-1] + 0.01:
            return {"is_vcp_setup": False, "reason": "Contractions are not diminishing"}
            
    if depths[0] > 0.35:
        return {"is_vcp_setup": False, "reason": "First contraction depth exceeds 35%"}
        
    if depths[-1] > 0.08:
        return {"is_vcp_setup": False, "reason": "Final contraction depth exceeds 8%"}
        
    final_c = contractions[-1]
    pivot_price = final_c['peak']
    stop_loss_price = final_c['trough']
    
    # Check if price in final 3-7 days is within 5% of pivot resistance
    recent_max = base_df['high'].iloc[-7:].max()
    if recent_max > pivot_price * 1.05 or curr_close < pivot_price * 0.95:
        # Relaxing slightly to 5% tolerance as requested (within 3% to 5%)
        # Just checking if close is near pivot
        pass # Actually strict rule: trade within 3% to 5% of pivot
        
    if curr_close > pivot_price * 1.05 or curr_close < pivot_price * 0.95:
        return {"is_vcp_setup": False, "reason": "Current price not within 5% of pivot"}
        
    # 4. Volume Signatures
    vol_50_sma = vol_series.rolling(50).mean().iloc[last_idx]
    last_5_days_vol = vol_series.iloc[-5:].mean()
    
    vdu_flag = last_5_days_vol < 0.70 * vol_50_sma
    
    if not vdu_flag:
        return {"is_vcp_setup": False, "reason": "No Volume Dry-Up (VDU) in final contraction"}
        
    risk_reward_pct = (curr_close - stop_loss_price) / curr_close * 100.0
    
    return {
        "is_vcp_setup": True,
        "pivot_price": float(pivot_price),
        "stop_loss_price": float(stop_loss_price),
        "risk_reward_pct": float(risk_reward_pct),
        "num_contractions": int(num_c),
        "contractions_depth": [float(d) for d in depths],
        "vdu_flag": bool(vdu_flag),
        "reason": None
    }
