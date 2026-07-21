"""Typed HTTP client for the Docmancer cloud protocol."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from uuid import UUID

import httpx

from docmancer.cloud import PROTOCOL_VERSION
from docmancer import __version__
from docmancer.cloud.crypto import b64encode, sign


class CloudError(RuntimeError):
    pass


class AuthenticationError(CloudError):
    pass


class EntitlementError(CloudError):
    pass


class ProtocolError(CloudError):
    pass


class RateLimitedError(CloudError):
    pass


class ProtocolTooOldError(ProtocolError):
    pass


class CloudClient:
    def __init__(
        self, base_url: str, *, token: str, device_id: str,
        signing_private_key: bytes | None = None, transport=None, timeout: float = 20.0,
    ) -> None:
        _server_uuid(device_id, "device_id")
        headers = {
            "X-Docmancer-Protocol": PROTOCOL_VERSION,
            "X-Docmancer-Client-Version": __version__,
            "X-Docmancer-Device-ID": device_id,
            "User-Agent": "docmancer-python",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"), transport=transport, timeout=timeout,
            headers=headers,
        )
        self.signing_private_key = signing_private_key

    def close(self) -> None:
        self.http.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        workspace = re.match(r"^/v1/workspaces/([^/]+)", path)
        if workspace:
            _server_uuid(workspace.group(1), "workspace_id")
        device = re.match(r"^/v1/workspaces/[^/]+/devices/([^/]+)", path)
        if device:
            _server_uuid(device.group(1), "device_id")
        params = kwargs.get("params")
        if isinstance(params, dict) and params.get("device_id") is not None:
            _server_uuid(str(params["device_id"]), "device_id")
        request_body = kwargs.pop("json", None)
        body_bytes = (
            json.dumps(request_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if request_body is not None else b"null"
        )
        if request_body is not None:
            kwargs["content"] = body_bytes
            headers = dict(kwargs.get("headers") or {})
            headers["Content-Type"] = "application/json"
            kwargs["headers"] = headers
        signed_path = path
        if kwargs.get("params"):
            signed_path = f"{path}?{httpx.QueryParams(kwargs['params'])}"
        if self.signing_private_key and path.startswith("/v1/workspaces/"):
            timestamp = str(int(time.time() * 1000))
            body_hash = hashlib.sha256(body_bytes).hexdigest()
            message = _device_request_message(
                timestamp=timestamp, method=method, path=signed_path,
                body_hash=body_hash,
            )
            headers = dict(kwargs.get("headers") or {})
            headers.update({
                "X-Docmancer-Device-Timestamp": timestamp,
                "X-Docmancer-Device-Body-SHA256": body_hash,
                "X-Docmancer-Device-Signature": b64encode(sign(message, self.signing_private_key)),
            })
            kwargs["headers"] = headers
        response = self.http.request(method, path, **kwargs)
        error_code = None
        error_message = None
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                error_code = error.get("code")
                error_message = error.get("message")
            elif isinstance(body, dict):
                # Retain compatibility with early alpha servers while the
                # nested protocol error envelope rolls out.
                error_code = body.get("code")
                error_message = body.get("message")
        except ValueError:
            pass
        if response.status_code == 429 or error_code == "RATE_LIMITED":
            raise RateLimitedError("cloud rate limit reached; encrypted revisions remain queued")
        if error_code == "PROTOCOL_TOO_OLD":
            raise ProtocolTooOldError("this Docmancer client is too old for cloud sync; local memory is unchanged")
        if response.status_code == 401:
            raise AuthenticationError("cloud authentication expired; run `docmancer cloud connect`")
        if response.status_code in {402, 403}:
            if error_code == "ENTITLEMENT_REQUIRED" or response.status_code == 402:
                raise EntitlementError(error_message or "cloud sync is not enabled for this account")
            raise AuthenticationError(error_message or "cloud authorization failed")
        if response.status_code >= 400 and error_message:
            raise CloudError(str(error_message))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CloudError(f"cloud request failed with HTTP {response.status_code}") from exc
        try:
            value = response.json()
        except ValueError as exc:
            raise ProtocolError("cloud returned invalid JSON") from exc
        if not isinstance(value, (dict, list)):
            raise ProtocolError("cloud response must be an object or array")
        return value

    def push(
        self,
        workspace_id: str,
        envelopes: list[dict],
        *,
        idempotency_key: str | None = None,
        cursor: int = 0,
        protocol_version: int | None = None,
    ) -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        version = protocol_version or int(envelopes[0].get("protocol_version") if envelopes else PROTOCOL_VERSION)
        if any(int(envelope.get("protocol_version") or version) != version for envelope in envelopes):
            raise ProtocolError("a cloud push batch cannot mix protocol versions")
        return self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/sync/push",
            json={
                "protocol_version": version,
                "base_cursor": cursor,
                "device_ack_cursor": cursor,
                "envelopes": envelopes,
            },
            headers=headers,
        )

    def start_device_login(self, payload: dict) -> dict:
        return self._request("POST", "/v1/auth/cli/start", json=payload)

    def poll_device_login(self, device_code: str) -> dict:
        response = self.http.post("/v1/auth/cli/exchange", json={"device_code": device_code})
        try:
            value = response.json()
        except ValueError as exc:
            raise ProtocolError("cloud returned invalid device-login JSON") from exc
        error = value.get("error") if isinstance(value, dict) else None
        code = error.get("code") if isinstance(error, dict) else value.get("code") if isinstance(value, dict) else None
        message = error.get("message") if isinstance(error, dict) else value.get("message") if isinstance(value, dict) else None
        retryable = error.get("retryable", False) if isinstance(error, dict) else value.get("retryable", False) if isinstance(value, dict) else False
        if code in {"AUTHORIZATION_PENDING", "SLOW_DOWN"}:
            return {
                "code": code,
                "message": message,
                "retryable": retryable,
            }
        if response.status_code >= 400:
            raise AuthenticationError(str(message or "device login failed"))
        if not isinstance(value, dict):
            raise ProtocolError("cloud device-login response must be an object")
        return value

    def pull(self, workspace_id: str, *, cursor: str | None = None, limit: int = 250) -> dict:
        params: dict[str, Any] = {"limit": limit, "after": int(cursor or 0)}
        value = self._request("GET", f"/v1/workspaces/{workspace_id}/sync/pull", params=params)
        envelopes = [
            row.get("envelope", row) if isinstance(row, dict) else row
            for row in list(value.get("envelopes") or [])
        ]
        return {
            **value,
            "envelopes": envelopes,
            "cursor": str(value.get("next_cursor", cursor or 0)),
        }

    def status(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/overview")

    def workspaces(self) -> dict:
        return self._request("GET", "/v1/workspaces")

    def create_workspace(self, payload: dict) -> dict:
        return self._request("POST", "/v1/workspaces", json=payload)

    def devices(self, workspace_id: str) -> dict:
        value = self._request("GET", f"/v1/workspaces/{workspace_id}/devices")
        return value if isinstance(value, dict) else {"devices": value}

    def key_wrapper(self, workspace_id: str, device_id: str, key_version: int) -> dict:
        return self._request(
            "GET",
            f"/v1/workspaces/{workspace_id}/key-wrappers",
            params={"device_id": device_id, "key_version": key_version},
        )

    def register_device(self, workspace_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/devices", json=payload)

    def approve_device(self, workspace_id: str, device_id: str, payload: dict) -> dict:
        return self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/devices/{device_id}/approve",
            json=payload,
        )

    def revoke_device(self, workspace_id: str, device_id: str) -> dict:
        return self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/devices/{device_id}/revoke",
            json={},
        )

    def entitlement(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/entitlement")

    def upload_recovery_wrapper(self, workspace_id: str, wrapper: dict) -> dict:
        return self._request("PUT", f"/v1/workspaces/{workspace_id}/recovery-wrapper", json=wrapper)

    def recovery_wrapper(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/recovery-wrapper")

    def promotion_proposals(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/promotions")

    def review_promotion(self, workspace_id: str, proposal_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/promotions/{proposal_id}/reviews", json=payload)

    def report_audit_risk(self, workspace_id: str, metadata: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/risk-reports", json=metadata)

    def create_relay_job(self, workspace_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/relay/jobs", json=payload)

    def relay_jobs(self, workspace_id: str) -> dict:
        value = self._request("GET", f"/v1/workspaces/{workspace_id}/relay/jobs")
        return {"jobs": value if isinstance(value, list) else list(value.get("jobs") or [])}

    def claim_relay_job(self, workspace_id: str) -> dict | None:
        value = self._request("POST", f"/v1/workspaces/{workspace_id}/relay/claim", json={})
        return value.get("job") if isinstance(value, dict) else None

    def complete_relay_job(self, workspace_id: str, job_id: str, payload: dict) -> dict:
        return self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/relay/jobs/{job_id}/result",
            json=payload,
        )

    def cancel_relay_job(self, workspace_id: str, job_id: str) -> dict:
        return self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/relay/jobs/{job_id}/cancel",
            json={},
        )

    def policy(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/policy")

    def acknowledge_policy(self, workspace_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/policy/acknowledge", json=payload)

    def delete_remote(self, workspace_id: str, confirmation: str) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/deletion", json={"confirmation": confirmation})


__all__ = ["AuthenticationError", "CloudClient", "CloudError", "EntitlementError", "ProtocolError", "ProtocolTooOldError", "RateLimitedError"]


def _server_uuid(value: str, field: str) -> None:
    try:
        UUID(value)
    except ValueError as exc:
        raise ProtocolError(f"{field} must be a canonical UUID") from exc


def _device_request_message(*, timestamp: str, method: str, path: str, body_hash: str) -> bytes:
    return (
        "docmancer-device-request-v1\n"
        f"{timestamp}\n{method.upper()}\n{path}\n{body_hash}"
    ).encode("utf-8")
