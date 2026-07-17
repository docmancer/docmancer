"""Secret detection and masking for harvested agent memory."""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretPattern:
    name: str
    label: str
    severity: str
    regex: re.Pattern[str]
    # Which regex group holds the secret value to mask/fingerprint; 0 means the
    # whole match. Lets one pattern match a wider context (e.g. a connection
    # string) while only the credential portion is treated as the secret.
    secret_group: int = 0
    # Optional predicate to suppress a match, e.g. a connection string whose
    # password is an obvious documented placeholder rather than a real leak.
    skip: Callable[[re.Match], bool] | None = None


@dataclass(frozen=True)
class SecretFinding:
    type: str
    severity: str
    line: int
    fingerprint: str
    match: str
    masked_excerpt: str


_PLACEHOLDER_PASSWORDS = {
    "password",
    "passwd",
    "pass",
    "changeme",
    "change_me",
    "change-me",
    "yourpassword",
    "your_password",
    "your-password",
    "xxxx",
    "xxxxx",
    "xxxxxxxx",
    "secret",
    "placeholder",
    "example",
    "test",
    "admin",
    "replaceme",
    "replace_me",
    "dbpassword",
    "db_password",
    "supersecret",
}


def _is_placeholder_connection_string(match: re.Match) -> bool:
    password = match.group("password") or ""
    return password.lower() in _PLACEHOLDER_PASSWORDS


# Ordered most-specific first: once a span is claimed by an earlier pattern,
# later (broader) patterns skip it so one real secret is not double-reported
# under two different types/severities (see the overlap check in detect_secrets).
SECRET_PATTERNS = [
    SecretPattern(
        "anthropic_api_key",
        "Anthropic API key",
        "high",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ),
    SecretPattern(
        "openai_api_key",
        "OpenAI-style API key",
        "high",
        re.compile(r"sk-[A-Za-z0-9]{16,}"),
    ),
    SecretPattern(
        "stripe_key",
        "Stripe API key",
        "high",
        re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    ),
    SecretPattern(
        "google_api_key",
        "Google API key",
        "high",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ),
    SecretPattern(
        "github_fine_grained_pat",
        "GitHub token",
        "high",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    SecretPattern(
        "github_token",
        "GitHub token",
        "high",
        re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    ),
    SecretPattern(
        "npm_token",
        "npm token",
        "high",
        re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"),
    ),
    SecretPattern(
        "aws_access_key",
        "AWS access key",
        "high",
        re.compile(r"AKIA[0-9A-Z]{12,}"),
    ),
    SecretPattern(
        "slack_token",
        "Slack token",
        "high",
        re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    ),
    SecretPattern(
        "jwt",
        "JWT / bearer token",
        "high",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    SecretPattern(
        "db_connection_string",
        "Database connection string",
        "high",
        re.compile(
            r"\b[a-zA-Z][a-zA-Z0-9+.-]{1,15}://"
            r"(?P<user>[^\s:/@]{1,64}):(?P<password>[^\s@/]{4,})@(?P<host>[^\s/'\"]+)"
        ),
        skip=_is_placeholder_connection_string,
    ),
    SecretPattern(
        "private_key",
        "Private key block",
        "critical",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    SecretPattern(
        "key_value_secret",
        "Key-value secret",
        "medium",
        re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*([^\s\"']{6,}|[\"'][^\"']{6,}[\"'])"),
        secret_group=2,
    ),
]

_ENTROPY_CANDIDATE = re.compile(r"\b[A-Za-z0-9_./+=-]{32,}\b")
_ENTROPY_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_-.")
_ENTROPY_LOOKBACK = 50
# A secret keyword must sit immediately before the candidate (only an optional
# `:`/`=` and quote/whitespace between them), not merely appear somewhere in
# the last N characters. This is what a real `key: value` or `key=value`
# assignment looks like; a keyword mentioned earlier in a sentence or list
# (e.g. "keywords: ..., apiKey, userSecret, ..., <some other long token>")
# must not count, or any long identifier near secret-sounding prose gets
# misflagged.
_ENTROPY_ADJACENT_CONTEXT = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token|credential|bearer|authorization)[:=]?\s*[\"']?\Z"
)
_UUID_RE = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_FILENAME_EXT_RE = re.compile(
    r"(?i)\.(?:md|markdown|py|js|jsx|ts|tsx|json|jsonl|ya?ml|txt|log|sh|rb|go|rs|toml"
    r"|ini|cfg|conf|html|css|csv|sql|xml|pdf|docx)$"
)


def _has_adjacent_secret_context(text: str, match_start: int) -> bool:
    window = text[max(0, match_start - _ENTROPY_LOOKBACK) : match_start]
    return bool(_ENTROPY_ADJACENT_CONTEXT.search(window))


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _line_excerpt(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return " ".join(text[line_start:line_end].strip().split())


def _mask(secret: str) -> str:
    secret = secret.strip().strip("\"'")
    if len(secret) <= 8:
        return "[SECRET]"
    return f"{secret[:4]}...[SECRET]...{secret[-4:]}"


def _masked_excerpt(text: str, start: int, end: int, secret: str | None = None) -> str:
    excerpt = _line_excerpt(text, start, end)
    matched = secret if secret is not None else text[start:end]
    normalized_match = " ".join((matched or "").strip().split())
    mask = _mask(matched)
    if normalized_match and normalized_match in excerpt:
        masked = excerpt.replace(normalized_match, mask, 1)
    elif matched and matched in excerpt:
        masked = excerpt.replace(matched, mask, 1)
    else:
        masked = mask
    if len(masked) <= 220:
        return masked
    return masked[:219].rstrip() + "..."


def _fingerprint(kind: str, secret: str) -> str:
    return hashlib.sha256(f"{kind}\n{secret.strip()}".encode("utf-8")).hexdigest()[:16]


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {ch: value.count(ch) for ch in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_high_entropy_secret(value: str) -> bool:
    if len(value) < 32 or len(value) > 160:
        return False
    if not set(value) <= _ENTROPY_CHARS:
        return False
    if value.count("-") > 8 or value.count("/") > 6:
        return False
    if _UUID_RE.match(value):
        return False  # session/request identifier, not a secret
    if _FILENAME_EXT_RE.search(value):
        return False  # a path or filename, not a secret
    return _entropy(value) >= 4.2


def _overlaps(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    return any(start < o_end and o_start < end for o_start, o_end in occupied)


def detect_secrets(text: str) -> list[SecretFinding]:
    text = text or ""
    findings: list[SecretFinding] = []
    occupied: list[tuple[int, int]] = []

    for pattern in SECRET_PATTERNS:
        for match in pattern.regex.finditer(text):
            if pattern.skip is not None and pattern.skip(match):
                continue
            secret = match.group(pattern.secret_group) if pattern.secret_group else match.group(0)
            span_start, span_end = match.span(pattern.secret_group) if pattern.secret_group else match.span()
            # A more specific pattern earlier in SECRET_PATTERNS may have
            # already claimed this exact secret; do not report it twice under
            # a second, broader type (e.g. both "OpenAI-style API key" and the
            # generic "Key-value secret" for the same key).
            if _overlaps(span_start, span_end, occupied):
                continue
            findings.append(
                SecretFinding(
                    type=pattern.label,
                    severity=pattern.severity,
                    line=_line_number(text, span_start),
                    fingerprint=_fingerprint(pattern.name, secret),
                    match=match.group(0),
                    masked_excerpt=_masked_excerpt(text, span_start, span_end, secret=secret),
                )
            )
            occupied.append((span_start, span_end))

    for match in _ENTROPY_CANDIDATE.finditer(text):
        if _overlaps(match.start(), match.end(), occupied):
            continue
        value = match.group(0)
        if _has_adjacent_secret_context(text, match.start()) and _looks_like_high_entropy_secret(value):
            findings.append(
                SecretFinding(
                    type="High-entropy token",
                    severity="medium",
                    line=_line_number(text, match.start()),
                    fingerprint=_fingerprint("high_entropy", value),
                    match=value,
                    masked_excerpt=_masked_excerpt(text, match.start(), match.end()),
                )
            )

    findings.sort(key=lambda f: (f.line, f.type, f.fingerprint))
    return findings


def redact_secrets(text: str) -> str:
    out = text or ""
    for finding in sorted(detect_secrets(out), key=lambda f: len(f.match), reverse=True):
        out = out.replace(finding.match, "[REDACTED]")
    return out


__all__ = ["SecretFinding", "detect_secrets", "redact_secrets"]
