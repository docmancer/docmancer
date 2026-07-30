from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.crypto import random_key, signing_keypair
from docmancer.cloud.envelope import build_envelope, open_envelope
from docmancer.cloud.outbox import CloudState
from docmancer.cloud.project_identity import derived_project_id, normalize_remote
from docmancer.cloud.serialize import build_tree_payload, validate_tree_payload
from docmancer.cloud.team_files import generate_team_file, transition_team_file
from docmancer.cloud.tree_sync import apply_tree_payload, payload_for_file, queue_tree_changes
from docmancer.memory.tree.store import TreeStore


def test_remote_identity_is_path_free_and_checkout_stable():
    assert normalize_remote("git@github.com:Docmancer/Docmancer.git") == "github.com/docmancer/docmancer"
    assert normalize_remote("https://github.com/docmancer/docmancer.git") == "github.com/docmancer/docmancer"
    assert derived_project_id("github.com/docmancer/docmancer") == derived_project_id(
        "github.com/docmancer/docmancer"
    )


def test_project_identity_platform_fixture_keeps_device_paths_local():
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "cloud"
            / "project-identity-platforms.json"
        ).read_text(encoding="utf-8")
    )
    normalized = {
        normalize_remote(remote) for remote in fixture["remote_variants"]
    }
    assert normalized == {fixture["normalized_remote"]}
    assert derived_project_id(fixture["normalized_remote"]) == fixture["project_id"]
    payload = build_tree_payload(
        object_kind="tree_file",
        file_id="abc",
        project_id=fixture["project_id"],
        relative_path="decisions/release.md",
        markdown="# Release\n",
        metadata={"local_paths": fixture["device_local_paths"]},
        updated_at="2026-07-23T10:00:00+00:00",
    )
    encoded = json.dumps(payload)
    assert all(path not in encoded for path in fixture["device_local_paths"].values())


def test_tree_payload_is_allowlisted_portable_and_content_addressed():
    payload = build_tree_payload(
        object_kind="tree_file",
        file_id="abc",
        project_id="prj_1234567890abcdef",
        relative_path="decisions/release.md",
        markdown="# Release\n",
        metadata={"title": "Release", "absolute_path": "/private/project"},
        updated_at="2026-07-23T10:00:00+00:00",
    )
    assert payload["metadata"] == {"title": "Release"}
    assert validate_tree_payload(payload) == payload
    with pytest.raises(ValueError, match="relative and portable"):
        build_tree_payload(
            object_kind="tree_file",
            file_id="abc",
            project_id="prj_1234567890abcdef",
            relative_path="../outside.md",
            markdown="unsafe",
            metadata={},
            updated_at="2026-07-23T10:00:00+00:00",
        )


def test_protocol_v3_tree_envelope_round_trip():
    payload = build_tree_payload(
        object_kind="tree_file",
        file_id="abc",
        project_id="prj_1234567890abcdef",
        relative_path="release.md",
        markdown="# Release\n",
        metadata={"title": "Release"},
        updated_at="2026-07-23T10:00:00+00:00",
    )
    private, public = signing_keypair()
    workspace_key = random_key()
    envelope = build_envelope(
        payload,
        workspace_id="00000000-0000-4000-8000-000000000001",
        device_id="00000000-0000-4000-8000-000000000002",
        workspace_key=workspace_key,
        signing_private_key=private,
    )
    assert envelope["protocol_version"] == 3
    assert envelope["kind"] == "tree_file_revision"
    assert open_envelope(envelope, workspace_key=workspace_key, signing_public_key=public) == payload


def test_tree_revision_applies_by_stable_project_mapping(tmp_path: Path):
    source_project = tmp_path / "source"
    target_project = tmp_path / "target"
    source_tree = source_project / ".docmancer" / "tree"
    target_tree = target_project / ".docmancer" / "tree"
    source_project.mkdir()
    target_project.mkdir()
    project_id = "prj_1234567890abcdef"
    entry = TreeStore(source_tree).write(
        relative_path="decisions/release.md",
        text="# Release\n\nDeploy through Railway.",
        scope="project",
        project_id=project_id,
        expect="absent",
    )
    payload = payload_for_file(entry.path, tree_root=source_tree, project_id=project_id)
    local_root = tmp_path / "device-b"
    CloudConfig(local_root).link_project(project_id, target_project)
    state = CloudState(CloudConfig(local_root).paths.sync_state)
    assert apply_tree_payload(payload, root=local_root, state=state) == "applied"
    copied = TreeStore(target_tree).read(entry.address)
    assert "Railway" in copied.body
    assert copied.revision_id == entry.revision_id


def test_first_tree_scan_records_all_heads_in_one_batch(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    root = tmp_path / "device"
    tree = TreeStore(project / ".docmancer" / "tree")
    for index in range(12):
        tree.write(
            relative_path=f"decisions/decision-{index}.md",
            text=f"# Decision {index}\n\nKeep the first sync resumable.",
            scope="project",
            project_id="prj_1234567890abcdef",
            expect="absent",
        )

    batches: list[int] = []
    original = CloudState.set_tree_heads

    def tracked_batch(self, heads):
        rows = list(heads)
        batches.append(len(rows))
        original(self, rows)

    def reject_per_file(*_args, **_kwargs):
        raise AssertionError("first sync must not open SQLite once per tree file")

    monkeypatch.setattr(CloudState, "set_tree_heads", tracked_batch)
    monkeypatch.setattr(CloudState, "set_tree_head", reject_per_file)

    result = queue_tree_changes(project, root=root)

    assert result == {"changed": 12, "queued": 0}
    assert batches == [12]
    config = CloudConfig(root)
    project_id = config.project_id_for_path(project)
    assert project_id is not None
    assert len(CloudState(config.paths.sync_state).tree_heads(project_id)) == 12


def test_ambiguous_checkout_is_preserved_as_mapping_conflict(tmp_path: Path):
    project_id = "prj_1234567890abcdef"
    payload = build_tree_payload(
        object_kind="tree_file",
        file_id="abc",
        project_id=project_id,
        relative_path="release.md",
        markdown="# Release\n",
        metadata={},
        updated_at="2026-07-23T10:00:00+00:00",
    )
    root = tmp_path / "device"
    for name in ("one", "two"):
        path = tmp_path / name
        path.mkdir()
        CloudConfig(root).link_project(project_id, path)
    state = CloudState(CloudConfig(root).paths.sync_state)
    assert apply_tree_payload(payload, root=root, state=state) == "deferred"
    assert state.conflicts()[0]["reason"] == "project_mapping_ambiguous"


def test_moved_checkout_and_duplicate_checkout_mapping_states(tmp_path: Path):
    project_id = "prj_1234567890abcdef"
    root = tmp_path / "device"
    moved_from = tmp_path / "old-name"
    moved_to = tmp_path / "new-name"
    moved_from.mkdir()
    config = CloudConfig(root)
    config.link_project(project_id, moved_from)
    moved_from.rename(moved_to)
    assert config.mapping_status(project_id)["state"] == "unmapped"
    config.link_project(project_id, moved_to)
    assert config.mapping_status(project_id) == {
        "project_id": project_id,
        "state": "mapped",
        "paths": [str(moved_to.resolve())],
    }
    duplicate = tmp_path / "second-checkout"
    duplicate.mkdir()
    config.link_project(project_id, duplicate)
    assert config.mapping_status(project_id)["state"] == "ambiguous"


def test_two_devices_converge_non_conflicting_tree_files_and_preserve_divergence(tmp_path: Path):
    project_id = "prj_1234567890abcdef"
    device_a = tmp_path / "device-a"
    device_b = tmp_path / "device-b"
    project_a = tmp_path / "checkout-a"
    project_b = tmp_path / "checkout-b"
    CloudConfig(device_a).link_project(project_id, project_a)
    CloudConfig(device_b).link_project(project_id, project_b)
    tree_a = TreeStore(project_a / ".docmancer" / "tree")
    tree_b = TreeStore(project_b / ".docmancer" / "tree")
    left = tree_a.write(
        relative_path="decisions/left.md",
        text="# Left\n\nWritten offline on A.",
        scope="project",
        project_id=project_id,
        sources=["source:a"],
        expect="absent",
    )
    right = tree_b.write(
        relative_path="decisions/right.md",
        text="# Right\n\nWritten offline on B.",
        scope="project",
        project_id=project_id,
        sources=["source:b"],
        expect="absent",
    )
    state_a = CloudState(CloudConfig(device_a).paths.sync_state)
    state_b = CloudState(CloudConfig(device_b).paths.sync_state)
    workspace_key = random_key()
    signing_a, public_a = signing_keypair()
    signing_b, public_b = signing_keypair()
    left_payload = payload_for_file(left.path, tree_root=tree_a.root, project_id=project_id)
    right_payload = payload_for_file(right.path, tree_root=tree_b.root, project_id=project_id)
    left_envelope = build_envelope(
        left_payload,
        workspace_id="00000000-0000-4000-8000-000000000001",
        device_id="00000000-0000-4000-8000-00000000000a",
        workspace_key=workspace_key,
        signing_private_key=signing_a,
    )
    right_envelope = build_envelope(
        right_payload,
        workspace_id="00000000-0000-4000-8000-000000000001",
        device_id="00000000-0000-4000-8000-00000000000b",
        workspace_key=workspace_key,
        signing_private_key=signing_b,
    )
    assert apply_tree_payload(
        open_envelope(
            right_envelope,
            workspace_key=workspace_key,
            signing_public_key=public_b,
        ),
        root=device_a,
        state=state_a,
    ) == "applied"
    assert apply_tree_payload(
        open_envelope(
            left_envelope,
            workspace_key=workspace_key,
            signing_public_key=public_a,
        ),
        root=device_b,
        state=state_b,
    ) == "applied"
    tree_a = TreeStore(project_a / ".docmancer" / "tree")
    tree_b = TreeStore(project_b / ".docmancer" / "tree")
    assert "Written offline on B" in tree_a.read(right.address).body
    assert "Written offline on A" in tree_b.read(left.address).body

    base = tree_a.write(
        relative_path="decisions/shared.md",
        text="# Shared\n\nBase.",
        scope="project",
        project_id=project_id,
        sources=["source:base"],
        expect="absent",
    )
    base_payload = payload_for_file(base.path, tree_root=tree_a.root, project_id=project_id)
    assert apply_tree_payload(base_payload, root=device_b, state=state_b) == "applied"
    tree_b = TreeStore(project_b / ".docmancer" / "tree")
    edited_a = tree_a.edit(
        base.address,
        text="# Shared\n\nA changed this offline.",
        expected_hash=base.content_hash,
    )
    copied_base = tree_b.read(base.address)
    edited_b = tree_b.edit(
        base.address,
        text="# Shared\n\nB changed this offline.",
        expected_hash=copied_base.content_hash,
    )
    divergent = payload_for_file(
        edited_a.path,
        tree_root=tree_a.root,
        project_id=project_id,
        parent=base.revision_id,
    )
    assert apply_tree_payload(divergent, root=device_b, state=state_b) == "conflict"
    assert "B changed this offline" in tree_b.read(edited_b.address).body
    conflict = state_b.conflicts()[0]
    assert conflict["reason"] == "tree_diverged_heads"
    assert "A changed this offline" in conflict["payload"]["markdown"]


def test_team_generation_excludes_personal_and_secret_content(tmp_path: Path):
    project = tmp_path / "project"
    cloud_root = tmp_path / "home"
    CloudConfig(cloud_root).link_project("prj_1234567890abcdef", project)
    tree = TreeStore(project / ".docmancer" / "tree")
    tree.write(
        relative_path="release.md",
        text="# Release\n\nDeploy through Railway.",
        scope="project",
        project_id="prj_1234567890abcdef",
        sources=["/Users/person/private/session.md"],
        expect="absent",
    )
    tree.write(
        relative_path="personal.md",
        text="# Personal\n\nMy private preference.",
        scope="global",
        expect="absent",
    )
    tree.write(
        relative_path="secret.md",
        text="# Secret\n\napi_key=sk-abcdefghijklmnop",
        scope="project",
        project_id="prj_1234567890abcdef",
        expect="absent",
    )
    preview = generate_team_file(project, root=cloud_root)
    assert preview["selected_count"] == 1
    assert {row["reason"] for row in preview["excluded"]} == {
        "non-project scope",
        "secret or credential finding",
    }
    with pytest.raises(ValueError, match="whole-file approval"):
        generate_team_file(project, root=cloud_root, apply=True)
    applied = generate_team_file(
        project,
        root=cloud_root,
        apply=True,
        approved=True,
        approver_id="profile-1",
    )
    assert applied["applied"] is True
    rendered = Path(applied["destination"]).read_text(encoding="utf-8")
    assert "Railway" in rendered
    assert "private preference" not in rendered
    assert "/Users/person" not in rendered
    assert "publication_state: published" in rendered

    blocked = transition_team_file(
        project,
        domain="standards",
        outcome="blocked",
        root=cloud_root,
    )
    assert blocked["publication_state"] == "blocked"
    assert blocked["parent_revision_id"] == applied["revision_id"]
    assert "publication_state: blocked" in Path(blocked["destination"]).read_text(encoding="utf-8")

    restored = transition_team_file(
        project,
        domain="standards",
        outcome="restored",
        root=cloud_root,
    )
    assert restored["publication_state"] == "restored"
    assert restored["parent_revision_id"] == blocked["revision_id"]
    assert "publication_state: restored" in Path(restored["destination"]).read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        transition_team_file(
            project,
            domain="standards",
            outcome="deleted",
            root=cloud_root,
        )
