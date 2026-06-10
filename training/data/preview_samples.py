#!/usr/bin/env python3
"""Render N parquet rows as human-readable HTML for spot-checking SFT data.

Produces:
    <preview-dir>/index.html         # gallery
    <preview-dir>/sample_NN.html     # one page per row
    <preview-dir>/sample_NN.png      # decoded screenshot (if images are embedded)

What you see per sample:
    - the screenshot the model sees
    - the rendered `messages` (system / user / assistant) verbatim
    - structured source fields (`goal`, `history`, `task_name`, `seed_key`, ...)
    - the chat-template-rendered string the HF processor will tokenize
    - a colour-highlighted view of which tokens contribute to loss
      (only when transformers + the pinned Qwen3-VL processor are available;
       otherwise this section is omitted and a note is shown)

Usage:
    python3 training/data/preview_samples.py \\
        --parquet training/data/sft_v0.1/train.parquet \\
        --out-dir training/data/sft_v0.1/preview \\
        --n 20 --stratify-by-task
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("preview_samples")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def pick_rows(table, n: int, stratify_by_task: bool, seed: int) -> list[int]:
    """Pick row indices, optionally one or more per task."""
    rng = random.Random(seed)
    n_rows = table.num_rows
    if not stratify_by_task or "task_name" not in table.column_names:
        return rng.sample(range(n_rows), min(n, n_rows))

    tasks = table.column("task_name").to_pylist()
    by_task: dict[str, list[int]] = {}
    for i, t in enumerate(tasks):
        by_task.setdefault(t, []).append(i)

    per_task = max(1, n // max(1, len(by_task)))
    chosen: list[int] = []
    for t in sorted(by_task):
        chosen.extend(rng.sample(by_task[t], min(per_task, len(by_task[t]))))
    rng.shuffle(chosen)
    return chosen[:n]


# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------
def extract_image(images_value: Any) -> bytes | None:
    """Return PNG bytes for the first image of a row, or None if unresolvable."""
    if not images_value:
        return None
    first = images_value[0]
    if isinstance(first, dict) and "bytes" in first:
        return bytes(first["bytes"])
    if isinstance(first, str):
        try:
            return Path(first).read_bytes()
        except OSError:
            return None
    if isinstance(first, (bytes, bytearray)):
        return bytes(first)
    return None


# ---------------------------------------------------------------------------
# Chat template + loss-mask rendering (optional)
# ---------------------------------------------------------------------------
def try_load_processor():
    """Return (processor, tokenizer) or (None, None) on any failure."""
    try:
        from transformers import AutoProcessor  # type: ignore

        processor = AutoProcessor.from_pretrained(
            "Qwen/Qwen3-VL-4B-Instruct",
            revision="ebb281ec70b05090aa6165b016eac8ec08e71b17",
            trust_remote_code=True,
        )
        return processor, getattr(processor, "tokenizer", None)
    except Exception as e:
        log.warning("processor unavailable: %s; loss-mask view disabled", e)
        return None, None


def render_chat_template(processor, messages: list[dict[str, str]]) -> str:
    """Apply the chat template without tokenising. Returns the literal string."""
    return processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )


def loss_mask_html(tokenizer, rendered: str, assistant_response: str) -> str:
    """Return HTML with the assistant span highlighted (loss-contributing tokens).

    Pragmatic approximation: locate the final assistant_response substring in
    the rendered chat-template string and shade that span. The verl collator
    masks everything outside this span with `-100`, so visually shading it
    matches what the loss is computed over.
    """
    idx = rendered.rfind(assistant_response)
    if idx < 0:
        return f"<pre>{html.escape(rendered)}</pre>"
    before = html.escape(rendered[:idx])
    span = html.escape(rendered[idx : idx + len(assistant_response)])
    after = html.escape(rendered[idx + len(assistant_response):])
    return (
        f"<pre>{before}"
        f"<mark class='loss'>{span}</mark>"
        f"{after}</pre>"
    )


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------
PAGE_CSS = """
:root { --paper:#f1ead8; --ink:#1c1611; --accent:#a23a1f; --rule:#d9cfb3; }
body { background:var(--paper); color:var(--ink); font-family: ui-monospace, "JetBrains Mono", monospace;
       font-size:13px; line-height:1.55; padding:24px 36px; max-width: 1100px; margin:0 auto; }
h1, h2 { font-family: Georgia, "Iowan Old Style", serif; }
h1 { font-size: 26px; margin: 0 0 8px; letter-spacing: -0.01em; }
h2 { font-size: 16px; border-bottom: 1px solid var(--rule); padding-bottom: 4px;
     margin: 28px 0 8px; color: var(--accent); }
img.screen { max-width: 360px; border: 1px solid var(--rule); display:block; }
table.fields { border-collapse: collapse; }
table.fields td { padding: 2px 12px 2px 0; vertical-align: top; }
table.fields td.k { color: #7a6c57; }
pre { background:#ffffff; border:1px solid var(--rule); padding:10px 12px; overflow-x:auto;
      white-space: pre-wrap; word-break: break-word; }
mark.loss { background: #ead488; color: var(--ink); padding: 0; }
.legend { font-size: 11px; color:#7a6c57; }
.legend mark.loss { padding: 0 4px; }
nav { font-size: 11px; margin-bottom: 16px; }
nav a { color: var(--accent); margin-right: 14px; text-decoration: none; }
.section-note { color:#7a6c57; font-style: italic; font-size: 11px; }
"""


def render_sample_page(
    idx: int,
    row: dict[str, Any],
    image_bytes: bytes | None,
    rendered_template: str | None,
    loss_mask_section: str | None,
    total: int,
) -> str:
    prev_link = f"sample_{idx-1:02d}.html" if idx > 0 else "index.html"
    next_link = f"sample_{idx+1:02d}.html" if idx + 1 < total else "index.html"

    fields_html = "".join(
        f"<tr><td class='k'>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in [
            ("task_name", row.get("task_name")),
            ("seed_key", row.get("seed_key", "—")),
            ("repeat_id", row.get("repeat_id")),
            ("instance_idx", row.get("instance_idx", "—")),
            ("step_index", row.get("step_index")),
            ("source_run_id", row.get("source_run_id")),
            ("template_id", row.get("template_id", "—")),
            ("image_path", row.get("image_path", "")),
        ]
    )

    if image_bytes is not None:
        img_html = (
            f"<img class='screen' src='sample_{idx:02d}.png' "
            f"alt='screenshot for sample {idx}'>"
        )
    else:
        img_html = "<p class='section-note'>(image unavailable)</p>"

    messages = row.get("messages") or []
    msg_blocks = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        msg_blocks.append(
            f"<h2>messages[{role}]</h2><pre>{html.escape(str(content))}</pre>"
        )

    if rendered_template is not None:
        template_section = (
            "<h2>chat template (literal string the processor sees)</h2>"
            "<p class='legend'>Yellow highlight = "
            "<mark class='loss'>tokens that contribute to loss</mark> "
            "(everything else is masked to -100).</p>"
            f"{loss_mask_section}"
        )
    else:
        template_section = (
            "<h2>chat template — not rendered</h2>"
            "<p class='section-note'>transformers / pinned processor unavailable; "
            "see preview log.</p>"
        )

    return f"""<!doctype html><html><head><meta charset='utf-8'>
<title>sft preview · sample {idx:02d} · {html.escape(str(row.get("task_name", "")))}</title>
<style>{PAGE_CSS}</style></head><body>
<nav><a href='index.html'>← gallery</a>
     <a href='{prev_link}'>prev</a>
     <a href='{next_link}'>next</a></nav>
<h1>sample {idx:02d} / {total-1:02d} · {html.escape(str(row.get("task_name", "")))}</h1>

<h2>screenshot (image[0])</h2>
{img_html}

<h2>source fields</h2>
<table class='fields'>{fields_html}</table>

{"".join(msg_blocks)}

{template_section}

</body></html>
"""


def render_index_page(rows: list[dict[str, Any]]) -> str:
    items = []
    for i, row in enumerate(rows):
        task = html.escape(str(row.get("task_name", "")))
        step = html.escape(str(row.get("step_index", "")))
        items.append(
            f"<li><a href='sample_{i:02d}.html'>sample_{i:02d}.html</a>"
            f" — <b>{task}</b>, step {step}</li>"
        )
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<title>sft preview · gallery</title>
<style>{PAGE_CSS}</style></head><body>
<h1>sft preview · {len(rows)} samples</h1>
<p class='legend'>Click any sample to see the screenshot, raw messages, and
the chat-template-rendered string with the loss-masked assistant span
highlighted.</p>
<ol>{"".join(items)}</ol>
</body></html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", type=Path, required=True,
                    help="Path to train.parquet (or val.parquet)")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Output directory; will be created")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--stratify-by-task", action="store_true",
                    help="Pick samples spread across tasks rather than uniformly random")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-template", action="store_true",
                    help="Skip the HF processor / loss-mask rendering")
    args = ap.parse_args()

    import pyarrow.parquet as pq

    table = pq.read_table(args.parquet)
    log.info("read %d rows from %s", table.num_rows, args.parquet)

    indices = pick_rows(table, args.n, args.stratify_by_task, args.seed)
    log.info("selected %d rows: %s", len(indices), indices)

    rows = table.take(indices).to_pylist()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.no_template:
        processor = tokenizer = None
    else:
        processor, tokenizer = try_load_processor()

    for i, row in enumerate(rows):
        # Image: decode and write next to the page
        image_bytes = extract_image(row.get("images"))
        if image_bytes is not None:
            (args.out_dir / f"sample_{i:02d}.png").write_bytes(image_bytes)

        # Chat template rendering
        rendered_template = None
        loss_mask_section = None
        if processor is not None:
            try:
                rendered_template = render_chat_template(processor, row.get("messages") or [])
                if tokenizer is not None and rendered_template is not None:
                    loss_mask_section = loss_mask_html(
                        tokenizer, rendered_template, row.get("assistant_response", "")
                    )
                else:
                    loss_mask_section = f"<pre>{html.escape(rendered_template)}</pre>"
            except Exception as e:
                log.warning("template render failed for row %d: %s", i, e)

        page = render_sample_page(
            idx=i, row=row, image_bytes=image_bytes,
            rendered_template=rendered_template,
            loss_mask_section=loss_mask_section,
            total=len(rows),
        )
        (args.out_dir / f"sample_{i:02d}.html").write_text(page)

    (args.out_dir / "index.html").write_text(render_index_page(rows))
    log.info("wrote %d sample pages + index.html under %s", len(rows), args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
