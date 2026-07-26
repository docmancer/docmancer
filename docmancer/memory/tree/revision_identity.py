"""Deterministic revision identity (T012, docs/contracts/revision-identity-contract.md).

``content_revision_id`` is the seed T067 builds ``ContextRevision.revision_id``
from: a pure function of an ordered-by-sorting member set plus policy inputs,
so that two independent builds over identical tree state -- regardless of
filesystem enumeration order or dict iteration order -- produce an identical
revision id.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

REVISION_ID_SCHEMA = 1


def content_revision_id(
    member_hashes: Iterable[tuple[str, str]],
    policy_inputs: dict[str, Any],
) -> str:
    """Hash an ordered-by-sorting member set plus policy inputs.

    ``member_hashes`` is an iterable of ``(member_id, content_hash)`` pairs in
    any order; they are sorted by ``member_id`` before hashing. ``policy_inputs``
    is any JSON-serializable dict of every non-membership input that can
    change the computed revision (clustering version, thresholds, dedup
    policy version, schema version, prompt version, model, provider, role,
    generation params -- the same discipline as the cache key in spec 7.7
    step 4). Returns a ``rev_`` prefixed hex digest.
    """
    ordered_members = sorted(member_hashes, key=lambda pair: pair[0])
    payload = {
        "schema": REVISION_ID_SCHEMA,
        "members": ordered_members,
        "policy": policy_inputs,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "rev_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


__all__ = ["content_revision_id", "REVISION_ID_SCHEMA"]
