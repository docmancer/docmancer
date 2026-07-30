from __future__ import annotations

import os
import json
import logging
import shlex
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path
from time import monotonic

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.ui import (
    LiveStatus,
    color_enabled,
    display_path,
    emit_brand_header,
    emit_status_line,
    style,
)


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

# Set to True by setup_cmd before invoking install_cmd in a loop so that
# each individual install does not re-emit the banner or a per-agent next-step.
_INSTALL_QUIET: bool = False


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


def _shared_skill_coverage(installed_for: str) -> str | None:
    """Describe other detected agents covered by the shared skill bundle."""
    home = Path.home()
    checks = {
        "codex": home / ".codex",
        "gemini": home / ".gemini",
        "opencode": home / ".config" / "opencode",
    }
    covered = [name for name, path in checks.items() if name != installed_for and path.exists()]
    if not covered:
        return None
    return "The shared skill also covers " + ", ".join(covered) + "; no separate install is required."


def _get_gemini_skill_path() -> Path:
    return Path.home() / ".gemini" / "skills" / "docmancer" / "SKILL.md"


def _get_cline_skill_path() -> Path:
    return Path.home() / ".cline" / "skills" / "docmancer" / "SKILL.md"


def _get_copilot_user_instructions_path() -> Path:
    return Path.home() / ".copilot" / "copilot-instructions.md"


_EMBEDDING_PROVIDER_DEFAULTS = {
    "model2vec": ("minishlab/potion-base-8M", 256),
    "fastembed": ("BAAI/bge-base-en-v1.5", 768),
    "openai": ("text-embedding-3-small", 1536),
    "voyage": ("voyage-3", 1024),
    "cohere": ("embed-english-v3.0", 1024),
}


def _apply_embedding_provider_shortcut(config, provider: str) -> None:
    """Set provider/model/dimensions defaults on a config's embeddings block.

    Never writes API keys; credentials only ever come from the provider's env
    var.
    """
    model, dims = _EMBEDDING_PROVIDER_DEFAULTS.get(provider, (None, None))
    config.embeddings.provider = provider
    if model:
        config.embeddings.model = model
    if dims:
        config.embeddings.dimensions = dims


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


def _enable_automatic_capture(config_path: Path) -> None:
    """Persist the setup-approved capture defaults without replacing other config."""
    import tempfile

    import yaml as _yaml
    from filelock import FileLock

    path = Path(config_path).expanduser().resolve()
    lock = FileLock(str(path) + ".lock", timeout=10)
    temporary: Path | None = None
    with lock:
        loaded = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data = loaded if isinstance(loaded, dict) else {}
        capture = data.get("capture")
        if not isinstance(capture, dict):
            capture = {}
        enabled = capture.get("enabled")
        if not isinstance(enabled, dict):
            enabled = {}
        enabled.update({"claude-code": True, "codex": True})
        capture["enabled"] = enabled
        data["capture"] = capture
        content = _yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _persist_retrieval_profile(config_path: Path, profile: str) -> None:
    """Persist an explicit local or scale retrieval profile atomically."""
    import tempfile

    import yaml as _yaml
    from filelock import FileLock

    path = Path(config_path).expanduser().resolve()
    lock = FileLock(str(path) + ".lock", timeout=10)
    temporary: Path | None = None
    with lock:
        loaded = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data = loaded if isinstance(loaded, dict) else {}
        retrieval = data.get("retrieval")
        if not isinstance(retrieval, dict):
            retrieval = {}
        retrieval["profile"] = profile
        data["retrieval"] = retrieval

        if profile == "scale":
            index = data.get("index")
            if not isinstance(index, dict):
                index = {}
            index["persist_extracted"] = False
            data["index"] = index

            vector_store = data.get("vector_store")
            if not isinstance(vector_store, dict):
                vector_store = {}
            vector_store.update({"provider": "qdrant", "collection": "docmancer"})
            vector_store.pop("db_path", None)
            vector_store.pop("local_path", None)
            data["vector_store"] = vector_store

            embeddings = data.get("embeddings")
            if not isinstance(embeddings, dict):
                embeddings = {}
            embeddings.update(
                {
                    "provider": "fastembed",
                    "model": "BAAI/bge-base-en-v1.5",
                    "dimensions": 768,
                    "sparse_model": "prithivida/Splade_PP_en_v1",
                }
            )
            data["embeddings"] = embeddings
        else:
            index = data.get("index")
            if not isinstance(index, dict):
                index = {}
            index["persist_extracted"] = True
            data["index"] = index
            data["vector_store"] = {
                "provider": "sqlite-vec",
                "options": {
                    "db_path": str((_get_user_config_dir() / "memory-vec.db").resolve())
                },
            }
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, dict):
                embeddings = {}
            embeddings.update(
                {
                    "provider": "model2vec",
                    "model": "minishlab/potion-base-8M",
                    "dimensions": 256,
                    "sparse_model": None,
                }
            )
            data["embeddings"] = embeddings

        content = _yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


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


def _effective_retrieval_mode(mode: str | None, config) -> str:
    if mode:
        return mode.lower()
    configured = getattr(getattr(config, "retrieval", None), "default_mode", None)
    if isinstance(configured, str) and configured:
        return configured.lower()
    return "lexical"


def _run_dispatch_query(
    *,
    agent,
    config,
    query: str,
    mode: str,
    limit: int | None,
    budget: int | None,
    expand: str | None,
    allow_degraded: bool = False,
):
    """Build a RetrievalDispatcher, run it, return (chunks, contributions, failures).

    Falls back to lexical-only if the embeddings provider or vector store
    cannot be *constructed*. Runtime retrieval failures (dimension mismatch,
    Qdrant down) propagate to the caller in non-lexical modes unless the caller
    sets ``allow_degraded=True``.
    """
    try:
        from docmancer.embeddings import get_embeddings_provider
        from docmancer.retrieval.dispatch import HybridRetrievalError, RetrievalDispatcher
        from docmancer.runtime.qdrant_manager import ensure_running
        from docmancer.stores.base import get_vector_store
    except ImportError:
        return agent.query(query, limit=limit, budget=budget, expand=expand), {}, {}

    vs_config = agent.resolve_vector_store_config()
    if vs_config.provider == "qdrant" and not vs_config.url:
        resolution = ensure_running()
        if resolution.fallback or not resolution.url:
            vs_config = vs_config.model_copy(update={"provider": "sqlite-vec"})
        else:
            vs_config = vs_config.model_copy(update={"url": resolution.url})

    try:
        vector_store = get_vector_store(vs_config, embeddings_dim=config.embeddings.dimensions)
        provider = get_embeddings_provider(config.embeddings)
    except Exception as exc:
        failures = {"vector": f"{type(exc).__name__}: {exc}"}
        if allow_degraded:
            return agent.query(query, limit=limit, budget=budget, expand=expand), {}, failures
        raise HybridRetrievalError(failures) from exc

    collection = agent._vector_collection_name()
    dispatcher = RetrievalDispatcher(
        store=agent.store,
        config=config,
        vector_store=vector_store,
        provider=provider,
        collection=collection,
    )
    result = dispatcher.run(
        query,
        mode=mode,
        limit=limit,
        budget=budget,
        expand=expand,
        allow_degraded=allow_degraded,
    )
    return result.chunks, result.contributions, result.failures


def _can_default_query_fallback(exc: Exception) -> bool:
    """Whether a default-mode query may silently fall back to lexical.

    The default retrieval mode is hybrid, but users can explicitly build an
    FTS5-only index with ``ingest --no-vectors``. A plain ``docmancer docs query``
    should still work in that state. Explicit vector modes remain strict unless
    the caller passes ``--allow-degraded``.
    """
    failures = getattr(exc, "failures", None)
    if not isinstance(failures, dict) or set(failures) != {"vector"}:
        return False
    message = str(failures.get("vector", ""))
    return (
        "is not docmancer-owned" in message
        or "has no indexed vectors" in message
    )


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
    emit_brand_header(command, subtitle)


def _emit_status_line(message: str, state: str = "ok", indent: int = 2) -> None:
    emit_status_line(message, state=state, indent=indent)


def _emit_next_step(text: str) -> None:
    click.echo()
    click.echo(_style("  Next:", fg="bright_green", bold=True) + f" {text}")


def _loader_availability() -> list[tuple[str, bool, str]]:
    checks = [
        ("txt", find_spec("charset_normalizer") is not None, "reinstall docmancer; charset-normalizer ships in core"),
        ("pdf", find_spec("pypdf") is not None, "reinstall docmancer; pypdf ships in core"),
        ("pdf fallback", find_spec("pdfplumber") is not None, "reinstall docmancer; pdfplumber ships in core"),
        ("docx", find_spec("docx") is not None, "reinstall docmancer; python-docx ships in core"),
        ("rtf", find_spec("striprtf") is not None, "reinstall docmancer; striprtf ships in core"),
        ("html", True, "built in"),
        ("markdown", True, "built in"),
    ]
    return checks


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
        if lower.startswith("embedding ") or lower.startswith("vectors:"):
            return _style("[embed] ", fg="bright_cyan", bold=True) + message
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
    for noisy_logger in ("httpx", "httpcore", "qdrant_client"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def _emit_install_summary(
    heading: str,
    installed_paths: list[tuple[str, Path]],
    created_user_config: bool,
    effective_config_path: Path | None,
    next_step: str,
    extra_lines: list[str] | None = None,
) -> None:
    if _INSTALL_QUIET:
        # Called from setup_cmd: print a compact section header instead of the full banner.
        click.echo()
        click.echo(_style(f"  {heading}", fg="white", bold=True))
    else:
        _emit_brand_header("docmancer agent install", heading)
    for label, path in installed_paths:
        _emit_status_line(f"{label}: {display_path(path)}")
    if created_user_config:
        _emit_status_line(f"Created user config at {display_path(_get_user_config_path())}")
    elif effective_config_path is not None:
        _emit_status_line(f"Skill uses config {display_path(effective_config_path)}")
    for line in extra_lines or []:
        _emit_status_line(line, state="info")
    if not _INSTALL_QUIET:
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


def _install_or_append_agents_md(dest: Path, content_body: str) -> Path | None:
    """Idempotently write docmancer's managed block into an always-loaded file.

    Delegates to the shared :mod:`docmancer.cli.managed_block` helper so install
    edits to user-owned files (``~/.cursor/AGENTS.md``, ``~/.codex/AGENTS.md``,
    ``CLAUDE.md``) get the same backup safety as ``memory apply``. A timestamped
    backup is taken the first time we touch a non-empty user file; idempotent
    re-installs that only replace our own block do not litter backups. Returns
    the backup path when one was written.
    """
    from docmancer._version import __version__
    from docmancer.cli.managed_block import upsert_block

    _action, backup_path = upsert_block(
        dest,
        content_body,
        begin=_AGENTS_MD_START,
        end=_AGENTS_MD_END,
        backup_policy="foreign-content",
        version=__version__,
    )
    return backup_path


def _instruction_block_targets(home: Path) -> list[dict]:
    """Global instruction-block locations docmancer may own, one per agent family.

    ``codex``, ``codex-app``, and ``codex-desktop`` all write the same shared
    ``~/.codex/AGENTS.md`` block, so they are represented once under ``codex``.
    """
    return [
        {"agent": "claude-code", "path": home / ".claude" / "CLAUDE.md", "template": "claude_code_instruction.md"},
        {"agent": "codex", "path": home / ".codex" / "AGENTS.md", "template": "codex_agents_md.md"},
        {"agent": "cursor", "path": home / ".cursor" / "AGENTS.md", "template": "cursor_agents_md.md"},
        {"agent": "github-copilot", "path": home / ".copilot" / "copilot-instructions.md", "template": "copilot_instructions.md"},
    ]


def check_instruction_block_drift(*, home: Path | None = None) -> list[dict]:
    """Report the installed-vs-current version stamp for every owned instruction block.

    Only targets that already contain a docmancer-managed block are reported;
    a target that was never installed is not drift, it is an install gap
    already surfaced by ``docmancer doctor``'s skill-install checks.
    """
    from docmancer._version import __version__
    from docmancer.cli.managed_block import installed_block_version

    home = home or Path.home()
    rows = []
    for target in _instruction_block_targets(home):
        path = target["path"]
        if not path.exists():
            continue
        installed_version = installed_block_version(path, begin=_AGENTS_MD_START, end=_AGENTS_MD_END)
        if installed_version is None and _AGENTS_MD_START not in path.read_text(encoding="utf-8"):
            continue  # no docmancer block here at all
        rows.append({
            "agent": target["agent"],
            "path": str(path),
            "installed_version": installed_version,
            "current_version": __version__,
            "stale": installed_version != __version__,
        })
    return rows


def refresh_stale_instruction_blocks(*, config_path: str | Path | None = None, home: Path | None = None) -> list[dict]:
    """Regenerate any owned instruction block whose version stamp is missing or stale.

    Called from ``setup``, ``status``, and ``doctor`` so drift never survives
    past the next time any of those commands runs. Returns the refreshed rows.
    """
    from docmancer._version import __version__
    from docmancer.cli.managed_block import upsert_block

    home = home or Path.home()
    effective_config_path = config_path or _get_user_config_path()
    refreshed = []
    for row in check_instruction_block_drift(home=home):
        if not row["stale"]:
            continue
        target = next(t for t in _instruction_block_targets(home) if t["agent"] == row["agent"])
        try:
            content = _build_skill_content(target["template"], effective_config_path)
            # Always back up here, even though a routine reinstall of an already
            # foreign-marked file would not: this is an unattended refresh
            # triggered by setup/status/doctor rather than an explicit install,
            # so the prior content is worth keeping one copy of no matter what.
            upsert_block(
                target["path"],
                content,
                begin=_AGENTS_MD_START,
                end=_AGENTS_MD_END,
                backup_policy="always",
                version=__version__,
            )
        except Exception as exc:  # noqa: BLE001
            # One unreadable template or read-only target must not take down
            # status, doctor, and setup. Report the failure as unresolved drift.
            refreshed.append({**row, "refreshed_to": None, "error": str(exc)})
            continue
        refreshed.append({**row, "refreshed_to": __version__})
    return refreshed


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


_HOOK_COMMAND_MARKER = "memory hook-context"
_SESSION_BASELINE_COMMAND_MARKER = "session-baseline"
_CAPTURE_HOOK_COMMAND_MARKER = " capture"
_LEGACY_CAPTURE_HOOK_COMMAND_MARKER = "memory capture-hook"


def _hook_command(agent: str, config_path: str | Path | None) -> str:
    return f"{_resolve_skill_command(config_path)} memory hook-context --agent {shlex.quote(agent)}"


def _session_baseline_command(agent: str, config_path: str | Path | None) -> str:
    return f"{_resolve_skill_command(config_path)} session-baseline --agent {shlex.quote(agent)}"


def _capture_hook_command(agent: str, config_path: str | Path | None) -> str:
    del agent
    return f"{_resolve_skill_command(config_path)} capture"


def _load_json_object(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Could not update {display_path(path)} because it is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise click.ClickException(f"Could not update {display_path(path)} because it must contain a JSON object.")
    return data


def _is_docmancer_hook(handler: object, marker: str | None = None) -> bool:
    command = str(handler.get("command") or "") if isinstance(handler, dict) else ""
    if marker:
        if marker == _CAPTURE_HOOK_COMMAND_MARKER:
            return marker in command or _LEGACY_CAPTURE_HOOK_COMMAND_MARKER in command
        return marker in command
    return (
        _HOOK_COMMAND_MARKER in command
        or _SESSION_BASELINE_COMMAND_MARKER in command
        or _CAPTURE_HOOK_COMMAND_MARKER in command
        or _LEGACY_CAPTURE_HOOK_COMMAND_MARKER in command
    )


def _install_hook_json(path: Path, *, event: str, command: str, status: str, matcher: str | None = None, timeout: int = 2) -> bool:
    data = _load_json_object(path)
    hooks_root = data.setdefault("hooks", {})
    if not isinstance(hooks_root, dict):
        raise click.ClickException(f"Could not update {display_path(path)} because hooks must be a JSON object.")
    groups = hooks_root.setdefault(event, [])
    if not isinstance(groups, list):
        raise click.ClickException(f"Could not update {display_path(path)} because hooks.{event} must be a list.")

    for group in groups:
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks")
        if _CAPTURE_HOOK_COMMAND_MARKER in command:
            marker = _CAPTURE_HOOK_COMMAND_MARKER
        elif _SESSION_BASELINE_COMMAND_MARKER in command:
            marker = _SESSION_BASELINE_COMMAND_MARKER
        else:
            marker = _HOOK_COMMAND_MARKER
        if isinstance(handlers, list) and any(_is_docmancer_hook(handler, marker) for handler in handlers):
            return False

    group: dict[str, object] = {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": timeout,
                "statusMessage": status,
            }
        ]
    }
    if matcher is not None:
        group["matcher"] = matcher
    groups.append(group)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def _remove_hook_json(path: Path, *, marker: str | None = None) -> bool:
    if not path.exists():
        return False
    data = _load_json_object(path)
    hooks_root = data.get("hooks")
    if not isinstance(hooks_root, dict):
        return False
    changed = False
    for event, groups in list(hooks_root.items()):
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                kept_groups.append(group)
                continue
            kept_handlers = [handler for handler in handlers if not _is_docmancer_hook(handler, marker)]
            if len(kept_handlers) != len(handlers):
                changed = True
            if kept_handlers:
                updated = dict(group)
                updated["hooks"] = kept_handlers
                kept_groups.append(updated)
        if kept_groups:
            hooks_root[event] = kept_groups
        else:
            hooks_root.pop(event, None)
    if not changed:
        return False
    if not hooks_root:
        data.pop("hooks", None)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def _install_agent_hooks(agent: str, *, project: bool, config_path: str | Path | None) -> list[tuple[str, Path]]:
    home = Path.home()
    if agent == "claude-code":
        path = (Path(".claude") / "settings.json") if project else (home / ".claude" / "settings.json")
        baseline_command = _session_baseline_command("claude-code", config_path)
        prompt_command = _hook_command("claude-code", config_path)
        installed = []
        if _install_hook_json(path, event="SessionStart", command=baseline_command, status="Loading curated docmancer context"):
            installed.append(("Installed Claude Code SessionStart hook at", path))
        if _install_hook_json(path, event="UserPromptSubmit", command=prompt_command, status="Searching docmancer memory"):
            installed.append(("Installed Claude Code UserPromptSubmit hook at", path))
        return installed or [("Docmancer hooks already present at", path)]
    if agent == "codex":
        path = (Path(".codex") / "hooks.json") if project else (home / ".codex" / "hooks.json")
        baseline_command = _session_baseline_command("codex", config_path)
        prompt_command = _hook_command("codex", config_path)
        installed = []
        if _install_hook_json(path, event="SessionStart", command=baseline_command, status="Loading curated docmancer context", matcher="startup|resume"):
            installed.append(("Installed Codex SessionStart hook at", path))
        if _install_hook_json(path, event="UserPromptSubmit", command=prompt_command, status="Searching docmancer memory"):
            installed.append(("Installed Codex UserPromptSubmit hook at", path))
        return installed or [("Docmancer hooks already present at", path)]
    raise click.ClickException("--hooks is currently supported for claude-code and codex.")


def _install_capture_hooks(agent: str, *, project: bool, config_path: str | Path | None) -> list[tuple[str, Path]]:
    home = Path.home()
    if agent == "claude-code":
        path = (Path(".claude") / "settings.json") if project else (home / ".claude" / "settings.json")
        command = _capture_hook_command("claude-code", config_path)
        events = [("PostCompact", "Capturing compacted memory"), ("SessionEnd", "Saving session memory")]
    elif agent == "codex":
        path = (Path(".codex") / "hooks.json") if project else (home / ".codex" / "hooks.json")
        command = _capture_hook_command("codex", config_path)
        events = [("PreCompact", "Capturing memory before compaction"), ("Stop", "Saving durable memory")]
    else:
        raise click.ClickException("--capture-hooks is currently supported for claude-code and codex.")
    installed = []
    for event, status in events:
        if _install_hook_json(path, event=event, command=command, status=status, timeout=10):
            installed.append((f"Installed {agent} {event} capture hook at", path))
    return installed or [("Docmancer capture hooks already present at", path)]


def _remove_agent_hooks(agent: str, *, project: bool, capture_only: bool = False) -> list[tuple[str, Path]]:
    home = Path.home()
    if agent == "claude-code":
        path = (Path(".claude") / "settings.json") if project else (home / ".claude" / "settings.json")
    elif agent == "codex":
        path = (Path(".codex") / "hooks.json") if project else (home / ".codex" / "hooks.json")
    else:
        raise click.ClickException("--hooks removal is currently supported for claude-code and codex.")
    marker = _CAPTURE_HOOK_COMMAND_MARKER if capture_only else None
    if _remove_hook_json(path, marker=marker):
        label = "Removed docmancer capture hooks from" if capture_only else "Removed all docmancer hooks from"
        return [(label, path)]
    label = "No docmancer capture hooks found at" if capture_only else "No docmancer hooks found at"
    return [(label, path)]


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
@click.option(
    "--embedding-provider",
    "embedding_provider",
    type=click.Choice(["model2vec", "fastembed", "openai", "voyage", "cohere"], case_sensitive=False),
    default=None,
    help="Set the embeddings provider in the generated config (default model2vec).",
)
def init_cmd(directory: str | None, embedding_provider: str | None):
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
    if embedding_provider:
        _apply_embedding_provider_shortcut(config, embedding_provider.lower())
    data = config.model_dump()
    with open(config_path, "w") as f:
        _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    click.echo(f"Created config at {display_path(config_path)}")
    click.echo("Local SQLite FTS5 index configured at .docmancer/docmancer.db")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Add local or URL docs to the local SQLite index.",
    epilog=format_examples(
        "docmancer docs add https://docs.example.com",
        "docmancer docs add ./docs",
        "docmancer docs add https://github.com/owner/repo",
        "docmancer docs add https://docs.example.com --max-pages 200",
    ),
)
@click.argument("path")
@click.option("--recreate", is_flag=True, help="Recreate the collection first.")
@click.option("--include", "include_patterns", multiple=True, help="Glob pattern to include for a local path.")
@click.option("--exclude", "exclude_patterns", multiple=True, help="Glob pattern to exclude for a local path.")
@click.option(
    "--format",
    "formats",
    multiple=True,
    type=click.Choice(["md", "markdown", "txt", "pdf", "docx", "rtf", "html", "htm"], case_sensitive=False),
    help="Restrict local ingest to one or more file formats.",
)
@click.option("--recursive/--no-recursive", default=True, show_default=True, help="Recurse through local directories.")
@click.option("--skip-known", is_flag=True, help="Skip local files whose content hash is already indexed.")
@click.option("--no-vectors", is_flag=True, help="Index local files with FTS5 only.")
@click.option("--provider", default="auto", show_default=True,
              type=click.Choice(["auto", "gitbook", "mintlify", "web", "github", "crawl4ai"], case_sensitive=False),
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
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    formats: tuple[str, ...],
    recursive: bool,
    skip_known: bool,
    no_vectors: bool,
    provider: str,
    config_path: str | None,
    max_pages: int,
    strategy: str | None,
    browser: bool,
    fetch_workers: int | None,
):
    """Add documents from a local path, documentation URL, or GitHub repository."""
    config_path = _effective_config(config_path)
    _configure_ingest_logging()

    config = _load_config(config_path)
    if fetch_workers is not None:
        config.web_fetch.workers = fetch_workers
    agent = _get_agent_class()(config=config)

    try:
        if path.startswith("http://") or path.startswith("https://"):
            if include_patterns or exclude_patterns or formats or not recursive or skip_known or no_vectors:
                raise click.UsageError("local file options cannot be used with a documentation URL")
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
            if recreate and not no_vectors:
                _drop_vector_collection(config, agent)
            total = agent.ingest(
                path,
                recreate=recreate,
                include=include_patterns,
                exclude=exclude_patterns,
                formats=formats,
                recursive=recursive,
                skip_known=skip_known,
                with_vectors=not no_vectors,
            )
        _emit_index_summary(total, agent)
        if getattr(agent, "last_ingest_skips", None):
            report_path = getattr(agent, "last_ingest_report_path", None)
            click.echo(f"Skipped {len(agent.last_ingest_skips)} file(s). Report: {display_path(report_path)}")
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Refresh all or specific indexed docs sources.",
    epilog=format_examples(
        "docmancer docs sync",
        "docmancer docs sync https://docs.example.com",
        "docmancer docs sync ./docs",
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
        click.echo("No indexed sources to update. Run 'docmancer docs add <url-or-path>' first.")
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
                click.echo("Run 'docmancer docs list' to see indexed sources.")
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
        src_label = src if src.startswith(("http://", "https://")) else display_path(src)
        try:
            if src.startswith(("http://", "https://")):
                click.echo(f"Updating {src_label}...")
                total = agent.add(src, recreate=False, max_pages=max_pages, browser=browser)
            else:
                if not Path(src).exists():
                    click.echo(f"Skipping {src_label} (path not found on disk)")
                    failed += 1
                    continue
                click.echo(f"Updating {src_label}...")
                total = agent.add(src, recreate=False)
            click.echo(f"  {total} sections indexed")
            updated += 1
        except Exception as e:
            click.echo(f"  Error updating {src_label}: {e}", err=True)
            failed += 1

    click.echo()
    click.echo(f"Updated {updated} source(s)." + (f" {failed} failed." if failed else ""))


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Index local files into the SQLite index.",
    epilog=format_examples(
        "docmancer docs add ./docs",
        "docmancer docs add ./README.md",
        "docmancer docs add ./docs --format md --format pdf",
        "docmancer docs add ./docs --include 'guides/**' --exclude '**/draft*'",
    ),
)
@click.argument("path")
@click.option("--recreate", is_flag=True, help="Recreate the collection first.")
@click.option("--include", "include_patterns", multiple=True, help="Glob pattern to include, relative to the ingest root.")
@click.option("--exclude", "exclude_patterns", multiple=True, help="Glob pattern to exclude, relative to the ingest root.")
@click.option(
    "--format",
    "formats",
    multiple=True,
    type=click.Choice(["md", "markdown", "txt", "pdf", "docx", "rtf", "html", "htm"], case_sensitive=False),
    help="Restrict ingest to one or more file formats.",
)
@click.option("--recursive/--no-recursive", default=True, show_default=True, help="Recurse through directories.")
@click.option("--skip-known", is_flag=True, help="Skip files whose content hash is already indexed.")
@click.option("--no-vectors", is_flag=True, help="Index FTS5 only; skip embedding/vector upsert.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def ingest_cmd(
    path: str,
    recreate: bool,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    formats: tuple[str, ...],
    recursive: bool,
    skip_known: bool,
    no_vectors: bool,
    config_path: str | None,
):
    """Index local files or directories."""
    if path.startswith(("http://", "https://")):
        raise click.ClickException("Use `docmancer docs add` for URLs.")

    config_path = _effective_config(config_path)
    _configure_ingest_logging()
    config = _load_config(config_path)
    agent = _get_agent_class()(config=config)

    if recreate and not no_vectors:
        _drop_vector_collection(config, agent)

    try:
        total = agent.ingest(
            path,
            recreate=recreate,
            include=include_patterns,
            exclude=exclude_patterns,
            formats=formats,
            recursive=recursive,
            skip_known=skip_known,
            with_vectors=not no_vectors,
        )
        _emit_index_summary(total, agent)
        if getattr(agent, "last_ingest_skips", None):
            report_path = getattr(agent, "last_ingest_report_path", None)
            click.echo(f"Skipped {len(agent.last_ingest_skips)} file(s). Report: {display_path(report_path)}")
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _drop_vector_collection(config, agent) -> None:
    """Best-effort: remove the Qdrant collection + persisted meta so the
    next ingest rebuilds at the current embedder dimension.

    Silent on missing-collection / Qdrant-down: callers use this defensively
    before re-ingest, and a missing collection is success, not failure.
    """
    try:
        from docmancer.core import index_meta
        from docmancer.runtime.qdrant_manager import ensure_running
        from docmancer.stores.base import get_vector_store
    except ImportError:
        return

    collection = agent._vector_collection_name()
    vs_config = agent.resolve_vector_store_config()
    if vs_config.provider == "qdrant" and not vs_config.url:
        resolution = ensure_running()
        if not resolution.url:
            index_meta.drop(collection)
            return
        vs_config = vs_config.model_copy(update={"url": resolution.url})

    try:
        store = get_vector_store(vs_config, embeddings_dim=config.embeddings.dimensions)
        store.delete_collection(collection)
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.debug("could not drop vector collection %r: %s", collection, exc)
    index_meta.drop(collection)


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
@click.option(
    "output_format",
    "--format",
    type=click.Choice(["md", "okf"], case_sensitive=False),
    default="md",
    show_default=True,
    help="Output format: plain markdown, or an OKF bundle (frontmatter + index.md).",
)
def fetch_cmd(url: str, output_dir: str, output_format: str):
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

    if output_format.lower() == "okf":
        from docmancer.okf.adapters import concepts_from_documents
        from docmancer.okf.bundle import write_bundle

        result = write_bundle(
            out_path,
            concepts_from_documents(documents),
            title=f"Docs fetched from {url}",
        )
        click.echo(
            f"Wrote OKF bundle to {display_path(result.root)} "
            f"({result.concept_count} page(s)). Validate: docmancer okf doctor {output_dir}"
        )
        return

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
        "docmancer docs list",
        "docmancer docs list --config ./docmancer.yaml",
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
    sources_by_format = stats.get("sources_by_format") or {}
    if sources_by_format:
        click.echo("Sources by format:")
        for format_name, count in sorted(sources_by_format.items()):
            click.echo(f"  {format_name}: {count}")
    click.echo(f"Sections: {stats.get('sections_count', 0)}")
    sections_by_format = stats.get("sections_by_format") or {}
    if sections_by_format:
        click.echo("Sections by format:")
        for format_name, count in sorted(sections_by_format.items()):
            click.echo(f"  {format_name}: {count}")
    click.echo(f"Extracted: {display_path(stats.get('extracted_dir', ''))}")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Check Shared Memory, indexes, providers, and integrations.",
    epilog=format_examples(
        "docmancer doctor",
        "docmancer doctor --config ./docmancer.yaml",
    ),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def doctor_cmd(config_path: str | None):
    """Check the environment, Shared Memory trees, indexes, providers, and installed integrations."""
    config_path = _effective_config(config_path)
    config = _load_config(config_path)
    home = Path.home()
    _emit_brand_header("docmancer doctor", "Check binary, config, Shared Memory, indexes, and installed integrations.")

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
            _emit_status_line("No docs indexed yet (run: docmancer docs add <path> or docmancer docs add <url>)", state="warn")

    click.echo()
    click.echo(_style("  Memory index", fg="white", bold=True))
    try:
        from docmancer.memory import MemoryAgent

        minfo = MemoryAgent().status()
        mdb = Path(minfo["db_path"])
        if mdb.exists():
            _emit_status_line(
                f"{minfo['sources']} entries indexed at {display_path(str(mdb))}",
                indent=4,
            )
        else:
            _emit_status_line(
                "no memory indexed yet (run: docmancer setup)",
                state="warn",
                indent=4,
            )
    except Exception as exc:  # noqa: BLE001 - doctor must never crash on one check
        _emit_status_line(f"unavailable ({exc})", state="warn", indent=4)

    click.echo()
    click.echo(_style("  Project Shared Memory", fg="white", bold=True))
    from docmancer.memory.tree.project import resolve_project_root

    tree_root = resolve_project_root() / ".docmancer" / "tree"
    inbox_root = tree_root.parent / "inbox"
    if not tree_root.exists():
        _emit_status_line(
            "not initialised for this project (run: docmancer web)",
            state="warn",
            indent=4,
        )
    elif not tree_root.is_dir():
        _emit_status_line("tree root exists but is not a directory", state="error", indent=4)
    else:
        try:
            from docmancer.memory.tree.parser import parse_tree_file
            from docmancer.memory.tree.store import TreeStore

            markdown_files = sorted(tree_root.rglob("*.md"))
            malformed: list[str] = []
            for path in markdown_files:
                try:
                    if parse_tree_file(path) is None:
                        malformed.append(str(path.relative_to(tree_root)))
                except Exception:  # noqa: BLE001 - report every malformed file together
                    malformed.append(str(path.relative_to(tree_root)))
            indexed = TreeStore(tree_root).rebuild_index()
            _emit_status_line(
                f"{len(markdown_files)} Shared Memory file(s), {indexed} indexed, "
                f"{len(list(inbox_root.glob('*.md'))) if inbox_root.exists() else 0} inbox item(s)",
                indent=4,
            )
            if malformed:
                _emit_status_line(
                    "invalid frontmatter: " + ", ".join(malformed[:10]),
                    state="error",
                    indent=4,
                )
            else:
                _emit_status_line("parser and disposable-index rebuild: healthy", indent=4)
        except Exception as exc:  # noqa: BLE001 - doctor must continue through other checks
            _emit_status_line(f"tree check failed ({exc})", state="error", indent=4)

        writable = os.access(tree_root, os.R_OK | os.W_OK | os.X_OK)
        _emit_status_line(
            "tree permissions: readable and writable" if writable else "tree permissions need attention",
            state="ok" if writable else "error",
            indent=4,
        )
        _emit_status_line("watcher: bounded content-hash polling available", indent=4)
        try:
            from docmancer.memory.tree.editor import editor_command

            sample = next((path for path in markdown_files if path.is_file()), None)
            if sample is None:
                _emit_status_line("external editor: no memory file available to probe", state="warn", indent=4)
            else:
                launcher = editor_command(sample, allowed_root=tree_root)[0]
                _emit_status_line(f"external editor launcher: {display_path(launcher)}", indent=4)
        except Exception as exc:  # noqa: BLE001 - unavailable editor is diagnostic, not fatal
            _emit_status_line(f"external editor unavailable ({exc})", state="warn", indent=4)

    click.echo()
    click.echo(_style("  Local loaders", fg="white", bold=True))
    for label, available, hint in _loader_availability():
        if available:
            _emit_status_line(f"{label}: available", indent=4)
        else:
            _emit_status_line(f"{label}: missing ({hint})", state="warn", indent=4)

    click.echo()
    click.echo(_style("  Vector retrieval", fg="white", bold=True))
    vs_provider = (config.vector_store.provider or "sqlite-vec").lower()
    emb_provider = (config.embeddings.provider or "model2vec").lower()
    qdrant_status = None

    # Default offline stack: report readiness without probing the heavy backend.
    if vs_provider == "sqlite-vec" and emb_provider == "model2vec":
        _emit_status_line(
            "static embeddings (model2vec, vendored), sqlite-vec, hybrid: ready, offline",
            indent=4,
        )
    elif vs_provider == "qdrant":
        try:
            from docmancer.runtime.qdrant_manager import QdrantManager  # noqa: F401

            qdrant_status = QdrantManager().status()
            if qdrant_status["alive"] and qdrant_status["owned"]:
                _emit_status_line(
                    f"qdrant: running (pid {qdrant_status['pid']}, port {qdrant_status['port']}, version {qdrant_status['version']})",
                    indent=4,
                )
            elif qdrant_status["alive"]:
                _emit_status_line("qdrant: running but not docmancer-owned", state="warn", indent=4)
            else:
                _emit_status_line(
                    "qdrant: not running (start with: docmancer qdrant up)",
                    state="warn",
                    indent=4,
                )
        except ImportError:
            _emit_status_line(
                'qdrant: optional heavy backend not installed (pipx install "docmancer[embeddings-heavy]")',
                state="warn",
                indent=4,
            )
    else:
        _emit_status_line(f"vector store: {vs_provider}", indent=4)

    _emit_status_line(
        f"embeddings: provider={config.embeddings.provider} model={config.embeddings.model} dimensions={config.embeddings.dimensions}",
        indent=4,
    )
    if emb_provider == "fastembed":
        if find_spec("fastembed") is None:
            _emit_status_line(
                'embeddings: fastembed not installed (pipx install "docmancer[embeddings-heavy]")',
                state="warn",
                indent=4,
            )
        elif os.environ.get("HF_TOKEN"):
            _emit_status_line("HF_TOKEN: set", indent=4)
        else:
            _emit_status_line(
                "HF_TOKEN: not set (first-run Hugging Face model downloads may be throttled)",
                state="warn",
                indent=4,
            )

    # Highlight vector/lexical drift if both stores have populated this DB.
    try:
        sections_total = agent.store.collection_stats().get("sections_count", 0)
        from docmancer.core import index_meta
        from docmancer.stores.base import get_vector_store

        vs_config = config.vector_store
        if vs_config.provider == "qdrant" and qdrant_status and qdrant_status.get("healthy"):
            url = qdrant_status.get("url")
            if url:
                vs_config = vs_config.model_copy(update={"url": url})
                store = get_vector_store(vs_config, embeddings_dim=config.embeddings.dimensions)
                collection = agent._vector_collection_name()
                try:
                    points = store.count(collection)
                    _emit_status_line(f"collection: {collection} ({points} vector point(s))", indent=4)
                    if sections_total and points == 0:
                        _emit_status_line(
                            "collection has no indexed vectors; re-run ingest or rebuild with --recreate",
                            state="error",
                            indent=4,
                        )
                    if sections_total and abs(points - sections_total) > 0:
                        _emit_status_line(
                            f"drift: sections={sections_total} vs vector_points={points}",
                            state="warn",
                            indent=4,
                        )
                    meta = (
                        getattr(store, "collection_metadata", lambda _collection: None)(collection)
                        or index_meta.get(collection)
                    )
                    if meta:
                        meta_provider = getattr(meta, "provider", None) or meta.get("provider")
                        meta_model = getattr(meta, "model", None) or meta.get("model")
                        meta_dim = getattr(meta, "dim", None) or meta.get("dim")
                        _emit_status_line(
                            f"collection embedder: provider={meta_provider} model={meta_model} dim={meta_dim}",
                            indent=4,
                        )
                        if (
                            str(meta_provider) != str(config.embeddings.provider)
                            or str(meta_model) != str(config.embeddings.model)
                            or int(meta_dim or 0) != int(config.embeddings.dimensions or 0)
                        ):
                            _emit_status_line(
                                "embedder mismatch: configured embeddings do not match the collection; rebuild with docmancer docs add <path> --recreate",
                                state="error",
                                indent=4,
                            )
                    else:
                        _emit_status_line(
                            "collection embedder metadata missing; rebuild with docmancer docs add <path> --recreate",
                            state="warn",
                            indent=4,
                        )
                except Exception:
                    pass
    except Exception:
        pass

    click.echo()
    click.echo(_style("  Memory hooks", fg="white", bold=True))
    hook_locations = [
        ("claude-code", home / ".claude" / "settings.json"),
        ("codex", home / ".codex" / "hooks.json"),
    ]
    for label, path in hook_locations:
        try:
            data = _load_json_object(path) if path.exists() else {}
            has_hook = _HOOK_COMMAND_MARKER in json.dumps(data)
        except Exception:
            has_hook = False
        if has_hook:
            _emit_status_line(f"{label}: hooks installed at {display_path(path)}", indent=4)
        else:
            _emit_status_line(f"{label}: no hooks installed (run: docmancer agent install {label} --hooks)", state="warn", indent=4)

    # Instruction-block drift: refresh anything stamped with an older release,
    # or never stamped at all, before reporting install status below.
    click.echo()
    click.echo(_style("  Instruction blocks", fg="white", bold=True))
    refreshed_blocks = refresh_stale_instruction_blocks(config_path=effective_config, home=home)
    if refreshed_blocks:
        for row in refreshed_blocks:
            _emit_status_line(
                f"{row['agent']}: refreshed {row['installed_version'] or 'unstamped'} -> {row['refreshed_to']}",
                indent=4,
            )
    else:
        for row in check_instruction_block_drift(home=home):
            _emit_status_line(f"{row['agent']}: up to date ({row['current_version']})", indent=4)

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
            stale = False
            if path.suffix.lower() == ".md":
                try:
                    content = path.read_text(encoding="utf-8")
                    stale = "docmancer ask" not in content
                except (OSError, UnicodeDecodeError):
                    stale = True
            if stale:
                _emit_status_line(
                    f"{label}: installed guidance is stale (refresh with: docmancer setup)",
                    state="warn",
                    indent=4,
                )
            else:
                _emit_status_line(f"{label}: {display_path(path)}", indent=4)
        else:
            _emit_status_line(f"{label}: not installed (run: docmancer agent install {install_target})", state="warn", indent=4)



@click.command(
    cls=DocmancerCommand,
    context_settings={**HELP_CONTEXT_SETTINGS, "allow_extra_args": True},
    short_help="Search indexed docs.",
    epilog=format_examples(
        'docmancer docs query "How do I authenticate?"',
        'docmancer docs query "getting started" --limit 3',
        'docmancer docs query "season 5 end date" --expand',
        'docmancer docs query "season 5 end date" --expand page',
        'docmancer docs query "auth" --format json',
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
@click.option(
    "--mode",
    type=click.Choice(["lexical", "dense", "sparse", "hybrid"], case_sensitive=False),
    default=None,
    help="Retrieval mode. Default reads from retrieval.default_mode in config.",
)
@click.option("--explain", is_flag=True, help="Show per-source rank contributions for each result.")
@click.option(
    "--allow-degraded",
    is_flag=True,
    default=False,
    help="In non-lexical modes, fall back to remaining signals if a retriever fails instead of erroring.",
)
@click.pass_context
def query_cmd(
    ctx: click.Context,
    text: str,
    config_path: str | None,
    limit: int | None,
    budget: int | None,
    expand: str | None,
    output_format: str,
    mode: str | None,
    explain: bool,
    allow_degraded: bool,
):
    """Return a compact docs context pack from the local SQLite index."""
    import json as _json
    from docmancer.retrieval.dispatch import HybridRetrievalError

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
    effective_mode = _effective_retrieval_mode(mode, config)
    contributions: dict = {}
    failures: dict[str, str] = {}
    if effective_mode == "lexical":
        chunks = agent.query(text, limit=limit, budget=budget, expand=expand)
    else:
        try:
            chunks, contributions, failures = _run_dispatch_query(
                agent=agent,
                config=config,
                query=text,
                mode=effective_mode,
                limit=limit,
                budget=budget,
                expand=expand,
                allow_degraded=allow_degraded,
            )
        except HybridRetrievalError as exc:
            if mode is None and _can_default_query_fallback(exc):
                chunks = agent.query(text, limit=limit, budget=budget, expand=expand)
                failures = exc.failures
            else:
                click.echo(f"Error: {exc}", err=True)
                sys.exit(2)

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
                    "degraded": bool(failures),
                    "failures": failures,
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
    if failures:
        for source, failure in failures.items():
            click.echo(f"Warning: {source} retriever degraded: {failure}", err=True)
    click.echo("---")

    for i, chunk in enumerate(chunks, start=1):
        body = chunk.text
        click.echo(f"[{i}] score={chunk.score:.2f}  source={chunk.source}")
        meta = chunk.metadata or {}
        if meta.get("title"):
            click.echo(f"    section: {meta['title']}")
        click.echo(f"    tokens: ~{meta.get('token_estimate', 0)}")
        if explain:
            sid = meta.get("section_id")
            contrib = contributions.get(sid) if sid is not None else None
            if contrib:
                parts = ", ".join(f"{src}#{rank}" for src, rank in sorted(contrib.items()))
                click.echo(f"    explain: {parts}")
            elif effective_mode == "lexical":
                click.echo("    explain: lexical#1")
            elif failures:
                failure_parts = "; ".join(f"{src}: {msg}" for src, msg in sorted(failures.items()))
                click.echo(f"    explain: degraded retrieval ({failure_parts})")
        click.echo(body)
        click.echo("---")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove an indexed source.",
    epilog=format_examples(
        "docmancer docs remove --all",
        "docmancer agent remove claude-code --hooks",
        "docmancer agent remove codex --hooks",
        "docmancer docs remove https://docs.example.com",
        "docmancer docs remove https://docs.example.com/page",
        "docmancer docs remove ./docs/getting-started.md",
    ),
)
@click.argument("source", required=False)
@click.option("--all", "remove_all", is_flag=True, default=False, help="Remove every stored source and docset.")
@click.option("--hooks", is_flag=True, default=False, help="Remove all docmancer recall and capture hooks for claude-code or codex.")
@click.option("--capture-hooks", is_flag=True, default=False, help="Remove opt-in memory capture hooks for claude-code or codex.")
@click.option("--project", is_flag=True, default=False, help="Remove project-level hook config instead of user-level hook config.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def remove_cmd(source: str | None, remove_all: bool, hooks: bool, capture_hooks: bool, project: bool, config_path: str | None):
    """Remove an indexed source or a docmancer hook integration."""
    if hooks or capture_hooks:
        if hooks and capture_hooks:
            click.echo("Remove recall and capture hooks with two explicit commands.", err=True)
            sys.exit(1)
        if remove_all:
            click.echo("Do not pass --all when removing hooks.", err=True)
            sys.exit(1)
        if not source:
            click.echo("Specify claude-code or codex when removing hooks.", err=True)
            sys.exit(2)
        removed = _remove_agent_hooks(source.lower(), project=project, capture_only=capture_hooks)
        for label, path in removed:
            _emit_status_line(f"{label}: {display_path(path)}")
        return
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
    deleted, removed_kind = agent.remove_source(source)
    if deleted:
        if removed_kind == "docset":
            click.echo(f"Removed docset: {source}")
        else:
            click.echo(f"Removed source: {source}")
    else:
        click.echo(f"No data found for source: {source}", err=True)
        sys.exit(1)


def _dir_size_bytes(path: Path) -> int:
    """Best-effort recursive size for a file or directory. Permission errors
    are skipped silently so a single unreadable file does not abort the scan."""
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _format_size(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _resolved_docmancer_home() -> Path:
    """The docmancer state directory this machine actually uses.

    Mirrors the ``DOCMANCER_HOME`` handling in ``docmancer.memory`` and
    ``docmancer.runtime.qdrant_manager`` so ``clear`` removes the same tree the
    rest of the CLI reads and writes, not a hardcoded ``~/.docmancer``.
    """
    override = os.environ.get("DOCMANCER_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".docmancer"


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove all docmancer state from this machine.",
    epilog=format_examples(
        "docmancer clear",
        "docmancer clear --yes",
        "docmancer clear --keep-config",
        "docmancer clear --keep-models",
    ),
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--keep-config", is_flag=True, help="Preserve docmancer.yaml in the docmancer home.")
@click.option(
    "--keep-models",
    is_flag=True,
    help="Skip the FastEmbed / Qdrant-hosted HuggingFace model caches.",
)
def clear_cmd(assume_yes: bool, keep_config: bool, keep_models: bool) -> None:
    """Remove every docmancer-related directory from this machine.

    Removes (by default):

    \b
    - the docmancer home ($DOCMANCER_HOME, else ~/.docmancer): config, the
      SQLite and sqlite-vec indexes, the memory tree, baselines, extracted
      docs, the embeddings cache, vendored models, managed Qdrant storage
    - ~/.cache/fastembed/ (FastEmbed ONNX model cache)
    - ~/.cache/huggingface/hub/models--Qdrant--* (Qdrant-published models that
      docmancer pulled via the qdrant_client embedding helper)

    The managed Qdrant process is stopped first if it is running. Other tools'
    HuggingFace caches (non-Qdrant publishers) are left untouched.

    Project-local .docmancer/ directories and cloud credentials held in the OS
    keyring are NOT removed. Rebuild afterwards with: docmancer setup
    """
    home = Path.home()

    docmancer_home = _resolved_docmancer_home()
    targets: list[Path] = []

    if docmancer_home.exists():
        if keep_config:
            for child in sorted(docmancer_home.iterdir()):
                if child.name == "docmancer.yaml":
                    continue
                targets.append(child)
        else:
            targets.append(docmancer_home)

    # A relocated home can leave an older default tree behind. Surface it
    # rather than deleting it silently, since it may predate the relocation.
    default_home = home / ".docmancer"
    leftover = default_home if default_home != docmancer_home and default_home.exists() else None

    if not keep_models:
        fastembed_cache = home / ".cache" / "fastembed"
        if fastembed_cache.exists():
            targets.append(fastembed_cache)
        hf_hub = home / ".cache" / "huggingface" / "hub"
        if hf_hub.exists():
            for child in sorted(hf_hub.iterdir()):
                if child.name.startswith("models--Qdrant--"):
                    targets.append(child)

    if not targets:
        click.echo("Nothing to remove. Docmancer state is already clear.")
        if leftover:
            click.echo(f"Note: {display_path(leftover)} exists but is not the active home.")
        return

    sizes = {t: _dir_size_bytes(t) for t in targets}
    total = sum(sizes.values())

    click.echo("Will remove:")
    for t in targets:
        click.echo(f"  {_format_size(sizes[t]):>10}  {display_path(t)}")
    click.echo(f"  {'-' * 10}")
    click.echo(f"  {_format_size(total):>10}  total")

    click.echo("\nNot removed: project-local .docmancer/ directories, cloud credentials in the OS keyring.")
    if leftover:
        click.echo(f"Not removed: {display_path(leftover)} (not the active home; $DOCMANCER_HOME is set).")

    if not assume_yes:
        click.confirm("\nRemove all of this?", abort=True)

    # Stop the managed Qdrant before deleting its storage so the binary
    # is not still writing into ~/.docmancer/qdrant as we remove it.
    try:
        from docmancer.runtime.qdrant_manager import QdrantManager

        mgr = QdrantManager()
        if mgr.stop():
            click.echo("Stopped managed qdrant.")
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Warning: could not stop managed qdrant: {exc}", err=True)

    removed = 0
    failed: list[tuple[Path, str]] = []
    for t in targets:
        try:
            if t.is_dir() and not t.is_symlink():
                shutil.rmtree(t)
            else:
                t.unlink()
            removed += sizes[t]
        except OSError as exc:
            failed.append((t, str(exc)))

    click.echo(f"Removed {_format_size(removed)} of docmancer state.")
    click.echo("Rebuild the local index with: docmancer setup")
    if failed:
        click.echo("Some paths could not be removed:", err=True)
        for path, msg in failed:
            click.echo(f"  {display_path(path)}: {msg}", err=True)
        sys.exit(1)


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="List indexed documentation sources.",
    epilog=format_examples(
        "docmancer docs list",
        "docmancer docs list --all",
        "docmancer docs list --config ./docmancer.yaml",
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
        click.echo(f"{entry['ingested_at']}  {entry['source']}")


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Install docmancer skills into an AI agent.",
    epilog=format_examples(
        "docmancer agent install claude-code",
        "docmancer agent install codex",
        "docmancer agent install claude-code --project",
        "docmancer agent install cursor",
        "docmancer agent install claude-desktop",
        "docmancer agent install gemini",
        "docmancer agent install github-copilot --project",
        "docmancer agent install opencode",
        "docmancer agent install cline",
    ),
)
@click.argument("agent", type=click.Choice(INSTALL_TARGETS, case_sensitive=False))
@click.option("--project", is_flag=True, default=False,
              help="Install in project-level settings (claude-code, gemini, cline, or github-copilot).")
@click.option("--hooks", is_flag=True, default=False, help="Install automatic memory recall hooks (claude-code or codex).")
@click.option("--capture-hooks", is_flag=True, default=False, help="Install opt-in local memory capture hooks (claude-code or codex).")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def install_cmd(agent: str, project: bool, hooks: bool, capture_hooks: bool, config_path: str | None):
    """Install docmancer skill files into an AI agent.

    Teaches the agent to recall your unified memory and search indexed docs
    through docmancer CLI commands directly.

    AGENT must be one of: claude-code, claude-desktop, cline, cursor, codex,
    codex-app, codex-desktop, gemini, github-copilot, opencode
    """
    config_path = _effective_config(config_path)
    normalized = agent.lower()
    if (hooks or capture_hooks) and normalized not in {"claude-code", "codex", "codex-app", "codex-desktop"}:
        raise click.ClickException("memory hooks are currently supported for claude-code and codex.")
    home = Path.home()

    def refresh_projection() -> None:
        """Best-effort delivery of current Shared Memory after installation."""
        if _INSTALL_QUIET:
            # Machine-wide setup installs integrations from whatever directory
            # the user happens to be in. It must not register that directory as
            # a project or create repository-local Docmancer state.
            return
        try:
            from docmancer.memory import MemoryAgent, default_memory_db
            from docmancer.memory.projections import refresh_projections
            from docmancer.memory.service import MemoryService

            memory_db = Path(os.getenv("DOCMANCER_MEMORY_DB") or default_memory_db())
            if not memory_db.exists():
                return
            rows = refresh_projections(
                MemoryService(MemoryAgent()),
                project_path=Path.cwd(),
                agents=[normalized],
                installed_only=False,
                home=home,
            )
            if rows:
                _emit_status_line(f"Refreshed Shared Memory projection at {display_path(rows[0]['path'])}")
        except Exception:  # noqa: BLE001 - a projection must not make skill installation fail
            return
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
        refresh_projection()
        return

    if normalized == "claude-code":
        if project:
            dest = Path(".claude") / "skills" / "docmancer" / "SKILL.md"
            mem_dest = Path(".claude") / "skills" / "docmancer-memory" / "SKILL.md"
        else:
            dest = home / ".claude" / "skills" / "docmancer" / "SKILL.md"
            mem_dest = home / ".claude" / "skills" / "docmancer-memory" / "SKILL.md"
        content = _build_skill_content("claude_code_skill.md", effective_config_path)
        _install_skill_file(content, dest)
        mem_content = _build_skill_content("memory_skill.md", effective_config_path)
        _install_skill_file(mem_content, mem_dest)
        # Inject a memory-recall instruction into the always-loaded CLAUDE.md so
        # the on-demand pull path fires even when skill discovery is flaky. The
        # scope mirrors where the skills were written (project vs global).
        claude_md = Path("CLAUDE.md") if project else home / ".claude" / "CLAUDE.md"
        instruction_body = _get_template_content("claude_code_instruction.md").replace(
            "{{DOCS_KIT_CMD}}", _resolve_skill_command(effective_config_path)
        )
        _install_or_append_agents_md(claude_md, instruction_body)
        installed_paths = [
            ("Installed docmancer skill at", dest),
            ("Installed docmancer-memory skill at", mem_dest),
            ("Injected recall instruction into", claude_md),
        ]
        extra_lines = ["Claude Code can use docmancer commands as a fallback."]
        next_step = "Claude Code can use docmancer immediately. No restart needed."
        if hooks:
            installed_paths.extend(_install_agent_hooks("claude-code", project=project, config_path=effective_config_path))
            extra_lines.insert(0, "Automatic recall hooks installed for SessionStart and UserPromptSubmit.")
            next_step = "Start Claude Code; relevant memories will be injected automatically when they match."
        if capture_hooks:
            installed_paths.extend(_install_capture_hooks("claude-code", project=project, config_path=effective_config_path))
            extra_lines.insert(0, "Opt-in capture hooks installed for PostCompact and SessionEnd.")
            next_step = "Start Claude Code; durable session memories will be saved locally at lifecycle boundaries."
        _emit_install_summary(
            "Install skill for Claude Code.",
            installed_paths,
            created_user_config,
            effective_config_path,
            next_step,
            extra_lines=extra_lines,
        )
        refresh_projection()
        return

    if normalized in {"codex", "codex-app", "codex-desktop"}:
        dest = _get_codex_skill_path()
        shared_dest = _get_shared_agent_skill_path()
        content = _build_skill_content("skill.md", effective_config_path)
        _install_skill_file(content, dest)
        _install_skill_file(content, shared_dest)
        mem_content = _build_skill_content("memory_skill.md", effective_config_path)
        mem_dest = dest.parent.parent / "docmancer-memory" / "SKILL.md"
        _install_skill_file(mem_content, mem_dest)
        # Inject a memory-recall instruction into the always-loaded AGENTS.md so
        # the on-demand pull path fires even when skill discovery is flaky.
        codex_agents_md = home / ".codex" / "AGENTS.md"
        instruction_body = _get_template_content("codex_agents_md.md").replace(
            "{{DOCS_KIT_CMD}}", _resolve_skill_command(effective_config_path)
        )
        _install_or_append_agents_md(codex_agents_md, instruction_body)
        installed_paths = [
            ("Installed docmancer skill at", dest),
            ("Installed docmancer-memory skill at", mem_dest),
            ("Also installed shared compatibility skill at", shared_dest),
            ("Injected recall instruction into", codex_agents_md),
        ]
        extra_lines = ["Codex can use docmancer commands as a fallback."]
        shared_coverage = _shared_skill_coverage("codex")
        if shared_coverage:
            extra_lines.append(shared_coverage)
        next_step = 'Run `docmancer docs query "your question"` to verify retrieval from the CLI.'
        if hooks:
            installed_paths.extend(_install_agent_hooks("codex", project=project, config_path=effective_config_path))
            extra_lines.insert(0, "Automatic recall hooks installed for SessionStart and UserPromptSubmit.")
            extra_lines.append("Codex may ask you to review and trust hooks. Open /hooks if prompted.")
            next_step = "Start Codex and review /hooks if requested; relevant memories will be injected automatically when they match."
        if capture_hooks:
            installed_paths.extend(_install_capture_hooks("codex", project=project, config_path=effective_config_path))
            extra_lines.insert(0, "Opt-in capture hooks installed for PreCompact and Stop.")
            extra_lines.append("Codex may ask you to review and trust hooks. Open /hooks if prompted.")
            next_step = "Start Codex and review /hooks if requested; durable memories will be saved locally."
        _emit_install_summary(
            "Install skill for Codex.",
            installed_paths,
            created_user_config,
            effective_config_path,
            next_step,
            extra_lines=extra_lines,
        )
        refresh_projection()
        return

    if hooks or capture_hooks:
        raise click.ClickException("memory hooks are currently supported for claude-code and codex.")

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
        refresh_projection()
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
        refresh_projection()
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
                    "For Copilot in VS Code, Xcode, JetBrains, or GitHub.com, run `docmancer agent install github-copilot --project` inside each repository.",
                ],
            )
        refresh_projection()
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
            'Run `docmancer docs query "your question"` or restart Gemini if it does not pick up the skill immediately.',
            extra_lines=[
                line for line in (
                    "Gemini CLI will automatically use docmancer commands.",
                    _shared_skill_coverage("gemini"),
                ) if line
            ],
        )
        refresh_projection()
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
            'Run `docmancer docs query "your question"` to verify retrieval from the CLI.',
            extra_lines=[
                line for line in (
                    "OpenCode will automatically use docmancer commands.",
                    _shared_skill_coverage("opencode"),
                ) if line
            ],
        )
        refresh_projection()
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


def _setup_index_memory(config, *, index_memory: bool, dry_run: bool) -> None:
    """Warm the static model once and index all local harness memory.

    Non-fatal: a machine with no agent memory is a valid, successful setup.
    """
    if not index_memory:
        _emit_status_line("Memory indexing skipped (--no-index-memory).", state="info")
        return

    if dry_run:
        try:
            from docmancer.memory import MemoryAgent

            preview_started = monotonic()
            preview_status = LiveStatus(started_at=preview_started)
            preview_status.start("Discovering memory and instruction files...")
            try:
                source_count = len(MemoryAgent().preview())
            finally:
                preview_status.stop()
            _emit_status_line(
                f"Would index {source_count:,} source file(s) from your agents "
                f"({monotonic() - preview_started:.1f}s)."
            )
        except Exception as exc:  # noqa: BLE001 - setup preview must stay non-fatal
            _emit_status_line(f"Could not preview agent memory ({exc}).", state="warn")
        return

    # Warm the default static model once so the first real query is instant.
    # model2vec only; never trigger the heavy FastEmbed path here.
    if config.embeddings.provider == "model2vec":
        warmup_started = monotonic()
        warmup_status = LiveStatus(started_at=warmup_started)
        warmup_status.start("Loading the local embedding model (the first run can take a moment)...")
        warmup_error: Exception | None = None
        try:
            from docmancer.embeddings import get_embeddings_provider

            get_embeddings_provider(config.embeddings).embed(["warmup"])
        except Exception as exc:  # noqa: BLE001
            warmup_error = exc
        finally:
            warmup_status.stop()
        if warmup_error is not None:
            _emit_status_line(f"Could not pre-warm the embedding model ({warmup_error}).", state="warn")
        else:
            _emit_status_line(f"Local embedding model ready ({monotonic() - warmup_started:.1f}s).")

    try:
        from docmancer.memory import MemoryAgent

        agent = MemoryAgent()
        sync_started = monotonic()
        live_status = LiveStatus(started_at=sync_started)

        def on_progress(stage: str, detail: str = "") -> None:
            if stage == "done":
                live_status.stop()
                return
            live_status.start(detail)

        try:
            n = agent.sync(progress_callback=on_progress)
        finally:
            live_status.stop()
    except Exception as exc:  # noqa: BLE001 - setup must stay non-fatal
        _emit_status_line(f"Could not index agent memory ({exc}).", state="warn")
        return

    if n:
        _emit_status_line(f"Indexed {n:,} memory atoms ({monotonic() - sync_started:.1f}s).")
        try:
            from docmancer.memory.laptop import LaptopMemoryReconciler, laptop_memory_root

            canonical = LaptopMemoryReconciler(agent).reconcile()
            state = "Updated" if canonical.get("changed") else "Confirmed"
            provider = canonical.get("provider") or "deterministic"
            _emit_status_line(
                f"{state} machine-wide canonical memory at "
                f"{display_path(laptop_memory_root() / 'tree')} "
                f"({provider})."
            )
            # Reconciliation reruns on its own and, with a key configured, spends
            # provider tokens each time the evidence changes. Context
            # distillation is previewed and priced before it runs; this path is
            # not, so the least it can do is say so once, out loud, at setup.
            if provider != "deterministic":
                _emit_status_line(
                    f"Canonical memory is rebuilt with {provider} whenever your evidence "
                    "changes during an explicit memory sync or session capture. "
                    "`docmancer ask` and web startup only read the current index. Run "
                    "`docmancer memory canonical --refresh --deterministic` to rebuild "
                    "without a provider.",
                    state="info",
                )
        except Exception as exc:  # noqa: BLE001 - indexed evidence remains usable
            _emit_status_line(
                f"Could not reconcile machine-wide canonical memory ({exc}).",
                state="warn",
            )
        click.echo('  Try: docmancer memory query "..."')
        click.echo("  Try: docmancer memory canonical")
    else:
        _emit_status_line(
            "No agent memory found yet. Run `docmancer memory sync` after an agent writes memory.",
            state="info",
        )


@click.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Build Shared Memory and connect detected coding agents.",
    epilog=format_examples(
        "docmancer setup",
        "docmancer setup --all",
        "docmancer setup --agent codex --agent claude-desktop",
        "docmancer setup --agent github-copilot",
    ),
)
@click.option("--all", "install_all", is_flag=True, default=False, help="Install every supported agent integration, including agents not detected.")
@click.option("--agent", "agents", multiple=True, type=click.Choice(INSTALL_TARGETS, case_sensitive=False), help="Agent integration to install. Can be repeated.")
@click.option("--index-memory/--no-index-memory", default=True, show_default=True, help="Index the memory your coding agents already wrote on this machine.")
@click.option("--capture-hooks", is_flag=True, default=True, hidden=True)
@click.option(
    "--profile",
    type=click.Choice(["local", "scale"], case_sensitive=False),
    default=None,
    help="Use the zero-daemon local stack or Qdrant plus FastEmbed scale stack.",
)
@click.option("-y", "--yes", "assume_yes", is_flag=True, default=False, help="Apply the displayed setup plan without prompting.")
@click.option("--dry-run", is_flag=True, help="Preview the memory index (counts only); write nothing.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
def setup_cmd(
    install_all: bool,
    agents: tuple[str, ...],
    index_memory: bool,
    capture_hooks: bool,
    profile: str | None,
    assume_yes: bool,
    dry_run: bool,
    config_path: str | None,
):
    """Build local Shared Memory, index existing agent evidence, and connect detected agents.

    This bootstraps `docmancer.yaml`, initializes the local SQLite index,
    indexes the memory your coding agents already wrote on this machine,
    reconciles the laptop-wide tree, and installs agent skills, managed
    instructions, and supported hooks. Use `--agent` to pick explicit targets.
    """
    from docmancer.harness.setup_plan import build_setup_confirmation, normalize_setup_targets

    setup_started = monotonic()
    _emit_brand_header("docmancer setup", "Build local Shared Memory and connect every coding agent detected on this machine.")

    selected = [agent.lower() for agent in agents]
    if install_all:
        selected = list(INSTALL_TARGETS)
    elif not selected:
        selected = _detect_setup_targets()
    unique_targets = normalize_setup_targets(selected)
    confirmation = build_setup_confirmation(
        unique_targets,
        index_memory=index_memory,
        recall_hooks=True,
        capture_hooks=capture_hooks,
    )
    click.echo("Docmancer is ready to:")
    for step in confirmation["steps"]:
        click.echo(f"  • {step['title']}: {step['detail']}")
    if unique_targets:
        click.echo(f"  Detected targets: {', '.join(confirmation['target_labels'])}")
    else:
        click.echo("  No supported coding agents were detected. Setup will only prepare and index local memory.")
    click.echo()
    click.echo(
        "Warning: setup will read supported local agent memory, enable lifecycle capture, "
        "and automatically update ~/.docmancer/tree. If an AI provider is configured, "
        "redacted evidence may be sent to that provider for canonical-memory synthesis."
    )
    click.echo()
    if not dry_run and not assume_yes:
        if not click.confirm("Apply this setup plan?", default=False):
            _emit_status_line("Setup cancelled. No files were changed.", state="info")
            return

    config_status = LiveStatus(started_at=setup_started)
    config_status.start("Preparing the local configuration and SQLite index...")
    try:
        config_path = _effective_config(config_path)
        if dry_run:
            if config_path:
                config_file = Path(config_path).expanduser().resolve()
            elif Path("docmancer.yaml").is_file():
                config_file = Path("docmancer.yaml").resolve()
            else:
                config_file = _get_user_config_path().resolve()
            config = (
                _get_config_class().from_yaml(config_file)
                if config_file.is_file()
                else _build_user_bootstrap_config()
            )
            if profile:
                config.retrieval.profile = profile
                if profile == "scale":
                    config.index.persist_extracted = False
                    config.vector_store.provider = "qdrant"
                    config.vector_store.collection = "docmancer"
                    _apply_embedding_provider_shortcut(config, "fastembed")
                    config.embeddings.sparse_model = "prithivida/Splade_PP_en_v1"
        else:
            config_file = _ensure_config_and_db(config_path)
            _enable_automatic_capture(config_file)
            if profile:
                _persist_retrieval_profile(config_file, profile)
            config = _get_config_class().from_yaml(config_file)
    finally:
        config_status.stop()
    prefix = "Would use" if dry_run else "Config"
    _emit_status_line(f"{prefix}: {display_path(config_file)}")
    index_prefix = "Would use SQLite index" if dry_run else "SQLite index"
    _emit_status_line(f"{index_prefix}: {display_path(config.index.db_path)}")
    _emit_status_line(
        f"Retrieval profile: {config.retrieval.profile} "
        f"({config.vector_store.provider}, {config.embeddings.provider})."
    )
    if config.retrieval.profile == "scale":
        _emit_status_line(
            "The scale profile requires the embeddings-heavy extra and a reachable Qdrant service.",
            state="info",
        )

    refreshed_blocks = [] if dry_run else refresh_stale_instruction_blocks(config_path=config_file)
    for row in refreshed_blocks:
        _emit_status_line(
            f"Refreshed stale instruction block for {row['agent']} "
            f"({row['installed_version'] or 'unstamped'} -> {row['refreshed_to']}).",
            state="info",
        )

    _setup_index_memory(config, index_memory=index_memory, dry_run=dry_run)

    if not unique_targets:
        _emit_status_line(f"Setup complete ({monotonic() - setup_started:.1f}s).")
        _emit_next_step("Change to a project and run `docmancer web`.")
        return

    if dry_run:
        if unique_targets:
            _emit_status_line(
                f"Would connect {len(unique_targets)} agent integration(s): "
                f"{', '.join(unique_targets)}.",
                state="info",
            )
        _emit_status_line(f"Setup complete, preview only ({monotonic() - setup_started:.1f}s).")
        return
    _emit_status_line(
        f"Connecting {len(unique_targets)} agent integration(s): {', '.join(unique_targets)}.",
        state="info",
    )
    global _INSTALL_QUIET
    _INSTALL_QUIET = True
    try:
        ctx = click.get_current_context()
        for target in unique_targets:
            target_started = monotonic()
            _emit_status_line(f"Installing integration for {target}...", state="info")
            # Machine-wide setup must never modify the repository that happens
            # to be the current working directory. Project integrations remain
            # an explicit `agent install ... --project` action.
            ctx.invoke(
                install_cmd,
                agent=target,
                project=False,
                hooks=target in {"claude-code", "codex"},
                capture_hooks=capture_hooks and target in {"claude-code", "codex"},
                config_path=str(config_file),
            )
            _emit_status_line(f"Finished integration for {target} ({monotonic() - target_started:.1f}s).")
    finally:
        _INSTALL_QUIET = False

    _emit_status_line(f"Setup complete ({monotonic() - setup_started:.1f}s).")
    click.echo()
    _emit_next_step("Change to a project and run `docmancer web`.")
