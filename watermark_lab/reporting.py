"""Diff and experiment reporting helpers."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from .core import _selector_to_byte, strip_watermark_characters


def text_metrics(original: str, marked: str) -> dict[str, Any]:
    visible = strip_watermark_characters(marked)
    original_words = original.split()
    visible_words = visible.split()
    return {
        "original_characters": len(original),
        "watermarked_characters": len(marked),
        "inserted_watermark_characters": len(marked) - len(visible),
        "original_words": len(original_words),
        "visible_words": len(visible_words),
        "visible_text_identical": original == visible,
        "visible_word_change_count": sum(
            1 for left, right in zip(original_words, visible_words) if left != right
        ) + abs(len(original_words) - len(visible_words)),
        "visible_similarity_ratio": difflib.SequenceMatcher(None, original, visible).ratio(),
    }


def codepoint_insertions(marked: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    visible_offset = 0
    for raw_offset, char in enumerate(marked):
        value = _selector_to_byte(char)
        if value is None:
            visible_offset += 1
            continue
        result.append(
            {
                "raw_offset": raw_offset,
                "visible_offset": visible_offset,
                "codepoint": f"U+{ord(char):04X}",
                "encoded_byte": value,
            }
        )
    return result


def unified_visible_diff(original: str, marked: str) -> str:
    visible = strip_watermark_characters(marked)
    lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        visible.splitlines(keepends=True),
        fromfile="original-visible.txt",
        tofile="watermarked-visible.txt",
    )
    diff = "".join(lines)
    return diff or "No human-visible text changes.\n"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

