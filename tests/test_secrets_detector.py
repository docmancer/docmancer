"""Precision/recall regression tests for the secret detector.

These pin down two failure modes found by manually auditing real memory
output: the entropy heuristic flagging prose that merely mentions a
secret-sounding word near an unrelated long identifier (false positives), and
several common real-world leak shapes having no dedicated pattern at all
(false negatives).
"""
from docmancer.harness.secrets import detect_secrets


def _types(text: str) -> list[str]:
    return [f.type for f in detect_secrets(text)]


# -- False positives the entropy heuristic used to produce --------------------


def test_keyword_list_does_not_flag_unrelated_identifier():
    """A prose list of field names must not make a later ID a 'secret'.

    Real example: a "keywords: ..., apiKey, userSecret, ..., feed ID, <long
    hyphenated feed identifier>" line used to flag the feed identifier purely
    because "apiKey"/"userSecret" appeared somewhere in the preceding 60
    characters, even though there is no assignment relationship between them.
    """
    text = (
        "keywords: Chainlink Data Streams, api.dataengine.chain.link, "
        "@chainlink/data-streams-sdk, API key, userSecret, HMAC, REST auth, "
        "WebSocket auth, feed ID, ETH/USD-RefPrice-DF-Testnet-Mainnet-Chainlink-Streams-003"
    )
    assert detect_secrets(text) == []


def test_rollout_filename_and_session_id_not_flagged():
    """Session ids and .md/.jsonl filenames are identifiers, not secrets."""
    text = (
        "See rollout_summaries/2026-06-23T10-36-11-019ef3d6-57ab-cdef.md "
        "(cwd=/Users/x/project, rollout_path=/Users/x/.codex/sessions/2026/06/23/"
        "rollout-2026-06-23T10-36-11-019ef3d6-57ab.jsonl)"
    )
    assert detect_secrets(text) == []


def test_markdown_filename_reference_not_flagged():
    text = "deployment: See STYLE_GUIDE_DOCKER_BUILD_REFERENCE.md for the exact Docker build command."
    assert detect_secrets(text) == []


def test_explicit_assignment_next_to_keyword_is_still_caught():
    """The adjacency fix must not lose real key=value assignments."""
    text = "the shell-test BONZO_AGENT_API_KEY=definitely-not-a-real-key-invalid still passed"
    findings = detect_secrets(text)
    assert any(f.type == "Key-value secret" for f in findings)


def test_bearer_context_still_detected():
    """Pre-existing behavior: a keyword immediately before a token still fires."""
    text = "bearer abcdefghijklmnopqrstuvwxyzABCDEFGH1234567890"
    assert "High-entropy token" in _types(text)


# -- Coverage gaps (false negatives) now filled --------------------------------


def test_anthropic_key_gets_dedicated_high_severity_label():
    """Anthropic's sk-ant- keys used to fall through to the generic medium
    'Key-value secret' type because their hyphens break the OpenAI regex's
    assumption of a contiguous alnum run after 'sk-'."""
    text = "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMN"
    findings = detect_secrets(text)
    assert len(findings) == 1
    assert findings[0].type == "Anthropic API key"
    assert findings[0].severity == "high"


def test_stripe_secret_key_detected():
    text = "STRIPE_KEY=" + "sk_" + "live_51H8xyzABCDEfghijKLMNOpqrstuv1234567890"
    findings = detect_secrets(text)
    assert any(f.type == "Stripe API key" and f.severity == "high" for f in findings)


def test_google_api_key_detected():
    text = "GOOGLE_MAPS_KEY=AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY"
    findings = detect_secrets(text)
    assert any(f.type == "Google API key" for f in findings)


def test_github_fine_grained_pat_detected():
    text = "GITHUB_TOKEN=github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789"
    findings = detect_secrets(text)
    assert any(f.type == "GitHub token" for f in findings)


def test_npm_token_detected():
    text = "registry_authToken=npm_abcdefghijklmnopqrstuvwxyz0123456789"
    findings = detect_secrets(text)
    assert any(f.type == "npm token" for f in findings)


def test_bare_jwt_detected_without_keyword_context():
    """JWTs are recognizable by their eyJ... structure alone; no nearby
    'token'/'bearer' keyword should be required."""
    text = "cfg.cache = eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ_fakefakefakefake"
    findings = detect_secrets(text)
    assert any(f.type == "JWT / bearer token" for f in findings)


def test_database_connection_string_with_real_credentials_detected():
    text = "DATABASE_URL=postgres://appuser:Tr0ub4dor3xyzsecretvalue@dbhost.com:5432/prod"
    findings = detect_secrets(text)
    assert any(f.type == "Database connection string" and f.severity == "high" for f in findings)


def test_database_connection_string_placeholder_not_flagged():
    """Docs commonly show `user:password@localhost` as a documented placeholder
    (this project's own CLAUDE.md instructs writing exactly this shape in
    .env.example files); that must not be reported as a leaked credential."""
    text = "DATABASE_URL=postgresql://user:password@localhost:5432/dbname"
    assert detect_secrets(text) == []


# -- No double-counting a single secret under two types ------------------------


def test_openai_key_reported_once_not_twice():
    """Previously a key like OPENAI_API_KEY=sk-... could be reported both as
    the generic 'Key-value secret' (medium) and the dedicated 'OpenAI-style
    API key' (high), inflating the occurrence count for one real secret."""
    text = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEF"
    findings = detect_secrets(text)
    assert len(findings) == 1
    assert findings[0].type == "OpenAI-style API key"
    assert findings[0].severity == "high"
