"""``docmancer memory`` command group.

Scan, sync, query, inspect, and clear the local memory index built from the
memory and instruction files your coding agents already wrote on this machine.
Sync and recall do not upload anything; the index is stored in local
SQLite-backed files.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path
from time import monotonic

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
    AGENTS.md / GEMINI.md), and project rule directories. `scan` and `sync`
    report the split by kind; `sources` shows exact provenance per file. Preview
    before writing with `sync --dry-run`; secrets are redacted on index, and
    local sync/query commands do not upload anything.
    """
    if os.environ.get("DOCMANCER_NO_RECURSE") == "1":
        click.echo("docmancer memory commands are disabled inside docmancer agent-provider subprocesses.", err=True)
        sys.exit(2)


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


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="List indexed sources with provenance.")
@click.option("--agent", "agent_filter", default=None, help="Filter by agent/harness name.")
@click.option("--scope", "scope_filter", type=click.Choice(["global", "project"], case_sensitive=False), default=None, help="Filter by scope.")
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
    """Show every indexed source: agent, type, scope, title, path, char count."""
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
        click.echo(_json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No indexed sources match. Run: docmancer memory sync")
        return

    home = str(Path.home())

    def _short(path: str) -> str:
        return path.replace(home, "~") if path.startswith(home) else path

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
            short_path = _short(r["path"])
            chars = f"{r['chars']:,}"
            # Fit type label in 13 chars, path fills the middle, chars right-padded
            click.echo(f"    {kind:<13}  {short_path:<60}  {chars} chars")
        click.echo()


_PROVIDER_NOTICE = (
    "Note: this sends your selected local memory text to {provider}. "
    "Secrets are redacted first; nothing is stored remotely by docmancer."
)
_PROVIDER_CHOICES = [
    "agent",
    "claude",
    "codex",
    "gemini",
    "opencode",
    "cline",
    "github-copilot",
    "cursor",
    "openrouter",
]
_DEFAULT_CLOUD_INPUT_BUDGET = 90_000
_DEFAULT_CONSOLIDATE_INPUT_BUDGET = 50_000
_FAST_CONSOLIDATE_INPUT_BUDGET = 35_000
_OPENROUTER_CONSOLIDATE_INPUT_BUDGET = 25_000
_OPENROUTER_FAST_CONSOLIDATE_INPUT_BUDGET = 18_000
_DEFAULT_CONSOLIDATE_MAX_OUTPUT_TOKENS = 4096
_FAST_CONSOLIDATE_MAX_OUTPUT_TOKENS = 2048
_OPENROUTER_CONSOLIDATE_MAX_OUTPUT_TOKENS = 8192
_OPENROUTER_FAST_CONSOLIDATE_MAX_OUTPUT_TOKENS = 4096
_APPROX_CHARS_PER_TOKEN = 4


def _provider_disclosure(provider: str, client=None) -> str:
    label = getattr(client, "provider_name", None) or provider
    if provider == "openrouter":
        return "OpenRouter (cloud)"
    if provider == "agent":
        return f"{label} through your installed coding-agent CLI"
    return f"{label} through your installed coding-agent CLI"


def _is_agent_provider(provider: str) -> bool:
    return provider != "openrouter"


def _openrouter_fallback_model(model: str | None) -> str | None:
    if model and "/" in model:
        return model
    return None


def _expected_provider_errors():
    from docmancer.ai.agent_cli_client import AgentCliError
    from docmancer.ai.openrouter_client import OpenRouterConfigError

    return (AgentCliError, OpenRouterConfigError)


def _make_provider_client(provider: str, *, model: str | None, timeout: float | None):
    if provider == "openrouter":
        from docmancer.ai.openrouter_client import OpenRouterClient

        return OpenRouterClient(model=model, timeout_seconds=timeout)

    from docmancer.ai.agent_cli_client import AgentCliClient

    return AgentCliClient(agent=provider, model=model, timeout_seconds=timeout)


def _make_openrouter_fallback_client(*, model: str | None, timeout: float | None):
    from docmancer.ai.openrouter_client import OpenRouterClient

    return OpenRouterClient(model=_openrouter_fallback_model(model), timeout_seconds=timeout)


def _make_provider_client_with_setup_fallback_or_exit(
    command: str,
    provider: str,
    *,
    model: str | None,
    timeout: float | None,
):
    try:
        return _make_provider_client(provider, model=model, timeout=timeout), provider
    except _expected_provider_errors() as exc:
        if not _is_agent_provider(provider):
            click.echo(str(exc), err=True)
            sys.exit(2)
        try:
            fallback = _make_openrouter_fallback_client(model=model, timeout=timeout)
        except _expected_provider_errors() as fallback_exc:
            click.echo(f"Agent provider setup failed: {exc}", err=True)
            click.echo(f"OpenRouter fallback unavailable: {fallback_exc}", err=True)
            sys.exit(2)
        except Exception as fallback_exc:  # noqa: BLE001 - fallback setup should not traceback
            click.echo(f"Agent provider setup failed: {exc}", err=True)
            click.echo(f"OpenRouter fallback setup failed: {fallback_exc}", err=True)
            sys.exit(1)
        click.echo(f"Agent provider setup failed: {exc}", err=True)
        click.echo("Retrying with OpenRouter fallback.", err=True)
        return fallback, "openrouter"
    except Exception as exc:  # noqa: BLE001 - provider setup should not traceback
        if not _is_agent_provider(provider):
            click.echo(f"docmancer memory {command} provider setup failed: {exc}", err=True)
            sys.exit(1)
        try:
            fallback = _make_openrouter_fallback_client(model=model, timeout=timeout)
        except _expected_provider_errors() as fallback_exc:
            click.echo(f"Agent provider setup failed: {exc}", err=True)
            click.echo(f"OpenRouter fallback unavailable: {fallback_exc}", err=True)
            sys.exit(2)
        except Exception as fallback_exc:  # noqa: BLE001 - fallback setup should not traceback
            click.echo(f"Agent provider setup failed: {exc}", err=True)
            click.echo(f"OpenRouter fallback setup failed: {fallback_exc}", err=True)
            sys.exit(1)
        click.echo(f"Agent provider setup failed: {exc}", err=True)
        click.echo("Retrying with OpenRouter fallback.", err=True)
        return fallback, "openrouter"


def _run_provider_with_openrouter_fallback_or_exit(
    command: str,
    provider: str,
    client,
    *,
    model: str | None,
    timeout: float | None,
    fn,
):
    """Run an agent provider call, falling back to OpenRouter on agent failure."""
    try:
        return fn(client, model)
    except _expected_provider_errors() as exc:
        if not _is_agent_provider(provider):
            click.echo(str(exc), err=True)
            sys.exit(2)
        primary_error = str(exc)
    except Exception as exc:  # noqa: BLE001 - provider/runtime errors must not traceback
        if not _is_agent_provider(provider):
            provider_label = getattr(client, "provider_name", None) or "provider"
            click.echo(f"docmancer memory {command} failed calling {provider_label}: {exc}", err=True)
            sys.exit(1)
        primary_error = f"{type(exc).__name__}: {exc}"

    try:
        fallback = _make_openrouter_fallback_client(model=model, timeout=timeout)
    except _expected_provider_errors() as fallback_exc:
        click.echo(f"Agent provider failed: {primary_error}", err=True)
        click.echo(f"OpenRouter fallback unavailable: {fallback_exc}", err=True)
        sys.exit(2)
    except Exception as fallback_exc:  # noqa: BLE001 - fallback setup should not traceback
        click.echo(f"Agent provider failed: {primary_error}", err=True)
        click.echo(f"OpenRouter fallback setup failed: {fallback_exc}", err=True)
        sys.exit(1)

    fallback_model = _openrouter_fallback_model(model)
    click.echo(f"Agent provider failed: {primary_error}", err=True)
    click.echo("Retrying with OpenRouter fallback.", err=True)
    try:
        return fn(fallback, fallback_model)
    except _expected_provider_errors() as fallback_exc:
        click.echo(f"OpenRouter fallback failed: {fallback_exc}", err=True)
        sys.exit(2)
    except Exception as fallback_exc:  # noqa: BLE001 - fallback runtime should not traceback
        click.echo(f"docmancer memory {command} OpenRouter fallback failed: {fallback_exc}", err=True)
        sys.exit(1)


def _redacted_entries(agent, *, query: str | None, limit: int | None):
    """Return privacy-redacted entries (optionally narrowed by a query)."""
    entries = [agent.privacy.clean(e) for e in agent.preview()]
    if query:
        try:
            chunks = agent.query(query, limit=limit or 20)
            wanted = {
                (c.metadata or {}).get("source_path")
                for c in chunks
                if (c.metadata or {}).get("source_path")
            }
            narrowed = [e for e in entries if e.path in wanted]
            if narrowed:
                entries = narrowed
        except Exception:  # noqa: BLE001 - retrieval is best-effort; fall back to all
            pass
    if limit:
        entries = entries[:limit]
    return entries


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


def _chunk_status(command: str, chunks: list[list[dict]], stats: dict, *, provider_label: str = "provider") -> None:
    if len(chunks) <= 1 and not stats["split_entries"]:
        return
    click.echo(
        f"docmancer memory {command}: sending {stats['expanded_entries']} payload part(s) "
        f"in {len(chunks)} {provider_label} request(s), then merging results as needed.",
        err=True,
    )
    if stats["split_entries"]:
        click.echo(
            f"Split {stats['split_entries']} oversized source entr(y/ies) into ordered parts; no selected text was trimmed.",
            err=True,
        )


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
) -> None:
    merge_step = "yes" if len(chunks) > 1 else "no"
    rows: list[tuple[str, object | None]] = [
        ("payload parts", stats["expanded_entries"]),
        ("provider requests", f"{len(chunks)} {provider_label} request(s)"),
        ("estimated input", _fmt_count(stats.get("original_tokens"), "tokens")),
        ("batch budget", "single request" if budget is None or budget <= 0 else _fmt_count(budget, "tokens")),
        ("output cap", "provider default" if max_output_tokens is None else _fmt_count(max_output_tokens, "tokens")),
        ("draft quality", draft_quality),
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
):
    """Map-reduce memory consolidation while preserving every selected entry."""
    from docmancer.ai.memory_features import consolidate_memory, draft_to_markdown

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

        drafts = []
        for i, chunk in enumerate(chunks, start=1):
            token_count = stats["request_tokens"][i - 1]
            batch_instruction = (
                f"{current_instruction or 'Consolidate these into a coherent master memory draft.'}\n\n"
                f"This is batch {i} of {len(chunks)} in consolidation round {round_no}. "
                "Preserve durable facts, conflicts, warnings, and source paths. "
                "Do not assume other batches contain the same information."
            )
            _provider_request_status(f"memory consolidation batch {i}/{len(chunks)}", client, token_count=token_count)
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
            markdown = draft_to_markdown(draft, source_files=source_files)
            click.echo(f"  status   completed", err=True)
            click.echo(f"  output   {len(markdown):,} chars", err=True)
            click.echo(f"  duration {_fmt_seconds(monotonic() - started)}", err=True)
            drafts.append(
                {
                    "scope": "docmancer-consolidation",
                    "title": f"Round {round_no} batch {i} consolidated draft",
                    "source_path": f"docmancer://memory-consolidate/round-{round_no}/batch-{i}",
                    "text": markdown,
                }
            )

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


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Extract durable memory facts with an agent CLI.")
@click.option("--limit", default=50, type=int, show_default=True, help="Max entries to feed the extractor.")
@click.option("--budget", default=_DEFAULT_CLOUD_INPUT_BUDGET, type=int, show_default=True, help="Approximate input-token budget per provider request; use 0 to send in one request.")
@click.option("--query", "query", default=None, help="Only extract from memory relevant to this query.")
@click.option("output_format", "--format", type=click.Choice(["json"], case_sensitive=False), default="json", show_default=True)
@click.option("--provider", type=click.Choice(_PROVIDER_CHOICES, case_sensitive=False), default="agent", show_default=True, help="Provider for extraction.")
@click.option("--model", default=None, help="Override the provider model. For OpenRouter, pass any OpenRouter model id, for example openai/gpt-4.1-nano.")
@click.option("--timeout", "timeout", default=None, type=float, help="Seconds per provider request (default 180, or provider timeout env var; use 0 for provider default).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the provider-use confirmation.")
@click.option("--include", "include", multiple=True, help="Only include entries whose path/scope match this glob.")
@click.option("--exclude", "exclude", multiple=True, help="Exclude entries whose path/scope match this glob.")
def extract(limit, budget, query, output_format, provider, model, timeout, assume_yes, include, exclude):
    """Extract durable memory facts. Uses an installed agent CLI by default."""
    import json as _json

    provider = provider.lower()
    agent = _agent(include, exclude)
    entries = _redacted_entries(agent, query=query, limit=limit)
    if not entries:
        click.echo("No memory entries to extract from. Run: docmancer memory sync")
        sys.exit(1)
    client, active_provider = _make_provider_client_with_setup_fallback_or_exit(
        "extract", provider, model=model, timeout=timeout
    )
    provider_label = getattr(client, "provider_name", None) or provider
    click.echo(_PROVIDER_NOTICE.format(provider=_provider_disclosure(active_provider, client)), err=True)
    if _is_agent_provider(provider):
        click.echo("If the agent provider fails, docmancer will retry with OpenRouter when configured.", err=True)
    if not assume_yes:
        target = provider_label
        if _is_agent_provider(provider) and active_provider != "openrouter":
            target = f"{provider_label}, or OpenRouter fallback if the agent provider fails"
        click.confirm(f"Send the selected memory to {target}?", abort=True, err=True)

    from docmancer.ai.memory_features import extract_memory_facts
    from docmancer.ai.memory_schemas import ExtractedMemoryFacts

    payload = _entries_to_payload(entries)
    chunks, stats = _chunk_payload_entries(payload, budget=budget)
    _chunk_status("extract", chunks, stats, provider_label=provider_label)

    def _combined(chunk: list[dict]) -> str:
        return "\n\n".join(
            f"### {e.get('title', '')} ({e.get('scope', '')})\n"
            f"source: {e.get('source_path', '')}\n\n{e.get('text', '')}"
            for e in chunk
        )

    def _call(active_client, active_model):
        _provider_preflight(active_client, model=active_model)
        all_facts = []
        for i, chunk in enumerate(chunks, start=1):
            metadata = {"entries": len(chunk)}
            if len(chunks) > 1:
                metadata["batch"] = f"{i}/{len(chunks)}"
                click.echo(
                    f"Extracting memory batch {i}/{len(chunks)} "
                    f"(~{stats['request_tokens'][i - 1]} tokens).",
                    err=True,
                )
            token_count = stats["request_tokens"][i - 1] if stats.get("request_tokens") else None
            _provider_request_status(f"memory extraction batch {i}/{len(chunks)}", active_client, token_count=token_count)
            on_progress, finish = _streaming_progress(f"memory extraction batch {i}/{len(chunks)}")
            try:
                result = extract_memory_facts(
                    _combined(chunk), metadata, client=active_client, model=active_model, on_progress=on_progress
                )
            finally:
                finish()
            active_label = getattr(active_client, "provider_name", None) or provider_label
            click.echo(f"{active_label} completed extraction batch {i}/{len(chunks)}.", err=True)
            all_facts.extend(result.facts)
        return ExtractedMemoryFacts(facts=all_facts)

    result = _run_provider_with_openrouter_fallback_or_exit(
        "extract", active_provider, client, model=model, timeout=timeout, fn=_call
    )
    click.echo(_json.dumps(result.model_dump(), indent=2))


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
@click.option("--provider", type=click.Choice(_PROVIDER_CHOICES, case_sensitive=False), default="agent", show_default=True, help="Provider for consolidation.")
@click.option("--model", default=None, help="Override the provider model. For OpenRouter, pass any OpenRouter model id, for example openai/gpt-4.1-nano.")
@click.option("--draft-quality", type=click.Choice(["standard", "fast"], case_sensitive=False), default="standard", show_default=True, help="Use fast for smaller batches and more aggressive compression.")
@click.option("--max-output-tokens", default=None, type=int, help="Hard cap for generated output per provider request. Defaults are provider-specific; use 0 for provider default.")
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
    entries = _redacted_entries(agent, query=query, limit=limit)
    if not entries:
        click.echo("No memory entries to consolidate. Run: docmancer memory sync")
        sys.exit(1)
    client, active_provider = _make_provider_client_with_setup_fallback_or_exit(
        "consolidate", provider, model=model, timeout=timeout
    )
    provider_label = getattr(client, "provider_name", None) or provider
    click.echo(_PROVIDER_NOTICE.format(provider=_provider_disclosure(active_provider, client)), err=True)
    if _is_agent_provider(provider):
        click.echo("If the agent provider fails, docmancer will retry with OpenRouter when configured.", err=True)
    if not assume_yes:
        target = provider_label
        if _is_agent_provider(provider) and active_provider != "openrouter":
            target = f"{provider_label}, or OpenRouter fallback if the agent provider fails"
        click.confirm(f"Send the selected memory to {target}?", abort=True, err=True)

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
        _provider_preflight(active_client, model=active_model)
        return _consolidate_payload_in_rounds(
            payload,
            instruction=query,
            client=active_client,
            model=active_model,
            budget=resolved_budget,
            draft_quality=draft_quality,
            max_output_tokens=resolved_max_output_tokens,
        )

    # The draft is only written after a successful call, so any failure leaves
    # no partial output behind.
    draft = _run_provider_with_openrouter_fallback_or_exit(
        "consolidate", active_provider, client, model=model, timeout=timeout, fn=_call
    )

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
                ("path", result.root),
                ("format", "okf"),
                ("sources", len(entries)),
                ("next", f"docmancer okf doctor {result.root}"),
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
            ("path", out_path),
            ("format", "markdown"),
            ("sources", len(entries)),
            ("size", f"{len(markdown):,} chars"),
            ("next", f"docmancer memory apply --from {out_path} --agent codex"),
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


def _apply_target_path(agent: str | None, output: str | None):
    from docmancer.harness.base import default_home

    if output:
        return Path(output)
    if agent and agent in _APPLY_TARGETS:
        sub, name = _APPLY_TARGETS[agent]
        return default_home() / sub / name
    return None


@memory_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Materialize a reviewed draft into an agent's file.")
@click.option("--from", "from_path", default=None, help=f"The reviewed draft markdown to apply (defaults to {_DEFAULT_DRAFT}).")
@click.option("--agent", type=click.Choice(sorted(_APPLY_TARGETS), case_sensitive=False), default=None, help="Target agent whose always-loaded file to write.")
@click.option("--output", "output", default=None, help="Write to an arbitrary file instead of an agent target.")
@click.option("--dry-run", is_flag=True, help="Show the diff; write nothing.")
@click.option("--print", "print_only", is_flag=True, help="Print the resolved target and block; write nothing.")
@click.option("--remove", "remove", is_flag=True, help="Strip docmancer's managed block (clean uninstall).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
def apply(from_path, agent, output, dry_run, print_only, remove, assume_yes):
    """Write a reviewed consolidated draft into an agent's always-loaded file.

    Local and keyless. Writes only inside a delimited managed block, after a
    timestamped backup. This is the only command that writes consolidated memory
    into agent-owned files, and it is never automatic. (`docmancer install` may
    also inject a short recall instruction into the same files.) Review the draft
    first; with no `--from`, it applies the default `master-memory-draft.md`
    written by `docmancer memory consolidate`.
    """
    from docmancer.cli.managed_block import diff_block, remove_block, upsert_block

    target = _apply_target_path(agent, output)
    if target is None:
        choices = "|".join(sorted(_APPLY_TARGETS))
        click.echo(f"Specify a target: --agent {{{choices}}} or --output <path>.", err=True)
        sys.exit(2)

    if remove:
        if not target.exists():
            click.echo(f"Nothing to remove; {target} does not exist.")
            return
        if print_only or dry_run:
            click.echo(f"Would remove docmancer managed block from {target}.")
            return
        if not assume_yes:
            click.confirm(f"Remove docmancer's managed block from {target}?", abort=True)
        removed, backup = remove_block(target, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END)
        if removed:
            click.echo(f"Removed managed block from {target}." + (f" Backup: {backup}" if backup else ""))
        else:
            click.echo(f"No docmancer managed block found in {target}.")
        return

    used_default = from_path is None
    src = Path(from_path or _DEFAULT_DRAFT)
    if not src.is_file() and used_default:
        # No reviewed draft at the default location: ask the user where it is
        # instead of just failing, so the flow keeps moving.
        click.echo(
            f"No draft found at {src}. Run `docmancer memory consolidate` first, "
            "or provide a reviewed draft path.",
            err=True,
        )
        try:
            answer = click.prompt("Path to draft (blank to cancel)", default="", show_default=False)
        except click.Abort:
            answer = ""
        answer = (answer or "").strip()
        if not answer:
            sys.exit(2)
        src = Path(answer).expanduser()
    if not src.is_file():
        click.echo(f"Draft not found: {src}", err=True)
        sys.exit(2)
    body = src.read_text(encoding="utf-8")

    if print_only:
        click.echo(f"Target: {target}")
        click.echo("")
        from docmancer.cli.managed_block import build_block

        click.echo(build_block(body, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END))
        return

    if dry_run:
        click.echo(f"Target: {target}")
        click.echo(diff_block(target, body, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END) or "(no changes)")
        return

    if not assume_yes:
        click.confirm(f"Write docmancer's managed block into {target}?", abort=True)

    action, backup = upsert_block(target, body, begin=_MEMORY_BLOCK_BEGIN, end=_MEMORY_BLOCK_END)
    click.echo(f"{action.capitalize()} docmancer managed block in {target}.")
    if backup:
        click.echo(f"Backup written to {backup}")
    click.echo("Undo: docmancer memory apply --remove" + (f" --agent {agent}" if agent else f" --output {target}") + f", or restore the backup.")


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
    entries = _redacted_entries(agent, query=query, limit=limit)
    if not entries:
        click.echo("No memory to export. Run: docmancer memory sync")
        sys.exit(1)

    concepts = concepts_from_memory_entries(entries)
    today = datetime.now(timezone.utc).date().isoformat()
    result = write_bundle(
        Path(output),
        concepts,
        title="docmancer cross-agent memory",
        log_entries=[f"{today}: exported {len(concepts)} concept(s) from docmancer memory"],
    )
    click.echo(f"Wrote OKF bundle to {result.root} ({result.concept_count} concept(s)).")
    click.echo(f"Validate it with: docmancer okf doctor {result.root}")


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
        click.echo(f"  {p}")
    if dry_run:
        click.echo("Dry run; no changes made.")
        return
    if not assume_yes:
        click.confirm("Remove the memory index?", abort=True)
    removed = agent.clear()
    click.echo(f"Removed {len(removed)} file(s).")


__all__ = ["memory_group"]
