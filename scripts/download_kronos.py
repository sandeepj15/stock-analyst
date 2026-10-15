import os
from huggingface_hub import snapshot_download

def download_models():
    print("Downloading Kronos-Tokenizer-base...")
    snapshot_download(
        repo_id="NeoQuasar/Kronos-Tokenizer-base",
        local_dir="packages/kronos/weights/tokenizer_base",
        ignore_patterns=["*.msgpack", "*.h5", "*.ot"]
    )
    
    print("Downloading Kronos-small...")
    snapshot_download(
        repo_id="NeoQuasar/Kronos-small",
        local_dir="packages/kronos/weights/kronos_small",
        ignore_patterns=["*.msgpack", "*.h5", "*.ot"]
    )
    print("Download complete.")

if __name__ == "__main__":
    download_models()
