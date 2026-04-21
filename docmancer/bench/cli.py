"""`docmancer bench` click group."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples


def _load_config_and_corpus(config_path: str | None):
    from docmancer.cli.commands import _effective_config, _load_config
    from docmancer.bench.backends.base import CorpusHandle
    from docmancer.bench.runner import compute_ingest_hash

    config = _load_config(_effective_config(config_path))
    corpus = CorpusHandle(
        db_path=str(config.index.db_path),
        ingest_hash="",
        extracted_dir=config.index.extracted_dir or None,
    )
    corpus.ingest_hash = compute_ingest_hash(corpus)
    return config, corpus


@click.group(
    "bench",
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Benchmark retrieval + reasoning backends locally.",
    epilog=format_examples(
        "docmancer bench init",
        "docmancer bench dataset create --from-corpus ./docs --size 30",
        "docmancer bench run --backend fts --dataset my-dataset",
        "docmancer bench compare run_a run_b",
    ),
)
def bench_group():
    """Compare FTS, Qdrant vector, and RLM backends on the same corpus."""


@bench_group.command("init", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_init_cmd(config_path: str | None):
    """Scaffold .docmancer/bench/{datasets,runs}/ under the current project."""
    from docmancer.cli.commands import _effective_config, _load_config

    config = _load_config(_effective_config(config_path))
    root = Path(config.bench.datasets_dir).parent
    (root / "datasets").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)
    click.echo(f"Initialized {root}/")


@bench_group.group("dataset", cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Manage bench datasets.")
def bench_dataset_group():
    """Create and validate bench datasets (YAML v1, legacy JSON supported)."""


@bench_dataset_group.command("validate", cls=DocmancerCommand)
@click.argument("path")
def bench_dataset_validate_cmd(path: str):
    """Validate a YAML or legacy JSON dataset against the v1 schema."""
    from docmancer.bench.dataset import load_dataset

    try:
        ds = load_dataset(path)
    except Exception as exc:
        click.echo(f"Invalid: {exc}", err=True)
        sys.exit(1)
    click.echo(f"OK: version={ds.version} questions={len(ds.questions)} corpus_ref={ds.corpus_ref}")


@bench_dataset_group.command("create", cls=DocmancerCommand)
@click.option("--from-corpus", "from_corpus", default=None, help="Directory of markdown docs to scaffold from.")
@click.option("--from-legacy", "from_legacy", default=None, help="Legacy eval_dataset.json to convert.")
@click.option("--size", default=30, show_default=True, type=int, help="Max entries to sample.")
@click.option("--name", default=None, help="Dataset name (directory under datasets/).")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_dataset_create_cmd(from_corpus, from_legacy, size, name, config_path):
    """Scaffold a new YAML dataset from a corpus or legacy JSON."""
    from docmancer.bench.dataset import (
        BenchDataset,
        generate_scaffold_from_corpus_dir,
        load_dataset,
    )
    from docmancer.cli.commands import _effective_config, _load_config

    if not (from_corpus or from_legacy):
        click.echo("Provide --from-corpus <dir> or --from-legacy <path.json>.", err=True)
        sys.exit(1)
    if from_corpus and from_legacy:
        click.echo("Pass only one of --from-corpus / --from-legacy.", err=True)
        sys.exit(1)

    config = _load_config(_effective_config(config_path))
    datasets_dir = Path(config.bench.datasets_dir)

    if from_corpus:
        ds = generate_scaffold_from_corpus_dir(Path(from_corpus), max_entries=size)
        out_name = name or Path(from_corpus).name.strip("/") or "dataset"
    else:
        ds = load_dataset(from_legacy)
        if ds.version != 1:
            ds = BenchDataset(version=1, corpus_ref=ds.corpus_ref, questions=ds.questions, metadata=ds.metadata)
        out_name = name or "legacy"

    out_dir = datasets_dir / out_name
    out_path = out_dir / "dataset.yaml"
    ds.save_yaml(out_path)
    if from_corpus:
        click.echo(
            f"Wrote {len(ds.questions)} heuristic question(s) to {out_path}\n"
            f"Questions are derived from markdown headings and are intentionally shallow. "
            f"Edit the YAML to refine them or add 'expected_answer' fields before running "
            f"'docmancer bench run'."
        )
    else:
        click.echo(f"Wrote {len(ds.questions)} questions to {out_path}")


@bench_group.command("run", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--backend", required=True, type=click.Choice(["fts", "qdrant", "rlm"], case_sensitive=False))
@click.option("--dataset", required=True, help="Dataset name under datasets/ or full path to .yaml/.json.")
@click.option("--run-id", "run_id", default=None, help="Run directory name. Default: <backend>_<timestamp>.")
@click.option("--k-retrieve", "k_retrieve", default=None, type=int)
@click.option("--k-answer", "k_answer", default=None, type=int)
@click.option("--timeout-s", "timeout_s", default=None, type=float)
@click.option("--sandbox", default=None, help="RLM only: local (default) or docker.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_run_cmd(backend, dataset, run_id, k_retrieve, k_answer, timeout_s, sandbox, config_path):
    """Run a dataset against one backend and write artifacts."""
    from docmancer.bench.backends import get_backend
    from docmancer.bench.dataset import load_dataset
    from docmancer.bench.runner import run_bench

    backend_name = backend.lower()
    try:
        backend_obj = get_backend(backend_name)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc))

    config, corpus = _load_config_and_corpus(config_path)

    dataset_path = Path(dataset)
    if not dataset_path.exists():
        dataset_path = Path(config.bench.datasets_dir) / dataset / "dataset.yaml"
    if not dataset_path.exists():
        raise click.ClickException(f"Dataset not found: {dataset}")

    ds = load_dataset(dataset_path)

    k_retrieve = k_retrieve or config.bench.backends.k_retrieve
    k_answer = k_answer or config.bench.backends.k_answer
    if timeout_s is None:
        timeout_s = {
            "fts": config.bench.backends.timeout_s_fts,
            "qdrant": config.bench.backends.timeout_s_qdrant,
            "rlm": config.bench.backends.timeout_s_rlm,
        }[backend_name]

    extra: dict = {}
    if backend_name == "rlm" and sandbox:
        extra["sandbox"] = sandbox

    if not run_id:
        run_id = f"{backend_name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

    run_dir = run_bench(
        ds,
        backend_obj,
        corpus,
        runs_dir=Path(config.bench.runs_dir),
        run_id=run_id,
        k_retrieve=k_retrieve,
        k_answer=k_answer,
        timeout_s=timeout_s,
        backend_extra=extra,
    )
    click.echo(f"Wrote run artifacts to {run_dir}")


@bench_group.command("compare", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.argument("run_ids", nargs=-1, required=True)
@click.option("--output", default=None, help="Path to write comparison markdown. Defaults to stdout.")
@click.option("--allow-mixed-ingest", is_flag=True, default=False, help="Allow comparing runs across different ingest hashes.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_compare_cmd(run_ids, output, allow_mixed_ingest, config_path):
    """Compare two or more bench runs and emit a side-by-side report."""
    from docmancer.bench.report import load_run_metrics, render_comparison_markdown
    from docmancer.cli.commands import _effective_config, _load_config

    if len(run_ids) < 2:
        raise click.ClickException("bench compare needs at least 2 run_ids.")

    config = _load_config(_effective_config(config_path))
    runs_dir = Path(config.bench.runs_dir)

    runs = []
    for rid in run_ids:
        rdir = runs_dir / rid
        if not rdir.exists():
            rdir = Path(rid)
        if not rdir.exists():
            raise click.ClickException(f"Run not found: {rid}")
        metrics, snap = load_run_metrics(rdir)
        runs.append((rid, metrics, snap))

    hashes = {m.ingest_hash for _, m, _ in runs}
    if len(hashes) > 1 and not allow_mixed_ingest:
        raise click.ClickException(
            f"Runs use different ingest hashes ({', '.join(h[:8] for h in hashes)}). "
            "Pass --allow-mixed-ingest to compare anyway."
        )
    ks = {(m.k_retrieve, m.k_answer) for _, m, _ in runs}
    if len(ks) > 1:
        click.echo(f"Warning: runs use different k values: {ks}", err=True)

    md = render_comparison_markdown(runs)
    if output:
        Path(output).write_text(md, encoding="utf-8")
        click.echo(f"Wrote {output}")
    else:
        click.echo(md)


@bench_group.command("report", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.argument("run_id")
@click.option("--format", "output_format", type=click.Choice(["markdown", "json"], case_sensitive=False), default="markdown")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_report_cmd(run_id, output_format, config_path):
    """Print or regenerate a report for a single run."""
    from docmancer.bench.report import load_run_metrics, render_single_run_markdown
    from docmancer.cli.commands import _effective_config, _load_config

    config = _load_config(_effective_config(config_path))
    runs_dir = Path(config.bench.runs_dir)
    rdir = runs_dir / run_id
    if not rdir.exists():
        rdir = Path(run_id)
    if not rdir.exists():
        raise click.ClickException(f"Run not found: {run_id}")
    metrics, snap = load_run_metrics(rdir)

    if output_format == "json":
        click.echo(json.dumps(metrics.to_dict(), indent=2))
    else:
        click.echo(render_single_run_markdown(metrics, snap))


@bench_group.command("list", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_list_cmd(config_path):
    """List local datasets and runs."""
    from docmancer.cli.commands import _effective_config, _load_config

    config = _load_config(_effective_config(config_path))
    datasets_dir = Path(config.bench.datasets_dir)
    runs_dir = Path(config.bench.runs_dir)

    click.echo("Datasets:")
    if datasets_dir.exists():
        for p in sorted(datasets_dir.iterdir()):
            if p.is_dir() and (p / "dataset.yaml").exists():
                click.echo(f"  {p.name}  {p / 'dataset.yaml'}")
    click.echo("Runs:")
    if runs_dir.exists():
        for p in sorted(runs_dir.iterdir()):
            if p.is_dir() and (p / "metrics.json").exists():
                click.echo(f"  {p.name}")
