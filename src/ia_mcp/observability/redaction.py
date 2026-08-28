import re

_BEARER_RE = re.compile(r"(?i)(Bearer)\s+\S+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def redact(value: str) -> str:
    redacted = _BEARER_RE.sub(r"\1 [REDACTED]", value)
    return _EMAIL_RE.sub("[EMAIL]", redacted)
