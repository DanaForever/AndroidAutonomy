# SFT Training Data for Phase 1 Dummy Run

## Context

Parent task: [`tasks/training-codebase/plan.md`](../plan.md). Phase 1 needs an SFT dataset to train Qwen3-VL-4B-Instruct under verl. This sub-plan covers how that dataset gets built.

**What exists already:**
- [`MARS-Voyager/androidworld/eval/agents/qwen_agent.py`](../../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) already writes SFT-shaped data when launched with `agent.sft_data_dir` set: per-step JSONL with `conversations` (system/user/assistant) + `images` paths, one file per `(task, repeat)` named `repeat_XX_succ.jsonl` or `repeat_XX_fail.jsonl`, plus a per-step `is_success` flag.
- 429 `*_succ.jsonl` rollouts exist under [`MARS-Voyager/eval_results/`](../../../MARS-Voyager/eval_results/), but most reuse the same seed across runs. After deduping by `(task_name, seed)` the effective pool is roughly **190 unique successful rollouts**, ~1-2k steps total — at the low end of the small-budget target.
- A pre-build audit confirmed all 10 runs with successful rollouts use **identical preprocessing and prompt config** (`resize=null`, `use_som=false`, `n_history_image=0`, `history_len=30`, `prompt_name=qwen3vl_instruct`). Only the random seed differs (null vs 42). No cross-run drift to worry about; record configs in the manifest but no equality gate is required.

**Decisions (frozen):**
- **Source policy:** existing UI-Voyager rollouts (self-distill). No frontier-model teacher, no public-data mixin.
- **Target size:** ~1-5k steps. Pipeline validation only.
- **History length:** `n_history_image = 0` (current screenshot only; text-only history). Matches all source runs.
- **Output format:** verl SFT parquet with hybrid record layout (rendered `messages` + structured source fields). See Step 4.
- **No train/val split.** Overfit on purpose; the meaningful eval is live android_world on the same task list (handled by the SFT-training sub-task, not here).

**Target outcome:** a frozen SFT dataset at [`training/data/sft_v0/`](../../../training/data/sft_v0/) with `train.parquet`, manifest, README, and consolidated stats — verified to load through verl's stock SFT batch collator in a build-time smoke test.

## Pre-execution prerequisites

Status: ✅ done. See [`training/PINS.md`](../../../training/PINS.md) for the canonical record.

1. **verl pinned to v0.7.1** (`bec9ef74768dd201881cd4e54cd0385e87caae27`), vendored at [`training/verl/`](../../../training/verl/) (gitignored; re-clone command in PINS.md). Has first-class Qwen3-VL SFT recipe at [`training/verl/examples/sft/vlm/run_qwen3_vl_2b.sh`](../../../training/verl/examples/sft/vlm/run_qwen3_vl_2b.sh).
2. **HF Qwen3-VL-4B-Instruct pinned to revision `ebb281ec70b05090aa6165b016eac8ec08e71b17`** (lastModified 2025-10-15). Use this `revision=` argument in `AutoProcessor.from_pretrained` / `AutoTokenizer.from_pretrained`.
3. **Schema decision frozen.** verl v0.7.1's [`multiturn_sft_dataset.py`](../../../training/verl/verl/utils/dataset/multiturn_sft_dataset.py) expects `messages` (list of `{role, content:str}` with literal `<image>` placeholders) and `images` (list of one image per `<image>` placeholder). [`_construct_prompt`](../../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) already emits a string with literal `<image>` — drop straight into `messages[1].content`. With `n_history_image=0`, exactly one `<image>` per row.

## Plan

### Step 1 — Audit and dedupe rollouts

Walk the configured `eval_results/` root. For each `*_succ.jsonl`, count steps, check that referenced image paths resolve, bucket by task, and tag with source run.

**Dedupe by `(task_name, seed)`.** Group successful rollouts; keep exactly one rollout per group. Selection rule:
1. **Gate:** every step in the rollout must pass `is_parseable(response)` (defined below). Drop any rollout with a malformed step.
2. **Fewest steps wins.** Among survivors, prefer the shortest successful trajectory (more efficient demonstration).
3. **Most recent run** as tie-break (timestamps are unique → no further tiebreak needed).

Seed source: read from the per-run `config.yaml` snapshot under `eval_results/<MODEL>/results/<TIMESTAMP>/config.yaml`. If absent, fall back to a content hash over the rollout's assistant responses.

**`is_parseable(response: str) -> bool` — strict predicate.** Do NOT use [`_parse_action`](../../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py)'s return value as a truthy gate; it returns `JSONAction(action_type='wait')` on every failure path, which would admit malformed responses as fake "successful waits." The predicate must distinguish a **real** `wait` (deliberate `arguments.action == "wait"`) from the **fallback** `wait` produced on parse failures.

Returns `True` iff the response contains a non-empty `<tool_call>...</tool_call>` block whose contents are valid JSON, `arguments.action` is one of `{wait, click, long_press, swipe, open_app, input_text, system_button, status, answer, scroll}`, AND the action's required fields are present and well-shaped:
- `click` / `long_press`: `coordinate` is `[x, y]` of two numbers.
- `swipe`: both `coordinate` and `coordinate2` are `[x, y]` of two numbers.
- `open_app` / `input_text` / `answer`: `text` is a string.
- `system_button`: `button` ∈ `{Back, Home, Enter}`.
- `status`: `status` is a string.
- `scroll`: `direction` ∈ `{up, down, left, right}`.

Lives at [`training/data/response_validation.py`](../../../training/data/response_validation.py) (separate from MARS-Voyager so the training pipeline doesn't depend on edits to the eval submodule). The eval pipeline can opt in later by importing the same module if desired.

**Status:** ✅ implemented. Self-test passes 23/23 cases (`python3 training/data/response_validation.py`). Sanity-check against real data: 4479/4481 (99.96%) of assistant turns from existing succ rollouts pass; the 2 failures are missing `<tool_call>` tags — exactly the silent-fallback cases the predicate is designed to reject.

### Step 2 — Filter steps within kept rollouts

For every step in the kept rollouts:
1. File suffix is `_succ.jsonl`.
2. `is_success == True` (defensive).
3. `is_parseable(response) == True` (already enforced at rollout level by Step 1's gate; revalidate per-step as a defensive check).
4. All referenced image files exist and load.

### Step 3 — Final assembly

Random shuffle the kept steps with a fixed seed. Write all of them to a single `train.parquet`. No per-task cap. No val split.

### Step 4 — Convert to verl SFT format (hybrid layout)

Per-row schema (verl-consumed fields per the v0.7.1 [`multiturn_sft_dataset.py`](../../../training/verl/verl/utils/dataset/multiturn_sft_dataset.py) contract, plus source fields for traceability and re-rendering):

| Column | Source | Used by |
|---|---|---|
| `messages` | list of `{role, content}` where `content` is a **string** with literal `<image>` placeholder; rendered via [`_construct_prompt`](../../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) + system-prompt loader | verl trainer |
| `images` | one-element list `[absolute_path_to_current_screenshot]` (one `<image>` placeholder per row at `n_history_image=0`) | verl trainer |
| `goal` | task instruction | inspection / re-rendering |
| `history` | list of action-description strings | inspection / re-rendering |
| `image_path` | same as `images[0]` | inspection |
| `assistant_response` | raw response string (also embedded in `messages[-1].content`) | inspection / re-rendering |
| `template_id` | string tag for the renderer used (e.g. `qwen_agent_v1`) | re-rendering |
| `task_name`, `repeat_id`, `step_index`, `source_run_id` | provenance | debugging |

**Rendering:** import the system-prompt loader (from `eval/prompts/get_prompt`) and [`_construct_prompt`](../../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) directly from `qwen_agent.py`. Do not reimplement. The `<image>` literal in the rendered user-message string is preserved verbatim — verl's dataset class splits on it and substitutes the image at training time.

**Build-time assertion to prevent Pattern C drift:** for every row, assert `row["messages"][-1]["content"] == row["assistant_response"]`. Fail the build on mismatch.

**Image storage:** PNG bytes are **embedded into the parquet** (`images` column = `list[{"bytes": <png>}]`). Verl's [`process_image`](../../../training/verl/verl/utils/dataset/vision_utils.py) handles this dict shape natively (line 28-30). The `image_path` source field still records the absolute local path for traceability, but is not used at training time. Default because the data is curated locally and trained on a remote machine — embedding makes the parquet a single-file portable artifact (~880MB at 2250 rows). Override with `--images-mode absolute` for a tiny parquet on a single-host workflow.

### Step 5 — Smoke test through verl's collator

Inside the build script, after writing the parquet and **before** declaring success:
1. Open `train.parquet` with verl's Qwen-VL SFT dataset class (the one matching the pinned verl commit).
2. Pull one batch via the trainer's collator.
3. Assert: batch has expected keys (`input_ids`, `attention_mask`, `labels`, `pixel_values` / image fields per verl's contract); `labels` are `-100` everywhere except over the assistant-response token span; image-token ids are masked from loss.
4. On failure, fail the build with a clear error pointing at the offending row index. **This is the single most important verification** — it catches loss-mask bugs, processor mismatch, and template drift before any GPU time is spent.

### Step 6 — Freeze and document

Outputs under [`training/data/sft_v0/`](../../../training/data/sft_v0/):

- `train.parquet` — the dataset.
- `README.md` — short data card. Includes a schema block (column → type → required) inline; pointer to `stats/stats.md` and `manifest.json`. Notes the known selection bias (fewest-steps preference may overrepresent early-status terminations).
- `manifest.json` — reproducibility record:
  - Source `eval_results/` git commit + per-rollout content hashes.
  - Selected `(task, seed) → run_id` decisions from Step 1.
  - Per-source-run config snapshots (`resize`, `use_som`, `n_history_image`, `history_len`, `prompt_name`, seed) — recorded for audit, not gated.
  - **Resolved system prompt** + its SHA256 hash.
  - **HF processor/tokenizer revision** for `Qwen3-VL-4B-Instruct`.
  - **verl commit SHA**.
  - Build script git SHA + run timestamp.
- `stats/stats.md` — consolidated stats. Trimmed scope:
  - Headline counts (rows, rollouts, tasks).
  - Filter funnel — text table: raw → after `_succ` filter → after parse gate → after image-load filter → after dedupe → final.
  - Action-type histogram (text + `plots/action_type_hist.png`).
  - Token-length distribution for `messages` (text: min/median/p95/max + `plots/token_length_hist.png`).
  - Trajectory-length distribution (text only).
  - Source-run distribution (text only).
  - Task list table — every task in the dataset, sorted by name. Columns: task name, source run id, step count, link to `repeat_XX_succ.jsonl`, link to `images/` dir. Links are relative paths from `stats.md` back to [`MARS-Voyager/eval_results/`](../../../MARS-Voyager/eval_results/) (clickable in IDE).
- `stats/plots/` — best-effort PNGs (`action_type_hist.png`, `token_length_hist.png`). Plot generation is wrapped in try/except: a plotting failure logs a warning and the corresponding `stats.md` link is omitted, but the build still succeeds.

## Critical files

Authored:
- [`training/data/response_validation.py`](../../../training/data/response_validation.py) — `is_parseable(response)` strict predicate. Run `python3 training/data/response_validation.py` for the 23-case self-test.
- [`training/data/build_sft_v0.py`](../../../training/data/build_sft_v0.py) — the build script (Steps 1-6 below). Run `python3 training/data/build_sft_v0.py [--no-smoke-test]`.
- [`training/PINS.md`](../../../training/PINS.md) — verl + HF revision pins.

Generated by the build (do not edit):
- [`training/data/sft_v0/train.parquet`](../../../training/data/sft_v0/train.parquet)
- [`training/data/sft_v0/manifest.json`](../../../training/data/sft_v0/manifest.json)
- [`training/data/sft_v0/README.md`](../../../training/data/sft_v0/README.md)
- [`training/data/sft_v0/stats/stats.md`](../../../training/data/sft_v0/stats/stats.md), `stats/plots/*.png`

**First-run results (2026-05-08):** 13 runs discovered, 429 raw `*_succ.jsonl` files → 427 pass parse gate (2 rejected as malformed; matches the 99.96% calibration from the `is_parseable` audit) → 427 pass image-load → 215 unique rollouts after `(task, seed)` dedupe → **2250 step records across 97 unique tasks**. Squarely in the 1-5k target. Pattern-C consistency assertion (`messages[-1].content == assistant_response`) holds for all rows. With `--images-mode embed` (default), parquet weighs 884 MB and is portable: `rsync training/data/sft_v0/train.parquet remote:.../sft_v0/` is the entire transfer.

To reuse (do not duplicate):
- [`MARS-Voyager/androidworld/eval/agents/qwen_agent.py`](../../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) — `_construct_prompt`, `_get_action_description`, `_clean_action_text`. Import these so training data and eval stay byte-identical at the user-content layer.
- `MARS-Voyager/androidworld/eval/prompts/get_prompt` — system-prompt registry. Resolve the same `prompt_name` (`qwen3vl_instruct`) used in the source runs.

## Verification

End-to-end checks for the v0 dataset itself:
1. [`build_sft_v0.py`](../../../training/data/build_sft_v0.py) runs end to end and writes `train.parquet`, `README.md`, `manifest.json`, `stats/stats.md`, `stats/plots/*.png`. Step count between 1-5k.
2. **Step 5 smoke test passes** — verl's stock SFT collator reads `train.parquet` and yields a well-formed batch with correct loss masking. (Most important check.)
3. Pattern C consistency: a sweep over the parquet confirms `messages[-1].content == assistant_response` on every row.
4. Spot-check 10 random rows in a notebook: image opens, `messages` reads correctly, `is_parseable(assistant_response) == True`.
5. Filter-funnel counts in `stats/stats.md` are internally consistent (each row = previous row − documented drops).
6. Action-type histogram is not single-peaked (>1 action type with non-trivial share).
7. Spot-check 3 task-list links in `stats/stats.md` — each opens the correct rollout folder under [`MARS-Voyager/eval_results/`](../../../MARS-Voyager/eval_results/).
8. Manifest contains: verl SHA, HF processor revision, system-prompt hash, per-source-run configs.

## Top-up (optional, deferred)

If after Step 5b the unique-step count is below ~1k, or the action-type histogram is too skewed to validate the training loop honestly, launch additional MARS-Voyager eval runs with `agent.sft_data_dir` set and **varied seeds**, then rerun this build script — the dedupe rule picks up the new rollouts automatically. This is opt-in; not part of the default execution path.
