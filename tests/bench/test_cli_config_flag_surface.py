"""Every `docmancer bench ...` subcommand must accept --config.

The live integration script passes --config <path> to every bench subcommand
to run against an isolated docmancer.yaml. When a new subcommand forgets to
add --config, the integration run aborts mid-way (see
scripts/live_cli_integration_20260421_143958.log line 1657).
"""

from __future__ import annotations

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


_BENCH_SUBCOMMANDS_WITH_CONFIG = [
    # (argv tokens that should be accepted, ignoring whether they succeed)
    ("bench", "init", "--config", "/does/not/exist.yaml"),
    ("bench", "dataset", "list-builtin", "--config", "/does/not/exist.yaml"),
    ("bench", "dataset", "validate", "/dev/null", "--config", "/does/not/exist.yaml"),
    ("bench", "list", "--config", "/does/not/exist.yaml"),
    ("bench", "remove", "x", "--config", "/does/not/exist.yaml"),
    ("bench", "reset", "--config", "/does/not/exist.yaml"),
]


def test_every_bench_subcommand_accepts_config_flag():
    runner = CliRunner()
    for argv in _BENCH_SUBCOMMANDS_WITH_CONFIG:
        result = runner.invoke(cli, list(argv))
        combined = (result.output or "") + (result.stderr or "")
        # The commands may fail for other reasons (missing file, etc.) but
        # must NOT fail with "No such option: --config".
        assert "No such option: --config" not in combined, (
            f"{' '.join(argv)} rejected --config; add the option to the command.\n"
            f"Output was:\n{combined}"
        )
