"""Local HTTP API tests for the in-app connect flow.

The browser never talks to the hosted API directly, so these tests cover the
contract the ConnectDialog relies on: a job that reports its stages, a refusal
when the device is already connected, cancellation, and a recovery key that can
be read exactly once and never appears in the pollable job record.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from starlette.testclient import TestClient

from docmancer.cloud.connect import ConnectTimeout
from docmancer.web.app import create_app


class CloudRuntime:
    """Runtime stub exposing only the cloud surface the connect routes touch."""

    project_path = Path("/tmp/project")

    def __init__(self, *, configured: bool = False, recovery: bool = False) -> None:
        self.configured = configured
        self.recovery = recovery
        self.cancelled = False
        self.paused = False
        self.disconnected = False
        self.recovery_upload_error = ""
        self.stages: list[str] = []

    async def initialize(self) -> dict:
        return {"ready": True}

    async def status(self) -> dict:
        return {"engine": "local"}

    async def counts(self) -> dict:
        return {"atoms": 0}

    async def cloud_status(self) -> dict:
        return {"configured": self.configured}

    async def cloud_connect(
        self, *, base_url, create_recovery, recovery_key=None, progress
    ) -> dict:
        progress("device_code", {"user_code": "ABCD-1234", "verification_uri": f"{base_url}/auth/device"})
        await asyncio.sleep(0)
        progress("authorized", {})
        outcome = {
            "state": "connected",
            "account_id": "account-1",
            "workspace_id": "workspace-1",
            "device_id": "device-1",
            "base_url": base_url,
        }
        if create_recovery and self.recovery:
            outcome["recovery_key"] = "super-secret-recovery-key"
        return outcome

    def cloud_cancel_connect(self) -> dict:
        self.cancelled = True
        return {"cancelled": True}

    async def cloud_pause(self) -> dict:
        self.paused = True
        return {"paused": True}

    async def cloud_disconnect(self) -> dict:
        self.disconnected = True
        return {"disconnected": True}

    async def cloud_create_recovery(self) -> tuple[str, str]:
        return "replacement-recovery-key", self.recovery_upload_error


def api_client(tmp_path: Path, runtime: CloudRuntime):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>local</html>", encoding="utf-8")
    app = create_app(
        port=48123,
        static_dir=static,
        runtime=runtime,  # type: ignore[arg-type]
        ask_history_path=tmp_path / "ask.sqlite3",
    )
    return TestClient(app, base_url="http://127.0.0.1:48123"), app


def authenticate(client: TestClient, app) -> dict:
    token = app.state.security.bootstrap_token
    assert client.get(f"/?bootstrap={token}", follow_redirects=False).status_code == 303
    csrf = client.get("/api/v1/session").json()["csrf_token"]
    return {"origin": "http://127.0.0.1:48123", "x-docmancer-csrf": csrf}


def drain(client: TestClient, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in {"completed", "failed"}:
            return job
    raise AssertionError("the job never reached a terminal state")


def test_connect_starts_a_job_and_reports_its_stages(tmp_path: Path) -> None:
    runtime = CloudRuntime()
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        started = client.post("/api/v1/cloud/connect", json={}, headers=headers)
        assert started.status_code == 202
        job = drain(client, started.json()["id"])

    assert job["state"] == "completed"
    stages = [entry["stage"] for entry in job["progress"]]
    assert stages == ["device_code", "authorized"]
    assert job["progress"][0]["data"]["user_code"] == "ABCD-1234"
    assert job["result"]["state"] == "connected"


def test_connect_uses_the_hosted_base_url_by_default(tmp_path: Path) -> None:
    runtime = CloudRuntime()
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        started = client.post("/api/v1/cloud/connect", json={}, headers=headers)
        job = drain(client, started.json()["id"])

    assert job["result"]["base_url"] == "https://api.docmancer.dev"


def test_connect_honours_an_explicit_base_url(tmp_path: Path) -> None:
    runtime = CloudRuntime()
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        started = client.post(
            "/api/v1/cloud/connect", json={"base_url": "https://staging.invalid"}, headers=headers,
        )
        job = drain(client, started.json()["id"])

    assert job["result"]["base_url"] == "https://staging.invalid"


def test_connect_refuses_when_already_configured(tmp_path: Path) -> None:
    runtime = CloudRuntime(configured=True)
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        response = client.post("/api/v1/cloud/connect", json={}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_CONNECTED"


def test_cancel_reaches_the_runtime(tmp_path: Path) -> None:
    runtime = CloudRuntime()
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        response = client.post("/api/v1/cloud/connect/cancel", json={}, headers=headers)

    assert response.json() == {"cancelled": True}
    assert runtime.cancelled is True


def test_connect_timeout_is_returned_without_an_error_traceback(
    tmp_path: Path, caplog,
) -> None:
    runtime = CloudRuntime()

    async def time_out(**_kwargs):
        raise ConnectTimeout("device login timed out")

    runtime.cloud_connect = time_out  # type: ignore[method-assign]
    client, app = api_client(tmp_path, runtime)
    with caplog.at_level(logging.INFO, logger="docmancer.web.api"), client:
        headers = authenticate(client, app)
        started = client.post("/api/v1/cloud/connect", json={}, headers=headers)
        job = drain(client, started.json()["id"])

    assert job["state"] == "failed"
    assert job["error"] == "device login timed out"
    records = [record for record in caplog.records if record.name == "docmancer.web.api"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].exc_info is None


def test_disconnect_clears_the_session(tmp_path: Path) -> None:
    runtime = CloudRuntime(configured=True)
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        response = client.post("/api/v1/cloud/disconnect", json={}, headers=headers)

    assert response.json() == {"disconnected": True}
    assert runtime.disconnected is True


def test_pause_retains_the_cloud_identity(tmp_path: Path) -> None:
    runtime = CloudRuntime(configured=True)
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        response = client.post("/api/v1/cloud/pause", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"paused": True}
    assert runtime.paused is True


def test_recovery_key_is_read_once_and_never_enters_the_job_record(tmp_path: Path) -> None:
    runtime = CloudRuntime(recovery=True)
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        started = client.post(
            "/api/v1/cloud/connect", json={"create_recovery": True}, headers=headers,
        )
        job = drain(client, started.json()["id"])
        assert "recovery_key" not in job["result"]
        assert job["result"]["recovery_key_available"] is True

        first = client.post("/api/v1/cloud/connect/recovery-key", json={}, headers=headers)
        second = client.post("/api/v1/cloud/connect/recovery-key", json={}, headers=headers)

    assert first.json()["recovery_key"] == "super-secret-recovery-key"
    assert second.status_code == 404, "the recovery key must not be readable twice"


def test_lost_recovery_key_can_be_replaced_from_the_local_api(tmp_path: Path) -> None:
    runtime = CloudRuntime()
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        response = client.post(
            "/api/v1/cloud/recovery-key/create", json={}, headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {
        "recovery_key": "replacement-recovery-key",
        "upload_error": "",
    }


def test_recovery_key_replacement_reports_a_failed_hosted_upload(tmp_path: Path) -> None:
    """A replacement key is worthless if the hosted wrapper still holds the old one."""
    runtime = CloudRuntime()
    runtime.recovery_upload_error = "Docmancer Cloud could not be reached"
    client, app = api_client(tmp_path, runtime)
    with client:
        headers = authenticate(client, app)
        response = client.post(
            "/api/v1/cloud/recovery-key/create", json={}, headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["upload_error"] == "Docmancer Cloud could not be reached"


def test_recovery_wrapper_upload_failure_is_returned_not_swallowed(tmp_path: Path) -> None:
    """The local wrapper is written either way, so the caller must learn the upload failed."""
    from docmancer.cloud.config import CloudConfig
    from docmancer.cloud.keystore import KeyStore, MemorySecretBackend
    from docmancer.runtime.backend import LocalRuntime

    config = CloudConfig(tmp_path)
    config.save_account(
        enabled=True,
        account_id="account-1",
        workspace_id="workspace-1",
        device_id="device-1",
        base_url="https://cloud.invalid",
    )
    keys = KeyStore(MemorySecretBackend())
    keys.set_workspace_key("account-1", "workspace-1", b"w" * 32)

    runtime = LocalRuntime.__new__(LocalRuntime)
    runtime._cloud_client = lambda: (_ for _ in ()).throw(RuntimeError("cloud unreachable"))

    recovery_key, upload_error = LocalRuntime._cloud_create_recovery(
        runtime, tmp_path, keys, "workspace-1",
    )

    assert recovery_key
    assert "cloud unreachable" in upload_error
    # The wrapper is still cached locally so the key is usable on this machine.
    assert (config.paths.root / "recovery-wrapper.json").is_file()
