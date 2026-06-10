#!/usr/bin/env python3
"""Generate Thought/Action variants for manual curation traces via vLLM.

Input traces are the raw output of ``tools/manual_curation/serve.py``.
This script does not mutate raw traces; it writes annotated copies under
``training/data/manual_curation/annotated``.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import random
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROMPT_TEMPLATE = """You are helping augment a human Android demonstration for SFT.

Generate {num_variants} alternative Thought/Action pairs for the same fixed
Android action. Do not change the action type, target UI element, text content,
button, or coordinates. The variants should be semantically equivalent and
short. Avoid adding facts not visible in the screenshot.

Rules for each variant:
- Thought: one concise sentence.
- Action: one short imperative sentence.
- The action description must match the provided action exactly.
- Do not mention coordinate numbers.
- If the screenshot does not support the action, return {{"needs_review": true}}.

Task goal:
{goal}

Previous actions:
{history}

Provided action:
{action_json}

Human note:
{human_note}

Return JSON:
{{
  "variants": [
    {{"thought": "...", "action": "..."}},
    {{"thought": "...", "action": "..."}}
  ]
}}"""


def iter_trace_paths(input_root: Path) -> list[Path]:
    return sorted(input_root.glob("*/trajectories/traj_*/trace.json"))


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def openai_chat_completion(
    *,
    base_url: str,
    model: str,
    prompt: str,
    image_path: Path | None,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image_path is not None:
        content.append({"type": "image_url", "image_url": {"url": data_url(image_path)}})
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content_text = body["choices"][0]["message"]["content"]
    return parse_json_response(content_text)


def history_for_step(steps: list[dict[str, Any]], idx: int) -> str:
    if idx == 0:
        return "(none)"
    lines: list[str] = []
    for s in steps[:idx]:
        note = s.get("human_note") or json.dumps(s.get("action", {}), ensure_ascii=False)
        lines.append(f"Step{s.get('step_index', len(lines))}: {note}")
    return "\n".join(lines)


def validate_variants(data: dict[str, Any], num_variants: int) -> list[dict[str, str]]:
    if data.get("needs_review"):
        return [{"needs_review": "true", "thought": "", "action": ""}]
    variants = data.get("variants")
    if not isinstance(variants, list):
        raise ValueError("LLM response missing variants list")
    out: list[dict[str, str]] = []
    for item in variants:
        if not isinstance(item, dict):
            continue
        thought = item.get("thought")
        action = item.get("action")
        if isinstance(thought, str) and isinstance(action, str) and thought.strip() and action.strip():
            out.append({"thought": thought.strip(), "action": action.strip()})
    if not out:
        raise ValueError("LLM response contained no usable variants")
    return out[:num_variants]


def fallback_variants(step: dict[str, Any], num_variants: int) -> list[dict[str, str]]:
    action = step.get("action", {})
    note = step.get("human_note") or "perform the provided action"
    if action.get("type") == "terminate":
        base = {
            "thought": "The task success criteria have been verified, so the task is complete.",
            "action": "Finish the task successfully.",
        }
    else:
        base = {
            "thought": f"I need to {note}.",
            "action": note[0].upper() + note[1:] + "." if note else "Perform the selected action.",
        }
    return [base.copy() for _ in range(num_variants)]


def annotate_trace(
    trace_path: Path,
    *,
    input_root: Path,
    output_root: Path,
    base_url: str,
    model: str,
    num_variants: int,
    temperature: float,
    max_tokens: int,
    timeout: int,
    dry_run: bool,
    coordinate_jitter_px: int,
) -> Path:
    trace = json.loads(trace_path.read_text())
    steps = trace.get("steps", [])
    source_dir = trace_path.parent
    rel_dir = trace_path.parent.relative_to(input_root)
    dest_dir = output_root / rel_dir
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(source_dir, dest_dir)
    annotated = json.loads((dest_dir / "trace.json").read_text())
    annotated["annotation"] = {
        "model": model,
        "num_variants": num_variants,
        "temperature": temperature,
        "coordinate_jitter_px": coordinate_jitter_px,
    }

    for idx, step in enumerate(annotated.get("steps", [])):
        screenshot = step.get("screenshot")
        image_path = dest_dir / screenshot if screenshot else None
        prompt = PROMPT_TEMPLATE.format(
            num_variants=num_variants,
            goal=annotated.get("goal", ""),
            history=history_for_step(steps, idx),
            action_json=json.dumps(step.get("action", {}), ensure_ascii=False),
            human_note=step.get("human_note", ""),
        )
        if dry_run:
            variants = fallback_variants(step, num_variants)
        else:
            if image_path is not None and not image_path.exists():
                raise FileNotFoundError(image_path)
            response = openai_chat_completion(
                base_url=base_url,
                model=model,
                prompt=prompt,
                image_path=image_path if image_path and image_path.exists() else None,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            variants = validate_variants(response, num_variants)
        step["llm_variants"] = variants

    out_path = dest_dir / "trace.json"
    out_path.write_text(json.dumps(annotated, indent=2) + "\n")
    return out_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", type=Path, default=Path("training/data/manual_curation/raw"))
    p.add_argument("--output-root", type=Path, default=Path("training/data/manual_curation/annotated"))
    p.add_argument("--vllm-base-url", required=True)
    p.add_argument("--model", default="Qwen3-VL-4B-Instruct")
    p.add_argument("--num-variants", type=int, default=3)
    p.add_argument("--temperature", type=float, default=0.4)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--coordinate-jitter-px", type=int, default=2)
    p.add_argument("--dry-run", action="store_true", help="Write deterministic placeholder variants without calling vLLM.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    traces = iter_trace_paths(args.input_root)
    if not traces:
        raise SystemExit(f"No traces found under {args.input_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    random.seed(42)
    for trace_path in traces:
        try:
            out = annotate_trace(
                trace_path,
                input_root=args.input_root,
                output_root=args.output_root,
                base_url=args.vllm_base_url,
                model=args.model,
                num_variants=args.num_variants,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                dry_run=args.dry_run,
                coordinate_jitter_px=args.coordinate_jitter_px,
            )
            print(f"wrote {out}")
        except (urllib.error.URLError, ValueError, OSError, KeyError) as e:
            print(f"ERROR {trace_path}: {e}", file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
