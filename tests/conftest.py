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
def isolate_provider_credentials(monkeypatch):
    """Never let provider tests observe or mutate the developer's OS keyring."""
    from docmancer.ai.providers.credentials import ProviderKeyStore
    from docmancer.cloud.keystore import MemorySecretBackend

    backend = MemorySecretBackend()
    original = ProviderKeyStore.__init__

    def initialize(store, selected_backend=None):
        original(store, backend=selected_backend or backend)

    monkeypatch.setattr(ProviderKeyStore, "__init__", initialize)
