"""Revision identity determinism (T012). See docs/contracts/revision-identity-contract.md."""
from __future__ import annotations

from docmancer.memory.tree.revision_identity import content_revision_id


def test_two_independent_builds_over_identical_tree_state_produce_identical_revision_id():
    # Same underlying set, deliberately constructed/ordered differently to
    # simulate two independent devices/builds enumerating in different order.
    build_a = [("mem_b", "hash_b"), ("mem_a", "hash_a"), ("mem_c", "hash_c")]
    build_b = [("mem_c", "hash_c"), ("mem_b", "hash_b"), ("mem_a", "hash_a")]
    policy = {"clustering_version": 1, "dedup_policy_version": 1}

    revision_a = content_revision_id(build_a, policy)
    revision_b = content_revision_id(build_b, policy)

    assert revision_a == revision_b


def test_revision_id_changes_when_a_member_hash_changes():
    base = [("mem_a", "hash_a"), ("mem_b", "hash_b")]
    changed = [("mem_a", "hash_a"), ("mem_b", "hash_b_edited")]
    policy = {"clustering_version": 1}

    assert content_revision_id(base, policy) != content_revision_id(changed, policy)


def test_revision_id_changes_when_membership_changes():
    base = [("mem_a", "hash_a"), ("mem_b", "hash_b")]
    added_member = base + [("mem_c", "hash_c")]
    policy = {"clustering_version": 1}

    assert content_revision_id(base, policy) != content_revision_id(added_member, policy)


def test_revision_id_changes_when_policy_inputs_change():
    members = [("mem_a", "hash_a")]

    assert content_revision_id(members, {"clustering_version": 1}) != content_revision_id(
        members, {"clustering_version": 2}
    )


def test_revision_id_is_stable_across_repeated_calls():
    members = [("mem_a", "hash_a"), ("mem_b", "hash_b")]
    policy = {"schema_version": 1}
    assert content_revision_id(members, policy) == content_revision_id(members, policy)


def test_revision_id_has_a_stable_prefix():
    assert content_revision_id([("mem_a", "hash_a")], {}).startswith("rev_")
