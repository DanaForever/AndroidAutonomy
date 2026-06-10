#!/usr/bin/env python3
"""Build training artifacts from annotated manual curation traces.

Default output is QwenAgent-style JSONL because it is easy to inspect and can
be validated with the existing response parser. Use ``--write-parquet`` to also
write a small verl-style parquet when pyarrow is installed.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from response_validation import is_parseable  # noqa: E402


SYSTEM_PROMPT = """# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{"type": "function", "function": {"name": "mobile_use", "description": "Use a touchscreen to interact with a mobile device, and take screenshots.\\n* This is an interface to a mobile device with touchscreen. You can perform actions like clicking, typing, swiping, etc.\\n* Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions.\\n* The screen's resolution is 999x999.\\n* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked.", "parameters": {"properties": {"action": {"description": "The action to perform. The available actions are:\\n* `click`: Click the point on the screen with coordinate (x, y).\\n* `long_press`: Press the point on the screen with coordinate (x, y) for specified seconds.\\n* `swipe`: Swipe from the starting point with coordinate (x, y) to the end point with coordinates2 (x2, y2).\\n* `type`: Input the specified text into the activated input box.\\n* `answer`: Output the answer.\\n* `system_button`: Press the system button.\\n* `wait`: Wait specified seconds for the change to happen.\\n* `terminate`: Terminate the current task and report its completion status.", "enum": ["click", "long_press", "swipe", "type", "answer", "system_button", "wait", "terminate"], "type": "string"}, "coordinate": {"description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required only by `action=click`, `action=long_press`, and `action=swipe`.", "type": "array"}, "coordinate2": {"description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required only by `action=swipe`.", "type": "array"}, "text": {"description": "Required only by `action=type` and `action=answer`.", "type": "string"}, "time": {"description": "The seconds to wait. Required only by `action=long_press` and `action=wait`.", "type": "number"}, "button": {"description": "Back means returning to the previous interface, Home means returning to the desktop, Menu means opening the application background menu, and Enter means pressing the enter. Required only by `action=system_button`", "enum": ["Back", "Home", "Menu", "Enter"], "type": "string"}, "status": {"description": "The status of the task. Required only by `action=terminate`.", "type": "string", "enum": ["success", "failure"]}}, "required": ["action"], "type": "object"}}}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>

# Response format

Response format for every step:
1) Thought: one concise sentence explaining the next move (no multi-step reasoning).
2) Action: a short imperative describing what to do in the UI.
3) A single <tool_call>...</tool_call> block containing only the JSON: {"name": <function-name>, "arguments": <args-json-object>}.

Rules:
- Output exactly in the order: Thought, Action, <tool_call>.
- Be brief: one sentence for Thought, one sentence for Action.
- Do not output anything else outside those three parts.
- If finishing, use action=terminate in the tool call.
"""


def iter_traces(root: Path) -> list[Path]:
    return sorted(root.glob("*/trajectories/traj_*/trace.json"))


def render_user(goal: str, history: list[str]) -> str:
    parts = [f"The user query: {goal}", ""]
    if history:
        parts.append("Task progress (You have done the following operations on the current device):")
        parts.extend(f"Step{i + 1}: {h}" for i, h in enumerate(history))
        parts.append("")
    parts.append("Current Screenshot: <image>")
    parts.append("")
    parts.append("Please analyze the current screenshot and history to generate the next step.")
    return "\n".join(parts)


def action_to_tool_args(action: dict[str, Any]) -> dict[str, Any]:
    atype = action.get("type")
    if atype in {"click", "long_press"}:
        return {"action": atype, "coordinate": action["qwen"]}
    if atype == "swipe":
        return {
            "action": "swipe",
            "coordinate": action["qwen"][0],
            "coordinate2": action["qwen"][1],
        }
    if atype == "type":
        return {"action": "type", "text": action.get("text", "")}
    if atype == "system_button":
        return {"action": "system_button", "button": action.get("button", "Back")}
    if atype == "wait":
        return {"action": "wait", "time": max(1, round(action.get("duration_ms", 1000) / 1000))}
    if atype == "terminate":
        return {"action": "terminate", "status": action.get("status", "success")}
    raise ValueError(f"unsupported action type: {atype}")


def assistant_response(variant: dict[str, str], action: dict[str, Any]) -> str:
    payload = {"name": "mobile_use", "arguments": action_to_tool_args(action)}
    return (
        f"Thought: {variant['thought']}\n"
        f"Action: {variant['action']}\n"
        "<tool_call>\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        "</tool_call>"
    )


def clamp(value: int, lo: int = 0, hi: int = 999) -> int:
    return max(lo, min(hi, value))


def jitter_action(action: dict[str, Any], px: int, screen_width: int, screen_height: int) -> dict[str, Any]:
    if px <= 0:
        return json.loads(json.dumps(action))
    if action.get("type") not in {"click", "long_press", "swipe"}:
        return json.loads(json.dumps(action))
    if action.get("type") in {"click", "long_press"}:
        pixel = action.get("pixel")
        if not _coord(pixel):
            return json.loads(json.dumps(action))
        dx = random.randint(-px, px)
        dy = random.randint(-px, px)
        new_pixel = [
            max(0, min(screen_width - 1, int(pixel[0]) + dx)),
            max(0, min(screen_height - 1, int(pixel[1]) + dy)),
        ]
        out = json.loads(json.dumps(action))
        out["pixel"] = new_pixel
        out["qwen"] = [
            clamp(round(new_pixel[0] * 999 / screen_width)),
            clamp(round(new_pixel[1] * 999 / screen_height)),
        ]
        out["augmentation"] = {"coordinate_jitter_px": [dx, dy]}
        return out
    pixel_pair = action.get("pixel")
    if not _coord_pair(pixel_pair):
        return json.loads(json.dumps(action))
    out = json.loads(json.dumps(action))
    out_pixels = []
    out_qwen = []
    jitter = []
    for pixel in pixel_pair:
        dx = random.randint(-px, px)
        dy = random.randint(-px, px)
        new_pixel = [
            max(0, min(screen_width - 1, int(pixel[0]) + dx)),
            max(0, min(screen_height - 1, int(pixel[1]) + dy)),
        ]
        out_pixels.append(new_pixel)
        out_qwen.append([
            clamp(round(new_pixel[0] * 999 / screen_width)),
            clamp(round(new_pixel[1] * 999 / screen_height)),
        ])
        jitter.append([dx, dy])
    out["pixel"] = out_pixels
    out["qwen"] = out_qwen
    out["augmentation"] = {"coordinate_jitter_px": jitter}
    return out


def _coord(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value)


def _coord_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and _coord(value[0]) and _coord(value[1])


def safe_to_jitter(trace: dict[str, Any], step: dict[str, Any]) -> bool:
    action = step.get("action", {})
    return action.get("type") in {"click", "long_press", "swipe"}


def build_rollout(trace_path: Path, variant_idx: int, jitter_px: int) -> list[dict[str, Any]]:
    trace = json.loads(trace_path.read_text())
    trace_dir = trace_path.parent
    goal = trace.get("goal", "")
    screen_width = int(trace.get("device", {}).get("screen_width") or 1)
    screen_height = int(trace.get("device", {}).get("screen_height") or 1)
    history: list[str] = []
    rows: list[dict[str, Any]] = []
    for step_idx, step in enumerate(trace.get("steps", [])):
        variants = step.get("llm_variants") or []
        if not variants:
            raise ValueError(f"{trace_path} step {step_idx} missing llm_variants")
        variant = variants[min(variant_idx, len(variants) - 1)]
        if variant.get("needs_review"):
            raise ValueError(f"{trace_path} step {step_idx} marked needs_review")
        action = step.get("action", {})
        if variant_idx > 0 and safe_to_jitter(trace, step):
            action = jitter_action(action, jitter_px, screen_width, screen_height)
        response = assistant_response(variant, action)
        if not is_parseable(response):
            raise ValueError(f"unparseable response in {trace_path} step {step_idx}: {response}")
        screenshot = step.get("screenshot")
        image_path = str((trace_dir / screenshot).resolve()) if screenshot else ""
        user = render_user(goal, history)
        rows.append({
            "task_id": f"manual-{trace.get('task_name')}-{trace.get('trajectory_id')}-v{variant_idx:02d}-s{step_idx:03d}",
            "task_name": trace.get("task_name"),
            "index": step_idx,
            "conversations": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
                {"role": "assistant", "content": response},
            ],
            "images": [image_path] if image_path else [],
            "is_success": True,
            "manual_trace": str(trace_path),
            "params": trace.get("params", {}),
            "goal": goal,
            "variant_index": variant_idx,
        })
        history.append(variant["action"])
    return rows


def write_jsonl_for_trace(trace_path: Path, output_root: Path, num_variants: int, jitter_px: int) -> list[Path]:
    trace = json.loads(trace_path.read_text())
    task = trace.get("task_name", "unknown")
    task_dir = output_root / task
    task_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    for variant_idx in range(num_variants):
        rows = build_rollout(trace_path, variant_idx, jitter_px)
        out_path = task_dir / f"{trace.get('trajectory_id', trace_path.parent.name)}_variant_{variant_idx:02d}_succ.jsonl"
        with out_path.open("w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        out_paths.append(out_path)
    return out_paths


def write_parquet(jsonl_root: Path, parquet_path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise SystemExit("pyarrow is required for --write-parquet") from e

    records: list[dict[str, Any]] = []
    for path in sorted(jsonl_root.glob("*/*_succ.jsonl")):
        with path.open() as f:
            for line in f:
                row = json.loads(line)
                images = []
                for img in row.get("images", []):
                    images.append({"bytes": Path(img).read_bytes()})
                records.append({
                    "messages": row["conversations"],
                    "images": images,
                    "goal": row["conversations"][1]["content"].split("\n", 1)[0],
                    "history": [],
                    "image_path": row["images"][0] if row.get("images") else "",
                    "assistant_response": row["conversations"][2]["content"],
                    "template_id": "manual_curation_v1",
                    "task_name": row["task_name"],
                    "repeat_id": row.get("variant_index", 0),
                    "step_index": row["index"],
                    "source_run_id": "manual_curation",
                })
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), parquet_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--annotated-root", type=Path, default=Path("training/data/manual_curation/annotated"))
    p.add_argument("--jsonl-out", type=Path, default=Path("training/data/manual_curation/qwen_jsonl"))
    p.add_argument("--num-variants", type=int, default=3)
    p.add_argument("--coordinate-jitter-px", type=int, default=2)
    p.add_argument("--clean", action="store_true")
    p.add_argument("--write-parquet", action="store_true")
    p.add_argument("--parquet-out", type=Path, default=Path("training/data/sft_manual_failed_v0/train.parquet"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    traces = iter_traces(args.annotated_root)
    if not traces:
        raise SystemExit(f"No annotated traces found under {args.annotated_root}")
    if args.clean and args.jsonl_out.exists():
        shutil.rmtree(args.jsonl_out)
    random.seed(42)
    written: list[Path] = []
    for trace_path in traces:
        written.extend(write_jsonl_for_trace(trace_path, args.jsonl_out, args.num_variants, args.coordinate_jitter_px))
    print(f"wrote {len(written)} jsonl rollouts under {args.jsonl_out}")
    if args.write_parquet:
        write_parquet(args.jsonl_out, args.parquet_out)
        print(f"wrote {args.parquet_out}")


if __name__ == "__main__":
    main()
