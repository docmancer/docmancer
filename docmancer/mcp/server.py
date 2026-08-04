"""FastMCP stdio server exposing docmancer's local memory and docs.

The ``mcp`` SDK is a core dependency, but it is still imported lazily inside
:func:`build_server`/:func:`main` so the package import stays light. The guard
below therefore signals a damaged environment rather than a missing extra.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import Field

from . import tools
from . import tree_tools

_MISSING_MCP = (
    "the MCP SDK is missing from this environment; docmancer depends on it, so "
    "reinstall with `pip install --force-reinstall docmancer` (or `pipx reinstall docmancer`)."
)
_NO_RECURSE_MESSAGE = "docmancer MCP server is disabled inside docmancer subprocesses."

# FastMCP builds its input schema from annotations, not function docstrings.
# Keep reusable parameter semantics here so MCP clients receive the same
# descriptions for each occurrence, and schema quality cannot silently regress.
MemoryQuery = Annotated[
    str,
    Field(description="Natural-language terms to search for in the local memory or documentation index."),
]
OptionalMemoryQuery = Annotated[
    str | None,
    Field(description="Natural-language terms to search for. Required unless the text alias is supplied."),
]
ResultLimit = Annotated[int, Field(description="Maximum number of matching results to return. Defaults are tool-specific.")]
IncludeHistory = Annotated[bool, Field(description="When true, include historical or superseded memory evidence in addition to active evidence.")]
ExpandRelations = Annotated[bool, Field(description="When true, include related memory items alongside direct matches.")]
RelativePath = Annotated[str | None, Field(description="Relative path for the memory file inside its selected memory tree. Required unless path is supplied.")]
RequiredRelativePath = Annotated[str, Field(description="Relative path for the new memory file inside its selected memory tree.")]
MemoryText = Annotated[
    str | None,
    Field(description="Markdown body to write or replace. Required unless content is supplied."),
]
CanonicalPinText = Annotated[
    str | None,
    Field(description="Complete durable line to add to the selected canonical section's pinned zone."),
]
CanonicalUnpinText = Annotated[
    str | None,
    Field(description="Case-insensitive substring identifying pinned lines to remove from the selected section."),
]
MemoryType = Annotated[str, Field(description="Memory classification stored in frontmatter. Defaults to fact.")]
MemoryScope = Annotated[str, Field(description="Memory visibility scope. Use global for shared memory or project for project-scoped memory.")]
Authority = Annotated[str, Field(description="Authority level stored in frontmatter. Defaults to advisory.")]
ProjectId = Annotated[str | None, Field(description="Optional project identifier stored in the memory file frontmatter.")]
ProjectPath = Annotated[str | None, Field(description="Optional project root that scopes the operation. Omit it when the server was started with a project pin.")]
Sources = Annotated[list[str] | None, Field(description="Optional source references that support the memory content.")]
Tags = Annotated[list[str] | None, Field(description="Optional labels used to classify and retrieve the memory content.")]
MemoryStatus = Annotated[str, Field(description="Lifecycle status stored in frontmatter. Defaults to active.")]
CurationOrigin = Annotated[str, Field(description="Origin label stored in frontmatter. Defaults to deliberate_write.")]
Expect = Annotated[str | None, Field(description="Create/update guard. Use absent for create-only, or pass the current content hash for a guarded update.")]
Address = Annotated[str | None, Field(description="Stable docmancer://memory address, relative path, or exact title of the memory file. Required unless an address alias is supplied.")]
RequiredAddress = Annotated[str, Field(description="Stable docmancer://memory address, relative path, or exact title of the memory file.")]
AddressAlias = Annotated[str | None, Field(description="Alias for address. Use the canonical address field when possible.")]
MemoryIdAlias = Annotated[str | None, Field(description="Alias for address that accepts a stable memory identifier. Use address when possible.")]
ExpectedHash = Annotated[str | None, Field(description="Current content_hash returned by a prior read. Required for guarded edits, moves, and deletes unless hash is supplied.")]
RequiredExpectedHash = Annotated[str, Field(description="Current content_hash returned by a prior read. This prevents overwriting a newer revision.")]
HashAlias = Annotated[str | None, Field(description="Alias for expected_hash. Use expected_hash when possible.")]
PathAlias = Annotated[str | None, Field(description="Alias for relative_path. Use relative_path when possible.")]
ContentAlias = Annotated[str | None, Field(description="Alias for text. Use text when possible.")]
SearchTextAlias = Annotated[str | None, Field(description="Alias for query. Use query when possible.")]
NewPathAlias = Annotated[str | None, Field(description="Alias for new_relative_path. Use new_relative_path when possible.")]
CanonicalSection = Annotated[str | None, Field(description="Canonical section name: about, preferences, working-principles, or active-projects. Omit only where the tool documents a status response.")]
RestoreToken = Annotated[str, Field(description="Restore token returned by trash_memory for the file to restore.")]
AgentName = Annotated[str, Field(description="Target agent identifier used when building a context projection or recording an ask. Defaults are tool-specific.")]
TokenBudget = Annotated[int | None, Field(description="Maximum token budget for the returned context bundle. Omit to use the tool default.")]
TokenBudgetAlias = Annotated[
    int | None,
    Field(description="Alias for token_budget. Use token_budget when possible."),
]
RequiredTokenBudget = Annotated[int, Field(description="Maximum token budget for the returned context projection.")]
TimelineFileId = Annotated[str | None, Field(description="Optional stable memory file identifier used to filter the timeline.")]
TimelineOperation = Annotated[str | None, Field(description="Optional operation name used to filter the timeline, such as create, edit, move, trash, or restore.")]
Answer = Annotated[bool, Field(description="When true, use the configured provider to generate a grounded cited answer from recalled memory.")]
AskMode = Annotated[str, Field(description="Recall mode. Defaults to normal.")]
MemoryTask = Annotated[
    str | None,
    Field(description="Natural-language task to recall relevant policy, memory, and evidence for. Required unless query is supplied."),
]
TaskQueryAlias = Annotated[
    str | None,
    Field(description="Alias for task. Use task when possible."),
]


def _argument_error(message: str, next_action: str) -> dict:
    return {
        "error": message,
        "error_type": "InvalidArgumentsError",
        "likely_cause": "The request used a missing, conflicting, or unsupported argument shape.",
        "retry_safe": True,
        "next_action": next_action,
    }


def _pick_argument(name: str, *values, required: bool = True):
    """Normalise a canonical MCP argument and its documented aliases.

    Multiple spellings are accepted only when they carry the same value. This
    helps a model recover from a plausible naming mistake without allowing an
    alias to override a validated canonical value.
    """
    supplied = [value for value in values if value is not None]
    if not supplied:
        if required:
            return None, _argument_error(
                f"missing required argument {name!r}",
                f"Retry with the canonical `{name}` argument.",
            )
        return None, None
    if any(value != supplied[0] for value in supplied[1:]):
        return None, _argument_error(
            f"conflicting values were supplied for {name!r} and one of its aliases",
            f"Retry with only the canonical `{name}` argument.",
        )
    return supplied[0], None


def build_server(project_path: str | Path | None = None):
    """Construct a FastMCP server, optionally pinned to one project root."""
    if os.environ.get("DOCMANCER_NO_RECURSE") == "1":
        raise RuntimeError(_NO_RECURSE_MESSAGE)

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:  # pragma: no cover - exercised via doctor/serve hint
        raise ImportError(_MISSING_MCP) from exc

    server = FastMCP("docmancer")
    pinned_project = Path(project_path).expanduser().resolve() if project_path is not None else None

    def tree_project(requested: str | None):
        if pinned_project is None:
            return requested, None
        if requested is not None and Path(requested).expanduser().resolve() != pinned_project:
            return None, _argument_error(
                "project_path cannot override this MCP server's startup pin",
                "Retry without project_path. The server is already pinned to its configured project.",
            )
        return str(pinned_project), None

    @server.tool(description="Search the local docmancer memory index (agent memory, instructions, rules). Local only.")
    def docmancer_memory_search(
        query: MemoryQuery,
        limit: ResultLimit = 8,
        include_history: IncludeHistory = False,
        expand_relations: ExpandRelations = False,
    ) -> list[dict]:
        return tools.memory_search(
            query,
            limit=limit,
            include_history=include_history,
            expand_relations=expand_relations,
        )

    @server.tool(description="Search the local docmancer docs index. Local only.")
    def docmancer_docs_search(query: MemoryQuery, limit: ResultLimit = 8) -> list[dict]:
        return tools.docs_search(query, limit=limit)

    @server.tool(description="Report docmancer memory index status (path, source/section counts). Local only.")
    def docmancer_memory_status() -> dict:
        return tools.memory_status()

    # The public MCP surface mirrors the compact CLI. Atom-management,
    # conflict-resolution, consolidation, and Cloud mutation tools were removed
    # with their deprecated CLI counterparts.

    @server.tool(
        description=(
            "MUTATING: create or update one curated tree-memory file (docmancer://memory/<id>). "
            "expect='absent' (default) is create-only; pass the current content_hash for a guarded "
            "update. Returns the stable address, content_hash, and revision id for follow-up calls. "
            "Example: relative_path='deployment/release.md', text='# Release\\n\\nUse Railway.' "
            "Aliases: path for relative_path, content for text."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def write_memory(
        relative_path: RelativePath = None,
        text: MemoryText = None,
        memory_type: MemoryType = "fact",
        scope: MemoryScope = "global",
        authority: Authority = "advisory",
        project_id: ProjectId = None,
        project_path: ProjectPath = None,
        sources: Sources = None,
        tags: Tags = None,
        status: MemoryStatus = "active",
        curation_origin: CurationOrigin = "deliberate_write",
        expect: Expect = "absent",
        path: PathAlias = None,
        content: ContentAlias = None,
    ) -> dict:
        relative_path, error = _pick_argument("relative_path", relative_path, path)
        if error:
            return error
        text, error = _pick_argument("text", text, content)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.write_memory(
            relative_path,
            text,
            memory_type=memory_type,
            scope=scope,
            authority=authority,
            project_id=project_id,
            project_path=project_path,
            sources=sources,
            tags=tags,
            status=status,
            curation_origin=curation_origin,
            expect=expect,
        )

    @server.tool(
        description=(
            "READ-ONLY: read one tree-memory file by stable address, relative path, or exact title. "
            "Ambiguous title/path matches return every candidate address instead of guessing. "
            "Example: address='docmancer://memory/01J...'. Aliases: target or memory_id for address."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def read_memory(
        address: Address = None,
        project_path: ProjectPath = None,
        target: AddressAlias = None,
        memory_id: MemoryIdAlias = None,
    ) -> dict:
        address, error = _pick_argument("address", address, target, memory_id)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.read_memory(address, project_path=project_path)

    @server.tool(
        description=(
            "MUTATING: replace the body of one tree-memory file, preserving its other frontmatter. "
            "Requires the file's current content_hash in expected_hash; a stale hash fails safely "
            "with a structured error naming the safe re-read-and-retry next action. "
            "Aliases: target for address, content for text, hash for expected_hash."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def edit_memory(
        address: Address = None,
        text: MemoryText = None,
        expected_hash: ExpectedHash = None,
        project_path: ProjectPath = None,
        target: AddressAlias = None,
        content: ContentAlias = None,
        hash: HashAlias = None,
    ) -> dict:
        address, error = _pick_argument("address", address, target)
        if error:
            return error
        text, error = _pick_argument("text", text, content)
        if error:
            return error
        expected_hash, error = _pick_argument("expected_hash", expected_hash, hash)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.edit_memory(address, text, expected_hash=expected_hash, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: read the machine-wide canonical memory, which is what docmancer has "
            "reconciled about this user across every agent and project (about, preferences, "
            "working-principles, active-projects). Omit section for the status of all sections; "
            "pass section for that section split into its pinned and generated zones. "
            "Call this to find out what is already known about the user before asking them."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def canonical_memory(section: CanonicalSection = None) -> dict:
        return tree_tools.canonical_memory(section=section)

    @server.tool(
        description=(
            "MUTATING: pin one durable line into a canonical memory section (about, preferences, "
            "working-principles, active-projects). The pinned zone is the ONLY part of a canonical "
            "section that survives automatic reconciliation, so use this (not edit_memory) for any "
            "correction, standing preference, or fact the reconciler got wrong or left out. "
            "Idempotent: pinning the same line twice changes nothing."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def pin_memory(section: CanonicalSection = None, text: CanonicalPinText = None) -> dict:
        section, error = _pick_argument("section", section, None)
        if error:
            return error
        text, error = _pick_argument("text", text, None)
        if error:
            return error
        return tree_tools.pin_memory(section, text)

    @server.tool(
        description=(
            "MUTATING: remove pinned lines from a canonical memory section by case-insensitive "
            "substring match. Fails without changing anything when nothing matches."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    )
    def unpin_memory(section: CanonicalSection = None, text: CanonicalUnpinText = None) -> dict:
        section, error = _pick_argument("section", section, None)
        if error:
            return error
        text, error = _pick_argument("text", text, None)
        if error:
            return error
        return tree_tools.unpin_memory(section, text)

    @server.tool(
        description=(
            "MUTATING, DESTRUCTIVE at the old path: move or rename one tree-memory file. Its stable "
            "address survives the move, but the old path stops resolving. Requires the file's current "
            "content_hash in expected_hash. Aliases: target for address, new_path for "
            "new_relative_path, hash for expected_hash."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    )
    def move_memory(
        address: Address = None,
        new_relative_path: RelativePath = None,
        expected_hash: ExpectedHash = None,
        project_path: ProjectPath = None,
        target: AddressAlias = None,
        new_path: NewPathAlias = None,
        hash: HashAlias = None,
    ) -> dict:
        address, error = _pick_argument("address", address, target)
        if error:
            return error
        new_relative_path, error = _pick_argument("new_relative_path", new_relative_path, new_path)
        if error:
            return error
        expected_hash, error = _pick_argument("expected_hash", expected_hash, hash)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.move_memory(
            address, new_relative_path, expected_hash=expected_hash, project_path=project_path
        )

    @server.tool(
        description="MUTATING: duplicate one tree-memory file under a new stable identity and relative path.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def duplicate_memory(
        address: RequiredAddress,
        new_relative_path: RequiredRelativePath,
        expected_hash: RequiredExpectedHash,
        project_path: ProjectPath = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.duplicate_memory(
            address, new_relative_path, expected_hash=expected_hash, project_path=project_path
        )

    @server.tool(
        description="DESTRUCTIVE BUT REVERSIBLE: move one tree-memory file to trash and return a restore token.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    )
    def trash_memory(
        address: RequiredAddress,
        expected_hash: RequiredExpectedHash,
        project_path: ProjectPath = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.trash_memory(address, expected_hash=expected_hash, project_path=project_path)

    @server.tool(
        description="MUTATING: restore one tree-memory file from a prior trash restore token.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def restore_memory(restore_token: RestoreToken, project_path: ProjectPath = None) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.restore_memory(restore_token, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: lexical search over one tree's active memory. Returns [] (not an error) when "
            "nothing is relevant or the tree is empty. Example: query='prior deployment decision'. "
            "Alias: text for query."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def search_memory(
        query: OptionalMemoryQuery = None,
        limit: ResultLimit = 8,
        project_path: ProjectPath = None,
        text: SearchTextAlias = None,
    ) -> list[dict] | dict:
        query, error = _pick_argument("query", query, text)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.search_memory(query, limit=limit, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: show memories recurring across two or more independent agent harnesses. "
            "Generated Docmancer integration copies are excluded. Results are recurrence evidence, "
            "not consensus or truth."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def common_memory(project_path: ProjectPath = None) -> list[dict] | dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.common_memory(project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: show each supported agent's integration mode, hook status, and latest "
            "observed context bundle revision and hash."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def context_delivery(project_path: ProjectPath = None) -> list[dict] | dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.context_delivery(project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: inspect the current consolidated Context revision, freshness, exclusions, "
            "and cluster metadata. Context refresh, rollback, adopt, and retire are intentionally "
            "human-only CLI or local-web operations."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def context_status(project_path: ProjectPath = None) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.context_status(project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: render a bounded revision-linked Context projection for an agent without "
            "writing or refreshing it. Context refresh, rollback, adopt, and retire are human-only."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def context_projection(
        agent: AgentName,
        project_path: ProjectPath = None,
        token_budget: RequiredTokenBudget = 2_000,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.context_projection(
            agent=agent,
            project_path=project_path,
            token_budget=token_budget,
        )

    @server.tool(
        description=(
            "READ-ONLY: show the append-only timeline of canonical memory file creates, edits, "
            "moves, duplicates, trash operations, and restores, including human-readable diffs."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def decision_timeline(
        project_path: ProjectPath = None,
        file_id: TimelineFileId = None,
        operation: TimelineOperation = None,
        limit: ResultLimit = 100,
    ) -> list[dict] | dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.decision_timeline(
            project_path=project_path,
            file_id=file_id,
            operation=operation,
            limit=limit,
        )

    def _ask_memory_impl(
        task: str | None,
        project_path: str | None,
        token_budget: int | None,
        include_history: bool,
        limit: int,
        query: str | None,
        budget: int | None,
        agent: str,
        answer: bool,
        mode: str,
    ) -> dict:
        task, error = _pick_argument("task", task, query)
        if error:
            return error
        token_budget, error = _pick_argument("token_budget", token_budget, budget, required=False)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.ask_memory(
            task,
            project_path=project_path,
            token_budget=token_budget or 4000,
            limit=limit,
            include_history=include_history,
            agent=agent,
            answer=answer,
            mode=mode,
        )

    @server.tool(
        name="ask_memory",
        description=(
            "READ-ONLY: recall one bounded bundle of mandatory policy, curated memory, and supporting "
            "indexed agent evidence for a task. Returns an empty bundle when no relevant local memory "
            "exists. Set answer=true to use the configured provider for a grounded cited answer. "
            "Answer generation defaults to false. Aliases: query for task, budget for token_budget."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def ask_memory_tool(
        task: MemoryTask = None,
        project_path: ProjectPath = None,
        token_budget: TokenBudget = None,
        include_history: IncludeHistory = False,
        limit: ResultLimit = 12,
        query: TaskQueryAlias = None,
        budget: TokenBudgetAlias = None,
        agent: AgentName = "mcp-client",
        answer: Answer = False,
        mode: AskMode = "normal",
    ) -> dict:
        return _ask_memory_impl(
            task,
            project_path,
            token_budget,
            include_history,
            limit,
            query,
            budget,
            agent,
            answer,
            mode,
        )

    return server


def main(project_path: str | Path | None = None) -> None:
    """Console-script entrypoint: run the stdio MCP server."""
    try:
        server = build_server(project_path=project_path)
    except (ImportError, RuntimeError) as exc:
        import sys

        print(str(exc), file=sys.stderr)
        sys.exit(1)
    server.run()


if __name__ == "__main__":
    main()
