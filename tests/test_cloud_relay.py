from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from docmancer.cloud.crypto import b64encode, encrypt, sign, signing_keypair
from docmancer.cloud.relay import (
    CLI_ONLY_ACTIONS,
    RELAY_ACTIONS,
    _associated_data,
    _signature_input,
    decrypt_request,
    dispatch,
    process_one,
    relay_header,
    serve,
)
from docmancer.cloud.serialize import canonicalize


class FakeBackend:
    async def initialize(self):
        return None

    async def query_memory(self, **arguments):
        return [{"text": arguments["text"], "score": 0.9}]

    async def clear_memory(self):
        return ["memory.db"]


def relay_job(workspace_key: bytes, signing_private: bytes) -> dict:
    job = {
        "id": "00000000-0000-4000-8000-000000000020",
        "request_id": "00000000-0000-4000-8000-000000000010",
        "workspace_id": "00000000-0000-4000-8000-000000000001",
        "source_device_id": "00000000-0000-4000-8000-000000000002",
        "target_device_id": "00000000-0000-4000-8000-000000000003",
        "key_version": 1,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        "state": "claimed",
    }
    header = relay_header(job)
    nonce, ciphertext = encrypt(
        canonicalize({"action": "memory.query", "arguments": {"text": "private question"}}),
        workspace_key,
        aad=_associated_data(header, "request"),
    )
    job.update(
        request_nonce=b64encode(nonce),
        request_ciphertext=b64encode(ciphertext),
        request_signature=b64encode(
            sign(_signature_input(header, "request", nonce, ciphertext), signing_private)
        ),
    )
    return job


def test_relay_request_is_signed_and_encrypted():
    workspace_key = bytes(range(32))
    signing_private, signing_public = signing_keypair()
    job = relay_job(workspace_key, signing_private)
    assert "private question" not in job["request_ciphertext"]
    assert decrypt_request(job, workspace_key, signing_public) == {
        "action": "memory.query",
        "arguments": {"text": "private question"},
    }


def test_relay_signature_normalizes_postgres_utc_timestamp():
    workspace_key = bytes(range(32))
    signing_private, signing_public = signing_keypair()
    job = relay_job(workspace_key, signing_private)
    job["expires_at"] = str(job["expires_at"]).replace("+00:00", "Z")

    assert decrypt_request(job, workspace_key, signing_public) == {
        "action": "memory.query",
        "arguments": {"text": "private question"},
    }


def test_dispatch_uses_an_explicit_allowlist_and_local_write_gate():
    backend = FakeBackend()
    result = asyncio.run(
        dispatch(backend, "memory.query", {"text": "decision"}, allow_writes=False)
    )
    assert result == [{"text": "decision", "score": 0.9}]
    with pytest.raises(PermissionError, match="--allow-writes"):
        asyncio.run(
            dispatch(
                backend,
                "context.add",
                {"text": "decision"},
                allow_writes=False,
            )
        )
    with pytest.raises(ValueError, match="allowlisted"):
        asyncio.run(dispatch(backend, "shell.exec", {"command": "whoami"}, allow_writes=True))
    with pytest.raises(PermissionError, match="docmancer memory forget"):
        asyncio.run(dispatch(backend, "memory.forget", {"identifier": "memory-id"}, allow_writes=True))
    assert "shell.exec" not in RELAY_ACTIONS
    assert "memory.forget" in CLI_ONLY_ACTIONS
    assert "memory.forget" not in RELAY_ACTIONS


def test_process_one_returns_only_an_encrypted_result_to_the_server():
    workspace_key = bytes(range(32))
    browser_private, browser_public = signing_keypair()
    device_private, _device_public = signing_keypair()
    job = relay_job(workspace_key, browser_private)

    class FakeClient:
        def __init__(self):
            self.completed = None

        def claim_relay_job(self, _workspace_id):
            return job

        def complete_relay_job(self, _workspace_id, _job_id, payload):
            self.completed = payload
            return {"id": job["id"], **payload}

    client = FakeClient()
    asyncio.run(
        process_one(
            client,
            FakeBackend(),
            workspace_id=job["workspace_id"],
            device_id=job["target_device_id"],
            workspace_key=workspace_key,
            signing_private=device_private,
            device_public_keys={job["source_device_id"]: browser_public},
            allow_writes=False,
        )
    )
    assert client.completed["state"] == "completed"
    assert "private question" not in client.completed["response_ciphertext"]
    assert set(client.completed) == {
        "state",
        "response_nonce",
        "response_ciphertext",
        "response_signature",
    }


def test_serve_reports_transport_failure_without_stopping_the_relay_loop():
    class FailingClient:
        def claim_relay_job(self, _workspace_id):
            raise RuntimeError("relay job was cancelled")

    errors = []
    asyncio.run(
        serve(
            FailingClient(),
            FakeBackend(),
            workspace_id="workspace",
            device_id="device",
            workspace_key=bytes(range(32)),
            signing_private=bytes(range(32)),
            device_public_keys={},
            allow_writes=False,
            once=True,
            on_error=errors.append,
        )
    )
    assert [str(error) for error in errors] == ["relay job was cancelled"]


def test_browser_and_local_relay_action_registries_match():
    browser_registry = (
        Path(__file__).parents[2]
        / "docmancer-cloud"
        / "apps"
        / "web"
        / "lib"
        / "relay-actions.ts"
    )
    if not browser_registry.exists():
        pytest.skip("docmancer-cloud sibling checkout is unavailable")
    browser_actions = set(
        re.findall(r'action\(\s*"([^"]+)"', browser_registry.read_text(encoding="utf-8"))
    )
    assert browser_actions == set(RELAY_ACTIONS)
