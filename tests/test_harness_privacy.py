from docmancer.harness.privacy import PrivacyFilter, redact_secrets
from docmancer.harness.secrets import detect_secrets
from docmancer.harness.base import MemoryEntry


def _entry(content="x", scope="project:/x/app", path="/x/app/memory/t.md"):
    return MemoryEntry("claude-code", scope, "t", content, path)


def test_redacts_common_secrets():
    body = "sk-ABCDEF1234567890ABCDEF AKIA0123456789ABCDEF ghp_abcd1234efgh"
    out = redact_secrets(body)
    for s in ("sk-ABCDEF1234567890ABCDEF", "AKIA0123456789ABCDEF", "ghp_abcd1234efgh"):
        assert s not in out
    assert "[REDACTED]" in out


def test_redacts_keyvalue_secret():
    out = redact_secrets("api_key = supersecretvalue123")
    assert "supersecretvalue123" not in out
    assert "[REDACTED]" in out


def test_detects_secret_locations_and_masks_values():
    body = "first line\napi_key = supersecretvalue123\nnormal line\n"
    findings = detect_secrets(body)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.type == "Key-value secret"
    assert finding.line == 2
    assert "supersecretvalue123" not in finding.masked_excerpt
    assert "[SECRET]" in finding.masked_excerpt
    assert len(finding.fingerprint) == 16


def test_detects_contextual_high_entropy_token():
    body = "bearer abcdefghijklmnopqrstuvwxyzABCDEFGH1234567890\n"
    findings = detect_secrets(body)
    assert any(f.type == "High-entropy token" for f in findings)


def test_private_key_audit_excerpt_does_not_leak_multiline_secret():
    body = """before
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAtotallysecretline
anothersecretline
-----END RSA PRIVATE KEY-----
after
"""
    findings = detect_secrets(body)
    finding = next(f for f in findings if f.type == "Private key block")
    assert finding.severity == "critical"
    assert finding.line == 2
    assert "[SECRET]" in finding.masked_excerpt
    assert "BEGIN RSA PRIVATE KEY" not in finding.masked_excerpt
    assert "MIIEpAIBAAKCAQEAtotallysecretline" not in finding.masked_excerpt
    assert "anothersecretline" not in finding.masked_excerpt

    out = redact_secrets(body)
    assert "MIIEpAIBAAKCAQEAtotallysecretline" not in out
    assert "[REDACTED]" in out


def test_default_excludes_fire_on_path_not_scope():
    f = PrivacyFilter()
    # Real-world: the secret-y signal is in the PATH, not the project scope.
    assert f.allows(_entry(path="/Users/x/.ssh/notes.md")) is False
    assert f.allows(_entry(path="/Users/x/app/.env.local.md")) is False
    assert f.allows(_entry(path="/Users/x/app/memory/2026-03-28.md")) is True


def test_include_exclude_globs_on_scope_and_path():
    f = PrivacyFilter(include=["*my-app*"], exclude=["*client-secret*"])
    assert f.allows(_entry(scope="project:/x/my-app", path="/x/my-app/m.md")) is True
    assert f.allows(_entry(scope="project:/x/client-secret", path="/x/client-secret/m.md")) is False
    # include is exclusive: a scope outside the include set is dropped.
    assert f.allows(_entry(scope="project:/x/other", path="/x/other/m.md")) is False


def test_clean_redacts_entry_content():
    e = _entry(content="token: abcdef123456")
    PrivacyFilter().clean(e)
    assert "abcdef123456" not in e.content
