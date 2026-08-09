"""Managed encrypted backup upload and download over approved devices."""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from nacl.signing import SigningKey

from docmancer import __version__
from docmancer.cloud.client import CloudClient
from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import b64decode, b64encode, decrypt, encrypt, hkdf, sign, verify
from docmancer.cloud.keystore import KeyStore
from docmancer.cloud.serialize import canonicalize
from docmancer.memory import default_memory_db

from .archive import write_local_archive_from_compressed_chunks
from .chunking import CHUNKER_ID, compress, dictionary_id, iter_content_defined_chunks
from .models import InventoryResult, SNAPSHOT_SCHEMA_VERSION
from .sanitize import prepare_artifact


CLOUD_BACKUP_FORMAT = "docmancer-cloud-backup-v1"
_COMPRESSED_MANIFEST_PREFIX = b"ZST1"


def _pack_manifest(value: dict[str, Any]) -> bytes:
    import zstandard as zstd

    return _COMPRESSED_MANIFEST_PREFIX + zstd.ZstdCompressor(level=7).compress(canonicalize(value))


def _unpack_manifest(value: bytes) -> dict[str, Any]:
    if value.startswith(_COMPRESSED_MANIFEST_PREFIX):
        import zstandard as zstd

        value = zstd.ZstdDecompressor().decompress(value[len(_COMPRESSED_MANIFEST_PREFIX):])
    result = json.loads(value)
    if not isinstance(result, dict):
        raise RuntimeError("Cloud backup manifest is invalid")
    return result


def _context() -> tuple[CloudConfig, dict, KeyStore, CloudClient, bytes, bytes, bytes]:
    root = Path(default_memory_db()).parent
    config = CloudConfig(root)
    account = config.account()
    if not config.enabled():
        raise RuntimeError("Docmancer Cloud is not connected")
    account_id = str(account.get("account_id") or "")
    workspace_id = str(account.get("workspace_id") or "")
    device_id = str(account.get("device_id") or "")
    key_version = int(account.get("key_version") or 1)
    keys = KeyStore()
    token = keys.token(account_id)
    workspace_key = keys.workspace_key(account_id, workspace_id, key_version)
    signing_private = keys.get(account_id, "device-signing-private")
    if not token or not workspace_key or not signing_private:
        raise RuntimeError("Cloud device keys are incomplete; reconnect or recover this device")
    ref_key = keys.get(account_id, f"backup-ref:{workspace_id}")
    if ref_key is None:
        ref_key = hkdf(
            workspace_key,
            salt=workspace_id.encode("utf-8"),
            info=b"docmancer-cloud-backup-reference/v1",
        )
        keys.set(account_id, f"backup-ref:{workspace_id}", ref_key)
    client = CloudClient(
        str(account.get("base_url")),
        token=token.decode("utf-8"),
        device_id=device_id,
        signing_private_key=signing_private,
        timeout=120,
    )
    return config, account, keys, client, workspace_key, signing_private, ref_key


def _aad(workspace_id: str, snapshot_id: str, device_id: str, key_version: int) -> bytes:
    return canonicalize({
        "format": CLOUD_BACKUP_FORMAT,
        "workspace_id": workspace_id,
        "snapshot_id": snapshot_id,
        "source_device_id": device_id,
        "key_version": key_version,
    })


def _ref(ref_key: bytes, digest: bytes) -> str:
    return hmac.new(ref_key, digest, hashlib.sha256).hexdigest()


def _chunk_aad(workspace_id: str, reference: str, digest: str, key_version: int) -> bytes:
    return canonicalize({
        "format": CLOUD_BACKUP_FORMAT,
        "workspace_id": workspace_id,
        "ref": reference,
        "compressed_sha256": digest,
        "key_version": key_version,
    })


def _large_removal_preview(
    client: CloudClient,
    *,
    workspace_id: str,
    device_id: str,
    key_version: int,
    workspace_key: bytes,
    signing_public: bytes,
    result: InventoryResult,
) -> dict[str, Any] | None:
    snapshots = [
        row for row in list(client.backups(workspace_id).get("snapshots") or [])
        if isinstance(row, dict) and str(row.get("source_device_id") or "") == device_id
    ]
    if not snapshots:
        return None
    previous = max(snapshots, key=lambda row: str(row.get("created_at") or ""))
    previous_count = int(previous.get("artifact_count") or 0)
    if previous_count <= 0 or len(result.artifacts) * 5 >= previous_count * 4:
        return None
    previous_version = int(previous.get("key_version") or 0)
    if previous_version != key_version:
        raise RuntimeError(
            "the previous backup uses a historical key; migrate historical keys before replacing it"
        )
    nonce = b64decode(str(previous.get("manifest_nonce") or ""))
    ciphertext = b64decode(str(previous.get("manifest_ciphertext") or ""))
    verify(
        nonce + ciphertext,
        b64decode(str(previous.get("manifest_signature") or "")),
        signing_public,
    )
    manifest = _unpack_manifest(decrypt(
        ciphertext,
        workspace_key,
        nonce=nonce,
        aad=_aad(
            workspace_id,
            str(previous.get("snapshot_id") or ""),
            device_id,
            previous_version,
        ),
    ))
    old_groups = {
        (str(item.get("project_id") or "machine-global"), str(item.get("category") or "unknown"))
        for item in manifest.get("artifacts") or []
    }
    new_groups = {
        (str(item.project_id or "machine-global"), item.category)
        for item in result.artifacts
    }
    disappeared = [f"{project}: {category}" for project, category in sorted(old_groups - new_groups)]
    return {
        "previous_artifacts": previous_count,
        "new_artifacts": len(result.artifacts),
        "disappeared": disappeared,
    }


def upload_cloud_backup(
    result: InventoryResult,
    *,
    include_attachments: bool = False,
    allow_large_removal: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    progress = on_progress or (lambda _stage, _current, _total: None)
    _config, account, keys, client, workspace_key, signing_private, ref_key = _context()
    workspace_id = str(account["workspace_id"])
    device_id = str(account["device_id"])
    key_version = int(account.get("key_version") or 1)
    signing_public = bytes(SigningKey(signing_private).verify_key)
    entitlement = client.entitlement(workspace_id)
    if not bool(entitlement.get("can_push")):
        client.close()
        raise RuntimeError("managed agent backups require an active Personal Sync entitlement")
    removal = _large_removal_preview(
        client,
        workspace_id=workspace_id,
        device_id=device_id,
        key_version=key_version,
        workspace_key=workspace_key,
        signing_public=signing_public,
        result=result,
    )
    if removal and not allow_large_removal:
        missing = ", ".join(removal["disappeared"][:20]) or "individual artifacts only"
        raise RuntimeError(
            f"backup would drop more than 20 percent of this device's artifacts "
            f"({removal['previous_artifacts']} to {removal['new_artifacts']}); "
            f"disappeared project/category groups: {missing}. "
            "Review the inventory, then rerun with --allow-large-removal if intentional."
        )
    snapshot_id = str(uuid.uuid4())
    descriptors: dict[str, dict[str, Any]] = {}
    chunk_paths: dict[str, Path] = {}
    artifacts = []
    totals = {"artifacts": 0, "transformed_artifacts": 0, "source_bytes": 0, "portable_bytes": 0, "compressed_unique_bytes": 0, "unique_chunks": 0}
    try:
        with tempfile.TemporaryDirectory(prefix="docmancer-cloud-backup-") as temp_name:
            temp_root = Path(temp_name)
            for index, spec in enumerate(result.artifacts, start=1):
                progress("prepare", index, len(result.artifacts))
                prepared = prepare_artifact(spec, temp_root, include_attachments=include_attachments)
                totals["source_bytes"] += prepared.source_size
                totals["portable_bytes"] += prepared.portable_size
                totals["transformed_artifacts"] += int(bool(prepared.transformations))
                for raw in iter_content_defined_chunks(prepared.portable_path):
                    packed = compress(raw)
                    digest_bytes = hashlib.sha256(packed).digest()
                    digest = digest_bytes.hex()
                    reference = _ref(ref_key, digest_bytes)
                    prepared.chunks.append(reference)
                    if reference in descriptors:
                        continue
                    nonce, ciphertext = encrypt(
                        packed,
                        workspace_key,
                        aad=_chunk_aad(workspace_id, reference, digest, key_version),
                    )
                    descriptor = {
                        "ref": reference,
                        "compressed_sha256": digest,
                        "plaintext_size": len(raw),
                        "compressed_size": len(packed),
                        "ciphertext_size": len(ciphertext),
                        "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
                        "nonce": b64encode(nonce),
                        "algorithm": "xchacha20poly1305-ietf",
                        "key_version": key_version,
                        "created_by_device_id": device_id,
                    }
                    descriptor["signature"] = b64encode(sign(canonicalize(descriptor), signing_private))
                    chunk_path = temp_root / f"chunk-{reference}"
                    chunk_path.write_bytes(ciphertext)
                    chunk_paths[reference] = chunk_path
                    descriptors[reference] = descriptor
                    totals["compressed_unique_bytes"] += len(packed)
                artifacts.append(prepared.manifest_dict())
            totals["artifacts"] = len(artifacts)
            totals["unique_chunks"] = len(descriptors)
            if len(descriptors) > 10_000:
                raise RuntimeError(
                    "this backup exceeds the managed snapshot limit of 10,000 chunks; "
                    "create a local .dmbak archive or narrow the selected projects"
                )
            lookup = client.lookup_backup_chunks(
                workspace_id,
                [
                    {"ref": reference, "key_version": key_version}
                    for reference in sorted(descriptors)
                ],
            )
            reused = {
                str(row.get("ref")): row
                for row in list(lookup.get("descriptors") or [])
                if isinstance(row, dict)
            }
            if reused:
                devices = list(client.devices(workspace_id).get("devices") or [])
                public_keys = {
                    str(row.get("device_id") or row.get("id")): b64decode(
                        str(row.get("sign_public_key") or row.get("sign_pubkey") or "")
                    )
                    for row in devices
                }
                for reference, stored in reused.items():
                    if reference not in descriptors or int(stored.get("key_version") or 0) != key_version:
                        raise RuntimeError("Cloud returned an unexpected backup chunk descriptor")
                    signer = public_keys.get(str(stored.get("created_by_device_id") or ""))
                    if signer is None:
                        raise RuntimeError("Cloud backup chunk signer is not an approved device")
                    signed = {key: item for key, item in stored.items() if key != "signature"}
                    verify(canonicalize(signed), b64decode(str(stored.get("signature") or "")), signer)
                    descriptors[reference] = stored
            manifest = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "format": CLOUD_BACKUP_FORMAT,
                "snapshot_id": snapshot_id,
                "workspace_id": workspace_id,
                "source_device_id": device_id,
                "key_version": key_version,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "client_version": __version__,
                "adapters": {
                    agent: {
                        "adapter_versions": sorted({item["adapter_version"] for item in artifacts if item["agent"] == agent}),
                        "vendor_versions": sorted({item["vendor_version"] for item in artifacts if item["agent"] == agent}),
                    }
                    for agent in sorted({item["agent"] for item in artifacts})
                },
                "chunker": CHUNKER_ID,
                "compression": "zstd",
                "dictionary_id": dictionary_id(),
                "artifacts": artifacts,
                "chunks": descriptors,
                "excluded": result.excluded,
                "totals": totals,
            }
            nonce, ciphertext = encrypt(
                _pack_manifest(manifest),
                workspace_key,
                aad=_aad(workspace_id, snapshot_id, device_id, key_version),
            )
            staged = client.stage_backup(workspace_id, {
                "snapshot_id": snapshot_id,
                "source_device_id": device_id,
                "key_version": key_version,
                "manifest_nonce": b64encode(nonce),
                "manifest_ciphertext": b64encode(ciphertext),
                "manifest_signature": b64encode(sign(nonce + ciphertext, signing_private)),
                "artifact_count": totals["artifacts"],
                "logical_bytes": totals["portable_bytes"],
                "compressed_bytes": totals["compressed_unique_bytes"],
                "allow_large_removal": allow_large_removal,
                "chunks": list(descriptors.values()),
            })
            missing = list(staged.get("missing_refs") or [])
            for index, reference in enumerate(missing, start=1):
                progress("upload", index, len(missing))
                client.upload_backup_chunk(workspace_id, str(staged["stage_id"]), reference, chunk_paths[reference].read_bytes())
            committed = client.commit_backup(workspace_id, str(staged["stage_id"]))
            return {"snapshot": committed.get("snapshot"), "uploaded_chunks": len(missing), "deduplicated_chunks": len(descriptors) - len(missing), **totals}
    finally:
        client.close()


def download_cloud_backup(
    destination: Path,
    *,
    passphrase: str,
    snapshot_id: str | None = None,
    source_device_id: str | None = None,
) -> dict[str, Any]:
    _config, account, keys, client, workspace_key, _signing_private, _ref_key = _context()
    workspace_id = str(account["workspace_id"])
    account_id = str(account["account_id"])
    try:
        snapshots = list(client.backups(workspace_id).get("snapshots") or [])
        if source_device_id:
            snapshots = [row for row in snapshots if row.get("source_device_id") == source_device_id]
        if snapshot_id:
            snapshots = [row for row in snapshots if row.get("snapshot_id") == snapshot_id]
        if not snapshots:
            raise RuntimeError("No matching Cloud backup snapshot was found")
        if not snapshot_id and not source_device_id:
            sources = sorted({str(row.get("source_device_id") or "") for row in snapshots})
            if len(sources) > 1:
                raise RuntimeError(
                    "Several source-device snapshots are available. Choose one with "
                    "--source-device: " + ", ".join(sources)
                )
        selected = max(snapshots, key=lambda row: str(row.get("created_at") or ""))
        key_version = int(selected["key_version"])
        if key_version != int(account.get("key_version") or 1):
            historical = keys.workspace_key(account_id, workspace_id, key_version)
            if historical is None:
                raise RuntimeError(f"Cloud backup requires unavailable workspace key version {key_version}")
            workspace_key = historical
        devices = list(client.devices(workspace_id).get("devices") or [])
        device_keys = {
            str(row.get("device_id") or row.get("id")): b64decode(
                str(row.get("sign_public_key") or row.get("sign_pubkey") or "")
            )
            for row in devices
        }
        source = next((row for row in devices if str(row.get("device_id") or row.get("id")) == selected["source_device_id"]), None)
        if not source:
            raise RuntimeError("Cloud backup source device is unavailable")
        public_key = device_keys[str(selected["source_device_id"])]
        nonce = b64decode(str(selected["manifest_nonce"]))
        ciphertext = b64decode(str(selected["manifest_ciphertext"]))
        verify(nonce + ciphertext, b64decode(str(selected["manifest_signature"])), public_key)
        plaintext = decrypt(
            ciphertext,
            workspace_key,
            nonce=nonce,
            aad=_aad(workspace_id, str(selected["snapshot_id"]), str(selected["source_device_id"]), key_version),
        )
        manifest = _unpack_manifest(plaintext)
        def fetch_compressed(reference: str) -> bytes:
            descriptor = (manifest.get("chunks") or {}).get(reference)
            if not isinstance(descriptor, dict):
                raise RuntimeError(f"Cloud backup descriptor is invalid: {reference}")
            value = client.backup_chunk(workspace_id, str(selected["snapshot_id"]), reference)
            stored = value.get("descriptor") or {}
            if stored != descriptor:
                raise RuntimeError(f"Cloud chunk descriptor mismatch: {reference}")
            signed = {key: item for key, item in descriptor.items() if key != "signature"}
            signer_key = device_keys.get(str(descriptor.get("created_by_device_id") or ""))
            if signer_key is None:
                raise RuntimeError(f"Cloud chunk signer is not an approved device: {reference}")
            verify(canonicalize(signed), b64decode(str(descriptor["signature"])), signer_key)
            encrypted = b64decode(str(value["ciphertext"]))
            if hashlib.sha256(encrypted).hexdigest() != descriptor["ciphertext_sha256"]:
                raise RuntimeError(f"Cloud chunk ciphertext verification failed: {reference}")
            packed = decrypt(
                encrypted,
                workspace_key,
                nonce=b64decode(str(descriptor["nonce"])),
                aad=_chunk_aad(workspace_id, reference, str(descriptor["compressed_sha256"]), key_version),
            )
            if hashlib.sha256(packed).hexdigest() != descriptor["compressed_sha256"]:
                raise RuntimeError(f"Cloud chunk content verification failed: {reference}")
            return packed
        return write_local_archive_from_compressed_chunks(
            manifest,
            fetch_compressed,
            destination,
            passphrase=passphrase,
        )
    finally:
        client.close()


def cloud_connected() -> bool:
    return CloudConfig(Path(default_memory_db()).parent).enabled()


def cloud_backup_entitled() -> bool:
    """Return whether this connected workspace may create managed backups."""
    if not cloud_connected():
        return False
    _config, account, _keys, client, _workspace_key, _signing_private, _ref_key = _context()
    try:
        return bool(client.entitlement(str(account["workspace_id"])).get("can_push"))
    finally:
        client.close()


def cloud_backup_status() -> dict[str, Any]:
    if not cloud_connected():
        return {"connected": False, "snapshots": [], "pending_key_migration": 0}
    root = Path(default_memory_db()).parent
    config = CloudConfig(root)
    account = config.account()
    account_id = str(account.get("account_id") or "")
    workspace_id = str(account.get("workspace_id") or "")
    current_key_version = int(account.get("key_version") or 1)
    keys = KeyStore()
    token = keys.token(account_id)
    signing_private = keys.get(account_id, "device-signing-private")
    if not token or not signing_private:
        return {
            "connected": True,
            "snapshots": [],
            "pending_key_migration": 0,
            "error": "Cloud device keys are incomplete",
        }
    client = CloudClient(
        str(account.get("base_url")),
        token=token.decode("utf-8"),
        device_id=str(account.get("device_id") or ""),
        signing_private_key=signing_private,
        timeout=30,
    )
    try:
        snapshots = list(client.backups(workspace_id).get("snapshots") or [])
    finally:
        client.close()
    return {
        "connected": True,
        "workspace_id": workspace_id,
        "current_key_version": current_key_version,
        "snapshots": snapshots,
        "pending_key_migration": sum(
            int(row.get("key_version") or 0) != current_key_version for row in snapshots
        ),
        "quota_bytes": 1_000_000_000,
        "retained_compressed_bytes": sum(int(row.get("compressed_bytes") or 0) for row in snapshots),
    }


__all__ = [
    "cloud_backup_entitled",
    "cloud_backup_status",
    "cloud_connected",
    "download_cloud_backup",
    "upload_cloud_backup",
]
