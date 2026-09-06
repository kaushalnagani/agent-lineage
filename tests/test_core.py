from __future__ import annotations

import unittest

from watermark_lab import CapacityError, WatermarkConfig, detect_watermark, detect_watermarks, embed_watermark, session_tag
from watermark_lab.core import _byte_to_selector, _selector_to_byte, rendered_equivalent, strip_watermark_characters
from watermark_lab.registry import match_tag


SECRET = "0123456789abcdef0123456789abcdef"
TEXT = (
    "The monitoring service reviews generated responses before they enter another agent context "
    "and records useful provenance information for careful security analysis and later inspection. "
) * 8


class WatermarkTests(unittest.TestCase):
    def test_selector_round_trip(self) -> None:
        for value in range(256):
            self.assertEqual(_selector_to_byte(_byte_to_selector(value)), value)

    def test_round_trip(self) -> None:
        config = WatermarkConfig(tag_bytes=8, redundancy=3)
        marked = embed_watermark(TEXT, "session-a", SECRET, config)
        detection = detect_watermark(marked, redundancy=3)
        self.assertTrue(detection.found)
        self.assertEqual(detection.tag_hex, session_tag(SECRET, "session-a").hex())
        self.assertTrue(rendered_equivalent(TEXT, marked))
        self.assertEqual(strip_watermark_characters(marked), TEXT)

    def test_finds_watermark_inside_larger_input(self) -> None:
        config = WatermarkConfig(tag_bytes=4, redundancy=1)
        marked = embed_watermark(TEXT, "session-b", SECRET, config)
        combined = "Unrelated introductory words appear before copied material in this input. " + marked
        detection = detect_watermark(combined, redundancy=1)
        self.assertTrue(detection.found)

    def test_majority_corrects_one_symbol_per_group(self) -> None:
        config = WatermarkConfig(tag_bytes=4, redundancy=3)
        marked = embed_watermark(TEXT, "session-c", SECRET, config)
        chars = list(marked)
        selector_positions = [i for i, char in enumerate(chars) if _selector_to_byte(char) is not None]
        for position in selector_positions[::3]:
            value = _selector_to_byte(chars[position])
            chars[position] = _byte_to_selector((value or 0) ^ 1)
        detection = detect_watermark("".join(chars), redundancy=3)
        self.assertTrue(detection.found)
        self.assertGreater(detection.corrected_groups, 0)

    def test_capacity_error(self) -> None:
        with self.assertRaises(CapacityError):
            embed_watermark("This sentence is much too short for the complete frame.", "x", SECRET)

    def test_long_unmarked_text_is_not_detected(self) -> None:
        self.assertFalse(detect_watermark(TEXT, redundancy=1).found)

    def test_registry_blocks_malicious_cross_session(self) -> None:
        tag = session_tag(SECRET, "bad-session").hex()
        match = match_tag(
            tag,
            [{"session_id": "bad-session", "status": "malicious"}],
            SECRET,
            destination_session="other-session",
        )
        self.assertEqual(match.session_id, "bad-session")
        self.assertEqual(match.action, "block")

    def test_registry_allows_same_session(self) -> None:
        tag = session_tag(SECRET, "same-session").hex()
        match = match_tag(
            tag,
            [{"session_id": "same-session", "status": "authorized"}],
            SECRET,
            destination_session="same-session",
        )
        self.assertEqual(match.action, "allow-self")

    def test_multiple_layered_sessions_are_detected(self) -> None:
        config = WatermarkConfig(tag_bytes=4, redundancy=1)
        first = embed_watermark(TEXT, "session-one", SECRET, config)
        layered = embed_watermark(first, "session-two", SECRET, config, preserve_existing=True)
        tags = {item.tag_hex for item in detect_watermarks(layered, redundancy=1)}
        self.assertEqual(
            tags,
            {
                session_tag(SECRET, "session-one", 4).hex(),
                session_tag(SECRET, "session-two", 4).hex(),
            },
        )


if __name__ == "__main__":
    unittest.main()
