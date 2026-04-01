from huggingface_hub import snapshot_download
import os

os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

snapshot_download(
    repo_id="Tongyi-MAI/MAI-UI-8B",
    local_dir=None,          # goes to HF cache
    max_workers=1,           # IMPORTANT → sequential
    resume_download=True,
)
