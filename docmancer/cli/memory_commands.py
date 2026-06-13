"""``docmancer memory`` command group.

Scan, sync, query, inspect, and clear the local memory index built from the
memory and instruction files your coding agents already wrote on this machine.
Nothing is uploaded; the index is a local SQLite file.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples


def _agent(include=(), exclude=()):
    from docmancer.memory import MemoryAgent

    return MemoryAgent(include=list(include), exclude=list(exclude))


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Index and recall your coding agents' memory.",
    epilog=format_examples(
        "docmancer memory scan",
        "docmancer memory sync",
        'docmancer memory query "why did we pick Railway"',
        "docmancer memory status",
        "docmancer memory clear",
    ),
)
def memory_group():
    """Local, offline memory harness over Claude Code, Codex, and Cursor.

    Indexes two kinds of content: agent-written memory (Claude Code, Codex) and
    user-authored instruction files (repo-level CLAUDE.md / AGENTS.md, Cursor
    rules) recovered from your agents' project history. `scan` and `sync` report
    the split by kind. Preview before writing with `sync --dry-run`; secrets are
    redacted on index and nothing is uploaded.
    """


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show what would be indexed.")
@click.option("--include", "include", multiple=True, help="Only include entries whose path/scope match this glob.")
@click.option("--exclude", "exclude", multiple=True, help="Exclude entries whose path/scope match this glob.")
def scan(include: tuple[str, ...], exclude: tuple[str, ...]):
    """List the harness memory present on this machine (no indexing)."""
    agent = _agent(include, exclude)
    entries = agent.preview()
    if not entries:
        click.echo("No agent memory found yet. Once your agents write memory, run: docmancer memory sync")
        return
    by_harness = Counter(e.harness for e in entries)
    by_kind = Counter(e.extra.get("kind", "agent-memory") for e in entries)
    click.echo(f"Found {len(entries)} entries across {len(by_harness)} harness(es):")
    for harness, count in sorted(by_harness.items()):
        click.echo(f"  {harness}: {count}")
    click.echo("By kind:")
    for kind, count in sorted(by_kind.items()):
        click.echo(f"  {kind}: {count}")


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Index your agents' memory.")
@click.option("--recreate", is_flag=True, help="Rebuild the memory index from scratch.")
@click.option("--dry-run", is_flag=True, help="Show counts and scopes only; write nothing.")
@click.option("--include", "include", multiple=True, help="Only include entries whose path/scope match this glob.")
@click.option("--exclude", "exclude", multiple=True, help="Exclude entries whose path/scope match this glob.")
def sync(recreate: bool, dry_run: bool, include: tuple[str, ...], exclude: tuple[str, ...]):
    """Harvest, redact, and index agent memory into the local store."""
    agent = _agent(include, exclude)
    if dry_run:
        entries = agent.preview()
        if not entries:
            click.echo("Would index 0 entries.")
            return
        by_scope = Counter(e.scope for e in entries)
        click.echo(f"Would index {len(entries)} entries from {len(by_scope)} scope(s):")
        for scope, count in sorted(by_scope.items()):
            click.echo(f"  {count:>4}  {scope}")
        click.echo("Secrets are redacted on index. Run without --dry-run to write.")
        return
    n = agent.sync(recreate=recreate)
    if n:
        click.echo(f"Indexed {n} memory entries from your coding agents.")
        click.echo('Try: docmancer memory query "..."')
    else:
        click.echo("No agent memory found yet. Once your agents write memory, run: docmancer memory sync")


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Search your agents' memory.")
@click.argument("text")
@click.option("--limit", default=None, type=int, help="Maximum entries to return.")
@click.option(
    "--mode",
    type=click.Choice(["lexical", "dense", "hybrid"], case_sensitive=False),
    default="hybrid",
    show_default=True,
    help="Retrieval mode.",
)
def query(text: str, limit: int | None, mode: str):
    """Recall from the local memory index (hybrid by default)."""
    agent = _agent()
    chunks = agent.query(text, limit=limit, mode=mode.lower())
    if not chunks:
        click.echo("No results found.")
        sys.exit(1)
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata or {}
        scope = meta.get("scope", "")
        kind = meta.get("kind", "")
        click.echo(f"[{i}] score={chunk.score:.2f}  {kind}  {scope}")
        if meta.get("title"):
            click.echo(f"    {meta['title']}")
        click.echo(chunk.text)
        click.echo("---")


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show memory index status.")
def status():
    """Report where the memory index lives and how much it holds."""
    agent = _agent()
    info = agent.status()
    db = Path(info["db_path"])
    click.echo(f"Memory index: {db}")
    click.echo(f"Exists: {db.exists()}")
    click.echo(f"Sources: {info['sources']}")
    click.echo(f"Sections: {info['sections']}")
    click.echo("Nothing is uploaded; this is a local SQLite file. Remove it with: docmancer memory clear")


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Delete the memory index.")
@click.option("--dry-run", is_flag=True, help="Show what would be removed; delete nothing.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
def clear(dry_run: bool, assume_yes: bool):
    """Delete the local memory index files."""
    agent = _agent()
    paths = [p for p in agent.memory_paths() if p.exists()]
    if not paths:
        click.echo("Memory index is already clear.")
        return
    click.echo("Will remove:")
    for p in paths:
        click.echo(f"  {p}")
    if dry_run:
        click.echo("Dry run; no changes made.")
        return
    if not assume_yes:
        click.confirm("Remove the memory index?", abort=True)
    removed = agent.clear()
    click.echo(f"Removed {len(removed)} file(s).")


__all__ = ["memory_group"]
