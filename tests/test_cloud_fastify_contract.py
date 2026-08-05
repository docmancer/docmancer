from __future__ import annotations

import select
import subprocess
import time
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from docmancer.cloud.client import CloudClient
from docmancer.cloud.crypto import b64encode, box_keypair, random_key, signing_keypair, wrap_key
from docmancer.cloud.recovery import create_recovery


def test_real_python_client_bootstraps_against_real_fastify_api(tmp_path):
    cloud_root = Path(__file__).parents[2] / "website"
    server_script = cloud_root / "apps" / "api" / "scripts" / "contract-server.ts"
    tsx = cloud_root / "apps" / "api" / "node_modules" / ".bin" / "tsx"
    if not server_script.exists() or not tsx.exists():
        pytest.skip("website platform monorepo sibling checkout is unavailable")

    process = subprocess.Popen(
        [str(tsx), str(server_script)],
        cwd=cloud_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        deadline = time.monotonic() + 15
        line = ""
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            line = process.stdout.readline().strip()
            if "CONTRACT_SERVER_URL=" in line:
                break
        if "CONTRACT_SERVER_URL=" not in line:
            process.terminate()
            _, stderr = process.communicate(timeout=5)
            pytest.fail(f"Fastify contract server did not start: {line}\n{stderr}")
        base_url = line.split("CONTRACT_SERVER_URL=", 1)[1]

        temporary_device = "00000000-0000-4000-8000-000000000002"
        unauthenticated = CloudClient(base_url, token="", device_id=temporary_device)
        challenge = unauthenticated.start_device_login({})
        pending = unauthenticated.poll_device_login(challenge["device_code"])
        assert pending["code"] == "AUTHORIZATION_PENDING"
        claimed = httpx.post(
            f"{base_url}/v1/auth/cli/claim",
            json={"user_code": challenge["user_code"]},
            headers={"x-test-profile-id": "00000000-0000-4000-8000-000000000001"},
            timeout=5,
        )
        claimed.raise_for_status()
        session = unauthenticated.poll_device_login(challenge["device_code"])
        unauthenticated.close()

        signing_private, signing_public = signing_keypair()
        _box_private, box_public = box_keypair()
        workspace_key = random_key()
        authenticated = CloudClient(
            base_url,
            token=session["access_token"],
            device_id=temporary_device,
        )
        assert authenticated.workspaces() == {"workspaces": []}
        created = authenticated.create_workspace(
            {
                "kind": "personal",
                "device": {
                    "sign_pubkey": b64encode(signing_public),
                    "box_pubkey": b64encode(box_public),
                    "fingerprint": "contract-test-device",
                },
                "wrapped_key": b64encode(wrap_key(workspace_key, box_public)),
            }
        )
        UUID(created["workspace_id"])
        UUID(created["device_id"])
        assert created["entitlement"]["status"] == "incomplete"
        assert created["entitlement"]["checkout_required"] is True
        assert created["entitlement"]["can_push"] is True
        assert authenticated.status(created["workspace_id"])["devices"]["approved"] == 1
        authenticated.close()

        device_client = CloudClient(
            base_url,
            token=session["access_token"],
            device_id=created["device_id"],
            signing_private_key=signing_private,
        )
        assert device_client.pull(created["workspace_id"])["envelopes"] == []
        recovery_key, wrapper = create_recovery(
            created["workspace_id"], workspace_key, root=tmp_path,
        )
        assert recovery_key
        assert device_client.upload_recovery_wrapper(created["workspace_id"], wrapper)["state"] == "stored"
        assert device_client.recovery_wrapper(created["workspace_id"]) == wrapper
        device_client.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
