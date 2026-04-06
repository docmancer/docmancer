from __future__ import annotations

import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.eval.dataset import generate_scaffold


def test_generate_scaffold_uses_vault_relative_source_refs(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / ".docmancer").mkdir(parents=True)
    raw_dir = vault_root / "raw"
    raw_dir.mkdir()
    (raw_dir / "doc.md").write_text("# Title\n\nBody text.", encoding="utf-8")

    dataset = generate_scaffold(raw_dir)

    assert dataset.entries[0].source_refs == ["raw/doc.md"]


def test_generate_scaffold_skips_auto_generated_vault_files(tmp_path):
    vault_root = tmp_path / "vault"
    (vault_root / ".docmancer").mkdir(parents=True)
    wiki_dir = vault_root / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "_index.md").write_text("# Index\n\nAuto-generated.", encoding="utf-8")
    (wiki_dir / "_graph.md").write_text("# Graph\n\nAuto-generated.", encoding="utf-8")
    (wiki_dir / "guide.md").write_text("# Guide\n\nReal content.", encoding="utf-8")

    dataset = generate_scaffold(wiki_dir)

    assert len(dataset.entries) == 1
    assert dataset.entries[0].source_refs == ["wiki/guide.md"]


def test_eval_command_writes_latest_result_cache(tmp_path, monkeypatch):
    dataset_path = tmp_path / ".docmancer" / "eval_dataset.json"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(json.dumps({
        "entries": [{
            "question": "What is auth?",
            "expected_answer": "Auth is login.",
            "expected_context": ["Auth is login."],
            "source_refs": ["raw/doc.md"],
            "tags": [],
        }],
        "metadata": {},
    }), encoding="utf-8")

    class _Result:
        source = "raw/doc.md"
        text = "Auth is login."
        score = 1.0

    class _FakeAgent:
        def __init__(self, config=None):
            self.config = config

        def query(self, text, limit=None):
            return [_Result()]

    monkeypatch.setattr("docmancer.cli.commands._get_agent_class", lambda: _FakeAgent)

    runner = CliRunner()
    result = runner.invoke(cli, ["eval", "--dataset", str(dataset_path)])
    assert result.exit_code == 0

    latest_result = tmp_path / ".docmancer" / "eval" / "latest_result.json"
    assert latest_result.exists()
    payload = json.loads(latest_result.read_text(encoding="utf-8"))
    assert payload["mrr"] == 1.0
    assert payload["hit_rate"] == 1.0


def test_eval_command_reports_how_to_fix_empty_dataset(tmp_path):
    dataset_path = tmp_path / ".docmancer" / "eval_dataset.json"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(json.dumps({
        "entries": [{
            "question": "",
            "expected_answer": "",
            "expected_context": ["Context"],
            "source_refs": ["wiki/guide.md"],
            "tags": [],
        }],
        "metadata": {},
    }), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["eval", "--dataset", str(dataset_path)])
    assert result.exit_code != 0
    assert "no entries with questions found" in result.output
    assert "Fill in at least one 'question' field" in result.output
