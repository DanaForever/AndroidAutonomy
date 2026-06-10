#!/usr/bin/env python3
"""Summarise an AndroidWorld eval run into a flat JSON score file.

Reads `detailed_results.csv` produced by `run_android_world_local.sh` and writes
a `{baseline,trained}_scores.json` matching the schema in
tasks/training-codebase/sft-data/overfit-10-tasks.html.

Usage:
    python3 training/data/summarize_eval_scores.py \\
        --csv MARS-Voyager/eval_results/<MODEL>/logs/<TS>/detailed_results.csv \\
        --config MARS-Voyager/androidworld/eval/configs/eval_overfit10.yaml \\
        --out training/data/sft_v0.1/baseline_scores.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True,
                    help="Path to detailed_results.csv from the eval run")
    ap.add_argument("--config", type=Path, required=True,
                    help="Path to the eval YAML used for the run")
    ap.add_argument("--out", type=Path, required=True,
                    help="Output JSON path")
    ap.add_argument("--model-label", type=str, default=None,
                    help="Override the model label written into the JSON. "
                         "Defaults to llm.model from the config.")
    args = ap.parse_args()

    cfg = yaml.safe_load(args.config.read_text())
    expected_tasks: list[str] = list(cfg["eval"]["tasks"])
    n_combos: int = int(cfg["eval"]["n_task_combinations"])
    seed: int = int(cfg["eval"]["task_random_seed"])
    model_label = args.model_label or cfg["llm"]["model"]

    rows: dict[str, dict[str, str]] = {}
    with args.csv.open() as f:
        for row in csv.DictReader(f):
            rows[row["task_template"]] = row

    per_task: dict[str, int | dict] = {}
    total_completed = 0
    total_instances = 0
    missing: list[str] = []

    for task in expected_tasks:
        if task not in rows:
            missing.append(task)
            continue
        completed = int(rows[task]["num_complete_trials"])
        failed = int(rows[task]["num_fail_trials"])
        instances = completed + failed
        total_completed += completed
        total_instances += instances

        if n_combos == 1:
            per_task[task] = completed  # 0 or 1
        else:
            per_task[task] = {
                "completed": completed,
                "instances": instances,
                "rate": round(completed / instances, 4) if instances else 0.0,
            }

    summary: dict = {
        "model": model_label,
        "config": args.config.name,
        "task_random_seed": seed,
        "n_task_combinations": n_combos,
        "per_task": per_task,
        "total_completed": total_completed,
    }
    if n_combos == 1:
        summary["total_tasks"] = len(expected_tasks)
    else:
        summary["total_instances"] = total_instances
        summary["aggregate_rate"] = (
            round(total_completed / total_instances, 4) if total_instances else 0.0
        )
    if missing:
        summary["missing_tasks"] = missing

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {args.out}: {total_completed}/{total_instances or len(expected_tasks)}"
          f" completed across {len(expected_tasks)} tasks"
          + (f"; missing: {missing}" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
