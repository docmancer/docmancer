import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.cli.memory_commands import _entry_in_project


class _Entry:
    def __init__(self, scope):
        self.scope = scope


def _plant_agent_memory(home, project_path):
    import json

    project = home / ".claude" / "projects" / "-Users-x-repo"
    memory = project / "memory"
    memory.mkdir(parents=True)
    (memory / "release.md").write_text("Production deploys run through Railway.\n")
    (project / "session.jsonl").write_text(json.dumps({"cwd": str(project_path)}) + "\n")


def test_digest_dry_run_lists_sources_without_provider(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    monkeypatch.chdir(project)
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(home / ".docmancer" / "memory.db"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = CliRunner().invoke(cli, ["memory", "digest", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Digest plan" in result.output
    # Dry run must actually name discovered sources and estimate output tokens.
    assert "release.md" in result.output
    assert "est output tokens" in result.output
    # No file is written and no provider is contacted on a dry run.
    assert not (project / "machine-memory-digest.md").exists()


def test_digest_without_key_falls_back_to_source_listing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    monkeypatch.chdir(project)
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(home / ".docmancer" / "memory.db"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = CliRunner().invoke(cli, ["memory", "digest", "--yes"])

    # No key: clean non-zero exit, a clear message, and the raw-source listing.
    assert result.exit_code == 2, result.output
    assert "would be digested" in result.output
    assert "release.md" in result.output
    assert not (project / "machine-memory-digest.md").exists()


def test_digest_default_output_is_outside_working_directory(tmp_path, monkeypatch):
    from docmancer.cli.memory_commands import _digest_default_output

    cfg = tmp_path / "cfg"
    monkeypatch.setenv("DOCMANCER_HOME", str(cfg))
    repo = tmp_path / "repo"

    machine = _digest_default_output("machine", repo)
    project = _digest_default_output("project", repo)

    # Both defaults live under the docmancer home, never inside the working repo,
    # so a fresh repo that does not ignore .docmancer/ cannot commit the digest.
    assert cfg in machine.parents
    assert cfg in project.parents
    assert repo not in project.parents
    # Project digests are namespaced by project path so two projects do not clash.
    assert repo.name in project.name


def test_digest_dry_run_reports_no_sources(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(home / ".docmancer" / "memory.db"))

    result = CliRunner().invoke(cli, ["memory", "digest", "--dry-run"])

    assert result.exit_code == 1, result.output
    assert "No memory sources" in result.output


def test_digest_run_redacts_and_requests_inline_citations(tmp_path, monkeypatch):
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft, ConsolidatedMemorySection
    from docmancer.ai.openrouter_client import OpenRouterClient

    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    proj_mem = home / ".claude" / "projects" / "-Users-x-repo"
    memory = proj_mem / "memory"
    memory.mkdir(parents=True)
    # A durable fact plus a planted secret that redaction must strip.
    (memory / "infra.md").write_text(
        "We deploy on Railway.\nAWS key AKIAIOSFODNN7EXAMPLE lives here.\n"
    )
    (proj_mem / "session.jsonl").write_text(json.dumps({"cwd": str(project)}) + "\n")
    monkeypatch.chdir(project)
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(home / ".docmancer" / "memory.db"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    seen = {}

    def fake_preflight(self, *, model=None):
        return None

    def fake_parse(self, messages, response_format, **kwargs):
        seen["messages"] = messages
        return ConsolidatedMemoryDraft(
            title="Machine digest",
            summary="summary",
            sections=[ConsolidatedMemorySection(heading="Infra", body="Railway. (source: infra.md)")],
            source_paths=["infra.md"],
        )

    monkeypatch.setattr(OpenRouterClient, "preflight", fake_preflight)
    monkeypatch.setattr(OpenRouterClient, "parse", fake_parse)

    out = tmp_path / "digest.md"
    result = CliRunner().invoke(cli, ["memory", "digest", "--output", str(out), "--yes"])

    assert result.exit_code == 0, result.output
    assert out.exists()
    payload = "\n".join(str(m.get("content", "")) for m in seen["messages"])
    # Redaction at the transmitted-payload boundary: the secret never leaves.
    assert "AKIAIOSFODNN7EXAMPLE" not in payload
    assert "[REDACTED]" in payload
    # The durable fact and its source path are present for attribution.
    assert "We deploy on Railway." in payload
    assert "infra.md" in payload
    # The system prompt puts the renderer in inline-citation mode.
    system = "\n".join(str(m["content"]) for m in seen["messages"] if m.get("role") == "system")
    assert "inline citation" in system.lower()
    assert "em dash" in system.lower()


def test_entry_in_project_scoping_excludes_nested_and_siblings(tmp_path):
    target = (tmp_path / "workspace" / "repo").resolve()
    (tmp_path / "workspace" / "repo").mkdir(parents=True)
    ancestor = (tmp_path / "workspace").resolve()
    child = (tmp_path / "workspace" / "repo" / "private-child").resolve()
    sibling = (tmp_path / "workspace" / "other").resolve()

    # Global and the exact project are always in scope.
    assert _entry_in_project(_Entry("global"), target) is True
    assert _entry_in_project(_Entry("global:"), target) is True
    assert _entry_in_project(_Entry(f"project:{target}"), target) is True
    assert _entry_in_project(_Entry(f"team:{target}"), target) is True
    # Ancestor (parent workspace) context applies to the child project.
    assert _entry_in_project(_Entry(f"project:{ancestor}"), target) is True
    # A nested descendant project must NOT be swept into the digest.
    assert _entry_in_project(_Entry(f"project:{child}"), target) is False
    # A sibling project is out of scope.
    assert _entry_in_project(_Entry(f"project:{sibling}"), target) is False
