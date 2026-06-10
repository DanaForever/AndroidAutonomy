# SFT overfit-failed v0.1

Self-distilled Qwen3-VL-4B-Instruct SFT dataset for the always-failed-task
overfit experiment. Built from successful UI-Voyager android_world rollouts under
[`MARS-Voyager/eval_results/`](../../../MARS-Voyager/eval_results/), with
50 param-varied instances per task.

- Steps: **434**, unique rollouts: **69**, unique tasks: **3**
- Images mode: **embed**
- Built by [`training/data/build_sft_v0_1.py`](../build_sft_v0_1.py)
- Plan: [`tasks/training-codebase/sft-overfit-failed/plan.html`](../../../tasks/training-codebase/sft-overfit-failed/plan.html)
- Pins: [`training/PINS.md`](../../PINS.md)

## Files

- `train.parquet` — training split (verl SFT layout: `messages` + `images` + Pattern-C source fields).
- `val.parquet` — held-out validation split (~10% of rollouts, stratified by task, deterministic).
- `manifest.json` — pins (verl + HF revision), system-prompt hash, per-source-run configs, selected (task, seed) → run_id decisions, input rollout hashes.
- `stats/stats.md` — consolidated statistics, plus task list with links back to source rollouts.
- `stats/plots/*.png` — best-effort plots (skipped if matplotlib missing).

## Schema

Verl-consumed columns (per [`training/verl/verl/utils/dataset/multiturn_sft_dataset.py`](../../verl/verl/utils/dataset/multiturn_sft_dataset.py) at v0.7.1):

| Column | Type | Notes |
|---|---|---|
| `messages` | list[{role, content:str}] | `<image>` placeholders in `content` are split by verl and substituted from `images`. |
| `images` | list[{bytes: PNG bytes}] — embedded; parquet is fully self-contained and portable | One entry per `<image>` placeholder. With `n_history_image=0`, exactly one per row. |

Source fields kept for traceability and re-rendering: `goal`, `history`, `image_path`, `assistant_response`, `template_id`, `task_name`, `repeat_id`, `step_index`, `source_run_id`. Note: `image_path` is the **original absolute path on the build host** — informational, not used by the trainer when `images` are embedded.

## Known caveats

- **Selection bias.** Among rollouts in the same `(task, seed)` group, the
  build picks the shortest. This systematically prefers early-`status`
  terminations and may underrepresent complex multi-step rollouts. Acceptable
  for a pipeline-validation dummy; revisit if used for serious training.
- **Tiny val split.** Validation is rollout-level and stratified by task, but
  the dataset is intentionally small; live android_world eval on the same task
  list is the meaningful test.
