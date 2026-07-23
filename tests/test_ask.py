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
