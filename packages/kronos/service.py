import os
import pandas as pd
from typing import Dict, Any, Optional

try:
    from packages.kronos.kronos import Kronos, KronosTokenizer, KronosPredictor
except ImportError:
    # Handle if dependencies aren't installed yet
    Kronos = None
    KronosTokenizer = None
    KronosPredictor = None

class KronosService:
    def __init__(self, use_small_model: bool = True):
        self._predictor = None
        self._tokenizer_path = "packages/kronos/weights/tokenizer_base"
        self._model_path = "packages/kronos/weights/kronos_nse_finetuned" if use_small_model else "packages/kronos/weights/kronos_base"
        
    def _lazy_load(self):
        if self._predictor is not None:
            return
        
        if not Kronos:
            raise RuntimeError("Kronos dependencies (torch, etc.) are not installed or Kronos models not found.")
            
        tokenizer = KronosTokenizer.from_pretrained(self._tokenizer_path)
        model = Kronos.from_pretrained(self._model_path)
        
        # Move model to CPU or GPU automatically
        import torch
        device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
        model = model.to(device)
        
        self._predictor = KronosPredictor(model, tokenizer, max_context=512)
        
    def predict_forward(self, ohlcv_df: pd.DataFrame, pred_len: int = 5) -> Optional[pd.DataFrame]:
        """
        Takes a dataframe with ['timestamps', 'open', 'high', 'low', 'close', 'volume']
        Returns a dataframe with forecasted points of length `pred_len`.
        """
        if ohlcv_df.empty or len(ohlcv_df) < 10:
            return None
            
        self._lazy_load()
        
        # Ensure timestamp is datetime
        ohlcv_df['timestamps'] = pd.to_datetime(ohlcv_df['timestamps'])
        
        # Only take up to max_context
        lookback = min(len(ohlcv_df), 512)
        df_context = ohlcv_df.tail(lookback).reset_index(drop=True)
        
        x_df = df_context[['open', 'high', 'low', 'close', 'volume']].copy()
        # Add dummy amount if missing, since model expects it sometimes or handles volume zeros
        if 'amount' not in x_df.columns:
            x_df['amount'] = 0.0
            
        x_timestamp = df_context['timestamps']
        
        # Generate future timestamps (skipping weekends roughly, or just calendar days)
        last_date = x_timestamp.iloc[-1]
        future_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=pred_len, freq='B')
        
        pred_df = self._predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=pd.Series(future_dates),
            pred_len=pred_len,
            T=0.1,
            top_p=0.9,
            sample_count=1,
            verbose=False
        )
        
        # Predictor returns DataFrame with predictions
        pred_df['timestamps'] = future_dates
        return pred_df
