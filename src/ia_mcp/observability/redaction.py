import re

# Value delimiters: a redacted value ends at the first structural separator so a
# single credential never swallows the rest of a log line or a JSON document.
_VALUE = r"[^\"'\r\n,;}\]]+"
_KEY = r"[\w.\-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|credential)[\w.\-]*"

_HEADER_RE = re.compile(
    rf"(?i)\b(authorization|proxy-authorization|set-cookie|cookie|x-api-key)"
    rf"[\"']?\s*[:=]\s*[\"']?{_VALUE}"
)
_BEARER_RE = re.compile(r"(?i)(Bearer)\s+\S+")
_CONNECTION_STRING_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.\-]{1,20})://[^\s/@:]+:[^\s/@]+@[^\s/?#,;\"']+"
)
_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?P<key>{_KEY})(?P<separator>[\"']?\s*[:=]\s*[\"']?)(?P<value>{_VALUE})"
)
_REFERENCE_KEY_RE = re.compile(r"(?i)(reference|_ref)$")
# The spared part of a reference value is its first whitespace-free token.
_FIRST_TOKEN_RE = re.compile(r"(?s)^(?P<token>\S*)(?P<gap>\s*)(?P<rest>.*)$")
_LABELLED_DOCUMENT_RE = re.compile(
    r"(?i)\b(dni|documento|document_number|cuit|cuil|c[eé]dula|pasaporte)\b\W{0,4}"
    r"\d{1,3}(?:[.\s-]?\d{3}){1,3}"
)
_DOTTED_DOCUMENT_RE = re.compile(r"\b\d{1,3}\.\d{3}\.\d{3}\b")
_INTERNATIONAL_PHONE_RE = re.compile(r"\+\d{1,3}(?:[\s.\-()]?\d){6,14}")
_LABELLED_PHONE_RE = re.compile(
    r"(?i)\b(tel|tel[eé]fono|celular|cel|whatsapp|phone|m[oó]vil)\b\W{0,4}"
    r"\d(?:[\s.\-()]?\d){5,13}"
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _mask_assignment(match: re.Match[str]) -> str:
    key = match.group("key")
    if not _REFERENCE_KEY_RE.search(key):
        return f"{key}=[REDACTED]"
    # `credentials_reference` names a secret; it is not the secret itself and
    # stays readable so operators can correlate an integration. The immunity
    # covers one token only: on an unquoted line the value runs to the end, so
    # sparing all of it would shield whatever shares the line. The remainder is
    # scanned again, which is what stops `reference=... password=...`.
    parts = _FIRST_TOKEN_RE.match(match.group("value"))
    if parts is None or not parts.group("rest"):
        return match.group(0)
    remainder = _ASSIGNMENT_RE.sub(_mask_assignment, parts.group("rest"))
    return (
        f"{key}{match.group('separator')}{parts.group('token')}"
        f"{parts.group('gap')}{remainder}"
    )


# T01 (P07-T01) patterns kept in union with T03 assignment/connection-string redaction.
_BASIC_RE = re.compile(r"(?i)(Basic)\s+\S+")
_API_KEY_RE = re.compile(r"(?i)(api[_-]?key)\s*[=:]\s*\S+")
_DNI_RE = re.compile(r"(?i)\b(DNI)\s*:?\s*\d{7,8}\b")
_PHONE_RE = re.compile(r"\+\d{1,3}(?:[\s-]?\d{2,4}){2,4}")


def redact(value: str) -> str:
    redacted = _HEADER_RE.sub(r"\1: [REDACTED]", value)
    redacted = _BEARER_RE.sub(r"\1 [REDACTED]", redacted)
    redacted = _BASIC_RE.sub(r"\1 [REDACTED]", redacted)
    redacted = _CONNECTION_STRING_RE.sub(r"\1://[REDACTED]", redacted)
    redacted = _ASSIGNMENT_RE.sub(_mask_assignment, redacted)
    redacted = _API_KEY_RE.sub(r"\1=[REDACTED]", redacted)
    redacted = _DNI_RE.sub(r"\1 [REDACTED]", redacted)
    redacted = _LABELLED_DOCUMENT_RE.sub(r"\1 [DOCUMENT]", redacted)
    redacted = _DOTTED_DOCUMENT_RE.sub("[DOCUMENT]", redacted)
    redacted = _LABELLED_PHONE_RE.sub(r"\1 [PHONE]", redacted)
    redacted = _INTERNATIONAL_PHONE_RE.sub("[PHONE]", redacted)
    redacted = _PHONE_RE.sub("[PHONE]", redacted)
    return _EMAIL_RE.sub("[EMAIL]", redacted)
