"""Conflict-safe restoration of encrypted agent snapshots."""
from __future__ import annotations

import hashlib
import getpass
import json
import os
import shutil
import subprocess
import tempfile
import time
import tomllib
import uuid
import zipfile
from pathlib import Path
from typing import Any

import tomli_w

from filelock import FileLock, Timeout

from .adapters import claude_slug_for_path, project_id
from .archive import materialize_artifact_to_path, open_archive


_AGENT_MARKERS = (
    "claude",
    "claude-code",
    "@anthropic-ai/claude-code",
    "openai/codex",
    "/codex",
)
_CONFIG_NAMES = {".claude.json", "settings.json", "settings.local.json", "config.toml", ".mcp.json"}
_SUPPORTED_ADAPTER_VERSIONS = {"claude-code": {1}, "codex": {1}}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ancestors() -> set[int]:
    found = {os.getpid()}
    current = os.getpid()
    for _ in range(32):
        try:
            value = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(current)],
                check=False, capture_output=True, text=True, timeout=2,
            ).stdout.strip()
            parent = int(value)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            break
        if parent <= 1 or parent in found:
            break
        found.add(parent)
        current = parent
    return found


def running_agents() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,user=,command="],
            check=False, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    ancestors = _ancestors()
    current_user = getpass.getuser()
    found = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if parts[1] != current_user:
            continue
        command = parts[2].casefold()
        basename = Path(command.split()[0]).name if command.split() else command
        if pid not in ancestors and any(marker in command for marker in _AGENT_MARKERS):
            found.append({"pid": pid, "command": basename, "argv": command[:240]})
    return found


def _project_destination(artifact: dict[str, Any], mappings: dict[str, Path]) -> Path | None:
    source = str(artifact.get("project_root") or "")
    project_id = str(artifact.get("project_id") or "")
    for key in (project_id, source):
        if key and key in mappings:
            return mappings[key].expanduser().resolve()
    return None


def _resolved_project_mappings(
    manifest: dict[str, Any],
    home: Path,
    mappings: dict[str, Path],
) -> tuple[dict[str, Path], list[dict[str, str]]]:
    from docmancer.backup.adapters import project_id
    from docmancer.harness.paths import discover_project_roots

    resolved = {key: Path(value).expanduser().resolve() for key, value in mappings.items()}
    discovered: dict[str, list[Path]] = {}
    for root_value in discover_project_roots(home):
        root = Path(root_value).expanduser().resolve()
        discovered.setdefault(project_id(str(root)), []).append(root)
    automatic: list[dict[str, str]] = []
    for artifact in manifest.get("artifacts") or []:
        identifier = str(artifact.get("project_id") or "")
        source = str(artifact.get("project_root") or "")
        if not identifier or identifier in resolved or source in resolved:
            continue
        candidates = discovered.get(identifier) or []
        if len(candidates) == 1:
            resolved[identifier] = candidates[0]
            automatic.append({
                "project_id": identifier,
                "source": source,
                "destination": str(candidates[0]),
                "reason": "git-identity",
            })
    return resolved, automatic


def _safe_relative(value: str, *, label: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe backup {label}: {value}")
    return relative


def _destination(artifact: dict[str, Any], home: Path, mappings: dict[str, Path]) -> Path | None:
    relative = _safe_relative(
        str(artifact.get("relative_path") or ""),
        label="relative path",
    ).as_posix()
    if artifact.get("root_kind") == "project":
        root = _project_destination(artifact, mappings)
        return root / relative if root else None
    if not (relative == ".claude.json" or relative.startswith(".claude/") or relative.startswith(".codex/")):
        raise ValueError(f"refusing unknown agent-home destination: {relative}")
    project_root = str(artifact.get("project_root") or "")
    mapped = _project_destination(artifact, mappings)
    if project_root and mapped and relative.startswith(".claude/projects/"):
        parts = list(Path(relative).parts)
        if len(parts) >= 4:
            parts[2] = claude_slug_for_path(str(mapped))
            relative = Path(*parts).as_posix()
    return (home / relative).resolve()


def _rewrite_jsonl_paths(data: bytes, old_root: str, new_root: str) -> tuple[bytes, int]:
    if not old_root or old_root == new_root:
        return data, 0
    output = bytearray()
    changes = 0
    for raw in data.splitlines(keepends=True):
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            output.extend(raw)
            continue
        changed = False
        if isinstance(value, dict):
            for key in ("cwd", "projectPath", "project_root"):
                if value.get(key) == old_root:
                    value[key] = new_root
                    changed = True
            metadata = value.get("metadata")
            if isinstance(metadata, dict) and metadata.get("cwd") == old_root:
                metadata["cwd"] = new_root
                changed = True
        if changed:
            ending = b"\n" if raw.endswith((b"\n", b"\r\n")) else b""
            output.extend(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + ending)
            changes += 1
        else:
            output.extend(raw)
    return bytes(output), changes


def _rewrite_jsonl_path_file(source: Path, destination: Path, old_root: str, new_root: str) -> int:
    changes = 0
    with source.open("rb") as incoming, destination.open("wb") as outgoing:
        for raw in incoming:
            rewritten, count = _rewrite_jsonl_paths(raw, old_root, new_root)
            outgoing.write(rewritten)
            changes += count
    return changes


def _mapped_project_root(source: str, mappings: dict[str, Path]) -> Path | None:
    for key in (source, project_id(source)):
        if key in mappings:
            return mappings[key].expanduser().resolve()
    return None


def _rewrite_known_project_fields(value: Any, old_root: str, new_root: str) -> tuple[Any, int]:
    changes = 0
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, child in value.items():
            if key in {"cwd", "projectPath", "project_root"} and child == old_root:
                rewritten[key] = new_root
                changes += 1
            else:
                rewritten[key], child_changes = _rewrite_known_project_fields(child, old_root, new_root)
                changes += child_changes
        return rewritten, changes
    if isinstance(value, list):
        rewritten_list = []
        for child in value:
            rewritten_child, child_changes = _rewrite_known_project_fields(child, old_root, new_root)
            rewritten_list.append(rewritten_child)
            changes += child_changes
        return rewritten_list, changes
    return value, 0


def _rewrite_claude_project_registry(
    source: Path,
    destination: Path,
    mappings: dict[str, Path],
) -> int:
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("cannot safely rewrite Claude Code project registry") from exc
    if not isinstance(value, dict) or not isinstance(value.get("projects"), dict):
        shutil.copyfile(source, destination)
        return 0
    projects: dict[str, Any] = {}
    changes = 0
    for source_root, project_value in value["projects"].items():
        old_root = str(source_root)
        mapped = _mapped_project_root(old_root, mappings)
        new_root = str(mapped) if mapped else old_root
        rewritten, nested_changes = _rewrite_known_project_fields(project_value, old_root, new_root)
        if new_root in projects and new_root != old_root:
            raise RuntimeError(f"several source projects map to the same Claude Code registry path: {new_root}")
        projects[new_root] = rewritten
        changes += nested_changes + int(new_root != old_root)
    value["projects"] = projects
    destination.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return changes


def _merge_json(destination: bytes, incoming: bytes) -> bytes | None:
    try:
        current = json.loads(destination)
        restored = json.loads(incoming)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(current, dict) or not isinstance(restored, dict):
        return None

    def merge(left: dict, right: dict) -> dict:
        combined = dict(right)
        for key, value in left.items():
            if isinstance(value, dict) and isinstance(combined.get(key), dict):
                combined[key] = merge(value, combined[key])
            else:
                combined[key] = value
        return combined

    return (json.dumps(merge(current, restored), indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _merge_toml(destination: bytes, incoming: bytes) -> bytes | None:
    try:
        current = tomllib.loads(destination.decode("utf-8"))
        restored = tomllib.loads(incoming.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, ValueError):
        return None

    def merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        combined = dict(right)
        for key, value in left.items():
            if isinstance(value, dict) and isinstance(combined.get(key), dict):
                combined[key] = merge(value, combined[key])
            else:
                combined[key] = value
        return combined

    return tomli_w.dumps(merge(current, restored)).encode("utf-8")


def _planned_bytes(artifact: dict[str, Any], data: bytes, destination: Path, mappings: dict[str, Path]) -> tuple[bytes, list[dict[str, Any]]]:
    transforms = []
    old_root = str(artifact.get("project_root") or "")
    mapped = _project_destination(artifact, mappings)
    if artifact.get("content_kind") == "jsonl" and old_root and mapped:
        data, count = _rewrite_jsonl_paths(data, old_root, str(mapped))
        if count:
            transforms.append({"kind": "structured-path-rewrite", "records": count})
    if destination.is_file() and destination.name in _CONFIG_NAMES:
        merged = (
            _merge_json(destination.read_bytes(), data)
            if destination.suffix == ".json"
            else _merge_toml(destination.read_bytes(), data)
            if destination.suffix == ".toml"
            else None
        )
        if merged is not None:
            data = merged
            transforms.append({"kind": "destination-precedence-config-merge"})
    return data, transforms


def _planned_file(
    artifact: dict[str, Any],
    source: Path,
    destination: Path,
    mappings: dict[str, Path],
    temporary_root: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    transforms: list[dict[str, Any]] = []
    planned = source
    old_root = str(artifact.get("project_root") or "")
    mapped = _project_destination(artifact, mappings)
    if artifact.get("content_kind") == "jsonl" and old_root and mapped:
        rewritten = temporary_root / f"{source.name}.rewritten"
        count = _rewrite_jsonl_path_file(source, rewritten, old_root, str(mapped))
        planned = rewritten
        if count:
            transforms.append({"kind": "structured-path-rewrite", "records": count})
    if artifact.get("relative_path") == ".claude.json" and mappings:
        rewritten = temporary_root / f"{source.name}.registry-rewritten"
        count = _rewrite_claude_project_registry(planned, rewritten, mappings)
        planned = rewritten
        if count:
            transforms.append({"kind": "structured-project-registry-rewrite", "fields": count})
    if destination.is_file() and destination.name in _CONFIG_NAMES:
        data = planned.read_bytes()
        merged = (
            _merge_json(destination.read_bytes(), data)
            if destination.suffix == ".json"
            else _merge_toml(destination.read_bytes(), data)
            if destination.suffix == ".toml"
            else None
        )
        if merged is not None:
            merged_path = temporary_root / f"{source.name}.merged"
            merged_path.write_bytes(merged)
            planned = merged_path
            transforms.append({"kind": "destination-precedence-config-merge"})
    return planned, transforms


def plan_restore(
    path: Path,
    *,
    passphrase: str,
    home: Path | None = None,
    mappings: dict[str, Path] | None = None,
) -> dict[str, Any]:
    home = Path(home or Path.home()).expanduser().resolve()
    mappings = dict(mappings or {})
    manifest, keys = open_archive(path, passphrase=passphrase)
    for artifact in manifest.get("artifacts") or []:
        agent = str(artifact.get("agent") or "")
        version = int(artifact.get("adapter_version") or 0)
        if version not in _SUPPORTED_ADAPTER_VERSIONS.get(agent, set()):
            raise ValueError(f"unsupported {agent or 'unknown'} backup adapter version: {version}")
    mappings, automatic_mappings = _resolved_project_mappings(manifest, home, mappings)
    actions = []
    recent = []
    with tempfile.TemporaryDirectory(prefix="docmancer-restore-plan-") as temp_name, zipfile.ZipFile(Path(path).expanduser().resolve(), "r") as archive:
        temporary_root = Path(temp_name)
        for index, artifact in enumerate(manifest.get("artifacts") or []):
            destination = _destination(artifact, home, mappings)
            if destination is None:
                actions.append({"state": "unmapped", "logical_path": artifact.get("logical_path"), "project_root": artifact.get("project_root"), "category": artifact.get("category")})
                continue
            if destination != home and home not in destination.parents and not any(root == destination or root in destination.parents for root in mappings.values()):
                raise ValueError(f"destination escapes approved roots: {destination}")
            if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents if parent != parent.parent):
                raise ValueError(f"refusing symlink destination: {destination}")
            source = temporary_root / f"artifact-{index}"
            materialize_artifact_to_path(archive, artifact, manifest, keys, source)
            planned, transforms = _planned_file(artifact, source, destination, mappings, temporary_root)
            planned_hash = _sha_path(planned)
            planned_size = planned.stat().st_size
            state = "create"
            before = None
            if destination.is_file():
                before = {"size": destination.stat().st_size, "hash": _sha_path(destination), "mtime_ns": destination.stat().st_mtime_ns}
                state = "identical" if before["size"] == planned_size and before["hash"] == planned_hash else "merge" if any(row["kind"].endswith("config-merge") for row in transforms) else "conflict"
                if state != "identical" and artifact.get("category") == "session" and time.time() - destination.stat().st_mtime < 2:
                    recent.append(str(destination))
            actions.append({
                "state": state,
                "category": artifact.get("category"),
                "logical_path": artifact.get("logical_path"),
                "destination": str(destination),
                "planned_hash": planned_hash,
                "planned_size": planned_size,
                "before": before,
                "transformations": transforms,
            })
    return {
        "snapshot_id": manifest.get("snapshot_id"),
        "source_device_id": manifest.get("source_device_id"),
        "actions": actions,
        "counts": {state: sum(1 for row in actions if row["state"] == state) for state in ("create", "identical", "merge", "conflict", "unmapped")},
        "recently_modified": recent,
        "project_mappings": automatic_mappings,
        "resolved_mappings": {key: str(value) for key, value in mappings.items()},
        "reconfiguration": sorted({
            f"{artifact.get('logical_path')}: {item}"
            for artifact in manifest.get("artifacts") or []
            for transform in artifact.get("transformations") or []
            for item in transform.get("reconfiguration") or []
        }),
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.restore-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if _sha(path.read_bytes()) != _sha(data):
            raise RuntimeError(f"post-write hash verification failed: {path}")
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_copy(path: Path, source: Path, *, expected_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.restore-{uuid.uuid4().hex}.tmp"
    try:
        with source.open("rb") as incoming, temporary.open("wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        os.chmod(temporary, 0o600)
        if _sha_path(temporary) != expected_hash:
            raise RuntimeError(f"staged restore hash verification failed: {path}")
        os.replace(temporary, path)
        if _sha_path(path) != expected_hash:
            raise RuntimeError(f"post-write hash verification failed: {path}")
    finally:
        temporary.unlink(missing_ok=True)


def restore_archive(
    path: Path,
    *,
    passphrase: str,
    home: Path | None = None,
    mappings: dict[str, Path] | None = None,
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    home = Path(home or Path.home()).expanduser().resolve()
    mappings = dict(mappings or {})
    active = running_agents()
    if active:
        names = ", ".join(f"{row['command']} ({row['pid']})" for row in active)
        raise RuntimeError(f"close running coding agents before restore: {names}")
    plan = preview or plan_restore(path, passphrase=passphrase, home=home, mappings=mappings)
    mappings = {
        key: Path(value).expanduser().resolve()
        for key, value in (plan.get("resolved_mappings") or {}).items()
    }
    if plan["recently_modified"]:
        raise RuntimeError("refusing to restore recently modified session files: " + ", ".join(plan["recently_modified"][:5]))
    if plan["counts"]["unmapped"]:
        raise RuntimeError("restore has unmapped projects; pass explicit project mappings")
    lock_path = home / ".docmancer" / "locks" / "agent-restore.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock = FileLock(str(lock_path), timeout=0)
        lock.acquire()
    except Timeout as exc:
        raise RuntimeError("another Docmancer restore is already running") from exc
    manifest, keys = open_archive(path, passphrase=passphrase)
    rollback = home / ".docmancer" / "restore-rollbacks" / str(manifest.get("snapshot_id"))
    quarantine = home / ".docmancer" / "restore-conflicts" / str(manifest.get("snapshot_id"))
    written = skipped = conflicts = 0
    applied: list[tuple[Path, Path | None]] = []
    rollback_entries: list[dict[str, str | None]] = []
    quarantine_written: list[Path] = []
    consolidation_sessions: list[str] = []
    action_by_logical = {str(row["logical_path"]): row for row in plan["actions"]}
    try:
        with tempfile.TemporaryDirectory(prefix="docmancer-restore-apply-") as temp_name, zipfile.ZipFile(Path(path).expanduser().resolve(), "r") as archive:
            temporary_root = Path(temp_name)
            for index, artifact in enumerate(manifest.get("artifacts") or []):
                logical = str(artifact.get("logical_path"))
                action = action_by_logical[logical]
                destination = Path(action["destination"])
                if action["state"] == "identical":
                    skipped += 1
                    if artifact.get("category") == "session":
                        consolidation_sessions.append(str(destination))
                    continue
                source = temporary_root / f"artifact-{index}"
                materialize_artifact_to_path(archive, artifact, manifest, keys, source)
                planned, _transforms = _planned_file(artifact, source, destination, mappings, temporary_root)
                planned_hash = _sha_path(planned)
                if planned_hash != action["planned_hash"]:
                    raise RuntimeError(f"restore bytes changed after preview: {destination}")
                before = action.get("before")
                if before:
                    if not destination.is_file():
                        raise RuntimeError(f"destination changed after preview: {destination}")
                    stat = destination.stat()
                    if stat.st_mtime_ns != before["mtime_ns"] or _sha_path(destination) != before["hash"]:
                        raise RuntimeError(f"destination changed after preview: {destination}")
                elif destination.exists():
                    raise RuntimeError(f"destination appeared after preview: {destination}")
                if action["state"] == "conflict":
                    target = quarantine / _safe_relative(logical, label="logical path")
                    _atomic_copy(target, planned, expected_hash=planned_hash)
                    quarantine_written.append(target)
                    conflicts += 1
                    continue
                if destination.exists():
                    rollback_target = rollback / destination.relative_to(home) if home in destination.parents else rollback / "projects" / hashlib.sha256(str(destination).encode()).hexdigest() / destination.name
                    rollback_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, rollback_target)
                    applied.append((destination, rollback_target))
                    rollback_entries.append({
                        "destination": str(destination),
                        "backup": str(rollback_target.relative_to(rollback)),
                    })
                else:
                    applied.append((destination, None))
                    rollback_entries.append({"destination": str(destination), "backup": None})
                _atomic_copy(destination, planned, expected_hash=planned_hash)
                written += 1
                if artifact.get("category") == "session":
                    consolidation_sessions.append(str(destination))
        if rollback_entries:
            _atomic_write(
                rollback / "rollback-manifest.json",
                (json.dumps({"snapshot_id": manifest.get("snapshot_id"), "entries": rollback_entries}, indent=2) + "\n").encode("utf-8"),
            )
    except Exception:
        for destination, rollback_target in reversed(applied):
            if rollback_target is None:
                destination.unlink(missing_ok=True)
            elif rollback_target.is_file():
                _atomic_write(destination, rollback_target.read_bytes())
        for target in quarantine_written:
            target.unlink(missing_ok=True)
        raise
    finally:
        lock.release()
    return {
        "snapshot_id": manifest.get("snapshot_id"),
        "written": written,
        "identical": skipped,
        "conflicts": conflicts,
        "status": "partial" if conflicts else "structurally-valid",
        "rollback": str(rollback) if rollback.exists() else None,
        "quarantine": str(quarantine) if conflicts else None,
        "reconfiguration": plan.get("reconfiguration") or [],
        "project_mappings": plan.get("project_mappings") or [],
        "_restored_session_paths": consolidation_sessions,
    }


def rollback_restore(snapshot_id: str, *, home: Path | None = None) -> dict[str, Any]:
    home = Path(home or Path.home()).expanduser().resolve()
    if not snapshot_id or "/" in snapshot_id or ".." in snapshot_id:
        raise ValueError("invalid restore snapshot id")
    root = home / ".docmancer" / "restore-rollbacks" / snapshot_id
    if not root.is_dir():
        raise ValueError(f"restore rollback not found: {snapshot_id}")
    manifest_path = root / "rollback-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("this rollback predates executable rollback metadata")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored = removed = 0
    for entry in reversed(value.get("entries") or []):
        destination = Path(str(entry.get("destination") or "")).expanduser().resolve()
        if not destination.is_absolute():
            raise ValueError("rollback destination is invalid")
        backup = entry.get("backup")
        if backup is None:
            destination.unlink(missing_ok=True)
            removed += 1
            continue
        source = (root / _safe_relative(str(backup), label="rollback path")).resolve()
        if root != source and root not in source.parents:
            raise ValueError("rollback source escapes rollback root")
        if not source.is_file():
            raise ValueError(f"rollback source is missing: {source}")
        _atomic_write(destination, source.read_bytes())
        restored += 1
    return {
        "snapshot_id": snapshot_id,
        "restored": restored,
        "removed": removed,
        "rollback": str(root),
    }


__all__ = ["plan_restore", "restore_archive", "rollback_restore", "running_agents"]
