import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.memory.tree.store import TreeStore


def _plant_agent_memory(home, project_path):
    project = home / ".claude" / "projects" / "-Users-x-repo"
    memory = project / "memory"
    memory.mkdir(parents=True)
    (memory / "release.md").write_text("Production deploys run through Railway.\n")
    (project / "session.jsonl").write_text(json.dumps({"cwd": str(project_path)}) + "\n")


def test_ask_combines_curated_memory_and_agent_evidence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "memory.db"))
    TreeStore(project / ".docmancer" / "tree").write(
        relative_path="decisions/release.md",
        text="# Release policy\n\nProduction releases require a smoke test.\n",
        scope="project",
        project_id="repo",
        expect="absent",
    )

    result = CliRunner().invoke(
        cli,
        [
            "ask",
            "How do production releases deploy?",
            "--project",
            str(project),
            "--agent",
            "cursor",
            "--fresh",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any("smoke test" in row["excerpt"] for row in payload["curated_memory"])
    assert any("Railway" in row["excerpt"] for row in payload["relevant_evidence"])
    delivery = json.loads(
        (project / ".docmancer" / "state" / "delivery.json").read_text(encoding="utf-8")
    )
    assert delivery["agents"]["cursor"]["bundle_hash"]


def test_ask_marks_indexed_instruction_files_as_mandatory(tmp_path, monkeypatch):
    # A policy question is answerable from the instruction files the agents
    # already read, with no curation step. Recall must carry the `instructions`
    # kind through as mandatory authority, or the normative gate in the answer
    # path discards correct evidence and refuses.
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    (project / "CLAUDE.md").write_text(
        "# Security rules\n\nNEVER read .env files or any .env.* variant.\n"
    )
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "memory.db"))

    result = CliRunner().invoke(
        cli,
        [
            "ask",
            "What are my rules around env files?",
            "--project",
            str(project),
            "--fresh",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    env_rows = [row for row in payload["relevant_evidence"] if ".env" in row["excerpt"]]
    assert env_rows, payload["relevant_evidence"]
    assert any(row["authority"] == "mandatory" for row in env_rows)
    assert all(row["authority"] == "advisory" for row in payload["relevant_evidence"] if "Railway" in row["excerpt"])


def test_ask_reports_an_unreadable_recall_index_instead_of_reporting_no_memory(
    tmp_path, monkeypatch
):
    # A stale CLI against a newer index raises SchemaMismatchError on every
    # query. Swallowing it renders a dead index as "No relevant memory found.",
    # which is indistinguishable from an empty corpus and hides the one fact
    # that would fix it.
    from docmancer.memory import MemoryAgent, SchemaMismatchError

    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "memory.db"))

    def _raise(*args, **kwargs):
        raise SchemaMismatchError("this memory index predates memory atoms")

    monkeypatch.setattr(MemoryAgent, "query", _raise)

    result = CliRunner().invoke(
        cli,
        [
            "ask",
            "How do production releases deploy?",
            "--project",
            str(project),
            "--fresh",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "predates memory atoms" in (payload.get("recall_error") or "")

    text_result = CliRunner().invoke(
        cli, ["ask", "How do production releases deploy?", "--project", str(project)]
    )
    assert "predates memory atoms" in text_result.output
    assert "No relevant memory found." not in text_result.output


def test_ask_defaults_to_global_recall_across_projects(tmp_path, monkeypatch):
    # Agent memory belongs to `project`, but we ask from an unrelated directory
    # with no --project. Evidence recall must default to global and still find
    # it, instead of scoping to the current directory and returning nothing.
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    work = tmp_path / "elsewhere"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(home / ".docmancer" / "memory.db"))

    result = CliRunner().invoke(
        cli, ["ask", "How do production releases deploy?", "--fresh", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scoped_to_project"] is False
    assert any("Railway" in row["excerpt"] for row in payload["relevant_evidence"])


def test_ask_scopes_when_project_is_explicit(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "memory.db"))

    result = CliRunner().invoke(
        cli,
        ["ask", "How do production releases deploy?", "--project", str(project), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scoped_to_project"] is True


def test_ask_stays_within_token_budget(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    _plant_agent_memory(home, project)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "memory.db"))
    TreeStore(project / ".docmancer" / "tree").write(
        relative_path="decisions/release.md",
        text="# Release policy\n\n" + ("Production releases require a smoke test. " * 200),
        scope="project",
        project_id="repo",
        expect="absent",
    )

    result = CliRunner().invoke(
        cli,
        ["ask", "How do production releases deploy?", "--project", str(project),
         "--token-budget", "1500", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Large non-mandatory curated memory must not push the bundle over budget:
    # evidence is bounded, so the whole bundle honours the budget here.
    assert payload["within_budget"] is True
    assert payload["mandatory_overflow"] is False
    assert payload["token_estimate"] <= payload["token_budget"]


def test_ask_returns_both_adjacent_facts_from_one_file(tmp_path, monkeypatch):
    # The Wallet A / Wallet B regression: two adjacent facts in one file must
    # both survive into the evidence bundle, not just the higher-ranked one.
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    proj_mem = home / ".claude" / "projects" / "-Users-x-repo"
    memory = proj_mem / "memory"
    memory.mkdir(parents=True)
    (memory / "incident.md").write_text(
        "Wallet A borrowed 9.05 million dollars in the exploit window.\n"
        "Wallet B borrowed 1.01 million dollars in the exploit window.\n"
    )
    (proj_mem / "session.jsonl").write_text(json.dumps({"cwd": str(project)}) + "\n")
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "memory.db"))

    result = CliRunner().invoke(
        cli,
        [
            "ask",
            "how much did wallet A and wallet B borrow in the exploit",
            "--fresh",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    evidence = " ".join(row["excerpt"] for row in payload["relevant_evidence"])
    assert "Wallet A" in evidence
    assert "Wallet B" in evidence


def test_empty_ask_is_read_only_in_current_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(home / ".docmancer" / "memory.db"))

    result = CliRunner().invoke(cli, ["ask", "anything", "--json"])

    assert result.exit_code == 0, result.output
    assert not (work / ".docmancer").exists()


def test_ask_calls_answer_provider_without_refreshing_sources(tmp_path, monkeypatch):
    from docmancer.ai.provider_protocol import TextResult
    from docmancer.memory import MemoryAgent
    from docmancer.memory.ask import ask

    project = tmp_path / "repo"
    project.mkdir()
    TreeStore(project / ".docmancer" / "tree").write(
        relative_path="decisions/deploy.md",
        text="# Deploy\n\nProduction deploys use Railway.\n",
        scope="project",
        project_id="repo",
        expect="absent",
    )

    def forbidden_refresh(self):
        raise AssertionError("Ask scanned source files")

    monkeypatch.setattr(MemoryAgent, "refresh_if_changed", forbidden_refresh)
    monkeypatch.setattr(MemoryAgent, "query", lambda self, *args, **kwargs: [])

    class Provider:
        provider_name = "test"
        provider_id = "test"
        model = "test-model"
        timeout_ms = None
        supports_streaming = False

        def complete_text(self, messages, options, on_delta=None):
            text = "Production deploys use Railway [1]."
            if on_delta:
                on_delta(text)
            return TextResult(
                text=text,
                model=self.model,
                provider=self.provider_name,
            )

    result = ask(
        "How does production deploy?",
        project_path=project,
        answer_client=Provider(),
    )

    assert result["refresh"]["requested"] is False
    assert result["answer"]["text"] == "Production deploys use Railway [1]."
