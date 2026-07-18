from dataclasses import dataclass, field

from docmancer.memory.atomic import (
    AtomicMemoryEntry,
    classify_memory,
    extract_atoms,
    merge_atoms,
)


@dataclass
class FakeEntry:
    harness: str = "claude-code"
    scope: str = "project:/app"
    title: str = "memory"
    content: str = ""
    path: str = "/app/memory.md"
    extra: dict = field(default_factory=lambda: {"kind": "agent-memory"})


def test_extracts_headings_bullets_paragraphs_and_line_ranges():
    entry = FakeEntry(
        content=(
            "# Deploy\n"
            "\n"
            "- We chose Railway because the team already knows Postgres.\n"
            "- Prefer pnpm for package management.\n"
            "\n"
            "The production app uses a Next.js frontend and FastAPI backend.\n"
        )
    )

    atoms = extract_atoms(entry)

    texts = [atom.text for atom in atoms]
    # The heading breadcrumb is folded into the atom text so each atom is
    # self-contained when injected out of context.
    assert "Deploy: We chose Railway because the team already knows Postgres." in texts
    assert "Deploy: Prefer pnpm for package management." in texts
    assert "Deploy: The production app uses a Next.js frontend and FastAPI backend." in texts
    railway = next(atom for atom in atoms if "Railway" in atom.text)
    assert railway.type == "decision"
    assert railway.source_title == "Deploy"
    assert railway.line_start == 3
    assert railway.line_end == 3


def test_extract_atoms_have_stable_ids_and_dedupe_repeated_items():
    entry = FakeEntry(
        content=(
            "- Always run tests from the repo root.\n"
            "- Always run tests from the repo root.\n"
        )
    )

    first = extract_atoms(entry)
    second = extract_atoms(entry)

    assert len(first) == 1
    assert [atom.atom_id for atom in first] == [atom.atom_id for atom in second]
    assert first[0].type == "fact"


def test_atom_document_is_single_section_metadata_shape():
    entry = FakeEntry(content="- Do not read .env files when loading context.\n")
    [atom] = extract_atoms(entry)

    doc = atom.to_document()

    assert doc.source.startswith("memory://atom/")
    assert doc.content == "Do not read .env files when loading context."
    assert doc.metadata["chunking_strategy"] == "single"
    assert doc.metadata["format"] == "memory-atomic"
    assert doc.metadata["memory_layer"] == "atomic"
    assert doc.metadata["source_path"] == "/app/memory.md"
    assert doc.metadata["memory_type"] == "constraint"


def test_heading_breadcrumb_prefixes_nested_atom_text():
    entry = FakeEntry(
        content=(
            "# Deployment\n"
            "\n"
            "## Production\n"
            "\n"
            "- Uses Railway with restart set to NEVER.\n"
        )
    )

    [atom] = extract_atoms(entry)

    assert atom.text == "Deployment > Production: Uses Railway with restart set to NEVER."
    assert atom.source_title == "Deployment > Production"


def test_bullet_groups_subbullets_into_one_atom():
    entry = FakeEntry(
        content=(
            "- Deploy checklist:\n"
            "  - Run migrations first.\n"
            "  - Then restart the workers.\n"
        )
    )

    atoms = extract_atoms(entry)

    assert len(atoms) == 1
    assert "Deploy checklist" in atoms[0].text
    assert "Run migrations first" in atoms[0].text
    assert "Then restart the workers" in atoms[0].text
    assert atoms[0].line_start == 1
    assert atoms[0].line_end == 3


def _atom(text, *, harness, path, line=1, base_conf=1.0):
    return AtomicMemoryEntry(
        atom_id=f"{harness}-{line}-{text[:8]}",
        text=text,
        type="decision",
        harness=harness,
        kind="agent-memory",
        scope=f"project:{path}",
        source_path=path,
        source_title="Deploy",
        line_start=line,
        line_end=line,
        source_hash="sh",
        content_hash=f"ch-{text}",
        confidence=base_conf,
    )


def _fake_embed(vectors_by_text):
    def embed(texts):
        return [vectors_by_text[t] for t in texts]

    return embed


def test_merge_collapses_cross_agent_duplicates():
    codex = _atom("Deploy: production runs on Railway.", harness="codex", path="/a/CODEX.md")
    claude = _atom("Deploy: production runs on Railway with restart NEVER.", harness="claude-code", path="/b/CLAUDE.md")
    claude.scope = codex.scope
    unrelated = _atom("Deploy: prefer pnpm for packages.", harness="codex", path="/a/CODEX.md", line=5)

    embed = _fake_embed(
        {
            codex.text: [1.0, 0.0, 0.0],
            claude.text: [0.99, 0.01, 0.0],   # near-parallel to codex -> merge
            unrelated.text: [0.0, 1.0, 0.0],  # orthogonal -> stays separate
        }
    )

    merged = merge_atoms([codex, claude, unrelated], embed_texts=embed, threshold=0.9)

    assert len(merged) == 2
    canonical = next(a for a in merged if "Railway" in a.text)
    # The longer, more self-contained phrasing wins.
    assert canonical.text == claude.text
    assert canonical.source_count == 2
    assert set(canonical.merged_from) == {"/a/CODEX.md", "/b/CLAUDE.md"}
    assert canonical.confidence > 1.0 - 1e-9  # boosted, clamped at 1.0
    kept = next(a for a in merged if "pnpm" in a.text)
    assert kept.source_count == 1


def test_merge_preserves_durable_record_identity_when_harvested_text_wins():
    durable = _atom("Deploy: production runs on Railway.", harness="docmancer", path="/memories/record.md")
    durable.record_id = "record-123"
    durable.origin = "manual"
    harvested = _atom(
        "Deploy: production runs on Railway with automatic restarts enabled.",
        harness="codex",
        path="/repo/AGENTS.md",
    )
    harvested.scope = durable.scope
    embed = _fake_embed({durable.text: [1.0, 0.0], harvested.text: [1.0, 0.0]})

    merged = merge_atoms([durable, harvested], embed_texts=embed, threshold=0.9)

    assert len(merged) == 1
    assert merged[0].text == harvested.text
    assert merged[0].record_id == durable.record_id
    assert merged[0].origin == "manual"


def test_merge_keeps_distinct_durable_records_addressable():
    first = _atom("Deploy: production runs on Railway.", harness="docmancer", path="/memories/a.md")
    first.record_id = "record-a"
    second = _atom("Deploy: production runs on Railway with restarts.", harness="docmancer", path="/memories/b.md")
    second.record_id = "record-b"
    second.scope = first.scope
    embed = _fake_embed({first.text: [1.0, 0.0], second.text: [1.0, 0.0]})

    merged = merge_atoms([first, second], embed_texts=embed, threshold=0.9)

    assert {atom.record_id for atom in merged} == {"record-a", "record-b"}


def test_merge_is_noop_below_threshold():
    a = _atom("Deploy: use Railway.", harness="codex", path="/a/CODEX.md")
    b = _atom("Deploy: use Vercel.", harness="claude-code", path="/b/CLAUDE.md")
    embed = _fake_embed({a.text: [1.0, 0.0], b.text: [0.0, 1.0]})

    merged = merge_atoms([a, b], embed_texts=embed, threshold=0.9)

    assert len(merged) == 2
    assert all(atom.source_count == 1 for atom in merged)


def test_merge_returns_atoms_unchanged_when_embedding_fails():
    a = _atom("x fact one here", harness="codex", path="/a/CODEX.md")
    b = _atom("y fact two here", harness="codex", path="/a/CODEX.md", line=2)

    def broken_embed(texts):
        raise RuntimeError("no backend")

    merged = merge_atoms([a, b], embed_texts=broken_embed, threshold=0.9)

    assert merged == [a, b]


def test_merge_keeps_conflicting_memories_separate():
    use = _atom("Deploy: use Railway for production.", harness="codex", path="/a/CODEX.md")
    avoid = _atom(
        "Deploy: do not use Railway for production.",
        harness="claude-code",
        path="/b/CLAUDE.md",
    )
    avoid.scope = use.scope
    embed = _fake_embed({use.text: [1.0, 0.0], avoid.text: [1.0, 0.0]})

    merged = merge_atoms([use, avoid], embed_texts=embed, threshold=0.9)

    assert merged == [use, avoid]


def test_extract_ignores_docmancer_managed_blocks():
    entry = FakeEntry(
        content=(
            "- Keep this user-authored instruction.\n"
            "<!-- docmancer:memory:begin (managed; edits inside are overwritten on next apply) -->\n"
            "# docmancer memory atoms\n"
            "- [fact] Generated memory that must not be re-harvested.\n"
            "<!-- docmancer:memory:end -->\n"
            "<!-- docmancer:start -->\n"
            "- Generated projection that must not be re-harvested.\n"
            "<!-- docmancer:end -->\n"
        )
    )

    atoms = extract_atoms(entry)

    assert [atom.text for atom in atoms] == ["Keep this user-authored instruction."]


def test_classify_memory_types():
    assert classify_memory("We chose Railway because deploys are simpler.") == "decision"
    assert classify_memory("Prefer direct prose for public docs.") == "preference"
    assert classify_memory("Never read .env files.") == "constraint"
    assert classify_memory("Warning: old vectors can go stale.") == "warning"
    assert classify_memory("`docmancer memory sync` rebuilds the index.") == "command"
