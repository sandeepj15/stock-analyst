import os
import time
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from packages.kronos.kronos import Kronos, KronosTokenizer
except ImportError:
    print("Kronos modules not found. Ensure torch and kronos are installed.")
    exit(1)

BATCH_SIZE = 2
GRADIENT_ACCUMULATION_STEPS = 8
EPOCHS = 3
CONTEXT_LENGTH = 128
LEARNING_RATE = 1e-4

class NSETrainingDataset(Dataset):
    def __init__(self, df, seq_len=512):
        self.seq_len = seq_len
        self.samples = []
        for symbol, group in df.groupby("symbol"):
            group = group.sort_values("timestamps")
            prices = group[['open', 'high', 'low', 'close', 'volume', 'amount']].values
            for i in range(len(prices) - seq_len):
                self.samples.append(prices[i:i+seq_len])
                
    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        return torch.tensor(self.samples[idx], dtype=torch.float32)

def main():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Using device: {device}")
    
    print("Loading data...")
    df = pd.read_csv("packages/kronos/data/nse_top150_ohlcv.csv")
    dataset = NSETrainingDataset(df, seq_len=CONTEXT_LENGTH)
    dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)
    
    print(f"Dataset created with {len(dataset)} sequences.")
    
    print("Loading Kronos models...")
    tokenizer = KronosTokenizer.from_pretrained("packages/kronos/weights/tokenizer_base").to(device)
    model = Kronos.from_pretrained("packages/kronos/weights/kronos_small").to(device)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    loss_fct = nn.CrossEntropyLoss()
    
    print("Starting strategic fine-tuning (with thermal pacing)...")
    
    model.train()
    tokenizer.eval() 
    
    for epoch in range(EPOCHS):
        print(f"\n--- Epoch {epoch+1}/{EPOCHS} ---")
        optimizer.zero_grad()
        
        for step, batch in enumerate(dataloader):
            batch = batch.to(device)
            
            with torch.no_grad():
                s1, s2 = tokenizer.encode(batch, half=True)
                
            s1_logits, s2_logits = model(s1_ids=s1, s2_ids=s2)
            
            s1_shift_logits = s1_logits[:, :-1, :].reshape(-1, s1_logits.size(-1))
            s2_shift_logits = s2_logits[:, :-1, :].reshape(-1, s2_logits.size(-1))
            
            s1_shift_labels = s1[:, 1:].reshape(-1)
            s2_shift_labels = s2[:, 1:].reshape(-1)
            
            loss_s1 = loss_fct(s1_shift_logits, s1_shift_labels)
            loss_s2 = loss_fct(s2_shift_logits, s2_shift_labels)
            loss = (loss_s1 + loss_s2) / GRADIENT_ACCUMULATION_STEPS
            
            loss.backward()
            
            if (step + 1) % GRADIENT_ACCUMULATION_STEPS == 0:
                optimizer.step()
                optimizer.zero_grad()
                time.sleep(1.0) 
            
            if step % 50 == 0:
                print(f"Epoch {epoch+1} | Step {step}/{len(dataloader)} | Loss: {loss.item() * GRADIENT_ACCUMULATION_STEPS:.4f}")
                
    print("\nTraining complete! Saving weights...")
    os.makedirs("packages/kronos/weights/kronos_nse_finetuned", exist_ok=True)
    model.save_pretrained("packages/kronos/weights/kronos_nse_finetuned")
    print("Saved to packages/kronos/weights/kronos_nse_finetuned")

if __name__ == "__main__":
    main()
