"""Secret detection and masking for harvested agent memory."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretPattern:
    name: str
    label: str
    severity: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class SecretFinding:
    type: str
    severity: str
    line: int
    fingerprint: str
    match: str
    masked_excerpt: str


SECRET_PATTERNS = [
    SecretPattern(
        "openai_api_key",
        "OpenAI-style API key",
        "high",
        re.compile(r"sk-[A-Za-z0-9]{16,}"),
    ),
    SecretPattern(
        "github_token",
        "GitHub token",
        "high",
        re.compile(r"ghp_[A-Za-z0-9]{8,}"),
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
    ),
]

_ENTROPY_CANDIDATE = re.compile(r"\b[A-Za-z0-9_./+=-]{32,}\b")
_ENTROPY_ALLOWED_CONTEXT = re.compile(r"(?i)(api[_-]?key|secret|password|token|credential|bearer|authorization)")
_ENTROPY_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_-.")


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
    return _entropy(value) >= 4.2


def detect_secrets(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    occupied: list[tuple[int, int]] = []

    for pattern in SECRET_PATTERNS:
        for match in pattern.regex.finditer(text or ""):
            secret = match.group(2) if pattern.name == "key_value_secret" and match.lastindex else match.group(0)
            findings.append(
                SecretFinding(
                    type=pattern.label,
                    severity=pattern.severity,
                    line=_line_number(text, match.start()),
                    fingerprint=_fingerprint(pattern.name, secret),
                    match=match.group(0),
                    masked_excerpt=_masked_excerpt(text, match.start(), match.end(), secret=secret),
                )
            )
            occupied.append((match.start(), match.end()))

    for match in _ENTROPY_CANDIDATE.finditer(text or ""):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        context_start = max(0, match.start() - 60)
        context = text[context_start : match.start()]
        value = match.group(0)
        if _ENTROPY_ALLOWED_CONTEXT.search(context) and _looks_like_high_entropy_secret(value):
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
