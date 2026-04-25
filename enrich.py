"""Body/subject derived fields added during sync (no LLM)."""
import re

_SUBJECT_PREFIX_RE = re.compile(
    r"^\s*(?:re|fwd|fw|r|tr|sv|aw|antw)\s*[:：]\s*|^\s*\[[^\]]+\]\s*",
    re.IGNORECASE,
)

_MISSING_ATTACH_RE = re.compile(
    r"(?i)("
    r"please\s+find\s+attached|see\s+attached|attached\s+please\s+find|"
    r"attached\s+(?:is|are|file|document|image|invoice|report)|"
    r"enclosed\s+(?:is|please|herewith)|"
    r"i[' ]?ve\s+attached|i\s+have\s+attached|"
    r"đính\s*kèm|file\s*đính\s*kèm|kèm\s*theo|xem\s*file\s*kèm"
    r")"
)


def normalize_subject(subject: str) -> str:
    """Strip Re:/Fwd:/[tag] prefixes and lowercase for grouping."""
    s = (subject or "").strip()
    while True:
        new = _SUBJECT_PREFIX_RE.sub("", s).strip()
        if new == s:
            break
        s = new
    return s.lower()


def detect_missing_attachment(body: str, has_attachment: bool) -> bool:
    """Body mentions an attachment but the email doesn't have one."""
    if has_attachment or not body:
        return False
    return bool(_MISSING_ATTACH_RE.search(body))
