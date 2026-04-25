"""Decide whether an email's content is sensitive enough to stay local-only."""
import re

_SENSITIVE_KEYWORDS = re.compile(
    r"(?i)("
    r"\bpassword\b|\bpasswd\b|\bOTP\b|\b2FA\b|\bSSN\b|"
    r"credit\s*card\s*number|routing\s*number|account\s*number|\bIBAN\b|"
    r"mật\s*khẩu|mã\s*OTP|biên\s*lai|chuyển\s*tiền|số\s*tài\s*khoản|"
    r"vietcombank|\bVCB\b"
    r")"
)

_SENSITIVE_SENDER_HINTS = re.compile(
    r"(?i)(\bbank\b|vcbdigibank|vietcombank|paypal|stripe|"
    r"healthcare|clinic|hospital|doctor|lawyer)"
)


def is_sensitive(subject: str, body: str, sender: str) -> bool:
    """True if this email should be routed to local-only (Ollama)."""
    if _SENSITIVE_SENDER_HINTS.search(sender or ""):
        return True
    if _SENSITIVE_KEYWORDS.search(f"{subject}\n{body}"):
        return True
    return False
