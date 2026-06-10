# Manual Curation Data

This directory holds raw and derived manual demonstrations for always-failed
AndroidWorld tasks.

- `raw/` contains browser-curated trajectories and screenshots.
- `annotated/` contains raw traces augmented with LLM-generated Thought/Action
  variants.
- `qwen_jsonl/` contains inspectable QwenAgent-style JSONL generated from
  annotated traces.

Most generated data in this directory can be large. Commit only small metadata
or curated examples intentionally.
