# SFT Training Setup Guide

This guide covers SFT training of Qwen3-VL-4B-Instruct on the current AndroidWorld SFT parquet using the vendored [verl](verl/) trainer.

## Architecture Overview

This workflow has two roles. The **training box** owns the GPUs, runs verl with FSDP, and writes checkpoints to local disk. A separate **inference box** (out of scope here — see [`MARS-Voyager/SETUP_GUIDE.md`](../MARS-Voyager/SETUP_GUIDE.md)) later loads the merged HuggingFace checkpoint into vLLM for AndroidWorld eval. Train here, ship the HF checkpoint over, serve there.

---

## Part 1: Environment Setup

verl v0.7.1 needs Python 3.12, CUDA 12.x, and a specific torch/vLLM stack. Use a fresh conda env — do not mix with `uivoyager` or `vllm`.

### Step 1: Create the conda environment

```bash
conda create -n verl python=3.12 -y
conda activate verl
```

### Step 2: Clone verl at the pinned commit

The [`training/verl/`](verl/) directory is gitignored. Re-clone it at the pin from [`PINS.md`](PINS.md):

```bash
git clone --depth 1 --branch v0.7.1 https://github.com/volcengine/verl.git training/verl
git -C training/verl rev-parse HEAD  # expect bec9ef74768dd201881cd4e54cd0385e87caae27
```

### Step 3: Install verl and its CUDA stack

verl ships an install script that resolves torch, vLLM, and flash-attn together. Run it from inside the verl tree:

```bash
pushd training/verl
USE_MEGATRON=0 USE_SGLANG=0 bash scripts/install_vllm_sglang_mcore.sh
popd
pip install -e ./training/verl
pip install 'transformers==4.57.3' pyarrow pyyaml pillow tqdm wandb
```

**Parameter explanation:**
- `USE_MEGATRON=0`: skip TransformerEngine and Megatron-LM — we use FSDP, not 3D parallelism.
- `USE_SGLANG=0`: install vLLM as the rollout backend (matches the eval pipeline). Not used by SFT directly but is a required dep.
- `transformers==4.57.3`: pinned per [`PINS.md`](PINS.md). Earlier 4.57.x crashes verl's FSDP2 wrap because `_no_split_modules` is a `set` instead of a `list`.

If a GPU node is available, [`setup_remote_env.sh`](setup_remote_env.sh) automates steps 1, 3, and pre-downloads the model. Use it on the remote box.

### Step 4: Pre-download the base model

Pin the HF revision so the trainer never picks up a different snapshot via cache:

```bash
python -c "from huggingface_hub import snapshot_download; \
  snapshot_download(repo_id='Qwen/Qwen3-VL-4B-Instruct', \
  revision='ebb281ec70b05090aa6165b016eac8ec08e71b17')"
```

### Step 5: Verify the stack imports

```bash
python -c "import torch, transformers, vllm; \
  from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset; \
  print(torch.__version__, transformers.__version__, vllm.__version__, torch.cuda.device_count())"
```

You should see torch 2.x with CUDA, transformers 4.57.3, vLLM 0.11.x, and a non-zero GPU count.

---

## Part 2: Sync and Verify the Dataset

Training datasets are generated artifacts and are intentionally not committed to Git. The current ready-to-train dataset is:

```text
training/data/sft_overfit_failed_v0.1/train.parquet
training/data/sft_overfit_failed_v0.1/val.parquet
```

From this machine, sync the dataset directory to the new training machine after cloning the branch:

```bash
rsync -av training/data/sft_overfit_failed_v0.1/ <remote>:/path/to/AndroidAutonomy/training/data/sft_overfit_failed_v0.1/
```

Schema and provenance are documented in [`data/sft_overfit_failed_v0.1/README.md`](data/sft_overfit_failed_v0.1/README.md). Verify the files exist and have the expected row counts:

```bash
python -c "import pyarrow.parquet as pq; \
  t = pq.read_table('training/data/sft_overfit_failed_v0.1/train.parquet'); \
  v = pq.read_table('training/data/sft_overfit_failed_v0.1/val.parquet'); \
  print('train:', t.num_rows, 'val:', v.num_rows); \
  print('cols:', t.column_names)"
```

Expected columns include `messages, images, goal, history, image_path, assistant_response, template_id, task_name, repeat_id, instance_idx, step_index, source_run_id`.

Inspect one row to confirm the verl SFT layout (string `content`, `<image>` placeholder, one PNG in `images`):

```bash
python -c "import pyarrow.parquet as pq; \
  r = pq.read_table('training/data/sft_overfit_failed_v0.1/train.parquet').slice(0,1).to_pylist()[0]; \
  print('roles:', [m['role'] for m in r['messages']]); \
  print('user[:200]:', r['messages'][1]['content'][:200]); \
  print('n_images:', len(r['images']))"
```

---

## Part 3: Configure SFT

verl SFT is configured by hydra overrides on the command line, not a standalone YAML. The current launch script lives at [`scripts/run_sft_overfit_failed.sh`](scripts/run_sft_overfit_failed.sh). It is derived from verl's stock VLM recipe at [`verl/examples/sft/vlm/run_qwen3_vl_2b.sh`](verl/examples/sft/vlm/run_qwen3_vl_2b.sh).

Key fields to review before launch:

- `data.train_files` / `data.val_files`: parquet paths — the current launch script uses [`data/sft_overfit_failed_v0.1/train.parquet`](data/sft_overfit_failed_v0.1/train.parquet) and [`val.parquet`](data/sft_overfit_failed_v0.1/val.parquet).
- `data.train_batch_size=32`: global batch across all GPUs. The 2B recipe uses 96; 4B needs more activation memory so we drop to 32.
- `data.max_length=8192`: per-row token cap. Long screenshots can push past 4k; 8k leaves headroom.
- `data.max_token_len_per_gpu=16384`: dynamic-batching cap per GPU. The 2B recipe uses 65536; 4B halves the per-step memory budget at the same value, so we drop to 16k.
- `model.path`: resolved snapshot path under `$HF_HOME` at the pinned revision.
- `model.enable_gradient_checkpointing=true`: required for 4B at 8k context on A100 80GB.
- `optim.lr=2e-5`, `optim.warmup_style=cosine`, `optim.lr_warmup_steps_ratio=0.03`: standard SFT schedule.
- `trainer.total_epochs=3`: with ~2.3k rows and global batch 32, this is ~210 steps. Enough to see overfit on 10 tasks; bump up if the val curve is still falling.
- `trainer.test_freq=50`, `trainer.save_freq=200`: val-loss eval every 50 steps, checkpoint every 200.
- `trainer.default_local_dir`: `training/checkpoints/<EXP_NAME>` by default; override via `CKPT_HOME`.
- `engine.ulysses_sequence_parallel_size`: kept at 1 for 4 GPUs; bump to 2 on 8 GPUs if context length pushes activation memory.

Edit the script in place when these need tuning.

---

## Part 4: Launch Training

Use [`scripts/run_sft_overfit_failed.sh`](scripts/run_sft_overfit_failed.sh) for the current ready dataset. The script assumes **8 GPUs by default** and falls back to `SP_SIZE=1` when `NUM_TRAINERS<=4`. verl uses `torchrun` (invoked via `python -m torch.distributed.run` to bind to the conda env's python, not a stale `~/.local/bin/torchrun`).

### Default (4 GPUs)

```bash
bash training/scripts/run_sft_overfit_failed.sh
```

### 8 GPUs with sequence parallel

```bash
NUM_TRAINERS=8 SP_SIZE=2 bash training/scripts/run_sft_overfit_failed.sh
```

### Smoke test (1 step, no real training)

```bash
DRYRUN=1 bash training/scripts/run_sft_overfit_failed.sh
```

**Environment variables honored by the script:**
- `NUM_TRAINERS`: GPUs per node (default 4).
- `SP_SIZE`: Ulysses sequence-parallel size. Auto-forced to 1 when `NUM_TRAINERS<=4`.
- `EXP_NAME`: W&B run name and checkpoint subdir (default `sft_overfit_failed_v0_1`).
- `CKPT_HOME`: checkpoint root (default `training/checkpoints/`).
- `HF_HOME`: HuggingFace cache root (default `~/.cache/huggingface`).
- `WANDB_MODE`: `online` if `api.wandb.ai` is reachable, else fall back to `offline` and `wandb sync` later.
- `DRYRUN=1`: pin to one training step.

verl also reads a few env vars verbatim: `WANDB_PROJECT`, `WANDB_API_KEY`, and the standard `CUDA_VISIBLE_DEVICES`. FSDP is configured via the hydra `engine.*` keys — no extra env vars needed.

---

## Part 5: Monitor Training

### Console and W&B

The trainer logs to both `console` and `wandb` (configured via `trainer.logger`). Console shows step/loss/throughput each step; W&B mirrors the same metrics plus learning rate, grad norm, and val loss.

Tail the console log (the launcher streams to stdout — redirect it):

```bash
bash training/scripts/run_sft_overfit_failed.sh 2>&1 | tee training/logs/sft_$(date +%Y%m%d_%H%M%S).log
```

### Checkpoints

verl writes to `training/checkpoints/<EXP_NAME>/global_step_<N>/`. Each step dir contains:

- `actor/huggingface/` — merged HF-format weights, ready for vLLM. **This is the artifact eval consumes.**
- `actor/model_world_size_<N>_rank_<R>.pt` — per-rank FSDP shards (for resume).
- `actor/extra_state_world_size_<N>_rank_<R>.pt` — optimizer state.

`max_ckpt_to_keep=3` keeps only the latest three step dirs.

### Identifying the best checkpoint

`trainer.test_freq=10` runs validation every 10 steps on [`val.parquet`](data/sft_overfit_failed_v0.1/val.parquet). The val-loss column in W&B (or in the JSONL emitted by verl under the checkpoint dir) is the criterion. Pick the step dir with the lowest val loss whose number is also a `save_freq` multiple — that's the one with weights on disk.

---

## Part 6: Hand Off to Eval

The eval pipeline ([`MARS-Voyager/`](../MARS-Voyager/)) needs the HF-format weights. Point vLLM at:

```
training/checkpoints/<EXP_NAME>/global_step_<BEST>/actor/huggingface/
```

Set `--model` on the vLLM `api_server` to this path (see [`MARS-Voyager/SETUP_GUIDE.md`](../MARS-Voyager/SETUP_GUIDE.md) Part 1, Step 3). The tokenizer, processor, and chat template are saved alongside the weights — no extra config needed.

---

## Troubleshooting

### Out of memory

In order of preference:
1. Lower `data.max_token_len_per_gpu` (try 12288, then 8192).
2. Keep `model.enable_gradient_checkpointing=true` (it is by default in [`scripts/run_sft_overfit_failed.sh`](scripts/run_sft_overfit_failed.sh)).
3. Drop `data.train_batch_size` to 16 — verl will compensate with more grad-accum micro-steps.
4. Lower `data.max_length` to 4096 if your rows fit (check with the inspector in Part 2).
5. Bump `engine.ulysses_sequence_parallel_size` to 2 (requires `NUM_TRAINERS>=4`).

### Tokenizer or processor mismatch

Symptom: silent loss-mask drift, or a hard error about `<image>` tokens. Cause: a different HF snapshot for the base model than the one used to build the parquet. Verify:

```bash
ls $HF_HOME/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/
```

Only the directory `ebb281ec70b05090aa6165b016eac8ec08e71b17` should be referenced. If a different snapshot is present, re-run the `snapshot_download` in Part 1 Step 4.

### `'set' object is not subscriptable` during FSDP wrap

`transformers` version drift. Pin must be exactly `4.57.3` — see [`PINS.md`](PINS.md). Re-install:

```bash
pip install 'transformers==4.57.3' --force-reinstall --no-deps
```

### verl-vs-vLLM version conflict

`scripts/install_vllm_sglang_mcore.sh` resolves the pair. Do **not** `pip install -U vllm` afterward — it will pull a torch version verl was not compiled against. If vLLM ever needs to be updated, re-run the install script.

### FSDP hang at startup

Usually one of:
- `ROCR_VISIBLE_DEVICES` set alongside `CUDA_VISIBLE_DEVICES`. The launch script `unset`s it; verify your shell does not re-export it.
- Stale NCCL state from a prior killed run. `pkill -9 -f torch.distributed.run` and retry.
- Mixed-version `torchrun` from `~/.local/bin/`. Use `python -m torch.distributed.run` (the script already does).

### Resuming after a crash

`trainer.resume_mode=auto` picks up the latest `global_step_*` dir under `trainer.default_local_dir`. Just re-run the same command.

---

## Quick Reference

| Task | Command |
|------|---------|
| Create env | `conda create -n verl python=3.12 -y && conda activate verl` |
| Clone verl | `git clone --depth 1 --branch v0.7.1 https://github.com/volcengine/verl.git training/verl` |
| Install stack | `pushd training/verl && USE_MEGATRON=0 USE_SGLANG=0 bash scripts/install_vllm_sglang_mcore.sh && popd && pip install -e ./training/verl && pip install 'transformers==4.57.3'` |
| Pre-download model | `python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-VL-4B-Instruct', revision='ebb281ec70b05090aa6165b016eac8ec08e71b17')"` |
| Verify dataset | `python -c "import pyarrow.parquet as pq; print(pq.read_table('training/data/sft_overfit_failed_v0.1/train.parquet').num_rows)"` |
| Smoke test (1 step) | `DRYRUN=1 bash training/scripts/run_sft_overfit_failed.sh` |
| Train (4 GPUs) | `NUM_TRAINERS=4 SP_SIZE=1 bash training/scripts/run_sft_overfit_failed.sh` |
| Train (8 GPUs, SP=2) | `NUM_TRAINERS=8 SP_SIZE=2 bash training/scripts/run_sft_overfit_failed.sh` |
| Best checkpoint path | `training/checkpoints/<EXP_NAME>/global_step_<BEST>/actor/huggingface/` |

---

## Additional Resources

- [verl v0.7.1 docs](https://verl.readthedocs.io/en/v0.7.1/)
- Reference recipe: [`verl/examples/sft/vlm/run_qwen3_vl_2b.sh`](verl/examples/sft/vlm/run_qwen3_vl_2b.sh)
- Dataset schema: [`data/sft_overfit_failed_v0.1/README.md`](data/sft_overfit_failed_v0.1/README.md)
- Pinned versions: [`PINS.md`](PINS.md)
- Eval handoff: [`MARS-Voyager/SETUP_GUIDE.md`](../MARS-Voyager/SETUP_GUIDE.md)
