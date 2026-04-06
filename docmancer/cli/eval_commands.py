from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, HELP_CONTEXT_SETTINGS, format_examples


def _default_eval_cache_path(dataset_path: Path, config_path: str | None) -> Path:
    if dataset_path.parent.name == ".docmancer":
        return dataset_path.parent / "eval" / "latest_result.json"
    if config_path:
        return Path(config_path).resolve().parent / ".docmancer" / "eval" / "latest_result.json"
    return Path(".docmancer") / "eval" / "latest_result.json"


@click.command(
    "generate",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Generate a golden eval dataset scaffold.",
    epilog=format_examples(
        "docmancer dataset generate --source ./docs",
        "docmancer dataset generate --source ./raw --count 30",
    ),
)
@click.option("--source", required=True, help="Source directory to generate dataset from.")
@click.option("--output", default=None, help="Output path (default: .docmancer/eval_dataset.json).")
@click.option("--count", default=50, type=int, help="Max entries to generate.")
@click.option("--llm", is_flag=True, default=False, help="Use LLM to generate Q&A pairs (requires API key).")
def dataset_generate_cmd(source: str, output: str | None, count: int, llm: bool):
    """Generate a golden dataset scaffold from source documents."""
    from docmancer.eval.dataset import generate_scaffold

    source_path = Path(source)
    if not source_path.is_dir():
        click.echo(f"Error: source directory not found: {source}", err=True)
        sys.exit(1)

    if llm:
        from docmancer.connectors.llm.provider import get_llm_provider
        from docmancer.core.config import DocmancerConfig

        # Try to load config for LLM settings
        config = DocmancerConfig()
        config_file = Path("docmancer.yaml")
        if config_file.exists():
            config = DocmancerConfig.from_yaml(config_file)

        provider = get_llm_provider(config)
        if provider is None:
            click.echo("  LLM features require an API key.")
            click.echo("  Run 'docmancer setup' to configure, or set ANTHROPIC_API_KEY.")
            click.echo("  Falling back to manual scaffold mode.")
            click.echo()
        else:
            from docmancer.eval.dataset import generate_with_llm
            dataset = generate_with_llm(source_path, provider, max_entries=count)
            output_path = Path(output) if output else Path(".docmancer/eval_dataset.json")
            dataset.save(output_path)
            click.echo(f"  Generated {len(dataset.entries)} Q&A pairs via LLM")
            click.echo(f"  Saved to: {output_path}")
            return

    dataset = generate_scaffold(source_path, max_entries=count)

    output_path = Path(output) if output else Path(".docmancer/eval_dataset.json")
    dataset.save(output_path)

    click.echo(f"  Generated {len(dataset.entries)} entries")
    click.echo(f"  Saved to: {output_path}")
    click.echo()
    click.echo("  Fill in 'question' and 'expected_answer' fields, then run 'docmancer eval'.")


@click.command(
    "eval",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Evaluate retrieval quality against a golden dataset.",
    epilog=format_examples(
        "docmancer eval --dataset .docmancer/eval_dataset.json",
        "docmancer eval --dataset eval.json --output report.md",
        "docmancer eval --dataset eval.json --output report.csv",
    ),
)
@click.option("--dataset", required=True, help="Path to eval dataset JSON.")
@click.option("--output", default=None, help="Output path for report (.md or .csv).")
@click.option("--limit", "k", default=5, type=int, help="Top-K results to evaluate.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.option("--judge", is_flag=True, default=False, help="Enable LLM-as-judge scoring (requires API key).")
def eval_cmd(dataset: str, output: str | None, k: int, config_path: str | None, judge: bool):
    """Run evaluation pipeline against a golden dataset."""
    from docmancer.cli.commands import _effective_config, _load_config, _get_agent_class
    from docmancer.eval.dataset import EvalDataset
    from docmancer.eval.runner import run_eval
    from docmancer.eval.report import format_terminal, format_markdown, format_csv

    dataset_path = Path(dataset)
    if not dataset_path.exists():
        click.echo(f"Error: dataset not found: {dataset}", err=True)
        sys.exit(1)

    ds = EvalDataset.load(dataset_path)
    filled = [e for e in ds.entries if e.question]
    if not filled:
        click.echo("Error: no entries with questions found in dataset.", err=True)
        sys.exit(1)

    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)

    click.echo(f"  Running eval with {len(filled)} queries (k={k})...")

    result = run_eval(ds, query_fn=agent.query, k=k)

    # Config snapshot for report
    config_snap = {
        "chunk_size": config.ingestion.chunk_size,
        "chunk_overlap": config.ingestion.chunk_overlap,
        "embedding_model": config.embedding.model,
        "retrieval_limit": k,
    }

    # LLM-as-judge scoring
    judge_result = None
    if judge:
        import os
        api_key = os.environ.get("OPENAI_API_KEY") or ""
        if not api_key and config.llm:
            api_key = config.llm.api_key
        judge_provider = "openai"
        if config.eval and config.eval.judge_provider:
            judge_provider = config.eval.judge_provider

        if not api_key:
            click.echo("  LLM-as-judge requires an API key.")
            click.echo("  Run 'docmancer setup' to configure, or set OPENAI_API_KEY.")
            click.echo("  Showing deterministic metrics only.")
            click.echo()
        else:
            from docmancer.eval.judge import ragas_available, run_judge_eval
            if not ragas_available():
                click.echo("  Ragas not installed. Run: pip install docmancer[ragas]")
                click.echo("  Showing deterministic metrics only.")
                click.echo()
            else:
                click.echo("  Running LLM-as-judge scoring...")
                judge_result = run_judge_eval(
                    ds, query_fn=agent.query, k=k,
                    api_key=api_key, provider=judge_provider,
                )

    click.echo(format_terminal(result, config_snapshot=config_snap, judge_result=judge_result))

    cache_path = _default_eval_cache_path(dataset_path, config_path)
    cache_payload = {
        **result.to_dict(),
        "config_snapshot": config_snap,
    }
    if judge_result is not None:
        cache_payload["judge_result"] = judge_result.to_dict()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache_payload, indent=2), encoding="utf-8")

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix == ".csv":
            output_path.write_text(
                format_csv(result, judge_result=judge_result), encoding="utf-8",
            )
        else:
            output_path.write_text(
                format_markdown(result, config_snapshot=config_snap, judge_result=judge_result),
                encoding="utf-8",
            )
        click.echo(f"\n  Report saved to: {output_path}")
