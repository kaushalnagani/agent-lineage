"""Controlled transformations for watermark robustness experiments."""

from __future__ import annotations

import random
import re
import unicodedata

from .core import _byte_to_selector, _selector_to_byte, strip_watermark_characters


def identity(text: str, rng: random.Random) -> str:
    del rng
    return text


def unicode_nfc(text: str, rng: random.Random) -> str:
    del rng
    return unicodedata.normalize("NFC", text)


def unicode_nfkc(text: str, rng: random.Random) -> str:
    del rng
    return unicodedata.normalize("NFKC", text)


def strip_selectors(text: str, rng: random.Random) -> str:
    del rng
    return strip_watermark_characters(text)


def drop_selectors(text: str, rng: random.Random, probability: float = 0.1) -> str:
    return "".join(
        char
        for char in text
        if _selector_to_byte(char) is None or rng.random() >= probability
    )


def corrupt_selectors(text: str, rng: random.Random, probability: float = 0.05) -> str:
    output: list[str] = []
    for char in text:
        value = _selector_to_byte(char)
        if value is not None and rng.random() < probability:
            value ^= 1 << rng.randrange(8)
            char = _byte_to_selector(value)
        output.append(char)
    return "".join(output)


def normalize_spaces(text: str, rng: random.Random) -> str:
    del rng
    return re.sub(r"[ \t]+", " ", text)


ATTACKS = {
    "identity": identity,
    "nfc": unicode_nfc,
    "nfkc": unicode_nfkc,
    "strip": strip_selectors,
    "drop10": drop_selectors,
    "corrupt05": corrupt_selectors,
    "spaces": normalize_spaces,
}

