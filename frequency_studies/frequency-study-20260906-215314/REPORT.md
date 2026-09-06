# Watermark placement-frequency study

This deterministic experiment crosses five copied-fragment lengths, five corruption rates, three complete-frame intervals, and three symbol-repetition levels: **4,500 trials across 225 aggregate cells**. Every cell contains 20 randomly positioned contiguous fragments from the same 1,200-line synthetic corpus.

## Reading the figure

- Horizontal axis: copied fragment length in lines (10, 25, 50, 100, or 200).
- Vertical axis: proportion of encoded variation selectors whose byte value was corrupted (0%, 5%, 10%, 20%, or 35%).
- Panel columns: frame placement interval. Smaller intervals mean more frequent complete frames.
- Panel rows: repetition factor. `r5` writes each frame byte five times and decodes it by majority vote.
- Cell value/color: probability of exact recovery across 20 trials. A recovery counts only when the session tag and CRC decode correctly.

## Main observations

1. Placement frequency primarily controls small-fragment coverage. With `r1`, a clean 10-line fragment recovered at 100% for a 100-word interval, 80% for 300 words, and 30% for 600 words.
2. Symbol repetition controls corruption resistance. For a 50-line fragment with 20% corruption, `r3` recovered at 100%, 85%, and 50% across the 100-, 300-, and 600-word intervals; `r1` recovered at only 25%, 5%, and 10%.
3. Large fragments provide multiple recovery opportunities. At 35% corruption, 200-line `r5` fragments recovered at 100%, 100%, and 95% across all three intervals.
4. Frequency cannot replace error correction, and repetition cannot guarantee a complete frame exists in a very short fragment. They address different failure modes.

## Scope

These are descriptive prototype results on a synthetic English corpus. Carrier corruption is not equivalent to paraphrase, word deletion, Unicode stripping, or a model-mediated rewrite. The long-form study covers several of those transformations separately. Absence of a valid frame means unknown, not safe.
