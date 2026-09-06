# XRF Session Watermark Lab

An experimental harness for embedding an opaque session tag into agent prose,
detecting it before another model call, matching it to a session registry, and
benchmarking fidelity and robustness.

This is a research sensor, not a complete sandbox. The first codec uses Unicode
variation selectors because they preserve visible text exactly and provide one
byte per eligible word. They can be removed by sanitizers, deliberate attacks,
or systems that do not preserve Unicode variation selectors. Production systems
should combine an in-band watermark with signed out-of-band provenance, strict
session isolation, scoped credentials, and egress controls.

## Frame

The encoded frame is:

```text
XRF | version | tag length | HMAC(session ID) | CRC32
```

`XRF` is encoded rather than visibly prepended. It provides a fast magic-prefix
rejection during scanning. The raw session ID and secret are never embedded.

With the default 8-byte tag, the frame is 17 bytes. Each frame byte is repeated
according to the requested odd redundancy:

| Redundancy | Correctable symbol errors per group | Minimum eligible words |
|---:|---:|---:|
| 1 | 0 | 17 |
| 3 | 1 | 51 |
| 5 | 2 | 85 |

"Eligible" excludes code, URLs, numbers, likely named entities, acronyms, and
negation terms. The detector reports capacity instead of silently degrading.

## Setup

The offline codec uses only the Python standard library:

```bash
python -m unittest discover -s tests -v
```

Use a shell environment variable for the watermark secret:

```bash
export WATERMARK_SECRET='replace-with-at-least-16-random-characters'
```

Do not commit the secret or an API key.

## Add a watermark

```bash
python scripts/add_watermark.py \
  --session-id agent-session-blocked \
  --redundancy 3 \
  --stats \
  < input.txt > marked.txt
```

The visible rendering of `marked.txt` is identical to `input.txt`, although the
raw Unicode strings differ.

## Detect and apply registry policy

```bash
python scripts/detect_watermark.py \
  --registry examples/registry.json \
  --destination-session destination-agent \
  --redundancy 3 \
  < marked.txt
```

Possible policy decisions are `allow-self`, `block`, `quarantine`, and
`review-cross-session`.

## Benchmark

```bash
python scripts/benchmark.py --redundancy 1
python scripts/benchmark.py --redundancy 3
python scripts/benchmark.py --tag-bytes 4 --redundancy 5
```

The benchmark measures capacity, exact tag recovery, invisible-character
overhead, unmarked false positives, CRC validation, and survival under Unicode
normalization, selector deletion/corruption, stripping, and spacing changes.

Supply a custom corpus as JSONL records with a `text` field:

```bash
python scripts/benchmark.py --input-jsonl corpus.jsonl
```

## Optional OpenAI-generated corpus

Install the optional dependency and set the API key locally:

```bash
python -m pip install -e '.[openai]'
export OPENAI_API_KEY='your-key-in-your-shell'
python scripts/generate_samples_openai.py \
  --prompts examples/prompts.jsonl \
  --output generated.jsonl \
  --model YOUR_MODEL_ID \
  --min-words 120
python scripts/benchmark.py --input-jsonl generated.jsonl
```

The generator uses the Responses API and `response.output_text`. The model ID is
required explicitly so experiments remain reproducible.

## Gemini simulation folders

Put `GOOGLE_API_KEY=...` in the ignored `secret.env` file. For a consistent
watermark secret across runs, also add a separate `WATERMARK_SECRET=...` value;
the Google API key is never reused as a watermark key.

```bash
python scripts/run_gemini_simulations.py \
  --model gemini-3.5-flash-lite \
  --samples 3 \
  --min-words 120 \
  --redundancies 1 3
```

Every configuration gets its own folder under `simulations/gemini-<timestamp>/`:

```text
simulation-001-r3/
├── original.txt
├── watermarked.txt
├── visible_diff.txt
├── codepoint_diff.json
├── metadata.json
├── metrics.json
├── detection.json
├── attack_results.json
└── attacks/
```

`visible_diff.txt` shows whether readable text changed. `codepoint_diff.json`
shows every invisible variation selector, its position, and its encoded byte.

The runner defaults to `gemini-3.5-flash-lite`. Google retired
`gemini-2.5-flash-lite` for new users and the live API response recommends the
3.5 replacement.

## Known limitations and next research stage

- Removing variation selectors destroys this carrier completely.
- Word insertion/deletion can desynchronize repeated groups.
- An agent can communicate through code, URLs, filenames, encryption, timing,
  or other channels that cannot safely carry this watermark.
- CRC detects corruption but is not authentication; HMAC-derived tags prevent
  exposure of raw session identifiers, while registry matching establishes the
  identity.
- Text watermarking attributes a source. A separate monitor decides whether the
  source session is malicious.

The next codec should operate during model decoding: spread a multi-bit payload
across keyed token partitions, retain soft token likelihoods, and use a
fountain/LDPC-style decoder across multiple messages. This repository separates
the frame, registry, detector, attacks, and benchmark so that carrier can be
added without changing policy logic.

## Longer research study

The extended study generates long Gemini documents, runs randomized error curves,
asks a second Gemini session to edit marked material, layers multiple legitimate
session marks, mixes a malicious section into an otherwise legitimate artifact,
and exports provenance-graph data.

```bash
python scripts/run_research_study.py \
  --model gemini-3.5-flash-lite \
  --lengths 250 500 1000 \
  --samples-per-length 2 \
  --seeds 20
```

Each run writes a research bundle under `research_runs/xrf-study-<timestamp>/`
with original and marked artifacts, randomized trial CSV, aggregated recovery
curves, Gemini rewrite experiments, mixed-session policy results, and graph data.
