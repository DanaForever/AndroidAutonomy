"""Build SFT dataset v0.1 from MARS-Voyager UI-Voyager rollouts.

Successor to `build_sft_v0.py`. Two real differences from v0:

  (a) Handles the per-instance filename scheme introduced by the
      `n_task_combinations`-overwrite fix in qwen_agent. Reads both
      `repeat_NN_succ.jsonl` (legacy) and `repeat_NN_inst_NNN_succ.jsonl`
      (post-fix). The dedupe key includes `instance_idx`, so the 30
      instances generated per task in one run survive as 30 distinct
      training rollouts instead of collapsing to one.

  (b) Writes a deterministic train/val split (default 90/10), stratified
      by task at the rollout level. `val.parquet` lets the SFT loop track
      a held-out loss curve without leaking step-level information.

See `tasks/training-codebase/sft-data/overfit-10-tasks.html` for the design
rationale of the overfit experiment that motivated this build.

Pipeline:
    1. Walk eval_results/, discover runs + per-run configs.
    2. Parse `*_succ.jsonl` rollouts; reject any rollout containing a step
       that fails `is_parseable` or whose images don't load.
    3. Group surviving rollouts by (task_name, seed_key); per group keep one
       rollout: fewest-steps wins; tie-break by most-recent run.
    4. Flatten to step-level records (Pattern C hybrid layout: rendered
       `messages` + `images` for verl, plus structured source fields).
    5. Hold out ~val-frac of rollouts per task (stratified, deterministic).
    6. Shuffle with a fixed seed; write `train.parquet` + `val.parquet`.
    7. Best-effort smoke test through verl's MultiturnSFTDataset.
    8. Write manifest.json, README.md, stats/stats.md, stats/plots/*.png.

Usage:
    python3 training/data/build_sft_v0_1.py \
        --eval-results MARS-Voyager/eval_results \
        --out-dir training/data/sft_v0.1 \
        [--val-frac 0.1] [--val-split-seed 42] \
        [--shuffle-seed 42] [--no-plots] [--no-smoke-test]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Iterator, Tuple, List, Dict

import yaml
from PIL import Image, UnidentifiedImageError

# Project-internal: strict parseability predicate.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from response_validation import is_parseable  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_sft_v0_1")


# ---------------------------------------------------------------------------
# Constants from training/PINS.md — keep in sync.
# ---------------------------------------------------------------------------
VERL_TAG = "v0.7.1"
VERL_SHA = "bec9ef74768dd201881cd4e54cd0385e87caae27"
HF_MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
HF_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
TEMPLATE_ID = "qwen_agent_v1"  # rendered with `_construct_prompt` from MARS-Voyager qwen_agent.py


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class RunInfo:
    run_id: str
    run_path: Path
    config: dict[str, Any]  # parsed config.yaml; {} if missing


@dataclasses.dataclass(frozen=True)
class StepRecord:
    """One filtered training step."""
    task_name: str
    repeat_id: int
    instance_idx: int
    step_index: int
    source_run_id: str
    seed_key: str
    messages: list[dict[str, str]]   # role/content pairs (string content)
    images: list[str]                # absolute paths
    goal: str
    history: list[str]
    image_path: str
    assistant_response: str
    rollout_path: str                # path to source `*_succ.jsonl`


@dataclasses.dataclass
class FilterFunnel:
    rollouts_seen: int = 0
    rollouts_after_succ_filter: int = 0
    rollouts_after_parse_gate: int = 0
    rollouts_after_image_check: int = 0
    rollouts_after_dedupe: int = 0
    steps_after_dedupe: int = 0


# ---------------------------------------------------------------------------
# Step 1: discovery
# ---------------------------------------------------------------------------
def discover_runs(eval_results_root: Path) -> list[RunInfo]:
    """Find every run directory and load its config.yaml."""
    runs: list[RunInfo] = []
    # Layout: <eval_results>/<MODEL>/results/<TIMESTAMP>/...
    for results_dir in eval_results_root.glob("*/results"):
        for run_dir in sorted(results_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            config_path = run_dir / "config.yaml"
            config: dict[str, Any] = {}
            if config_path.exists():
                try:
                    with config_path.open() as f:
                        config = yaml.safe_load(f) or {}
                except yaml.YAMLError as e:
                    log.warning("config.yaml parse failed for %s: %s", run_dir, e)
            else:
                log.warning("missing config.yaml in %s", run_dir)
            runs.append(RunInfo(run_id=run_dir.name, run_path=run_dir, config=config))
    return runs


def seed_key_for(run: RunInfo, repeat_id: int, instance_idx: int = 0) -> str:
    """Dedupe key encoding the seed.

    Each n_task_combinations instance within a single (run, repeat) gets a
    *different* per-instance seed (via suite_utils._get_instance_seed in
    AndroidWorld), so the key must include `instance_idx` — otherwise all 30
    instances under one master `task_random_seed` collapse into a single
    dedupe bucket and we lose 29 out of every 30 rollouts.
    """
    seed = (run.config.get("eval") or {}).get("task_random_seed")
    if seed is None:
        return f"random_{run.run_id}_repeat{repeat_id}_inst{instance_idx}"
    return f"seed_{seed}_repeat{repeat_id}_inst{instance_idx}"


# ---------------------------------------------------------------------------
# Step 2: parse + gate rollouts
# ---------------------------------------------------------------------------
# Matches both legacy `repeat_00_succ.jsonl` and post-fix per-instance
# `repeat_00_inst_000_succ.jsonl` patterns.
_REPEAT_RE = re.compile(
    r"^repeat_(?P<repeat>\d+)(?:_inst_(?P<inst>\d+))?_succ\.jsonl$"
)


def iter_succ_rollouts(run: RunInfo) -> Iterator[tuple[str, int, int, Path]]:
    """Yield (task_name, repeat_id, instance_idx, rollout_path) for every *_succ.jsonl."""
    for task_dir in sorted(run.run_path.iterdir()):
        if not task_dir.is_dir() or task_dir.name == "logs":
            continue
        for jsonl in sorted(task_dir.glob("repeat_*_succ.jsonl")):
            m = _REPEAT_RE.match(jsonl.name)
            if not m:
                continue
            repeat_id = int(m.group("repeat"))
            instance_idx = int(m.group("inst") or 0)
            yield task_dir.name, repeat_id, instance_idx, jsonl


def parse_rollout(path: Path) -> list[dict[str, Any]] | None:
    """Read a JSONL rollout. Return None on any read failure."""
    steps: list[dict[str, Any]] = []
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                steps.append(json.loads(line))
    except (json.JSONDecodeError, OSError) as e:
        log.debug("rollout parse failed %s: %s", path, e)
        return None
    return steps if steps else None


def all_steps_parseable(steps: list[dict[str, Any]]) -> bool:
    """Strict gate: every assistant response must pass `is_parseable`."""
    for step in steps:
        for msg in step.get("conversations", []):
            if msg.get("role") == "assistant":
                if not is_parseable(msg.get("content", "")):
                    return False
                break
        else:
            # No assistant message → malformed step.
            return False
    return True


def all_images_loadable(steps: list[dict[str, Any]]) -> bool:
    """Defensive: confirm every referenced image opens."""
    for step in steps:
        for img_path in step.get("images", []):
            try:
                with Image.open(img_path) as im:
                    im.verify()
            except (FileNotFoundError, UnidentifiedImageError, OSError):
                return False
    return True


# ---------------------------------------------------------------------------
# Action-grammar helpers (used for stats)
# ---------------------------------------------------------------------------
_TOOL_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.DOTALL)


def extract_action_type(response: str) -> str | None:
    """Return the action_type string from an assistant response, or None."""
    m = _TOOL_RE.search(response)
    if not m:
        return None
    payload = m.group(1).split("\n", 1)[0] if "</tool_call>" not in response else m.group(1)
    try:
        d = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    args = d.get("arguments")
    if not isinstance(args, dict):
        return None
    a = args.get("action")
    return a if isinstance(a, str) else None


def extract_user_goal(user_content: str) -> str:
    """Goal lives on the line `The user query: <goal>`."""
    m = re.search(r"The user query:\s*(.+)", user_content)
    return m.group(1).strip() if m else ""


def extract_history(user_content: str) -> list[str]:
    """History block is the lines `Step{n}: <text>` after the progress header."""
    out: list[str] = []
    for line in user_content.splitlines():
        m = re.match(r"^Step\d+:\s*(.+)$", line)
        if m:
            out.append(m.group(1).strip())
    return out


# ---------------------------------------------------------------------------
# Step 3: dedupe + selection
# ---------------------------------------------------------------------------
CandidateTuple = Tuple[RunInfo, str, int, int, Path, List[Dict[str, Any]]]
# (run, task, repeat_id, instance_idx, rollout_path, steps)


def select_one_per_group(
    candidates: list[CandidateTuple],
) -> list[CandidateTuple]:
    """Pick one rollout per (task_name, seed_key).

    Selection rule:
      1. Fewest steps wins (more efficient demonstration).
      2. Most recent run as tie-break (run_ids sort lexicographically by
         their leading timestamp, so max() is "most recent").
    """
    groups: dict[tuple[str, str], list[CandidateTuple]] = {}
    for run, task, repeat, inst, path, steps in candidates:
        key = (task, seed_key_for(run, repeat, inst))
        groups.setdefault(key, []).append((run, task, repeat, inst, path, steps))

    chosen: list[CandidateTuple] = []
    for key, items in groups.items():
        items.sort(key=lambda it: (len(it[5]), -_run_recency_key(it[0].run_id)))
        chosen.append(items[0])
    return chosen


def split_train_val(
    records: list[StepRecord],
    val_frac: float,
    seed: int,
) -> tuple[list[StepRecord], list[StepRecord]]:
    """Stratified rollout-level train/val split.

    Rationale:
      - Step-level random split leaks: two steps from the same rollout end up
        in different splits and the model can shortcut via shared context.
      - Task-level split is too aggressive for an overfit experiment — val tasks
        are never trained on so val loss never falls; you can't tell whether the
        loss curve reflects optimisation or distribution shift.
      - Rollout-level split (this function) holds out whole `(task, seed_key)`
        trajectories from seen tasks. Val loss measures per-step prediction on
        unseen trajectories of *seen* tasks — the right signal for "did overfit
        on the task family generalise across param draws".

    Stratification: holdout fraction is applied independently per task, so
    every task contributes to both splits (rounded; floor-1 train kept).
    Deterministic: ordering is sorted by seed_key before sampling and the RNG
    is seeded — re-running yields the same split.
    """
    if val_frac <= 0.0:
        return records, []
    if not 0 < val_frac < 1:
        raise ValueError(f"val_frac must be in (0, 1); got {val_frac}")

    # Group step records by (task, seed_key) — one group = one rollout.
    groups: dict[tuple[str, str], list[StepRecord]] = {}
    for r in records:
        groups.setdefault((r.task_name, r.seed_key), []).append(r)

    # Stable per-task ordering of rollouts.
    by_task: dict[str, list[tuple[str, str]]] = {}
    for key in sorted(groups):  # (task, seed_key)
        by_task.setdefault(key[0], []).append(key)

    rng = random.Random(seed)
    val_keys: set[tuple[str, str]] = set()
    for task, keys in by_task.items():
        if len(keys) < 2:
            # Can't split — keep the single rollout in train.
            continue
        n_val = max(1, round(len(keys) * val_frac))
        n_val = min(n_val, len(keys) - 1)  # always leave ≥1 train rollout per task
        chosen = rng.sample(keys, n_val)
        val_keys.update(chosen)

    train, val = [], []
    for r in records:
        key = (r.task_name, r.seed_key)
        (val if key in val_keys else train).append(r)
    return train, val


def _run_recency_key(run_id: str) -> int:
    """Run ids start with a 14-digit timestamp; convert to int when possible."""
    m = re.match(r"^(\d{14})", run_id)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Step 4: build per-step records
# ---------------------------------------------------------------------------
def build_records(
    rollouts: list[CandidateTuple],
) -> list[StepRecord]:
    out: list[StepRecord] = []
    for run, task, repeat, inst, path, steps in rollouts:
        for step in steps:
            convs = step.get("conversations", [])
            sys_msg = next((m for m in convs if m.get("role") == "system"), None)
            usr_msg = next((m for m in convs if m.get("role") == "user"), None)
            asst_msg = next((m for m in convs if m.get("role") == "assistant"), None)
            if not (sys_msg and usr_msg and asst_msg):
                continue

            user_content: str = usr_msg["content"]
            asst_content: str = asst_msg["content"]
            images: list[str] = list(step.get("images", []))

            # n_history_image=0 → exactly one <image> in the user content.
            placeholder_count = user_content.count("<image>")
            if placeholder_count != len(images):
                # Shouldn't happen on the existing rollouts; skip if it does
                # rather than misalign images vs placeholders.
                log.warning(
                    "image count %d != <image> placeholders %d in %s step %d; skipping",
                    len(images), placeholder_count, path, step.get("index", -1),
                )
                continue

            messages = [
                {"role": "system", "content": sys_msg["content"]},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": asst_content},
            ]

            out.append(StepRecord(
                task_name=task,
                repeat_id=repeat,
                instance_idx=inst,
                step_index=int(step.get("index", 0)),
                source_run_id=run.run_id,
                seed_key=seed_key_for(run, repeat, inst),
                messages=messages,
                images=images,
                goal=extract_user_goal(user_content),
                history=extract_history(user_content),
                image_path=images[0] if images else "",
                assistant_response=asst_content,
                rollout_path=str(path),
            ))
    return out


# ---------------------------------------------------------------------------
# Step 5: parquet write
# ---------------------------------------------------------------------------
def _load_image_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def write_parquet(records: list[StepRecord], out_path: Path, images_mode: str) -> None:
    """Write parquet.

    images_mode:
      - "embed": images column is list[{"bytes": <png-bytes>}] — verl-portable
        ([`vision_utils.process_image`](../verl/verl/utils/dataset/vision_utils.py)
        handles this dict natively). Single self-contained file; fully
        portable to remote training boxes. ~400KB per row.
      - "absolute": images column is list[str] of absolute paths. Tiny parquet
        but only works on the host that built it.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if images_mode not in ("embed", "absolute"):
        raise ValueError(f"images_mode must be 'embed' or 'absolute', got {images_mode!r}")

    rows: list[dict[str, Any]] = []
    for r in records:
        if images_mode == "embed":
            images_field = [{"bytes": _load_image_bytes(p)} for p in r.images]
        else:
            images_field = list(r.images)
        rows.append({
            "messages": r.messages,
            "images": images_field,
            "goal": r.goal,
            "history": r.history,
            "image_path": r.image_path,
            "assistant_response": r.assistant_response,
            "template_id": TEMPLATE_ID,
            "task_name": r.task_name,
            "repeat_id": r.repeat_id,
            "instance_idx": r.instance_idx,
            "step_index": r.step_index,
            "source_run_id": r.source_run_id,
        })

    # Build-time assertion: rendered ↔ source field consistency.
    for i, (rec, row) in enumerate(zip(records, rows)):
        assert row["messages"][-1]["content"] == rec.assistant_response, \
            f"row {i}: messages[-1].content drifted from assistant_response"

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, out_path)
    log.info(
        "wrote %s rows to %s (images=%s, %.1f MB on disk)",
        len(rows), out_path, images_mode,
        out_path.stat().st_size / (1024 * 1024),
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def char_token_proxy(text: str) -> int:
    """Cheap token-count proxy when transformers isn't available (~4 chars/tok)."""
    return max(1, len(text) // 4)


def compute_token_lengths(records: list[StepRecord]) -> list[int]:
    """Best-effort: real tokens via transformers, else char/4 proxy."""
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(HF_MODEL_ID, revision=HF_REVISION)
        lengths = []
        for r in records:
            full = "".join(m["content"] for m in r.messages)
            lengths.append(len(tok.encode(full, add_special_tokens=False)))
        return lengths
    except Exception as e:  # noqa: BLE001
        log.warning("transformers unavailable (%s) — using char/4 proxy", e)
        return [char_token_proxy("".join(m["content"] for m in r.messages)) for r in records]


def compute_stats(records: list[StepRecord], funnel: FilterFunnel) -> dict[str, Any]:
    from collections import Counter
    rollouts = {(r.task_name, r.seed_key) for r in records}
    tasks = {r.task_name for r in records}
    rollout_lengths: dict[tuple[str, str], int] = {}
    for r in records:
        rollout_lengths[(r.task_name, r.seed_key)] = rollout_lengths.get((r.task_name, r.seed_key), 0) + 1
    actions = Counter(extract_action_type(r.assistant_response) or "<unparseable>" for r in records)
    per_task = Counter(r.task_name for r in records)
    per_run = Counter(r.source_run_id for r in records)

    token_lengths = compute_token_lengths(records)

    def _quartiles(vals: list[int]) -> dict[str, int]:
        if not vals:
            return {"min": 0, "median": 0, "p95": 0, "max": 0}
        s = sorted(vals)
        n = len(s)
        return {
            "min": s[0],
            "median": s[n // 2],
            "p95": s[min(n - 1, int(n * 0.95))],
            "max": s[-1],
            "mean": sum(s) // n,
        }

    return {
        "headline": {
            "total_steps": len(records),
            "unique_rollouts": len(rollouts),
            "unique_tasks": len(tasks),
            "build_timestamp_utc": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
        "filter_funnel": dataclasses.asdict(funnel),
        "trajectory_length": _quartiles(list(rollout_lengths.values())),
        "per_task_step_count": {
            **_quartiles(list(per_task.values())),
            "tasks_with_one_step": sum(1 for v in per_task.values() if v == 1),
        },
        "action_type_histogram": dict(sorted(actions.items(), key=lambda kv: -kv[1])),
        "token_length": _quartiles(token_lengths),
        "source_run_distribution": dict(sorted(per_run.items(), key=lambda kv: -kv[1])),
        "task_list": _build_task_list(records),
    }


def _build_task_list(records: list[StepRecord]) -> list[dict[str, Any]]:
    by_task: dict[str, dict[str, Any]] = {}
    for r in records:
        e = by_task.setdefault(r.task_name, {
            "task_name": r.task_name,
            "source_run": r.source_run_id,
            "steps": 0,
            "rollout_path": r.rollout_path,
            "images_dir": str(Path(r.rollout_path).parent / "images"),
        })
        e["steps"] += 1
    return sorted(by_task.values(), key=lambda d: d["task_name"])


# ---------------------------------------------------------------------------
# Plots (best effort)
# ---------------------------------------------------------------------------
def make_plots(stats: dict[str, Any], plots_dir: Path) -> dict[str, str]:
    """Generate PNGs. Returns {plot_name: relative_path} for those that succeed."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        log.warning("matplotlib unavailable (%s) — skipping plots", e)
        return {}

    plots_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}

    def _save(fig, name: str) -> None:
        path = plots_dir / name
        try:
            fig.tight_layout()
            fig.savefig(path, dpi=120)
            out[name] = f"plots/{name}"
        except Exception as e:  # noqa: BLE001
            log.warning("plot %s failed: %s", name, e)
        finally:
            plt.close(fig)

    # action histogram
    try:
        labels = list(stats["action_type_histogram"].keys())
        counts = list(stats["action_type_histogram"].values())
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(labels, counts)
        ax.set_title("Action types")
        ax.set_ylabel("steps")
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        _save(fig, "action_type_hist.png")
    except Exception as e:  # noqa: BLE001
        log.warning("action plot failed: %s", e)

    # token length histogram (we don't have raw lengths, just quartiles; skip a
    # detailed hist and just plot quartile bars)
    try:
        tl = stats["token_length"]
        fig, ax = plt.subplots(figsize=(6, 4))
        keys = ["min", "median", "p95", "max"]
        ax.bar(keys, [tl[k] for k in keys])
        ax.set_title("Token-length distribution (per row)")
        ax.set_ylabel("tokens")
        _save(fig, "token_length_hist.png")
    except Exception as e:  # noqa: BLE001
        log.warning("token plot failed: %s", e)

    return out


# ---------------------------------------------------------------------------
# Stats markdown
# ---------------------------------------------------------------------------
def write_stats_md(
    stats: dict[str, Any],
    stats_md_path: Path,
    plot_paths: dict[str, str],
    eval_results_root: Path,
) -> None:
    lines: list[str] = []
    h = stats["headline"]
    lines.append("# SFT v0 — Dataset Statistics\n")
    lines.append(f"- Total steps: **{h['total_steps']}**")
    lines.append(f"- Unique rollouts: **{h['unique_rollouts']}**")
    lines.append(f"- Unique tasks: **{h['unique_tasks']}**")
    lines.append(f"- Build timestamp (UTC): {h['build_timestamp_utc']}\n")

    lines.append("## Filter funnel\n")
    f = stats["filter_funnel"]
    lines.append("| Stage | Rollouts |")
    lines.append("|---|---|")
    lines.append(f"| Discovered (`*_succ.jsonl`) | {f['rollouts_seen']} |")
    lines.append(f"| After succ-suffix filter | {f['rollouts_after_succ_filter']} |")
    lines.append(f"| After parse gate | {f['rollouts_after_parse_gate']} |")
    lines.append(f"| After image-load check | {f['rollouts_after_image_check']} |")
    lines.append(f"| After (task, seed) dedupe | {f['rollouts_after_dedupe']} |")
    lines.append(f"| Steps in final dataset | {f['steps_after_dedupe']} |")
    lines.append("")

    def _row_q(label: str, q: dict[str, Any]) -> str:
        keys = [k for k in ("min", "median", "mean", "p95", "max") if k in q]
        return f"- {label}: " + ", ".join(f"{k}={q[k]}" for k in keys)

    lines.append("## Distributions\n")
    lines.append(_row_q("Trajectory length (steps per kept rollout)", stats["trajectory_length"]))
    pt = stats["per_task_step_count"]
    lines.append(
        _row_q("Per-task step count", pt)
        + f", tasks_with_one_step={pt['tasks_with_one_step']}"
    )
    lines.append(_row_q("Token-length per row (`messages` content)", stats["token_length"]))
    if "token_length_hist.png" in plot_paths:
        lines.append(f"\n![token length]({plot_paths['token_length_hist.png']})")
    lines.append("")

    lines.append("### Action types\n")
    lines.append("| Action | Count |")
    lines.append("|---|---|")
    for action, n in stats["action_type_histogram"].items():
        lines.append(f"| `{action}` | {n} |")
    if "action_type_hist.png" in plot_paths:
        lines.append(f"\n![action types]({plot_paths['action_type_hist.png']})")
    lines.append("")

    lines.append("### Source-run distribution\n")
    lines.append("| Run | Steps |")
    lines.append("|---|---|")
    for run, n in stats["source_run_distribution"].items():
        lines.append(f"| `{run}` | {n} |")
    lines.append("")

    lines.append("## Task list\n")
    lines.append("| Task | Source run | Steps | Trajectory | Images |")
    lines.append("|---|---|---|---|---|")
    # Links are relative from stats.md (which lives at sft_v0/stats/stats.md).
    # eval_results_root is given as absolute; we compute relative to stats.md.
    stats_md_dir = stats_md_path.parent
    for entry in stats["task_list"]:
        rollout_rel = os.path.relpath(entry["rollout_path"], stats_md_dir)
        images_rel = os.path.relpath(entry["images_dir"], stats_md_dir)
        lines.append(
            f"| `{entry['task_name']}` | `{entry['source_run']}` | {entry['steps']} "
            f"| [jsonl]({rollout_rel}) | [images]({images_rel}) |"
        )

    stats_md_path.parent.mkdir(parents=True, exist_ok=True)
    stats_md_path.write_text("\n".join(lines) + "\n")
    log.info("wrote stats to %s", stats_md_path)


# ---------------------------------------------------------------------------
# Manifest + README
# ---------------------------------------------------------------------------
def _git_sha(path: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def write_manifest(
    manifest_path: Path,
    records: list[StepRecord],
    runs: list[RunInfo],
    repo_root: Path,
    system_prompt: str,
) -> None:
    selected = sorted({(r.task_name, r.seed_key, r.source_run_id) for r in records})
    selected_records = [{"task_name": t, "seed_key": s, "run_id": rid} for t, s, rid in selected]

    rollout_hashes = {}
    for r in records:
        rollout_hashes.setdefault(r.rollout_path, _file_hash(Path(r.rollout_path)))

    manifest = {
        "build": {
            "timestamp_utc": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "build_script_sha": _git_sha(repo_root),
            "template_id": TEMPLATE_ID,
        },
        "pins": {
            "verl": {"tag": VERL_TAG, "sha": VERL_SHA},
            "hf_model": {"id": HF_MODEL_ID, "revision": HF_REVISION},
        },
        "system_prompt": {
            "sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
            "char_count": len(system_prompt),
            "first_120_chars": system_prompt[:120],
        },
        "source_runs": [
            {
                "run_id": r.run_id,
                "agent": (r.config.get("agent") or {}),
                "eval": (r.config.get("eval") or {}),
                "llm": {k: v for k, v in (r.config.get("llm") or {}).items() if k != "api_key"},
            }
            for r in runs
        ],
        "selected_rollouts": selected_records,
        "input_rollout_hashes": rollout_hashes,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=False))
    log.info("wrote manifest %s", manifest_path)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_readme(readme_path: Path, n_steps: int, n_rollouts: int, n_tasks: int, images_mode: str) -> None:
    images_col_spec = (
        "list[{bytes: PNG bytes}] — embedded; parquet is fully self-contained and portable"
        if images_mode == "embed"
        else "list[str] — absolute filesystem paths; only resolves on the host that built the parquet"
    )
    md = f"""# SFT v0.1

Self-distilled Qwen3-VL-4B-Instruct SFT dataset for the 10-task overfit
experiment. Built from successful UI-Voyager android_world rollouts under
[`MARS-Voyager/eval_results/`](../../../MARS-Voyager/eval_results/), with
30 param-varied instances per task.

- Steps: **{n_steps}**, unique rollouts: **{n_rollouts}**, unique tasks: **{n_tasks}**
- Images mode: **{images_mode}**
- Built by [`training/data/build_sft_v0_1.py`](../build_sft_v0_1.py)
- Plan: [`tasks/training-codebase/sft-data/overfit-10-tasks.html`](../../../tasks/training-codebase/sft-data/overfit-10-tasks.html)
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
| `messages` | list[{{role, content:str}}] | `<image>` placeholders in `content` are split by verl and substituted from `images`. |
| `images` | {images_col_spec} | One entry per `<image>` placeholder. With `n_history_image=0`, exactly one per row. |

Source fields kept for traceability and re-rendering: `goal`, `history`, `image_path`, `assistant_response`, `template_id`, `task_name`, `repeat_id`, `step_index`, `source_run_id`. Note: `image_path` is the **original absolute path on the build host** — informational, not used by the trainer when `images` are embedded.

## Known caveats

- **Selection bias.** Among rollouts in the same `(task, seed)` group, the
  build picks the shortest. This systematically prefers early-`status`
  terminations and may underrepresent complex multi-step rollouts. Acceptable
  for a pipeline-validation dummy; revisit if used for serious training.
- **No val split.** Dummy is meant to overfit; live android_world eval on the
  same task list is the meaningful test (handled by the SFT-training sub-task).
"""
    readme_path.write_text(md)
    log.info("wrote README %s", readme_path)


# ---------------------------------------------------------------------------
# Smoke test (best effort)
# ---------------------------------------------------------------------------
def smoke_test(parquet_path: Path) -> bool:
    """Load one batch through verl's MultiturnSFTDataset.

    Best-effort: any import/runtime error is logged and treated as 'skipped'.
    Returns True iff the test ran and the assertions held.
    """
    try:
        # Heavy imports gated to the smoke-test path.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verl"))
        from omegaconf import OmegaConf  # type: ignore
        from transformers import AutoProcessor, AutoTokenizer  # type: ignore
        from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset  # type: ignore
    except Exception as e:  # noqa: BLE001
        log.warning("smoke test skipped — missing dep: %s", e)
        return False

    try:
        tok = AutoTokenizer.from_pretrained(HF_MODEL_ID, revision=HF_REVISION)
        proc = AutoProcessor.from_pretrained(HF_MODEL_ID, revision=HF_REVISION)
        cfg = OmegaConf.create({
            "messages_key": "messages",
            "image_key": "images",
            "max_length": 4096,
        })
        ds = MultiTurnSFTDataset(parquet_files=[str(parquet_path)], tokenizer=tok, config=cfg, processor=proc)
        item = ds[0]
        for k in ("input_ids", "attention_mask", "loss_mask"):
            assert k in item, f"missing key: {k}"
        # Loss mask must be non-trivial (some assistant tokens contribute).
        import torch  # type: ignore
        assert torch.any(item["loss_mask"] > 0), "loss_mask is all zero"
        log.info("smoke test OK — sample shape input_ids=%s, loss_mask non-zero=%d",
                 tuple(item["input_ids"].shape), int(item["loss_mask"].sum()))
        return True
    except Exception as e:  # noqa: BLE001
        log.error("smoke test FAILED: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-results", type=Path,
                    default=Path("MARS-Voyager/eval_results"),
                    help="Root of MARS-Voyager eval_results/")
    ap.add_argument("--out-dir", type=Path,
                    default=Path("training/data/sft_v0.1"),
                    help="Output directory")
    ap.add_argument("--shuffle-seed", type=int, default=42)
    ap.add_argument("--val-frac", type=float, default=0.1,
                    help="Fraction of rollouts to hold out for val (per-task "
                         "stratified). 0.0 disables the split.")
    ap.add_argument("--val-split-seed", type=int, default=42,
                    help="Seed for the train/val rollout-level split.")
    ap.add_argument("--tasks", nargs="+", default=None,
                    help="Restrict the build to these task names only. Useful "
                         "when eval_results/ has rollouts for many tasks but "
                         "the experiment only cares about a subset (e.g. the "
                         "10-task overfit run).")
    ap.add_argument("--images-mode", choices=("embed", "absolute"), default="embed",
                    help="'embed' (default): inline PNG bytes into parquet for portability; "
                         "'absolute': store local paths only (single-host workflow).")
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--no-smoke-test", action="store_true")
    ap.add_argument("--repo-root", type=Path, default=Path("."),
                    help="Repo root for git-sha lookups")
    args = ap.parse_args()

    eval_root: Path = args.eval_results.resolve()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = discover_runs(eval_root)
    log.info("discovered %d runs", len(runs))

    funnel = FilterFunnel()
    survivors: list[CandidateTuple] = []
    system_prompts_seen: set[str] = set()
    canonical_system_prompt = ""

    task_filter = set(args.tasks) if args.tasks else None
    if task_filter:
        log.info("task filter: %d tasks (%s)", len(task_filter), sorted(task_filter))

    for run in runs:
        for task, repeat, inst, path in iter_succ_rollouts(run):
            if task_filter and task not in task_filter:
                continue
            funnel.rollouts_seen += 1
            funnel.rollouts_after_succ_filter += 1  # all `_succ.jsonl` by construction
            steps = parse_rollout(path)
            if steps is None:
                continue
            if not all_steps_parseable(steps):
                continue
            funnel.rollouts_after_parse_gate += 1
            if not all_images_loadable(steps):
                continue
            funnel.rollouts_after_image_check += 1
            survivors.append((run, task, repeat, inst, path, steps))
            # Track system prompts to ensure they agree.
            for step in steps:
                for m in step.get("conversations", []):
                    if m.get("role") == "system":
                        system_prompts_seen.add(m.get("content", ""))
                        if not canonical_system_prompt:
                            canonical_system_prompt = m.get("content", "")
                        break

    if len(system_prompts_seen) > 1:
        log.warning("MULTIPLE system prompts seen (%d distinct). Manifest hash will be of the first encountered.",
                    len(system_prompts_seen))

    log.info("rollouts after parse + image gates: %d", len(survivors))

    chosen = select_one_per_group(survivors)
    funnel.rollouts_after_dedupe = len(chosen)
    log.info("rollouts after (task, seed) dedupe: %d", len(chosen))

    records = build_records(chosen)
    funnel.steps_after_dedupe = len(records)
    log.info("step records: %d", len(records))

    # Step 5: train/val split — rollout-level, stratified by task, deterministic.
    train_records, val_records = split_train_val(
        records, val_frac=args.val_frac, seed=args.val_split_seed
    )
    log.info(
        "split: %d train rows / %d val rows (val_frac=%.2f, seed=%d)",
        len(train_records), len(val_records), args.val_frac, args.val_split_seed,
    )

    rng = random.Random(args.shuffle_seed)
    rng.shuffle(train_records)
    rng.shuffle(val_records)

    parquet_path = out_dir / "train.parquet"
    write_parquet(train_records, parquet_path, images_mode=args.images_mode)
    if val_records:
        val_path = out_dir / "val.parquet"
        write_parquet(val_records, val_path, images_mode=args.images_mode)

    # Stats
    stats = compute_stats(records, funnel)
    plots_dir = out_dir / "stats" / "plots"
    plot_paths = {} if args.no_plots else make_plots(stats, plots_dir)
    write_stats_md(stats, out_dir / "stats" / "stats.md", plot_paths, eval_root)

    # Manifest + README
    write_manifest(out_dir / "manifest.json", records, runs, args.repo_root.resolve(), canonical_system_prompt)
    write_readme(out_dir / "README.md", len(records),
                 stats["headline"]["unique_rollouts"], stats["headline"]["unique_tasks"],
                 images_mode=args.images_mode)

    # Step 6: smoke test
    if args.no_smoke_test:
        log.info("smoke test skipped (--no-smoke-test)")
    else:
        smoke_test(parquet_path)

    log.info("DONE — outputs under %s", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
