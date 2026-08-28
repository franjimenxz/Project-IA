import re

_BEARER_RE = re.compile(r"(?i)(Bearer)\s+\S+")
_BASIC_RE = re.compile(r"(?i)(Basic)\s+\S+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_API_KEY_RE = re.compile(r"(?i)(api[_-]?key)\s*[=:]\s*\S+")
_DNI_RE = re.compile(r"(?i)\b(DNI)\s*:?\s*\d{7,8}\b")
_PHONE_RE = re.compile(r"\+\d{1,3}(?:[\s-]?\d{2,4}){2,4}")


def redact(value: str) -> str:
    redacted = _BEARER_RE.sub(r"\1 [REDACTED]", value)
    redacted = _BASIC_RE.sub(r"\1 [REDACTED]", redacted)
    redacted = _API_KEY_RE.sub(r"\1=[REDACTED]", redacted)
    redacted = _DNI_RE.sub(r"\1 [REDACTED]", redacted)
    redacted = _PHONE_RE.sub("[PHONE]", redacted)
    return _EMAIL_RE.sub("[EMAIL]", redacted)
