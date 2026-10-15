import pandas as pd
import numpy as np
from scipy.signal import find_peaks

def evaluate_vcp(df: pd.DataFrame) -> dict:
    if len(df) < 260:
        return {"is_vcp_setup": False, "reason": "Insufficient data (needs 260 days)"}
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values
    
    sma_50 = df['close'].rolling(50).mean().values
    sma_150 = df['close'].rolling(150).mean().values
    sma_200 = df['close'].rolling(200).mean().values
    vol_50_sma = df['volume'].rolling(50).mean().values
    
    high_52w = df['high'].rolling(260).max().values
    low_52w = df['low'].rolling(260).min().values
    
    c = close[-1]
    s50 = sma_50[-1]
    s150 = sma_150[-1]
    s200 = sma_200[-1]
    s200_20ago = sma_200[-21] if len(sma_200) >= 21 else 0
    h52 = high_52w[-1]
    l52 = low_52w[-1]
    
    # Step 1: Pre-requisite Filter - Minervini Trend Template
    if not (c > s150 and c > s200): return {"is_vcp_setup": False, "reason": "Close not above 150/200 SMA"}
    if not (s150 > s200): return {"is_vcp_setup": False, "reason": "150 SMA not above 200 SMA"}
    if not (s200 > s200_20ago): return {"is_vcp_setup": False, "reason": "200 SMA not trending up"}
    if not (s50 > s150 and s50 > s200): return {"is_vcp_setup": False, "reason": "50 SMA not above 150/200 SMA"}
    if not (c >= 0.75 * h52): return {"is_vcp_setup": False, "reason": "Close not within 25% of 52w high"}
    if not (c >= 1.30 * l52): return {"is_vcp_setup": False, "reason": "Close not >= 30% above 52w low"}
    
    # Step 2: Base Identification
    base_window = min(120, len(df))
    recent_highs = high[-base_window:]
    recent_lows = low[-base_window:]
    
    peaks, _ = find_peaks(recent_highs, distance=5)
    troughs, _ = find_peaks(-recent_lows, distance=5)
    
    if len(peaks) < 2 or len(troughs) < 2:
        return {"is_vcp_setup": False, "reason": "Not enough swings detected"}
        
    base_high_idx = np.argmax(recent_highs[peaks])
    valid_peaks = peaks[base_high_idx:]
    valid_troughs = [t for t in troughs if t > valid_peaks[0]]
    
    if len(valid_peaks) < 2 or len(valid_troughs) < 1:
        return {"is_vcp_setup": False, "reason": "Invalid swing structure after base high"}
        
    depths = []
    for i in range(min(len(valid_peaks), len(valid_troughs))):
        p_val = recent_highs[valid_peaks[i]]
        t_val = recent_lows[valid_troughs[i]]
        depths.append((p_val - t_val) / p_val)
        
    # Step 3: Strict Contraction Conditions
    n = len(depths)
    if not (2 <= n <= 4):
        return {"is_vcp_setup": False, "reason": f"Invalid number of contractions ({n})"}
        
    for i in range(1, n):
        if depths[i] >= depths[i-1] + 0.01:
            return {"is_vcp_setup": False, "reason": "Contractions not diminishing"}
            
    if depths[0] > 0.35:
        return {"is_vcp_setup": False, "reason": "First contraction > 35%"}
        
    if depths[-1] > 0.08:
        return {"is_vcp_setup": False, "reason": "Final contraction > 8%"}
        
    final_peak_val = recent_highs[valid_peaks[-1]]
    if not (0.95 * final_peak_val <= c <= 1.03 * final_peak_val):
        return {"is_vcp_setup": False, "reason": "Price not near pivot"}
        
    # Step 4: Volume Signatures
    v50 = vol_50_sma[-1]
    last_5_days_vol = np.mean(volume[-5:])
    vdu_flag = last_5_days_vol < 0.70 * v50
    if not vdu_flag:
        return {"is_vcp_setup": False, "reason": "No volume dry-up"}
        
    stop_loss = recent_lows[valid_troughs[-1]]
    risk = (c - stop_loss) / c
    
    return {
        "is_vcp_setup": True,
        "pivot_price": float(final_peak_val),
        "stop_loss_price": float(stop_loss),
        "risk_reward_pct": float(risk),
        "num_contractions": int(n),
        "contractions_depth": [float(d) for d in depths],
        "vdu_flag": bool(vdu_flag),
        "reason": "VCP setup valid"
    }
