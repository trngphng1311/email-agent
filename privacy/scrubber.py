"""Redact sensitive substrings before sending text to any LLM."""
import re

import scrubadub

_scrubber = scrubadub.Scrubber()

_PATTERNS = [
    (re.compile(r"(?i)\b(?:password|passwd|mật\s*khẩu|mk)\s*[:=]\s*\S+"), "<PASSWORD>"),
    (re.compile(r"(?i)\b(?:otp|mã\s*otp|mã\s*xác\s*thực)[\s:=]*\d{4,8}\b"), "<OTP>"),
    (re.compile(r"\b(?:sk|ghp|pk|gho|ghu|ghs)_[A-Za-z0-9]{20,}\b"), "<API_KEY>"),
    (re.compile(r"\b\d{13,19}\b"), "<CARD_OR_ACCOUNT>"),
    (re.compile(r"\b\d{1,3}(?:[.,]\d{3}){2,}(?:\s*(?:VND|đ|vnd|đồng))?\b"), "<AMOUNT>"),
]


def scrub(text: str) -> str:
    """Return a redacted copy of text safe to send to a third-party LLM."""
    if not text:
        return text
    out = _scrubber.clean(text)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
