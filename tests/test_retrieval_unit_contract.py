"""Retrieval-unit contract fixtures (T011): adjacency survives for a
conversational source and is absent for an instruction file.

See docs/contracts/retrieval-unit-contract.md.
"""
from __future__ import annotations

import json
from pathlib import Path

from docmancer.harness.base import MemoryEntry
from docmancer.memory import MemoryAgent, RETRIEVAL_UNIT_STRATEGY
from docmancer.memory.atomic import extract_atoms
from docmancer.memory.importers import conversation_atoms
from docmancer.core.models import RetrievedChunk


def _chatgpt_export_fixture(tmp_path: Path) -> Path:
    export = [
        {
            "title": "Deployment planning",
            "mapping": {
                "n1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["Where should we deploy the worker?"]},
                        "create_time": 1,
                    }
                },
                "n2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": ["Railway handles the worker deployment well."]},
                        "create_time": 2,
                    }
                },
            },
        }
    ]
    path = tmp_path / "chatgpt_export.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    return path


def test_conversational_source_preserves_session_turn_and_speaker(tmp_path: Path):
    export_path = _chatgpt_export_fixture(tmp_path)
    atoms = conversation_atoms(export_path, source="chatgpt")

    assert atoms, "fixture conversation must produce at least one atom"
    for atom in atoms:
        assert atom.session_id is not None
        assert atom.turn_index is not None
        assert atom.speaker in {"user", "assistant"}


def test_turn_index_is_monotonic_within_one_session_and_matches_message_order(tmp_path: Path):
    export_path = _chatgpt_export_fixture(tmp_path)
    atoms = conversation_atoms(export_path, source="chatgpt")

    by_session: dict[str, list[int]] = {}
    for atom in atoms:
        by_session.setdefault(atom.session_id, []).append(atom.turn_index)
    for session_id, indices in by_session.items():
        assert indices == sorted(indices), f"turn_index must be non-decreasing within {session_id}"

    # The user's question is turn 0, the assistant's reply is turn 1.
    user_atom = next(a for a in atoms if a.speaker == "user")
    assistant_atom = next(a for a in atoms if a.speaker == "assistant")
    assert user_atom.turn_index == 0
    assert assistant_atom.turn_index == 1
    assert user_atom.session_id == assistant_atom.session_id


def test_instruction_file_has_no_adjacency_metadata(tmp_path: Path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        "# Project instructions\n\n"
        "Always run the full test suite before claiming completion.\n\n"
        "Never commit directly to main.\n",
        encoding="utf-8",
    )
    entry = MemoryEntry(
        harness="codex",
        scope="global:codex",
        title="AGENTS.md",
        content=agents_md.read_text(encoding="utf-8"),
        path=str(agents_md),
        extra={"kind": "instructions"},
    )
    atoms = extract_atoms(entry)

    assert atoms, "fixture instruction file must produce at least one atom"
    for atom in atoms:
        assert atom.session_id is None
        assert atom.turn_index is None
        assert atom.speaker is None


def test_rank_unit_is_turn_and_return_unit_is_surrounding_window(tmp_path: Path):
    atoms = conversation_atoms(_chatgpt_export_fixture(tmp_path), source="chatgpt")

    documents = MemoryAgent._retrieval_documents(atoms)

    user = next(document for document in documents if document.metadata["speaker"] == "user")
    assert user.content == "Where should we deploy the worker?"
    assert user.metadata["retrieval_unit"] == "turn"
    assert user.metadata["return_unit"] == "context_window"
    assert "Railway handles the worker deployment well." in user.metadata["context_text"]
    assert len(user.metadata["context_member_ids"]) == 2


def test_overlapping_return_windows_collapse_without_changing_best_score(tmp_path: Path):
    atoms = conversation_atoms(_chatgpt_export_fixture(tmp_path), source="chatgpt")
    documents = MemoryAgent._retrieval_documents(atoms)
    chunks = [
        RetrievedChunk(
            source=document.source,
            chunk_index=0,
            text=document.content,
            score=0.9 - index * 0.1,
            metadata=document.metadata,
        )
        for index, document in enumerate(documents)
    ]

    collapsed = MemoryAgent._collapse_context_windows(chunks)

    assert len(collapsed) == 1
    assert collapsed[0].score == 0.9
    assert "user: Where should we deploy the worker?" in collapsed[0].text
    assert "assistant: Railway handles the worker deployment well." in collapsed[0].text


def test_retrieval_strategy_has_an_explicit_schema_identity():
    assert RETRIEVAL_UNIT_STRATEGY == "rank-turn-return-window-v1"
