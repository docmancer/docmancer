"""``docmancer memory`` command group.

Scan, sync, query, inspect, and clear the local memory index built from the
memory and instruction files your coding agents already wrote on this machine.
Sync and recall do not upload anything; the index is stored in local
SQLite-backed files.
"""
from __future__ import annotations

import os
import re
import signal
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.ui import (
    TAGLINE,
    display_path,
    emit_brand_header,
    emit_status_line,
    rule,
    severity_style,
    style,
)
from docmancer.memory.hooks import DEFAULT_HOOK_THRESHOLD


def _emit_counts(heading: str, counts: Counter) -> None:
    """Render a labeled count breakdown, largest first, aligned in a column."""
    if not counts:
        return
    click.echo("  " + style(heading, fg="cyan", bold=True))
    width = max(len(str(key)) for key in counts)
    for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        click.echo(f"    {str(key).ljust(width)}  " + style(str(count), fg="bright_green", bold=True))


def _emit_sync_details(agent) -> None:
    """Show per-agent and per-kind breakdown plus totals and the index path.

    Reads the freshly written index via ``sources()``/``status()`` (no second
    harvest of the agent files on disk).
    """
    info = agent.status()
    rows = agent.sources()
    if rows:
        # The "agent" field is the harness that owns each source; it includes
        # non-agent buckets like "instructions" for user-authored files, so
        # label it "By harness" to match the `scan` command's vocabulary.
        by_harness = Counter(r["agent"] for r in rows)
        by_kind = Counter(r["type"] for r in rows)
        total_chars = sum(int(r.get("chars") or 0) for r in rows)
        _emit_counts("By harness", by_harness)
        _emit_counts("By kind", by_kind)
        click.echo(
            "  "
            + style(f"{total_chars:,}", fg="white", bold=True)
            + f" characters across {info['sources']} source files, {info['atoms']} memory atoms"
        )
    stats = agent.last_sync_stats() if hasattr(agent, "last_sync_stats") else {}
    if stats:
        merged = stats.get("duplicates_merged", 0)
        cross = stats.get("cross_agent_atoms", 0)
        if merged:
            dup_word = "duplicate memory" if merged == 1 else "duplicate memories"
            shared_word = "atom" if cross == 1 else "atoms"
            click.echo(
                "  "
                + style(f"{merged:,}", fg="white", bold=True)
                + f" {dup_word} merged into {cross:,} shared {shared_word} across agents"
            )
        reused = stats.get("sources_reused", 0)
        extracted = stats.get("sources_extracted", 0)
        click.echo(
            "  "
            + style("Incremental", fg="bright_black")
            + f"  re-read {extracted:,} changed source(s), reused {reused:,} unchanged"
        )
    click.echo("  " + style("Index", fg="bright_black") + f"  {display_path(info['db_path'])}")


def _memory_health_audit(agent, entries) -> dict:
    """Build deterministic memory-hygiene findings without changing state."""
    import hashlib
    import json as _json
    from dataclasses import replace

    from docmancer.memory.atomic import extract_atoms

    source_rows = []
    atoms = []
    for entry in entries:
        # PrivacyFilter.clean mutates the entry content. Audit must preserve the
        # raw in-memory copy for the secret detector that runs in the same pass.
        cleaned = agent.privacy.clean(replace(entry))
        entry_atoms = extract_atoms(cleaned)
        atoms.extend(entry_atoms)
        source_rows.append(
            {
                "path": entry.path,
                "display_path": display_path(entry.path),
                "agent": entry.harness,
                "scope": entry.scope,
                "chars": len(entry.content or ""),
                "atoms": len(entry_atoms),
                "content_hash": hashlib.sha256((cleaned.content or "").encode("utf-8")).hexdigest(),
            }
        )

    findings: list[dict] = []
    duplicate_groups: dict[str, list] = defaultdict(list)
    for atom in atoms:
        key = re.sub(r"\s+", " ", atom.text).strip().casefold()
        duplicate_groups[key].append(atom)
    for group in duplicate_groups.values():
        paths = sorted({atom.source_path for atom in group})
        if len(paths) < 2:
            continue
        findings.append(
            {
                "code": "duplicate-memory",
                "severity": "medium",
                "summary": f"The same memory appears in {len(paths)} source files.",
                "paths": paths,
                "display_paths": [display_path(path) for path in paths],
                "excerpt": group[0].text[:240],
                "next": "Keep one authoritative copy, remove stale duplicates, then run `docmancer memory sync --recreate`.",
            }
        )

    for row in source_rows:
        if row["chars"] >= 10_000 and row["atoms"] == 0:
            findings.append(
                {
                    "code": "low-yield-source",
                    "severity": "medium",
                    "summary": f"A {row['chars']:,}-character source produced no usable memory atoms.",
                    "paths": [row["path"]],
                    "display_paths": [row["display_path"]],
                    "next": "Rewrite durable facts as short bullets or remove this source from memory discovery.",
                }
            )
        elif row["chars"] >= 100_000:
            findings.append(
                {
                    "code": "oversized-source",
                    "severity": "low",
                    "summary": f"Large memory source contains {row['chars']:,} characters.",
                    "paths": [row["path"]],
                    "display_paths": [row["display_path"]],
                    "next": "Review whether old run detail can be consolidated or archived outside always-recalled memory.",
                }
            )

    snapshot_path = agent._source_snapshot_path()
    if snapshot_path.is_file():
        try:
            snapshot = _json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a broken snapshot is itself reported below
            snapshot = None
        if not isinstance(snapshot, dict):
            findings.append(
                {
                    "code": "invalid-index-snapshot",
                    "severity": "high",
                    "summary": "The stored source snapshot cannot be read.",
                    "paths": [str(snapshot_path)],
                    "display_paths": [display_path(snapshot_path)],
                    "next": "Run `docmancer memory sync --recreate` to rebuild index provenance.",
                }
            )
        else:
            stored = {
                str(row.get("path")): hashlib.sha256(str(row.get("content") or "").encode("utf-8")).hexdigest()
                for row in snapshot.get("sources", [])
                if row.get("path")
            }
            live = {row["path"]: row["content_hash"] for row in source_rows}
            changed = sorted(path for path in set(stored) & set(live) if stored[path] != live[path])
            added = sorted(set(live) - set(stored))
            removed = sorted(set(stored) - set(live))
            drift = changed + added + removed
            if drift:
                findings.append(
                    {
                        "code": "index-drift",
                        "severity": "high",
                        "summary": (
                            f"The index is stale: {len(changed)} changed, {len(added)} new, "
                            f"and {len(removed)} removed source file(s)."
                        ),
                        "paths": drift,
                        "display_paths": [display_path(path) for path in drift],
                        "next": "Run `docmancer memory sync` before relying on recall.",
                    }
                )

    findings.sort(
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item["severity"], 9),
            item["code"],
            item.get("display_paths", [""])[0],
        )
    )
    return {
        "source_count": len(source_rows),
        "atom_count": len(atoms),
        "agents": dict(Counter(row["agent"] for row in source_rows)),
        "scopes": dict(Counter(row["scope"] for row in source_rows)),
        "findings": findings,
    }
def _agent(include=(), exclude=()):
    from docmancer.memory import MemoryAgent

    return MemoryAgent(include=list(include), exclude=list(exclude))


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Index and recall your coding agents' memory.",
    epilog=format_examples(
        "docmancer memory sync",
        "docmancer memory sources --preview",
        "docmancer memory audit",
        'docmancer memory query "what deployment decisions have we recorded?"',
        "docmancer memory sources",
        "docmancer memory status",
        "docmancer memory clear",
    ),
)
def memory_group():
    """Local, offline memory harness across your coding agents.

    Discovers and indexes three kinds of content from every agent on this
    machine (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and
    more): agent-written memory, user-authored instruction files (CLAUDE.md /
    AGENTS.md / GEMINI.md), and project rule directories. `sources` shows exact
    provenance per file, and `sources --preview` shows what would index before
    writing. Secrets are redacted on index, and local sync/query commands do not
    upload anything.
    """
    if os.environ.get("DOCMANCER_NO_RECURSE") == "1":
        click.echo("docmancer memory commands are disabled inside docmancer subprocesses.", err=True)
        sys.exit(2)


@memory_group.command(
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Show what would be indexed.",
    hidden=True,
)
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
    """Harvest, redact, extract, and index memory atoms in the local store."""
    agent = _agent(include, exclude)
    emit_brand_header("docmancer memory sync", TAGLINE)
    if dry_run:
        entries = agent.preview()
        atoms = agent.atom_preview()
        if not entries:
            emit_status_line("Would index 0 entries; no agent memory found yet.", state="info")
            return
        by_scope = Counter(e.scope for e in entries)
        by_kind = Counter(e.extra.get("kind", "agent-memory") for e in entries)
        by_type = Counter(atom.type for atom in atoms)
        emit_status_line(
            f"Would index {len(atoms)} memory atoms from {len(entries)} source file(s) and {len(by_scope)} scope(s).",
            state="info",
        )
        _emit_counts("By kind", by_kind)
        _emit_counts("By atom type", by_type)
        _emit_counts("By scope", by_scope)
        click.echo()
        emit_status_line("Secrets are redacted on index. Run without --dry-run to write.", state="info")
        return
    started = monotonic()
    seen_stages: set[str] = set()

    def on_progress(stage: str, detail: str = "") -> None:
        if stage in seen_stages or stage == "done":
            return
        seen_stages.add(stage)
        emit_status_line(f"{detail} ({monotonic() - started:.1f}s)", state="info")

    n = agent.sync(recreate=recreate, progress_callback=on_progress)
    if not n:
        emit_status_line(
            "No agent memory found yet. Once your agents write memory, run: docmancer memory sync",
            state="info",
        )
        return
    verb = "Re-indexed" if recreate else "Indexed"
    emit_status_line(f"{verb} {n} memory atoms from your coding agents.")
    _emit_sync_details(agent)
    click.echo()
    click.echo(
        "  "
        + style("Next", fg="bright_green", bold=True)
        + '  docmancer memory query "what deployment decisions have we recorded?"'
    )


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Audit harvested memory for likely secrets.")
@click.option("--agent", "agent_filter", default=None, help="Only audit one agent/harness name.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--fail-on-findings", is_flag=True, help="Exit 1 when likely secrets are found.")
@click.option("--max-findings", default=20, show_default=True, type=click.IntRange(1), help="Maximum health findings in human output; JSON always includes all findings.")
@click.option("--include", "include", multiple=True, help="Only include entries whose path/scope match this glob.")
@click.option("--exclude", "exclude", multiple=True, help="Exclude entries whose path/scope match this glob.")
def audit(agent_filter, as_json, fail_on_findings, max_findings, include, exclude):
    """Audit security, freshness, duplication, and source quality.

    This is local and read-only. Secret scanning happens before redaction, but
    output is always masked. The health pass also compares the live corpus to
    the last sync and identifies duplicate, oversized, and low-yield sources.
    """
    import json as _json

    from docmancer.harness.secrets import detect_secrets

    if not as_json:
        emit_brand_header("docmancer memory audit", "Inspect security, freshness, duplication, and source quality.")
        emit_status_line("Discovering and inspecting live memory sources...", state="info")

    agent = _agent(include, exclude)
    entries = agent.preview()
    if agent_filter:
        entries = [e for e in entries if e.harness.lower() == agent_filter.lower()]
    health = _memory_health_audit(agent, entries)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        for finding in detect_secrets(entry.content or ""):
            grouped[finding.fingerprint].append(
                {
                    "type": finding.type,
                    "severity": finding.severity,
                    "line": finding.line,
                    "source_path": entry.path,
                    "display_path": display_path(entry.path),
                    "agent": entry.harness,
                    "scope": entry.scope,
                    "title": entry.title,
                    "masked_excerpt": finding.masked_excerpt,
                    "fingerprint": finding.fingerprint,
                }
            )

    findings = []
    for fingerprint, occurrences in sorted(
        grouped.items(),
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item[1][0]["severity"], 9),
            item[1][0]["display_path"],
            item[1][0]["line"],
        ),
    ):
        first = occurrences[0]
        findings.append(
            {
                "fingerprint": fingerprint,
                "type": first["type"],
                "severity": first["severity"],
                "occurrences": occurrences,
                "occurrence_count": len(occurrences),
            }
        )

    if as_json:
        click.echo(
            _json.dumps(
                {
                    "finding_count": sum(item["occurrence_count"] for item in findings),
                    "unique_secret_count": len(findings),
                    "findings": findings,
                    "inventory": {
                        "source_count": health["source_count"],
                        "atom_count": health["atom_count"],
                        "agents": health["agents"],
                        "scopes": health["scopes"],
                    },
                    "health_finding_count": len(health["findings"]),
                    "health_findings": health["findings"],
                },
                indent=2,
            )
        )
        if findings and fail_on_findings:
            sys.exit(1)
        return

    emit_status_line(
        f"Audited {health['source_count']:,} source file(s) producing {health['atom_count']:,} memory atoms.",
        state="info",
    )
    _emit_counts("By harness", Counter(health["agents"]))
    click.echo()

    occurrence_total = sum(item["occurrence_count"] for item in findings)
    source_total = len({occ["source_path"] for item in findings for occ in item["occurrences"]})
    by_severity = Counter(item["severity"] for item in findings)

    if findings:
        emit_status_line(
            f"Found {occurrence_total} likely secret occurrence(s) across {source_total} source file(s).",
            state="warn",
        )
        _emit_counts("By severity", by_severity)
        click.echo()
        emit_status_line("Review these source files, rotate any real secrets, then remove them from agent memory.", state="info")
        click.echo()
        click.echo(rule())
        click.echo()
    else:
        emit_status_line("No likely secrets found in harvested memory sources.", state="ok")
        click.echo()

    for index, item in enumerate(findings, start=1):
        first = item["occurrences"][0]
        color, bold = severity_style(item["severity"])
        index_label = style(f"[{index}]", fg="bright_black", bold=True)
        severity_badge = style(item["severity"].upper(), fg=color, bold=bold)
        type_label = style(item["type"], bold=True)
        count_label = style(f"({item['occurrence_count']} occurrence(s))", fg="bright_black")
        click.echo(f"{index_label} {severity_badge}  {type_label}  {count_label}")
        for occurrence in item["occurrences"][:3]:
            location = style(f"{occurrence['display_path']}:{occurrence['line']}", fg="cyan")
            click.echo(f"    {location}")
            click.echo("    " + style(occurrence["masked_excerpt"], fg="bright_black"))
        remaining = item["occurrence_count"] - 3
        if remaining > 0:
            click.echo("    " + style(f"{remaining} more occurrence(s) omitted.", fg="bright_black"))
        click.echo(
            "    "
            + style("Next:", fg="bright_green", bold=True)
            + " rotate if real, delete from the source memory file, then run `docmancer memory sync --recreate`."
        )
        if first.get("scope"):
            click.echo("    " + style("Scope:", fg="bright_black") + f" {first['scope']}")
        click.echo()

    health_findings = health["findings"]
    if health_findings:
        click.echo(rule())
        click.echo()
        emit_status_line(f"Found {len(health_findings)} memory-health issue(s).", state="warn")
        _emit_counts("By issue", Counter(item["code"] for item in health_findings))
        click.echo()
        for index, item in enumerate(health_findings[:max_findings], start=1):
            color, bold = severity_style(item["severity"])
            click.echo(
                style(f"[H{index}]", fg="bright_black", bold=True)
                + " "
                + style(item["severity"].upper(), fg=color, bold=bold)
                + "  "
                + style(item["code"], bold=True)
            )
            click.echo(f"    {item['summary']}")
            for path in item.get("display_paths", [])[:3]:
                click.echo("    " + style(path, fg="cyan"))
            if item.get("excerpt"):
                click.echo("    " + style(item["excerpt"], fg="bright_black"))
            click.echo("    " + style("Next:", fg="bright_green", bold=True) + f" {item['next']}")
            click.echo()
        omitted = len(health_findings) - max_findings
        if omitted > 0:
            emit_status_line(
                f"{omitted} additional health finding(s) omitted. Use `--json` for the complete report.",
                state="info",
            )
            click.echo()
    else:
        emit_status_line("Memory sources are aligned with the last sync and no hygiene issues were found.", state="ok")

    click.echo(rule())
    if fail_on_findings:
        sys.exit(1)


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Search your agents' memory.")
@click.argument("text")
@click.option("--limit", default=None, type=int, help="Maximum entries to return.")
@click.option("--project", "project_path", default=None, type=click.Path(path_type=Path), help="Prefer this project's memory and exclude unrelated projects.")
@click.option("--scope", type=click.Choice(["global", "project", "team"], case_sensitive=False), default=None, help="Only return one memory scope.")
@click.option(
    "--mode",
    type=click.Choice(["lexical", "dense", "hybrid"], case_sensitive=False),
    default="hybrid",
    show_default=True,
    help="Retrieval mode.",
)
@click.option(
    "--min-score",
    default=DEFAULT_HOOK_THRESHOLD,
    type=click.FloatRange(0.0, 1.0),
    show_default=True,
    help="Minimum normalized relevance. Use 0 only for retrieval diagnostics.",
)
def query(
    text: str,
    limit: int | None,
    project_path: Path | None,
    scope: str | None,
    mode: str,
    min_score: float,
):
    """Recall memory atoms from the local memory index."""
    agent = _agent()
    chunks = agent.query(
        text,
        limit=limit,
        mode=mode.lower(),
        project_path=project_path,
        scope=scope,
        min_score=min_score,
    )
    if not chunks:
        emit_brand_header("docmancer memory query", "Recall only when the index has relevant evidence.")
        emit_status_line(f"No relevant memory found at or above score {min_score:.2f}.", state="info")
        click.echo("  Try a more specific query, lower `--min-score` for diagnostics, or run `docmancer memory sync`.")
        sys.exit(1)
    emit_brand_header("docmancer memory query", f"{len(chunks)} relevant match(es), strongest first.")
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata or {}
        scope = meta.get("scope", "")
        kind = meta.get("kind", "")
        memory_type = meta.get("memory_type", "memory")
        click.echo(f"[{i}] score={chunk.score:.2f}  {memory_type}  {kind}  {scope}")
        if meta.get("title"):
            click.echo(f"    {meta['title']}")
        if meta.get("source_path"):
            line = meta.get("line_start")
            suffix = f":{line}" if line else ""
            click.echo(f"    Source: {display_path(meta['source_path'])}{suffix}")
        click.echo(chunk.text)
        click.echo("---")


@memory_group.command("add", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Write a durable local memory.")
@click.argument("text")
@click.option("--scope", "scope_kind", type=click.Choice(["global", "project", "team"], case_sensitive=False), default="global", show_default=True)
@click.option("--project", "project_path", type=click.Path(path_type=Path), default=None, help="Project or Git repository root.")
@click.option("--type", "memory_type", type=click.Choice(["fact", "decision", "preference", "constraint", "workflow", "warning", "command", "status"], case_sensitive=False), default=None)
@click.option("--tag", "tags", multiple=True, help="Tag the memory; repeatable.")
def memory_add(text: str, scope_kind: str, project_path: Path | None, memory_type: str | None, tags: tuple[str, ...]):
    """Add one inspectable memory and index it immediately when possible."""
    agent = _agent()
    try:
        record, indexed = agent.add_record(
            text,
            scope_kind=scope_kind.lower(),
            project_path=project_path,
            memory_type=memory_type.lower() if memory_type else None,
            tags=list(tags),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    emit_brand_header("docmancer memory add", "Write one inspectable, source-attributed memory.")
    emit_status_line(f"Added memory {record.record_id[:12]}")
    click.echo(f"  Type    {style(record.type, fg='cyan', bold=True)}")
    click.echo(f"  Scope   {record.scope}")
    click.echo(f"  Stored  {display_path(record.source_path)}")
    if not indexed:
        emit_status_line("Saved durably; another sync is active. Run `docmancer memory sync` afterward.", state="warn")
    if record.scope_kind == "team":
        click.echo()
        emit_status_line("The new team-memory file may be untracked, so plain `git diff` can be empty.", state="info")
        click.echo("  Review  git status --short .docmancer/memory/")


def _atom_dict(atom) -> dict:
    return {
        "id": atom.record_id or atom.atom_id,
        "atom_id": atom.atom_id,
        "record_id": atom.record_id,
        "text": atom.text,
        "type": atom.type,
        "origin": atom.origin,
        "scope": atom.scope,
        "scope_kind": atom.scope_kind,
        "project_path": atom.project_path,
        "tags": atom.tags,
        "source_path": atom.source_path,
        "source_count": atom.source_count,
        "merged_from": atom.merged_from,
        "timestamp": atom.timestamp,
    }


@memory_group.command("list", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="List inspectable memory atoms.")
@click.option("--scope", type=click.Choice(["global", "project", "team"], case_sensitive=False), default=None)
@click.option("--type", "memory_type", default=None, help="Filter by atom type.")
@click.option("--origin", default=None, help="Filter by origin, such as manual, capture, or harvested.")
@click.option("--project", "project_path", type=click.Path(path_type=Path), default=None)
@click.option("--limit", default=100, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def memory_list(scope, memory_type, origin, project_path, limit, as_json):
    """Browse memory atoms with stable IDs and provenance."""
    import json as _json

    atoms = _agent().indexed_atoms()
    if scope:
        atoms = [atom for atom in atoms if atom.scope_kind == scope.lower()]
    if memory_type:
        atoms = [atom for atom in atoms if atom.type == memory_type.lower()]
    if origin:
        atoms = [atom for atom in atoms if atom.origin == origin.lower()]
    if project_path:
        project = project_path.expanduser().resolve()
        atoms = [atom for atom in atoms if atom.project_path and Path(atom.project_path).expanduser().resolve() == project]
    atoms = atoms[: max(0, limit)]
    if as_json:
        click.echo(_json.dumps([_atom_dict(atom) for atom in atoms], indent=2))
        return
    if not atoms:
        emit_brand_header("docmancer memory list", "Browse stable memory IDs and provenance.")
        emit_status_line("No memory atoms match these filters.", state="info")
        return
    emit_brand_header("docmancer memory list", f"{len(atoms)} inspectable memory item(s).")
    click.echo("  " + style("ID", fg="cyan", bold=True) + " is used by `memory show`, `forget`, and `promote`.")
    click.echo()
    for index, atom in enumerate(atoms, start=1):
        identifier = (atom.record_id or atom.atom_id)[:12]
        click.echo(style(f"[{index}] {identifier}", fg="bright_cyan", bold=True))
        click.echo(f"    {atom.type}  {atom.scope}  {atom.origin}")
        click.echo(f"    {atom.text}")
        click.echo(f"    Source: {display_path(atom.source_path)}")
        if index != len(atoms):
            click.echo()


@memory_group.command("show", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show one memory atom and its provenance.")
@click.argument("identifier", metavar="ID")
@click.option("--json", "as_json", is_flag=True)
def memory_show(identifier: str, as_json: bool):
    """Show one memory using the ID from ``docmancer memory list``.

    ID may be the full stable record or atom ID, or any unique prefix.
    """
    import json as _json

    atom = _agent().find_atom(identifier)
    if atom is None:
        raise click.ClickException("memory ID is missing or ambiguous; copy a unique ID from `docmancer memory list`")
    data = _atom_dict(atom)
    if as_json:
        click.echo(_json.dumps(data, indent=2))
        return
    emit_brand_header("docmancer memory show", "Inspect content and provenance before changing memory.")
    click.echo(f"ID: {data['id']}")
    click.echo(f"Atom: {atom.atom_id}")
    click.echo(f"Type: {atom.type}")
    click.echo(f"Origin: {atom.origin}")
    click.echo(f"Scope: {atom.scope}")
    click.echo(f"Source: {display_path(atom.source_path)}")
    if atom.merged_from:
        click.echo("Merged from: " + ", ".join(display_path(path) for path in atom.merged_from))
    click.echo()
    click.echo(atom.text)


@memory_group.command("forget", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Suppress or remove one memory atom.")
@click.argument("identifier", metavar="ID")
@click.option("--dry-run", is_flag=True, help="Preview the provenance-aware action without changing memory.")
@click.option("--yes", is_flag=True)
def memory_forget(identifier: str, dry_run: bool, yes: bool):
    """Forget the memory identified by ID from ``memory list``.

    ID is a stable record ID or harvested atom ID. A unique prefix, such as
    the 12-character value printed by ``memory list``, is accepted.
    """
    agent = _agent()
    atom = agent.find_atom(identifier)
    if atom is None:
        raise click.ClickException("memory ID is missing or ambiguous; copy a unique ID from `docmancer memory list`")
    action = "remove the Docmancer-owned record" if atom.record_id else "suppress this harvested atom without editing its source"
    emit_brand_header("docmancer memory forget", "Preview provenance-aware removal before confirming.")
    click.echo(f"  ID      {atom.record_id or atom.atom_id}")
    click.echo(f"  Origin  {atom.origin}")
    click.echo(f"  Source  {display_path(atom.source_path)}")
    click.echo(f"  Action  Would {action}.")
    click.echo(f"  Memory  {atom.text}")
    if dry_run:
        click.echo()
        emit_status_line("Dry run only. Nothing was changed.", state="info")
        return
    if not yes:
        click.confirm("Forget this memory?", abort=True)
    agent.forget(identifier)
    emit_status_line("Memory forgotten. Its content is absent from the tombstone.")


@memory_group.command("promote", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Copy a reviewed memory into the Git team store.")
@click.argument("identifier", metavar="ID")
@click.option("--team", is_flag=True, required=True, help="Confirm the destination is team memory.")
@click.option("--project", "project_path", type=click.Path(path_type=Path), default=None)
@click.option("--dry-run", is_flag=True)
def memory_promote(identifier: str, team: bool, project_path: Path | None, dry_run: bool):
    agent = _agent()
    atom = agent.find_atom(identifier)
    if atom is None:
        raise click.ClickException("memory ID is missing or ambiguous; copy a unique ID from `docmancer memory list`")
    project = (project_path or Path.cwd()).expanduser().resolve()
    emit_brand_header("docmancer memory promote", "Copy reviewed memory into the repository team store.")
    click.echo(f"Team destination: {display_path(project / '.docmancer' / 'memory')}")
    click.echo(atom.text)
    if dry_run:
        return
    try:
        record, indexed = agent.promote(identifier, project_path=project)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Promoted {record.record_id[:12]} to {display_path(record.source_path)}")
    click.echo("Review: git status --short .docmancer/memory/")
    if not indexed:
        click.echo("Saved durably; run `docmancer memory sync` after the active sync finishes.")


@memory_group.command("capture-hook", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, hidden=True)
@click.option("--agent", type=click.Choice(["claude-code", "codex"], case_sensitive=False), required=True)
@click.option("--debug", is_flag=True)
def capture_hook(agent: str, debug: bool):
    """Capture durable local memories from a lifecycle hook payload."""
    import json as _json

    try:
        payload = _json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return
        from docmancer.memory.capture import capture_payload

        count, indexed = capture_payload(payload, agent=agent.lower())
        if debug and count:
            click.echo(f"captured {count} memory atom(s); indexed={indexed}", err=True)
    except Exception as exc:  # noqa: BLE001 - capture must never block the agent
        if debug:
            click.echo(f"docmancer capture failed: {exc}", err=True)


@memory_group.command("capture", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Preview lifecycle memory capture without writing.")
@click.option("--agent", type=click.Choice(["claude-code", "codex"], case_sensitive=False), required=True)
@click.option("--input", "input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Hook payload JSON file. Reads stdin when omitted.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable preview output.")
def capture_preview(agent: str, input_path: Path | None, as_json: bool):
    """Preview exactly what a supported lifecycle event would retain.

    The payload is redacted and evaluated locally. This command never creates
    a record, changes the memory index, or enables capture hooks.
    """
    import json as _json

    raw = input_path.read_text(encoding="utf-8") if input_path else sys.stdin.read()
    try:
        payload = _json.loads(raw or "{}")
    except _json.JSONDecodeError as exc:
        raise click.ClickException(f"invalid hook payload JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException("hook payload must be a JSON object")

    from docmancer.memory.capture import capture_candidates

    normalized_agent = agent.lower()
    candidates = capture_candidates(payload, agent=normalized_agent)
    cwd = str(payload.get("cwd") or "").strip()
    scope = f"project:{Path(cwd).expanduser().resolve()}" if cwd else "global:docmancer"
    report = {
        "agent": normalized_agent,
        "event": str(payload.get("hook_event_name") or payload.get("hookEventName") or ""),
        "scope": scope,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "writes_performed": False,
    }
    if as_json:
        click.echo(_json.dumps(report, indent=2))
        return

    emit_brand_header("docmancer memory capture", "Preview local lifecycle capture without writing.")
    if not candidates:
        emit_status_line("This payload produced no durable memory candidates.", state="info")
        return
    emit_status_line(f"Would retain {len(candidates)} memory atom(s) in {scope}.", state="info")
    for index, candidate in enumerate(candidates, start=1):
        click.echo(f"[{index}] {candidate['type']}  {candidate['text']}")
    click.echo()
    emit_status_line("Preview only. No records or index files were changed.", state="info")


@memory_group.command("eval", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Measure recall quality against a JSONL dataset.")
@click.option("--dataset", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option("--gate", is_flag=True, help="Fail below the checked recall-quality thresholds.")
@click.option(
    "--min-score",
    default=DEFAULT_HOOK_THRESHOLD,
    type=click.FloatRange(0.0, 1.0),
    show_default=True,
    help="Minimum normalized relevance used for every evaluation query.",
)
def memory_eval(dataset: Path, output_format: str, gate: bool, min_score: float):
    """Run deterministic top-one, hit-rate, MRR, and latency evaluation."""
    import json as _json
    import statistics
    import tempfile
    import time

    cases = []
    corpus = []
    dataset_metadata = {}
    for number, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = _json.loads(line)
        except _json.JSONDecodeError as exc:
            raise click.ClickException(f"invalid JSONL at line {number}: {exc}") from exc
        if case.get("kind") == "memory":
            corpus.append(case)
        elif case.get("kind") == "case":
            cases.append(case)
        elif case.get("kind") == "metadata":
            dataset_metadata.update(case)
    if not cases:
        raise click.ClickException("dataset contains no cases")
    tempdir = None
    if corpus:
        from docmancer.memory import MemoryAgent

        tempdir = tempfile.TemporaryDirectory(prefix="docmancer-memory-eval-")
        root = Path(tempdir.name)
        agent = MemoryAgent(db_path=str(root / "memory.db"), home=root)
        import hashlib

        for index, item in enumerate(corpus):
            if item.get("forgotten"):
                continue
            identity = f"{index}\n{item.get('id') or ''}\n{item['text']}"
            identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            agent.records.add(
                str(item["text"]),
                record_id=f"eval-{index:04d}-{identity_hash}",
                scope_kind=str(item.get("scope") or "global"),
                project_path=item.get("project_path"),
                memory_type=item.get("type"),
                tags=[str(tag) for tag in item.get("tags", [])],
                origin=str(item.get("origin") or "eval"),
            )
        agent._extra_project_paths.update(
            str(Path(str(item["project_path"])).expanduser().resolve())
            for item in corpus
            if item.get("project_path")
        )
        agent.sync(recreate=True)
    else:
        agent = _agent()
    results = []
    latencies = []
    reciprocal = []
    for case in cases:
        started = time.perf_counter()
        chunks = agent.query(
            str(case["query"]),
            limit=max(5, int(case.get("k") or 5)),
            project_path=case.get("project_path"),
            scope=case.get("scope"),
            min_score=min_score,
        )
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        expected_ids = {str(value) for value in case.get("expected_atom_ids", [])}
        fragments = [str(value).lower() for value in case.get("expected_contains", [])]
        absent_fragments = [str(value).lower() for value in case.get("expected_absent", [])]
        rank = 0
        if case.get("expect_no_results"):
            rank = 1 if not chunks else 0
        elif absent_fragments:
            combined = "\n".join((chunk.text or "").lower() for chunk in chunks)
            rank = 1 if all(fragment not in combined for fragment in absent_fragments) else 0
        else:
            for index, chunk in enumerate(chunks, start=1):
                meta = chunk.metadata or {}
                ids = {str(meta.get("atom_id") or ""), str(meta.get("record_id") or "")}
                text_lower = (chunk.text or "").lower()
                if expected_ids.intersection(ids) or any(fragment in text_lower for fragment in fragments):
                    rank = index
                    break
        reciprocal.append(1 / rank if rank else 0.0)
        results.append(
            {
                "feature": str(case.get("feature") or "unspecified"),
                "query": case["query"],
                "rank": rank or None,
                "latency_ms": round(latency, 2),
            }
        )
    count = len(results)
    sorted_latency = sorted(latencies)
    percentile = lambda p: sorted_latency[min(len(sorted_latency) - 1, int((len(sorted_latency) - 1) * p))]
    report = {
        "cases": count,
        "min_score": min_score,
        "dataset_baseline": dataset_metadata.get("baseline"),
        "top_one_correct": sum(1 for item in results if item["rank"] == 1) / count,
        "hit_at_3": sum(1 for item in results if item["rank"] and item["rank"] <= 3) / count,
        "hit_at_5": sum(1 for item in results if item["rank"] and item["rank"] <= 5) / count,
        "mrr": statistics.mean(reciprocal),
        "latency_p50_ms": round(percentile(0.50), 2),
        "latency_p95_ms": round(percentile(0.95), 2),
        "failed": [item for item in results if item["rank"] is None],
        "results": results,
    }
    if gate:
        gate_config = dataset_metadata.get("gate") if isinstance(dataset_metadata.get("gate"), dict) else {}
        min_top_one = float(gate_config.get("min_top_one_correct", 0.85))
        min_hit_at_3 = float(gate_config.get("min_hit_at_3", 0.95))
        strict_features = {
            str(feature)
            for feature in gate_config.get(
                "zero_failure_features",
                ["scope-isolation", "forget", "conflict-current"],
            )
        }
        failures = []
        if report["top_one_correct"] < min_top_one:
            failures.append(
                f"Top-one correctness {report['top_one_correct']:.1%} is below {min_top_one:.1%}."
            )
        if report["hit_at_3"] < min_hit_at_3:
            failures.append(f"Hit@3 {report['hit_at_3']:.1%} is below {min_hit_at_3:.1%}.")
        for item in results:
            if item["feature"] in strict_features and item["rank"] is None:
                failures.append(f"Strict feature {item['feature']} failed: {item['query']}")
        report["gate"] = {
            "passed": not failures,
            "min_top_one_correct": min_top_one,
            "min_hit_at_3": min_hit_at_3,
            "zero_failure_features": sorted(strict_features),
            "failures": failures,
        }
    if output_format == "json":
        click.echo(_json.dumps(report, indent=2))
        if tempdir is not None:
            tempdir.cleanup()
        if gate and not report["gate"]["passed"]:
            raise click.exceptions.Exit(1)
        return
    click.echo(f"Cases: {count}")
    click.echo(f"Top-one correct: {report['top_one_correct']:.1%}")
    click.echo(f"Hit@3: {report['hit_at_3']:.1%}  Hit@5: {report['hit_at_5']:.1%}  MRR: {report['mrr']:.3f}")
    click.echo(f"Latency: p50 {report['latency_p50_ms']:.2f} ms  p95 {report['latency_p95_ms']:.2f} ms")
    if report["failed"]:
        click.echo("Failed cases:")
        for item in report["failed"]:
            click.echo(f"  - {item['query']}")
    if gate:
        click.echo(f"Quality gate: {'PASS' if report['gate']['passed'] else 'FAIL'}")
        for failure in report["gate"]["failures"]:
            click.echo(f"  - {failure}")
    if tempdir is not None:
        tempdir.cleanup()
    if gate and not report["gate"]["passed"]:
        raise click.exceptions.Exit(1)


@memory_group.command(
    "hook-context",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Emit bounded memory context for agent hooks.",
)
@click.option("--agent", type=click.Choice(["auto", "claude-code", "codex"], case_sensitive=False), default="auto", show_default=True)
@click.option("--limit", default=3, type=int, show_default=True, help="Maximum snippets to inject.")
@click.option("--max-chars", default=2_000, type=int, show_default=True, help="Maximum injected context characters.")
@click.option(
    "--threshold",
    default=DEFAULT_HOOK_THRESHOLD,
    type=click.FloatRange(0.0, 1.0),
    show_default=True,
    help="Minimum normalized relevance required to inject.",
)
@click.option("--debug", is_flag=True, help="Print diagnostic errors to stderr.")
def hook_context(agent: str, limit: int, max_chars: int, threshold: float, debug: bool):
    """Read hook JSON on stdin and emit hook-compatible additional context.

    This command is for Claude Code and Codex lifecycle hooks. It is local and
    read-only from the perspective of agent memory: it queries the existing
    memory index and prints nothing unless relevant, source-backed snippets are
    found quickly.
    """
    from docmancer.memory.hooks import (
        build_hook_context,
        hook_output,
        hook_timeout_ms,
        parse_hook_payload,
    )

    class _HookTimeout(Exception):
        pass

    def _alarm(_signum, _frame):
        raise _HookTimeout()

    previous = None
    timeout_seconds = hook_timeout_ms() / 1000
    if hasattr(signal, "SIGALRM"):
        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        raw = sys.stdin.read()
        payload = parse_hook_payload(raw, agent=agent.lower())
        if payload is None:
            return
        context = build_hook_context(payload, limit=max(0, limit), max_chars=max(1, max_chars), threshold=threshold)
        output = hook_output(payload.event, context)
        if output:
            click.echo(output)
    except _HookTimeout:
        if debug:
            click.echo("docmancer hook-context timed out; injecting no context.", err=True)
    except Exception as exc:  # noqa: BLE001 - hooks must never break the agent turn
        if debug:
            click.echo(f"docmancer hook-context failed: {exc}", err=True)
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.setitimer(signal.ITIMER_REAL, 0)
            if previous is not None:
                signal.signal(signal.SIGALRM, previous)


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="List indexed sources with provenance.")
@click.option("--agent", "agent_filter", default=None, help="Filter by agent/harness name.")
@click.option("--scope", "scope_filter", type=click.Choice(["global", "project", "team"], case_sensitive=False), default=None, help="Filter by scope.")
@click.option(
    "--type",
    "type_filter",
    type=click.Choice(["memory", "agent-memory", "instructions", "rules"], case_sensitive=False),
    default=None,
    help="Filter by kind. Use memory for agent-written memory.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--preview", "live_preview", is_flag=True, help="Live re-harvest (what WOULD index) instead of the stored index.")
@click.option("--include", "include", multiple=True, help="Only include entries whose path/scope match this glob.")
@click.option("--exclude", "exclude", multiple=True, help="Exclude entries whose path/scope match this glob.")
def sources(agent_filter, scope_filter, type_filter, as_json, live_preview, include, exclude):
    """Show every harvested source file and how many atoms it produced."""
    import json as _json

    agent = _agent(include, exclude)
    rows = agent.sources(live_preview=live_preview)
    if type_filter and type_filter.lower() == "memory":
        type_filter = "agent-memory"

    def _keep(row: dict) -> bool:
        if agent_filter and row["agent"].lower() != agent_filter.lower():
            return False
        if scope_filter and not row["scope"].startswith(scope_filter.lower()):
            return False
        if type_filter and row["type"].lower() != type_filter.lower():
            return False
        return True

    rows = [r for r in rows if _keep(r)]
    if as_json:
        rows = [dict(r, display_path=display_path(r["path"])) for r in rows]
        click.echo(_json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No indexed sources match. Run: docmancer memory sync")
        return

    by_agent: Counter = Counter(r["agent"] for r in rows)
    by_type: Counter = Counter(r["type"] for r in rows)
    label = "would index" if live_preview else "indexed"

    # Summary header
    agent_summary = "  ".join(f"{a} ({c})" for a, c in sorted(by_agent.items()))
    click.echo(f"{len(rows)} files {label}  |  {agent_summary}")
    type_summary = "  ".join(f"{k}: {c}" for k, c in sorted(by_type.items()))
    click.echo(f"{'':>{len(str(len(rows))) + 1}}             {type_summary}")
    click.echo()

    # Group rows by agent, preserving the original sort order within each group
    seen_agents: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        a = r["agent"]
        if a not in grouped:
            grouped[a] = []
            seen_agents.append(a)
        grouped[a].append(r)

    for agent_name in seen_agents:
        group = grouped[agent_name]
        count = len(group)
        click.echo(f"  {agent_name.upper()}  ({count})")
        for r in group:
            kind = r["type"]
            short_path = display_path(r["path"])
            chars = f"{r['chars']:,}"
            atoms = f"{int(r.get('atoms') or 0):,}"
            # Fit type label in 13 chars, path fills the middle, counts right-padded
            click.echo(f"    {kind:<13}  {short_path:<60}  {chars} chars  {atoms} atoms")
        click.echo()


_PROVIDER_NOTICE = (
    "Note: this sends your selected local memory text to {provider}. "
    "Secrets are redacted first; nothing is stored remotely by docmancer."
)
_PROVIDER_CHOICES = ["openrouter"]
_DEFAULT_CONSOLIDATE_INPUT_BUDGET = 50_000
_FAST_CONSOLIDATE_INPUT_BUDGET = 35_000
_OPENROUTER_CONSOLIDATE_INPUT_BUDGET = 25_000
_OPENROUTER_FAST_CONSOLIDATE_INPUT_BUDGET = 18_000
_DEFAULT_CONSOLIDATE_MAX_OUTPUT_TOKENS = 4096
_FAST_CONSOLIDATE_MAX_OUTPUT_TOKENS = 2048
_OPENROUTER_CONSOLIDATE_MAX_OUTPUT_TOKENS = 8192
_OPENROUTER_FAST_CONSOLIDATE_MAX_OUTPUT_TOKENS = 4096
_DEFAULT_CONSOLIDATE_CONCURRENCY = 1
_OPENROUTER_CONSOLIDATE_CONCURRENCY = 3
_MERGE_DRAFT_MAX_CHARS = 12_000
_APPROX_CHARS_PER_TOKEN = 4


def _provider_disclosure(provider: str, client=None) -> str:
    label = getattr(client, "provider_name", None) or provider
    if provider == "openrouter":
        return "OpenRouter (cloud)"
    return label


def _expected_provider_errors():
    from docmancer.ai.openrouter_client import OpenRouterConfigError

    return (OpenRouterConfigError,)


def _make_provider_client(provider: str, *, model: str | None, timeout: float | None):
    if provider == "openrouter":
        from docmancer.ai.openrouter_client import OpenRouterClient

        return OpenRouterClient(model=model, timeout_seconds=timeout)
    raise click.ClickException(f"Unsupported provider: {provider}")


def _make_provider_client_or_exit(command: str, provider: str, *, model: str | None, timeout: float | None):
    try:
        return _make_provider_client(provider, model=model, timeout=timeout), provider
    except _expected_provider_errors() as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 - provider setup should not traceback
        click.echo(f"docmancer memory {command} provider setup failed: {exc}", err=True)
        sys.exit(1)


def _run_provider_or_exit(
    command: str,
    provider: str,
    client,
    *,
    model: str | None,
    timeout: float | None,
    fn,
):
    try:
        return fn(client, model)
    except _expected_provider_errors() as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 - provider/runtime errors must not traceback
        provider_label = getattr(client, "provider_name", None) or provider
        click.echo(f"docmancer memory {command} failed calling {provider_label}: {exc}", err=True)
        sys.exit(1)


def _chunk_to_atom(chunk):
    from docmancer.memory.atomic import AtomicMemoryEntry

    meta = chunk.metadata or {}
    return AtomicMemoryEntry(
        atom_id=str(meta.get("atom_id") or meta.get("section_id") or ""),
        text=str(chunk.text or ""),
        type=str(meta.get("memory_type") or "fact"),
        harness=str(meta.get("harness") or ""),
        kind=str(meta.get("kind") or "agent-memory"),
        scope=str(meta.get("scope") or ""),
        source_path=str(meta.get("source_path") or chunk.source or ""),
        source_title=str(meta.get("title") or ""),
        line_start=int(meta.get("line_start") or 0),
        line_end=int(meta.get("line_end") or 0),
        source_hash=str(meta.get("source_hash") or ""),
        content_hash=str(meta.get("content_hash") or ""),
        source_chars=int(meta.get("source_chars") or 0),
        confidence=float(meta.get("confidence") or 1.0),
        tags=[str(tag) for tag in meta.get("tags", []) if tag],
        status=str(meta.get("status") or "active"),
        timestamp=meta.get("timestamp"),
    )


def _selected_atoms(agent, *, query: str | None, limit: int | None):
    """Return memory atoms from the index, with live preview as fallback."""
    atoms = []
    if query:
        try:
            chunks = agent.query(query, limit=limit or 20, min_score=None)
            atoms = [_chunk_to_atom(chunk) for chunk in chunks]
        except Exception:  # noqa: BLE001 - retrieval is best-effort; fall back to all
            pass
    if not atoms:
        atoms = agent.indexed_atoms(limit=limit)
    if not atoms:
        atoms = agent.atom_preview()
    if limit:
        atoms = atoms[:limit]
    return atoms


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + _APPROX_CHARS_PER_TOKEN - 1) // _APPROX_CHARS_PER_TOKEN)


def _payload_entry_overhead_tokens(entry: dict) -> int:
    header = (
        "### Entry\n"
        f"scope: {entry.get('scope', '')}\n"
        f"title: {entry.get('title', '')}\n"
        f"source: {entry.get('source_path', '')}\n\n"
    )
    return _estimate_tokens(header)


def _payload_entry_tokens(entry: dict) -> int:
    return _payload_entry_overhead_tokens(entry) + _estimate_tokens(entry.get("text", ""))


def _entries_to_payload(entries) -> list[dict]:
    return [{"scope": e.scope, "title": e.title, "source_path": e.path, "text": e.content} for e in entries]


def _split_payload_entry(entry: dict, *, budget: int | None) -> list[dict]:
    if budget is None or budget <= 0:
        return [entry]

    overhead = _payload_entry_overhead_tokens(entry)
    content = entry.get("text", "")
    content_budget = max(1, budget - overhead)
    content_tokens = _estimate_tokens(content)
    if overhead + content_tokens <= budget:
        return [entry]

    max_chars = max(1, content_budget * _APPROX_CHARS_PER_TOKEN)
    parts = [content[i : i + max_chars] for i in range(0, len(content), max_chars)] or [""]
    total = len(parts)
    split = []
    for i, part in enumerate(parts, start=1):
        item = dict(entry)
        item["title"] = f"{entry.get('title', '')} (part {i}/{total})"
        item["text"] = part
        split.append(item)
    return split


def _chunk_payload_entries(payload: list[dict], *, budget: int | None) -> tuple[list[list[dict]], dict]:
    """Split payload entries into approximate per-request batches without trimming.

    If a single entry exceeds the per-request budget, its text is divided into
    ordered parts that keep the same source path. Every selected character is
    still sent to the selected provider.
    """
    original_tokens = sum(_payload_entry_tokens(e) for e in payload)
    expanded: list[dict] = []
    split_entries = 0
    for entry in payload:
        parts = _split_payload_entry(entry, budget=budget)
        if len(parts) > 1:
            split_entries += 1
        expanded.extend(parts)

    if budget is None or budget <= 0:
        total_tokens = sum(_payload_entry_tokens(e) for e in expanded)
        return [expanded], {
            "original_tokens": original_tokens,
            "request_tokens": [total_tokens],
            "split_entries": split_entries,
            "expanded_entries": len(expanded),
        }

    batches: list[list[dict]] = []
    current: list[dict] = []
    current_tokens = 0
    request_tokens: list[int] = []

    for entry in expanded:
        tokens = _payload_entry_tokens(entry)
        if current and current_tokens + tokens > budget:
            batches.append(current)
            request_tokens.append(current_tokens)
            current = []
            current_tokens = 0
        current.append(entry)
        current_tokens += tokens

    if current:
        batches.append(current)
        request_tokens.append(current_tokens)

    return batches, {
        "original_tokens": original_tokens,
        "request_tokens": request_tokens,
        "split_entries": split_entries,
        "expanded_entries": len(expanded),
    }


def _fmt_count(value: int | None, suffix: str) -> str:
    if value is None:
        return "n/a"
    return f"{value:,} {suffix}"


def _fmt_timeout(timeout_ms: int | None) -> str:
    return "provider default" if timeout_ms is None else f"{timeout_ms / 1000:g}s"


def _fmt_seconds(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _is_openrouter_client(client) -> bool:
    return (getattr(client, "provider_name", "") or "").lower() == "openrouter"


def _default_consolidate_budget(*, draft_quality: str, client) -> int:
    if _is_openrouter_client(client):
        return (
            _OPENROUTER_FAST_CONSOLIDATE_INPUT_BUDGET
            if draft_quality == "fast"
            else _OPENROUTER_CONSOLIDATE_INPUT_BUDGET
        )
    return _FAST_CONSOLIDATE_INPUT_BUDGET if draft_quality == "fast" else _DEFAULT_CONSOLIDATE_INPUT_BUDGET


def _default_consolidate_max_output_tokens(*, draft_quality: str, client) -> int:
    if _is_openrouter_client(client):
        return (
            _OPENROUTER_FAST_CONSOLIDATE_MAX_OUTPUT_TOKENS
            if draft_quality == "fast"
            else _OPENROUTER_CONSOLIDATE_MAX_OUTPUT_TOKENS
        )
    return _FAST_CONSOLIDATE_MAX_OUTPUT_TOKENS if draft_quality == "fast" else _DEFAULT_CONSOLIDATE_MAX_OUTPUT_TOKENS


def _default_consolidate_concurrency(*, client) -> int:
    if _is_openrouter_client(client):
        return _OPENROUTER_CONSOLIDATE_CONCURRENCY
    return _DEFAULT_CONSOLIDATE_CONCURRENCY


def _emit_block(title: str, rows: list[tuple[str, object | None]], *, err: bool = True) -> None:
    click.echo("", err=err)
    click.echo(title, err=err)
    width = max((len(label) for label, _ in rows), default=0)
    for label, value in rows:
        click.echo(f"  {label:<{width}}  {value}", err=err)


def _format_action_title(action: str) -> str:
    title = action.title()
    return title.replace("Api", "API")


def _emit_consolidation_plan(
    *,
    provider_label: str,
    chunks: list[list[dict]],
    stats: dict,
    budget: int | None,
    max_output_tokens: int | None,
    draft_quality: str,
    concurrency: int,
) -> None:
    merge_step = "yes" if len(chunks) > 1 else "no"
    rows: list[tuple[str, object | None]] = [
        ("payload parts", stats["expanded_entries"]),
        ("provider requests", f"{len(chunks)} {provider_label} request(s)"),
        ("estimated input", _fmt_count(stats.get("original_tokens"), "tokens")),
        ("batch budget", "single request" if budget is None or budget <= 0 else _fmt_count(budget, "tokens")),
        ("output cap", "provider default" if max_output_tokens is None else _fmt_count(max_output_tokens, "tokens")),
        ("draft quality", draft_quality),
        ("concurrency", concurrency),
        ("merge step", merge_step),
    ]
    if stats["split_entries"]:
        rows.append(("split entries", f"{stats['split_entries']} oversized source entr(y/ies), no text trimmed"))
    _emit_block("Consolidation Plan", rows)


def _provider_request_status(action: str, client, *, token_count: int | None = None) -> None:
    provider = getattr(client, "provider_name", None) or "provider"
    model = getattr(client, "model", None) or "configured model"
    timeout_ms = getattr(client, "timeout_ms", None)
    rows: list[tuple[str, object | None]] = [
        ("provider", provider),
        ("model", model),
        ("timeout", _fmt_timeout(timeout_ms)),
    ]
    if token_count is not None:
        rows.append(("input", f"~{token_count:,} tokens"))
    _emit_block(_format_action_title(action), rows)


def _streaming_progress(label: str):
    """Return ``(on_progress, finish)`` for a live "receiving response" heartbeat.

    A provider can take over a minute to generate a large structured draft.
    Without feedback that silent gap reads as a hang, so we surface incoming
    bytes as the stream arrives. On a TTY this updates one line in place; when
    piped it prints a fresh throttled line. ``finish`` closes the in-place line
    with a newline.
    """
    import time as _time

    state = {"last": 0.0, "started": _time.monotonic(), "printed": False}
    tty = bool(getattr(sys.stderr, "isatty", lambda: False)())

    def on_progress(chars: int) -> None:
        now = _time.monotonic()
        if state["printed"] and now - state["last"] < 0.5:
            return
        state["last"] = now
        elapsed = now - state["started"]
        message = f"  {label}: receiving response... {chars:,} chars, {elapsed:.0f}s"
        if tty:
            click.echo("\r" + message + "    ", nl=False, err=True)
        else:
            click.echo(message, err=True)
        state["printed"] = True

    def finish() -> None:
        if state["printed"] and tty:
            click.echo("", err=True)

    return on_progress, finish


def _consolidate_streaming(consolidate_memory, label, **kwargs):
    """Call ``consolidate_memory`` with a live progress heartbeat under ``label``."""
    on_progress, finish = _streaming_progress(label)
    try:
        return consolidate_memory(on_progress=on_progress, **kwargs)
    finally:
        finish()


def _provider_preflight(client, *, model: str | None = None) -> None:
    """Send a tiny provider request before large memory payloads."""
    _provider_request_status("API preflight", client)
    client.preflight(model=model)
    click.echo(f"  status   ok", err=True)


def _consolidate_payload_in_rounds(
    payload: list[dict],
    *,
    instruction: str | None,
    client,
    model: str | None,
    budget: int | None,
    draft_quality: str,
    max_output_tokens: int | None,
    concurrency: int,
):
    """Map-reduce memory consolidation while preserving every selected entry."""
    from docmancer.ai.memory_features import consolidate_memory, draft_to_markdown, draft_to_merge_text

    current_payload = payload
    current_instruction = instruction
    round_no = 1

    while True:
        chunks, stats = _chunk_payload_entries(current_payload, budget=budget)
        provider_label = getattr(client, "provider_name", None) or "provider"
        _emit_consolidation_plan(
            provider_label=provider_label,
            chunks=chunks,
            stats=stats,
            budget=budget,
            max_output_tokens=max_output_tokens,
            draft_quality=draft_quality,
            concurrency=concurrency,
        )

        if len(chunks) == 1:
            token_count = stats["request_tokens"][0] if stats.get("request_tokens") else None
            _provider_request_status("memory consolidation", client, token_count=token_count)
            started = monotonic()
            draft = _consolidate_streaming(
                consolidate_memory,
                "memory consolidation",
                entries=chunks[0],
                instruction=current_instruction,
                client=client,
                model=model,
                draft_quality=draft_quality,
                max_tokens=max_output_tokens,
            )
            markdown = draft_to_markdown(draft)
            click.echo(f"  status   completed", err=True)
            click.echo(f"  output   {len(markdown):,} chars", err=True)
            click.echo(f"  duration {_fmt_seconds(monotonic() - started)}", err=True)
            return draft

        def _run_batch(i: int, chunk: list[dict]):
            token_count = stats["request_tokens"][i - 1]
            batch_instruction = (
                f"{current_instruction or 'Consolidate these into a coherent master memory draft.'}\n\n"
                f"This is batch {i} of {len(chunks)} in consolidation round {round_no}. "
                "Preserve durable facts, conflicts, warnings, and source paths. "
                "Do not assume other batches contain the same information."
            )
            started = monotonic()
            draft = _consolidate_streaming(
                consolidate_memory,
                f"memory consolidation batch {i}/{len(chunks)}",
                entries=chunk,
                instruction=batch_instruction,
                client=client,
                model=model,
                draft_quality=draft_quality,
                max_tokens=max_output_tokens,
            )
            source_files = [e.get("source_path", "") for e in chunk if e.get("source_path")]
            draft.source_paths = list(dict.fromkeys([*draft.source_paths, *source_files]))
            markdown = draft_to_markdown(draft, source_files=source_files)
            merge_text = draft_to_merge_text(draft, source_files=source_files, max_chars=_MERGE_DRAFT_MAX_CHARS)
            return i, {
                "scope": "docmancer-consolidation",
                "title": f"Round {round_no} batch {i} consolidated draft",
                "source_path": f"docmancer://memory-consolidate/round-{round_no}/batch-{i}",
                "text": merge_text,
            }, len(markdown), len(merge_text), monotonic() - started

        drafts_by_index = {}
        workers = max(1, min(concurrency, len(chunks)))
        for i, chunk in enumerate(chunks, start=1):
            token_count = stats["request_tokens"][i - 1]
            _provider_request_status(f"memory consolidation batch {i}/{len(chunks)}", client, token_count=token_count)
        if workers == 1:
            for i, chunk in enumerate(chunks, start=1):
                index, draft_entry, markdown_size, merge_size, elapsed = _run_batch(i, chunk)
                click.echo(f"  status   completed", err=True)
                click.echo(f"  output   {markdown_size:,} chars", err=True)
                click.echo(f"  merge    {merge_size:,} chars", err=True)
                click.echo(f"  duration {_fmt_seconds(elapsed)}", err=True)
                drafts_by_index[index] = draft_entry
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_run_batch, i, chunk): i for i, chunk in enumerate(chunks, start=1)}
                for future in as_completed(futures):
                    index, draft_entry, markdown_size, merge_size, elapsed = future.result()
                    click.echo(f"  batch    {index}/{len(chunks)} completed", err=True)
                    click.echo(f"  output   {markdown_size:,} chars", err=True)
                    click.echo(f"  merge    {merge_size:,} chars", err=True)
                    click.echo(f"  duration {_fmt_seconds(elapsed)}", err=True)
                    drafts_by_index[index] = draft_entry

        drafts = [drafts_by_index[i] for i in range(1, len(chunks) + 1)]

        current_payload = drafts
        current_instruction = (
            "Merge these batch-level consolidated drafts into one final review-only master memory draft. "
            "Preserve all durable facts, conflicts, warnings, and original source paths. "
            "Deduplicate repeated facts, but do not drop unique details. Keep the final result compact."
        )
        round_no += 1
        if round_no > 6:
            raise RuntimeError(
                "memory consolidation still exceeded the per-request budget after 5 merge rounds; "
                "increase --budget or narrow the selection with --query, --include, or --limit."
            )


# Default draft path shared by `consolidate` (where it writes) and `apply`
# (what it reads when `--from` is omitted), so the two commands chain with no
# arguments: `consolidate` then `apply --agent codex`.
_DEFAULT_DRAFT = "master-memory-draft.md"


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Consolidate memory into a review-only draft.")
@click.option("--query", "query", default=None, help="Focus the consolidation on memory relevant to this query.")
@click.option("--output", "output", default=None, help=f"Where to write the draft (default {_DEFAULT_DRAFT}, or a .okf bundle dir for --format okf).")
@click.option("output_format", "--format", type=click.Choice(["md", "okf"], case_sensitive=False), default="md", show_default=True, help="Draft format: a single markdown file, or an OKF bundle.")
@click.option("--limit", default=100, type=int, show_default=True, help="Max entries to consolidate.")
@click.option("--budget", default=None, type=int, help="Approximate input-token budget per provider request. Defaults are provider-specific; use 0 to send in one request.")
@click.option("--provider", type=click.Choice(_PROVIDER_CHOICES, case_sensitive=False), default="openrouter", show_default=True, help="Provider for consolidation.")
@click.option("--model", default=None, help="Override the provider model. For OpenRouter, pass any OpenRouter model id, for example openai/gpt-4.1-nano.")
@click.option("--draft-quality", type=click.Choice(["standard", "fast"], case_sensitive=False), default="standard", show_default=True, help="Use fast for smaller batches and more aggressive compression.")
@click.option("--max-output-tokens", default=None, type=int, help="Hard cap for generated output per provider request. Defaults are provider-specific; use 0 for provider default.")
@click.option("--concurrency", default=None, type=int, help="Parallel consolidation requests. Defaults are provider-specific; use 1 for serial execution.")
@click.option("--timeout", "timeout", default=None, type=float, help="Seconds per provider request (provider-specific default, or provider timeout env var; use 0 for provider default).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the provider-use confirmation.")
@click.option("--include", "include", multiple=True, help="Only include entries whose path/scope match this glob.")
@click.option("--exclude", "exclude", multiple=True, help="Exclude entries whose path/scope match this glob.")
def consolidate(
    query,
    output,
    output_format,
    limit,
    budget,
    provider,
    model,
    draft_quality,
    max_output_tokens,
    concurrency,
    timeout,
    assume_yes,
    include,
    exclude,
):
    """Produce a review-only consolidated memory draft.

    Writes a markdown draft (or an OKF bundle with --format okf) for you to
    review; it never edits agent files. Use `docmancer memory apply --from
    <draft>` to materialize a markdown draft after review.
    """
    provider = provider.lower()
    draft_quality = draft_quality.lower()
    agent = _agent(include, exclude)
    entries = _selected_atoms(agent, query=query, limit=limit)
    if not entries:
        click.echo("No memory atoms to consolidate. Run: docmancer memory sync")
        sys.exit(1)
    client, active_provider = _make_provider_client_or_exit("consolidate", provider, model=model, timeout=timeout)
    provider_label = getattr(client, "provider_name", None) or provider
    click.echo(_PROVIDER_NOTICE.format(provider=_provider_disclosure(active_provider, client)), err=True)
    if not assume_yes:
        click.confirm(f"Send the selected memory to {provider_label}?", abort=True, err=True)

    from docmancer.ai.memory_features import draft_to_markdown

    payload = _entries_to_payload(entries)
    source_files = [e.path for e in entries]
    def _call(active_client, active_model):
        resolved_budget = budget
        if resolved_budget is None:
            resolved_budget = _default_consolidate_budget(draft_quality=draft_quality, client=active_client)
        resolved_max_output_tokens = max_output_tokens
        if resolved_max_output_tokens is None:
            resolved_max_output_tokens = _default_consolidate_max_output_tokens(
                draft_quality=draft_quality, client=active_client
            )
        if resolved_max_output_tokens <= 0:
            resolved_max_output_tokens = None
        resolved_concurrency = concurrency
        if resolved_concurrency is None:
            resolved_concurrency = _default_consolidate_concurrency(client=active_client)
        resolved_concurrency = max(1, resolved_concurrency)
        _provider_preflight(active_client, model=active_model)
        return _consolidate_payload_in_rounds(
            payload,
            instruction=query,
            client=active_client,
            model=active_model,
            budget=resolved_budget,
            draft_quality=draft_quality,
            max_output_tokens=resolved_max_output_tokens,
            concurrency=resolved_concurrency,
        )

    # The draft is only written after a successful call, so any failure leaves
    # no partial output behind.
    draft = _run_provider_or_exit(
        "consolidate", active_provider, client, model=model, timeout=timeout, fn=_call
    )
    draft.source_paths = list(dict.fromkeys(source_files))

    if output_format.lower() == "okf":
        from docmancer.okf.adapters import concepts_from_draft
        from docmancer.okf.bundle import write_bundle

        bundle_dir = Path(output) if output else Path("master-memory-draft.okf")
        result = write_bundle(
            bundle_dir,
            concepts_from_draft(draft),
            title=draft.title or "Consolidated memory (review only)",
        )
        _emit_block(
            "Output",
            [
                ("path", display_path(result.root)),
                ("format", "okf"),
                ("sources", len(entries)),
                ("next", f"docmancer okf doctor {display_path(result.root)}"),
            ],
            err=False,
        )
        click.echo("Review it before sharing. memory apply expects a markdown draft, not a bundle.")
        return

    markdown = draft_to_markdown(draft, source_files=source_files)
    out_path = Path(output) if output else Path(_DEFAULT_DRAFT)
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    _emit_block(
        "Output",
        [
            ("path", display_path(out_path)),
            ("format", "markdown"),
            ("sources", len(entries)),
            ("size", f"{len(markdown):,} chars"),
            ("next", f"docmancer memory apply --from {display_path(out_path)} --agent codex"),
        ],
        err=False,
    )


_MEMORY_BLOCK_BEGIN = "<!-- docmancer:memory:begin (managed; edits inside are overwritten on next apply) -->"
_MEMORY_BLOCK_END = "<!-- docmancer:memory:end -->"

_APPLY_TARGETS = {
    "claude-code": (".claude", "CLAUDE.md"),
    "cline": (".cline", "AGENTS.md"),
    "codex": (".codex", "AGENTS.md"),
    "cursor": (".cursor", "AGENTS.md"),
    "gemini": (".gemini", "GEMINI.md"),
    "github-copilot": (".copilot", "copilot-instructions.md"),
    "opencode": (".config/opencode", "AGENTS.md"),
}


def _render_atoms_for_apply(atoms, *, limit: int = 80) -> str:
    selected = list(atoms)[:limit]
    lines = [
        "# docmancer memory atoms",
        "",
        "These memory atoms are generated from the local Docmancer index.",
        "",
    ]
    for atom in selected:
        source = display_path(atom.source_path) if atom.source_path else "unknown source"
        suffix = f":{atom.line_start}" if atom.line_start else ""
        lines.append(f"- [{atom.type}] {atom.text} Source: {source}{suffix}")
    return "\n".join(lines).rstrip() + "\n"


def _apply_target_path(agent: str | None, output: str | None):
    from docmancer.harness.base import default_home

    if output:
        return Path(output)
    if agent and agent in _APPLY_TARGETS:
        sub, name = _APPLY_TARGETS[agent]
        return default_home() / sub / name
    return None


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Materialize a reviewed draft into an agent's file.")
@click.option("--from", "from_path", default=None, help="Apply a reviewed draft markdown file instead of rendering memory atoms from the index.")
@click.option("--agent", type=click.Choice(sorted(_APPLY_TARGETS), case_sensitive=False), default=None, help="Target agent whose always-loaded file to write.")
@click.option("--output", "output", default=None, help="Write to an arbitrary file instead of an agent target.")
@click.option("--dry-run", is_flag=True, help="Show the diff; write nothing.")
@click.option("--print", "print_only", is_flag=True, help="Print the resolved target and block; write nothing.")
@click.option("--remove", "remove", is_flag=True, help="Strip docmancer's managed block (clean uninstall).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
def apply(from_path, agent, output, dry_run, print_only, remove, assume_yes):
    """Write memory atoms into an agent's always-loaded file.

    Local and keyless. Writes only inside a delimited managed block, after a
    timestamped backup. With no `--from`, this renders high-value atomic
    memories from the local index. `--from` remains available for older reviewed
    drafts written by `docmancer memory consolidate`.
    """
    from docmancer.cli.managed_block import diff_block, remove_block, upsert_block

    target = _apply_target_path(agent, output)
    if target is None:
        choices = "|".join(sorted(_APPLY_TARGETS))
        click.echo(f"Specify a target: --agent {{{choices}}} or --output <path>.", err=True)
        sys.exit(2)

    if remove:
        if not target.exists():
            click.echo(f"Nothing to remove; {display_path(target)} does not exist.")
            return
        if print_only or dry_run:
            click.echo(f"Would remove docmancer managed block from {display_path(target)}.")
            return
        if not assume_yes:
            click.confirm(f"Remove docmancer's managed block from {display_path(target)}?", abort=True)
        removed, backup = remove_block(target, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END)
        if removed:
            suffix = f" Backup: {display_path(backup)}" if backup else ""
            click.echo(f"Removed managed block from {display_path(target)}.{suffix}")
        else:
            click.echo(f"No docmancer managed block found in {display_path(target)}.")
        return

    if from_path:
        src = Path(from_path).expanduser()
        if not src.is_file():
            click.echo(f"Draft not found: {display_path(src)}", err=True)
            sys.exit(2)
        body = src.read_text(encoding="utf-8")
    else:
        memory_agent = _agent()
        atoms = memory_agent.indexed_atoms(limit=80)
        if not atoms:
            click.echo("No memory atoms found. Run `docmancer memory sync` first.", err=True)
            sys.exit(2)
        body = _render_atoms_for_apply(atoms)

    if print_only:
        click.echo(f"Target: {display_path(target)}")
        click.echo("")
        from docmancer.cli.managed_block import build_block

        click.echo(build_block(body, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END))
        return

    if dry_run:
        click.echo(f"Target: {display_path(target)}")
        click.echo(diff_block(target, body, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END) or "(no changes)")
        return

    if not assume_yes:
        click.confirm(f"Write docmancer's managed block into {display_path(target)}?", abort=True)

    action, backup = upsert_block(target, body, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END)
    click.echo(f"{action.capitalize()} docmancer managed block in {display_path(target)}.")
    if backup:
        click.echo(f"Backup written to {display_path(backup)}")
    click.echo(
        "Undo: docmancer memory apply --remove"
        + (f" --agent {agent}" if agent else f" --output {display_path(target)}")
        + ", or restore the backup."
    )


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Export memory as a portable OKF bundle.")
@click.option("output_format", "--format", type=click.Choice(["okf"], case_sensitive=False), default="okf", show_default=True, help="Export format.")
@click.option("--output", "output", default="memory.okf", show_default=True, help="Bundle directory to write.")
@click.option("--query", "query", default=None, help="Only export memory relevant to this query.")
@click.option("--limit", default=None, type=int, help="Max entries to export.")
@click.option("--include", "include", multiple=True, help="Only include entries whose path/scope match this glob.")
@click.option("--exclude", "exclude", multiple=True, help="Exclude entries whose path/scope match this glob.")
def export(output_format, output, query, limit, include, exclude):
    """Export your cross-agent memory as a Google OKF bundle (local, keyless).

    Writes a directory of markdown files with YAML frontmatter that any
    OKF-aware tool can read. Secrets are redacted first; nothing is uploaded.
    """
    from datetime import datetime, timezone

    from docmancer.okf.adapters import concepts_from_memory_entries
    from docmancer.okf.bundle import write_bundle

    agent = _agent(include, exclude)
    entries = _selected_atoms(agent, query=query, limit=limit)
    if not entries:
        click.echo("No memory atoms to export. Run: docmancer memory sync")
        sys.exit(1)

    concepts = concepts_from_memory_entries(entries)
    today = datetime.now(timezone.utc).date().isoformat()
    result = write_bundle(
        Path(output),
        concepts,
        title="docmancer cross-agent memory",
        log_entries=[f"{today}: exported {len(concepts)} concept(s) from docmancer memory"],
    )
    click.echo(f"Wrote OKF bundle to {display_path(result.root)} ({result.concept_count} concept(s)).")
    click.echo(f"Validate it with: docmancer okf doctor {display_path(result.root)}")


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show memory index status.")
def status():
    """Report where the memory index lives and how much it holds."""
    agent = _agent()
    info = agent.status()
    db = Path(info["db_path"])
    click.echo(f"Memory index: {display_path(db)}")
    click.echo(f"Exists: {db.exists()}")
    click.echo(f"Source files: {info['sources']}")
    click.echo(f"Memory atoms: {info['atoms']}")
    click.echo("Sync and recall stay local. Remove the local index with: docmancer memory clear")


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
        click.echo(f"  {display_path(p)}")
    if dry_run:
        click.echo("Dry run; no changes made.")
        return
    if not assume_yes:
        click.confirm("Remove the memory index?", abort=True)
    removed = agent.clear()
    click.echo(f"Removed {len(removed)} file(s).")


__all__ = ["memory_group"]
