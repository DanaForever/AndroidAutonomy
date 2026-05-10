# Training Stack — Pinned Versions

Two pins must agree across the dataset build and the SFT trainer. The build script writes both into `manifest.json` and the trainer asserts on load.

## verl

- **Tag:** `v0.7.1`
- **Commit SHA:** `bec9ef74768dd201881cd4e54cd0385e87caae27`
- **Released:** 2026-03-16
- **Vendored at:** `training/verl/` (gitignored — re-clone with the command below)
- **Why this pin:** latest tagged stable as of pin date. First-class Qwen3-VL support — has both SFT (`examples/sft/vlm/run_qwen3_vl_2b.sh`) and GRPO (`examples/grpo_trainer/run_qwen3_vl-*`) recipes, plus the model wrapper at `verl/models/transformers/qwen3_vl.py`. Pin to the tag (not main HEAD) so research changes are deliberate.

Re-clone:
```bash
git clone --depth 1 --branch v0.7.1 https://github.com/volcengine/verl.git training/verl
# verify
git -C training/verl rev-parse HEAD  # expect bec9ef74768dd201881cd4e54cd0385e87caae27
```

## HF model + processor (Qwen3-VL-4B-Instruct)

- **Model id:** `Qwen/Qwen3-VL-4B-Instruct`
- **Revision SHA:** `ebb281ec70b05090aa6165b016eac8ec08e71b17`
- **Last modified upstream:** 2025-10-15
- **Architecture:** `Qwen3VLForConditionalGeneration`, `model_type=qwen3_vl`
- **Params:** 4.4B (BF16, ~8.9GB on disk)
- **Why this pin:** the only widely-served revision since release; processor + chat template + tokenizer must match between dataset build and SFT trainer (mismatch silently changes which tokens contribute to loss).

Use this revision in code:
```python
from transformers import AutoProcessor, AutoTokenizer
HF_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
processor = AutoProcessor.from_pretrained("Qwen/Qwen3-VL-4B-Instruct", revision=HF_REVISION)
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-VL-4B-Instruct", revision=HF_REVISION)
```

## verl SFT dataset schema (v0.7.1)

Confirmed from [`training/verl/verl/utils/dataset/multiturn_sft_dataset.py:240-286`](./verl/verl/utils/dataset/multiturn_sft_dataset.py).

Per-row columns the trainer reads:

| Column | Type | Notes |
|---|---|---|
| `messages` | list of `{role, content}` | `content` is a **string** (not content list); placeholders `<image>` and `<video>` are split out by the dataset class. |
| `images` | list of image paths or PIL | One entry per `<image>` placeholder across all messages, in order. Default column name; configurable via `image_key`. |

Happy alignment: [`MARS-Voyager/androidworld/eval/agents/qwen_agent.py:216`](../MARS-Voyager/androidworld/eval/agents/qwen_agent.py)'s `_construct_prompt` already produces a string containing `Current Screenshot: <image>` — drop it straight into `messages[1].content` and verl will substitute the image. With `n_history_image=0` (the eval-time setting), exactly one `<image>` per row → `images` is a one-element list per row.

Reference SFT recipe: [`training/verl/examples/sft/vlm/run_qwen3_vl_2b.sh`](./verl/examples/sft/vlm/run_qwen3_vl_2b.sh) — for our 4B run, swap `MODEL_ID` and adjust batch/parallelism.
