"""Typed HTTP client for the Docmancer cloud protocol."""
from __future__ import annotations

from typing import Any

import httpx

from docmancer.cloud import PROTOCOL_VERSION
from docmancer import __version__


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
    def __init__(self, base_url: str, *, token: str, device_id: str, transport=None, timeout: float = 20.0) -> None:
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

    def close(self) -> None:
        self.http.close()

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = self.http.request(method, path, **kwargs)
        error_code = None
        try:
            error_code = response.json().get("code") if isinstance(response.json(), dict) else None
        except ValueError:
            pass
        if response.status_code == 429 or error_code == "RATE_LIMITED":
            raise RateLimitedError("cloud rate limit reached; encrypted revisions remain queued")
        if error_code == "PROTOCOL_TOO_OLD":
            raise ProtocolTooOldError("this Docmancer client is too old for cloud sync; local memory is unchanged")
        if response.status_code == 401:
            raise AuthenticationError("cloud authentication expired; run `docmancer cloud login`")
        if response.status_code in {402, 403}:
            raise EntitlementError("cloud sync is not enabled for this account")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CloudError(f"cloud request failed with HTTP {response.status_code}") from exc
        try:
            value = response.json()
        except ValueError as exc:
            raise ProtocolError("cloud returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ProtocolError("cloud response must be an object")
        return value

    def push(self, workspace_id: str, envelopes: list[dict], *, idempotency_key: str | None = None) -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._request("POST", f"/v1/workspaces/{workspace_id}/push", json={"envelopes": envelopes}, headers=headers)

    def start_device_login(self, payload: dict) -> dict:
        return self._request("POST", "/v1/auth/device/start", json=payload)

    def poll_device_login(self, device_code: str) -> dict:
        response = self.http.post("/v1/auth/device/token", json={"device_code": device_code})
        try:
            value = response.json()
        except ValueError as exc:
            raise ProtocolError("cloud returned invalid device-login JSON") from exc
        if isinstance(value, dict) and value.get("code") in {"AUTHORIZATION_PENDING", "SLOW_DOWN"}:
            return value
        if response.status_code >= 400:
            raise AuthenticationError(str(value.get("message") if isinstance(value, dict) else "device login failed"))
        if not isinstance(value, dict):
            raise ProtocolError("cloud device-login response must be an object")
        return value

    def pull(self, workspace_id: str, *, cursor: str | None = None, limit: int = 250) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", f"/v1/workspaces/{workspace_id}/pull", params=params)

    def status(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/status")

    def devices(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/devices")

    def key_wrapper(self, workspace_id: str, device_id: str, key_version: int) -> dict:
        return self._request(
            "GET",
            f"/v1/workspaces/{workspace_id}/key-wrappers",
            params={"device_id": device_id, "key_version": key_version},
        )

    def register_device(self, workspace_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/devices", json=payload)

    def revoke_device(self, workspace_id: str, device_id: str) -> dict:
        return self._request("DELETE", f"/v1/workspaces/{workspace_id}/devices/{device_id}")

    def entitlement(self) -> dict:
        return self._request("GET", "/v1/billing/entitlement")

    def upload_recovery_wrapper(self, workspace_id: str, wrapper: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/recovery", json=wrapper)

    def recovery_wrapper(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/recovery")

    def rotate_key(self, workspace_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/key-rotations", json=payload)

    def upload_snapshot(self, workspace_id: str, snapshot: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/sync/snapshots", json=snapshot)

    def latest_snapshot(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/sync/snapshots/latest")

    def promotion_proposals(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/promotion-proposals")

    def review_promotion(self, workspace_id: str, proposal_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/promotion-proposals/{proposal_id}/reviews", json=payload)

    def report_audit_risk(self, workspace_id: str, metadata: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/audit-risk", json=metadata)

    def policy(self, workspace_id: str) -> dict:
        return self._request("GET", f"/v1/workspaces/{workspace_id}/policy")

    def acknowledge_policy(self, workspace_id: str, payload: dict) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/policy/acknowledgements", json=payload)

    def request_export(self, workspace_id: str) -> dict:
        return self._request("POST", f"/v1/workspaces/{workspace_id}/export")

    def delete_account(self, confirmation: str) -> dict:
        return self._request("DELETE", "/v1/account", json={"confirmation": confirmation})

    def delete_remote(self, workspace_id: str, confirmation: str) -> dict:
        return self._request("DELETE", f"/v1/workspaces/{workspace_id}/ciphertext", json={"confirmation": confirmation})


__all__ = ["AuthenticationError", "CloudClient", "CloudError", "EntitlementError", "ProtocolError", "ProtocolTooOldError", "RateLimitedError"]
