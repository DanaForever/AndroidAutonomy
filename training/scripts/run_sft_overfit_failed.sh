#!/usr/bin/env bash
# SFT run on the always-failed cohort (3 SFT-ready tasks):
# NotesTodoItemCount, SimpleCalendarEventsInNextWeek, SystemCopyToClipboard.
#
# Forked from training/scripts/run_sft.sh. Deltas vs the overfit-10 run:
#   * TRAIN_FILES / VAL_FILES: training/data/sft_overfit_failed_v0.1
#   * EXP_NAME:                sft_overfit_failed_v0_1
#   * trainer.total_epochs:    5 (was 60) — much smaller demo set
#
# Hardware target: 4-8x A100 40GB on the remote training node.
# Plan: tasks/training-codebase/sft-overfit-failed/plan.html
#
# Usage:
#   bash training/scripts/run_sft_overfit_failed.sh                # full run
#   DRYRUN=1 bash training/scripts/run_sft_overfit_failed.sh       # 1 step, smoke only
#   NUM_TRAINERS=4 SP_SIZE=1 bash training/scripts/run_sft_overfit_failed.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# --- Env --------------------------------------------------------------------
unset ROCR_VISIBLE_DEVICES

: "${HF_HOME:=$HOME/.cache/huggingface}"
: "${CKPT_HOME:=training/checkpoints}"
: "${WANDB_PROJECT:=gui_agent}"
export HF_HOME CKPT_HOME WANDB_PROJECT
mkdir -p "$CKPT_HOME"

if [[ -z "${WANDB_MODE:-}" ]]; then
  if curl -fsS --max-time 5 https://api.wandb.ai >/dev/null 2>&1; then
    export WANDB_MODE=online
  else
    export WANDB_MODE=offline
    echo "[run_sft] api.wandb.ai unreachable (no tunnel?) -> WANDB_MODE=offline"
  fi
fi

# --- Pins -------------------------------------------------------------------
HF_REVISION=ebb281ec70b05090aa6165b016eac8ec08e71b17
MODEL_PATH="${HF_HOME}/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/${HF_REVISION}"
if [[ ! -d "$MODEL_PATH" ]]; then
  echo "[run_sft] pinned snapshot missing at $MODEL_PATH" >&2
  echo "[run_sft] re-run setup_remote_env.sh to download." >&2
  exit 1
fi

TRAIN_FILES="training/data/sft_overfit_failed_v0.1/train.parquet"
VAL_FILES="training/data/sft_overfit_failed_v0.1/val.parquet"
if [[ ! -f "$TRAIN_FILES" ]]; then
  echo "[run_sft] $TRAIN_FILES missing -- upload the dataset before launching." >&2
  exit 1
fi

# --- Topology ---------------------------------------------------------------
NUM_TRAINERS=${NUM_TRAINERS:-8}
SP_SIZE=${SP_SIZE:-2}
if [[ "$NUM_TRAINERS" -le 4 && "$SP_SIZE" -gt 1 ]]; then
  echo "[run_sft] NUM_TRAINERS=$NUM_TRAINERS -> forcing SP_SIZE=1"
  SP_SIZE=1
fi

# --- Run identity -----------------------------------------------------------
PROJECT_NAME="gui_agent"
EXP_NAME="sft_overfit_failed_v0_1"
if [[ "${DRYRUN:-0}" == "1" ]]; then
  EXP_NAME="${EXP_NAME}_dryrun"
fi

# --- Dry-run extras ---------------------------------------------------------
EXTRA=()
if [[ "${DRYRUN:-0}" == "1" ]]; then
  EXTRA+=(trainer.total_training_steps=1)
fi

# --- Launch -----------------------------------------------------------------
python -m torch.distributed.run --standalone --nnodes=1 --nproc-per-node="${NUM_TRAINERS}" \
  -m verl.trainer.sft_trainer \
  data.train_files="${TRAIN_FILES}" \
  data.val_files="${VAL_FILES}" \
  data.train_batch_size=8 \
  data.max_length=8192 \
  data.pad_mode=no_padding \
  data.truncation=error \
  data.use_dynamic_bsz=true \
  data.max_token_len_per_gpu=16384 \
  data.messages_key=messages \
  model.path="${MODEL_PATH}" \
  model.use_remove_padding=true \
  model.enable_gradient_checkpointing=true \
  +model.override_config.attn_implementation=sdpa \
  engine=fsdp \
  engine.strategy=fsdp2 \
  engine.fsdp_size=-1 \
  engine.ulysses_sequence_parallel_size="${SP_SIZE}" \
  optim=fsdp \
  optim.lr=2e-5 \
  optim.lr_warmup_steps_ratio=0.03 \
  optim.weight_decay=0.1 \
  optim.betas="[0.9,0.95]" \
  optim.clip_grad=1.0 \
  optim.min_lr_ratio=0.1 \
  optim.warmup_style=cosine \
  trainer.project_name="${PROJECT_NAME}" \
  trainer.experiment_name="${EXP_NAME}" \
  trainer.total_epochs=5 \
  trainer.test_freq=10 \
  trainer.save_freq=30 \
  trainer.max_ckpt_to_keep=3 \
  trainer.default_local_dir="${CKPT_HOME}/${EXP_NAME}" \
  trainer.resume_mode=auto \
  trainer.nnodes=1 \
  trainer.n_gpus_per_node="${NUM_TRAINERS}" \
  trainer.logger=['console','wandb'] \
  checkpoint.save_contents=[model,hf_model,extra] \
  "${EXTRA[@]}"
