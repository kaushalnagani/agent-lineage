#!/usr/bin/env python3
"""Run a larger XRF study with long texts, edit chains, and provenance graphs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from watermark_lab import WatermarkConfig, detect_watermarks, embed_watermark, session_tag
from watermark_lab.core import _selector_to_byte, strip_watermark_characters
from watermark_lab.registry import match_tag
from watermark_lab.reporting import codepoint_insertions, text_metrics, unified_visible_diff, write_json


TOPICS = [
    "Designing secure provenance controls for autonomous AI agents that share files and tool results",
    "The limits of invisible text watermarking under editing, paraphrasing, and Unicode normalization",
    "Combining agent sandboxing, scoped credentials, egress controls, and information-flow tracking",
    "How defenders should distinguish a malicious source session from legitimate downstream editors",
    "Evaluating false positives and exact payload recovery in multi-bit language-model watermarks",
    "Building an incident graph when several agents contribute to the same evolving software artifact",
]


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


def gemini_call(api_key: str, model: str, instruction: str, max_tokens: int) -> tuple[str, dict]:
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model, safe="-._")
        + ":generateContent"
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": instruction}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": max_tokens},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
            parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(str(part.get("text", "")) for part in parts).strip()
            if not text:
                raise RuntimeError("Gemini returned no text")
            return text, result.get("usageMetadata", {})
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code == 429 and attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Gemini HTTP {error.code}: {body[:500]}") from error
    raise RuntimeError("Gemini retry limit reached")


def generate_document(api_key: str, model: str, topic: str, target_words: int) -> tuple[str, dict]:
    return gemini_call(
        api_key,
        model,
        (
            f"Write a technically precise research-style discussion of approximately {target_words} words about: {topic}. "
            "Use several titled plain-text sections and full paragraphs. Include limitations and concrete evaluation criteria. "
            "Do not use a Markdown table. Do not include unsafe operational attack instructions."
        ),
        max(800, target_words * 3),
    )


def rewrite_document(api_key: str, model: str, marked: str) -> tuple[str, dict]:
    return gemini_call(
        api_key,
        model,
        (
            "Act as a legitimate second-session editor. Rewrite the following document for clarity while preserving every factual "
            "claim, named entity, number, date, negation, security term, code fragment, and citation. Change approximately 15 percent "
            "of the ordinary prose. Return only the revised document.\n\n" + marked
        ),
        max(1000, len(marked.split()) * 3),
    )


def mutate_selectors(text: str, rng: random.Random, drop_rate: float, corrupt_rate: float) -> str:
    output: list[str] = []
    for char in text:
        value = _selector_to_byte(char)
        if value is None:
            output.append(char)
        elif rng.random() < drop_rate:
            continue
        elif rng.random() < corrupt_rate:
            from watermark_lab.core import _byte_to_selector
            output.append(_byte_to_selector(value ^ (1 << rng.randrange(8))))
        else:
            output.append(char)
    return "".join(output)


def delete_words(text: str, rng: random.Random, rate: float) -> str:
    matches = list(re.finditer(r"[A-Za-z][A-Za-z'-]*", text))
    selected = {index for index in range(len(matches)) if rng.random() < rate}
    if not selected:
        return text
    pieces: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        if index not in selected:
            continue
        pieces.append(text[cursor : match.start()])
        end = match.end()
        while end < len(text) and _selector_to_byte(text[end]) is not None:
            end += 1
        cursor = end
    pieces.append(text[cursor:])
    return re.sub(r"[ \t]{2,}", " ", "".join(pieces))


def aggregate(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[int]] = {}
    for row in rows:
        key = (row["attack"], row["rate"], row["redundancy"], row["target_words"])
        groups.setdefault(key, []).append(int(row["exact_recovery"]))
    return [
        {
            "attack": key[0],
            "rate": key[1],
            "redundancy": key[2],
            "target_words": key[3],
            "trials": len(values),
            "exact_recovery_rate": sum(values) / len(values),
        }
        for key, values in sorted(groups.items())
    ]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-env-file", default="secret.env")
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--lengths", nargs="+", type=int, default=[250, 500, 1000])
    parser.add_argument("--samples-per-length", type=int, default=2)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--output-root", default="research_runs")
    parser.add_argument("--delay-seconds", type=float, default=1.5)
    args = parser.parse_args()

    load_env(Path(args.secret_env_file))
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        parser.error("GOOGLE_API_KEY or GEMINI_API_KEY is required")
    secret = os.environ.get("WATERMARK_SECRET") or os.urandom(32).hex()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = Path(args.output_root) / f"xrf-study-{stamp}"
    corpus_dir = root / "corpus"
    artifacts_dir = root / "artifacts"
    corpus_dir.mkdir(parents=True)
    artifacts_dir.mkdir()

    configs = [WatermarkConfig(8, redundancy) for redundancy in (1, 3, 5)]
    documents: list[dict] = []
    document_index = 0
    for target_words in args.lengths:
        for repeat in range(args.samples_per_length):
            topic = TOPICS[document_index % len(TOPICS)]
            text, usage = generate_document(api_key, args.model, topic, target_words)
            doc_id = f"doc-{document_index + 1:03d}"
            (corpus_dir / f"{doc_id}.txt").write_text(text + "\n", encoding="utf-8")
            documents.append({"id": doc_id, "text": text, "target_words": target_words, "topic": topic, "usage": usage})
            document_index += 1
            time.sleep(max(0.0, args.delay_seconds))

    trial_rows: list[dict] = []
    fidelity_rows: list[dict] = []
    attack_rates = [0.0, 0.01, 0.05, 0.10, 0.20, 0.35]
    for doc in documents:
        session_id = f"origin-{doc['id']}"
        doc_dir = artifacts_dir / doc["id"]
        doc_dir.mkdir()
        for config in configs:
            marked = embed_watermark(doc["text"], session_id, secret, config)
            expected = session_tag(secret, session_id, config.tag_bytes).hex()
            (doc_dir / f"marked-r{config.redundancy}.txt").write_text(marked + "\n", encoding="utf-8")
            metrics = text_metrics(doc["text"], marked)
            fidelity_rows.append(
                {
                    "document": doc["id"],
                    "target_words": doc["target_words"],
                    "actual_words": len(doc["text"].split()),
                    "redundancy": config.redundancy,
                    **metrics,
                }
            )
            for rate in attack_rates:
                for seed in range(args.seeds):
                    for attack in ("selector_drop", "selector_corrupt", "word_delete"):
                        rng = random.Random(10_000 * document_index + 100 * config.redundancy + 10 * seed + int(rate * 100))
                        if attack == "selector_drop":
                            attacked = mutate_selectors(marked, rng, rate, 0.0)
                        elif attack == "selector_corrupt":
                            attacked = mutate_selectors(marked, rng, 0.0, rate)
                        else:
                            attacked = delete_words(marked, rng, rate)
                        detections = detect_watermarks(attacked, config.redundancy)
                        recovered = {item.tag_hex for item in detections}
                        trial_rows.append(
                            {
                                "document": doc["id"],
                                "target_words": doc["target_words"],
                                "redundancy": config.redundancy,
                                "attack": attack,
                                "rate": rate,
                                "seed": seed,
                                "detected_count": len(detections),
                                "exact_recovery": expected in recovered,
                            }
                        )

    # Real model-mediated edits: test whether the origin mark survives a second
    # model session, then mark the new output as belonging to the editor.
    rewrite_rows: list[dict] = []
    graph_nodes: list[dict] = []
    graph_edges: list[dict] = []
    for index, doc in enumerate(documents[::2]):
        origin = f"origin-{doc['id']}"
        editor = f"editor-{doc['id']}"
        config = WatermarkConfig(8, 3)
        marked = embed_watermark(doc["text"], origin, secret, config)
        revised, usage = rewrite_document(api_key, args.model, marked)
        revised_marked = embed_watermark(revised, editor, secret, config)
        rewrite_dir = artifacts_dir / doc["id"] / "gemini-rewrite"
        rewrite_dir.mkdir()
        (rewrite_dir / "origin-marked.txt").write_text(marked + "\n", encoding="utf-8")
        (rewrite_dir / "editor-output-before-marking.txt").write_text(revised + "\n", encoding="utf-8")
        (rewrite_dir / "editor-output-marked.txt").write_text(revised_marked + "\n", encoding="utf-8")
        original_detections = detect_watermarks(revised, 3)
        final_detections = detect_watermarks(revised_marked, 3)
        rewrite_rows.append(
            {
                "document": doc["id"],
                "target_words": doc["target_words"],
                "origin_mark_survived_model_rewrite": session_tag(secret, origin).hex() in {d.tag_hex for d in original_detections},
                "editor_mark_detected": session_tag(secret, editor).hex() in {d.tag_hex for d in final_detections},
                "origin_words": len(doc["text"].split()),
                "revised_words": len(revised.split()),
                "visible_similarity_ratio": text_metrics(doc["text"], revised)["visible_similarity_ratio"],
                "usage": usage,
            }
        )
        graph_nodes.extend(
            [
                {"id": origin, "type": "session", "status": "authorized"},
                {"id": editor, "type": "session", "status": "authorized"},
                {"id": f"artifact-{doc['id']}-v1", "type": "artifact", "status": "clean"},
                {"id": f"artifact-{doc['id']}-v2", "type": "artifact", "status": "review"},
            ]
        )
        graph_edges.extend(
            [
                {"source": origin, "target": f"artifact-{doc['id']}-v1", "relation": "created"},
                {"source": f"artifact-{doc['id']}-v1", "target": editor, "relation": "read"},
                {"source": editor, "target": f"artifact-{doc['id']}-v2", "relation": "modified"},
            ]
        )
        time.sleep(max(0.0, args.delay_seconds))

    # Demonstrate multiple surviving provenance marks in one artifact and mixed
    # legitimate/malicious sections without marking the whole artifact malicious.
    mix_config = WatermarkConfig(8, 3)
    safe_a, safe_b, malicious = "session-safe-a", "session-safe-b", "session-malicious-c"
    layered = embed_watermark(documents[0]["text"], safe_a, secret, mix_config)
    layered = embed_watermark(layered, safe_b, secret, mix_config, preserve_existing=True)
    malicious_section = embed_watermark(documents[1]["text"], malicious, secret, mix_config)
    human_section = "Human reviewer note: this unmarked section records a manual decision and should not inherit suspicion automatically."
    mixed = layered + "\n\n" + human_section + "\n\n" + malicious_section
    mixed_dir = artifacts_dir / "mixed-session-artifact"
    mixed_dir.mkdir()
    (mixed_dir / "artifact.txt").write_text(mixed + "\n", encoding="utf-8")
    registry = [
        {"session_id": safe_a, "status": "authorized"},
        {"session_id": safe_b, "status": "authorized"},
        {"session_id": malicious, "status": "malicious"},
    ]
    mixed_detections = detect_watermarks(mixed, 3)
    mixed_matches = [asdict(match_tag(item.tag_hex or "", registry, secret, "destination-reviewer")) for item in mixed_detections]
    write_json(mixed_dir / "detections.json", [asdict(item) for item in mixed_detections])
    write_json(mixed_dir / "policy_matches.json", mixed_matches)

    graph_nodes.extend(
        [
            {"id": safe_a, "type": "session", "status": "authorized"},
            {"id": safe_b, "type": "session", "status": "authorized"},
            {"id": malicious, "type": "session", "status": "malicious"},
            {"id": "mixed-artifact", "type": "artifact", "status": "mixed"},
            {"id": "destination-reviewer", "type": "session", "status": "authorized"},
        ]
    )
    graph_edges.extend(
        [
            {"source": safe_a, "target": "mixed-artifact", "relation": "created section"},
            {"source": safe_b, "target": "mixed-artifact", "relation": "legitimate edit"},
            {"source": malicious, "target": "mixed-artifact", "relation": "suspicious section"},
            {"source": "mixed-artifact", "target": "destination-reviewer", "relation": "intercepted before model"},
        ]
    )

    aggregate_rows = aggregate(trial_rows)
    write_csv(root / "trial-results.csv", trial_rows)
    write_csv(root / "aggregate-results.csv", aggregate_rows)
    write_csv(root / "fidelity-results.csv", fidelity_rows)
    write_json(root / "rewrite-results.json", rewrite_rows)
    write_json(root / "provenance-graph.json", {"nodes": graph_nodes, "edges": graph_edges})
    write_json(root / "mixed-artifact-results.json", {"detections": len(mixed_detections), "matches": mixed_matches})

    clean_trials = [row for row in trial_rows if row["rate"] == 0.0]
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "documents": len(documents),
        "target_lengths": args.lengths,
        "offline_trials": len(trial_rows),
        "clean_exact_recovery_rate": statistics.mean(int(row["exact_recovery"]) for row in clean_trials),
        "visible_text_unchanged_rate": statistics.mean(int(row["visible_text_identical"]) for row in fidelity_rows),
        "model_rewrites": rewrite_rows,
        "mixed_artifact_detected_sessions": mixed_matches,
        "api_key_recorded": False,
    }
    write_json(root / "summary.json", summary)
    (root / "REPORT.md").write_text(
        "# XRF research study\n\n"
        f"- Model: `{args.model}`\n"
        f"- Long documents: {len(documents)} at target lengths {args.lengths}\n"
        f"- Offline randomized trials: {len(trial_rows):,}\n"
        f"- Clean exact recovery: {summary['clean_exact_recovery_rate']:.1%}\n"
        f"- Visibly unchanged after encoding: {summary['visible_text_unchanged_rate']:.1%}\n"
        f"- Model-mediated rewrites tested: {len(rewrite_rows)}\n"
        f"- Distinct session marks in mixed artifact: {len(mixed_detections)}\n\n"
        "See `aggregate-results.csv` for error curves, `rewrite-results.json` for model-mediated edits, "
        "and `provenance-graph.json` for session/artifact lineage.\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_directory": str(root), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
