"""Output sanitization — verify LLM responses don't leak sensitive data.

After deanonymization, scan the response for any residual placeholders
or patterns that suggest the LLM echoed back raw PII/PPI that wasn't
properly anonymized on the way in.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("securellm.sanitizer")

# Patterns that should NEVER appear in final output to the user
# (they indicate a leak or incomplete deanonymization)
RESIDUAL_PLACEHOLDER_PATTERNS = [
    re.compile(r"\[PRODUCT_\d+\]"),           # PPI placeholder leaked
    re.compile(r"<[A-Z_]+_\d+>"),             # PII placeholder leaked
]

# Common PII patterns that might appear in LLM output even after deanonymization
# These indicate the LLM hallucinated or echoed PII it shouldn't have seen
SENSITIVE_PATTERNS = [
    re.compile(r"\b[A-Z]{2}\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b"),  # IBAN
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),                  # Credit card
]


def sanitize_response(text: str, warn_only: bool = True) -> tuple[str, list[str]]:
    """Scan LLM response for data leaks.

    Returns (sanitized_text, list_of_warnings).
    If warn_only=False, replaces detected patterns with [REDACTED].
    """
    warnings: list[str] = []

    # Check for residual placeholders (incomplete deanonymization)
    for pattern in RESIDUAL_PLACEHOLDER_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            unique = list(set(matches))
            warnings.append(f"Residual placeholders found: {unique}")
            if not warn_only:
                text = pattern.sub("[REDACTED]", text)

    # Check for sensitive data patterns in output
    for pattern in SENSITIVE_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            warnings.append(f"Sensitive pattern detected in output ({len(matches)} matches)")
            if not warn_only:
                text = pattern.sub("[REDACTED]", text)

    if warnings:
        logger.warning("Output sanitization warnings: %s", warnings)

    return text, warnings


def validate_no_raw_data_in_prompt(
    original_texts: list[str],
    anonymized_messages: list[dict],
) -> list[str]:
    """Verify that no raw text from original input appears in the anonymized messages.

    This is a defense-in-depth check — if anonymization failed silently,
    this catches it before sending to the LLM.
    """
    warnings: list[str] = []

    for original in original_texts:
        if not original or len(original) < 10:
            continue
        # Check substrings of the original in the anonymized output
        for msg in anonymized_messages:
            content = msg.get("content", "")
            # Look for exact matches of original text fragments (>20 chars)
            # Skip if the original is very short (common words)
            words = original.split()
            for i in range(len(words) - 3):
                fragment = " ".join(words[i:i+4])
                if len(fragment) > 20 and fragment in content:
                    # Check it's not a placeholder
                    if not re.match(r"[\[<]", fragment):
                        warnings.append(f"Raw text fragment found in anonymized output: '{fragment[:30]}...'")
                        break

    if warnings:
        logger.error("CRITICAL: Raw data leak detected in anonymized messages: %s", warnings)

    return warnings
