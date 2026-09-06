#!/usr/bin/env python3
"""Generate Gemini samples and create a self-contained folder per simulation."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from watermark_lab import CapacityError, WatermarkConfig, detect_watermark, embed_watermark, session_tag
from watermark_lab.attacks import ATTACKS
from watermark_lab.core import capacity
from watermark_lab.reporting import codepoint_insertions, text_metrics, unified_visible_diff, write_json


DEFAULT_PROMPTS = [
    "Explain how a gateway can detect unauthorized communication between otherwise isolated AI agents.",
    "Describe the benefits and limitations of session-attributable text watermarking for autonomous agents.",
    "Explain why watermark detection should complement sandboxing, scoped credentials, and network controls.",
]


def load_secret_env(path: Path) -> None:
    """Load KEY=VALUE pairs without logging secret values or replacing real env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key and value:
            os.environ.setdefault(key, value)


def gemini_generate(api_key: str, model: str, prompt: str, min_words: int) -> tuple[str, dict]:
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model, safe="-._")
        + ":generateContent"
    )
    instruction = (
        f"Write one factual, self-contained paragraph of at least {min_words} words. "
        "Do not use Markdown tables or code blocks. Use complete sentences. "
        "Preserve exact names, quantities, dates, negation, commands, citations, and security terminology. "
        f"Topic: {prompt}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": instruction}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": max(256, min_words * 3),
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        # Google error bodies should not contain the request header/key, but
        # avoid printing the entire response in case a proxy echoes headers.
        raise RuntimeError(f"Gemini API returned HTTP {error.code}: {body[:500]}") from error
    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise RuntimeError("Gemini API returned no text candidate")
    usage = result.get("usageMetadata", {})
    return text, usage


def run_one(
    directory: Path,
    original: str,
    prompt: str,
    model: str,
    usage: dict,
    session_id: str,
    secret: str,
    config: WatermarkConfig,
    seed: int,
) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "original.txt").write_text(original + "\n", encoding="utf-8")
    cap = capacity(original, config)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt": prompt,
        "session_id": session_id,
        "session_tag": session_tag(secret, session_id, config.tag_bytes).hex(),
        "config": asdict(config),
        "capacity": cap,
        "usage": usage,
    }
    write_json(directory / "metadata.json", metadata)

    try:
        marked = embed_watermark(original, session_id, secret, config)
    except CapacityError as error:
        result = {"encoded": False, "error": str(error), "capacity": cap}
        write_json(directory / "metrics.json", result)
        return result

    (directory / "watermarked.txt").write_text(marked + "\n", encoding="utf-8")
    (directory / "visible_diff.txt").write_text(unified_visible_diff(original, marked), encoding="utf-8")
    write_json(directory / "codepoint_diff.json", codepoint_insertions(marked))

    detection = detect_watermark(marked, config.redundancy)
    write_json(directory / "detection.json", asdict(detection))
    metrics = {
        "encoded": True,
        **text_metrics(original, marked),
        "detection_found": detection.found,
        "exact_session_tag_recovered": detection.tag_hex == metadata["session_tag"],
        "detection_confidence": detection.confidence,
    }
    write_json(directory / "metrics.json", metrics)

    rng = random.Random(seed)
    attack_results: dict[str, dict] = {}
    attacks_dir = directory / "attacks"
    attacks_dir.mkdir()
    for name, transform in ATTACKS.items():
        attacked = transform(marked, rng)
        (attacks_dir / f"{name}.txt").write_text(attacked + "\n", encoding="utf-8")
        found = detect_watermark(attacked, config.redundancy)
        attack_results[name] = {
            **asdict(found),
            "exact_session_tag_recovered": found.tag_hex == metadata["session_tag"],
        }
    write_json(directory / "attack_results.json", attack_results)
    return {**metrics, "attacks": attack_results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-env-file", default="secret.env")
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--output-root", default="simulations")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--min-words", type=int, default=120)
    parser.add_argument("--tag-bytes", type=int, default=8)
    parser.add_argument("--redundancies", type=int, nargs="+", default=[1, 3])
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    load_secret_env(Path(args.secret_env_file))
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        parser.error("GOOGLE_API_KEY or GEMINI_API_KEY was not found")
    watermark_secret = os.environ.get("WATERMARK_SECRET")
    if not watermark_secret:
        # The API key must never double as the watermark secret.
        watermark_secret = os.urandom(32).hex()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = Path(args.output_root) / f"gemini-{stamp}"
    run_root.mkdir(parents=True, exist_ok=False)
    write_json(
        run_root / "run_config.json",
        {
            "model": args.model,
            "samples": args.samples,
            "min_words": args.min_words,
            "tag_bytes": args.tag_bytes,
            "redundancies": args.redundancies,
            "seed": args.seed,
            "api_key_recorded": False,
            "watermark_secret_source": "WATERMARK_SECRET" if os.environ.get("WATERMARK_SECRET") else "ephemeral-run-secret",
        },
    )

    all_results: list[dict] = []
    for sample_index in range(args.samples):
        prompt = DEFAULT_PROMPTS[sample_index % len(DEFAULT_PROMPTS)]
        original, usage = gemini_generate(api_key, args.model, prompt, args.min_words)
        for redundancy in args.redundancies:
            session_id = f"gemini-{stamp}-sample-{sample_index + 1}"
            name = f"simulation-{sample_index + 1:03d}-r{redundancy}"
            result = run_one(
                run_root / name,
                original,
                prompt,
                args.model,
                usage,
                session_id,
                watermark_secret,
                WatermarkConfig(args.tag_bytes, redundancy),
                args.seed + sample_index * 100 + redundancy,
            )
            all_results.append({"simulation": name, **result})
        if sample_index + 1 < args.samples:
            time.sleep(max(0.0, args.delay_seconds))

    summary = {
        "run_directory": str(run_root),
        "simulations": len(all_results),
        "encoded": sum(int(bool(item.get("encoded"))) for item in all_results),
        "clean_exact_recovery": sum(int(bool(item.get("exact_session_tag_recovered"))) for item in all_results),
        "results": all_results,
    }
    write_json(run_root / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
