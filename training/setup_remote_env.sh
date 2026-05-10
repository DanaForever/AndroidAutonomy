#!/usr/bin/env bash
# Set up the training env on the remote.
#
# Run this ONCE on the remote box, **in an interactive session that has a GPU
# visible** (so flash-attn / vLLM compile-time probes find CUDA correctly).
#
# Usage (on remote):
#     cd path/to/AndroidAutonomy
#     bash training/setup_remote_env.sh
#
# Time: ~15-30 min, mostly vLLM 0.11.0 + flash-attn wheel install.
# Disk: ~10-15 GB in conda env + caches.

# Path-based env on lustre scratch (keeps env off home volume / shared envs dir).
ENV_PREFIX=${ENV_PREFIX:-/lustre/scratch/client/movian/research/users/thivt1/conda/verl}
PYVER=${PYVER:-3.12}

# Cluster-specific module loads, if any. Comment in/out as needed.
# module load cuda/12.4
# module load gcc/11.4

if ! command -v conda >/dev/null; then
    echo "[setup] conda not on PATH — install miniconda or load the cluster's conda module first." >&2
    exit 1
fi

# 1. Create conda env at the lustre prefix (idempotent).
if [[ ! -d "$ENV_PREFIX" ]]; then
    mkdir -p "$(dirname "$ENV_PREFIX")"
    conda create -p "$ENV_PREFIX" "python=$PYVER" -y
fi
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_PREFIX"

python --version
which python

# 2. Sanity: GPU + CUDA visible.
nvidia-smi || { echo "[setup] no nvidia-smi — request a GPU node before running." >&2; exit 1; }

# 3. verl's official install script.
#    USE_MEGATRON=0 → skip TransformerEngine + Megatron-LM (FSDP only).
#    USE_SGLANG=0   → use vLLM as the rollout backend (matches eval pipeline).
pushd training/verl >/dev/null
USE_MEGATRON=0 USE_SGLANG=0 bash scripts/install_vllm_sglang_mcore.sh
popd >/dev/null

# 4. Editable install of verl itself.
pip install -e ./training/verl

# 5. Light deps for our local helper scripts (in case we ever rebuild data here).
pip install pyarrow pyyaml pillow matplotlib tqdm

# 6. Verify the stack imports cleanly.
python - <<'PY'
import sys
import torch
import transformers
import vllm
from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset  # noqa: F401
print("python      :", sys.version.split()[0])
print("torch       :", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
print("gpu count   :", torch.cuda.device_count())
print("transformers:", transformers.__version__)
print("vllm        :", vllm.__version__)
print("verl SFT dataset import: OK")
PY

# 7. Pre-download the model weights + processor at the pinned revision, so the
#    smoke test and the SFT trainer don't race on first download.
python - <<'PY'
from huggingface_hub import snapshot_download
HF_MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
HF_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
path = snapshot_download(repo_id=HF_MODEL_ID, revision=HF_REVISION)
print("model cached at:", path)
PY

# 8. Smoke-test the parquet through verl's collator (only if it's been pushed).
PARQUET=training/data/sft_v0/train.parquet
if [[ -f "$PARQUET" ]]; then
    python - <<PY
import sys, importlib.util
spec = importlib.util.spec_from_file_location("build", "training/data/build_sft_v0.py")
mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
from pathlib import Path
ok = mod.smoke_test(Path("$PARQUET"))
sys.exit(0 if ok else 1)
PY
else
    echo "[setup] $PARQUET missing — push the dataset first, then run:"
    echo "        python -c \"import sys, importlib.util as u; m=u.module_from_spec(s:=u.spec_from_file_location('b','training/data/build_sft_v0.py')); sys.modules[s.name]=m; s.loader.exec_module(m); from pathlib import Path; assert m.smoke_test(Path('training/data/sft_v0/train.parquet'))\""
fi

echo "[setup] DONE — env at '$ENV_PREFIX' ready."
echo "[setup] activate later with: conda activate $ENV_PREFIX"
