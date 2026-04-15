from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class TrustTier(str, Enum):
    OFFICIAL = "official"
    MAINTAINER_VERIFIED = "maintainer_verified"
    COMMUNITY = "community"


class PackProvenance(BaseModel):
    registry: str | None = None
    package: str | None = None
    docs_field: str | None = None
    registry_url: str | None = None
    observed_docs_url: str | None = None
    observed_at: datetime | None = None
    package_version: str | None = None
    submitted_by: str | None = None


class PackTrust(BaseModel):
    tier: TrustTier
    provenance: PackProvenance = Field(default_factory=PackProvenance)


class PackMaintainer(BaseModel):
    username: str | None = None
    email: str | None = None


class PackStats(BaseModel):
    total_tokens: int = 0
    raw_tokens: int = 0
    compression_ratio: float = 1.0
    sources_count: int = 0
    sections_count: int = 0


class PackMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format_version: int = 1
    sqlite_schema_version: int = 1
    docmancer_version_min: str = "0.0.0"
    docmancer_version_built: str | None = None
    name: str
    version: str
    description: str | None = None
    source_url: str
    docs_platform: str | None = None
    language: str | None = None
    trust: PackTrust
    maintainer: PackMaintainer | None = None
    stats: PackStats = Field(default_factory=PackStats)
    archive_sha256: str | None = None
    index_db_sha256: str
    tags: list[str] = Field(default_factory=list)
    crawled_at: datetime | None = None


class RegistrySearchResult(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    latest_version: str
    language: str | None = None
    trust_tier: TrustTier
    total_tokens: int = 0
    sections_count: int = 0
    pull_count: int = 0
    updated_at: datetime | str | None = None


class RegistrySearchResponse(BaseModel):
    results: list[RegistrySearchResult] = Field(default_factory=list)
    total: int = 0
    limit: int = 10
    offset: int = 0


class DownloadInfo(BaseModel):
    name: str
    version: str
    download_url: str
    archive_sha256: str
    index_db_sha256: str
    file_size_bytes: int = 0
    expires_in: int = 300


class InstalledPack(BaseModel):
    name: str
    version: str
    trust_tier: TrustTier
    source_url: str
    total_tokens: int = 0
    sections_count: int = 0
    installed_at: datetime | str
    registry_url: str
    archive_sha256: str
    index_db_sha256: str
    extracted_path: str | None = None


class PublishRequest(BaseModel):
    url: str
    name: str | None = None
    description: str | None = None
    version: str | None = None


class PublishResponse(BaseModel):
    pack_name: str
    trust_tier: TrustTier
    status: str
    track_url: str
    estimated_minutes: int | None = None


class AuthToken(BaseModel):
    token: str
    email: str | None = None
    tier: str = "free"
    expires_at: datetime | str | None = None


class DeviceCodeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int = 5


def installed_pack_from_metadata(
    metadata: PackMetadata,
    *,
    registry_url: str,
    archive_sha256: str,
    extracted_path: Path | str | None = None,
) -> InstalledPack:
    return InstalledPack(
        name=metadata.name,
        version=metadata.version,
        trust_tier=metadata.trust.tier,
        source_url=metadata.source_url,
        total_tokens=metadata.stats.total_tokens,
        sections_count=metadata.stats.sections_count,
        installed_at=datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        registry_url=registry_url,
        archive_sha256=archive_sha256,
        index_db_sha256=metadata.index_db_sha256,
        extracted_path=str(extracted_path) if extracted_path is not None else None,
    )
