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


def test_sources_preview_shortens_home_paths(tmp_path, monkeypatch):
    from pathlib import Path

    home = tmp_path / "home"
    _plant(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    monkeypatch.setattr(Path, "home", lambda: home)

    r = CliRunner().invoke(cli, ["memory", "sources", "--preview"])

    assert r.exit_code == 0, r.output
    assert str(home) not in r.output
    assert "~/.claude/projects" in r.output


def test_sources_json_and_filter(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "sources", "--preview", "--json", "--agent", "claude-code"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data and all(row["agent"] == "claude-code" for row in data)
    assert "chars" in data[0] and "path" in data[0] and "display_path" in data[0]


def test_audit_reports_no_findings(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "audit"])
    assert r.exit_code == 0
    assert "No likely secrets found" in r.output


def test_audit_reports_masked_actionable_findings(tmp_path, monkeypatch):
    from pathlib import Path

    home = tmp_path / "home"
    _plant(home)
    secret_file = home / ".claude" / "projects" / "-Users-x-app" / "memory" / "creds.md"
    secret_file.write_text("api_key = supersecretvalue123\n")
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    monkeypatch.setattr(Path, "home", lambda: home)

    r = CliRunner().invoke(cli, ["memory", "audit", "--agent", "claude-code"])

    assert r.exit_code == 0, r.output
    assert "Found 1 likely secret" in r.output
    assert "Key-value secret" in r.output
    assert "supersecretvalue123" not in r.output
    assert "[SECRET]" in r.output
    assert "~/.claude/projects" in r.output
    assert "Next: rotate if real" in r.output


def test_audit_json_includes_raw_and_display_paths(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant(home)
    secret_file = home / ".claude" / "projects" / "-Users-x-app" / "memory" / "creds.md"
    secret_file.write_text("ghp_abcd1234efgh\n")
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))

    r = CliRunner().invoke(cli, ["memory", "audit", "--json"])

    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["finding_count"] == 1
    occurrence = data["findings"][0]["occurrences"][0]
    assert occurrence["source_path"].endswith("creds.md")
    assert "display_path" in occurrence
    assert "ghp_abcd1234efgh" not in r.output


def test_audit_fail_on_findings_exits_nonzero(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant(home)
    secret_file = home / ".claude" / "projects" / "-Users-x-app" / "memory" / "creds.md"
    secret_file.write_text("AKIA0123456789ABCDEF\n")
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))

    r = CliRunner().invoke(cli, ["memory", "audit", "--fail-on-findings"])

    assert r.exit_code == 1
    assert "AWS access key" in r.output


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


def test_hook_context_injects_relevant_memory_and_dedupes(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "docmancer-home"))
    s = CliRunner().invoke(cli, ["memory", "sync"])
    assert s.exit_code == 0, s.output

    payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "cwd": "/Users/x/app",
            "prompt": "Where do we deploy?",
        }
    )
    r = CliRunner().invoke(
        cli,
        ["memory", "hook-context", "--agent", "codex", "--threshold", "0", "--max-chars", "900"],
        input=payload,
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    context = data["hookSpecificOutput"]["additionalContext"]
    assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Relevant docmancer memories:" in context
    assert "Railway" in context
    assert "Source:" in context

    second = CliRunner().invoke(
        cli,
        ["memory", "hook-context", "--agent", "codex", "--threshold", "0"],
        input=payload,
    )
    assert second.exit_code == 0, second.output
    assert second.output == ""


def test_codex_hook_payload_outputs_documented_additional_context(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "docmancer-home"))
    s = CliRunner().invoke(cli, ["memory", "sync"])
    assert s.exit_code == 0, s.output

    payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "codex-session-1",
            "turn_id": "turn-1",
            "permission_mode": "workspace-write",
            "cwd": "/Users/x/app",
            "prompt": "Where do we deploy?",
        }
    )
    r = CliRunner().invoke(
        cli,
        ["memory", "hook-context", "--agent", "auto", "--threshold", "0"],
        input=payload,
    )

    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": data["hookSpecificOutput"]["additionalContext"],
        }
    }
    assert "Railway" in data["hookSpecificOutput"]["additionalContext"]


def test_session_start_does_not_dedupe_later_user_prompt(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "docmancer-home"))
    s = CliRunner().invoke(cli, ["memory", "sync"])
    assert s.exit_code == 0, s.output

    session_start = json.dumps(
        {
            "hook_event_name": "SessionStart",
            "session_id": "session-2",
            "cwd": "/Users/x/app",
        }
    )
    first = CliRunner().invoke(
        cli,
        ["memory", "hook-context", "--agent", "codex", "--threshold", "0"],
        input=session_start,
    )
    assert first.exit_code == 0, first.output

    user_prompt = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-2",
            "cwd": "/Users/x/app",
            "prompt": "Where do we deploy?",
        }
    )
    second = CliRunner().invoke(
        cli,
        ["memory", "hook-context", "--agent", "codex", "--threshold", "0"],
        input=user_prompt,
    )
    assert second.exit_code == 0, second.output
    assert "Railway" in second.output


def test_hook_seen_cache_keeps_recent_insertion_order(tmp_path, monkeypatch):
    from docmancer.memory import hooks

    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "docmancer-home"))
    hooks._save_seen("session-3", [f"fp-{i:03d}" for i in range(205)])

    seen = hooks._load_seen("session-3")
    assert seen == [f"fp-{i:03d}" for i in range(5, 205)]


def test_hook_context_is_silent_for_bad_input(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "hook-context", "--debug"], input="{")
    assert r.exit_code == 0
    assert r.output == ""


def test_consolidate_defaults_to_openrouter_provider(tmp_path, monkeypatch):
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection
    from docmancer.ai.openrouter_client import OpenRouterClient

    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def fake_preflight(self, *, model=None):
        return None

    def fake_parse(self, messages, response_format, **kwargs):
        return ConsolidatedMemoryDraft(
            title="Master Memory",
            summary="summary",
            sections=[ConsolidatedMemorySection(heading="Infra", body="Railway.")],
            source_paths=["note.md"],
        )

    monkeypatch.setattr(OpenRouterClient, "preflight", fake_preflight)
    monkeypatch.setattr(OpenRouterClient, "parse", fake_parse)

    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    assert "OpenRouter" in r.output
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


def test_agent_cli_providers_are_removed_from_consolidate(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "codex", "--output", str(out), "--yes"])
    assert r.exit_code == 2
    assert "Invalid value" in r.output


def test_consolidate_help_only_advertises_openrouter_provider():
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--help"])
    assert r.exit_code == 0, r.output
    assert "openrouter" in r.output
    assert "claude" not in r.output.lower()
    assert "codex" not in r.output.lower()
    assert "github-copilot" not in r.output


def test_unknown_provider_is_not_available(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "not-a-provider", "--yes"])
    assert r.exit_code == 2
    assert "Invalid value" in r.output


def test_default_provider_requires_openrouter_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _env(monkeypatch, tmp_path)

    r = CliRunner().invoke(cli, ["memory", "consolidate", "--yes"])
    assert r.exit_code == 2
    assert "OPENROUTER_API_KEY is not set" in r.output
    assert "Traceback" not in r.output


def test_openrouter_consolidate_uses_openrouter_defaults(tmp_path, monkeypatch):
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection
    from docmancer.ai.openrouter_client import OpenRouterClient

    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

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

    monkeypatch.setattr(OpenRouterClient, "preflight", openrouter_preflight)
    monkeypatch.setattr(OpenRouterClient, "parse", openrouter_parse)

    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
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
    assert "disabled inside docmancer subprocesses" in r.output
