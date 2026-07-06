import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _plant(home):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    (mem / "note.md").write_text("We deploy on Railway.\n")
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def _env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    _plant(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    return tmp_path / "mem.db"


def test_scan_lists_harness(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "scan"])
    assert r.exit_code == 0
    assert "claude-code" in r.output


def test_sync_dry_run_writes_nothing(tmp_path, monkeypatch):
    db = _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "sync", "--dry-run"])
    assert r.exit_code == 0
    assert "Would index" in r.output
    assert not db.exists()


def test_sync_then_query(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    s = CliRunner().invoke(cli, ["memory", "sync"])
    assert s.exit_code == 0, s.output
    q = CliRunner().invoke(cli, ["memory", "query", "where do we deploy"])
    assert q.exit_code == 0, q.output
    assert "Railway" in q.output


def test_sources_preview_lists_provenance(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "sources", "--preview"])
    assert r.exit_code == 0, r.output
    assert "claude-code" in r.output
    assert "would index" in r.output
    assert "CLAUDE-CODE" in r.output  # grouped section header


def test_sources_json_and_filter(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "sources", "--preview", "--json", "--agent", "claude-code"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data and all(row["agent"] == "claude-code" for row in data)
    assert "chars" in data[0] and "path" in data[0]


def test_sources_stored_index_after_sync(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    CliRunner().invoke(cli, ["memory", "sync"])
    r = CliRunner().invoke(cli, ["memory", "sources"])
    assert r.exit_code == 0, r.output
    assert "files indexed" in r.output
    assert "claude-code" in r.output


def test_clear_removes_and_status_reports_empty(tmp_path, monkeypatch):
    db = _env(monkeypatch, tmp_path)
    CliRunner().invoke(cli, ["memory", "sync"])
    assert db.exists()
    c = CliRunner().invoke(cli, ["memory", "clear", "--yes"])
    assert c.exit_code == 0, c.output
    assert not db.exists()
    st = CliRunner().invoke(cli, ["memory", "status"])
    assert st.exit_code == 0
    assert "Exists: False" in st.output


def test_consolidate_defaults_to_agent_provider(tmp_path, monkeypatch):
    from docmancer.ai.agent_cli_client import AgentCliClient
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection

    _env(monkeypatch, tmp_path)

    def fake_preflight(self, *, model=None):
        return None

    def fake_parse(self, messages, response_format, **kwargs):
        return ConsolidatedMemoryDraft(
            title="Master Memory",
            summary="summary",
            sections=[ConsolidatedMemorySection(heading="Infra", body="Railway.")],
            source_paths=["note.md"],
        )

    monkeypatch.setattr(AgentCliClient, "_resolve_agent", classmethod(lambda cls, agent: "claude"))
    monkeypatch.setattr(AgentCliClient, "preflight", fake_preflight)
    monkeypatch.setattr(AgentCliClient, "parse", fake_parse)

    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    assert "Claude Code" in r.output
    assert "Railway" in out.read_text()


def test_consolidate_markdown_compacts_large_source_lists():
    from docmancer.ai.memory_features import draft_to_markdown
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection

    draft = ConsolidatedMemoryDraft(
        title="Master Memory",
        summary="summary",
        sections=[ConsolidatedMemorySection(heading="Infra", body="Railway.")],
        source_paths=[f"/Users/x/app/memory/source-{i}.md" for i in range(30)],
    )

    markdown = draft_to_markdown(draft)

    assert "This draft cites 30 source file(s)." in markdown
    assert "more source file(s) omitted" in markdown
    assert "/Users/x/app/memory/source-29.md" not in markdown


def test_merge_text_compacts_verbose_intermediate_drafts():
    from docmancer.ai.memory_features import draft_to_merge_text
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection

    draft = ConsolidatedMemoryDraft(
        title="Batch Memory",
        summary="summary " * 400,
        sections=[
            ConsolidatedMemorySection(heading=f"Section {i}", body="durable detail " * 800)
            for i in range(5)
        ],
        source_paths=[f"/Users/x/app/memory/source-{i}.md" for i in range(100)],
        warnings=["warning " * 200 for _ in range(20)],
    )

    text = draft_to_merge_text(draft, max_chars=6_000)

    assert len(text) <= 6_100
    assert "Source files represented: 100" in text
    assert "/Users/x/app/memory/source-99.md" not in text
    assert "truncated for merge" in text


def test_codex_consolidate_defaults_to_parallel_batches(tmp_path, monkeypatch):
    from docmancer.ai.agent_cli_client import AgentCliClient
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection

    _env(monkeypatch, tmp_path)

    def fake_preflight(self, *, model=None):
        return None

    def fake_parse(self, messages, response_format, **kwargs):
        return ConsolidatedMemoryDraft(
            title="Master Memory",
            summary="summary",
            sections=[ConsolidatedMemorySection(heading="Infra", body="Railway.")],
            source_paths=["note.md"],
        )

    monkeypatch.setattr(AgentCliClient, "_resolve_agent", classmethod(lambda cls, agent: "codex"))
    monkeypatch.setattr(AgentCliClient, "preflight", fake_preflight)
    monkeypatch.setattr(AgentCliClient, "parse", fake_parse)

    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "codex", "--output", str(out), "--yes"])

    assert r.exit_code == 0, r.output
    assert "provider  Codex" in r.output
    assert "concurrency        2" in r.output


def test_unknown_provider_is_not_available(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "not-a-provider", "--yes"])
    assert r.exit_code == 2
    assert "Invalid value" in r.output


def test_default_agent_provider_error_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _binary: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _env(monkeypatch, tmp_path)

    r = CliRunner().invoke(cli, ["memory", "consolidate", "--yes"])
    assert r.exit_code == 2
    assert "Agent provider setup failed" in r.output
    assert "no supported agent CLI found on PATH" in r.output
    assert "OpenRouter fallback unavailable" in r.output
    assert "Traceback" not in r.output


def test_agent_provider_falls_back_to_openrouter_on_runtime_failure(tmp_path, monkeypatch):
    from docmancer.ai.agent_cli_client import AgentCliClient, AgentCliError
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection
    from docmancer.ai.openrouter_client import OpenRouterClient

    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def failing_preflight(self, *, model=None):
        raise AgentCliError("Claude Code failed: test failure")

    def openrouter_preflight(self, *, model=None):
        return None

    seen = {}

    def openrouter_parse(self, messages, response_format, **kwargs):
        seen["max_tokens"] = kwargs.get("max_tokens")
        return ConsolidatedMemoryDraft(
            title="Fallback Memory",
            summary="summary",
            sections=[ConsolidatedMemorySection(heading="Infra", body="Railway via fallback.")],
            source_paths=["note.md"],
        )

    monkeypatch.setattr(AgentCliClient, "_resolve_agent", classmethod(lambda cls, agent: "claude"))
    monkeypatch.setattr(AgentCliClient, "preflight", failing_preflight)
    monkeypatch.setattr(OpenRouterClient, "preflight", openrouter_preflight)
    monkeypatch.setattr(OpenRouterClient, "parse", openrouter_parse)

    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    assert "Agent provider failed" in r.output
    assert "Retrying with OpenRouter fallback" in r.output
    assert "batch budget       25,000 tokens" in r.output
    assert "output cap         8,192 tokens" in r.output
    assert "concurrency        3" in r.output
    assert seen["max_tokens"] == 8192
    assert "Railway via fallback" in out.read_text()
    assert "Traceback" not in r.output


def test_recursion_guard_blocks_memory_commands(monkeypatch):
    monkeypatch.setenv("DOCMANCER_NO_RECURSE", "1")
    r = CliRunner().invoke(cli, ["memory", "status"])
    assert r.exit_code == 2
    assert "disabled inside docmancer agent-provider subprocesses" in r.output
