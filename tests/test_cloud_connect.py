"""Unit tests for the shared device-code connect flow.

These cover the module the CLI and the local web API both call, so a regression
here breaks both front ends at once.
"""

from __future__ import annotations

import pytest

from docmancer.cloud import connect as connect_module
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.connect import (
    ConnectCancelled,
    ConnectError,
    ConnectTimeout,
    ConnectUsageError,
    await_authorization,
    enqueue_project,
    finish_connect,
    start_connect,
)
from docmancer.cloud.crypto import random_key
from docmancer.cloud.keystore import KeyStore, MemorySecretBackend
from docmancer.cloud.outbox import CloudState
from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.graph import MemoryGraphStore

ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000002"
DEVICE_ID = "00000000-0000-4000-8000-000000000003"


def _harvested_atom(text: str) -> AtomicMemoryEntry:
    content_hash = __import__("hashlib").sha256(text.encode()).hexdigest()
    return AtomicMemoryEntry(
        atom_id="existing-agent-memory",
        text=text,
        type="decision",
        harness="codex",
        kind="agent-memory",
        scope="project:test",
        scope_kind="project",
        project_id="project-test",
        project_path="/tmp/project-test",
        source_path="/tmp/project-test/MEMORY.md",
        source_title="Codex memory",
        line_start=1,
        line_end=1,
        source_hash=content_hash,
        content_hash=content_hash,
        origin="harvested",
    )


class FakeClient:
    """Stands in for CloudClient across every constructor in the flow."""

    poll_results: list[dict] = []
    workspace_rows: list[dict] = []
    created: dict = {}
    registered: dict = {}
    device_rows: list[dict] = []

    def __init__(self, *_args, **_kwargs):
        pass

    def start_device_login(self, _payload):
        return {
            "device_code": "device-code",
            "user_code": "ABCD-1234",
            "verification_uri": "https://docmancer.dev/auth/device",
            "interval": 1,
            "expires_in": 120,
        }

    def poll_device_login(self, _device_code):
        return type(self).poll_results.pop(0)

    def workspaces(self):
        return {"workspaces": list(type(self).workspace_rows)}

    def create_workspace(self, _payload):
        return dict(type(self).created)

    def register_device(self, _workspace_id, _payload):
        return dict(type(self).registered)

    def devices(self, _workspace_id):
        return {"devices": list(type(self).device_rows)}

    def close(self):
        pass


@pytest.fixture
def flow(tmp_path, monkeypatch):
    monkeypatch.setattr(connect_module, "CloudClient", FakeClient)
    FakeClient.poll_results = []
    FakeClient.workspace_rows = []
    FakeClient.created = {}
    FakeClient.registered = {}
    FakeClient.device_rows = []
    return tmp_path, KeyStore(MemorySecretBackend())


def test_start_connect_surfaces_the_user_code(flow):
    root, keys = flow
    stages: list[tuple[str, dict]] = []

    session = start_connect(
        "https://cloud.invalid", root=root, project_path=root, keys=keys,
        on_event=lambda stage, data: stages.append((stage, data)),
    )

    assert session.user_code == "ABCD-1234"
    assert session.verification_uri == "https://docmancer.dev/auth/device"
    assert stages[0][0] == "device_code"
    assert stages[0][1]["user_code"] == "ABCD-1234"


def test_start_connect_rejects_insecure_remote_cloud_url(flow):
    root, keys = flow

    with pytest.raises(ConnectUsageError, match="must use HTTPS"):
        start_connect(
            "http://api.example.test", root=root, project_path=root, keys=keys,
        )


def test_first_connect_queues_preexisting_harvested_graph_memory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=True,
        account_id=ACCOUNT_ID,
        workspace_id=WORKSPACE_ID,
        device_id=DEVICE_ID,
        base_url="https://cloud.invalid",
    )
    config.set_workspace(WORKSPACE_ID, key_version=1)
    keys = KeyStore(MemorySecretBackend())
    keys.ensure_device_keys(ACCOUNT_ID)
    keys.set_workspace_key(ACCOUNT_ID, WORKSPACE_ID, random_key(), key_version=1)
    MemoryGraphStore(tmp_path / "memory.db").rebuild(
        [_harvested_atom("Keep the release checklist in the repository.")]
    )

    enqueue_project(tmp_path, keys, project)

    pending = CloudState(config.paths.sync_state).pending()
    assert [item["kind"] for item in pending] == ["atom_revision"]
    assert "release checklist" not in __import__("json").dumps(pending)


def test_await_authorization_returns_the_token_after_pending(flow):
    root, keys = flow
    FakeClient.poll_results = [
        {"code": "AUTHORIZATION_PENDING"},
        {"code": "SLOW_DOWN"},
        {"access_token": "token", "account_id": ACCOUNT_ID},
    ]
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)
    slept: list[float] = []

    result = await_authorization(session, sleep=slept.append, monotonic=lambda: 0.0)

    assert result["access_token"] == "token"
    assert slept == [1, 3], "the SLOW_DOWN response must back off by an extra two seconds"


def test_await_authorization_times_out(flow):
    root, keys = flow
    FakeClient.poll_results = [{"code": "AUTHORIZATION_PENDING"}] * 5
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)
    clock = iter([0.0, 1000.0, 1000.0])

    with pytest.raises(ConnectTimeout):
        await_authorization(session, sleep=lambda _s: None, monotonic=lambda: next(clock))


def test_await_authorization_stops_when_cancelled(flow):
    root, keys = flow
    FakeClient.poll_results = [{"code": "AUTHORIZATION_PENDING"}]
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)

    with pytest.raises(ConnectCancelled):
        await_authorization(session, should_cancel=lambda: True, monotonic=lambda: 0.0)


def test_await_authorization_raises_on_a_terminal_error(flow):
    root, keys = flow
    FakeClient.poll_results = [{"code": "ACCESS_DENIED", "message": "the user declined"}]
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)

    with pytest.raises(ConnectError, match="the user declined"):
        await_authorization(session, monotonic=lambda: 0.0)


def test_finish_connect_creates_a_workspace_and_persists_the_session(flow):
    root, keys = flow
    FakeClient.workspace_rows = []
    FakeClient.created = {
        "workspace_id": WORKSPACE_ID, "device_id": DEVICE_ID, "current_key_version": 1,
    }
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)

    outcome = finish_connect(session, {"access_token": "token", "account_id": ACCOUNT_ID})

    assert outcome["state"] == "connected"
    assert outcome["workspace_id"] == WORKSPACE_ID
    config = CloudConfig(root)
    assert config.enabled() is True
    assert config.account()["base_url"] == "https://cloud.invalid"
    assert keys.token(ACCOUNT_ID) == b"token", "the access token must reach the keystore"
    assert keys.workspace_key(ACCOUNT_ID, WORKSPACE_ID, 1)


def test_finish_connect_registers_a_second_device_as_pending(flow):
    root, keys = flow
    FakeClient.workspace_rows = [{"workspace_id": WORKSPACE_ID, "current_key_version": 2}]
    FakeClient.device_rows = []
    FakeClient.registered = {"device_id": DEVICE_ID}
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)

    outcome = finish_connect(session, {"access_token": "token", "account_id": ACCOUNT_ID})

    assert outcome["state"] == "pending_approval"
    assert outcome["key_version"] == 2
    assert outcome["fingerprint"].startswith("docmancer-")
    assert CloudConfig(root).enabled() is False, "a pending device must not enable transfer"


def test_finish_connect_rejects_an_invalid_account_uuid(flow):
    root, keys = flow
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)

    with pytest.raises(ConnectError, match="invalid account UUID"):
        finish_connect(session, {"access_token": "token", "account_id": "not-a-uuid"})


def test_finish_connect_refuses_multiple_workspaces_without_a_choice(flow):
    root, keys = flow
    FakeClient.workspace_rows = [
        {"workspace_id": WORKSPACE_ID}, {"workspace_id": ACCOUNT_ID},
    ]
    session = start_connect("https://cloud.invalid", root=root, project_path=root, keys=keys)

    with pytest.raises(ConnectError, match="multiple workspaces"):
        finish_connect(session, {"access_token": "token", "account_id": ACCOUNT_ID})
