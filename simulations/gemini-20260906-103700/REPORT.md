# Gemini XRF simulation report

- Model: `gemini-3.5-flash-lite`
- Generated samples: 3
- Configurations: redundancy 1 and redundancy 3 for every sample
- Total simulation folders: 6
- Generated output lengths: 131, 172, and 177 words
- Session tag: 8-byte opaque HMAC-derived value

## Clean-output results

| Metric | Result |
|---|---:|
| Successful encodings | 6/6 |
| Watermark detections | 6/6 |
| Exact session-tag recovery | 6/6 |
| Visible word changes | 0 |
| Visible similarity | 1.0 for every simulation |
| Inserted invisible characters, redundancy 1 | 17 |
| Inserted invisible characters, redundancy 3 | 51 |

## Attack results

| Transformation | Redundancy 1 | Redundancy 3 | Combined |
|---|---:|---:|---:|
| No transformation | 3/3 | 3/3 | 6/6 |
| NFC normalization | 3/3 | 3/3 | 6/6 |
| NFKC normalization | 3/3 | 3/3 | 6/6 |
| Spacing normalization | 3/3 | 3/3 | 6/6 |
| 10% random selector deletion | 1/3 | 3/3 | 4/6 |
| 5% random selector corruption | 2/3 | 3/3 | 5/6 |
| Remove every selector | 0/3 | 0/3 | 0/6 |

These are small, seeded experiments and should not be interpreted as estimated
population-level reliability. The next run should use at least hundreds of
samples, varied output lengths, repeated random seeds, paraphrasing, translation,
copy/paste through real platforms, truncation, and mixed-session inputs.

Each simulation directory contains the original and marked text, a human-visible
diff, exact Unicode insertion locations, clean detection output, and transformed
attack samples.
