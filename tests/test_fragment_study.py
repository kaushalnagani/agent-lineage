from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "run_fragment_study", str(Path(__file__).resolve().parents[1] / "scripts" / "run_fragment_study.py")
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

from watermark_lab import WatermarkConfig, detect_watermark, embed_distributed_watermark, session_tag
from watermark_lab.code_provenance import create_code_manifest, verify_code_manifest

SECRET = b"fragment-test-key-00123456789ABCDEF-test-only-0001"


class FragmentStudyTests(unittest.TestCase):
    def test_corpus_has_at_least_1000_lines_and_is_deterministic(self) -> None:
        first = _MOD.build_prose_lines(1200, 20260906)
        second = _MOD.build_prose_lines(1200, 20260906)
        self.assertGreaterEqual(len(first), 1000)
        self.assertEqual(first, second)

    def test_large_fragment_recovers_distributed_mark(self) -> None:
        lines = _MOD.build_prose_lines(150, 7)
        corpus = "\n".join(lines) + "\n"
        config = WatermarkConfig(tag_bytes=4, redundancy=1)
        marked = embed_distributed_watermark(corpus, "frag-test", SECRET, config, interval_carriers=60)
        marked_lines = marked.splitlines()
        fragment = "\n".join(marked_lines[10:110])
        detection = detect_watermark(fragment, 1)
        self.assertTrue(detection.found)
        self.assertEqual(detection.tag_hex, session_tag(SECRET, "frag-test", 4).hex())

    def test_mutation_rounds_are_deterministic(self) -> None:
        self.assertEqual(
            _MOD.apply_mutation_rounds("sample text here", 11, 2, 0.05, 0.05),
            _MOD.apply_mutation_rounds("sample text here", 11, 2, 0.05, 0.05),
        )

    def test_failure_boundary_picks_smallest_reliable_length(self) -> None:
        aggregate = [
            {"fragment_lines": 5, "mutation_rounds": 0, "trials": 4, "exact_recovery_rate": 0.25},
            {"fragment_lines": 25, "mutation_rounds": 0, "trials": 4, "exact_recovery_rate": 1.0},
            {"fragment_lines": 5, "mutation_rounds": 1, "trials": 4, "exact_recovery_rate": 0.0},
            {"fragment_lines": 25, "mutation_rounds": 1, "trials": 4, "exact_recovery_rate": 0.95},
        ]
        boundaries = _MOD.failure_boundaries(aggregate, threshold=0.9)
        self.assertEqual(boundaries["min_reliable_fragment_lines_at_zero_damage"], 25)
        self.assertEqual(boundaries["max_tolerated_mutation_rounds_at_largest_fragment"], 1)

    def test_code_manifest_localizes_single_line_edit(self) -> None:
        code = _MOD.build_code_text(200, 3)
        manifest = create_code_manifest(code, "code-test", SECRET, chunk_lines=50)
        lines = code.splitlines(keepends=True)
        edited = list(lines)
        edited[53] = "edited = dangerous_call()\n"
        result = verify_code_manifest("".join(edited), manifest, SECRET)
        self.assertTrue(result["manifest_authentic"])
        self.assertFalse(result["exact_content"])
        self.assertEqual(result["changed_chunks"], [1])


if __name__ == "__main__":
    unittest.main()
