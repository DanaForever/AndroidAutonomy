"""Detect and drop rows whose tokenized seqlen collides with another row's.

Why: verl's seqlen-balancing micro-batch packer + torch.nested.as_nested_tensor
mis-infer the ragged dim of 3D position_ids when two samples in a micro-batch
share an identical post-tokenization sequence length, crashing in
`torch.nested.unbind`. The crash is deterministic across shuffles because the
balancer sorts by length, so any two same-length samples end up adjacent in
some micro-batch. With small homogenous datasets (e.g. 387 rows from 3 similar
tasks) collisions are routine; with large diverse datasets they're rare.

This script tokenizes every row of `train.parquet` with the actual Qwen3-VL
processor (text + image tokens), groups rows by total seqlen, and for any
seqlen with >1 row keeps just one row and drops the rest. The output is a new
parquet without collisions.

Usage (on superpod, in the verl conda env):

    python3 training/data/dedupe_seqlen.py \\
        --in training/data/sft_overfit_failed_v0.1/train.parquet \\
        --out training/data/sft_overfit_failed_v0.1/train_dedup.parquet \\
        --model-path /home/thivt1/.cache/huggingface/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from PIL import Image
from transformers import AutoProcessor


def messages_to_processor_inputs(messages, images_field):
    """Re-render messages into (text, image_list) the processor expects.

    The parquet stores messages as a list of {role, content} dicts; for
    Qwen3-VL the content is either a string or a list of {type: text/image,
    text/image: ...} chunks. Images are stored separately in `images_field`
    as a list of {bytes: ...} dicts.
    """
    pil_images = []
    if images_field is not None:
        for img in images_field:
            if isinstance(img, dict) and "bytes" in img:
                pil_images.append(Image.open(io.BytesIO(img["bytes"])).convert("RGB"))
            elif hasattr(img, "tobytes"):  # rare: already a PIL image
                pil_images.append(img)
    # the processor.apply_chat_template / __call__ pipeline handles the structured
    # messages, so just return them as-is along with the images.
    return messages, pil_images


def compute_row_seqlen(row, processor) -> int:
    """Return total token count (text + image) for one parquet row."""
    messages = row["messages"]
    images = row.get("images", None) if isinstance(row, dict) else (
        row["images"] if "images" in row.index else None
    )
    msgs, pil_images = messages_to_processor_inputs(messages, images)

    # Apply chat template to get the prompt text with image placeholders.
    try:
        text = processor.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=False
        )
    except TypeError:
        # Some processor versions don't accept add_generation_prompt
        text = processor.apply_chat_template(msgs, tokenize=False)

    if pil_images:
        inputs = processor(text=[text], images=pil_images, return_tensors="pt")
    else:
        inputs = processor(text=[text], return_tensors="pt")
    return int(inputs["input_ids"].shape[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", dest="outp", type=Path, required=True)
    ap.add_argument("--model-path", type=Path, required=True,
                    help="Local snapshot path for AutoProcessor.from_pretrained")
    ap.add_argument("--report-only", action="store_true",
                    help="Just print collision stats; don't write a new parquet.")
    args = ap.parse_args()

    print(f"loading processor from {args.model_path}", file=sys.stderr)
    processor = AutoProcessor.from_pretrained(str(args.model_path))

    print(f"loading parquet from {args.inp}", file=sys.stderr)
    df = pd.read_parquet(args.inp)
    print(f"  rows: {len(df)}", file=sys.stderr)

    seqlens = []
    for i in range(len(df)):
        row = df.iloc[i]
        try:
            sl = compute_row_seqlen(row, processor)
        except Exception as e:
            print(f"  row {i}: tokenization failed ({type(e).__name__}: {e})", file=sys.stderr)
            sl = -1
        seqlens.append(sl)
        if (i + 1) % 25 == 0 or i == len(df) - 1:
            print(f"  tokenized {i + 1}/{len(df)}", file=sys.stderr)

    df = df.copy()
    df["_seqlen"] = seqlens

    # Group by seqlen, find collisions.
    by_len = defaultdict(list)
    for i, sl in enumerate(seqlens):
        by_len[sl].append(i)

    collisions = {k: v for k, v in by_len.items() if len(v) > 1 and k > 0}
    print(f"\n=== collision report ===", file=sys.stderr)
    print(f"distinct seqlens: {len(by_len)}", file=sys.stderr)
    print(f"colliding seqlens (>=2 rows): {len(collisions)}", file=sys.stderr)
    if collisions:
        # Show the worst 10
        worst = sorted(collisions.items(), key=lambda kv: -len(kv[1]))[:10]
        for sl, idxs in worst:
            tasks = df.loc[idxs, "task_name"].tolist() if "task_name" in df.columns else ["?"] * len(idxs)
            print(f"  seqlen={sl}: {len(idxs)} rows, indices={idxs[:5]}{'...' if len(idxs) > 5 else ''}, "
                  f"tasks={tasks[:5]}", file=sys.stderr)

    if args.report_only:
        return 0

    # Keep one row per colliding seqlen (the first, which is also kept for unique seqlens).
    keep_mask = [False] * len(df)
    seen = set()
    for i, sl in enumerate(seqlens):
        if sl <= 0:
            continue  # skip tokenization failures
        if sl not in seen:
            keep_mask[i] = True
            seen.add(sl)
    kept = df[pd.Series(keep_mask)]

    # Drop the helper column before writing.
    kept = kept.drop(columns=["_seqlen"])
    args.outp.parent.mkdir(parents=True, exist_ok=True)
    kept.to_parquet(args.outp, index=False)
    print(f"\nwrote {len(kept)} rows (dropped {len(df) - len(kept)}) to {args.outp}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
