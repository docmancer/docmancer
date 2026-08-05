"""FastMCP stdio server exposing docmancer's local memory and docs.

The ``mcp`` SDK is a core dependency, but it is still imported lazily inside
:func:`build_server`/:func:`main` so the package import stays light. The guard
below therefore signals a damaged environment rather than a missing extra.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

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
#
# Two rules hold across this module, because a model reads the description far
# more reliably than it reads the schema:
#
# 1. Every parameter a tool exposes is also named and explained in that tool's
#    description string. `tests/test_mcp.py` enforces this.
# 2. Genuinely required arguments are typed as required, so a missing one is a
#    protocol-level validation error rather than a tool-result payload the
#    model has to parse. No parameter has an alias spelling.
_PROJECT_PATH_HELP = (
    "Project root whose memory tree the operation applies to. Omit it to use the machine-wide "
    "tree, and always omit it when this server was started pinned to a project."
)

MemoryQuery = Annotated[
    str,
    Field(description="Natural-language terms to search for in the local memory or documentation index."),
]
ResultLimit = Annotated[int, Field(description="Maximum number of matching results to return. Defaults are tool-specific.")]
IncludeHistory = Annotated[bool, Field(description="When true, include historical or superseded memory evidence in addition to active evidence.")]
ExpandRelations = Annotated[bool, Field(description="When true, include related memory items alongside direct matches.")]
RelativePath = Annotated[str, Field(description="Relative path, including the .md suffix, for the memory file inside its selected memory tree.")]
MemoryText = Annotated[str, Field(description="Markdown body to write or replace. Replaces the body wholesale; it is not appended.")]
CanonicalPinText = Annotated[
    str,
    Field(description="Complete durable line to add to the selected canonical section's pinned zone."),
]
CanonicalUnpinText = Annotated[
    str,
    Field(description="Case-insensitive substring identifying pinned lines to remove from the selected section."),
]
MemoryType = Annotated[str, Field(description="Free-form memory classification stored in frontmatter, such as fact, decision, preference, or constraint. Defaults to fact.")]
MemoryScope = Annotated[
    Literal["global", "project"],
    Field(description="Memory visibility scope stored in frontmatter. Use global for machine-wide memory or project for project-scoped memory."),
]
Authority = Annotated[
    Literal["advisory", "mandatory"],
    Field(description="How binding the memory is. mandatory entries are always included in a recall bundle; advisory entries compete on relevance. Defaults to advisory."),
]
ProjectId = Annotated[str | None, Field(description="Project identifier stored in the memory file frontmatter. Omit unless the memory belongs to a named project.")]
ProjectPath = Annotated[str | None, Field(description=_PROJECT_PATH_HELP)]
Sources = Annotated[list[str] | None, Field(description="Source references, such as file paths or URLs, that back the memory content.")]
Tags = Annotated[list[str] | None, Field(description="Labels used to classify and retrieve the memory content.")]
MemoryStatus = Annotated[str, Field(description="Free-form lifecycle status stored in frontmatter, such as active, draft, or archived. Only active entries are recalled. Defaults to active.")]
CurationOrigin = Annotated[str, Field(description="Free-form origin label stored in frontmatter recording how the memory was created. Defaults to deliberate_write.")]
Expect = Annotated[str, Field(description="Create/update guard, and not an enum: pass the literal string absent for create-only, or the file's current content_hash for a guarded update.")]
Address = Annotated[str, Field(description="Stable docmancer://memory/<id> address, relative path, or exact title of the memory file.")]
ExpectedHash = Annotated[str, Field(description="The file's current content_hash from a prior read_memory call. A stale value fails safely instead of overwriting a newer revision.")]
CanonicalSection = Annotated[
    Literal["about", "preferences", "working-principles", "active-projects", "canonical-memory"] | None,
    Field(description="Canonical section to read. Omit for a status summary of every section."),
]
PinnableSection = Annotated[
    Literal["about", "preferences", "working-principles", "active-projects"],
    Field(description="Canonical section to modify. canonical-memory is excluded because it describes the store itself and is regenerated wholesale."),
]
RestoreToken = Annotated[str, Field(description="Restore token returned by a prior trash_memory call, identifying the file to restore.")]
AgentName = Annotated[str, Field(description="Target agent identifier, such as claude-code or cursor, used to shape and attribute the result. Defaults are tool-specific.")]
TokenBudget = Annotated[int | None, Field(description="Approximate maximum token size of the returned bundle. Omit to use the tool default.")]
RequiredTokenBudget = Annotated[int, Field(description="Approximate maximum token size of the returned context projection.")]
TimelineFileId = Annotated[str | None, Field(description="Stable memory file identifier. Supply it to restrict the timeline to one file's history.")]
TimelineOperation = Annotated[
    Literal["create", "edit", "move", "duplicate", "trash", "restore", "pin", "reconcile"] | None,
    Field(description="Operation name used to restrict the timeline to one kind of change. Omit for every operation."),
]
Answer = Annotated[bool, Field(description="When true, spend a configured provider call to generate a grounded cited answer from the recalled memory instead of returning the bundle alone.")]
AskMode = Annotated[
    Literal["concise", "normal", "thorough"],
    Field(description="Answer verbosity when answer is true. Ignored when answer is false. Defaults to normal."),
]
MemoryTask = Annotated[
    str,
    Field(description="Natural-language task or question to recall relevant policy, memory, and evidence for."),
]


def _argument_error(message: str, next_action: str) -> dict:
    return {
        "error": message,
        "error_type": "InvalidArgumentsError",
        "likely_cause": "The request used a missing, conflicting, or unsupported argument shape.",
        "retry_safe": True,
        "next_action": next_action,
    }


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

    @server.tool(
        description=(
            "READ-ONLY: semantic search over the raw evidence index, meaning the memory, instruction, "
            "and rule files that other coding agents already wrote on this machine and that docmancer "
            "harvested. Runs entirely locally against the embedding index; no network call, no cost. "
            "Use it to find what an agent originally recorded, with a relevance score and the file it "
            "came from. Not for curated memory you or an agent deliberately wrote: that lives in a "
            "separate tree, so use search_memory for it, or ask_memory to get both at once. "
            "Parameters: query is the natural-language text to match; limit caps the number of results "
            "(default 8); include_history adds superseded evidence to the active evidence; "
            "expand_relations adds items linked to a direct match. "
            "Returns a list of objects with score, excerpt, source_path, scope, kind, lifecycle_state, "
            "and a docmancer://record/<id> record_uri. Returns [] when nothing matches. "
            "Example: query='why did we choose Railway', limit=5."
        ),
        annotations=ToolAnnotations(
            title="Search harvested agent evidence",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def search_evidence(
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

    @server.tool(
        description=(
            "READ-ONLY: search the local documentation index built by `docmancer docs add`, covering "
            "library, API, and vendor documentation the user chose to ingest. Runs entirely locally; "
            "no network call, so it only ever returns docs already added on this machine and returns "
            "[] when none have been. Use it for version-specific library or vendor behaviour. Not for "
            "anything about this user or their projects: use search_memory, search_evidence, or "
            "ask_memory for that. "
            "Parameters: query is the natural-language text to match against the indexed documentation; "
            "limit caps the number of results (default 8). "
            "Returns a list of objects with the matching excerpt, its source document, and a relevance "
            "score. Example: query='fastapi dependency injection', limit=5."
        ),
        annotations=ToolAnnotations(
            title="Search local documentation index",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def search_docs(query: MemoryQuery, limit: ResultLimit = 8) -> list[dict]:
        return tools.docs_search(query, limit=limit)

    @server.tool(
        description=(
            "READ-ONLY: report whether the local evidence index that search_evidence queries is present "
            "and populated, including its on-disk path and its source and section counts. Local only, "
            "and takes no parameters. Call it first when search_evidence returns nothing, to tell an "
            "empty index apart from a genuine miss; an empty one means the user has not run "
            "`docmancer setup` yet. Not for curated memory health, which is context_status, nor for "
            "per-agent delivery, which is context_delivery. "
            "Returns an object with the index path and the number of indexed sources and sections."
        ),
        annotations=ToolAnnotations(
            title="Evidence index status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def evidence_status() -> dict:
        return tools.memory_status()

    # The public MCP surface mirrors the compact CLI. Atom-management,
    # conflict-resolution, consolidation, and Cloud mutation tools were removed
    # with their deprecated CLI counterparts.

    @server.tool(
        description=(
            "MUTATING: create or update one curated memory file in the memory tree, addressed as "
            "docmancer://memory/<id>. Writes to local disk and appends to the change timeline; never "
            "silently clobbers, because the expect guard decides whether an existing file may be "
            "replaced. Use it to record a durable decision, constraint, or convention. Not for "
            "correcting the reconciled canonical memory about the user, which is regenerated and would "
            "discard the edit: use pin_memory for that. To change only the body of an existing file, "
            "prefer edit_memory. "
            "Parameters: relative_path is the file's path in the tree, such as "
            "'decisions/deployment.md'; text is the full Markdown body; expect is the write guard, "
            "'absent' (default) to create only and fail if the path exists, or the current "
            "content_hash to permit a guarded overwrite; memory_type, scope, authority, status, and "
            "curation_origin are frontmatter labels described in the schema; project_id names the "
            "owning project; sources lists backing file paths or URLs; tags lists retrieval labels; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the stable address, the new content_hash, and the revision id, "
            "all of which later guarded calls need. "
            "Example: relative_path='decisions/deployment.md', text='# Deployment\\n\\nWe use Railway.', "
            "authority='mandatory'."
        ),
        annotations=ToolAnnotations(
            title="Create or update a memory file",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def write_memory(
        relative_path: RelativePath,
        text: MemoryText,
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
    ) -> dict:
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
            "READ-ONLY: read one curated memory file in full, resolved by stable address, relative "
            "path, or exact title. Local disk read with no side effects. Ambiguous title or path "
            "matches return every candidate address rather than guessing, so a caller can retry with "
            "an exact address. This is also how you obtain the content_hash that edit_memory, "
            "move_memory, duplicate_memory, and trash_memory all require. Use search_memory first when "
            "you do not already know which file you want. "
            "Parameters: address is the docmancer://memory/<id> address, the relative path, or the "
            "exact title; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the body, frontmatter, address, content_hash, and revision id, or "
            "a candidates list when the address was ambiguous. "
            "Example: address='docmancer://memory/01J8XY...'."
        ),
        annotations=ToolAnnotations(
            title="Read a memory file",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def read_memory(
        address: Address,
        project_path: ProjectPath = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.read_memory(address, project_path=project_path)

    @server.tool(
        description=(
            "MUTATING: replace the body of one existing curated memory file while preserving its "
            "frontmatter, address, and history. Writes to local disk and appends to the change "
            "timeline. The write is guarded: a stale expected_hash fails without changing anything and "
            "returns a structured error naming the re-read-and-retry next action, so concurrent edits "
            "cannot be lost. Read the file first to obtain the hash. Not for canonical memory about "
            "the user, which reconciliation regenerates: use pin_memory there. Not for creating a new "
            "file: use write_memory. "
            "Parameters: address identifies the file to edit; text is the complete replacement "
            "Markdown body, which overwrites rather than appends; expected_hash is the content_hash "
            "from the read that produced text; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the address and the new content_hash and revision id. "
            "Example: address='docmancer://memory/01J8XY...', text='# Deployment\\n\\nWe use Fly.io.', "
            "expected_hash='9f2c...'."
        ),
        annotations=ToolAnnotations(
            title="Replace a memory file body",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def edit_memory(
        address: Address,
        text: MemoryText,
        expected_hash: ExpectedHash,
        project_path: ProjectPath = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.edit_memory(address, text, expected_hash=expected_hash, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: read the machine-wide canonical memory, which is what docmancer has reconciled "
            "about this user across every agent and project. Local disk read, machine-wide, so it takes "
            "no project_path. Call it before asking the user something they may already have told "
            "another agent. Not a search tool: it returns whole prepared sections rather than matches, "
            "so use search_memory or ask_memory to look something up. To change what it returns, use "
            "pin_memory rather than edit_memory. "
            "Parameters: section selects one of about (who the user is), preferences (how they want to "
            "work), working-principles (cross-project rules), active-projects (what they are working "
            "on), or canonical-memory (a description of the store itself); omit section entirely for a "
            "status summary of every section. "
            "Returns, with a section, that section split into its pinned zone (durable, survives "
            "reconciliation) and its generated zone (rewritten automatically), plus content_hash and "
            "revision id. Without a section, returns per-section presence and pinned-line counts. "
            "Example: section='preferences'."
        ),
        annotations=ToolAnnotations(
            title="Read canonical memory about the user",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def canonical_memory(section: CanonicalSection = None) -> dict:
        return tree_tools.canonical_memory(section=section)

    @server.tool(
        description=(
            "MUTATING: pin one durable line into a canonical memory section. Writes to local disk, "
            "machine-wide, so it takes no project_path. The pinned zone is the ONLY part of a canonical "
            "section that survives automatic reconciliation, so use this, not edit_memory or "
            "write_memory, for any correction, standing preference, or fact the reconciler got wrong "
            "or left out. Idempotent: pinning the same line twice changes nothing. Use unpin_memory to "
            "reverse it, and canonical_memory to see the result. "
            "Parameters: section selects which canonical section to pin into, one of about, "
            "preferences, working-principles, or active-projects; text is the complete line to pin, "
            "which should read as a standalone statement because it is stored verbatim. "
            "Returns an object with the section, its path, and the updated pinned-line count. "
            "Example: section='preferences', text='Prefers pnpm over npm for all TypeScript work.'"
        ),
        annotations=ToolAnnotations(
            title="Pin a durable line to canonical memory",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def pin_memory(section: PinnableSection, text: CanonicalPinText) -> dict:
        return tree_tools.pin_memory(section, text)

    @server.tool(
        description=(
            "MUTATING and DESTRUCTIVE: permanently remove pinned lines from a canonical memory section "
            "by case-insensitive substring match, with no undo and no restore token. Writes to local "
            "disk, machine-wide, so it takes no project_path. A substring can match more lines than "
            "intended, so read the section with canonical_memory first and pass text specific enough "
            "to hit only what you mean. Fails without changing anything when nothing matches, which "
            "makes a dry run safe. Only pinned lines are removable; generated content is rewritten by "
            "reconciliation instead. "
            "Parameters: section selects which canonical section to modify, one of about, preferences, "
            "working-principles, or active-projects; text is the case-insensitive substring, not a "
            "whole line and not a pattern, identifying the pinned lines to delete. "
            "Returns an object with the section and how many lines were removed. "
            "Example: section='preferences', text='pnpm'."
        ),
        annotations=ToolAnnotations(
            title="Remove pinned lines from canonical memory",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def unpin_memory(section: PinnableSection, text: CanonicalUnpinText) -> dict:
        return tree_tools.unpin_memory(section, text)

    @server.tool(
        description=(
            "MUTATING and DESTRUCTIVE at the old path: move or rename one curated memory file. Writes "
            "to local disk and appends to the change timeline. The file's stable docmancer://memory "
            "address survives the move, so existing references by address keep working, but the old "
            "relative path stops resolving and anything referring to it by path breaks. Guarded by "
            "expected_hash, so a stale hash fails without changing anything. The body is untouched: "
            "use edit_memory to change content, or duplicate_memory to copy rather than move. "
            "Parameters: address identifies the file to move; new_relative_path is its destination "
            "path in the tree, including the .md suffix, and renaming is just a move within the same "
            "directory; expected_hash is the file's current content_hash from read_memory; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the unchanged address, the new path, and the new revision id. "
            "Example: address='docmancer://memory/01J8XY...', "
            "new_relative_path='decisions/hosting.md', expected_hash='9f2c...'."
        ),
        annotations=ToolAnnotations(
            title="Move or rename a memory file",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def move_memory(
        address: Address,
        new_relative_path: RelativePath,
        expected_hash: ExpectedHash,
        project_path: ProjectPath = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.move_memory(
            address, new_relative_path, expected_hash=expected_hash, project_path=project_path
        )

    @server.tool(
        description=(
            "MUTATING: copy one curated memory file to a new path under a new stable identity. Writes "
            "to local disk and appends to the change timeline. The original is left untouched, and the "
            "copy gets its own docmancer://memory address and its own history, so the two diverge from "
            "here and editing one does not affect the other. Use it to fork an existing memory into a "
            "variant. Use move_memory instead when the original should not survive. Not idempotent: "
            "calling it twice with the same new_relative_path fails on the second call rather than "
            "creating a second copy. "
            "Parameters: address identifies the file to copy; new_relative_path is the copy's path in "
            "the tree, including the .md suffix, and must not already exist; expected_hash is the "
            "source file's current content_hash from read_memory, which guards against copying a "
            "revision you have not seen; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the new copy's address, path, content_hash, and revision id. "
            "Example: address='docmancer://memory/01J8XY...', "
            "new_relative_path='decisions/hosting-staging.md', expected_hash='9f2c...'."
        ),
        annotations=ToolAnnotations(
            title="Duplicate a memory file",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def duplicate_memory(
        address: Address,
        new_relative_path: RelativePath,
        expected_hash: ExpectedHash,
        project_path: ProjectPath = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.duplicate_memory(
            address, new_relative_path, expected_hash=expected_hash, project_path=project_path
        )

    @server.tool(
        description=(
            "DESTRUCTIVE BUT REVERSIBLE: move one curated memory file to trash so it stops being read "
            "or recalled. Writes to local disk and appends to the change timeline. Nothing is erased: "
            "the call returns a restore_token that restore_memory consumes to bring the file back, so "
            "keep that token in your reply if the user might change their mind. Guarded by "
            "expected_hash, so a stale hash fails without trashing anything. Prefer setting "
            "status='archived' with write_memory when the file should stay readable but stop being "
            "recalled. "
            "Parameters: address identifies the file to trash; expected_hash is its current "
            "content_hash from read_memory, confirming you are discarding the revision you actually "
            "saw; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the trashed address and the restore_token needed to undo it. "
            "Example: address='docmancer://memory/01J8XY...', expected_hash='9f2c...'."
        ),
        annotations=ToolAnnotations(
            title="Trash a memory file",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def trash_memory(
        address: Address,
        expected_hash: ExpectedHash,
        project_path: ProjectPath = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.trash_memory(address, expected_hash=expected_hash, project_path=project_path)

    @server.tool(
        description=(
            "MUTATING: undo a trash_memory call by restoring one curated memory file from its restore "
            "token. Writes to local disk and appends to the change timeline. The file returns to its "
            "original path with its address and history intact, so references by address resume "
            "working. A token is single-use and only valid for the tree it was issued against, so a "
            "spent or foreign token fails without changing anything. Restoring is only possible while "
            "the token is known: there is no way to browse trash from MCP. "
            "Parameters: restore_token is the exact token returned by the trash_memory call being "
            "undone; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the restored address, path, and revision id. "
            "Example: restore_token='trash-01J8XY...'."
        ),
        annotations=ToolAnnotations(
            title="Restore a trashed memory file",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def restore_memory(restore_token: RestoreToken, project_path: ProjectPath = None) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.restore_memory(restore_token, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: lexical search over the curated memory tree, meaning the decisions, "
            "constraints, and conventions deliberately written by the user or an agent. Local disk "
            "read, no embedding call, no cost. Only active entries are searched; archived and trashed "
            "files are excluded. Returns [] rather than an error when nothing is relevant or the tree "
            "is empty, so an empty result is a real answer and not a failure. Not the same store as "
            "search_evidence, which searches raw harvested agent files instead; use ask_memory when "
            "you want both stores plus mandatory policy in one bundle. "
            "Parameters: query is the natural-language text to match; limit caps the number of results "
            "(default 8, capped at 50); "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns a list of objects with the docmancer://memory address, title, excerpt, authority, "
            "and source_type. Pass an address to read_memory for the full file. "
            "Example: query='prior deployment decision', limit=5."
        ),
        annotations=ToolAnnotations(
            title="Search curated memory",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def search_memory(
        query: MemoryQuery,
        limit: ResultLimit = 8,
        project_path: ProjectPath = None,
    ) -> list[dict] | dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.search_memory(query, limit=limit, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: list the memories that recur across two or more independent agent harnesses, "
            "for example something both Claude Code and Cursor recorded separately. Local disk read "
            "over already-harvested evidence; docmancer's own generated integration copies are "
            "excluded so they cannot manufacture agreement. Recurrence is evidence of salience, not "
            "proof of correctness, so treat the result as a signal worth checking rather than settled "
            "truth. Takes no query: it returns the whole recurring set. Use search_evidence to look "
            "something specific up instead. "
            "Parameters: "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns a list of objects describing each recurring memory and the harnesses it was seen "
            "in. Returns [] when nothing recurs. Example: call with no arguments."
        ),
        annotations=ToolAnnotations(
            title="Memories recurring across agents",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def common_memory(project_path: ProjectPath = None) -> list[dict] | dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.common_memory(project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: show, per agent, whether context is actually reaching it, listing each "
            "supported agent's integration mode, hook installation status, and the revision and hash "
            "of the last context bundle it was observed to receive. Local disk read with no side "
            "effects. This is the delivery question, so use it to diagnose why one agent seems to be "
            "missing context that another has. It is one of three context tools: context_status "
            "answers what the current context revision contains and how fresh it is, and "
            "context_projection renders the actual text one agent would receive. Read-only across all "
            "three; installing hooks and refreshing context are deliberately human-only CLI or "
            "local-web operations. "
            "Parameters: "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns a list with one row per agent giving its integration mode, hook status, and last "
            "delivered revision and hash. A stale or absent revision on one row is the signal to look "
            "for. Example: call with no arguments."
        ),
        annotations=ToolAnnotations(
            title="Per-agent context delivery status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def context_delivery(project_path: ProjectPath = None) -> list[dict] | dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.context_delivery(project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: inspect the consolidated Context itself, reporting its current revision id, how "
            "fresh it is, which sources are excluded, and its cluster metadata. Local disk read with no "
            "side effects. This is the what-and-how-fresh question, so use it to decide whether the "
            "context an agent is working from is stale or is missing something on purpose. It is one of "
            "three context tools: context_delivery answers whether each agent is actually receiving it, "
            "and context_projection renders the actual text one agent would receive. Refresh, rollback, "
            "adopt, and retire are deliberately human-only CLI or local-web operations, so no MCP tool "
            "can change what this reports. "
            "Parameters: "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the current revision, its scope and freshness, the active "
            "exclusions, and cluster metadata. Example: call with no arguments."
        ),
        annotations=ToolAnnotations(
            title="Consolidated context revision status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def context_status(project_path: ProjectPath = None) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.context_status(project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: render the actual bounded context text one named agent would receive, linked to "
            "the current revision. Local disk read that renders without writing, refreshing, or "
            "delivering anything, so it is safe to preview repeatedly. This is the show-me-the-content "
            "question, so use it to check what an agent will actually see before installing or "
            "debugging an integration. It is one of three context tools: context_status reports the "
            "revision and its freshness, and context_delivery reports whether each agent is receiving "
            "it. Refresh, rollback, adopt, and retire are human-only CLI or local-web operations. "
            "Parameters: agent is the required target agent identifier, such as claude-code or cursor, "
            "and the projection is shaped for that agent's integration; token_budget bounds the "
            "rendered size in approximate tokens (default 2000), so raising it returns more content and "
            "lowering it truncates by priority; "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the rendered projection text and the revision it was built from. "
            "Example: agent='claude-code', token_budget=4000."
        ),
        annotations=ToolAnnotations(
            title="Render a context projection for an agent",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
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
            "READ-ONLY: show the append-only history of how memory changed over time, with a "
            "human-readable diff per entry. Local disk read over a log that is only ever appended to, "
            "so nothing here can be rewritten and the record is trustworthy. Use it to answer when and "
            "how a memory changed, or to recover text that an edit replaced. Newest entries come "
            "first. This is history, not content: use search_memory or read_memory for what a file "
            "says now. "
            "Parameters: file_id restricts the timeline to one memory file's own history, which is the "
            "usual way to trace a single decision; operation restricts it to one kind of change, one "
            "of create, edit, move, duplicate, trash, restore, pin, or reconcile; limit caps how many "
            "entries come back (default 100); "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Omit every filter for the whole recent history. "
            "Returns a list of entries with the operation, timestamp, affected file, revision ids, and "
            "a readable diff. Example: file_id='01J8XY...', operation='edit', limit=20."
        ),
        annotations=ToolAnnotations(
            title="Memory change timeline",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
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
        task: str,
        project_path: str | None,
        token_budget: int | None,
        include_history: bool,
        limit: int,
        agent: str,
        answer: bool,
        mode: str,
    ) -> dict:
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
            "READ-ONLY: recall one bounded bundle of everything local memory knows about a task, "
            "combining mandatory policy, curated memory, and supporting harvested agent evidence in "
            "priority order. This is the default recall tool and the right first call when you do not "
            "already know which store holds the answer; search_memory and search_evidence each cover "
            "only one store. Local and free by default. Returns an empty bundle rather than an error "
            "when nothing relevant exists, so an empty result means the memory is genuinely silent. "
            "Parameters: task is the natural-language task or question to recall for; answer defaults "
            "to false and returns the raw bundle, and setting it true spends a configured provider "
            "call, which may leave the machine, to produce a grounded cited answer; mode sets that "
            "answer's verbosity to concise, normal, or thorough and is ignored when answer is false; "
            "token_budget bounds the bundle size in approximate tokens (default 4000); limit caps how "
            "many supporting evidence items are considered (default 12); include_history adds "
            "superseded evidence; agent is the requesting agent identifier recorded for attribution "
            "(default mcp-client); "
            f"project_path {_PROJECT_PATH_HELP[0].lower()}{_PROJECT_PATH_HELP[1:]} "
            "Returns an object with the mandatory policy, curated memory, and evidence sections, each "
            "carrying source citations, plus the generated answer when answer is true. "
            "Example: task='how do we deploy this project', token_budget=2000."
        ),
        annotations=ToolAnnotations(
            title="Recall memory for a task",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def ask_memory_tool(
        task: MemoryTask,
        project_path: ProjectPath = None,
        token_budget: TokenBudget = None,
        include_history: IncludeHistory = False,
        limit: ResultLimit = 12,
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
