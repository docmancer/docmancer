"""Curated Markdown tree commands and advanced recovery operations.

Write, read, edit, and move are everyday root commands. Search, context,
harvest, and init remain compatibility implementations during the 0.8
transition to unified ask, import, and automatic project initialization.
"""
from __future__ import annotations

import difflib
import json
import sys
import hashlib
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.memory.tree.errors import TreeError
from docmancer.memory.tree.store import TreeStore

MAX_STDIN_BYTES = 1_000_000

def _default_tree_root() -> Path:
    # Resolved lazily (not at import time) so the CLI always uses the
    # directory it was actually invoked from. Uses ".docmancer/tree", a
    # sibling of the legacy project record directory
    # ("<project>/.docmancer/memory", see docmancer.memory.records) --
    # never that directory itself, and the same convention the MCP tree
    # tools (docmancer/mcp/tree_tools.py) use for project scope, so a
    # decision written through this CLI in a directory is discoverable
    # through MCP with project_path set to that same directory, and vice
    # versa. This is deliberate: Release A's stated goal is one shared
    # tree, not two divergent default roots.
    from docmancer.memory.tree.project import tree_paths

    return tree_paths()[0]


def _global_tree_root() -> Path:
    from docmancer.memory.laptop import laptop_memory_root

    return laptop_memory_root() / "tree"


def _store(root: str | None, *, ensure: bool = False, global_scope: bool = False) -> TreeStore:
    if root:
        return TreeStore(Path(root))
    # The machine-wide canonical tree lives at ~/.docmancer/tree, but the default
    # root is <project>/.docmancer/tree. Without --global, the instruction the
    # canonical self-description gives ("docmancer read about.md") silently
    # resolved to the wrong tree from inside any repository.
    if global_scope:
        return TreeStore(_global_tree_root())
    if ensure:
        from docmancer.memory.tree.project import ensure_project

        return TreeStore(ensure_project().tree_root)
    return TreeStore(_default_tree_root())


def _guard_canonical_zone(store: TreeStore, address: str, new_body: str) -> None:
    """Refuse a whole-body edit that would rewrite an automatically generated zone.

    The reconciler replaces that zone on the next sync, so accepting the edit
    would quietly discard the caller's work. The error names the pin command
    instead, which is the write that actually persists.
    """
    from docmancer.memory.tree.zones import ZoneViolation, guard_zoned_write

    try:
        existing = store.read(address)
    except TreeError:
        return  # A missing or ambiguous address is the store's error to report.
    try:
        guard_zoned_write(existing.body, new_body, address=address)
    except ZoneViolation as exc:
        raise click.ClickException(str(exc)) from exc


_GLOBAL_OPTION = click.option(
    "--global",
    "global_scope",
    is_flag=True,
    help="Target the machine-wide canonical tree (~/.docmancer/tree) instead of this project's.",
)


def _read_text(text: str | None) -> str:
    """Read body text from the argument, or from stdin when the argument is
    omitted or is the conventional ``-`` placeholder."""
    if text is None or text == "-":
        return sys.stdin.read()
    return text


def _read_bounded_stdin() -> str:
    data = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(data) > MAX_STDIN_BYTES:
        raise click.UsageError(f"standard input exceeds the {MAX_STDIN_BYTES}-byte limit")
    return data.decode("utf-8", errors="replace")


def _emit_json(value) -> None:
    import json

    click.echo(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _fail(err: TreeError) -> "click.ClickException":
    """Render a typed tree error as a clean, non-traceback CLI failure."""
    likely_cause = getattr(err, "likely_cause", "") or ""
    next_action = getattr(err, "next_action", "") or ""
    lines = [str(err)]
    if likely_cause:
        lines.append(f"Likely cause: {likely_cause}")
    if next_action:
        lines.append(f"Next: {next_action}")
    return click.ClickException("\n".join(lines))


def _entry_dict(entry) -> dict:
    return {
        "address": entry.address,
        "memory_id": entry.memory_id,
        "title": entry.title,
        "type": entry.type,
        "scope": entry.scope,
        "authority": entry.authority,
        "project_id": entry.project_id,
        "status": entry.status,
        "tags": list(entry.tags),
        "sources": list(entry.sources),
        "revision_id": entry.revision_id,
        "content_hash": entry.content_hash,
        "path": str(entry.path),
    }


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Write, read, edit, move, search, and compile context over the curated memory tree.",
    epilog=format_examples(
        'docmancer tree write "# Deploy\\n\\nWe deploy on Railway." --path deployment/release.md',
        "docmancer tree read docmancer://memory/<id>",
        'docmancer tree search "deployment"',
        'docmancer tree context "how do we deploy?"',
    ),
)
def tree_group() -> None:
    """Curated Markdown memory tree: deliberate writes, stable addresses, and Context Compiler retrieval.

    This is a new, additive surface alongside the existing ``docmancer memory
    ...`` local-index harness; it does not change or replace it.
    """


@tree_group.command("init", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Create or adopt a curated Markdown tree.")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--project-id", default=None, help="Stable project ID written to the project context file.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def init_tree(root: str | None, project_id: str | None, as_json: bool) -> None:
    """Create the standard tree directories without enabling capture hooks."""
    from docmancer.memory.tree.project import ensure_project

    try:
        if root:
            tree_root = Path(root).expanduser().resolve()
            project_root = tree_root.parent
        else:
            tree_root = None
            project_root = None
        project = ensure_project(project_root, project_id=project_id, tree_root=tree_root)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "root": str(project.tree_root),
        "inbox": str(project.inbox_root),
        "trash": str(project.trash_root),
        "project_id": project_id,
        "created": project.created,
        "adopted": project.adopted,
        "capture_enabled": False,
        "files_adopted": len(list(project.tree_root.rglob("*.md"))) - (0 if project.adopted else 1),
    }
    if as_json:
        _emit_json(payload)
    else:
        click.echo(f"Tree ready: {payload['root']}")
        click.echo("Capture hooks remain disabled until explicitly installed.")


@tree_group.command(
    "session-baseline",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Emit bounded curated context for SessionStart hooks.",
)
@click.option("--root", default=None, help="Tree root directory. Defaults to <hook cwd>/.docmancer/tree.")
@click.option("--agent", type=click.Choice(["auto", "claude-code", "codex"], case_sensitive=False), default="auto")
@click.option("--token-budget", type=click.IntRange(100, 10_000), default=1500, show_default=True)
@click.option("--debug", is_flag=True, help="Print bounded hook diagnostics to stderr.")
def session_baseline_command(root: str | None, agent: str, token_budget: int, debug: bool) -> None:
    """Read one host hook payload from stdin and emit additionalContext JSON."""
    from docmancer.memory.hooks import hook_output, parse_hook_payload
    from docmancer.memory.tree.session_baseline import build_session_baseline_safe

    try:
        payload = parse_hook_payload(_read_bounded_stdin(), agent=agent.lower())
        if payload is None or payload.event != "SessionStart":
            return
        project_path = Path(payload.cwd).resolve() if payload.cwd else Path.cwd().resolve()
        tree_root = Path(root).resolve() if root else project_path / ".docmancer" / "tree"
        store = TreeStore(tree_root)
        baseline = build_session_baseline_safe(
            store.index,
            project_path=str(project_path),
            agent=payload.agent,
            session_id=payload.session_id or None,
            token_budget=token_budget,
            state_dir=tree_root.parent / "state" / "session-baselines",
        )
        if baseline:
            click.echo(hook_output("SessionStart", baseline))
    except Exception as exc:  # noqa: BLE001 - SessionStart recall must fail open
        if debug:
            click.echo(f"docmancer session-baseline failed: {str(exc)[:300]}", err=True)


@tree_group.command("capture", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Capture one bounded lifecycle event from standard input.")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--inbox", "inbox_path", default=None, help="Inbox directory. Defaults to ./.docmancer/inbox.")
@click.option("--validate-only", is_flag=True, help="Validate and redact the event without writing an inbox file.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def capture_command(root: str | None, inbox_path: str | None, validate_only: bool, as_json: bool) -> None:
    """Read exactly one JSON event from stdin. Hook failures always exit successfully."""
    from docmancer.memory.tree.capture_event import parse_capture_event, capture as capture_event
    from docmancer.memory.tree.curation import CurationEngine

    try:
        raw = _read_bounded_stdin()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("capture payload must be a JSON object")
    except Exception as exc:  # noqa: BLE001 - hook path must fail open
        result = {"captured": False, "reason": "invalid_capture_payload", "detail": str(exc)[:300]}
    else:
        if validate_only:
            event = parse_capture_event(payload)
            result = {
                "captured": False,
                "validated": True,
                "event_type": event.event_type,
                "session_id": event.session_id,
                "project_path": event.project_path,
                "redacted_excerpt": event.transcript_excerpt_or_summary,
            }
        else:
            tree_root = Path(root) if root else _default_tree_root()
            inbox = Path(inbox_path) if inbox_path else tree_root.parent / "inbox"
            result = capture_event(payload, CurationEngine(TreeStore(tree_root), inbox))
            if result.get("ok") and result.get("inbox_path"):
                try:
                    event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "")
                    agent_name = (
                        "claude-code"
                        if event in {"PostCompact", "SessionEnd"}
                        else "codex"
                    )
                    from docmancer.memory.capture import capture_payload

                    retained, indexed = capture_payload(payload, agent=agent_name)
                    result["retained_atoms"] = retained
                    result["indexed"] = indexed
                    if retained:
                        from docmancer.memory import MemoryAgent
                        from docmancer.memory.laptop import LaptopMemoryReconciler

                        result["canonical"] = LaptopMemoryReconciler(
                            MemoryAgent()
                        ).reconcile(use_provider=False)
                    Path(str(result["inbox_path"])).unlink(missing_ok=True)
                    result["processed"] = True
                    result["inbox_path"] = None
                except Exception as exc:  # noqa: BLE001 - capture and reconciliation fail open
                    result["reconcile_error"] = str(exc)[:300]
    if as_json:
        _emit_json(result)
    elif result.get("ok") and result.get("processed"):
        click.echo("Captured and reconciled durable session memory.")
    else:
        click.echo(f"Capture skipped: {result.get('reason') or result.get('note') or result.get('error') or 'not eligible'}", err=True)


def _preview_diff(relative_path: str | None, text: str) -> str:
    destination = relative_path or "inbox/<generated>.md"
    return "\n".join(
        difflib.unified_diff([], text.splitlines(), fromfile="/dev/null", tofile=destination, lineterm="")
    )


@tree_group.command("curate", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Preview or apply one complete curation operation.")
@click.argument("text", required=False)
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--inbox", "inbox_path", default=None, help="Inbox directory. Defaults to ./.docmancer/inbox.")
@click.option("--path", "relative_path", default=None, help="Explicit curated destination relative to the tree root.")
@click.option("--project-id", default=None)
@click.option("--scope", type=click.Choice(["global", "project"]), default="project", show_default=True)
@click.option("--type", "memory_type", default="fact", show_default=True)
@click.option("--tag", "tags", multiple=True)
@click.option("--source", "source_path", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.option("--llm", "use_llm", is_flag=True, help="Opt in to BYOK OpenRouter curation for this operation.")
@click.option("--yes-provider", is_flag=True, help="Confirm that redacted evidence may be sent to the configured provider.")
@click.option("--apply", is_flag=True, help="Write the complete file. Preview is the default.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def curate_command(
    text: str | None,
    root: str | None,
    inbox_path: str | None,
    relative_path: str | None,
    project_id: str | None,
    scope: str,
    memory_type: str,
    tags: tuple[str, ...],
    source_path: Path | None,
    use_llm: bool,
    yes_provider: bool,
    apply: bool,
    as_json: bool,
) -> None:
    """Curate one cited text input deterministically. Preview is non-mutating."""
    from docmancer.memory.tree.curation import CurationEngine

    evidence = source_path.read_text(encoding="utf-8") if source_path else _read_text(text)
    if not evidence.strip():
        raise click.UsageError("provide TEXT, stdin, or --source")
    if use_llm and not yes_provider:
        raise click.UsageError("--llm requires --yes-provider for explicit provider consent")
    preview = _preview_diff(relative_path, evidence)
    if not apply:
        payload = {
            "applied": False,
            "destination": relative_path or "inbox",
            "diff": preview,
            "provider_mode": "BYOK OpenRouter" if use_llm else "deterministic local",
            "source": str(source_path) if source_path else "stdin or argument",
            "exclusions": ["secrets", "mandatory authority", "uncited claims"] if use_llm else [],
        }
    else:
        tree_root = Path(root) if root else _default_tree_root()
        inbox = Path(inbox_path) if inbox_path else tree_root.parent / "inbox"
        fallback_reason = None
        if use_llm:
            from docmancer.memory.tree.byok_curation import BYOKCurationEngine, EvidenceItem

            byok_result = BYOKCurationEngine(TreeStore(tree_root)).curate(
                [EvidenceItem(text=evidence, source=str(source_path) if source_path else "direct-input")],
                scope=scope,
                project_id=project_id,
                memory_type=memory_type,
                tags=list(tags),
            )
            if byok_result.outcome == "written":
                payload = {
                    "applied": True,
                    "destination": "tree",
                    "address": byok_result.entry.address if byok_result.entry else None,
                    "inbox_path": None,
                    "reason": byok_result.reason,
                    "provider": byok_result.provider,
                    "model": byok_result.model,
                    "prompt_version": byok_result.prompt_version,
                    "diff": "Provider synthesis validated and written; re-read the returned address for canonical bytes.",
                }
                result = None
            else:
                fallback_reason = f"{byok_result.outcome}: {byok_result.reason}"
                result = CurationEngine(TreeStore(tree_root), inbox).curate(
                    evidence,
                    relative_path=relative_path,
                    memory_type=memory_type,
                    scope=scope,
                    project_id=project_id,
                    tags=list(tags),
                    source_path=source_path,
                )
        else:
            result = CurationEngine(TreeStore(tree_root), inbox).curate(
                evidence,
                relative_path=relative_path,
                memory_type=memory_type,
                scope=scope,
                project_id=project_id,
                tags=list(tags),
                source_path=source_path,
            )
        if result is not None:
            payload = {
                "applied": True,
                "destination": result.destination,
                "address": result.entry.address if result.entry else None,
                "inbox_path": str(result.inbox_path) if result.inbox_path else None,
                "reason": result.reason,
                "fallback_reason": fallback_reason,
                "diff": preview,
            }
    if as_json:
        _emit_json(payload)
    else:
        click.echo(preview)
        click.echo("Applied." if payload["applied"] else "Preview only. Re-run with --apply to write.")


@tree_group.command("harvest", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Preview or ingest Markdown evidence without rewriting sources.")
@click.argument("sources", nargs=-1, type=click.Path(path_type=Path, exists=True))
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--inbox", "inbox_path", default=None, help="Inbox directory. Defaults to ./.docmancer/inbox.")
@click.option("--apply", is_flag=True, help="Write harvested evidence to the inbox. Preview is the default.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def harvest_command(sources: tuple[Path, ...], root: str | None, inbox_path: str | None, apply: bool, as_json: bool) -> None:
    """Preview project sources, or import an explicit Markdown path."""
    from docmancer.memory.tree.curation import CurationEngine
    from docmancer.memory.tree.harvest import discover_project_harvest_sources, markdown_files

    selection = "explicit"
    discovered: list[dict] = []
    if not sources:
        selection = "current-project"
        config = None
        try:
            from docmancer.memory import MemoryAgent

            config = MemoryAgent().config.discovery
        except Exception:  # noqa: BLE001 - discovery still works with defaults
            pass
        registered = discover_project_harvest_sources(Path.cwd(), config=config)
        sources = tuple(path for item in registered for path in item.files)
        discovered = [
            {
                "harness": item.harness,
                "root": str(item.root),
                "scope": item.scope,
                "file_count": len(item.files),
            }
            for item in registered
        ]
    files = markdown_files(sources)
    before = {path: path.stat().st_mtime_ns for path in files}
    results: list[dict] = []
    if apply:
        tree_root = Path(root) if root else _default_tree_root()
        inbox = Path(inbox_path) if inbox_path else tree_root.parent / "inbox"
        engine = CurationEngine(TreeStore(tree_root), inbox)
        for path in files:
            result = engine.curate(path.read_text(encoding="utf-8")[:MAX_STDIN_BYTES], source_path=path)
            results.append({"source": str(path), "inbox_path": str(result.inbox_path), "status": result.destination})
    else:
        results = [{"source": str(path), "status": "preview"} for path in files]
    if any(path.stat().st_mtime_ns != before[path] for path in files):
        raise click.ClickException("a harvested source changed during the operation; no source rewrite was attempted")
    payload = {
        "applied": apply,
        "selection": selection,
        "project": str(Path.cwd().resolve()),
        "registered_sources": discovered,
        "count": len(results),
        "results": results,
    }
    if as_json:
        _emit_json(payload)
    else:
        click.echo(f"Found {len(results)} Markdown source(s).")
        if selection == "current-project" and not discovered:
            click.echo("No registered sources matched this project. Import an arbitrary directory with: docmancer import ./notes")
        if not apply:
            click.echo("Preview only. Re-run with --apply to write inbox copies.")


@tree_group.command("import", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Import an arbitrary Markdown file or directory into the project inbox.")
@click.argument("sources", nargs=-1, required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--dry-run", is_flag=True, help="List matching files without writing inbox copies.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def import_command(
    sources: tuple[Path, ...],
    project_path: Path | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Copy arbitrary Markdown evidence into the current project's inbox.

    Source files are read-only and never moved or rewritten.
    """
    from docmancer.memory.tree.curation import CurationEngine
    from docmancer.memory.tree.harvest import markdown_files
    from docmancer.memory.tree.project import ensure_project, resolve_project_root

    project_root = resolve_project_root(project_path)
    files = markdown_files(sources)
    before = {path: (path.stat().st_mtime_ns, path.stat().st_size) for path in files}
    results: list[dict] = []
    if dry_run:
        results = [{"source": str(path), "status": "preview"} for path in files]
    else:
        project = ensure_project(project_root)
        engine = CurationEngine(TreeStore(project.tree_root), project.inbox_root)
        for path in files:
            result = engine.curate(
                path.read_text(encoding="utf-8")[:MAX_STDIN_BYTES],
                source_path=path,
            )
            results.append(
                {
                    "source": str(path),
                    "inbox_path": str(result.inbox_path),
                    "status": result.destination,
                }
            )
    if any((path.stat().st_mtime_ns, path.stat().st_size) != before[path] for path in files):
        raise click.ClickException("an imported source changed during the operation; no source rewrite was attempted")
    payload = {
        "imported": not dry_run,
        "project": str(project_root),
        "count": len(results),
        "results": results,
    }
    if as_json:
        _emit_json(payload)
    else:
        action = "Would import" if dry_run else "Imported"
        click.echo(f"{action} {len(results)} Markdown file(s).")
        if not files:
            click.echo("No Markdown files found.")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Write a new or updated curated memory file.")
@click.argument("text", required=False)
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@_GLOBAL_OPTION
@click.option("--path", "relative_path", required=True, help="Path relative to the tree root, e.g. deployment/release.md.")
@click.option("--type", "memory_type", default="fact", show_default=True)
@click.option("--scope", default="global", show_default=True)
@click.option("--authority", default="advisory", show_default=True)
@click.option("--project-id", default=None)
@click.option("--source", "sources", multiple=True, help="Attributed source; repeatable.")
@click.option("--tags", "tags", multiple=True, help="Tag; repeatable.")
@click.option("--status", default="active", show_default=True)
@click.option("--expect", default="absent", show_default=True, help='"absent" for create-only, or the current content hash for a guarded update.')
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def write(
    text: str | None,
    root: str | None,
    global_scope: bool,
    relative_path: str,
    memory_type: str,
    scope: str,
    authority: str,
    project_id: str | None,
    sources: tuple[str, ...],
    tags: tuple[str, ...],
    status: str,
    expect: str,
    as_json: bool,
) -> None:
    """Write TEXT (or stdin, when TEXT is omitted or "-") to --path.

    Prints the resulting stable address, content hash, and revision.
    """
    body = _read_text(text)
    store = _store(root, ensure=True, global_scope=global_scope)
    _guard_canonical_zone(store, relative_path, body)
    try:
        entry = store.write(
            relative_path=relative_path,
            text=body,
            memory_type=memory_type,
            scope=scope,
            authority=authority,
            project_id=project_id,
            sources=list(sources),
            status=status,
            tags=list(tags),
            expect=expect,
            actor_surface="cli",
        )
    except TreeError as exc:
        raise _fail(exc) from exc
    if as_json:
        _emit_json(_entry_dict(entry))
        return
    click.echo(f"Address: {entry.address}")
    click.echo(f"Content hash: {entry.content_hash}")
    click.echo(f"Revision: {entry.revision_id}")
    click.echo(f"Path: {entry.path}")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Read one curated memory file.")
@click.argument("address")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@_GLOBAL_OPTION
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def read(address: str, root: str | None, global_scope: bool, as_json: bool) -> None:
    """Resolve ADDRESS (stable ID, docmancer:// address, path, or title) and print it."""
    store = _store(root, global_scope=global_scope)
    try:
        entry = store.read(address)
    except TreeError as exc:
        raise _fail(exc) from exc
    if as_json:
        data = _entry_dict(entry)
        data["body"] = entry.body
        _emit_json(data)
        return
    click.echo(f"Address: {entry.address}")
    click.echo(f"Title: {entry.title}")
    click.echo(f"Type: {entry.type}  Scope: {entry.scope}  Authority: {entry.authority}")
    click.echo(f"Status: {entry.status}")
    if entry.tags:
        click.echo(f"Tags: {', '.join(entry.tags)}")
    if entry.sources:
        click.echo(f"Sources: {', '.join(entry.sources)}")
    click.echo(f"Content hash: {entry.content_hash}")
    click.echo()
    click.echo(entry.body)


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Edit the body of a curated memory file.")
@click.argument("address")
@click.argument("text", required=False)
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@_GLOBAL_OPTION
@click.option("--expected-hash", required=True, help="The content hash read from `tree read`/`tree write`; guards against a stale write.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def edit(
    address: str,
    text: str | None,
    root: str | None,
    global_scope: bool,
    expected_hash: str,
    as_json: bool,
) -> None:
    """Replace the body of ADDRESS with TEXT (or stdin), guarded by --expected-hash."""
    body = _read_text(text)
    store = _store(root, global_scope=global_scope)
    _guard_canonical_zone(store, address, body)
    try:
        entry = store.edit(address, text=body, expected_hash=expected_hash, actor_surface="cli")
    except TreeError as exc:
        raise _fail(exc) from exc
    if as_json:
        _emit_json(_entry_dict(entry))
        return
    click.echo(f"Address: {entry.address}")
    click.echo(f"New content hash: {entry.content_hash}")
    click.echo(f"Revision: {entry.revision_id}")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Move or rename a curated memory file.")
@click.argument("address")
@click.argument("new_relative_path")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--expected-hash", required=True, help="The content hash read from `tree read`/`tree write`; guards against a stale move.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def move(address: str, new_relative_path: str, root: str | None, expected_hash: str, as_json: bool) -> None:
    """Move or rename ADDRESS to NEW_RELATIVE_PATH inside the same tree root."""
    store = _store(root)
    try:
        entry = store.move(address, new_relative_path, expected_hash=expected_hash, actor_surface="cli")
    except TreeError as exc:
        raise _fail(exc) from exc
    if as_json:
        _emit_json(_entry_dict(entry))
        return
    click.echo(f"Address: {entry.address}")
    click.echo(f"New path: {entry.path}")
    click.echo(f"Content hash: {entry.content_hash}")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Duplicate a curated memory file under a new stable identity.")
@click.argument("address")
@click.argument("new_relative_path")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--expected-hash", required=True, help="The current content hash; guards against duplicating stale content.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def duplicate(address: str, new_relative_path: str, root: str | None, expected_hash: str, as_json: bool) -> None:
    """Copy ADDRESS to NEW_RELATIVE_PATH with a new stable memory ID."""
    try:
        entry = _store(root).duplicate(
            address,
            new_relative_path,
            expected_hash=expected_hash,
            actor_surface="cli",
        )
    except TreeError as exc:
        raise _fail(exc) from exc
    payload = _entry_dict(entry)
    payload["duplicated"] = True
    if as_json:
        _emit_json(payload)
    else:
        click.echo(f"Address: {entry.address}")
        click.echo(f"Path: {entry.path}")
        click.echo(f"Content hash: {entry.content_hash}")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Move a curated memory file to recoverable trash.")
@click.argument("address")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--expected-hash", required=True, help="The current content hash; guards against trashing a changed file.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def trash(address: str, root: str | None, expected_hash: str, as_json: bool) -> None:
    """Move ADDRESS to recoverable trash and return its restore token."""
    try:
        restore_token = _store(root).trash(address, expected_hash=expected_hash, actor_surface="cli")
    except TreeError as exc:
        raise _fail(exc) from exc
    payload = {"trashed": True, "address": address, "restore_token": restore_token}
    if as_json:
        _emit_json(payload)
    else:
        click.echo(f"Moved to recoverable trash: {address}")
        click.echo(f"Restore token: {restore_token}")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Restore a curated memory file from recoverable trash.")
@click.argument("restore_token")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def restore(restore_token: str, root: str | None, as_json: bool) -> None:
    """Restore one trashed file without overwriting a newer destination."""
    try:
        entry = _store(root).restore(restore_token, actor_surface="cli")
    except TreeError as exc:
        raise _fail(exc) from exc
    payload = _entry_dict(entry)
    payload["restored"] = True
    if as_json:
        _emit_json(payload)
    else:
        click.echo(f"Restored: {entry.address}")
        click.echo(f"Path: {entry.path}")
        click.echo(f"Content hash: {entry.content_hash}")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Search curated memory via the Context Compiler.")
@click.argument("query")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--limit", default=10, show_default=True, type=click.IntRange(1), help="Maximum results to show.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def search(query: str, root: str | None, limit: int, as_json: bool) -> None:
    """Search the curated tree for QUERY using the same retrieval as `tree context`."""
    from docmancer.memory.tree.compiler import ContextRequest, compile_context

    store = _store(root)
    request = ContextRequest(task=query, token_budget=1_000_000_000)
    bundle = compile_context(store.index, request)
    items = list(bundle.curated_memory)[:limit]

    if as_json:
        _emit_json(
            [
                {"address": item.address, "title": item.title, "excerpt": item.excerpt, "authority": item.authority}
                for item in items
            ]
        )
        return

    if not items:
        click.echo("No relevant memory found.")
        return

    for index, item in enumerate(items, start=1):
        click.echo(f"[{index}] {item.address}")
        click.echo(f"    {item.title}")
        click.echo(f"    {item.excerpt}")


@tree_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Compile a ContextBundle for a task.")
@click.argument("task")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--project-path", default=None, help="Project path passed through to the ContextRequest.")
@click.option("--project-id", default=None, help="Stable project ID passed through to the ContextRequest.")
@click.option("--agent", default="unknown", show_default=True)
@click.option("--session-id", default=None)
@click.option("--token-budget", default=2000, show_default=True, type=click.IntRange(1))
@click.option("--domain", "requested_domains", multiple=True, help="Requested domain; repeatable.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable ContextBundle output.")
def context(
    task: str,
    root: str | None,
    project_path: str | None,
    project_id: str | None,
    agent: str,
    session_id: str | None,
    token_budget: int,
    requested_domains: tuple[str, ...],
    as_json: bool,
) -> None:
    """Compile the mandatory-policy plus curated-memory ContextBundle for TASK."""
    from docmancer.memory.tree.compiler import ContextRequest, compile_context, context_bundle_payload

    store = _store(root)
    request = ContextRequest(
        task=task,
        project_path=project_path,
        project_id=project_id,
        agent=agent,
        session_id=session_id,
        token_budget=token_budget,
        requested_domains=list(requested_domains),
    )
    bundle = compile_context(store.index, request)

    if as_json:
        _emit_json(context_bundle_payload(bundle))
        return

    click.echo(f"Task: {task}")
    click.echo(f"Token budget: {token_budget}  Estimated tokens used: {bundle.token_estimate}")
    click.echo()
    click.echo(f"Mandatory policies ({len(bundle.mandatory_policies)}):")
    if not bundle.mandatory_policies:
        click.echo("  (none)")
    for item in bundle.mandatory_policies:
        click.echo(f"  - {item.address}  {item.title}")
    click.echo()
    click.echo(f"Curated memory ({len(bundle.curated_memory)}):")
    if not bundle.curated_memory:
        click.echo("  No relevant memory found.")
    for item in bundle.curated_memory:
        click.echo(f"  - {item.address}  {item.title}")


@tree_group.command("reindex", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Rebuild the disposable local index from Markdown files.")
@click.option("--root", default=None, help="Tree root directory. Defaults to ./.docmancer/tree.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def reindex_command(root: str | None, as_json: bool) -> None:
    """Rebuild local derived state without changing canonical Markdown files."""
    store = _store(root)
    count = store.rebuild_index()
    entries = store.index.entries()
    from docmancer.memory.tree.dense_index import TreeDenseIndex

    dense = TreeDenseIndex(store.root)
    try:
        dense_stats = dense.sync(entries)
    finally:
        dense.close()
    revision = hashlib.sha256(
        "\n".join(sorted(f"{entry.memory_id}:{entry.content_hash}" for entry in entries)).encode("utf-8")
    ).hexdigest()[:16]
    payload = {"indexed": count, "root": str(store.root), "index_revision": revision, "dense": dense_stats}
    if as_json:
        _emit_json(payload)
    else:
        click.echo(f"Indexed {count} curated Markdown file(s).")
        click.echo(f"Index revision: {revision}")
        click.echo(f"Dense chunks: {dense_stats['embedded']} embedded, {dense_stats['reused']} reused.")


@tree_group.command("migrate", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Inventory, preview, apply, or roll back legacy record migration.")
@click.option("--records-root", type=click.Path(path_type=Path, file_okay=False), required=True)
@click.option("--tree-root", type=click.Path(path_type=Path, file_okay=False), required=True)
@click.option("--backup-dir", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--apply", "apply_changes", is_flag=True, help="Back up records and apply the migration plan.")
@click.option("--rollback", is_flag=True, help="Restore the legacy record root from --backup-dir.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def migrate_command(
    records_root: Path,
    tree_root: Path,
    backup_dir: Path | None,
    apply_changes: bool,
    rollback: bool,
    as_json: bool,
) -> None:
    """Dry-run by default. Paths are always explicit, with no hidden production root."""
    from docmancer.memory.records import MemoryRecordStore
    from docmancer.memory.tree.migration import (
        apply_migration,
        backup,
        inventory,
        plan_migration,
        rollback_migration,
    )

    if apply_changes and rollback:
        raise click.UsageError("choose either --apply or --rollback")
    if (apply_changes or rollback) and backup_dir is None:
        raise click.UsageError("--backup-dir is required for --apply and --rollback")
    if rollback:
        restored = rollback_migration(backup_dir, records_root)
        payload = {"rolled_back": True, "records_root": str(restored)}
    else:
        record_store = MemoryRecordStore(records_root)
        report = inventory(record_store)
        plan = plan_migration(record_store, None, lambda _record: tree_root)
        payload = {"inventory": report, "plan": plan, "applied": False}
        if apply_changes:
            backup_path = backup(records_root, backup_dir)
            result = apply_migration(plan, record_store, lambda _scope, _project: TreeStore(tree_root))
            payload.update({"applied": True, "backup": str(backup_path), "result": result})
    if as_json:
        _emit_json(payload)
    else:
        if payload.get("rolled_back"):
            click.echo(f"Restored legacy records to {payload['records_root']}")
        elif payload.get("applied"):
            click.echo(json.dumps(payload["result"], indent=2))
        else:
            click.echo(f"Found {payload['inventory']['total_records']} legacy record(s).")
            click.echo("Dry run only. Re-run with --apply and --backup-dir to write.")
