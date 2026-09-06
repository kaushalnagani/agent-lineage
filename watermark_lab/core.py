"""Core XRF watermark encoder and detector.

The initial carrier maps one byte to one Unicode variation selector placed after
an eligible prose word. Variation selectors are normally invisible, so the
rendered text remains unchanged. This is intentionally a research codec: it is
high-capacity and deterministic, but normalization or deliberate stripping can
remove it. The benchmark scripts quantify those limitations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import hmac
import re
import struct
import unicodedata
import zlib


MAGIC = b"XRF"
VERSION = 1
DEFAULT_TAG_BYTES = 8

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_PROTECTED_RE = re.compile(
    r"```.*?```|`[^`\n]+`|https?://\S+|www\.\S+|"
    r"\b(?:CVE-\d{4}-\d{4,}|[A-Fa-f0-9]{32,}|\d+(?:\.\d+)?%?)\b",
    re.DOTALL,
)
_LOCKED_WORDS = {
    "no", "not", "never", "neither", "nor", "without", "except",
    "deny", "denies", "denied", "prevent", "prevents", "prevented",
    "fail", "fails", "failed", "false", "true",
}


class CapacityError(ValueError):
    """Raised when text has too few eligible words for the requested frame."""


@dataclass(frozen=True)
class WatermarkConfig:
    tag_bytes: int = DEFAULT_TAG_BYTES
    redundancy: int = 3

    def __post_init__(self) -> None:
        if not 4 <= self.tag_bytes <= 24:
            raise ValueError("tag_bytes must be between 4 and 24")
        if self.redundancy < 1 or self.redundancy % 2 == 0:
            raise ValueError("redundancy must be a positive odd number")

    @property
    def frame_bytes(self) -> int:
        # magic + version + tag length + tag + CRC32
        return 3 + 1 + 1 + self.tag_bytes + 4

    @property
    def minimum_carriers(self) -> int:
        return self.frame_bytes * self.redundancy


@dataclass(frozen=True)
class Detection:
    found: bool = False
    tag_hex: str | None = None
    version: int | None = None
    carrier_offset: int | None = None
    corrected_groups: int = 0
    confidence: float = 0.0
    reason: str = "watermark not found"


def session_tag(secret: str | bytes, session_id: str, tag_bytes: int = DEFAULT_TAG_BYTES) -> bytes:
    """Return an opaque tag; the raw session ID is never placed in the text."""
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(key) < 16:
        raise ValueError("secret must be at least 16 bytes")
    return hmac.new(key, b"XRF/session/" + session_id.encode("utf-8"), hashlib.sha256).digest()[:tag_bytes]


def _frame(tag: bytes) -> bytes:
    header = MAGIC + bytes((VERSION, len(tag))) + tag
    return header + struct.pack(">I", zlib.crc32(header) & 0xFFFFFFFF)


def _byte_to_selector(value: int) -> str:
    if not 0 <= value <= 255:
        raise ValueError("selector value must be a byte")
    if value < 16:
        return chr(0xFE00 + value)
    return chr(0xE0100 + value - 16)


def _selector_to_byte(char: str) -> int | None:
    value = ord(char)
    if 0xFE00 <= value <= 0xFE0F:
        return value - 0xFE00
    if 0xE0100 <= value <= 0xE01EF:
        return value - 0xE0100 + 16
    return None


def strip_watermark_characters(text: str) -> str:
    """Remove the variation-selector alphabet used by this prototype."""
    return "".join(char for char in text if _selector_to_byte(char) is None)


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _PROTECTED_RE.finditer(text)]


def _inside_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def _carrier_ends(text: str) -> list[int]:
    """Return insertion points following eligible, non-sensitive prose words."""
    ranges = _protected_ranges(text)
    ends: list[int] = []
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        if _inside_ranges(match.start(), ranges):
            continue
        if word.lower() in _LOCKED_WORDS:
            continue
        # Preserve likely named entities and acronyms. Sentence-initial title
        # case is allowed only when it follows sentence punctuation.
        if word.isupper() and len(word) > 1:
            continue
        if word[0].isupper():
            prefix = text[: match.start()].rstrip()
            if prefix and prefix[-1] not in ".!?\n":
                continue
        ends.append(match.end())
    return ends


def capacity(text: str, config: WatermarkConfig = WatermarkConfig()) -> dict[str, int | bool]:
    eligible = len(_carrier_ends(strip_watermark_characters(text)))
    return {
        "eligible_words": eligible,
        "required_words": config.minimum_carriers,
        "frame_bytes": config.frame_bytes,
        "redundancy": config.redundancy,
        "fits": eligible >= config.minimum_carriers,
    }


def embed_watermark(
    text: str,
    session_id: str,
    secret: str | bytes,
    config: WatermarkConfig = WatermarkConfig(),
    preserve_existing: bool = False,
) -> str:
    """Embed an XRF frame into text and return visually equivalent output."""
    clean = text if preserve_existing else strip_watermark_characters(text)
    tag = session_tag(secret, session_id, config.tag_bytes)
    symbols = [byte for byte in _frame(tag) for _ in range(config.redundancy)]
    carriers = [
        end
        for end in _carrier_ends(clean)
        if end >= len(clean) or _selector_to_byte(clean[end]) is None
    ]
    if len(carriers) < len(symbols):
        raise CapacityError(
            f"need {len(symbols)} eligible words, found {len(carriers)}; "
            f"use lower redundancy, a shorter tag, or longer text"
        )

    insertions = list(zip(carriers[: len(symbols)], symbols))
    result = clean
    for position, value in reversed(insertions):
        result = result[:position] + _byte_to_selector(value) + result[position:]
    return result


def embed_distributed_watermark(
    text: str,
    session_id: str,
    secret: str | bytes,
    config: WatermarkConfig = WatermarkConfig(),
    interval_carriers: int = 300,
    preserve_existing: bool = False,
) -> str:
    """Embed complete, independently decodable frames throughout long prose.

    ``interval_carriers`` is the distance between frame starts. Each frame is
    complete, so a copied subsection can decode without material from the
    beginning of the original document.
    """
    if interval_carriers < config.minimum_carriers:
        raise ValueError("interval_carriers must be at least one complete frame")
    clean = text if preserve_existing else strip_watermark_characters(text)
    tag = session_tag(secret, session_id, config.tag_bytes)
    symbols = [byte for byte in _frame(tag) for _ in range(config.redundancy)]
    carriers = [end for end in _carrier_ends(clean) if end >= len(clean) or _selector_to_byte(clean[end]) is None]
    if len(carriers) < len(symbols):
        raise CapacityError(f"need {len(symbols)} eligible words, found {len(carriers)}")
    starts = list(range(0, len(carriers) - len(symbols) + 1, interval_carriers))
    tail_start = len(carriers) - len(symbols)
    if tail_start - starts[-1] >= interval_carriers // 2:
        starts.append(tail_start)
    insertions = []
    for start in starts:
        insertions.extend(zip(carriers[start:start + len(symbols)], symbols))
    result = clean
    for position, value in reversed(insertions):
        result = result[:position] + _byte_to_selector(value) + result[position:]
    return result


def _observations(text: str) -> list[int | None]:
    """Read a selector, if present, after every eligible carrier word."""
    carriers = _carrier_ends(text)
    observations: list[int | None] = []
    for end in carriers:
        observations.append(_selector_to_byte(text[end]) if end < len(text) else None)
    return observations


def _majority(group: list[int | None]) -> tuple[int | None, bool, float]:
    present = [value for value in group if value is not None]
    if not present:
        return None, False, 0.0
    value, count = Counter(present).most_common(1)[0]
    corrected = len(set(present)) > 1 or len(present) < len(group)
    return value, corrected, count / len(group)


def _decode_at(
    observations: list[int | None], offset: int, redundancy: int
) -> tuple[bytes | None, int, float]:
    decoded: list[int] = []
    corrected = 0
    agreements: list[float] = []

    # Decode fixed header first. The XRF prefix makes most offsets cheap rejects.
    for index in range(5):
        start = offset + index * redundancy
        value, was_corrected, agreement = _majority(observations[start : start + redundancy])
        if value is None:
            return None, corrected, 0.0
        decoded.append(value)
        corrected += int(was_corrected)
        agreements.append(agreement)
    if bytes(decoded[:3]) != MAGIC or decoded[3] != VERSION:
        return None, corrected, 0.0
    tag_length = decoded[4]
    if not 4 <= tag_length <= 24:
        return None, corrected, 0.0

    frame_length = 3 + 1 + 1 + tag_length + 4
    needed = offset + frame_length * redundancy
    if needed > len(observations):
        return None, corrected, 0.0
    for index in range(5, frame_length):
        start = offset + index * redundancy
        value, was_corrected, agreement = _majority(observations[start : start + redundancy])
        if value is None:
            return None, corrected, 0.0
        decoded.append(value)
        corrected += int(was_corrected)
        agreements.append(agreement)

    frame = bytes(decoded)
    expected_crc = struct.unpack(">I", frame[-4:])[0]
    if zlib.crc32(frame[:-4]) & 0xFFFFFFFF != expected_crc:
        return None, corrected, 0.0
    return frame, corrected, sum(agreements) / len(agreements)


def detect_watermark(text: str, redundancy: int = 3) -> Detection:
    """Scan arbitrary input for a valid XRF frame."""
    detections = detect_watermarks(text, redundancy)
    return detections[0] if detections else Detection(reason="no valid XRF frame or CRC")


def detect_watermarks(text: str, redundancy: int = 3) -> list[Detection]:
    """Return every non-overlapping valid XRF frame found in arbitrary input."""
    if redundancy < 1 or redundancy % 2 == 0:
        raise ValueError("redundancy must be a positive odd number")
    observations = _observations(text)
    minimum = (3 + 1 + 1 + 4 + 4) * redundancy
    if len(observations) < minimum:
        return []

    detections: list[Detection] = []
    occupied_until = -1
    for offset in range(0, len(observations) - minimum + 1):
        if offset < occupied_until:
            continue
        frame, corrected, confidence = _decode_at(observations, offset, redundancy)
        if frame is None:
            continue
        tag_length = frame[4]
        tag = frame[5 : 5 + tag_length]
        detections.append(
            Detection(
                found=True,
                tag_hex=tag.hex(),
                version=frame[3],
                carrier_offset=offset,
                corrected_groups=corrected,
                confidence=confidence,
                reason="valid XRF prefix and CRC",
            )
        )
        occupied_until = offset + (3 + 1 + 1 + tag_length + 4) * redundancy
    return detections


def rendered_equivalent(original: str, watermarked: str) -> bool:
    """True when this prototype changed only its invisible carrier characters."""
    return unicodedata.normalize("NFC", original) == unicodedata.normalize(
        "NFC", strip_watermark_characters(watermarked)
    )
