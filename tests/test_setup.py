from click.testing import CliRunner
from docmancer.cli.__main__ import cli


def test_setup_writes_config(tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "docmancer.yaml"
    # Pipe input: yes to LLM, anthropic, fake-key, default model, no to langfuse
    result = runner.invoke(cli, ["setup", "--config", str(config_path)], input="y\nanthropic\nsk-fake-key\nclaude-sonnet-4-20250514\nn\nn\n")
    assert result.exit_code == 0
    assert config_path.exists()

    import yaml
    with open(config_path) as f:
        data = yaml.safe_load(f)
    assert data["llm"]["provider"] == "anthropic"
    assert data["llm"]["api_key"] == "sk-fake-key"


def test_setup_skip_all(tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "docmancer.yaml"
    result = runner.invoke(cli, ["setup", "--config", str(config_path)], input="n\nn\nn\n")
    assert result.exit_code == 0
    assert "skipped" in result.output.lower()
