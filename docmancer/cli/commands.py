from __future__ import annotations

import os
import logging
import shlex
import shutil
import sys
import zipfile
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.ui import BANNER_COLOR, BANNER_LINES, color_enabled, display_path, style


def _effective_config(config_path: str | None) -> str | None:
    """Merge subcommand --config with group-level --config."""
    if config_path is not None:
        return config_path
    ctx = click.get_current_context(silent=True)
    if ctx and ctx.parent and ctx.parent.obj:
        return ctx.parent.obj.get("config_path")
    return None

INSTALL_TARGETS = [
    "claude-code",
    "claude-desktop",
    "cline",
    "cursor",
    "codex",
    "codex-app",
    "codex-desktop",
    "gemini",
    "opencode",
]


def _get_agent_class():
    from docmancer.agent import DocmancerAgent

    return DocmancerAgent


def _get_config_class():
    from docmancer.core.config import DocmancerConfig

    return DocmancerConfig


def _get_qdrant_client_class():
    from qdrant_client import QdrantClient

    return QdrantClient


def _get_user_config_dir() -> Path:
    return Path.home() / ".docmancer"


def _get_user_config_path() -> Path:
    return _get_user_config_dir() / "docmancer.yaml"


def _get_codex_skill_path() -> Path:
    return Path.home() / ".codex" / "skills" / "docmancer" / "SKILL.md"


def _get_shared_agent_skill_path() -> Path:
    return Path.home() / ".agents" / "skills" / "docmancer" / "SKILL.md"


def _get_gemini_skill_path() -> Path:
    return Path.home() / ".gemini" / "skills" / "docmancer" / "SKILL.md"


def _get_cline_skill_path() -> Path:
    return Path.home() / ".cline" / "skills" / "docmancer" / "SKILL.md"


def _build_user_bootstrap_config():
    DocmancerConfig = _get_config_class()
    config = DocmancerConfig()
    config.vector_store.local_path = str((_get_user_config_dir() / "qdrant").resolve())
    return config


def _ensure_user_config() -> Path:
    import yaml as _yaml

    config_path = _get_user_config_path()
    if config_path.exists():
        return config_path

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = _build_user_bootstrap_config()
    with open(config_path, "w") as f:
        _yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)
    return config_path


def _load_config(config_path: str | None):
    DocmancerConfig = _get_config_class()
    if config_path:
        return DocmancerConfig.from_yaml(config_path)
    default_yaml = Path("docmancer.yaml")
    if default_yaml.exists():
        return DocmancerConfig.from_yaml(default_yaml)
    return DocmancerConfig.from_yaml(_ensure_user_config())


def _describe_vector_store(config) -> str:
    if config.vector_store.url:
        return f"remote Qdrant at {config.vector_store.url}"
    return f"local embedded Qdrant at {display_path(config.vector_store.local_path)}"


def _color_enabled() -> bool:
    return color_enabled()


def _style(text: str, **styles: str | bool) -> str:
    return style(text, **styles)


def _emit_brand_header(command: str, subtitle: str) -> None:
    click.echo()
    for line in BANNER_LINES:
        click.echo(_style(line, fg=BANNER_COLOR, bold=True))
    click.echo(_style(f"  {command}", fg="white", bold=True) + _style(f"  {subtitle}", fg="bright_black"))
    click.echo()


def _emit_status_line(message: str, state: str = "ok", indent: int = 2) -> None:
    palette = {
        "ok": ("[OK]", "bright_green"),
        "info": ("[--]", "bright_cyan"),
        "warn": ("[--]", "yellow"),
        "error": ("[!!]", "red"),
    }
    label, color = palette[state]
    click.echo(" " * indent + _style(label, fg=color, bold=True) + f" {message}")


def _emit_next_step(text: str) -> None:
    click.echo()
    click.echo(_style("  Next:", fg="bright_green", bold=True) + f" {text}")


class _IngestLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        lower = message.lower()

        if lower.startswith("http request:"):
            return _style("[http] ", fg="bright_black") + message
        if "auto-detected platform" in lower or lower.startswith("detected platform:"):
            return _style("[site] ", fg="bright_cyan", bold=True) + message
        if lower.startswith("fetched ") and "starting ingest" in lower:
            return _style("[fetch] ", fg="bright_green", bold=True) + message
        if lower.startswith("chunking ") or lower.startswith("built "):
            return _style("[chunk] ", fg="yellow", bold=True) + message
        if lower.startswith("embedding "):
            return _style("[embed] ", fg="magenta", bold=True) + message
        if lower.startswith("upserting ") or lower.startswith("persisting batch ") or "vector store write complete" in lower or "preparing vector store collections" in lower:
            return _style("[store] ", fg="bright_blue", bold=True) + message
        if lower.startswith("stored source ") or lower.startswith("processed "):
            return _style("[done] ", fg="bright_green", bold=True) + message
        if "large local write detected" in lower or "this step can take a while" in lower:
            return _style("[hint] ", fg="bright_yellow", bold=True) + message
        return message


def _configure_ingest_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_IngestLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def _apply_ingest_overrides(config, workers: int | None, fetch_workers: int | None) -> None:
    if workers is not None:
        config.ingestion.workers = workers
    if fetch_workers is not None:
        config.web_fetch.workers = fetch_workers


def _emit_install_summary(
    heading: str,
    installed_paths: list[tuple[str, Path]],
    created_user_config: bool,
    effective_config_path: Path | None,
    next_step: str,
    extra_lines: list[str] | None = None,
) -> None:
    _emit_brand_header("docmancer install", heading)
    for label, path in installed_paths:
        _emit_status_line(f"{label}: {display_path(path)}")
    if created_user_config:
        _emit_status_line(f"Created user config at {display_path(_get_user_config_path())}")
    elif effective_config_path is not None:
        _emit_status_line(f"Skill uses config {display_path(effective_config_path)}")
    for line in extra_lines or []:
        _emit_status_line(line, state="info")
    _emit_next_step(next_step)


# ---------------------------------------------------------------------------
# Skill install helpers
# ---------------------------------------------------------------------------

def _get_template_content(template_name: str) -> str:
    from importlib.resources import files
    return files("docmancer.templates").joinpath(template_name).read_text(encoding="utf-8")


def _resolve_docmancer_executable() -> str:
    resolved = shutil.which("docmancer")
    if resolved:
        return str(Path(resolved).resolve())
    return f"{sys.executable} -m docmancer"


def _resolve_skill_command(config_path: str | Path | None) -> str:
    parts = [_resolve_docmancer_executable()]
    if config_path is not None:
        parts.extend(["--config", str(Path(config_path).resolve())])
    return " ".join(shlex.quote(part) for part in parts)


def _resolve_install_config_path(config_path: str | None, project: bool) -> Path | None:
    if config_path:
        return Path(config_path).resolve()
    if project:
        default_yaml = Path("docmancer.yaml")
        if default_yaml.exists():
            return default_yaml.resolve()
        return None
    return _ensure_user_config().resolve()


def _build_skill_content(template_name: str, config_path: str | Path | None) -> str:
    content = _get_template_content(template_name)
    return content.replace("{{DOCS_KIT_CMD}}", _resolve_skill_command(config_path))


def _install_skill_file(content: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


def _create_claude_desktop_zip(config_path: str | Path | None) -> Path:
    content = _build_skill_content("claude_desktop_skill.md", config_path)
    export_dir = _get_user_config_dir() / "exports" / "claude-desktop"
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / "docmancer.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docmancer/Skill.md", content)
    return zip_path


_AGENTS_MD_START = "<!-- docmancer:start -->"
_AGENTS_MD_END = "<!-- docmancer:end -->"


def _install_or_append_agents_md(dest: Path, content_body: str) -> None:
    marker_block = f"{_AGENTS_MD_START}\n{content_body.strip()}\n{_AGENTS_MD_END}\n"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        start_idx = existing.find(_AGENTS_MD_START)
        end_idx = existing.find(_AGENTS_MD_END)
        if start_idx != -1 and end_idx != -1:
            # Replace existing block
            new_content = existing[:start_idx] + marker_block + existing[end_idx + len(_AGENTS_MD_END):]
            dest.write_text(new_content.strip() + "\n", encoding="utf-8")
        else:
            # Append to file
            separator = "\n\n" if existing.strip() else ""
            dest.write_text(existing.rstrip() + separator + marker_block, encoding="utf-8")
    else:
        dest.write_text(marker_block, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Create a docmancer config file.",
    epilog=format_examples(
        "docmancer init",
        "docmancer init --dir ./sandbox",
        "docmancer init --template vault",
        "docmancer init --template vault --name stripe-research",
    ),
)
@click.option("--dir", "directory", default=".", help="Target directory for the config file.")
@click.option("--template", "template", default=None,
              type=click.Choice(["vault"], case_sensitive=False),
              help="Project template. 'vault' scaffolds a structured knowledge base.")
@click.option("--name", "vault_name", default=None, help="Custom vault name (vault template only). Defaults to directory name.")
def init_cmd(directory: str, template: str | None, vault_name: str | None):
    """Initialize a docmancer project with a config file."""
    import yaml as _yaml

    if template == "vault":
        from docmancer.vault.operations import init_vault
        dir_path = Path(directory)
        config_path = init_vault(dir_path, name=vault_name)
        effective_name = vault_name or dir_path.resolve().name
        click.echo(f"Vault '{effective_name}' initialized at {display_path(dir_path.resolve())}")
        click.echo(f"  Config: {display_path(config_path)}")
        click.echo("  Directories: raw/, wiki/, outputs/, .docmancer/")
        click.echo()
        click.echo("Next: add content with 'docmancer vault add-url <url>' or place files in raw/")
        return

    dir_path = Path(directory)
    dir_path.mkdir(parents=True, exist_ok=True)
    config_path = dir_path / "docmancer.yaml"
    if config_path.exists():
        click.echo(f"Config already exists at {display_path(config_path)}")
        return
    DocmancerConfig = _get_config_class()
    config = DocmancerConfig()
    data = config.model_dump()
    with open(config_path, "w") as f:
        _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    click.echo(f"Created config at {display_path(config_path)}")
    click.echo("No API keys required; embeddings run fully locally.")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Ingest docs from a path or URL.",
    epilog=format_examples(
        "docmancer ingest ./docs",
        "docmancer ingest https://docs.example.com",
        "docmancer ingest ./docs --recreate",
        "docmancer ingest https://docs.example.com --provider web",
        "docmancer ingest https://docs.example.com --provider web --max-pages 200",
    ),
)
@click.argument("path")
@click.option("--recreate", is_flag=True, help="Recreate the collection first.")
@click.option("--provider", default="auto", show_default=True,
              type=click.Choice(["auto", "gitbook", "mintlify", "web"], case_sensitive=False),
              help="Docs platform. auto tries llms.txt then sitemap.xml. web uses generic pipeline.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.option("--max-pages", default=500, show_default=True, type=int,
              help="Maximum pages to fetch (web provider).")
@click.option("--strategy", default=None, type=str,
              help="Force a discovery strategy (e.g. llms-full.txt, sitemap.xml, nav-crawl).")
@click.option("--browser", is_flag=True, default=False,
              help="Enable Playwright browser fallback for JS-heavy sites.")
@click.option("--workers", default=None, type=int,
              help="Number of concurrent ingest workers for chunking and embedding.")
@click.option("--fetch-workers", default=None, type=int,
              help="Number of concurrent page fetch workers for the web provider.")
def ingest_cmd(
    path: str,
    recreate: bool,
    provider: str,
    config_path: str | None,
    max_pages: int,
    strategy: str | None,
    browser: bool,
    workers: int | None,
    fetch_workers: int | None,
):
    """Ingest documents from a file, directory, or URL."""
    config_path = _effective_config(config_path)
    _configure_ingest_logging()

    config = _load_config(config_path)
    _apply_ingest_overrides(config, workers=workers, fetch_workers=fetch_workers)
    agent = _get_agent_class()(config=config)

    try:
        if path.startswith("http://") or path.startswith("https://"):
            click.echo(f"Fetching docs from {path}...")
            total = agent.ingest_url(
                path,
                recreate=recreate,
                provider=provider if provider != "auto" else None,
                max_pages=max_pages,
                strategy=strategy,
                browser=browser,
            )
        else:
            total = agent.ingest(path, recreate=recreate)
        click.echo(f"Total: {total} chunks ingested")
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Download docs to Markdown files.",
    epilog=format_examples(
        "docmancer fetch https://docs.example.com",
        "docmancer fetch https://docs.example.com --output ./downloaded-docs",
    ),
)
@click.argument("url")
@click.option(
    "--output",
    "output_dir",
    default="docmancer-docs",
    show_default=True,
    help="Output directory for downloaded .md files.",
)
def fetch_cmd(url: str, output_dir: str):
    """Download docs from a GitBook URL to local .md files."""
    from urllib.parse import urlparse
    from docmancer.connectors.fetchers.gitbook import GitBookFetcher

    fetcher = GitBookFetcher()
    click.echo(f"Fetching docs from {url}...")
    try:
        documents = fetcher.fetch(url)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    for doc in documents:
        parsed = urlparse(doc.source)
        slug = parsed.path.strip("/").replace("/", "_") or "index"
        filename = f"{slug}.md"
        file_path = out_path / filename
        file_path.write_text(doc.content, encoding="utf-8")
        click.echo(f"  Saved {display_path(file_path)}")

    click.echo(f"Downloaded {len(documents)} document(s) to {output_dir}/")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Show collection stats.",
    epilog=format_examples(
        "docmancer inspect",
        "docmancer inspect --config ./docmancer.yaml",
    ),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def inspect_cmd(config_path: str | None):
    """Show collection stats and configuration."""
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)

    stats = agent.collection_stats()
    click.echo(f"Collection: {config.vector_store.collection_name}")
    click.echo(f"Exists: {stats.get('collection_exists', False)}")
    click.echo(f"Points: {stats.get('points_count', 0)}")
    click.echo(f"Embeddings: {config.embedding.provider} ({config.embedding.model})")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Check config, connectivity, and installed skills.",
    epilog=format_examples(
        "docmancer doctor",
        "docmancer doctor --config ./docmancer.yaml",
    ),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def doctor_cmd(config_path: str | None):
    """Check environment, connectivity, and installed skill status."""
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    home = Path.home()
    _emit_brand_header("docmancer doctor", "Check binary, config, archive, and installed skills.")

    # Binary resolution
    resolved_bin = shutil.which("docmancer")
    if resolved_bin:
        _emit_status_line(f"docmancer binary: {display_path(resolved_bin)}")
    else:
        _emit_status_line("docmancer not found on PATH (install with: pipx install docmancer --python python3.13)", state="warn")

    # Effective config
    if config_path:
        effective_config = Path(config_path)
    elif Path("docmancer.yaml").exists():
        effective_config = Path("docmancer.yaml")
    else:
        effective_config = _get_user_config_path()
    _emit_status_line(f"Config: {display_path(effective_config)}")

    # Vector store
    _emit_status_line(f"Vector store: {_describe_vector_store(config)}")

    if config.vector_store.url:
        try:
            QdrantClient = _get_qdrant_client_class()
            client = QdrantClient(url=config.vector_store.url, timeout=3)
            client.get_collections()
            _emit_status_line(f"Qdrant reachable at {config.vector_store.url}")
        except Exception:
            _emit_status_line(f"Qdrant not reachable at {config.vector_store.url}", state="warn")
    else:
        qdrant_path = Path(config.vector_store.local_path)
        if qdrant_path.exists():
            _emit_status_line(f"Embedded Qdrant data at {display_path(qdrant_path)}")
            try:
                agent = _get_agent_class()(config=config)
                stats = agent.collection_stats()
                count = stats.get("points_count") or 0
                _emit_status_line(f"Chunks indexed: {count}")
                if count >= 20000:
                    _emit_status_line(
                        f"Large collection ({count} chunks). For best performance, run "
                        "'docmancer remove --all' and re-ingest to apply on-disk storage optimizations.",
                        state="warn",
                    )
            except Exception:
                pass
        else:
            _emit_status_line(f"No Qdrant data yet at {display_path(qdrant_path)} (run: docmancer ingest)", state="warn")

    # Skill install status
    click.echo()
    click.echo(_style("  Installed skills", fg="white", bold=True))
    skill_locations = [
        ("claude-code", "claude-code", home / ".claude" / "skills" / "docmancer" / "SKILL.md"),
        ("cursor", "cursor", home / ".cursor" / "skills" / "docmancer" / "SKILL.md"),
        ("cline", "cline", _get_cline_skill_path()),
        ("codex", "codex", _get_codex_skill_path()),
        ("codex-shared", "codex", _get_shared_agent_skill_path()),
        ("gemini", "gemini", _get_gemini_skill_path()),
        ("opencode", "opencode", home / ".config" / "opencode" / "skills" / "docmancer" / "SKILL.md"),
        ("claude-desktop", "claude-desktop", _get_user_config_dir() / "exports" / "claude-desktop" / "docmancer.zip"),
    ]
    for label, install_target, path in skill_locations:
        if path.exists():
            _emit_status_line(f"{label}: {display_path(path)}", indent=4)
        else:
            _emit_status_line(f"{label}: not installed (run: docmancer install {install_target})", state="warn", indent=4)


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Search ingested docs.",
    epilog=format_examples(
        'docmancer query "How do I authenticate?"',
        'docmancer query "getting started" --limit 3',
        'docmancer query "season 5 end date" --full',
    ),
)
@click.argument("text")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.option("--limit", default=None, type=int, help="Maximum chunks to return.")
@click.option("--full", is_flag=True, default=False, help="Show full chunk text without truncation.")
@click.option("--trace", is_flag=True, default=False, help="Show execution trace with timing breakdown.")
@click.option("--save-trace", is_flag=True, default=False, help="Save trace to .docmancer/traces/.")
@click.option("--cross-vault", "cross_vault", is_flag=True, default=False, help="Query across all registered vaults.")
@click.option("--tag", "filter_tag", default=None, help="Filter cross-vault query to vaults with this tag.")
def query_cmd(text: str, config_path: str | None, limit: int | None, full: bool, trace: bool, save_trace: bool, cross_vault: bool, filter_tag: str | None):
    """Run a retrieval query against the vector store (no server required)."""
    effective_limit = limit if limit is not None else 5

    if filter_tag and not cross_vault:
        cross_vault = True  # --tag implies --cross-vault

    if cross_vault:
        from docmancer.vault.operations import cross_vault_query
        chunks = cross_vault_query(text, tag=filter_tag, limit=effective_limit)
        query_trace = None
    else:
        config_path = _effective_config(config_path)
        config = _load_config(config_path)
        agent = _get_agent_class()(config=config)

        if trace or save_trace:
            chunks, query_trace = agent.query_with_trace(text, limit=limit)
        else:
            chunks = agent.query(text, limit=limit)
            query_trace = None

    if not chunks:
        click.echo("No results found.")
        sys.exit(1)

    for i, chunk in enumerate(chunks, start=1):
        if full:
            body = chunk.text
        else:
            body = chunk.text[:1500] + "..." if len(chunk.text) > 1500 else chunk.text
        vault_label = f"  vault={chunk.vault_name}" if chunk.vault_name else ""
        click.echo(f"[{i}] score={chunk.score:.2f}  source={chunk.source}{vault_label}")
        click.echo(body)
        click.echo("---")

    if query_trace is not None:
        if trace:
            from docmancer.telemetry.tracer import format_trace_for_terminal
            click.echo("")
            click.echo(format_trace_for_terminal(query_trace))
        if save_trace:
            traces_dir = Path(".docmancer") / "traces"
            saved_path = query_trace.save(traces_dir)
            click.echo(f"Trace saved to {saved_path}")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove an ingested source.",
    epilog=format_examples(
        "docmancer remove --all",
        "docmancer remove https://docs.example.com",
        "docmancer remove https://docs.example.com/page",
        "docmancer remove ./docs/getting-started.md",
    ),
)
@click.argument("source", required=False)
@click.option("--all", "remove_all", is_flag=True, default=False, help="Remove every stored source and docset.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def remove_cmd(source: str | None, remove_all: bool, config_path: str | None):
    """Remove an ingested source (URL or file path) from the knowledge base."""
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)
    if remove_all:
        if source:
            click.echo("Do not pass a source when using --all.", err=True)
            sys.exit(1)
        deleted = agent.remove_all_sources()
        if deleted:
            click.echo("Removed all sources.")
        else:
            click.echo("No data found to remove.", err=True)
            sys.exit(1)
        return
    if not source:
        click.echo("Missing argument 'SOURCE'.", err=True)
        sys.exit(1)
    deleted, removed_kind = agent.remove_source(source)
    if deleted:
        if removed_kind == "docset":
            click.echo(f"Removed docset: {source}")
        else:
            click.echo(f"Removed source: {source}")
    else:
        click.echo(f"No data found for source: {source}", err=True)
        sys.exit(1)


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="List ingested sources.",
    epilog=format_examples(
        "docmancer list",
        "docmancer list --all",
        "docmancer list --vaults",
        "docmancer list --vaults --tag research",
        "docmancer list --config ./docmancer.yaml",
    ),
)
@click.option("--all", "show_all", is_flag=True, default=False, help="Show every stored page/file source.")
@click.option("--vaults", "show_vaults", is_flag=True, default=False, help="Show all registered vaults.")
@click.option("--tag", "filter_tag", default=None, help="Filter vaults by tag (use with --vaults).")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def list_cmd(show_all: bool, show_vaults: bool, filter_tag: str | None, config_path: str | None):
    """List all ingested sources with their ingestion dates."""
    if show_vaults:
        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry()
        if filter_tag:
            vaults = registry.list_vaults_by_tag(filter_tag)
        else:
            vaults = registry.list_vaults()
        if not vaults:
            if filter_tag:
                click.echo(f"No vaults with tag '{filter_tag}'.")
            else:
                click.echo("No vaults registered.")
            return
        for v in vaults:
            name = v["name"]
            path = v["root_path"]
            last_scan = v.get("last_scan") or "never"
            status = v.get("status", "unknown")
            tags = v.get("tags", [])
            click.echo(f"  {name}")
            click.echo(f"    Path:      {path}")
            click.echo(f"    Last scan: {last_scan}")
            click.echo(f"    Status:    {status}")
            if tags:
                click.echo(f"    Tags:      {', '.join(tags)}")
            click.echo()
        return
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)
    entries = agent.list_sources_with_dates() if show_all else agent.list_grouped_sources_with_dates()
    if not entries:
        click.echo("No sources ingested yet.")
        return
    for entry in entries:
        click.echo(f"{entry['ingested_at']}  {entry['source']}")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Install docmancer skills into an AI agent.",
    epilog=format_examples(
        "docmancer install claude-code",
        "docmancer install codex",
        "docmancer install claude-code --project",
        "docmancer install cursor",
        "docmancer install claude-desktop",
        "docmancer install gemini",
        "docmancer install opencode",
        "docmancer install cline",
    ),
)
@click.argument("agent", type=click.Choice(INSTALL_TARGETS, case_sensitive=False))
@click.option("--project", is_flag=True, default=False,
              help="Install in project-level settings (claude-code, gemini, or cline).")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def install_cmd(agent: str, project: bool, config_path: str | None):
    """Install docmancer skill files into an AI agent.

    Teaches the agent to call docmancer CLI commands directly. No server
    required. Run 'docmancer ingest <url>' first to populate the knowledge base.

    AGENT must be one of: claude-code, claude-desktop, cline, cursor, codex,
    codex-app, codex-desktop, gemini, opencode
    """
    config_path = _effective_config(config_path)
    normalized = agent.lower()
    home = Path.home()
    user_config_exists_before = _get_user_config_path().exists()
    effective_config_path = _resolve_install_config_path(config_path, project)
    created_user_config = (
        not project
        and config_path is None
        and not user_config_exists_before
        and effective_config_path == _get_user_config_path().resolve()
    )

    if normalized == "claude-desktop":
        zip_path = _create_claude_desktop_zip(effective_config_path)
        _emit_install_summary(
            "Package skill for Claude Desktop.",
            [("Created docmancer skill package at", zip_path)],
            created_user_config,
            effective_config_path,
            f"Upload {display_path(zip_path)} in Claude Desktop > Customize > Skills.",
            extra_lines=[
                "1. Open Claude Desktop",
                "2. Go to Customize > Skills",
                '3. Click "+" and select "Upload a skill"',
                f"4. Upload: {display_path(zip_path)}",
            ],
        )
        return

    if normalized == "claude-code":
        if project:
            dest = Path(".claude") / "skills" / "docmancer" / "SKILL.md"
        else:
            dest = home / ".claude" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("claude_code_skill.md", effective_config_path)
        _install_skill_file(content, dest)
        _emit_install_summary(
            "Install skill for Claude Code.",
            [("Installed docmancer skill at", dest)],
            created_user_config,
            effective_config_path,
            "Claude Code can use docmancer immediately. No restart needed.",
            extra_lines=["Claude Code will automatically use docmancer commands."],
        )
        return

    if normalized in {"codex", "codex-app", "codex-desktop"}:
        dest = _get_codex_skill_path()
        shared_dest = _get_shared_agent_skill_path()
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)
        _install_skill_file(content, shared_dest)
        _emit_install_summary(
            "Install skill for Codex.",
            [
                ("Installed docmancer skill at", dest),
                ("Also installed shared compatibility skill at", shared_dest),
            ],
            created_user_config,
            effective_config_path,
            'Run `docmancer query "your question"` to verify retrieval from the CLI.',
            extra_lines=["Codex will automatically use docmancer commands."],
        )
        return

    if normalized == "cursor":
        dest = home / ".cursor" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)

        # Also write AGENTS.md fallback while Cursor's skill discovery matures
        agents_md = home / ".cursor" / "AGENTS.md"
        agents_body = _get_template_content("cursor_agents_md.md").replace(
            "{{DOCS_KIT_CMD}}", _resolve_skill_command(effective_config_path)
        )
        _install_or_append_agents_md(agents_md, agents_body)
        _emit_install_summary(
            "Install skill for Cursor.",
            [
                ("Installed docmancer skill at", dest),
                ("Updated fallback at", agents_md),
            ],
            created_user_config,
            effective_config_path,
            "Restart Cursor for changes to take effect.",
        )
        return

    if normalized == "cline":
        if project:
            dest = Path(".cline") / "skills" / "docmancer" / "SKILL.md"
        else:
            dest = home / ".cline" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)
        _emit_install_summary(
            "Install skill for Cline.",
            [("Installed docmancer skill at", dest)],
            created_user_config,
            effective_config_path,
            "Enable Skills in Cline (Settings → Features) if you have not already. Restart VS Code if Cline does not pick up the skill.",
            extra_lines=[
                "Cline discovers skills from ~/.cline/skills/ or .cline/skills/ in the workspace.",
            ],
        )
        return

    if normalized == "gemini":
        if project:
            dest = Path(".gemini") / "skills" / "docmancer" / "SKILL.md"
        else:
            dest = home / ".gemini" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)

        # Also write to shared ~/.agents/skills/ path if not already installed
        shared_dest = _get_shared_agent_skill_path()
        installed_paths = [("Installed docmancer skill at", dest)]
        if not shared_dest.exists():
            _install_skill_file(content, shared_dest)
            installed_paths.append(("Also installed at shared path", shared_dest))

        _emit_install_summary(
            "Install skill for Gemini CLI.",
            installed_paths,
            created_user_config,
            effective_config_path,
            'Run `docmancer query "your question"` or restart Gemini if it does not pick up the skill immediately.',
            extra_lines=["Gemini CLI will automatically use docmancer commands."],
        )
        return

    if normalized == "opencode":
        dest = home / ".config" / "opencode" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)

        # Also write to shared ~/.agents/skills/ path if not already installed by codex
        shared_dest = _get_shared_agent_skill_path()
        installed_paths = [("Installed docmancer skill at", dest)]
        if not shared_dest.exists():
            _install_skill_file(content, shared_dest)
            installed_paths.append(("Also installed at shared path", shared_dest))

        _emit_install_summary(
            "Install skill for OpenCode.",
            installed_paths,
            created_user_config,
            effective_config_path,
            'Run `docmancer query "your question"` to verify retrieval from the CLI.',
            extra_lines=["OpenCode will automatically use docmancer commands."],
        )
        return
