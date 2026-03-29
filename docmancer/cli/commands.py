from __future__ import annotations

import os
import shlex
import shutil
import sys
import zipfile
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, HELP_CONTEXT_SETTINGS, format_examples

INSTALL_TARGETS = [
    "claude-code",
    "claude-desktop",
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
    return f"local embedded Qdrant at {config.vector_store.local_path}"


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
    ),
)
@click.option("--dir", "directory", default=".", help="Target directory for the config file.")
def init_cmd(directory: str):
    """Initialize a docmancer project with a config file."""
    import yaml as _yaml

    dir_path = Path(directory)
    dir_path.mkdir(parents=True, exist_ok=True)
    config_path = dir_path / "docmancer.yaml"
    if config_path.exists():
        click.echo(f"Config already exists at {config_path}")
        return
    DocmancerConfig = _get_config_class()
    config = DocmancerConfig()
    data = config.model_dump()
    with open(config_path, "w") as f:
        _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    click.echo(f"Created config at {config_path}")
    click.echo("No API keys required — embeddings run fully locally.")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Ingest docs from a path or URL.",
    epilog=format_examples(
        "docmancer ingest ./docs",
        "docmancer ingest https://docs.example.com",
        "docmancer ingest ./docs --recreate",
    ),
)
@click.argument("path")
@click.option("--recreate", is_flag=True, help="Recreate the collection first.")
@click.option("--provider", default="auto", show_default=True,
              type=click.Choice(["auto", "gitbook", "mintlify"], case_sensitive=False),
              help="Docs platform. auto tries llms.txt then sitemap.xml.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def ingest_cmd(path: str, recreate: bool, provider: str, config_path: str | None):
    """Ingest documents from a file, directory, or URL."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)

    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)

    try:
        if path.startswith("http://") or path.startswith("https://"):
            click.echo(f"Fetching docs from {path}...")
            total = agent.ingest_url(path, recreate=recreate, provider=provider if provider != "auto" else None)
        else:
            total = agent.ingest(path, recreate=recreate)
        click.echo(f"Total: {total} chunks ingested")
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Download GitBook docs to Markdown files.",
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
        click.echo(f"  Saved {file_path}")

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
    config = _load_config(config_path)
    home = Path.home()

    # Binary resolution
    resolved_bin = shutil.which("docmancer")
    if resolved_bin:
        click.echo(f"  [OK] docmancer binary: {resolved_bin}")
    else:
        click.echo("  [--] docmancer not found on PATH (install with: pipx install docmancer)")

    # Effective config
    if config_path:
        effective_config = Path(config_path)
    elif Path("docmancer.yaml").exists():
        effective_config = Path("docmancer.yaml")
    else:
        effective_config = _get_user_config_path()
    click.echo(f"  [OK] Config: {effective_config}")

    # Vector store
    click.echo(f"  [OK] Vector store: {_describe_vector_store(config)}")

    if config.vector_store.url:
        try:
            QdrantClient = _get_qdrant_client_class()
            client = QdrantClient(url=config.vector_store.url, timeout=3)
            client.get_collections()
            click.echo(f"  [OK] Qdrant reachable at {config.vector_store.url}")
        except Exception:
            click.echo(f"  [--] Qdrant not reachable at {config.vector_store.url}")
    else:
        qdrant_path = Path(config.vector_store.local_path)
        if qdrant_path.exists():
            click.echo(f"  [OK] Embedded Qdrant data at {qdrant_path}")
        else:
            click.echo(f"  [--] No Qdrant data yet at {qdrant_path} (run: docmancer ingest)")

    # Skill install status
    click.echo("  Installed skills:")
    skill_locations = [
        ("claude-code", "claude-code", home / ".claude" / "skills" / "docmancer" / "SKILL.md"),
        ("cursor", "cursor", home / ".cursor" / "skills" / "docmancer" / "SKILL.md"),
        ("codex", "codex", _get_codex_skill_path()),
        ("codex-shared", "codex", _get_shared_agent_skill_path()),
        ("gemini", "gemini", _get_gemini_skill_path()),
        ("opencode", "opencode", home / ".config" / "opencode" / "skills" / "docmancer" / "SKILL.md"),
        ("claude-desktop", "claude-desktop", _get_user_config_dir() / "exports" / "claude-desktop" / "docmancer.zip"),
    ]
    for label, install_target, path in skill_locations:
        if path.exists():
            click.echo(f"    [OK] {label}: {path}")
        else:
            click.echo(f"    [--] {label}: not installed (run: docmancer install {install_target})")


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
def query_cmd(text: str, config_path: str | None, limit: int | None, full: bool):
    """Run a retrieval query against the vector store (no server required)."""
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)
    chunks = agent.query(text, limit=limit)

    if not chunks:
        click.echo("No results found.")
        sys.exit(1)

    for i, chunk in enumerate(chunks, start=1):
        if full:
            body = chunk.text
        else:
            body = chunk.text[:1500] + "..." if len(chunk.text) > 1500 else chunk.text
        click.echo(f"[{i}] score={chunk.score:.2f}  source={chunk.source}")
        click.echo(body)
        click.echo("---")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove an ingested source.",
    epilog=format_examples(
        "docmancer remove https://docs.example.com/page",
        "docmancer remove ./docs/getting-started.md",
    ),
)
@click.argument("source")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def remove_cmd(source: str, config_path: str | None):
    """Remove an ingested source (URL or file path) from the knowledge base."""
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)
    deleted = agent.remove_source(source)
    if deleted:
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
        "docmancer list --config ./docmancer.yaml",
    ),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def list_cmd(config_path: str | None):
    """List all ingested sources with their ingestion dates."""
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)
    entries = agent.list_sources_with_dates()
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
    ),
)
@click.argument("agent", type=click.Choice(INSTALL_TARGETS, case_sensitive=False))
@click.option("--project", is_flag=True, default=False,
              help="Install in project-level settings (claude-code only).")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def install_cmd(agent: str, project: bool, config_path: str | None):
    """Install docmancer skill files into an AI agent.

    Teaches the agent to call docmancer CLI commands directly — no server
    required. Run 'docmancer ingest <url>' first to populate the knowledge base.

    AGENT must be one of: claude-code, claude-desktop, cursor, codex,
    codex-app, codex-desktop, gemini, opencode
    """
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
        click.echo(f"Created docmancer skill package at {zip_path}")
        if created_user_config:
            click.echo(f"  Created user config at {_get_user_config_path()}")
        elif effective_config_path is not None:
            click.echo(f"  Skill package uses config {effective_config_path}")
        click.echo("")
        click.echo("To install in Claude Desktop:")
        click.echo("  1. Open Claude Desktop")
        click.echo("  2. Go to Customize > Skills")
        click.echo('  3. Click "+" and select "Upload a skill"')
        click.echo(f"  4. Upload: {zip_path}")
        return

    if normalized == "claude-code":
        if project:
            dest = Path(".claude") / "skills" / "docmancer" / "SKILL.md"
        else:
            dest = home / ".claude" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("claude_code_skill.md", effective_config_path)
        _install_skill_file(content, dest)
        click.echo(f"Installed docmancer skill at {dest}")
        if created_user_config:
            click.echo(f"  Created user config at {_get_user_config_path()}")
        elif effective_config_path is not None:
            click.echo(f"  Skill uses config {effective_config_path}")
        click.echo("  Claude Code will automatically use docmancer commands.")
        click.echo("  No restart needed.")
        return

    if normalized in {"codex", "codex-app", "codex-desktop"}:
        dest = _get_codex_skill_path()
        shared_dest = _get_shared_agent_skill_path()
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)
        _install_skill_file(content, shared_dest)
        click.echo(f"Installed docmancer skill at {dest}")
        click.echo(f"  Also installed shared compatibility skill at {shared_dest}")
        if created_user_config:
            click.echo(f"  Created user config at {_get_user_config_path()}")
        elif effective_config_path is not None:
            click.echo(f"  Skill uses config {effective_config_path}")
        click.echo("  Codex will automatically use docmancer commands.")
        return

    if normalized == "cursor":
        dest = home / ".cursor" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)
        click.echo(f"Installed docmancer skill at {dest}")

        # Also write AGENTS.md fallback while Cursor's skill discovery matures
        agents_md = home / ".cursor" / "AGENTS.md"
        agents_body = _get_template_content("cursor_agents_md.md").replace(
            "{{DOCS_KIT_CMD}}", _resolve_skill_command(effective_config_path)
        )
        _install_or_append_agents_md(agents_md, agents_body)
        click.echo(f"  Updated fallback at {agents_md}")
        if created_user_config:
            click.echo(f"  Created user config at {_get_user_config_path()}")
        elif effective_config_path is not None:
            click.echo(f"  Skill uses config {effective_config_path}")
        click.echo("  Restart Cursor for changes to take effect.")
        return

    if normalized == "gemini":
        if project:
            dest = Path(".gemini") / "skills" / "docmancer" / "SKILL.md"
        else:
            dest = home / ".gemini" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)
        click.echo(f"Installed docmancer skill at {dest}")

        # Also write to shared ~/.agents/skills/ path if not already installed
        shared_dest = _get_shared_agent_skill_path()
        if not shared_dest.exists():
            _install_skill_file(content, shared_dest)
            click.echo(f"  Also installed at shared path {shared_dest}")

        if created_user_config:
            click.echo(f"  Created user config at {_get_user_config_path()}")
        elif effective_config_path is not None:
            click.echo(f"  Skill uses config {effective_config_path}")
        click.echo("  Gemini CLI will automatically use docmancer commands.")
        return

    if normalized == "opencode":
        dest = home / ".config" / "opencode" / "skills" / "docmancer" / "SKILL.md"
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)
        click.echo(f"Installed docmancer skill at {dest}")

        # Also write to shared ~/.agents/skills/ path if not already installed by codex
        shared_dest = _get_shared_agent_skill_path()
        if not shared_dest.exists():
            _install_skill_file(content, shared_dest)
            click.echo(f"  Also installed at shared path {shared_dest}")

        if created_user_config:
            click.echo(f"  Created user config at {_get_user_config_path()}")
        elif effective_config_path is not None:
            click.echo(f"  Skill uses config {effective_config_path}")
        click.echo("  OpenCode will automatically use docmancer commands.")
        return
