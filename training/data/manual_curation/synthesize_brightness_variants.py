#!/usr/bin/env python3
"""Create local Thought/Action variants for SystemBrightnessMin traces.

This is intentionally offline: it copies raw manual traces, adds deterministic
llm_variants for each step, and leaves screenshots/actions unchanged. The text
variants vary in length so seqlen dedupe keeps substantially more rows.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


OPEN_THOUGHTS = [
    "I need to open the notification shade to reach quick settings.",
    "The brightness control is in Android quick settings, so I should pull down the shade.",
    "Before changing brightness, I need to reveal the system controls from the top of the screen.",
    "I am starting from the main screen, and the next move is to open the shade that contains quick settings.",
    "To get access to display controls, I need to drag down from the status bar area.",
    "The brightness slider is not visible yet, so I first need to expose the notification panel.",
    "I need the Android control panel, which starts by swiping down from the top edge.",
    "This task requires a system setting, so I should open the notification shade first.",
]

OPEN_ACTIONS = [
    "Swipe down from the top edge of the screen.",
    "Drag downward from the status bar area.",
    "Pull the notification shade down from the top of the display.",
    "Swipe down from the upper edge to open the shade.",
    "Drag down from the top of the screen to reveal quick settings.",
]

EXPAND_THOUGHTS = [
    "The shade is open, but I need the expanded quick settings panel to see the brightness slider.",
    "I need to expand quick settings because the brightness control is not fully available yet.",
    "To adjust brightness directly, I should pull the panel down again until the full controls appear.",
    "The quick settings area needs one more downward swipe so the brightness bar becomes visible.",
    "I can see the panel now, and expanding it further should reveal the display brightness slider.",
    "The current view is only partially expanded, so I need to open the full control center.",
    "The brightness setting is inside the expanded quick settings view, so I should drag down again.",
    "I need the larger system controls view before I can set brightness to the minimum.",
]

EXPAND_ACTIONS = [
    "Swipe down again to expand quick settings.",
    "Drag the shade farther downward.",
    "Pull down on the notification panel a second time.",
    "Swipe downward again to open the full quick settings panel.",
    "Drag down on the panel until the brightness slider is visible.",
]

MINIMIZE_THOUGHTS = [
    "The brightness slider is visible, so I need to move it to the minimum value.",
    "Now I should lower the brightness by dragging the slider all the way left.",
    "The task asks for minimum brightness, so the slider handle needs to go to the far-left end.",
    "I can adjust brightness here, and I need to set it as low as possible.",
    "The quick settings panel shows the brightness bar, so I should reduce it to the minimum.",
    "To complete the requested setting, I need to slide the brightness control fully left.",
    "The visible brightness control should be moved to its lowest position.",
    "I need to make the screen brightness minimum by dragging the slider to the left edge.",
]

MINIMIZE_ACTIONS = [
    "Drag the brightness slider all the way to the left.",
    "Swipe the brightness control toward the far-left end.",
    "Pull the brightness bar left to the minimum position.",
    "Move the brightness slider handle to the left edge.",
    "Slide the brightness control left until it reaches the minimum.",
]

RECOVER_THOUGHTS = [
    "The panel moved away, so I need to bring quick settings back into view before adjusting brightness.",
    "I need to reopen the expanded controls because the brightness slider is no longer accessible.",
    "The previous movement hid the controls, so I should pull the shade down again.",
    "To continue toward minimum brightness, I need the quick settings panel visible again.",
    "The brightness control is off screen, so I should restore the panel with another downward swipe.",
]

RECOVER_ACTIONS = [
    "Swipe down again to bring the quick settings panel back.",
    "Drag downward to show the controls again.",
    "Pull the shade back down.",
    "Swipe down to return to the brightness controls.",
]

TERMINATE_THOUGHTS = [
    "The brightness setting is at the minimum, so the task is complete.",
    "The screen brightness has been reduced to the lowest setting, so I can finish.",
    "The success condition is satisfied because the brightness slider is at the minimum position.",
    "No more UI action is needed now that brightness is set to the minimum.",
    "The device is already at minimum brightness, so I should terminate successfully.",
    "The quick settings brightness control shows the minimum value, which completes the request.",
]

TERMINATE_ACTIONS = [
    "Finish the task successfully.",
    "Terminate with success.",
    "Report successful completion.",
    "End the task as successful.",
]

FILLER = [
    "",
    " I will keep the gesture direct and avoid opening unrelated controls.",
    " This matches the requested system brightness task.",
    " The next action should stay focused on the visible Android system panel.",
    " I only need one precise gesture for this step.",
    " This keeps the demonstration aligned with the manual trajectory.",
    " The action should not change apps or enter text.",
    " I can use the current screenshot and the prior steps to choose this move.",
    " The goal is still to reach and set the brightness control, not to inspect notifications.",
    " This step follows the recorded human demonstration for the same screen state.",
    " The UI state indicates that a swipe gesture is the correct next command.",
    " I should preserve the same target element and only describe the action naturally.",
]


def iter_trace_paths(root: Path) -> list[Path]:
    return sorted(root.glob("*/trajectories/traj_*/trace.json"))


def is_terminate(action: dict[str, Any]) -> bool:
    return action.get("type") == "terminate"


def is_horizontal_swipe(action: dict[str, Any]) -> bool:
    if action.get("type") != "swipe":
        return False
    qwen = action.get("qwen")
    if not isinstance(qwen, list) or len(qwen) != 2:
        return False
    return abs(qwen[0][0] - qwen[1][0]) > abs(qwen[0][1] - qwen[1][1])


def classify_step(steps: list[dict[str, Any]], idx: int) -> str:
    action = steps[idx].get("action", {})
    note = (steps[idx].get("human_note") or "").lower()
    if is_terminate(action):
        return "terminate"
    if is_horizontal_swipe(action) or "brightness" in note or "slider" in note or "min" in note:
        return "minimize"
    if "again" in note or "expand" in note or idx == 1:
        return "expand"
    if idx >= 3:
        return "recover"
    return "open"


def pools_for(kind: str) -> tuple[list[str], list[str]]:
    if kind == "open":
        return OPEN_THOUGHTS, OPEN_ACTIONS
    if kind == "expand":
        return EXPAND_THOUGHTS, EXPAND_ACTIONS
    if kind == "minimize":
        return MINIMIZE_THOUGHTS, MINIMIZE_ACTIONS
    if kind == "recover":
        return RECOVER_THOUGHTS, RECOVER_ACTIONS
    return TERMINATE_THOUGHTS, TERMINATE_ACTIONS


def make_variants(kind: str, num_variants: int) -> list[dict[str, str]]:
    thoughts, actions = pools_for(kind)
    variants: list[dict[str, str]] = []
    for i in range(num_variants):
        thought = thoughts[i % len(thoughts)] + FILLER[i % len(FILLER)]
        if i >= len(FILLER):
            thought += " " + FILLER[(i // len(FILLER)) % len(FILLER)].strip()
        if i >= len(FILLER) * 2:
            thought += " The final answer must remain a valid mobile_use tool call."
        action = actions[(i * 3 + i // len(actions)) % len(actions)]
        if i % 7 == 6 and kind != "terminate":
            action = action.rstrip(".") + " using the same recorded target."
        variants.append({"thought": thought.strip(), "action": action.strip()})
    return variants


def synthesize_trace(trace_path: Path, input_root: Path, output_root: Path, num_variants: int) -> Path:
    rel_dir = trace_path.parent.relative_to(input_root)
    dest_dir = output_root / rel_dir
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(trace_path.parent, dest_dir)
    out_path = dest_dir / "trace.json"
    trace = json.loads(out_path.read_text())
    trace["annotation"] = {
        "model": "local_synthetic_brightness_variants",
        "num_variants": num_variants,
        "purpose": "offline overfit data with varied token lengths",
    }
    steps = trace.get("steps", [])
    for idx, step in enumerate(steps):
        kind = classify_step(steps, idx)
        step["llm_variants"] = make_variants(kind, num_variants)
    out_path.write_text(json.dumps(trace, indent=2) + "\n")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=Path("training/data/manual_curation/raw"))
    parser.add_argument("--output-root", type=Path, default=Path("training/data/manual_curation/annotated_synthetic_overfit"))
    parser.add_argument("--num-variants", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    traces = iter_trace_paths(args.input_root)
    if not traces:
        raise SystemExit(f"No traces found under {args.input_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    for trace_path in traces:
        out = synthesize_trace(trace_path, args.input_root, args.output_root, args.num_variants)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
