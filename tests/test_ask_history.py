from __future__ import annotations

import sqlite3

import pytest

from docmancer.web.ask_history import AskHistoryStore


def test_ask_history_persists_messages_and_metadata(tmp_path) -> None:
    path = tmp_path / "ask.sqlite3"
    store = AskHistoryStore(path, project_id="project-1", project_label="Project")
    conversation = store.create_conversation()
    user_id, answer_id = store.begin_exchange(
        conversation["id"],
        "Why did we choose SQLite for local state?",
    )
    store.complete_answer(
        conversation["id"],
        answer_id,
        "It keeps the local product self-contained. [1]",
        metadata={
            "provider": "openrouter",
            "model": "test-model",
            "cost_usd": 0.001,
            "token_estimate": 120,
            "index_revision": "revision-1",
            "evidence": [{"title": "Architecture", "address": "docmancer://memory/one"}],
        },
    )

    reopened = AskHistoryStore(path, project_id="project-1", project_label="Project")
    detail = reopened.get_conversation(conversation["id"])
    assert detail is not None
    assert detail["title"] == "Why did we choose SQLite for local state?"
    assert [message["id"] for message in detail["messages"]] == [user_id, answer_id]
    assert detail["messages"][1]["provider"] == "openrouter"
    assert detail["messages"][1]["evidence"][0]["title"] == "Architecture"


def test_ask_history_is_project_scoped_and_deletion_cascades(tmp_path) -> None:
    path = tmp_path / "ask.sqlite3"
    first = AskHistoryStore(path, project_id="project-1", project_label="One")
    second = AskHistoryStore(path, project_id="project-2", project_label="Two")
    conversation = first.create_conversation()
    first.begin_exchange(conversation["id"], "Remember this conversation")

    assert second.list_conversations() == []
    assert second.get_conversation(conversation["id"]) is None
    assert first.delete_conversation(conversation["id"]) is True

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM ask_messages").fetchone()[0] == 0


def test_ask_history_rejects_untrusted_identifiers(tmp_path) -> None:
    store = AskHistoryStore(
        tmp_path / "ask.sqlite3",
        project_id="project-1",
        project_label="Project",
    )
    with pytest.raises(ValueError, match="invalid"):
        store.get_conversation("../../outside")


def test_ask_history_persists_and_supersedes_actions(tmp_path) -> None:
    path = tmp_path / "ask.sqlite3"
    store = AskHistoryStore(path, project_id="project-1", project_label="Project")
    conversation = store.create_conversation()
    _, first_message = store.begin_exchange(conversation["id"], "Update the release memory")
    store.complete_answer(conversation["id"], first_message, "First proposal")
    first = store.save_action(
        conversation["id"],
        first_message,
        {
            "operation": "edit",
            "scope": "project",
            "address": "docmancer://memory/release",
            "target": "docmancer://memory/release",
            "path": "decisions/release.md",
            "status": "pending",
            "before_markdown": "old",
            "after_markdown": "first",
            "diff": "first diff",
        },
    )

    _, second_message = store.begin_exchange(conversation["id"], "Revise that update")
    store.complete_answer(conversation["id"], second_message, "Second proposal")
    second = store.save_action(
        conversation["id"],
        second_message,
        {
            "operation": "edit",
            "scope": "project",
            "address": "docmancer://memory/release",
            "target": "docmancer://memory/release",
            "path": "decisions/release.md",
            "status": "pending",
            "before_markdown": "old",
            "after_markdown": "second",
            "diff": "second diff",
        },
    )

    assert store.get_action(first["id"])["status"] == "superseded"
    assert store.get_action(second["id"])["status"] == "pending"
    detail = store.get_conversation(conversation["id"])
    assert detail["messages"][1]["action"]["status"] == "superseded"
    assert detail["messages"][3]["action"]["after_markdown"] == "second"


def test_deleting_conversation_removes_unapplied_action_records(tmp_path) -> None:
    path = tmp_path / "ask.sqlite3"
    store = AskHistoryStore(path, project_id="project-1", project_label="Project")
    conversation = store.create_conversation()
    _, message_id = store.begin_exchange(conversation["id"], "Forget this decision")
    store.complete_answer(conversation["id"], message_id, "Trash proposal")
    store.save_action(
        conversation["id"],
        message_id,
        {
            "operation": "trash",
            "scope": "project",
            "address": "docmancer://memory/release",
            "target": "docmancer://memory/release",
            "path": "decisions/release.md",
            "status": "pending",
            "before_markdown": "old",
            "after_markdown": "",
            "diff": "trash diff",
        },
    )

    assert store.delete_conversation(conversation["id"]) is True
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM ask_actions").fetchone()[0] == 0
