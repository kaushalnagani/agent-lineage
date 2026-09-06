# XRF session-watermark research study

## Executive result

The prototype reliably identifies a session when its hidden Unicode carrier survives, and it can recover several independent session marks from one composite artifact. It is not, however, a security boundary: ordinary model/API normalization removed every origin mark in the three live handoff tests. The correct use is therefore as one authenticated provenance signal inside a broader policy engine, not as proof that content is safe or malicious.

## Experimental design

- Generator/editor model: `gemini-3.5-flash-lite`
- Corpus: six model-generated documents at target lengths 250, 500, and 1,000 words (two per target)
- Codec: authenticated XRF frame carried by Unicode variation selectors, with repetition factors 1, 3, and 5
- Randomized trials: 6,480 total; 20 deterministic seeds per document, attack, rate, and redundancy setting
- Perturbations: selector loss, selector corruption, and visible-word deletion at 0%, 1%, 5%, 10%, 20%, and 35%
- Live handoffs: three origin outputs passed through Gemini, followed by a new editor-session mark
- Multi-session case: two authorized contributors plus one known-malicious contributor in a single artifact
- Primary endpoint: exact authenticated session recovery (HMAC and CRC valid), not merely detection of unusual Unicode

## Main findings

Clean decoding was 100%, and the visible text after encoding was byte-for-byte unchanged after removing the invisible carrier in 100% of encoded samples.

| Perturbation | Rate | r1 | r3 | r5 |
|---|---:|---:|---:|---:|
| Selector corruption | 10% | 20% | 60% | 100% |
| Selector corruption | 20% | 5% | 20% | 85% |
| Selector loss | 10% | 20% | 95% | 100% |
| Selector loss | 20% | 5% | 90% | 100% |
| Selector loss | 35% | 0% | 50% | 95% |
| Word deletion | 1% | 85% | 87.5% | 100% |
| Word deletion | 5% | 38.3% | 35% | 23.3% |
| Word deletion | 10% | 29.2% | 5% | 5.8% |

Repetition is highly effective against carrier-symbol loss and corruption. It does not solve synchronization errors: once visible words are deleted, later carrier symbols shift position, and greater repetition can increase the amount of state that becomes misaligned.

Document length produced no improvement at fixed settings. The current encoder writes one fixed frame near the beginning and does not exploit unused capacity in a longer document. This is a useful negative result: simply requiring longer output is insufficient.

All three Gemini handoffs removed the origin mark. The returned visible text had a similarity ratio of 1.0 in these runs, so the API effectively preserved the readable text while normalizing away the invisible selectors. A fresh editor mark added after the handoff was detected in all three cases. This establishes hop-local provenance but not end-to-end lineage through arbitrary model transformations.

The composite artifact exposed all three contributors. Registry policy returned `review-cross-session` for the two authorized sessions and `block` only for the known-malicious session. A watermark therefore need not make every collaborating session suspicious; the decision should be attached to registry status and graph context.

## Interpretation and next codec

For a second-generation experiment, spread several independently synchronized authenticated shards across the full document. Candidate designs include marker-delimited chunks, interleaving, erasure codes or fountain codes, and content-anchored placement. Evaluate section copy/paste, sentence reordering, Unicode normalization, paraphrase, translation, format conversion, and adversarial stripping. Use a signed or MACed payload with key rotation and a short key identifier; never store a raw session ID in the text.

Operationally, detection should produce a scored provenance event rather than an automatic block. Combine it with tool-call authorization, sandbox boundaries, content provenance, audit logs, and behavioral detection. Missing marks must remain “unknown,” because benign software often strips invisible Unicode; present valid marks identify a known issuer/session but do not prove benign intent.

## Reproducibility and limitations

The aggregate table is in `aggregate-results.csv`, individual randomized observations in `trial-results.csv`, fidelity checks in `fidelity-results.csv`, model handoffs in `rewrite-results.json`, and lineage in `provenance-graph.json`. The run records no API key.

This is a prototype study with six documents, one language, one model family, and synthetic perturbations. Trials within a setting reuse the same documents and are not independent estimates of general Internet traffic. Reported percentages are descriptive, not confidence-certified production guarantees. Variation selectors can be intentionally detected and stripped, so covert-channel robustness and adversarial robustness should be treated separately.
