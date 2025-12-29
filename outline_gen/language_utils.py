"""Language detection utilities for validating LLM outputs.

This module provides lightweight heuristics to determine whether
an outline returned by the LLM is predominantly English or Chinese,
without introducing external dependencies.
"""

from __future__ import annotations

import re
from typing import Dict


def analyze_language(text: str) -> Dict[str, float]:
    """
    Analyze basic language character statistics for the given text.

    Returns a dict with counts and ratios of ASCII letters vs. CJK characters.
    """
    if not text:
        return {
            "ascii_letters": 0,
            "chinese_chars": 0,
            "total_letters": 0,
            "ascii_ratio": 0.0,
            "chinese_ratio": 0.0,
        }

    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))

    total_letters = ascii_letters + chinese_chars
    if total_letters == 0:
        ascii_ratio = 0.0
        chinese_ratio = 0.0
    else:
        ascii_ratio = ascii_letters / total_letters
        chinese_ratio = chinese_chars / total_letters

    return {
        "ascii_letters": ascii_letters,
        "chinese_chars": chinese_chars,
        "total_letters": total_letters,
        "ascii_ratio": ascii_ratio,
        "chinese_ratio": chinese_ratio,
    }


def is_probably_english(text: str) -> bool:
    """
    Heuristically determine whether the text is predominantly English.

    The heuristic is intentionally simple:
    - Count ASCII letters vs. CJK characters.
    - If ASCII letters dominate with a high ratio and there are enough
      letters overall, we treat the text as "mostly English".

    This is designed to catch cases where the LLM returns an English
    outline instead of the expected Chinese one.
    """
    stats = analyze_language(text)

    ascii_letters = stats["ascii_letters"]
    chinese_chars = stats["chinese_chars"]
    total_letters = stats["total_letters"]

    if total_letters == 0:
        return False

    ascii_ratio = stats["ascii_ratio"]
    chinese_ratio = stats["chinese_ratio"]

    # Require a minimum amount of letters to avoid noise on very short texts.
    if ascii_letters < 30:
        return False

    # If ASCII letters clearly dominate and Chinese characters are scarce,
    # we consider the text "mostly English".
    if ascii_ratio >= 0.7 and chinese_ratio <= 0.2:
        return True

    return False

