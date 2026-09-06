#!/usr/bin/env python3
"""Benchmark XRF capacity, fidelity, robustness, and false positives."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from watermark_lab import CapacityError, WatermarkConfig, detect_watermark, embed_watermark
from watermark_lab.attacks import ATTACKS
from watermark_lab.core import capacity, rendered_equivalent, session_tag


DEFAULT_TEXTS = [
    (
        "The monitoring service reviews every generated response before it enters another "
        "agent context and records relevant provenance information for later security analysis. "
    ) * 8,
    (
        "A careful evaluation measures detection accuracy, false alarms, payload recovery, "
        "formatting stability, processing latency, and resistance to routine text transformations. "
    ) * 8,
    (
        "Researchers should preserve factual statements while testing whether an embedded signal "
        "survives copying, normalization, partial corruption, and movement across storage systems. "
    ) * 8,
]


def load_texts(path: str | None) -> list[str]:
    if path is None:
        return DEFAULT_TEXTS
    texts: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        texts.append(item["text"] if isinstance(item, dict) else str(item))
    return texts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl")
    parser.add_argument("--secret", default="development-secret-change-me")
    parser.add_argument("--tag-bytes", type=int, default=8)
    parser.add_argument("--redundancy", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--false-positive-samples", type=int, default=1000)
    args = parser.parse_args()

    config = WatermarkConfig(args.tag_bytes, args.redundancy)
    rng = random.Random(args.seed)
    texts = load_texts(args.input_jsonl)
    rows: list[dict[str, object]] = []
    expected = session_tag(args.secret, "benchmark-session", args.tag_bytes).hex()

    for index, text in enumerate(texts):
        base = {
            "sample": index,
            **capacity(text, config),
        }
        try:
            marked = embed_watermark(text, "benchmark-session", args.secret, config)
        except CapacityError as error:
            rows.append({**base, "encoded": False, "error": str(error)})
            continue
        for attack_name, attack in ATTACKS.items():
            attacked = attack(marked, rng)
            detected = detect_watermark(attacked, args.redundancy)
            rows.append(
                {
                    **base,
                    "encoded": True,
                    "attack": attack_name,
                    "rendered_equivalent_before_attack": rendered_equivalent(text, marked),
                    "detected": detected.found,
                    "exact_tag": detected.tag_hex == expected,
                    "confidence": detected.confidence,
                    "corrected_groups": detected.corrected_groups,
                    "raw_character_overhead": len(marked) - len(text),
                }
            )

    false_positives = 0
    for index in range(args.false_positive_samples):
        plain = f"Plain unmarked sample number {index} contains ordinary words for detector calibration. " * 8
        false_positives += int(detect_watermark(plain, args.redundancy).found)

    successful = [row for row in rows if row.get("encoded")]
    attack_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"trials": 0, "detected": 0, "exact_tag": 0})
    for row in successful:
        attack = str(row["attack"])
        attack_totals[attack]["trials"] += 1
        attack_totals[attack]["detected"] += int(bool(row["detected"]))
        attack_totals[attack]["exact_tag"] += int(bool(row["exact_tag"]))
    attack_summary = {
        attack: {
            **counts,
            "detection_rate": counts["detected"] / counts["trials"],
            "exact_recovery_rate": counts["exact_tag"] / counts["trials"],
        }
        for attack, counts in sorted(attack_totals.items())
    }
    summary = {
        "config": {
            "tag_bytes": args.tag_bytes,
            "redundancy": args.redundancy,
            "minimum_eligible_words": config.minimum_carriers,
        },
        "encoded_samples": len({row["sample"] for row in successful}),
        "attack_summary": attack_summary,
        "results": rows,
        "false_positive_samples": args.false_positive_samples,
        "false_positives": false_positives,
        "false_positive_rate": false_positives / args.false_positive_samples if args.false_positive_samples else 0.0,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
