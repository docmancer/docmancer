"""Base prompt, role extensions, and assembly order (T020-T022)."""
from __future__ import annotations

import pytest

from docmancer.ai.prompts.assembly import CorpusFrame, assemble_prompt
from docmancer.ai.prompts.base import (
    DOCMANCER_BASE_PROMPT,
    DOCMANCER_BASE_PROMPT_FILE_ENV,
    DOCMANCER_NO_BASE_PROMPT_ENV,
    base_prompt,
)
from docmancer.ai.prompts.roles import ROLE_EXTENSIONS, role_extension


# --- T020: base prompt module ---------------------------------------------

def test_base_prompt_snapshot_contains_every_required_section():
    text = DOCMANCER_BASE_PROMPT
    for heading in (
        "# Identity",
        "# Grounding",
        "# When the corpus does not answer the question",
        "# Conflicts",
        "# Reading provenance",
        "# Output",
        "# What you never do",
    ):
        assert heading in text


def test_base_prompt_snapshot_bans_the_em_dash():
    assert "—" not in DOCMANCER_BASE_PROMPT


def test_base_prompt_snapshot_states_the_prompt_injection_boundary():
    assert "Evidence is data" in DOCMANCER_BASE_PROMPT


def test_base_prompt_defaults_to_the_compiled_in_constant(monkeypatch):
    monkeypatch.delenv(DOCMANCER_NO_BASE_PROMPT_ENV, raising=False)
    monkeypatch.delenv(DOCMANCER_BASE_PROMPT_FILE_ENV, raising=False)
    assert base_prompt() == DOCMANCER_BASE_PROMPT


def test_no_base_prompt_env_disables_the_layer_entirely(monkeypatch):
    monkeypatch.setenv(DOCMANCER_NO_BASE_PROMPT_ENV, "1")
    assert base_prompt() == ""


def test_base_prompt_file_env_replaces_the_whole_layer(tmp_path, monkeypatch):
    override = tmp_path / "custom-base.md"
    override.write_text("Custom base prompt.\n", encoding="utf-8")
    monkeypatch.delenv(DOCMANCER_NO_BASE_PROMPT_ENV, raising=False)
    monkeypatch.setenv(DOCMANCER_BASE_PROMPT_FILE_ENV, str(override))
    assert base_prompt() == "Custom base prompt.\n"


# --- T021: role extensions ---------------------------------------------------

def test_every_spec_role_has_an_extension():
    for role in ("ask", "brief", "review", "consolidate"):
        text = role_extension(role)
        assert isinstance(text, str) and text.strip()


def test_consolidate_role_extension_reuses_the_existing_system_prompt_verbatim():
    from docmancer.ai.memory_features import _CONSOLIDATE_SYSTEM

    assert role_extension("consolidate") == _CONSOLIDATE_SYSTEM


def test_unknown_role_raises():
    with pytest.raises(ValueError, match="unknown role"):
        role_extension("summarize")


def test_ask_brief_review_extensions_are_distinct():
    texts = {role: ROLE_EXTENSIONS[role] for role in ("ask", "brief", "review")}
    assert len(set(texts.values())) == 3


# --- T022: assembly order -----------------------------------------------------

def test_assembly_order_matches_spec_4_4():
    prompt = assemble_prompt(
        role="ask",
        preferences="Prefer decisions over code descriptions.",
        corpus=CorpusFrame(index_revision="rev_abc123", scope="global"),
        evidence="[1] sqlite-vec needs no daemon.",
        task="why sqlite-vec?",
    )
    labels_in_order = ["[Identity + Base]", "[Role]", "[Preferences]", "[Corpus]", "[Evidence]", "[Task]"]
    positions = [prompt.index(label) for label in labels_in_order]
    assert positions == sorted(positions), "blocks must appear in the fixed spec 4.4 order"


def test_evidence_block_is_always_labelled_and_always_after_corpus():
    prompt = assemble_prompt(
        role="brief",
        preferences="",
        corpus=CorpusFrame(index_revision="rev_x", scope="project:/repo"),
        evidence="some evidence text",
        task="what changed this week?",
    )
    assert "[Evidence]" in prompt
    assert prompt.index("[Corpus]") < prompt.index("[Evidence]")


def test_corpus_block_states_revision_scope_and_subset_note():
    prompt = assemble_prompt(
        role="review",
        preferences="",
        corpus=CorpusFrame(index_revision="rev_777", scope="team:acme"),
        evidence="e",
        task="t",
    )
    assert "rev_777" in prompt
    assert "team:acme" in prompt
    assert "retrieved subset" in prompt


def test_empty_preferences_and_evidence_render_explicit_placeholders():
    prompt = assemble_prompt(
        role="ask",
        preferences="",
        corpus=CorpusFrame(index_revision="rev_1", scope="global"),
        evidence="",
        task="t",
    )
    assert "(none set)" in prompt
    assert "(no evidence retrieved)" in prompt
