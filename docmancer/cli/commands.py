from __future__ import annotations

import os
import hashlib
import json
import logging
import shlex
import shutil
import sys
import tarfile
import tempfile
import time
import webbrowser
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
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
    "github-copilot",
    "opencode",
]


def _get_agent_class():
    from docmancer.agent import DocmancerAgent

    return DocmancerAgent


def _get_config_class():
    from docmancer.core.config import DocmancerConfig

    return DocmancerConfig


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


def _get_copilot_user_instructions_path() -> Path:
    return Path.home() / ".copilot" / "copilot-instructions.md"


def _build_user_bootstrap_config():
    DocmancerConfig = _get_config_class()
    config = DocmancerConfig()
    config.index.db_path = str((_get_user_config_dir() / "docmancer.db").resolve())
    config.index.extracted_dir = str((_get_user_config_dir() / "extracted").resolve())
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


def _resolve_config_file(config_path: str | None) -> Path:
    if config_path:
        return Path(config_path).resolve()
    if Path("docmancer.yaml").exists():
        return Path("docmancer.yaml").resolve()
    return _ensure_user_config().resolve()


def _describe_index(config) -> str:
    return f"SQLite FTS5 at {display_path(config.index.db_path)}"


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.1f} MB"
    return f"{num_bytes / 1024 / 1024 / 1024:.1f} GB"


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _emit_index_summary(total: int, agent) -> None:
    click.echo(f"Total: {total} sections indexed")
    try:
        stats = agent.collection_stats()
    except Exception:
        return

    db_path_value = stats.get("db_path") if isinstance(stats, dict) else None
    extracted_dir_value = stats.get("extracted_dir") if isinstance(stats, dict) else None

    db_path = Path(db_path_value) if db_path_value else None
    extracted_dir = Path(extracted_dir_value) if extracted_dir_value else None
    db_size = _path_size(db_path) if db_path else 0
    extracted_size = _path_size(extracted_dir) if extracted_dir else 0
    total_size = db_size + extracted_size

    if total_size:
        click.echo(f"Storage: {_format_size(total_size)} on disk")
    if db_path:
        suffix = f" ({_format_size(db_size)})" if db_size else ""
        click.echo(f"Index: {display_path(db_path)}{suffix}")
    if extracted_dir:
        suffix = f" ({_format_size(extracted_size)})" if extracted_size else ""
        click.echo(f"Extracted docs: {display_path(extracted_dir)}{suffix}")


def _create_agent_or_raise_lock_error(config):
    try:
        return _get_agent_class()(config=config)
    except RuntimeError:
        raise


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_pack_ref(value: str) -> tuple[str, str | None]:
    value = _normalize_pack_ref(value)
    if "@" not in value:
        return value, None
    name, version = value.rsplit("@", 1)
    if not name or not version:
        raise click.ClickException("Pack must be formatted as <name> or <name>@<version>.")
    return name, version


def _normalize_pack_ref(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return value

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "registry":
        name = parts[1]
        version = parse_qs(parsed.query).get("version", [None])[0]
        return f"{name}@{version}" if version else name

    return value


def _registry_client(config):
    from docmancer.core.auth import load_auth_token
    from docmancer.core.registry_client import RegistryClient

    return RegistryClient(config.registry, load_auth_token(config.registry.auth_path))


def _handle_registry_error(exc: Exception) -> None:
    from docmancer.core.registry_errors import RegistryError

    if isinstance(exc, RegistryError):
        raise click.ClickException(exc.message)
    raise exc


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
        if lower.startswith("indexing "):
            return _style("[index] ", fg="magenta", bold=True) + message
        if lower.startswith("stored ") or lower.startswith("persisting batch "):
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


def _install_vscode_copilot_settings(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    settings: dict[str, object] = {}
    if dest.exists() and dest.read_text(encoding="utf-8").strip():
        try:
            settings = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Could not update {display_path(dest)} because it is not valid JSON: {exc}") from exc
        if not isinstance(settings, dict):
            raise click.ClickException(f"Could not update {display_path(dest)} because it must contain a JSON object.")
    settings["github.copilot.chat.codeGeneration.useInstructionFiles"] = True
    dest.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.command(
    cls=DocmancerCommand,
    context_settings={**HELP_CONTEXT_SETTINGS, "allow_extra_args": True},
    short_help="Create a project-local config file.",
    epilog=format_examples(
        "docmancer init",
        "docmancer init --dir ./sandbox",
    ),
)
@click.option("--dir", "directory", default=None, help="Target directory for the config file.")
def init_cmd(directory: str | None):
    """Initialize a docmancer project with a config file."""
    import yaml as _yaml

    dir_path = Path(directory or ".")
    dir_path.mkdir(parents=True, exist_ok=True)
    config_path = dir_path / "docmancer.yaml"
    if config_path.exists():
        click.echo(f"Config already exists at {display_path(config_path)}")
        return
    DocmancerConfig = _get_config_class()
    config = DocmancerConfig()
    config.index.db_path = ".docmancer/docmancer.db"
    config.index.extracted_dir = ".docmancer/extracted"
    data = config.model_dump()
    with open(config_path, "w") as f:
        _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    click.echo(f"Created config at {display_path(config_path)}")
    click.echo("Local SQLite FTS5 index configured at .docmancer/docmancer.db")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Add docs to the local SQLite index.",
    epilog=format_examples(
        "docmancer add ./docs",
        "docmancer add ./README.md",
        "docmancer add https://docs.example.com",
        "docmancer add https://github.com/owner/repo",
        "docmancer add https://docs.example.com --max-pages 200",
    ),
)
@click.argument("path")
@click.option("--recreate", is_flag=True, help="Recreate the collection first.")
@click.option("--provider", default="auto", show_default=True,
              type=click.Choice(["auto", "gitbook", "mintlify", "web", "github"], case_sensitive=False),
              help="Docs platform. auto tries llms.txt then sitemap.xml. web uses generic pipeline.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.option("--max-pages", default=500, show_default=True, type=int,
              help="Maximum pages to fetch (web provider).")
@click.option("--strategy", default=None, type=str,
              help="Force a discovery strategy (e.g. llms-full.txt, sitemap.xml, nav-crawl).")
@click.option("--browser", is_flag=True, default=False,
              help="Enable Playwright browser fallback for JS-heavy sites.")
@click.option("--fetch-workers", default=None, type=int,
              help="Number of concurrent page fetch workers for the web provider.")
def add_cmd(
    path: str,
    recreate: bool,
    provider: str,
    config_path: str | None,
    max_pages: int,
    strategy: str | None,
    browser: bool,
    fetch_workers: int | None,
):
    """Add documents from a file, directory, or URL."""
    config_path = _effective_config(config_path)
    _configure_ingest_logging()

    config = _load_config(config_path)
    if fetch_workers is not None:
        config.web_fetch.workers = fetch_workers
    agent = _get_agent_class()(config=config)

    try:
        if path.startswith("http://") or path.startswith("https://"):
            click.echo(f"Adding docs from {path}...")
            total = agent.add(
                path,
                recreate=recreate,
                provider=provider if provider != "auto" else None,
                max_pages=max_pages,
                strategy=strategy,
                browser=browser,
            )
        else:
            total = agent.add(path, recreate=recreate)
        _emit_index_summary(total, agent)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Refresh all or specific indexed docs sources.",
    epilog=format_examples(
        "docmancer update",
        "docmancer update https://docs.example.com",
        "docmancer update ./docs",
    ),
)
@click.argument("source", required=False, default=None)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.option("--max-pages", default=500, show_default=True, type=int,
              help="Maximum pages to fetch (web sources).")
@click.option("--browser", is_flag=True, default=False,
              help="Enable Playwright browser fallback for JS-heavy sites.")
def update_cmd(
    source: str | None,
    config_path: str | None,
    max_pages: int,
    browser: bool,
):
    """Re-fetch and re-index existing docs sources.

    With no arguments, refreshes every source in the index. Pass a specific
    source URL or path to update only that source.
    """
    config_path = _effective_config(config_path)
    _configure_ingest_logging()

    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)

    sources = agent.list_sources_with_dates()
    if not sources:
        click.echo("No indexed sources to update. Run 'docmancer add <url-or-path>' first.")
        return

    if source:
        matching = [s for s in sources if s["source"] == source]
        if not matching:
            # Try matching against grouped docset roots
            grouped = agent.list_grouped_sources_with_dates()
            matching_root = [g for g in grouped if g["source"] == source]
            if matching_root:
                # Re-add the entire docset root
                matching = [s for s in sources if True]  # will be filtered below
                # Get all individual sources under this docset root
                all_sources = agent.list_sources_with_dates()
                matching = []
                with agent.store._connect() as conn:
                    rows = conn.execute(
                        "SELECT source FROM sources WHERE docset_root = ?", (source,)
                    ).fetchall()
                    matching = [{"source": row["source"]} for row in rows]
            if not matching:
                click.echo(f"Source not found in index: {source}")
                click.echo("Run 'docmancer list' to see indexed sources.")
                sys.exit(1)
        targets = matching
    else:
        # Deduplicate by docset root so we re-add at the docset level
        grouped = agent.list_grouped_sources_with_dates()
        targets = grouped

    updated = 0
    failed = 0
    for entry in targets:
        src = entry["source"]
        try:
            if src.startswith(("http://", "https://")):
                click.echo(f"Updating {src}...")
                total = agent.add(src, recreate=False, max_pages=max_pages, browser=browser)
            else:
                if not Path(src).exists():
                    click.echo(f"Skipping {src} (path not found on disk)")
                    failed += 1
                    continue
                click.echo(f"Updating {src}...")
                total = agent.add(src, recreate=False)
            click.echo(f"  {total} sections indexed")
            updated += 1
        except Exception as e:
            click.echo(f"  Error updating {src}: {e}", err=True)
            failed += 1

    click.echo()
    click.echo(f"Updated {updated} source(s)." + (f" {failed} failed." if failed else ""))


@click.command(
    cls=DocmancerCommand,
    context_settings={**HELP_CONTEXT_SETTINGS, "ignore_unknown_options": True, "allow_extra_args": True},
    short_help="Deprecated. Use 'docmancer add'.",
)
def ingest_cmd():
    """Deprecated command retained only to explain the breaking transition."""
    raise click.ClickException("docmancer ingest has been removed from the primary CLI. Use: docmancer add <url-or-path>")


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
    agent = _create_agent_or_raise_lock_error(config)

    stats = agent.collection_stats()
    click.echo(f"Index: {display_path(config.index.db_path)}")
    click.echo(f"Exists: {stats.get('collection_exists', False)}")
    click.echo(f"Sources: {stats.get('sources_count', 0)}")
    click.echo(f"Sections: {stats.get('sections_count', 0)}")
    click.echo(f"Extracted: {display_path(stats.get('extracted_dir', ''))}")


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
    # Detect the actual executable running this process (handles python -m docmancer).
    current_exe = str(Path(sys.executable).resolve())
    is_module_invocation = not resolved_bin or str(Path(resolved_bin).resolve()) != current_exe

    if resolved_bin:
        _emit_status_line(f"docmancer binary: {display_path(resolved_bin)}")
    else:
        _emit_status_line("docmancer not found on PATH (install with: pipx install docmancer --python python3.13)", state="warn")

    if is_module_invocation:
        _emit_status_line(f"running via: {current_exe} -m docmancer")

    # Effective config
    if config_path:
        effective_config = Path(config_path)
    elif Path("docmancer.yaml").exists():
        effective_config = Path("docmancer.yaml")
    else:
        effective_config = _get_user_config_path()
    _emit_status_line(f"Config: {display_path(effective_config)}")

    _emit_status_line(f"Index: {_describe_index(config)}")
    try:
        agent = _get_agent_class()(config=config)
        stats = agent.collection_stats()
        _emit_status_line(f"Sources indexed: {stats.get('sources_count', 0)}")
        _emit_status_line(f"Sections indexed: {stats.get('sections_count', 0)}")
        _emit_status_line(f"Inspectable extracts: {display_path(stats.get('extracted_dir', ''))}")
    except RuntimeError as exc:
        _emit_status_line(str(exc), state="error")
    else:
        if not Path(config.index.db_path).exists():
            _emit_status_line("No docs indexed yet (run: docmancer add <url-or-path>)", state="warn")

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
        ("github-copilot", "github-copilot", _get_copilot_user_instructions_path()),
        ("opencode", "opencode", home / ".config" / "opencode" / "skills" / "docmancer" / "SKILL.md"),
        ("claude-desktop", "claude-desktop", _get_user_config_dir() / "exports" / "claude-desktop" / "docmancer.zip"),
    ]
    for label, install_target, path in skill_locations:
        if path.exists():
            _emit_status_line(f"{label}: {display_path(path)}", indent=4)
        else:
            _emit_status_line(f"{label}: not installed (run: docmancer install {install_target})", state="warn", indent=4)

    click.echo()
    click.echo(_style("  Registry", fg="white", bold=True))
    try:
        from docmancer.core.auth import load_auth_token
        from docmancer.core.registry_client import RegistryClient
        from docmancer.core.registry_errors import AuthExpired, AuthRequired
        from docmancer.core.sqlite_store import SQLiteStore

        store = SQLiteStore(config.index.db_path, extracted_dir=config.index.extracted_dir or None)
        _emit_status_line(f"Installed packs: {len(store.list_installed_packs())}", indent=4)
        ok, message = RegistryClient(config.registry, load_auth_token(config.registry.auth_path)).check_connectivity()
        _emit_status_line(f"Connectivity: {message}", state="ok" if ok else "warn", indent=4)
        auth = load_auth_token(config.registry.auth_path)
        if auth is None:
            _emit_status_line("Auth: not authenticated", state="info", indent=4)
        else:
            try:
                status = RegistryClient(config.registry, auth).get_user_status()
                _emit_status_line(f"Auth: {status.get('email') or status.get('username') or 'token found'} ({status.get('tier') or 'free'})", indent=4)
            except (AuthExpired, AuthRequired):
                _emit_status_line("Auth: token expired or invalid; local CLI unaffected", state="warn", indent=4)
            except Exception:
                _emit_status_line("Auth: token found; registry verification unavailable, local CLI unaffected", state="warn", indent=4)
    except Exception:
        _emit_status_line("Registry checks skipped; local CLI unaffected", state="warn", indent=4)


@click.command(
    cls=DocmancerCommand,
    context_settings={**HELP_CONTEXT_SETTINGS, "allow_extra_args": True},
    short_help="Search indexed docs.",
    epilog=format_examples(
        'docmancer query "How do I authenticate?"',
        'docmancer query "getting started" --limit 3',
        'docmancer query "season 5 end date" --expand',
        'docmancer query "season 5 end date" --expand page',
        'docmancer query "auth" --format json',
    ),
)
@click.argument("text")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.option("--limit", default=None, type=int, help="Maximum sections to return.")
@click.option("--budget", default=None, type=int, help="Maximum estimated output tokens.")
@click.option(
    "--expand",
    flag_value="adjacent",
    default=None,
    help="Include adjacent sections around matches. Add 'page' after the flag for the full page.",
)
@click.option("output_format", "--format", type=click.Choice(["markdown", "json"], case_sensitive=False), default="markdown", show_default=True)
@click.pass_context
def query_cmd(
    ctx: click.Context,
    text: str,
    config_path: str | None,
    limit: int | None,
    budget: int | None,
    expand: str | None,
    output_format: str,
):
    """Return a compact docs context pack from the local SQLite index."""
    import json as _json

    if expand and ctx.args:
        if ctx.args == ["page"]:
            expand = "page"
        elif ctx.args == ["adjacent"]:
            expand = "adjacent"
        else:
            raise click.ClickException("Unexpected argument after --expand. Use '--expand' or '--expand page'.")
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)
    chunks = agent.query(text, limit=limit, budget=budget, expand=expand)

    if not chunks:
        click.echo("No results found.")
        sys.exit(1)

    meta = chunks[0].metadata or {}
    savings = meta.get("savings_percent", 0)
    runway = meta.get("runway_multiplier", 1)
    docmancer_tokens = meta.get("docmancer_tokens", 0)
    raw_tokens = meta.get("raw_tokens", 0)

    if output_format == "json":
        click.echo(
            _json.dumps(
                {
                    "query": text,
                    "budget": budget or config.query.default_budget,
                    "docmancer_tokens": docmancer_tokens,
                    "raw_tokens": raw_tokens,
                    "savings_percent": savings,
                    "runway_multiplier": runway,
                    "results": [chunk.model_dump() for chunk in chunks],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    click.echo(
        f"Context pack: ~{docmancer_tokens} tokens vs ~{raw_tokens} raw docs tokens "
        f"({savings}% less docs overhead, {runway}x agentic runway)"
    )
    click.echo("---")

    for i, chunk in enumerate(chunks, start=1):
        body = chunk.text
        click.echo(f"[{i}] score={chunk.score:.2f}  source={chunk.source}")
        meta = chunk.metadata or {}
        if meta.get("title"):
            click.echo(f"    section: {meta['title']}")
        click.echo(f"    tokens: ~{meta.get('token_estimate', 0)}")
        click.echo(body)
        click.echo("---")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove an indexed source.",
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
    """Remove an indexed source (URL or file path) from the knowledge base."""
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
            click.echo("No data found to remove.")
        return
    if not source:
        click.echo("Missing argument 'SOURCE'.", err=True)
        sys.exit(1)
    if not source.startswith(("http://", "https://", "./", "/", ".")):
        try:
            if agent.store.uninstall_pack(*_split_pack_ref(source)):
                click.echo(f"Removed pack: {source}")
                return
        except Exception:
            pass
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
    short_help="List indexed documentation sources.",
    epilog=format_examples(
        "docmancer list",
        "docmancer list --all",
        "docmancer list --config ./docmancer.yaml",
    ),
)
@click.option("--all", "show_all", is_flag=True, default=False, help="Show every stored page/file source.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def list_cmd(show_all: bool, config_path: str | None):
    """List all indexed sources with their indexing dates."""
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    agent = _create_agent_or_raise_lock_error(config)
    entries = agent.list_sources_with_dates() if show_all else agent.list_grouped_sources_with_dates()
    if not entries:
        click.echo("No sources indexed yet.")
        return
    for entry in entries:
        source = entry["source"]
        if str(source).startswith("registry://"):
            pack_ref = str(source).removeprefix("registry://")
            click.echo(f"{entry['ingested_at']}  [pack] {pack_ref}")
        else:
            click.echo(f"{entry['ingested_at']}  {source}")


def _detail_trust_tier(detail: dict) -> str:
    pack = detail.get("pack") if isinstance(detail.get("pack"), dict) else detail
    trust = pack.get("trust_tier") or pack.get("trust", {}).get("tier")
    return str(trust or "community")


def _detail_latest_version(detail: dict) -> str | None:
    pack = detail.get("pack") if isinstance(detail.get("pack"), dict) else detail
    version = detail.get("version")
    if isinstance(version, dict):
        return str(version.get("version") or pack.get("latest_version"))
    return str(pack.get("latest_version")) if pack.get("latest_version") else None


def _install_downloaded_pack(config, archive_path: Path, download_info, detail: dict) -> dict:
    from docmancer.core.registry_errors import ChecksumMismatch, IncompatiblePack
    from docmancer.core.registry_models import PackMetadata, installed_pack_from_metadata
    from docmancer.core.sqlite_store import SQLiteStore

    actual_archive = _sha256(archive_path)
    if actual_archive != download_info.archive_sha256:
        archive_path.unlink(missing_ok=True)
        raise ChecksumMismatch(download_info.name, download_info.version, download_info.archive_sha256, actual_archive)

    extract_dir = Path(config.registry.cache_dir).expanduser() / "extracted" / download_info.name / download_info.version
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:*") as tar:
        tar.extractall(extract_dir)

    pack_json = extract_dir / "pack.json"
    index_db = extract_dir / "index.db"
    if not pack_json.exists() or not index_db.exists():
        raise click.ClickException("Downloaded pack is missing pack.json or index.db.")

    actual_index = _sha256(index_db)
    if actual_index != download_info.index_db_sha256:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise ChecksumMismatch(download_info.name, download_info.version, download_info.index_db_sha256, actual_index)

    metadata = PackMetadata.model_validate(json.loads(pack_json.read_text(encoding="utf-8")))
    if metadata.format_version != 1 or metadata.sqlite_schema_version != 1:
        raise IncompatiblePack(metadata.name, "format_version=1 sqlite_schema_version=1", f"{metadata.format_version}/{metadata.sqlite_schema_version}")

    store = SQLiteStore(config.index.db_path, extracted_dir=config.index.extracted_dir or None)
    docset_root = f"registry://{metadata.name}@{metadata.version}"
    section_count = store.import_pack_db(index_db, docset_root, Path(config.index.extracted_dir or store.extracted_dir) / "registry" / metadata.name / metadata.version)
    installed = installed_pack_from_metadata(
        metadata,
        registry_url=config.registry.url,
        archive_sha256=download_info.archive_sha256,
        extracted_path=extract_dir,
    )
    store.install_pack(installed)
    return {
        "name": metadata.name,
        "version": metadata.version,
        "trust_tier": metadata.trust.tier.value,
        "total_tokens": metadata.stats.total_tokens,
        "sections_count": metadata.stats.sections_count or section_count,
    }


def _pull_one(config, pack_ref: str, allow_community: bool, force: bool) -> dict:
    from docmancer.core.registry_errors import CommunityPackBlocked

    name, requested_version = _split_pack_ref(pack_ref)
    store = None
    try:
        from docmancer.core.sqlite_store import SQLiteStore

        store = SQLiteStore(config.index.db_path, extracted_dir=config.index.extracted_dir or None)
        installed = store.get_installed_pack(name, requested_version) if not force else None
        if installed:
            return {
                "name": installed["name"],
                "version": installed["version"],
                "trust_tier": installed["trust_tier"],
                "total_tokens": installed["total_tokens"],
                "sections_count": installed["sections_count"],
                "skipped": True,
            }
        client = _registry_client(config)
        detail = client.get_pack_detail(name, requested_version)
        trust_tier = _detail_trust_tier(detail)
        if trust_tier == "community" and not allow_community:
            raise CommunityPackBlocked(name)
        resolved_version = requested_version or _detail_latest_version(detail)
        info = client.get_download_info(name, resolved_version)
        archive_name = f"{info.name}-{info.version}.docmancer-pack"
        archive_path = Path(config.registry.cache_dir).expanduser() / archive_name
        client.download_archive(info.download_url, archive_path)
        return _install_downloaded_pack(config, archive_path, info, detail)
    except Exception as exc:
        _handle_registry_error(exc)
        raise


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Pull a registry pack into the local index.",
    epilog=format_examples(
        "docmancer pull react",
        "docmancer pull react@18.2",
        "docmancer pull --community",
        "docmancer pull react --save",
    ),
)
@click.argument("pack", required=False)
@click.option("--force", is_flag=True, default=False, help="Re-download even if already installed.")
@click.option("--community", is_flag=True, default=False, help="Allow community-trust packs.")
@click.option("--save", is_flag=True, default=False, help="Save the pack reference to docmancer.yaml.")
@click.option("--registry", "registry_url", default=None, help="Override registry URL.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def pull_cmd(pack: str | None, force: bool, community: bool, save: bool, registry_url: str | None, config_path: str | None):
    """Download prebuilt docs packs from the registry into the local index."""
    config_path = _effective_config(config_path)
    config_file = _resolve_config_file(config_path)
    config = _load_config(str(config_file))
    if registry_url:
        config.registry.url = registry_url

    refs = [pack] if pack else [f"{name}@{version}" for name, version in config.packs.items()]
    if not refs:
        click.echo("No packs declared. Use: docmancer pull <name>[@<version>]")
        return

    successes: list[dict] = []
    failures: list[tuple[str, str]] = []
    for ref in refs:
        try:
            result = _pull_one(config, ref, community, force)
            successes.append(result)
            state = "SKIP" if result.get("skipped") else "OK"
            click.echo(f"{result['name']}@{result['version']}  {result['trust_tier']}  [{state}] {result['sections_count']} sections ({result['total_tokens']} tokens)")
        except click.ClickException as exc:
            failures.append((ref, exc.message))
            click.echo(f"{ref}  [FAIL] {exc.message}", err=True)

    if save and pack and not failures:
        import yaml as _yaml

        name, version = _split_pack_ref(pack)
        data = _yaml.safe_load(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        data = data or {}
        data.setdefault("packs", {})[name] = version or successes[0]["version"]
        config_file.write_text(_yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
        click.echo(f"Saved {name}@{data['packs'][name]} to {display_path(config_file)}")

    if failures:
        raise click.ClickException(f"{len(successes)} succeeded, {len(failures)} failed.")
    total_tokens = sum(int(row.get("total_tokens") or 0) for row in successes)
    click.echo(f"{len(successes)} pack(s) installed ({total_tokens} tokens).")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Search the public registry.",
    epilog=format_examples(
        "docmancer search langchain",
        "docmancer search react --community",
        "docmancer search next --format json",
    ),
)
@click.argument("query")
@click.option("--limit", default=10, show_default=True, type=int, help="Maximum results.")
@click.option("--community", is_flag=True, default=False, help="Include community-trust packs.")
@click.option("--registry", "registry_url", default=None, help="Override registry URL.")
@click.option("output_format", "--format", type=click.Choice(["table", "json"], case_sensitive=False), default="table", show_default=True)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def search_cmd(query: str, limit: int, community: bool, registry_url: str | None, output_format: str, config_path: str | None):
    """Search registry packs without modifying the local index."""
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    if registry_url:
        config.registry.url = registry_url
    try:
        trust = "official,maintainer_verified,community" if community else "official,maintainer_verified"
        response = _registry_client(config).search(query, limit=limit, trust_tier=trust)
    except Exception as exc:
        _handle_registry_error(exc)
        return
    if output_format == "json":
        click.echo(response.model_dump_json(indent=2))
        return
    click.echo(f"Registry: {config.registry.url}")
    for item in response.results:
        click.echo(
            f"{item.name:24} {item.latest_version:10} {item.total_tokens:9} "
            f"{item.trust_tier.value:19} {item.pull_count:8}"
        )
    click.echo(f"{response.total} result(s) for \"{query}\"")


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Manage registry authentication.")
def auth_group():
    """Manage registry authentication."""


@auth_group.command("login", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--token", default=None, help="Store an existing registry token.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def auth_login_cmd(token: str | None, config_path: str | None):
    """Authenticate with the registry."""
    from docmancer.core.auth import save_auth_token
    from docmancer.core.registry_models import AuthToken

    config = _load_config(_effective_config(config_path))
    if token:
        save_auth_token(config.registry.auth_path, AuthToken(token=token))
        click.echo("Authenticated.")
        return
    try:
        client = _registry_client(config)
        device = client.start_device_auth()
        click.echo(f"Open: {device.verification_uri}")
        click.echo(f"Code: {device.user_code}")
        try:
            webbrowser.open(device.verification_uri)
        except Exception:
            pass
        deadline = time.time() + device.expires_in
        while time.time() < deadline:
            auth = client.poll_device_token(device.device_code)
            if auth:
                save_auth_token(config.registry.auth_path, auth)
                click.echo("Authenticated.")
                return
            time.sleep(max(1, device.interval))
    except Exception as exc:
        _handle_registry_error(exc)
    raise click.ClickException("Device authorization expired.")


@auth_group.command("logout", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def auth_logout_cmd(config_path: str | None):
    """Remove stored registry credentials."""
    from docmancer.core.auth import remove_auth_token

    config = _load_config(_effective_config(config_path))
    if remove_auth_token(config.registry.auth_path):
        click.echo("Logged out.")
    else:
        click.echo("Not authenticated.")


@auth_group.command("status", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def auth_status_cmd(config_path: str | None):
    """Show registry auth status without affecting local CLI behavior."""
    from docmancer.core.auth import load_auth_token
    from docmancer.core.registry_errors import AuthExpired, AuthRequired, RegistryUnreachable

    config = _load_config(_effective_config(config_path))
    auth = load_auth_token(config.registry.auth_path)
    if auth is None:
        click.echo("Not authenticated.")
        return
    try:
        status = _registry_client(config).get_user_status()
    except RegistryUnreachable:
        click.echo("Authenticated (token found). Registry unreachable, cannot verify tier.")
        return
    except (AuthExpired, AuthRequired):
        click.echo("Token expired or invalid. Run: docmancer auth login")
        return
    except Exception:
        click.echo("Authenticated (token found). Registry status unavailable.")
        return
    click.echo(f"Authenticated as {status.get('email') or status.get('username') or 'unknown'}")
    click.echo(f"Tier: {status.get('tier') or 'free'}")


@click.command(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Submit a docs URL to the registry.",
)
@click.argument("url")
@click.option("--name", default=None, help="Pack name.")
@click.option("--description", default=None, help="Short description.")
@click.option("--version", default=None, help="Library version.")
@click.option("--registry", "registry_url", default=None, help="Override registry URL.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def publish_cmd(url: str, name: str | None, description: str | None, version: str | None, registry_url: str | None, config_path: str | None):
    """Submit a docs URL for server-side community pack indexing."""
    from docmancer.core.auth import require_auth
    from docmancer.core.registry_client import RegistryClient
    from docmancer.core.registry_models import PublishRequest

    config = _load_config(_effective_config(config_path))
    if registry_url:
        config.registry.url = registry_url
    try:
        auth = require_auth(config.registry.auth_path)
        response = RegistryClient(config.registry, auth).publish(PublishRequest(url=url, name=name, description=description, version=version))
    except Exception as exc:
        _handle_registry_error(exc)
        return
    click.echo(f"Submitted {url} as {response.pack_name}.")
    click.echo(f"Trust tier: {response.trust_tier.value}")
    click.echo(f"Status: {response.status}")
    click.echo(f"Track: {response.track_url}")


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    invoke_without_command=True,
    short_help="List and sync installed registry packs.",
)
@click.pass_context
def packs_cmd(ctx: click.Context):
    """Manage locally installed registry packs."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(packs_list_cmd)


@packs_cmd.command("list", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def packs_list_cmd(config_path: str | None):
    """List locally installed registry packs."""
    from docmancer.core.sqlite_store import SQLiteStore

    config = _load_config(_effective_config(config_path))
    rows = SQLiteStore(config.index.db_path, extracted_dir=config.index.extracted_dir or None).list_installed_packs()
    if not rows:
        click.echo("No registry packs installed.")
        return
    total = 0
    for row in rows:
        total += int(row["total_tokens"] or 0)
        click.echo(f"{row['name']:24} {row['version']:10} {row['trust_tier']:19} {row['total_tokens']:9} {row['sections_count']:8} {row['installed_at']}")
    click.echo(f"{len(rows)} pack(s) installed ({total} tokens).")


@packs_cmd.command("sync", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS)
@click.option("--prune", is_flag=True, default=False, help="Remove packs not declared in the manifest.")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompts.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def packs_sync_cmd(prune: bool, yes: bool, config_path: str | None):
    """Sync locally installed packs with docmancer.yaml."""
    from docmancer.core.sqlite_store import SQLiteStore

    config = _load_config(_effective_config(config_path))
    store = SQLiteStore(config.index.db_path, extracted_dir=config.index.extracted_dir or None)
    installed = store.list_installed_packs()
    declared = {name: version for name, version in config.packs.items()}
    for name, version in declared.items():
        if not store.get_installed_pack(name, version):
            _pull_one(config, f"{name}@{version}", allow_community=False, force=False)
            click.echo(f"Installed {name}@{version}")
    orphans = [row for row in installed if declared.get(row["name"]) != row["version"]]
    if orphans and not prune:
        click.echo(f"{len(orphans)} orphaned pack(s). Re-run with --prune to remove them.")
    if orphans and prune:
        if yes or click.confirm(f"Remove {len(orphans)} orphaned pack(s)?", default=False):
            for row in orphans:
                store.uninstall_pack(row["name"], row["version"])
                click.echo(f"Removed {row['name']}@{row['version']}")


packs_cmd.add_command(packs_list_cmd, "list")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Audit a local pack archive or extracted directory.",
)
@click.argument("path")
def audit_cmd(path: str):
    """Scan a pack for risky content patterns."""
    target = Path(path)
    if not target.exists():
        raise click.ClickException(f"Path not found: {path}")
    patterns = {
        "secret file access": [".env", "id_rsa", "aws_secret_access_key"],
        "external command": ["curl ", "wget ", "subprocess", "os.system"],
        "destructive command": ["rm -rf", "shutil.rmtree"],
        "agent override": ["ignore previous instructions", "system prompt"],
    }
    texts: list[tuple[Path, str]] = []
    if target.is_file() and tarfile.is_tarfile(target):
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(target, "r:*") as tar:
                tar.extractall(tmp)
            for file in Path(tmp).rglob("*"):
                if file.suffix in {".md", ".json", ".txt"}:
                    texts.append((file, file.read_text(encoding="utf-8", errors="ignore")))
    elif target.is_dir():
        for file in target.rglob("*"):
            if file.suffix in {".md", ".json", ".txt"}:
                texts.append((file, file.read_text(encoding="utf-8", errors="ignore")))
    findings = []
    for file, text in texts:
        lower = text.lower()
        for label, needles in patterns.items():
            for needle in needles:
                if needle in lower:
                    findings.append((label, file, needle))
    if not findings:
        click.echo("PASS: no suspicious patterns found.")
        return
    for label, file, needle in findings:
        click.echo(f"WARN: {label}: {display_path(file)} contains {needle!r}")
    raise click.ClickException(f"{len(findings)} suspicious pattern(s) found.")


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
        "docmancer install github-copilot --project",
        "docmancer install opencode",
        "docmancer install cline",
    ),
)
@click.argument("agent", type=click.Choice(INSTALL_TARGETS, case_sensitive=False))
@click.option("--project", is_flag=True, default=False,
              help="Install in project-level settings (claude-code, gemini, cline, or github-copilot).")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def install_cmd(agent: str, project: bool, config_path: str | None):
    """Install docmancer skill files into an AI agent.

    Teaches the agent to call docmancer CLI commands directly. No server
    required. Run 'docmancer add <url-or-path>' first to populate the knowledge base.

    AGENT must be one of: claude-code, claude-desktop, cline, cursor, codex,
    codex-app, codex-desktop, gemini, github-copilot, opencode
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

    if normalized == "github-copilot":
        content = _build_skill_content("copilot_instructions.md", effective_config_path)
        if project:
            copilot_dest = Path(".github") / "copilot-instructions.md"
            agents_dest = Path("AGENTS.md")
            settings_dest = Path(".vscode") / "settings.json"
            _install_or_append_agents_md(copilot_dest, content)
            _install_or_append_agents_md(agents_dest, content)
            _install_vscode_copilot_settings(settings_dest)
            _emit_install_summary(
                "Install instructions for GitHub Copilot.",
                [
                    ("Updated Copilot repository instructions at", copilot_dest),
                    ("Updated Copilot coding-agent fallback at", agents_dest),
                    ("Enabled VS Code Copilot instruction files at", settings_dest),
                ],
                created_user_config,
                effective_config_path,
                "Reload VS Code or start a new Copilot Chat session if the instructions are not picked up immediately.",
                extra_lines=[
                    "Copilot Chat and code review use .github/copilot-instructions.md.",
                    "Copilot coding agent can also read AGENTS.md.",
                ],
            )
        else:
            dest = _get_copilot_user_instructions_path()
            _install_or_append_agents_md(dest, content)
            _emit_install_summary(
                "Install user instructions for GitHub Copilot CLI.",
                [("Updated Copilot user instructions at", dest)],
                created_user_config,
                effective_config_path,
                "Start a new Copilot CLI session for the instructions to take effect.",
                extra_lines=[
                    "For Copilot in VS Code, Xcode, JetBrains, or GitHub.com, run `docmancer install github-copilot --project` inside each repository.",
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


def _detect_setup_targets() -> list[str]:
    home = Path.home()
    targets: list[str] = []
    checks = [
        ("claude-code", home / ".claude"),
        ("cursor", home / ".cursor"),
        ("codex", home / ".codex"),
        ("cline", home / ".cline"),
        ("gemini", home / ".gemini"),
        ("opencode", home / ".config" / "opencode"),
    ]
    for target, path in checks:
        if path.exists():
            targets.append(target)
    # Claude Desktop has no stable skill directory to inspect, so include it
    # when its macOS support directory exists.
    if (home / "Library" / "Application Support" / "Claude").exists():
        targets.append("claude-desktop")
    vscode_ext_dir = home / ".vscode" / "extensions"
    vscode_app_dir = home / "Library" / "Application Support" / "Code"
    if (
        _get_copilot_user_instructions_path().parent.exists()
        or vscode_app_dir.exists()
        or (vscode_ext_dir.exists() and any(vscode_ext_dir.glob("github.copilot*")))
    ):
        targets.append("github-copilot")
    return targets


def _ensure_config_and_db(config_path: str | None) -> Path:
    config_file = Path(config_path).resolve() if config_path else _ensure_user_config().resolve()
    config = _get_config_class().from_yaml(config_file)
    agent = _get_agent_class()(config=config)
    agent.collection_stats()
    return config_file


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Set up docmancer for local agent docs retrieval.",
    epilog=format_examples(
        "docmancer setup",
        "docmancer setup --all",
        "docmancer setup --agent codex --agent claude-desktop",
    ),
)
@click.option("--all", "install_all", is_flag=True, default=False, help="Install every supported agent integration non-interactively.")
@click.option("--agent", "agents", multiple=True, type=click.Choice(INSTALL_TARGETS, case_sensitive=False), help="Agent integration to install. Can be repeated.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def setup_cmd(install_all: bool, agents: tuple[str, ...], config_path: str | None):
    """Create config/database and install selected agent skills."""
    config_path = _effective_config(config_path)
    config_file = _ensure_config_and_db(config_path)
    _emit_brand_header("docmancer setup", "Create the SQLite index and connect coding agents.")
    _emit_status_line(f"Config: {display_path(config_file)}")
    config = _get_config_class().from_yaml(config_file)
    _emit_status_line(f"SQLite index: {display_path(config.index.db_path)}")

    selected = [agent.lower() for agent in agents]
    if install_all:
        selected = list(INSTALL_TARGETS)
    elif not selected:
        detected = _detect_setup_targets()
        if detected:
            selected = detected
        elif click.confirm("No agent installs detected. Install Codex skill?", default=True):
            selected = ["codex"]

    if not selected:
        _emit_next_step("Run `docmancer pull <library>` for registry packs or `docmancer add <url-or-path>` for local indexing.")
        return

    for target in dict.fromkeys(selected):
        ctx = click.get_current_context()
        ctx.invoke(install_cmd, agent=target, project=(target == "github-copilot"), config_path=str(config_file))

    _emit_next_step("Run `docmancer pull <library>` or `docmancer add <url-or-path>`, then `docmancer query \"your question\"`.")
