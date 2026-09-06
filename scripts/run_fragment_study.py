#!/usr/bin/env python3
"""Distributed-watermark fragment study: subpart extraction + mutation rounds + code manifests.

Builds (deterministically) a long prose corpus of >= 1000 lines, embeds
independently decodable watermark frames across it with
``embed_distributed_watermark``, then benchmarks random contiguous subpart
extraction at several fragment lengths under repeated carrier-mutation rounds.
Also benchmarks detached code manifests on long code with localized edits.

Outputs (timestamped folder under ``fragment_studies/``):
  corpus.txt, code.py, fragment-trials.csv, fragment-aggregate.csv,
  code-manifest-results.csv, code-manifest-results.json, summary.json,
  REPORT.md, fragment-study.png (Pillow only).

Deterministic: every random choice derives from ``--seed``.
Security: this script never reads ``secret.env`` or environment secrets and
never prints key material. It uses a fixed non-production study key that is
kept out of all output files.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from watermark_lab import WatermarkConfig, detect_watermark, embed_distributed_watermark, session_tag
from watermark_lab.code_provenance import create_code_manifest, verify_code_manifest
from watermark_lab.core import _byte_to_selector, _selector_to_byte

# Fixed non-production study key. Never log or persist this value; outputs
# record only detection booleans, tag hashes are compared internally.
_STUDY_KEY = b"fragment-study-deterministic-key-00123456789ABCDEF-xyz!"
_STUDY_SESSION = "fragment-origin"
_CODE_SESSION = "fragment-code-origin"

_PROSE_WORDS = [
    "monitoring", "service", "reviews", "generated", "responses", "careful",
    "security", "analysis", "provenance", "evaluation", "detection", "accuracy",
    "resistance", "routine", "transformations", "researchers", "preserve",
    "factual", "statements", "survives", "copying", "movement", "storage",
    "systems", "agents", "share", "files", "results", "sandboxing", "scoped",
    "credentials", "egress", "controls", "tracking", "defenders", "distinguish",
    "malicious", "source", "session", "legitimate", "editors", "incident",
    "several", "contribute", "evolving", "artifact", "precise", "discussion",
    "limitations", "concrete", "criteria", "paragraph", "section", "document",
    "context", "records", "relevant", "information", "later", "inspection",
    "ordinary", "prose", "clarity", "claim", "entity", "citation", "policy",
    "reviewer", "manual", "decision", "handoff", "lineage", "robustness",
]

_CLOSERS = [
    "about evaluation methods and provenance controls.",
    "about session attribution and incident review.",
    "about robustness under copying and routine edits.",
    "about sandboxing and scoped credential controls.",
    "about distinguishing legitimate editors from malicious sources.",
]


def build_prose_lines(num_lines: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    lines: list[str] = []
    for _ in range(num_lines):
        n_words = 18 + rng.randrange(5)
        words = [rng.choice(_PROSE_WORDS) for _ in range(n_words)]
        lines.append(" ".join(words).capitalize() + " " + rng.choice(_CLOSERS))
    return lines


def build_code_text(num_lines: int, seed: int) -> str:
    rng = random.Random(seed + 999)
    out: list[str] = []
    out.append('"""Deterministic synthetic module for detached-manifest study."""')
    out.append("from __future__ import annotations")
    out.append("")
    i = 0
    while len(out) < num_lines:
        name = f"value_{i}"
        out.append(f"{name} = {rng.randrange(10000)}")
        if i % 10 == 9 and len(out) < num_lines:
            out.append("")
            out.append(f"def func_{i}(item):")
            out.append(f"    total = item + {rng.randrange(100)}")
            out.append("    return total")
            out.append("")
        i += 1
    return "\n".join(out[:num_lines]) + "\n"


def mutate_carriers(text: str, rng: random.Random, drop: float, corrupt: float) -> str:
    output: list[str] = []
    for char in text:
        value = _selector_to_byte(char)
        if value is None:
            output.append(char)
        elif rng.random() < drop:
            continue
        elif rng.random() < corrupt:
            output.append(_byte_to_selector(value ^ (1 << rng.randrange(8))))
        else:
            output.append(char)
    return "".join(output)


def apply_mutation_rounds(text: str, seed: int, rounds: int, drop: float, corrupt: float) -> str:
    mutated = text
    for round_index in range(rounds):
        rng = random.Random(seed * 10_000 + round_index)
        mutated = mutate_carriers(mutated, rng, drop, corrupt)
    return mutated


def aggregate_trials(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[int, int], list[int]] = {}
    for row in rows:
        groups.setdefault((row["fragment_lines"], row["mutation_rounds"]), []).append(
            int(row["exact_recovery"])
        )
    return [
        {
            "fragment_lines": key[0],
            "mutation_rounds": key[1],
            "trials": len(values),
            "exact_recovery_rate": sum(values) / len(values),
        }
        for key, values in sorted(groups.items())
    ]


def failure_boundaries(aggregate: list[dict], threshold: float = 0.9) -> dict:
    """Smallest fragment length reliable at 0 mutation rounds, and most mutation
    rounds tolerated at the largest fragment length."""
    by_length = sorted({row["fragment_lines"] for row in aggregate})
    lookup = {(r["fragment_lines"], r["mutation_rounds"]): r["exact_recovery_rate"] for r in aggregate}
    max_round = max(r["mutation_rounds"] for r in aggregate)
    max_length = max(by_length)
    min_reliable_length = None
    for length in by_length:
        if lookup.get((length, 0), 0.0) >= threshold:
            min_reliable_length = length
            break
    max_tolerated_rounds = None
    for round_index in sorted({r["mutation_rounds"] for r in aggregate}, reverse=True):
        if lookup.get((max_length, round_index), 0.0) >= threshold:
            max_tolerated_rounds = round_index
            break
    first_failure = None
    for row in sorted(aggregate, key=lambda r: (r["mutation_rounds"], r["fragment_lines"])):
        if row["exact_recovery_rate"] < threshold:
            first_failure = {
                "fragment_lines": row["fragment_lines"],
                "mutation_rounds": row["mutation_rounds"],
                "exact_recovery_rate": row["exact_recovery_rate"],
            }
            break
    return {
        "threshold": threshold,
        "min_reliable_fragment_lines_at_zero_damage": min_reliable_length,
        "max_tolerated_mutation_rounds_at_largest_fragment": max_tolerated_rounds,
        "largest_fragment_lines": max_length,
        "first_sub_threshold_cell": first_failure,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def draw_png(
    path: Path,
    aggregate: list[dict],
    code_rows: list[dict],
    boundaries: dict,
    meta: dict,
) -> None:
    from PIL import Image, ImageDraw, ImageFont  # Pillow only

    def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
        for item in candidates:
            if Path(item).exists():
                return ImageFont.truetype(item, size)
        return ImageFont.load_default()

    W, H = 2000, 1320
    BG, CARD, TEXT, MUTED, GRID = "#F5F7FB", "#FFFFFF", "#101828", "#667085", "#D0D5DD"
    COLORS = {0: "#2563EB", 1: "#7C3AED", 2: "#E11D48", 3: "#B45309", 4: "#067647"}
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    def centered(box: tuple[int, int, int, int], label: str, fnt, fill=TEXT) -> None:
        left, top, right, bottom = box
        l, t, r, b = draw.textbbox((0, 0), label, font=fnt)
        draw.text(((left + right - (r - l)) / 2, (top + bottom - (b - t)) / 2 - t), label, font=fnt, fill=fill)

    centered((0, 24, W, 84), "Distributed watermark: fragment recovery under damage", font(44, True))
    centered(
        (0, 86, W, 122),
        f"{meta['corpus_lines']} lines  |  {meta['trials_per_cell']} trials/cell  |  seed {meta['seed']}  |  "
        f"interval {meta['interval_carriers']} carriers, r{meta['redundancy']}",
        font(21),
        MUTED,
    )

    # Panel 1: recovery curves.
    chart = (50, 150, 1300, 880)
    draw.rounded_rectangle(chart, 22, fill=CARD, outline=GRID, width=2)
    draw.text((chart[0] + 28, chart[1] + 16), "Exact recovery vs fragment length (lines)", font=font(28, True), fill=TEXT)
    lengths = sorted({r["fragment_lines"] for r in aggregate})
    rounds = sorted({r["mutation_rounds"] for r in aggregate})
    lookup = {(r["fragment_lines"], r["mutation_rounds"]): r["exact_recovery_rate"] for r in aggregate}
    x0, x1, y0, y1 = chart[0] + 110, chart[2] - 50, chart[1] + 110, chart[3] - 90
    for pct in (0, 25, 50, 75, 100):
        y = y1 - (pct / 100) * (y1 - y0)
        draw.line((x0, y, x1, y), fill=GRID, width=2)
        draw.text((x0 - 68, y - 12), f"{pct}%", font=font(18), fill=MUTED)
    positions = {length: x0 + (i / (len(lengths) - 1)) * (x1 - x0) if len(lengths) > 1 else (x0 + x1) / 2 for i, length in enumerate(lengths)}
    for length in lengths:
        draw.text((positions[length] - 22, y1 + 14), str(length), font=font(18), fill=MUTED)
    draw.line((x0, y0, x0, y1), fill=MUTED, width=3)
    draw.line((x0, y1, x1, y1), fill=MUTED, width=3)
    draw.text((x0, y1 + 44), "Contiguous fragment length (lines, categorical axis)", font=font(18), fill=MUTED)
    for round_index in rounds:
        color = COLORS.get(round_index % len(COLORS), "#101828")
        pts = [(positions[length], y1 - lookup[(length, round_index)] * (y1 - y0)) for length in lengths]
        if len(pts) > 1:
            draw.line(pts, fill=color, width=6, joint="curve")
        for x, y in pts:
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline=CARD, width=2)
    # Legend.
    lx = x0 + 20
    for i, round_index in enumerate(rounds):
        color = COLORS.get(round_index % len(COLORS), "#101828")
        x = lx + i * 210
        draw.line((x, y0 + 22, x + 44, y0 + 22), fill=color, width=7)
        draw.text((x + 54, y0 + 8), f"{round_index} rounds", font=font(20, True), fill=TEXT)
    bound = boundaries["min_reliable_fragment_lines_at_zero_damage"]
    first = boundaries.get("first_sub_threshold_cell") or {}
    draw.text(
        (x0, y1 + 74),
        f"Failure boundary (90%): reliable from {bound} lines at 0 damage; "
        f"first sub-90% cell: {first.get('fragment_lines')} lines / {first.get('mutation_rounds')} rounds.",
        font=font(19, True),
        fill="#B42318" if bound else MUTED,
    )

    # Panel 2: code manifest localization + key facts.
    panel = (1330, 150, 1950, 880)
    draw.rounded_rectangle(panel, 22, fill=CARD, outline=GRID, width=2)
    draw.text((panel[0] + 28, panel[1] + 16), "Detached code manifests", font=font(28, True), fill=TEXT)
    draw.text((panel[0] + 28, panel[1] + 58), "Long code, localized edits stay localized", font=font(20), fill=MUTED)
    bar_x0, bar_x1 = panel[0] + 28, panel[2] - 28
    y = panel[1] + 120
    for row in code_rows:
        total = max(1, int(row["total_chunks"]))
        matching = int(row["matching_chunks"])
        draw.text((bar_x0, y), str(row["case"])[:38], font=font(19, True), fill=TEXT)
        draw.text((bar_x0, y + 26), f"{matching}/{total} chunks match  changed={row['changed_chunks']}", font=font(17), fill=MUTED)
        bw, bh = bar_x1 - bar_x0, 22
        by = y + 52
        draw.rounded_rectangle((bar_x0, by, bar_x1, by + bh), 8, fill="#EAECF0")
        fill_w = (matching / total) * (bar_x1 - bar_x0)
        color = "#16A34A" if matching == total else "#2563EB"
        if fill_w > 1:
            draw.rounded_rectangle((bar_x0, by, bar_x0 + fill_w, by + bh), 8, fill=color)
        y += 108

    # Footer facts strip.
    footer = (50, 910, 1950, 1250)
    draw.rounded_rectangle(footer, 22, fill=CARD, outline=GRID, width=2)
    clean = [r for r in aggregate if r["mutation_rounds"] == 0]
    clean_best = max(clean, key=lambda r: r["exact_recovery_rate"]) if clean else {}
    lines_text = [
        f"Corpus: {meta['corpus_lines']} lines / {meta['corpus_words']:,} words / {meta['frames_embedded']} frames.",
        f"Clean extraction: {clean_best.get('exact_recovery_rate', 0):.0%} at {clean_best.get('fragment_lines')} lines; "
        f"{lookup.get((min(lengths), 0), 0):.0%} at {min(lengths)} lines (small fragments often miss a full frame).",
        f"Damage model: per mutation round drop {meta['drop_rate']:.0%} + corrupt {meta['corrupt_rate']:.0%} of carriers, cumulative.",
        "Reading guide: each curve is one damage level; the knee where a curve falls below 90% is the failure boundary. "
        "Code bars show a detached manifest still authenticates while pinpointing only the edited chunk.",
        "Limitation: invisible carriers are strippable; absence of a mark means unknown, not safe.",
    ]
    ty = footer[1] + 26
    draw.text((footer[0] + 28, ty), "How to read this figure", font=font(28, True), fill=TEXT)
    ty += 52
    for line in lines_text:
        # Simple word-wrap.
        words = line.split(" ")
        wrapped: list[str] = []
        current = ""
        for word in words:
            trial = (current + " " + word).strip()
            if draw.textlength(trial, font=font(20)) < (footer[2] - footer[0] - 70):
                current = trial
            else:
                wrapped.append(current)
                current = word
        if current:
            wrapped.append(current)
        for part in wrapped:
            draw.text((footer[0] + 28, ty), part, font=font(20), fill=TEXT if part == wrapped[0] else MUTED)
            ty += 30
        ty += 8
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Distributed-watermark fragment study")
    parser.add_argument("--seed", type=int, default=20260906)
    parser.add_argument("--corpus-lines", type=int, default=1200)
    parser.add_argument("--fragment-lengths", nargs="+", type=int, default=[5, 10, 25, 50, 100, 200])
    parser.add_argument("--trials-per-cell", type=int, default=30)
    parser.add_argument("--max-mutation-rounds", type=int, default=3)
    parser.add_argument("--drop-rate", type=float, default=0.05)
    parser.add_argument("--corrupt-rate", type=float, default=0.05)
    parser.add_argument("--interval-carriers", type=int, default=300)
    parser.add_argument("--tag-bytes", type=int, default=8)
    parser.add_argument("--redundancy", type=int, default=3)
    parser.add_argument("--code-lines", type=int, default=1200)
    parser.add_argument("--chunk-lines", type=int, default=50)
    parser.add_argument("--output-root", default="fragment_studies")
    args = parser.parse_args()

    if args.corpus_lines < 1000:
        parser.error("--corpus-lines must be at least 1000")
    if args.max_mutation_rounds < 0:
        parser.error("--max-mutation-rounds must be >= 0")

    config = WatermarkConfig(args.tag_bytes, args.redundancy)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = Path(args.output_root) / f"fragment-study-{stamp}"
    root.mkdir(parents=True)

    prose_lines = build_prose_lines(args.corpus_lines, args.seed)
    corpus = "\n".join(prose_lines) + "\n"
    marked = embed_distributed_watermark(
        corpus, _STUDY_SESSION, _STUDY_KEY, config, interval_carriers=args.interval_carriers
    )
    expected_hex = session_tag(_STUDY_KEY, _STUDY_SESSION, args.tag_bytes).hex()
    marked_lines = marked.splitlines()
    assert len(marked_lines) >= args.corpus_lines
    frames = len(marked_lines)  # placeholder replaced below
    from watermark_lab.core import _carrier_ends

    carriers = len(_carrier_ends(corpus))
    frame_words = config.minimum_carriers
    frames = max(1, carriers // args.interval_carriers)

    trial_rows: list[dict] = []
    for fragment_lines in args.fragment_lengths:
        for trial in range(args.trials_per_cell):
            picker = random.Random(args.seed + 1_000_000 + fragment_lines * 10_000 + trial)
            start = picker.randrange(0, len(marked_lines) - fragment_lines + 1)
            fragment = "\n".join(marked_lines[start : start + fragment_lines])
            for mutation_rounds in range(args.max_mutation_rounds + 1):
                mutated = apply_mutation_rounds(
                    fragment,
                    args.seed + 5_000_000 + trial * 100 + fragment_lines + mutation_rounds,
                    mutation_rounds,
                    args.drop_rate,
                    args.corrupt_rate,
                )
                detection = detect_watermark(mutated, args.redundancy)
                trial_rows.append(
                    {
                        "fragment_lines": fragment_lines,
                        "mutation_rounds": mutation_rounds,
                        "trial": trial,
                        "start_line": start,
                        "detected": detection.found,
                        "exact_recovery": (detection.found and detection.tag_hex == expected_hex),
                        "corrected_groups": detection.corrected_groups,
                        "confidence": round(detection.confidence, 4),
                    }
                )

    aggregate = aggregate_trials(trial_rows)
    boundaries = failure_boundaries(aggregate, threshold=0.9)

    # Detached code manifests on long code with localized edits.
    code = build_code_text(args.code_lines, args.seed)
    manifest = create_code_manifest(code, _CODE_SESSION, _STUDY_KEY, chunk_lines=args.chunk_lines)
    code_lines = code.splitlines(keepends=True)
    total_chunks = len(manifest["chunk_sha256"])

    def edited(cases: dict[str, str]) -> list[dict]:
        rows: list[dict] = []
        for case, text in cases.items():
            result = verify_code_manifest(text, manifest, _STUDY_KEY)
            rows.append(
                {
                    "case": case,
                    "edited_lines": sum(1 for a, b in zip(code.splitlines(), text.splitlines()) if a != b)
                    + abs(len(code.splitlines()) - len(text.splitlines())),
                    "total_chunks": result["total_expected_chunks"],
                    "matching_chunks": result["matching_chunks"],
                    "exact_content": result["exact_content"],
                    "manifest_authentic": result["manifest_authentic"],
                    "changed_chunks": json.dumps(result["changed_chunks"]),
                }
            )
        return rows

    single = list(code_lines)
    single[5 * args.chunk_lines + 3] = "value Edited = dangerous_call()\n"
    three = list(code_lines)
    for offset in range(3):
        three[12 * args.chunk_lines + offset] = f"edited_line_{offset} = dangerous_call()\n"
    boundary = list(code_lines)
    at = 4 * args.chunk_lines - 1
    boundary[at] = "cross_a = dangerous_call()\n"
    boundary[at + 1] = "cross_b = dangerous_call()\n"
    scattered = list(code_lines)
    scattered[2 * args.chunk_lines + 1] = "scatter_a = dangerous_call()\n"
    scattered[17 * args.chunk_lines + 1] = "scatter_b = dangerous_call()\n"

    code_rows = edited(
        {
            "no-edit control": code,
            "single-line edit": "".join(single),
            "three-line localized edit": "".join(three),
            "two-line cross-chunk-boundary edit": "".join(boundary),
            "two scattered single-line edits": "".join(scattered),
        }
    )

    (root / "corpus.txt").write_text(corpus, encoding="utf-8")
    (root / "code.py").write_text(code, encoding="utf-8")
    write_csv(root / "fragment-trials.csv", trial_rows)
    write_csv(root / "fragment-aggregate.csv", aggregate)
    write_csv(root / "code-manifest-results.csv", code_rows)

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "corpus_lines": args.corpus_lines,
        "corpus_words": len(corpus.split()),
        "eligible_carriers": carriers,
        "frame_minimum_words": frame_words,
        "frames_embedded": frames,
        "interval_carriers": args.interval_carriers,
        "tag_bytes": args.tag_bytes,
        "redundancy": args.redundancy,
        "fragment_lengths": args.fragment_lengths,
        "trials_per_cell": args.trials_per_cell,
        "max_mutation_rounds": args.max_mutation_rounds,
        "drop_rate": args.drop_rate,
        "corrupt_rate": args.corrupt_rate,
        "total_fragment_trials": len(trial_rows),
        "code_lines": args.code_lines,
        "chunk_lines": args.chunk_lines,
        "total_code_chunks": total_chunks,
    }
    summary = {
        **meta,
        "fragment_aggregate": aggregate,
        "failure_boundaries": boundaries,
        "clean_exact_recovery_rate_at_largest_fragment": next(
            r["exact_recovery_rate"]
            for r in aggregate
            if r["fragment_lines"] == max(args.fragment_lengths) and r["mutation_rounds"] == 0
        ),
        "code_manifest": code_rows,
        "secret_recorded": False,
    }
    (root / "code-manifest-results.json").write_text(json.dumps(code_rows, indent=2) + "\n", encoding="utf-8")
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    draw_png(root / "fragment-study.png", aggregate, code_rows, boundaries, meta)

    table = "\n".join(
        f"| {r['fragment_lines']:>4} | {r['mutation_rounds']} | {r['exact_recovery_rate']:.1%} |"
        for r in aggregate
    )
    first = boundaries["first_sub_threshold_cell"] or {}
    (root / "REPORT.md").write_text(
        "# Distributed-watermark fragment study\n\n"
        f"- Corpus: {meta['corpus_lines']} lines / {meta['corpus_words']:,} words / "
        f"{meta['eligible_carriers']:,} eligible carriers / ~{meta['frames_embedded']} frames.\n"
        f"- Config: tag_bytes={args.tag_bytes}, redundancy={args.redundancy}, "
        f"interval={args.interval_carriers} carriers; seed={args.seed}.\n"
        f"- Fragment trials: {len(trial_rows):,} "
        f"({len(args.fragment_lengths)} lengths x {args.max_mutation_rounds + 1} damage levels x {args.trials_per_cell} trials).\n"
        f"- Damage model: each mutation round drops {args.drop_rate:.0%} and corrupts "
        f"{args.corrupt_rate:.0%} of carriers (cumulative, deterministic).\n"
        f"- Failure boundary (90% exact recovery): smallest reliable fragment at zero damage is "
        f"{boundaries['min_reliable_fragment_lines_at_zero_damage']} lines; "
        f"max tolerated mutation rounds at {boundaries['largest_fragment_lines']} lines is "
        f"{boundaries['max_tolerated_mutation_rounds_at_largest_fragment']}.\n"
        f"- First sub-90% cell: {first.get('fragment_lines')} lines / {first.get('mutation_rounds')} rounds "
        f"({(first.get('exact_recovery_rate') or 0):.1%}).\n"
        f"- Clean exact recovery at {max(args.fragment_lengths)} lines: "
        f"{summary['clean_exact_recovery_rate_at_largest_fragment']:.1%}.\n"
        f"- Code manifests: {total_chunks} chunks; single-line edits change exactly one chunk while "
        "the detached manifest still authenticates (see code-manifest-results.csv).\n\n"
        "## Exact recovery by fragment length and damage\n\n"
        "| lines | mutation rounds | exact recovery |\n"
        "|---:|---:|---:|\n"
        f"{table}\n\n"
        "## Code manifest localization\n\n"
        "| case | matching / total | exact content | manifest authentic | changed chunks |\n"
        "|---|---|---|---|---|\n"
        + "\n".join(
            f"| {r['case']} | {r['matching_chunks']}/{r['total_chunks']} | "
            f"{r['exact_content']} | {r['manifest_authentic']} | {r['changed_chunks']} |"
            for r in code_rows
        )
        + "\n\nSee `fragment-study.png` for the chart, `summary.json` for machine-readable "
        "results, and `fragment-trials.csv` for every trial. No secrets are stored in outputs.\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "run_directory": str(root),
                "total_fragment_trials": len(trial_rows),
                "failure_boundaries": boundaries,
                "clean_exact_recovery_rate_at_largest_fragment": summary[
                    "clean_exact_recovery_rate_at_largest_fragment"
                ],
                "code_manifest": code_rows,
                "mean_confidence_clean": statistics.mean(
                    r["confidence"] for r in trial_rows if r["mutation_rounds"] == 0
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
