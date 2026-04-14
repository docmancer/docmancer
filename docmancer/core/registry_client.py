from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from docmancer.core.config import RegistryConfig
from docmancer.core.registry_errors import (
    AuthExpired,
    AuthRequired,
    PackNotFound,
    ProRequired,
    RateLimited,
    RegistryError,
    RegistryUnreachable,
    ServerError,
    VersionNotFound,
)
from docmancer.core.registry_models import (
    AuthToken,
    DeviceCodeResponse,
    DownloadInfo,
    PublishRequest,
    PublishResponse,
    RegistrySearchResponse,
)


class RegistryClient:
    def __init__(self, config: RegistryConfig, auth_token: AuthToken | None = None):
        parsed = urlparse(config.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RegistryUnreachable(config.url, "invalid registry URL")
        self.config = config
        self.auth_token = auth_token
        self.base_url = config.url.rstrip("/")
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            headers = {"accept": "application/json"}
            if self.auth_token:
                headers["authorization"] = f"Bearer {self.auth_token.token}"
            self._client = httpx.Client(timeout=self.config.timeout, follow_redirects=True, headers=headers)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        try:
            response = self.client.request(method, url, **kwargs)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, httpx.NetworkError) as exc:
            raise RegistryUnreachable(self.base_url, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise RegistryUnreachable(self.base_url, str(exc)) from exc

        if response.status_code < 400:
            if not response.content:
                return {}
            return response.json()

        payload: dict = {}
        try:
            payload = response.json()
        except ValueError:
            pass
        code = str(payload.get("code") or payload.get("error") or "")

        if response.status_code == 401:
            if code in {"auth_expired", "invalid_token", "expired_token"}:
                raise AuthExpired()
            raise AuthRequired()
        if response.status_code == 403:
            if code == "pro_required":
                raise ProRequired(str(payload.get("feature") or "this registry feature"), payload.get("free_alternative"))
            raise AuthRequired(str(payload.get("message") or "Registry access forbidden."))
        if response.status_code == 404:
            parsed_path = urlparse(path)
            if not payload and parsed_path.path.startswith("/v1-"):
                raise RegistryUnreachable(self.base_url, f"endpoint not found: {parsed_path.path}")
            query = parse_qs(parsed_path.query)
            name = str(payload.get("name") or query.get("name", [""])[0] or Path(parsed_path.path).name or "unknown")
            version = payload.get("version")
            if version:
                raise VersionNotFound(name, str(version), payload.get("available") or [])
            raise PackNotFound(name)
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise RateLimited(int(retry_after) if retry_after and retry_after.isdigit() else None)
        if response.status_code >= 500:
            raise ServerError(response.status_code)
        raise RegistryError(str(payload.get("message") or f"Registry error: HTTP {response.status_code}"), code or None)

    def search(self, query: str, limit: int = 10, offset: int = 0, trust_tier: str | None = None) -> RegistrySearchResponse:
        params = {"q": query, "limit": str(limit), "offset": str(offset)}
        if trust_tier:
            params["trust_tier"] = trust_tier
        return RegistrySearchResponse.model_validate(self._request("GET", f"/v1-packs-search?{urlencode(params)}"))

    def get_pack_detail(self, name: str, version: str | None = None) -> dict:
        params: dict[str, str] = {"name": name}
        if version:
            params["version"] = version
        return self._request("GET", f"/v1-packs-detail?{urlencode(params)}")

    def get_download_info(self, name: str, version: str | None = None) -> DownloadInfo:
        params: dict[str, str] = {"name": name}
        if version:
            params["version"] = version
        return DownloadInfo.model_validate(self._request("GET", f"/v1-packs-download?{urlencode(params)}"))

    def download_archive(self, download_url: str, dest_path: str | Path) -> Path:
        dest = Path(dest_path).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.client.stream("GET", download_url) as response:
                response.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, httpx.NetworkError) as exc:
            raise RegistryUnreachable(download_url, str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise ServerError(exc.response.status_code) from exc
            raise RegistryError(f"Download failed: HTTP {exc.response.status_code}") from exc
        return dest

    def publish(self, request: PublishRequest) -> PublishResponse:
        return PublishResponse.model_validate(self._request("POST", "/v1-packs-publish", json=request.model_dump(exclude_none=True)))

    def start_device_auth(self) -> DeviceCodeResponse:
        return DeviceCodeResponse.model_validate(self._request("POST", "/v1-auth-device-code"))

    def poll_device_token(self, device_code: str) -> AuthToken | None:
        data = self._request("POST", "/v1-auth-device-token", json={"device_code": device_code})
        if data.get("error") == "authorization_pending":
            return None
        if data.get("error") in {"expired_token", "access_denied"}:
            raise AuthExpired()
        token = data.get("access_token") or data.get("token")
        if not token:
            return None
        return AuthToken(
            token=token,
            email=data.get("email"),
            tier=data.get("tier") or "free",
            expires_at=data.get("expires_at"),
        )

    def get_user_status(self) -> dict:
        return self._request("GET", "/v1-auth-me")

    def check_connectivity(self) -> tuple[bool, str]:
        try:
            payload = self._request("GET", "/v1-health")
        except RegistryError as exc:
            return False, exc.message
        return True, str(payload.get("status") or "ok")
