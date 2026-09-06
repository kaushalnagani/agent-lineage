#!/usr/bin/env python3
"""Generate a JSONL corpus for benchmarking through the OpenAI Responses API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", required=True, help="JSONL with a 'prompt' field")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--min-words", type=int, default=100)
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("set OPENAI_API_KEY in your shell; do not put it in source files")
    try:
        from openai import OpenAI
    except ImportError as error:
        raise SystemExit("install with: pip install -e '.[openai]'") from error

    prompts = [json.loads(line) for line in Path(args.prompts).read_text(encoding="utf-8").splitlines() if line.strip()]
    client = OpenAI()
    with Path(args.output).open("w", encoding="utf-8") as output:
        for index, item in enumerate(prompts):
            response = client.responses.create(
                model=args.model,
                input=(
                    f"Answer accurately in at least {args.min_words} words. Preserve exact names, "
                    f"numbers, dates, code, commands, and citations.\n\n{item['prompt']}"
                ),
            )
            output.write(json.dumps({"id": index, "prompt": item["prompt"], "text": response.output_text}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

