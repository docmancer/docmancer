"""One encrypted snapshot format for local archives and hosted backup."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable as CallableABC, Mapping
from typing import Any, Callable

from nacl import pwhash
from nacl.signing import SigningKey

from docmancer import __version__
from docmancer.cloud.crypto import b64decode, b64encode, decrypt, encrypt, hkdf, sign, verify
from docmancer.cloud.serialize import canonicalize

from .chunking import CHUNKER_ID, compress, decompress, dictionary_id, iter_content_defined_chunks
from .inventory import ensure_source_device_id
from .models import InventoryResult, SNAPSHOT_SCHEMA_VERSION
from .sanitize import prepare_artifact


ARCHIVE_FORMAT = "docmancer-backup-v1"
_MANIFEST_AAD = b"docmancer-backup-manifest-v1"


def _derive(passphrase: str, salt: bytes, *, opslimit: int, memlimit: int) -> dict[str, bytes]:
    if not passphrase:
        raise ValueError("backup passphrase cannot be empty")
    master = pwhash.argon2id.kdf(
        32,
        passphrase.encode("utf-8"),
        salt,
        opslimit=opslimit,
        memlimit=memlimit,
    )
    return {
        name: hkdf(master, salt=salt, info=f"docmancer-backup-v1/{name}".encode())
        for name in ("content", "manifest", "reference", "signing")
    }


def _chunk_ref(reference_key: bytes, digest: bytes) -> str:
    return hmac.new(reference_key, digest, hashlib.sha256).hexdigest()


def _chunk_aad(reference: str, digest: str) -> bytes:
    return canonicalize({"format": ARCHIVE_FORMAT, "ref": reference, "compressed_sha256": digest})


def create_archive(
    result: InventoryResult,
    destination: Path,
    *,
    passphrase: str,
    include_attachments: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    progress = on_progress or (lambda _stage, _current, _total: None)
    destination = Path(destination).expanduser().resolve()
    if destination.suffix != ".dmbak":
        destination = destination.with_suffix(destination.suffix + ".dmbak" if destination.suffix else ".dmbak")
    destination.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(pwhash.argon2id.SALTBYTES)
    opslimit = pwhash.argon2id.OPSLIMIT_MODERATE
    memlimit = pwhash.argon2id.MEMLIMIT_MODERATE
    keys = _derive(passphrase, salt, opslimit=opslimit, memlimit=memlimit)
    signing = SigningKey(keys["signing"])
    snapshot_id = str(uuid.uuid4())
    ensure_source_device_id(result.source_home or Path.home())
    source_device = result.source_device_id
    chunks: dict[str, dict[str, Any]] = {}
    artifacts = []
    transformed = 0
    source_bytes = 0
    portable_bytes = 0
    compressed_bytes = 0

    with tempfile.TemporaryDirectory(prefix="docmancer-backup-") as temp_name:
        temp_root = Path(temp_name)
        temporary_archive = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        try:
            with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for index, spec in enumerate(result.artifacts, start=1):
                    progress("prepare", index, len(result.artifacts))
                    prepared = prepare_artifact(spec, temp_root, include_attachments=include_attachments)
                    source_bytes += prepared.source_size
                    portable_bytes += prepared.portable_size
                    transformed += int(bool(prepared.transformations))
                    for raw_chunk in iter_content_defined_chunks(prepared.portable_path):
                        packed = compress(raw_chunk)
                        digest_bytes = hashlib.sha256(packed).digest()
                        digest = digest_bytes.hex()
                        reference = _chunk_ref(keys["reference"], digest_bytes)
                        prepared.chunks.append(reference)
                        if reference in chunks:
                            continue
                        aad = _chunk_aad(reference, digest)
                        nonce, ciphertext = encrypt(packed, keys["content"], aad=aad)
                        descriptor = {
                            "ref": reference,
                            "compressed_sha256": digest,
                            "plaintext_size": len(raw_chunk),
                            "compressed_size": len(packed),
                            "ciphertext_size": len(ciphertext),
                            "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
                            "nonce": b64encode(nonce),
                            "algorithm": "xchacha20poly1305-ietf",
                            "key_version": 1,
                        }
                        descriptor["signature"] = b64encode(sign(canonicalize(descriptor), bytes(signing)))
                        chunks[reference] = descriptor
                        compressed_bytes += len(packed)
                        archive.writestr(f"chunks/{reference}.bin", ciphertext)
                    artifacts.append(prepared.manifest_dict())
                manifest = {
                    "schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "format": ARCHIVE_FORMAT,
                    "snapshot_id": snapshot_id,
                    "source_device_id": source_device,
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
                    "chunks": chunks,
                    "excluded": result.excluded,
                    "totals": {
                        "artifacts": len(artifacts),
                        "transformed_artifacts": transformed,
                        "source_bytes": source_bytes,
                        "portable_bytes": portable_bytes,
                        "compressed_unique_bytes": compressed_bytes,
                        "unique_chunks": len(chunks),
                    },
                }
                manifest_bytes = canonicalize(manifest)
                manifest_nonce, manifest_ciphertext = encrypt(manifest_bytes, keys["manifest"], aad=_MANIFEST_AAD)
                manifest_signature = sign(manifest_nonce + manifest_ciphertext, bytes(signing))
                header = {
                    "format": ARCHIVE_FORMAT,
                    "schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "key_wrap": "argon2id",
                    "salt": b64encode(salt),
                    "opslimit": opslimit,
                    "memlimit": memlimit,
                    "manifest_nonce": b64encode(manifest_nonce),
                    "manifest_signature": b64encode(manifest_signature),
                    "sign_public_key": b64encode(bytes(signing.verify_key)),
                }
                archive.writestr("manifest.enc", manifest_ciphertext)
                archive.writestr("header.json", json.dumps(header, sort_keys=True, separators=(",", ":")))
            os.chmod(temporary_archive, 0o600)
            os.replace(temporary_archive, destination)
        finally:
            temporary_archive.unlink(missing_ok=True)
    return {"path": str(destination), **manifest["totals"], "snapshot_id": snapshot_id}


def _read_header(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        header = json.loads(archive.read("header.json"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid Docmancer backup header") from exc
    if not isinstance(header, dict) or header.get("format") != ARCHIVE_FORMAT:
        raise ValueError("unsupported Docmancer backup format")
    if int(header.get("schema_version") or 0) != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"unsupported Docmancer backup schema: {header.get('schema_version')}")
    return header


def open_archive(path: Path, *, passphrase: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    with zipfile.ZipFile(Path(path).expanduser().resolve(), "r") as archive:
        header = _read_header(archive)
        keys = _derive(
            passphrase,
            b64decode(str(header["salt"])),
            opslimit=int(header["opslimit"]),
            memlimit=int(header["memlimit"]),
        )
        ciphertext = archive.read("manifest.enc")
        nonce = b64decode(str(header["manifest_nonce"]))
        try:
            verify(
                nonce + ciphertext,
                b64decode(str(header["manifest_signature"])),
                b64decode(str(header["sign_public_key"])),
            )
            plaintext = decrypt(ciphertext, keys["manifest"], nonce=nonce, aad=_MANIFEST_AAD)
            manifest = json.loads(plaintext)
        except Exception as exc:
            raise ValueError("backup passphrase is wrong or the archive is corrupt") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT:
            raise ValueError("invalid encrypted backup manifest")
        if int(manifest.get("schema_version") or 0) != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported encrypted backup schema: {manifest.get('schema_version')}")
        return manifest, keys


def inspect_archive(path: Path, *, passphrase: str) -> dict[str, Any]:
    manifest, _keys = open_archive(path, passphrase=passphrase)
    return manifest


def materialize_artifact(
    archive: zipfile.ZipFile,
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    keys: dict[str, bytes],
) -> bytes:
    output = io.BytesIO()
    _write_materialized_artifact(archive, artifact, manifest, keys, output)
    return output.getvalue()


def materialize_artifact_to_path(
    archive: zipfile.ZipFile,
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    keys: dict[str, bytes],
    destination: Path,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as output:
        def write(value: bytes) -> None:
            nonlocal size
            output.write(value)
            digest.update(value)
            size += len(value)

        _write_materialized_artifact(archive, artifact, manifest, keys, write)
    if digest.hexdigest() != artifact["portable_hash"]:
        destination.unlink(missing_ok=True)
        raise ValueError(f"artifact {artifact.get('logical_path')} failed portable hash verification")
    return {"path": str(destination), "size": size, "hash": digest.hexdigest()}


def _write_materialized_artifact(
    archive: zipfile.ZipFile,
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    keys: dict[str, bytes],
    output: io.BytesIO | Callable[[bytes], None],
) -> None:
    descriptors = manifest.get("chunks") or {}
    public_key = b64decode(str(_read_header(archive)["sign_public_key"]))
    for reference in artifact.get("chunks") or []:
        descriptor = descriptors.get(reference)
        if not isinstance(descriptor, dict):
            raise ValueError(f"backup is missing descriptor for chunk {reference}")
        signed = {key: value for key, value in descriptor.items() if key != "signature"}
        verify(
            canonicalize(signed),
            b64decode(str(descriptor["signature"])),
            public_key,
        )
        ciphertext = archive.read(f"chunks/{reference}.bin")
        if hashlib.sha256(ciphertext).hexdigest() != descriptor["ciphertext_sha256"]:
            raise ValueError(f"backup chunk {reference} failed ciphertext verification")
        packed = decrypt(
            ciphertext,
            keys["content"],
            nonce=b64decode(str(descriptor["nonce"])),
            aad=_chunk_aad(reference, str(descriptor["compressed_sha256"])),
        )
        if hashlib.sha256(packed).hexdigest() != descriptor["compressed_sha256"]:
            raise ValueError(f"backup chunk {reference} failed content verification")
        value = decompress(packed, dictionary=str(manifest.get("dictionary_id") or ""))
        output.write(value) if isinstance(output, io.BytesIO) else output(value)
    if isinstance(output, io.BytesIO):
        value = output.getvalue()
        if hashlib.sha256(value).hexdigest() != artifact["portable_hash"]:
            raise ValueError(f"artifact {artifact.get('logical_path')} failed portable hash verification")


__all__ = [
    "ARCHIVE_FORMAT", "create_archive", "inspect_archive", "materialize_artifact", "materialize_artifact_to_path", "open_archive",
    "write_local_archive_from_compressed_chunks",
]


def write_local_archive_from_compressed_chunks(
    manifest: dict[str, Any],
    compressed_chunks: Mapping[str, bytes] | Callable[[str], bytes],
    destination: Path,
    *,
    passphrase: str,
) -> dict[str, Any]:
    """Rewrap a verified Cloud snapshot as the identical local archive format."""
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(pwhash.argon2id.SALTBYTES)
    opslimit = pwhash.argon2id.OPSLIMIT_MODERATE
    memlimit = pwhash.argon2id.MEMLIMIT_MODERATE
    keys = _derive(passphrase, salt, opslimit=opslimit, memlimit=memlimit)
    signing = SigningKey(keys["signing"])
    ref_map: dict[str, str] = {}
    descriptors: dict[str, dict[str, Any]] = {}
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            source_descriptors = manifest.get("chunks") or {}
            if not isinstance(source_descriptors, dict):
                raise ValueError("Cloud backup has an invalid chunk descriptor table")
            for old_ref in source_descriptors:
                packed = (
                    compressed_chunks(old_ref)
                    if isinstance(compressed_chunks, CallableABC)
                    else compressed_chunks[old_ref]
                )
                digest_bytes = hashlib.sha256(packed).digest()
                digest = digest_bytes.hex()
                reference = _chunk_ref(keys["reference"], digest_bytes)
                ref_map[old_ref] = reference
                nonce, ciphertext = encrypt(packed, keys["content"], aad=_chunk_aad(reference, digest))
                descriptor = {
                    "ref": reference,
                    "compressed_sha256": digest,
                    "plaintext_size": 0,
                    "compressed_size": len(packed),
                    "ciphertext_size": len(ciphertext),
                    "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
                    "nonce": b64encode(nonce),
                    "algorithm": "xchacha20poly1305-ietf",
                    "key_version": 1,
                }
                descriptor["signature"] = b64encode(sign(canonicalize(descriptor), bytes(signing)))
                descriptors[reference] = descriptor
                archive.writestr(f"chunks/{reference}.bin", ciphertext)
            local_manifest = json.loads(json.dumps(manifest))
            local_manifest.pop("backup_ref_key", None)
            local_manifest["format"] = ARCHIVE_FORMAT
            local_manifest["chunks"] = descriptors
            for artifact in local_manifest.get("artifacts") or []:
                artifact["chunks"] = [ref_map[reference] for reference in artifact.get("chunks") or []]
            manifest_nonce, manifest_ciphertext = encrypt(
                canonicalize(local_manifest), keys["manifest"], aad=_MANIFEST_AAD
            )
            header = {
                "format": ARCHIVE_FORMAT,
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "key_wrap": "argon2id",
                "salt": b64encode(salt),
                "opslimit": opslimit,
                "memlimit": memlimit,
                "manifest_nonce": b64encode(manifest_nonce),
                "manifest_signature": b64encode(sign(manifest_nonce + manifest_ciphertext, bytes(signing))),
                "sign_public_key": b64encode(bytes(signing.verify_key)),
            }
            archive.writestr("manifest.enc", manifest_ciphertext)
            archive.writestr("header.json", json.dumps(header, sort_keys=True, separators=(",", ":")))
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(destination), "snapshot_id": local_manifest.get("snapshot_id"), **(local_manifest.get("totals") or {})}
