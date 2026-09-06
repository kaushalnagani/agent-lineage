# Distributed-watermark fragment study

- Corpus: 1200 lines / 31,690 words / 31,690 eligible carriers / ~105 frames.
- Config: tag_bytes=8, redundancy=3, interval=300 carriers; seed=20260906.
- Fragment trials: 720 (6 lengths x 4 damage levels x 30 trials).
- Damage model: each mutation round drops 5% and corrupts 5% of carriers (cumulative, deterministic).
- Failure boundary (90% exact recovery): smallest reliable fragment at zero damage is 25 lines; max tolerated mutation rounds at 200 lines is 3.
- First sub-90% cell: 5 lines / 0 rounds (30.0%).
- Clean exact recovery at 200 lines: 100.0%.
- Code manifests: 24 chunks; single-line edits change exactly one chunk while the detached manifest still authenticates (see code-manifest-results.csv).

## Exact recovery by fragment length and damage

| lines | mutation rounds | exact recovery |
|---:|---:|---:|
|    5 | 0 | 30.0% |
|    5 | 1 | 26.7% |
|    5 | 2 | 16.7% |
|    5 | 3 | 10.0% |
|   10 | 0 | 76.7% |
|   10 | 1 | 73.3% |
|   10 | 2 | 50.0% |
|   10 | 3 | 20.0% |
|   25 | 0 | 100.0% |
|   25 | 1 | 96.7% |
|   25 | 2 | 73.3% |
|   25 | 3 | 36.7% |
|   50 | 0 | 100.0% |
|   50 | 1 | 100.0% |
|   50 | 2 | 100.0% |
|   50 | 3 | 70.0% |
|  100 | 0 | 100.0% |
|  100 | 1 | 100.0% |
|  100 | 2 | 100.0% |
|  100 | 3 | 90.0% |
|  200 | 0 | 100.0% |
|  200 | 1 | 100.0% |
|  200 | 2 | 100.0% |
|  200 | 3 | 100.0% |

## Code manifest localization

| case | matching / total | exact content | manifest authentic | changed chunks |
|---|---|---|---|---|
| no-edit control | 24/24 | True | True | [] |
| single-line edit | 23/24 | False | True | [5] |
| three-line localized edit | 23/24 | False | True | [12] |
| two-line cross-chunk-boundary edit | 22/24 | False | True | [3, 4] |
| two scattered single-line edits | 22/24 | False | True | [2, 17] |

See `fragment-study.png` for the chart, `summary.json` for machine-readable results, and `fragment-trials.csv` for every trial. No secrets are stored in outputs.
