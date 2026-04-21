"""`docmancer bench` click group."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples


_CORPUS_SOURCE_SUFFIXES = {".md", ".txt"}


def _normalize_source_value(value: str | Path) -> str:
    return str(value).replace("\\", "/")


def _corpus_expected_sources(corpus_root: Path) -> set[str]:
    if corpus_root.is_file():
        return {_normalize_source_value(corpus_root)}
    if not corpus_root.is_dir():
        return set()
    return {
        _normalize_source_value(path)
        for path in sorted(corpus_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in _CORPUS_SOURCE_SUFFIXES
    }


def _corpus_fully_indexed(corpus_root: Path, existing_sources: list[str]) -> bool:
    expected = _corpus_expected_sources(corpus_root)
    if not expected:
        return False
    existing_norm = {_normalize_source_value(src) for src in existing_sources}
    return expected.issubset(existing_norm)


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
        "docmancer bench dataset use lenny",
        "docmancer bench dataset create --from-corpus ./docs --size 30 --provider auto",
        "docmancer bench run --backend fts --dataset lenny",
        "docmancer bench compare run_a run_b",
    ),
)
def bench_group():
    """Compare retrieval and answer quality across local bench backends.

    Use built-in datasets such as `lenny` for a zero-config first run, or
    create your own dataset from a local markdown corpus. Every run writes
    metrics and artifacts under `.docmancer/bench/runs/` so you can report,
    compare, and remove them later.
    """


@bench_group.command(
    "init",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Create local bench datasets/ and runs/ folders.",
    epilog=format_examples(
        "docmancer bench init",
        "docmancer bench init --config ./docmancer.yaml",
    ),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_init_cmd(config_path: str | None):
    """Create the local bench workspace under the current project.

    This prepares `.docmancer/bench/datasets/` and `.docmancer/bench/runs/`.
    Run it once before creating datasets or bench runs in a new repo.
    """
    from docmancer.cli.commands import _effective_config, _load_config

    config = _load_config(_effective_config(config_path))
    root = Path(config.bench.datasets_dir).parent
    (root / "datasets").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)
    click.echo(f"Initialized {root}/")


@bench_group.group(
    "dataset",
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Create, validate, and install bench datasets.",
    epilog=format_examples(
        "docmancer bench dataset list-builtin",
        "docmancer bench dataset use lenny",
        "docmancer bench dataset create --from-corpus ./docs --size 30 --provider auto",
        "docmancer bench dataset validate .docmancer/bench/datasets/mydocs/dataset.yaml",
    ),
)
def bench_dataset_group():
    """Manage benchmark datasets used by `docmancer bench run`.

    Datasets are stored as YAML under `.docmancer/bench/datasets/`. You can
    use a built-in dataset, scaffold one from local markdown files, or validate
    an existing YAML or legacy JSON dataset before running a benchmark.
    """


@bench_dataset_group.command(
    "validate",
    cls=DocmancerCommand,
    short_help="Validate a bench dataset file.",
    epilog=format_examples(
        "docmancer bench dataset validate .docmancer/bench/datasets/lenny/dataset.yaml",
        "docmancer bench dataset validate ./eval_dataset.json",
    ),
)
@click.argument("path")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_dataset_validate_cmd(path: str, config_path: str | None):
    """Validate a bench dataset before running it.

    Accepts YAML v1 datasets and legacy JSON datasets. This is useful after
    editing a generated dataset by hand or converting an older eval dataset.
    """
    del config_path  # accepted for interface symmetry with other bench commands
    from docmancer.bench.dataset import load_dataset

    try:
        ds = load_dataset(path)
    except Exception as exc:
        click.echo(f"Invalid: {exc}", err=True)
        sys.exit(1)
    click.echo(f"OK: version={ds.version} questions={len(ds.questions)} corpus_ref={ds.corpus_ref}")


_PROVIDER_CHOICES = ["auto", "anthropic", "openai", "gemini", "ollama", "heuristic"]


@bench_dataset_group.command(
    "create",
    cls=DocmancerCommand,
    short_help="Create a dataset from markdown docs or legacy JSON.",
    epilog=format_examples(
        "docmancer bench dataset create --from-corpus ./docs --size 30 --name mydocs --provider auto",
        "docmancer bench dataset create --from-corpus ./docs --provider heuristic",
        "docmancer bench dataset create --from-legacy .docmancer/eval_dataset.json --name migrated",
    ),
)
@click.option("--from-corpus", "from_corpus", default=None, help="Directory of markdown docs to scaffold from.")
@click.option("--from-legacy", "from_legacy", default=None, help="Legacy eval_dataset.json to convert.")
@click.option("--size", default=30, show_default=True, type=int, help="Max entries to sample.")
@click.option("--name", default=None, help="Dataset name (directory under datasets/).")
@click.option(
    "--provider",
    type=click.Choice(_PROVIDER_CHOICES, case_sensitive=False),
    default="auto",
    show_default=True,
    help="LLM provider for question generation, or 'heuristic' for shallow heading-based questions.",
)
@click.option("--model", default=None, help="Override the provider's default model.")
@click.option(
    "--questions-per-file",
    "questions_per_file",
    default=3,
    show_default=True,
    type=int,
    help="How many questions the LLM is asked to draft per source file.",
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_dataset_create_cmd(from_corpus, from_legacy, size, name, provider, model, questions_per_file, config_path):
    """Scaffold a new YAML dataset from a corpus or legacy JSON.

    With --from-corpus and an LLM provider configured, questions are
    generated with the LLM and include expected_answer fields. Without a
    provider, pass --provider heuristic for the legacy heading-based path.
    """
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
        ds = _dataset_from_corpus(
            Path(from_corpus),
            size=size,
            provider_choice=provider.lower(),
            model=model,
            questions_per_file=questions_per_file,
        )
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
        mode = ds.metadata.get("mode", "heuristic")
        if mode == "heuristic":
            click.echo(
                f"Wrote {len(ds.questions)} heuristic question(s) to {out_path}\n"
                f"Questions are derived from markdown headings and are intentionally shallow. "
                f"Edit the YAML to refine them or add 'expected_answer' fields, or re-run "
                f"with --provider auto once an LLM key is set."
            )
        else:
            click.echo(
                f"Wrote {len(ds.questions)} LLM-generated question(s) to {out_path} "
                f"(provider={ds.metadata.get('provider')}, model={ds.metadata.get('model')})."
            )
    else:
        click.echo(f"Wrote {len(ds.questions)} questions to {out_path}")


def _dataset_from_corpus(corpus_dir: Path, *, size: int, provider_choice: str, model: str | None, questions_per_file: int):
    """Build a BenchDataset from a corpus directory, dispatching on --provider."""
    from docmancer.bench.dataset import BenchDataset, generate_scaffold_from_corpus_dir
    from docmancer.bench.llm_providers import (
        ProviderUnavailableError,
        available_providers,
        detect_provider,
        get_generator,
        no_provider_message,
    )
    from docmancer.bench.question_gen import generate_questions_llm

    if provider_choice == "heuristic":
        return generate_scaffold_from_corpus_dir(corpus_dir, max_entries=size)

    if provider_choice == "auto":
        candidates = available_providers()
        if not candidates:
            click.echo(no_provider_message(), err=True)
            sys.exit(2)
        # Try each env-detected provider in order; skip any whose SDK is
        # not installed. Users often have a key set for a provider whose
        # Python SDK is in a different venv.
        generator = None
        provider_name = ""
        skipped: list[str] = []
        for candidate in candidates:
            try:
                generator = get_generator(candidate, model=model)
                provider_name = candidate
                break
            except ProviderUnavailableError as exc:
                skipped.append(f"{candidate}: {exc}")
        if generator is None:
            click.echo(
                "All auto-detected providers failed to initialize:\n  "
                + "\n  ".join(skipped)
                + "\n\nInstall SDKs with: pipx inject docmancer 'docmancer[llm]'\n"
                "Or pass --provider heuristic to skip LLM generation.",
                err=True,
            )
            sys.exit(2)
        if skipped:
            click.echo(
                "Skipped providers with missing SDKs: "
                + ", ".join(s.split(":", 1)[0] for s in skipped)
            )
        click.echo(f"Using provider: {provider_name} (auto-detected from env).")
    else:
        provider_name = provider_choice
        try:
            generator = get_generator(provider_name, model=model)
        except ProviderUnavailableError as exc:
            click.echo(f"Provider '{provider_name}' unavailable: {exc}", err=True)
            sys.exit(2)

    click.echo(f"Generating up to {size} questions from {corpus_dir} ...")
    questions = generate_questions_llm(
        corpus_dir,
        generator=generator,
        size=size,
        questions_per_file=questions_per_file,
    )
    ds = BenchDataset(
        version=1,
        corpus_ref=str(corpus_dir),
        questions=questions,
        metadata={
            "generated_from": str(corpus_dir),
            "mode": "llm",
            "provider": provider_name,
            "model": model or "",
        },
    )
    return ds


@bench_dataset_group.command(
    "use",
    cls=DocmancerCommand,
    short_help="Fetch and install a built-in dataset such as lenny.",
    epilog=format_examples(
        "docmancer bench dataset use lenny",
        "docmancer bench dataset use lenny --yes",
        "docmancer bench dataset use lenny --refresh",
        "docmancer bench dataset use lenny --no-ingest",
    ),
)
@click.argument("name")
@click.option("--refresh", is_flag=True, default=False, help="Force re-fetch even if the corpus is already cached.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Pre-accept the corpus license non-interactively.")
@click.option("--no-ingest", is_flag=True, default=False, help="Skip ingesting the corpus into the docmancer index.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_dataset_use_cmd(name, refresh, yes, no_ingest, config_path):
    """Install a built-in benchmark dataset (e.g. `docmancer bench dataset use lenny`).

    Fetches the corpus on first use and caches it under
    ~/.docmancer/bench/corpora/<name>/. Subsequent invocations reuse the
    cache and make zero network calls; pass --refresh to force a re-fetch.

    Also ingests the corpus into the docmancer index so `bench run` can
    retrieve from it. Skip with --no-ingest if you plan to ingest yourself.
    """
    from docmancer.bench.corpora import BUILTIN_CORPORA, is_fetched, resolve_corpus
    from docmancer.bench.dataset import load_dataset
    from docmancer.cli.commands import _effective_config, _load_config, _get_agent_class

    if name not in BUILTIN_CORPORA:
        available = ", ".join(sorted(BUILTIN_CORPORA)) or "(none)"
        raise click.ClickException(f"Unknown built-in dataset {name!r}. Available: {available}")

    config = _load_config(_effective_config(config_path))
    datasets_dir = Path(config.bench.datasets_dir)

    cached = is_fetched(name) and not refresh
    try:
        corpus_root = resolve_corpus(
            name,
            accept_license=True if yes else None,
            refresh=refresh,
            echo=lambda msg: click.echo(msg),
            confirm=None if yes else (lambda prompt: click.confirm(prompt, default=False)),
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc))

    if cached:
        click.echo(f"Corpus '{name}' already cached at {corpus_root} (no network call).")

    bundled = _bundled_dataset_path(name)
    if bundled is None or not bundled.exists():
        raise click.ClickException(
            f"Bundled dataset YAML for {name!r} is missing from the package."
        )

    ds = load_dataset(bundled)
    ds.corpus_ref = str(corpus_root)
    out_path = datasets_dir / name / "dataset.yaml"
    ds.save_yaml(out_path)

    ingested_note = ""
    if not no_ingest:
        agent = _get_agent_class()(config=config)
        existing = agent.list_sources()
        corpus_str = str(corpus_root)
        already_ingested = _corpus_fully_indexed(corpus_root, existing)
        if already_ingested and not refresh:
            ingested_note = f"Corpus already indexed (skipping re-ingest).\n"
        else:
            click.echo(f"Ingesting corpus into docmancer index at {config.index.db_path} ...")
            try:
                count = agent.add(corpus_str, recreate=False)
                ingested_note = (
                    f"Ingested {count} sections into the index.\n"
                    f"To remove later: docmancer remove {corpus_str}\n"
                )
            except Exception as exc:
                ingested_note = (
                    f"WARNING: auto-ingest failed: {exc}\n"
                    f"Run manually: docmancer add {corpus_str}\n"
                )
    else:
        ingested_note = (
            f"Skipped ingest (--no-ingest). Run manually before bench:\n"
            f"  docmancer add {corpus_root}\n"
        )

    click.echo(
        f"\nDataset '{name}' ready: {len(ds.questions)} questions at {out_path}\n"
        f"Corpus at {corpus_root}\n"
        f"{ingested_note}"
        f"Next: docmancer bench run --dataset {name} --backend fts"
    )


def _bundled_dataset_path(name: str) -> Path | None:
    """Locate the bundled dataset YAML for a built-in corpus."""
    from importlib import resources

    try:
        pkg = resources.files(f"docmancer.bench.data.{name}")
        candidate = pkg / "dataset.yaml"
        if candidate.is_file():
            return Path(str(candidate))
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        pass
    fallback = Path(__file__).parent / "data" / name / "dataset.yaml"
    return fallback if fallback.exists() else None


@bench_dataset_group.command(
    "list-builtin",
    cls=DocmancerCommand,
    short_help="List packaged datasets available via `dataset use`.",
    epilog=format_examples(
        "docmancer bench dataset list-builtin",
    ),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_dataset_list_builtin_cmd(config_path: str | None):
    """List built-in datasets shipped with docmancer.

    This shows what can be installed with `docmancer bench dataset use`,
    whether the corpus is already cached locally, and the source/license links.
    """
    del config_path  # accepted for interface symmetry with other bench commands
    from docmancer.bench.corpora import is_fetched, list_builtin

    items = list_builtin()
    if not items:
        click.echo("(no built-in datasets registered)")
        return
    for spec in items:
        status = "cached" if is_fetched(spec.name) else "not fetched"
        click.echo(f"{spec.name}  [{status}]")
        click.echo(f"  {spec.description}")
        click.echo(f"  source: {spec.git_url}")
        click.echo(f"  license: {spec.license_url}")


@bench_group.command(
    "run",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Run one backend against one dataset and write artifacts.",
    epilog=format_examples(
        "docmancer bench run --backend fts --dataset lenny --run-id lenny_fts",
        "docmancer bench run --backend qdrant --dataset lenny --run-id lenny_qdrant",
        "docmancer bench run --backend rlm --dataset lenny --run-id lenny_rlm --rlm-provider vllm",
    ),
)
@click.option("--backend", required=True, type=click.Choice(["fts", "qdrant", "rlm"], case_sensitive=False))
@click.option("--dataset", required=True, help="Dataset name under datasets/ or full path to .yaml/.json.")
@click.option("--run-id", "run_id", default=None, help="Run directory name. Default: <backend>_<timestamp>.")
@click.option("--k-retrieve", "k_retrieve", default=None, type=int, help="How many chunks to retrieve before scoring.")
@click.option("--k-answer", "k_answer", default=None, type=int, help="How many retrieved chunks to pass into answer generation.")
@click.option("--timeout-s", "timeout_s", default=None, type=float, help="Per-question timeout in seconds for the selected backend.")
@click.option("--sandbox", default=None, help="RLM only: execution environment (local, docker, modal, prime, daytona, e2b).")
@click.option("--rlm-provider", "rlm_provider", default=None,
              help="RLM only: override provider (anthropic, openai, gemini, azure_openai, openrouter, portkey, vercel, vllm, litellm).")
@click.option("--rlm-model", "rlm_model", default=None, help="RLM only: override the provider's default model.")
@click.option("--rlm-max-chars", "rlm_max_chars", default=None, type=int,
              help="RLM only: cap the corpus fed to the model (default 120000).")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_run_cmd(backend, dataset, run_id, k_retrieve, k_answer, timeout_s, sandbox, rlm_provider, rlm_model, rlm_max_chars, config_path):
    """Execute one benchmark run and save metrics under `.docmancer/bench/runs/`.

    The dataset can be a dataset name under `.docmancer/bench/datasets/` or a
    direct path to a YAML or legacy JSON file. Use `bench report` for a single
    run summary and `bench compare` to compare multiple runs side by side.
    """
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
    if backend_name == "rlm":
        # Precedence: CLI flag > bench config value > (unset; backend picks default).
        cfg_backends = config.bench.backends
        effective_sandbox = sandbox or cfg_backends.__dict__.get("sandbox") or None
        if effective_sandbox:
            extra["sandbox"] = effective_sandbox
        effective_provider = rlm_provider or cfg_backends.rlm_provider or ""
        if effective_provider:
            extra["rlm_provider"] = effective_provider
        effective_model = rlm_model or cfg_backends.rlm_model or ""
        if effective_model:
            extra["rlm_model"] = effective_model
        effective_max_chars = rlm_max_chars or cfg_backends.rlm_max_chars
        if effective_max_chars:
            extra["rlm_max_chars"] = effective_max_chars

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


@bench_group.command(
    "compare",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Compare two or more saved bench runs.",
    epilog=format_examples(
        "docmancer bench compare lenny_fts lenny_qdrant",
        "docmancer bench compare lenny_fts lenny_qdrant lenny_rlm",
        "docmancer bench compare run_a run_b --allow-mixed-ingest",
    ),
)
@click.argument("run_ids", nargs=-1, required=True)
@click.option("--output", default=None, help="Path to write comparison markdown. Defaults to stdout.")
@click.option("--allow-mixed-ingest", is_flag=True, default=False, help="Allow comparing runs across different ingest hashes.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_compare_cmd(run_ids, output, allow_mixed_ingest, config_path):
    """Compare two or more saved runs and print a side-by-side report.

    By default, runs must share the same ingest hash so the comparison is
    meaningful. Pass `--allow-mixed-ingest` only when you intentionally want
    to compare runs produced from different indexed corpora.
    """
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


@bench_group.command(
    "report",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Render a markdown or JSON report for one run.",
    epilog=format_examples(
        "docmancer bench report lenny_fts",
        "docmancer bench report lenny_fts --format json",
    ),
)
@click.argument("run_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"], case_sensitive=False),
    default="markdown",
    show_default=True,
    help="Output format for the rendered report.",
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_report_cmd(run_id, output_format, config_path):
    """Render a report for one saved bench run.

    Use the default markdown format for a human-readable summary, or `json`
    when you want to feed the metrics into another tool or CI step.
    """
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


@bench_group.command(
    "list",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="List local bench datasets and saved runs.",
    epilog=format_examples(
        "docmancer bench list",
    ),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_list_cmd(config_path):
    """List the datasets and run artifacts available in the current bench workspace.

    Use this to see which dataset names can be passed to `bench run` and which
    saved run IDs can be used with `bench report`, `bench compare`, or
    `bench remove`.
    """
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


@bench_group.command(
    "remove",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove datasets and/or saved run artifacts.",
    epilog=format_examples(
        "docmancer bench remove mydocs",
        "docmancer bench remove mydocs_fts --run",
        "docmancer bench remove mydocs mydocs_fts",
    ),
)
@click.argument("targets", nargs=-1, required=True)
@click.option("--dataset", "remove_dataset", is_flag=True, default=False, help="Only remove dataset entries.")
@click.option("--run", "remove_run", is_flag=True, default=False, help="Only remove run entries.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def bench_remove_cmd(targets, remove_dataset, remove_run, config_path):
    """Remove local bench datasets and run artifacts from the bench workspace.

    This only removes entries shown by `docmancer bench list`. It does not
    remove indexed docs from the SQLite index and it does not clear cached
    built-in corpora under `~/.docmancer/bench/corpora/`.
    """
    from docmancer.cli.commands import _effective_config, _load_config

    config = _load_config(_effective_config(config_path))
    datasets_dir = Path(config.bench.datasets_dir)
    runs_dir = Path(config.bench.runs_dir)

    if not remove_dataset and not remove_run:
        remove_dataset = True
        remove_run = True

    removed: list[tuple[str, str]] = []
    missing: list[str] = []

    for target in targets:
        matched = False
        if remove_dataset:
            ds_dir = datasets_dir / target
            if ds_dir.is_dir() and (ds_dir / "dataset.yaml").exists():
                shutil.rmtree(ds_dir)
                removed.append(("dataset", target))
                matched = True
        if remove_run:
            run_dir = runs_dir / target
            if run_dir.is_dir() and (run_dir / "metrics.json").exists():
                shutil.rmtree(run_dir)
                removed.append(("run", target))
                matched = True
        if not matched:
            missing.append(target)

    for kind, name in removed:
        click.echo(f"Removed {kind}: {name}")

    if missing:
        available_kinds = []
        if remove_dataset:
            available_kinds.append("datasets")
        if remove_run:
            available_kinds.append("runs")
        kinds_str = " and ".join(available_kinds) or "bench artifacts"
        raise click.ClickException(
            f"Not found in {kinds_str}: {', '.join(missing)}"
        )
