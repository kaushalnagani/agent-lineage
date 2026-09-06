# Contributing

Contributions that improve reproducibility, carrier robustness, false-positive measurement, provenance policy, documentation, or privacy analysis are welcome.

Before opening a pull request:

1. Keep secrets and provider keys out of code, fixtures, logs, and generated output.
2. Add focused tests for behavior changes.
3. Run `python -m unittest discover -s tests -v`.
4. Report both successes and failures; do not describe a watermark as a security boundary.
5. Include the seed, corpus description, transformation, trial count, and exact-recovery definition for benchmark changes.

Use synthetic, public, or appropriately licensed inputs. Do not submit private conversations, credentials, or identifiable session data.
