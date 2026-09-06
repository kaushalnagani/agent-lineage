#!/usr/bin/env python3
"""Add an XRF session watermark to text."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from watermark_lab import CapacityError, WatermarkConfig, embed_watermark
from watermark_lab.core import capacity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--text", help="Text to mark; stdin is used when omitted")
    parser.add_argument("--secret-env", default="WATERMARK_SECRET")
    parser.add_argument("--tag-bytes", type=int, default=8)
    parser.add_argument("--redundancy", type=int, default=3)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    secret = os.environ.get(args.secret_env)
    if not secret:
        parser.error(f"set {args.secret_env} to a secret of at least 16 characters")
    text = args.text if args.text is not None else sys.stdin.read()
    config = WatermarkConfig(tag_bytes=args.tag_bytes, redundancy=args.redundancy)
    if args.stats:
        print(json.dumps(capacity(text, config), indent=2), file=sys.stderr)
    try:
        print(embed_watermark(text, args.session_id, secret, config))
    except CapacityError as error:
        print(f"capacity error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
