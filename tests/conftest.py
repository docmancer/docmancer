"""Test-wide defaults.

Vector retrieval is on by default for user installs, but the test suite
should never spawn the managed Qdrant binary or download FastEmbed models
into the developer's real ``~/.docmancer`` while running locally. Tests
that exercise the vector path opt in explicitly.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DOCMANCER_AUTO_VECTORS", "0")


@pytest.fixture(autouse=True)
def isolate_docmancer_home(tmp_path, monkeypatch):
    """Keep every test away from the developer's real Docmancer state.

    Memory tests historically overrode the harness and database paths but
    occasionally left ``DOCMANCER_HOME`` pointing at the real laptop-wide
    canonical tree. A test that called Ask could therefore reconcile pytest
    fixture content into the user's actual canonical memory. Set every
    state-bearing root before the test constructs any runtime object.
    """
    sandbox = tmp_path / "docmancer-test-home"
    harness = tmp_path / "docmancer-test-harness"
    monkeypatch.setenv("DOCMANCER_TESTING", "1")
    monkeypatch.setenv("DOCMANCER_HOME", str(sandbox))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(sandbox / "memory.db"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(harness))
    monkeypatch.setenv("DOCMANCER_INDEX_DB_PATH", str(sandbox / "docmancer.db"))
    monkeypatch.setenv("DOCMANCER_EMBEDDINGS_CACHE", str(sandbox / "embeddings-cache"))
    yield


@pytest.fixture(autouse=True)
def isolate_provider_credentials(monkeypatch):
    """Never let provider tests observe or mutate the developer's OS keyring."""
    from docmancer.ai.providers.credentials import ProviderKeyStore
    from docmancer.cloud.keystore import MemorySecretBackend

    backend = MemorySecretBackend()
    original = ProviderKeyStore.__init__

    def initialize(store, selected_backend=None):
        original(store, backend=selected_backend or backend)

    monkeypatch.setattr(ProviderKeyStore, "__init__", initialize)
