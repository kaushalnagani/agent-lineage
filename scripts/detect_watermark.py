#!/usr/bin/env python3
"""Detect an XRF watermark and optionally enforce a session registry policy."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from watermark_lab import detect_watermark
from watermark_lab.registry import load_registry, match_tag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", help="Text to inspect; stdin is used when omitted")
    parser.add_argument("--redundancy", type=int, default=3)
    parser.add_argument("--registry")
    parser.add_argument("--destination-session")
    parser.add_argument("--secret-env", default="WATERMARK_SECRET")
    args = parser.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()
    detection = detect_watermark(text, redundancy=args.redundancy)
    result = asdict(detection)
    if detection.found and args.registry:
        secret = os.environ.get(args.secret_env)
        if not secret:
            parser.error(f"set {args.secret_env} when using --registry")
        match = match_tag(
            detection.tag_hex or "",
            load_registry(args.registry),
            secret,
            args.destination_session,
        )
        result["registry"] = asdict(match)
    print(json.dumps(result, indent=2))
    return 0 if detection.found else 1


if __name__ == "__main__":
    raise SystemExit(main())
