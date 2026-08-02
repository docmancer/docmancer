"""Provider-planned, locally validated Shared Memory actions."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from docmancer.harness.secrets import redact_secrets
from docmancer.memory.laptop import (
    CANONICAL_EXCLUSIONS_PATH,
    CANONICAL_SECTION_PATHS,
    LaptopMemoryReconciler,
    laptop_memory_root,
    validate_canonical_exclusions,
)
from docmancer.memory.tree.journal import DecisionJournal
from docmancer.memory.tree.parser import parse_tree_file
from docmancer.memory.tree.project import resolve_project_root, tree_paths
from docmancer.memory.tree.store import TreeStore


ACTION_OPERATIONS = ("create", "edit", "pin", "move", "duplicate", "trash", "restore")
ACTION_STATUSES = ("pending", "applied", "cancelled", "superseded", "conflict", "failed")
PROJECT_FOLDERS = ("decisions", "constraints", "workflows", "lessons")
MACHINE_FOLDERS = ("profile", "principles", "projects", "shared")
MAX_AI_FILE_CHARS = 16_000
MAX_AI_EXACT_GENERATED_CHARS = 24_000

_MUTATION_VERB = (
    r"(?:remember|save|record|update|edit|change|rewrite|streamline|simplify|shorten|move|rename|duplicate|copy|"
    r"delete|remove|forget|trash|hide|exclude|suppress|ignore|retire|shelve|de[- ]?prioriti[sz]e|"
    r"stop\s+(?:showing|surfacing|including|using)|restore|undelete|undo\s+(?:the\s+)?deletion)"
)
_MUTATION_RE = re.compile(
    rf"(?:^\s*(?:please\s+)?{_MUTATION_VERB}\b|"
    rf"\b(?:please|can\s+you|could\s+you|would\s+you|will\s+you|"
    rf"i\s+want\s+you\s+to|i(?:'d|\s+would)\s+like\s+you\s+to|let(?:'s|\s+us))\s+"
    rf"{_MUTATION_VERB}\b)",
    re.IGNORECASE,
)
_MACHINE_RE = re.compile(
    r"\b(machine[- ]wide|global(?:ly)?|all projects|every project|across projects|"
    r"shared memor(?:y|ies)|canonical memor(?:y|ies)|master memor(?:y|ies)|"
    r"laptop(?:[- ]wide)? memor(?:y|ies)|all (?:of )?my memor(?:y|ies)|"
    r"all (?:of )?my shared memory files|every shared memory file|across (?:all )?my memor(?:y|ies)|"
    r"my preference|i prefer|about me|my profile|my career)\b",
    re.IGNORECASE,
)
_PROJECT_RE = re.compile(
    r"\b(this project|this repo|this repository|current project|current repo|"
    r"project decision|project workflow|release workflow|deployment decision)\b",
    re.IGNORECASE,
)
_CANONICAL_FORGET_RE = re.compile(
    r"\b(?:delete|remove|forget|trash|hide|exclude|suppress|ignore|retire|shelve|"
    r"de[- ]?prioriti[sz]e|stop (?:showing|surfacing|including|using)|"
    r"no longer (?:show|surface|include|use)|not (?:using|working on))\b",
    re.IGNORECASE | re.DOTALL,
)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.IGNORECASE)
_GENERATED_REWRITE_RE = re.compile(r"\b(?:streamline|simplify|shorten)\b", re.IGNORECASE)


class MemoryActionDraft(BaseModel):
    """One provider response. The server rejects incomplete combinations."""

    outcome: Literal["proposal", "clarification", "none"]
    message: str = ""
    operation: Literal["create", "edit", "pin", "move", "duplicate", "trash", "restore"] | None = None
    scope: Literal["project", "machine"] | None = None
    target_address: str | None = None
    path: str | None = None
    markdown: str | None = None
    section: str | None = None
    restore_token: str | None = None
    rationale: str = ""


class ActionPlanningResult(BaseModel):
    kind: Literal["proposal", "clarification", "none", "unavailable"]
    message: str
    proposal: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None


def is_mutation_request(task: str) -> bool:
    """High-precision local gate. Ordinary Ask never pays for action planning."""
    return bool(_MUTATION_RE.search(task or ""))


def _scope_hint(task: str) -> str | None:
    machine = bool(_MACHINE_RE.search(task))
    project = bool(_PROJECT_RE.search(task))
    if machine == project:
        return None
    return "machine" if machine else "project"


def _canonical_forget_request(task: str, scope_hint: str | None) -> bool:
    """Recognize a broad generated-memory removal, never a source-file delete."""
    return scope_hint == "machine" and bool(_CANONICAL_FORGET_RE.search(task or ""))


def _safe_markdown(text: str, *, label: str) -> str:
    value = str(text or "").strip()
    if not value:
        raise ValueError(f"{label} Markdown is empty")
    if len(value) > MAX_AI_FILE_CHARS:
        raise ValueError(
            f"{label} is larger than {MAX_AI_FILE_CHARS:,} characters and must be edited manually"
        )
    if redact_secrets(value) != value:
        raise ValueError(f"{label} contains possible secrets and must be edited manually")
    return value + ("\n" if not value.endswith("\n") else "")


def _allowed_path(scope: str, value: str) -> str:
    path = Path(str(value or "").strip())
    if path.is_absolute() or ".." in path.parts or path.suffix.casefold() != ".md":
        raise ValueError("memory path must be a relative Markdown path")
    prefixes = MACHINE_FOLDERS if scope == "machine" else PROJECT_FOLDERS
    relative = path.as_posix()
    if not path.parts or path.parts[0] not in prefixes:
        raise ValueError(
            f"{scope} memory paths must live under: {', '.join(prefixes)}"
        )
    if scope == "machine" and relative in set(CANONICAL_SECTION_PATHS.values()):
        raise ValueError("generated canonical sections must be changed with a pin action")
    return relative


def _entry_payload(entry, *, scope: str, root: Path) -> dict[str, Any]:
    path = entry.path.relative_to(root).as_posix()
    return {
        "scope": scope,
        "address": entry.address,
        "path": path,
        "title": entry.title,
        "markdown": entry.body,
        "content_hash": entry.content_hash,
        "type": entry.type,
        "authority": entry.authority,
        "generated_section": next(
            (key for key, relative in CANONICAL_SECTION_PATHS.items() if relative == path),
            None,
        ),
    }


class MemoryActionEngine:
    """Plan and execute exactly one guarded Shared Memory action."""

    def __init__(self, project_path: str | Path, *, memory_agent=None) -> None:
        self.project_path = resolve_project_root(project_path)
        self.project_store = TreeStore(tree_paths(self.project_path)[0])
        self.machine_store = TreeStore(laptop_memory_root() / "tree")
        self.memory_agent = memory_agent

    def _store(self, scope: str) -> TreeStore:
        if scope == "project":
            return self.project_store
        if scope == "machine":
            return self.machine_store
        raise ValueError("scope must be project or machine")

    def _entries(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for scope, store in (("project", self.project_store), ("machine", self.machine_store)):
            rows.extend(
                _entry_payload(entry, scope=scope, root=store.root)
                for entry in store.index.entries()
            )
        return rows

    @staticmethod
    def _score(task: str, row: dict[str, Any]) -> tuple[int, str]:
        query = {token.casefold() for token in _TOKEN_RE.findall(task)}
        haystack = " ".join(
            str(row.get(key) or "") for key in ("address", "path", "title", "markdown")
        ).casefold()
        score = sum(3 if token in str(row.get("path") or "").casefold() else 1 for token in query if token in haystack)
        if str(row["address"]) in task or str(row["path"]) in task:
            score += 100
        return score, str(row["path"])

    def _candidates(self, task: str) -> list[dict[str, Any]]:
        rows = self._entries()
        ranked = sorted(rows, key=lambda row: self._score(task, row), reverse=True)
        return [row for row in ranked if self._score(task, row)[0] > 0][:8]

    def _trash_candidates(self) -> list[dict[str, Any]]:
        rows = []
        for scope, store in (("project", self.project_store), ("machine", self.machine_store)):
            for manifest_path in sorted(store.trash_root.glob("*.manifest.json")):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    token = str(manifest["memory_id"])
                    body_path = store.trash_root / f"{token}.md"
                    entry = parse_tree_file(body_path) if body_path.is_file() else None
                    rows.append({
                        "scope": scope,
                        "restore_token": token,
                        "path": str(manifest["original_relative_path"]),
                        "markdown": entry.body if entry else "",
                    })
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    continue
        return rows

    def _client(self):
        if self.memory_agent is None:
            from docmancer.memory import MemoryAgent

            self.memory_agent = MemoryAgent()
        from docmancer.ai.providers.factory import provider_client

        config = self.memory_agent.config.providers
        return provider_client(config.default_llm, config=config)

    def _reconciler(self) -> LaptopMemoryReconciler:
        if self.memory_agent is None:
            from docmancer.memory import MemoryAgent

            self.memory_agent = MemoryAgent()
        return LaptopMemoryReconciler(self.memory_agent)

    def plan(
        self,
        task: str,
        *,
        history: list[dict[str, str]] | None = None,
        client=None,
    ) -> dict[str, Any]:
        if not is_mutation_request(task):
            return ActionPlanningResult(kind="none", message="").model_dump()
        if redact_secrets(task) != task:
            return ActionPlanningResult(
                kind="unavailable",
                message="This request may contain a secret. Edit the memory file manually instead.",
            ).model_dump()

        candidates = self._candidates(task)
        hint = _scope_hint(task)
        canonical_forget = _canonical_forget_request(task, hint)
        exclusion = None
        if canonical_forget:
            exclusion = next(
                (
                    row
                    for row in self._entries()
                    if row["scope"] == "machine"
                    and row["path"] == CANONICAL_EXCLUSIONS_PATH
                ),
                None,
            )
            if exclusion is not None and all(
                row["address"] != exclusion["address"] for row in candidates
            ):
                candidates.append(exclusion)
        exact_scopes = {
            str(row["scope"])
            for row in candidates
            if str(row["address"]) in task or str(row["path"]) in task
        }
        if len(exact_scopes) == 1:
            hint = next(iter(exact_scopes))
        safe_candidates = []
        for row in candidates:
            body = str(row["markdown"])
            exact_target = str(row["address"]) in task or str(row["path"]) in task
            size_limit = (
                MAX_AI_EXACT_GENERATED_CHARS
                if exact_target and row.get("generated_section")
                else MAX_AI_FILE_CHARS
            )
            if len(body) > size_limit or redact_secrets(body) != body:
                if exact_target:
                    reason = (
                        f"The complete target file exceeds {size_limit:,} characters."
                        if len(body) > size_limit
                        else "Secret redaction would change the complete target file."
                    )
                    return ActionPlanningResult(
                        kind="unavailable",
                        message=f"{reason} Shared Memory is unchanged; use the manual editor.",
                    ).model_dump()
                continue
            safe_candidates.append(row)

        generated_rewrite_target = next(
            (
                row for row in safe_candidates
                if row.get("generated_section")
                and (str(row["address"]) in task or str(row["path"]) in task)
            ),
            None,
        )
        if (
            generated_rewrite_target is not None
            and _GENERATED_REWRITE_RE.search(task)
            and "User clarification:" not in task
        ):
            return ActionPlanningResult(
                kind="clarification",
                message=(
                    f"{generated_rewrite_target['path']} is generated from source evidence, so "
                    "replacing it directly would be overwritten on the next refresh. Should I "
                    "prepare a concise summary in its preserved pinned section instead?"
                ),
            ).model_dump()

        try:
            planner = client or self._client()
        except Exception:
            return ActionPlanningResult(
                kind="unavailable",
                message=(
                    "Conversational memory editing needs a configured generation provider. "
                    "Shared Memory is unchanged; use docmancer write, edit, move, trash, or restore manually."
                ),
            ).model_dump()

        prompt = {
            "task": task,
            "project": str(self.project_path),
            "scope_hint": hint,
            "scope_rule": (
                "Use scope_hint when present. If it is absent and the target does not uniquely "
                "determine scope, return clarification asking machine-wide or current project."
            ),
            "shared_memory_reference": {
                "definition": (
                    "Shared Memory is Docmancer's machine-wide canonical memory. It is the local "
                    "cross-agent view assembled from attributable evidence, user-approved pinned "
                    "notes, and durable machine-wide controls."
                ),
                "terminology": {
                    "same_product_surface": [
                        "Shared Memory",
                        "shared memories",
                        "canonical memory",
                        "master memory",
                        "laptop memory",
                        "laptop-wide memory",
                        "machine memory",
                        "global memory",
                        "all my memory files",
                        "all my shared memory files",
                        "memory shared by my agents",
                        "memory available to every agent",
                    ],
                    "not_the_same_thing": [
                        "A source repository or its code files",
                        "Agent-owned source memory such as CLAUDE.md or MEMORY.md",
                        "Project-scoped curated memory under the current project's .docmancer tree",
                        "The separate technical-documentation index",
                        "Chat history",
                    ],
                },
                "storage_model": [
                    (
                        "Generated canonical files summarize source evidence. Their generated zones "
                        "are rebuilt and must never be edited, replaced, or trashed directly."
                    ),
                    (
                        "Pinned zones are preserved user-owned corrections or summaries. A pin action "
                        "replaces one complete pinned zone, not generated evidence."
                    ),
                    (
                        f"{CANONICAL_EXCLUSIONS_PATH} is the durable control file for removing topics, "
                        "projects, paths, or text from generated machine-wide memory while leaving all "
                        "source evidence untouched."
                    ),
                    (
                        "Standalone curated machine or project files can be created, edited, moved, "
                        "duplicated, trashed, or restored only when one exact file is identified."
                    ),
                ],
                "intent_precedence": [
                    (
                        "An exact supplied docmancer:// address or exact candidate path identifies one "
                        "existing file. Follow that target unless it is a generated canonical section."
                    ),
                    (
                        "A request to remove a project, topic, company, product, person, preference, "
                        "decision family, or source from Shared Memory is a canonical exclusion, not a "
                        "request to delete repositories or agent-owned evidence."
                    ),
                    (
                        "Words such as remove, forget, hide, exclude, suppress, ignore, retire, shelve, "
                        "stop showing, stop surfacing, no longer include, and de-prioritize all express "
                        "canonical-exclusion intent when their object is material in Shared Memory."
                    ),
                    (
                        "Lifecycle explanations such as 'I am not using it anymore', 'we stopped working "
                        "on it', 'this is inactive', or 'this is no longer relevant' strengthen an "
                        "accompanying removal or exclusion request. They do not authorize source deletion."
                    ),
                    (
                        "When the user offers alternatives such as 'remove it or de-prioritize it' and the "
                        "context says the subject is inactive or unused, choose the supported canonical "
                        "exclusion. Do not return a proposal without an operation."
                    ),
                    (
                        "If the user asks only for lower ranking or lower priority while explicitly wanting "
                        "the material to remain visible, return one clarification because Shared Memory has "
                        "no persistent ranking-weight action."
                    ),
                    (
                        "If scope is genuinely absent and neither an exact target nor Shared Memory wording "
                        "resolves it, ask whether the change is machine-wide or project-only."
                    ),
                ],
                "canonical_exclusion_contract": {
                    "required_path": CANONICAL_EXCLUSIONS_PATH,
                    "purpose": (
                        "Filter matching evidence before generated canonical sections are reconciled. "
                        "Never edit or delete the matching source files."
                    ),
                    "required_markdown_shape": (
                        "Return the complete file with '# Canonical memory exclusions', then "
                        "'## Evidence path contains' and '## Text contains'. Put one literal "
                        "case-insensitive substring in each bullet. Preserve all existing exclusions."
                    ),
                    "selection_guidance": [
                        "Use Evidence path contains for distinctive repository, directory, or filename fragments.",
                        "Use Text contains for distinctive project, product, topic, or entity names.",
                        "Include common spacing, punctuation, or casing variants only when one literal would miss them.",
                        "Do not add broad terms that could suppress unrelated projects or evidence.",
                    ],
                },
                "examples": [
                    {
                        "request": "Remove Token Tape from all my shared memory files.",
                        "interpretation": "Canonical exclusion for Token Tape in machine-wide Shared Memory.",
                    },
                    {
                        "request": "Remove the project Token Tape or de-prioritize it. I am not using it anymore.",
                        "interpretation": "Choose canonical exclusion because removal is supported and inactivity resolves the alternative.",
                    },
                    {
                        "request": "Stop surfacing the old pet marketplace project to any of my agents.",
                        "interpretation": "Canonical exclusion because the request targets cross-agent generated memory.",
                    },
                    {
                        "request": "Forget everything from repositories whose path contains /token_tape/.",
                        "interpretation": "Add a narrow Evidence path contains exclusion. Do not touch those repositories.",
                    },
                    {
                        "request": "Hide references to Mewline from canonical memory but keep the source notes.",
                        "interpretation": "Add a narrow Text contains exclusion and preserve source notes.",
                    },
                    {
                        "request": "This project is shelved and should no longer appear in laptop-wide memory.",
                        "interpretation": "Canonical exclusion for the identified project.",
                    },
                    {
                        "request": "De-prioritize Token Tape but keep it visible when directly relevant.",
                        "interpretation": "Clarification required because persistent ranking weights are unsupported and exclusion would hide it.",
                    },
                    {
                        "request": "Trash decisions/obsolete-launch.md from this project.",
                        "interpretation": "Exact project-file trash, not a canonical exclusion.",
                    },
                    {
                        "request": "Rewrite projects/active.md to remove Token Tape.",
                        "interpretation": "Do not rewrite the generated section. Use canonical exclusion or ask about a pinned note.",
                    },
                    {
                        "request": "Delete the Token Tape repository and its memory.",
                        "interpretation": "Never delete the repository. Only a Shared Memory proposal is permitted here, and source deletion requires separate explicit handling outside this system.",
                    },
                ],
                "output_requirements": [
                    "Return exactly one proposal, one necessary clarification, or none.",
                    "A proposal must always include exactly one supported operation.",
                    "Never invent an address, path, operation, or restore token.",
                    "Never convert a Shared Memory cleanup into source-file deletion.",
                    "Never treat yes, ok, approval language, or lifecycle commentary by itself as authorization to apply an action.",
                ],
            },
            "rules": [
                "Return exactly one action or one clarification.",
                "scope_hint is authoritative when present; never ask the user to repeat that scope.",
                "Use only a supplied target_address for existing files.",
                (
                    "Generated sections permit pin only. A pin replaces the complete preserved "
                    "pinned zone and never replaces the generated evidence below it. If a request "
                    "asks to rewrite generated evidence, ask whether to add a concise pinned note instead."
                ),
                "For create, edit, or pin, markdown is the complete proposed body or complete pinned zone.",
                "Move and duplicate stay within one scope.",
                "Never interpret yes or approval as an action.",
                (
                    "A broad request to remove topics or projects from generated machine-wide "
                    f"Shared Memory without touching source files must create or edit "
                    f"{CANONICAL_EXCLUSIONS_PATH}. Use headings '## Evidence path contains' "
                    "and '## Text contains', with one literal case-insensitive substring per bullet."
                ),
            ],
            "allowed_project_folders": PROJECT_FOLDERS,
            "allowed_machine_folders": MACHINE_FOLDERS,
            "candidates": [
                {
                    "scope": row["scope"],
                    "address": row["address"],
                    "path": row["path"],
                    "title": row["title"],
                    "markdown": row["markdown"],
                    "generated_section": row["generated_section"],
                }
                for row in safe_candidates
            ],
            "trash": self._trash_candidates(),
            "recent_conversation": list(history or [])[-6:],
            "canonical_exclusion_target": (
                {
                    "scope": "machine",
                    "path": CANONICAL_EXCLUSIONS_PATH,
                    "address": exclusion["address"] if exclusion is not None else None,
                    "required_operation": "edit" if exclusion is not None else "create",
                }
                if canonical_forget
                else None
            ),
        }
        try:
            draft = planner.parse(
                [
                    {
                        "role": "system",
                        "content": (
                            "Plan exactly one safe Shared Memory file action from the supplied "
                            "request and constraints. Do not answer the request as a question. "
                            "Do not ask for information the request or scope_hint already supplies."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                MemoryActionDraft,
                temperature=0.0,
                max_tokens=4096,
            )
        except Exception as exc:
            return ActionPlanningResult(
                kind="unavailable",
                message=f"Docmancer could not validate a memory action ({type(exc).__name__}). Shared Memory is unchanged.",
            ).model_dump()

        provider = str(getattr(planner, "provider_name", "") or "")
        model = str(getattr(planner, "model", "") or "")
        if draft.outcome != "proposal":
            return ActionPlanningResult(
                kind="clarification" if draft.outcome == "clarification" else "none",
                message=draft.message or (
                    "Should this be saved machine-wide or only for the current project?"
                    if draft.outcome == "clarification"
                    else "No memory change was proposed."
                ),
                provider=provider,
                model=model,
            ).model_dump()
        if draft.operation == "pin" and not str(draft.markdown or "").strip():
            target = next(
                (
                    row for row in safe_candidates
                    if row.get("generated_section")
                    and str(row["address"]) == str(draft.target_address or "")
                ),
                None,
            )
            if target is not None:
                return ActionPlanningResult(
                    kind="clarification",
                    message=(
                        f"{target['path']} is generated from source evidence, so replacing it "
                        "directly would be overwritten on the next refresh. Should I prepare a "
                        "concise summary in its preserved pinned section instead?"
                    ),
                    provider=provider,
                    model=model,
                ).model_dump()
        if canonical_forget:
            draft.scope = "machine"
            draft.path = CANONICAL_EXCLUSIONS_PATH
            if exclusion is None:
                draft.operation = "create"
                draft.target_address = None
            else:
                draft.operation = "edit"
                draft.target_address = str(exclusion["address"])
        try:
            proposal = self._validate_draft(draft, safe_candidates)
        except ValueError as exc:
            return ActionPlanningResult(
                kind="unavailable",
                message=f"Docmancer refused the proposed memory action: {exc}. Shared Memory is unchanged.",
                provider=provider,
                model=model,
            ).model_dump()
        proposal.update(id=new_action_id(), provider=provider, model=model)
        return ActionPlanningResult(
            kind="proposal",
            message=self._proposal_message(proposal),
            proposal=proposal,
            provider=provider,
            model=model,
        ).model_dump()

    def _validate_draft(
        self,
        draft: MemoryActionDraft,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        operation = str(draft.operation or "")
        if operation not in ACTION_OPERATIONS:
            raise ValueError("the provider did not return one supported action")
        by_address = {str(row["address"]): row for row in candidates}
        scope = str(draft.scope or "")
        before = ""
        after = ""
        address = str(draft.target_address or "")
        path = str(draft.path or "")
        section = str(draft.section or "")
        restore_token = str(draft.restore_token or "")
        expected_hash = None
        target = None

        if operation == "create":
            if scope not in {"project", "machine"}:
                raise ValueError("create needs an unambiguous scope")
            path = _allowed_path(scope, path)
            after = _safe_markdown(str(draft.markdown or ""), label="proposed memory")
            if path == CANONICAL_EXCLUSIONS_PATH:
                validate_canonical_exclusions(after)
            if (self._store(scope).root / path).exists():
                raise ValueError("the proposed create path already exists")
        elif operation == "restore":
            matches = [
                row for row in self._trash_candidates()
                if row["restore_token"] == restore_token
                and (not scope or row["scope"] == scope)
            ]
            if len(matches) != 1:
                raise ValueError("restore needs one valid restore token")
            target = matches[0]
            scope = str(target["scope"])
            path = str(target["path"])
            after = str(target["markdown"])
        else:
            requested_path = path
            target = by_address.get(address)
            if target is None:
                raise ValueError("the action target is not one of the allowed current files")
            scope = str(target["scope"])
            before = str(target["markdown"])
            current_path = str(target["path"])
            path = current_path
            expected_hash = str(target["content_hash"])
            generated = str(target.get("generated_section") or "")
            if generated and operation != "pin":
                raise ValueError("generated canonical sections support pin actions only")
            if operation == "pin":
                if not generated or generated == "canonical-memory":
                    raise ValueError("pin needs one writable generated canonical section")
                section = generated
                before = str(self._reconciler().read_section(section)["pinned"])
                after = _safe_markdown(str(draft.markdown or ""), label="proposed pinned memory")
            elif operation == "edit":
                before = _safe_markdown(before, label="existing memory")
                after = _safe_markdown(str(draft.markdown or ""), label="proposed memory")
                if current_path == CANONICAL_EXCLUSIONS_PATH:
                    validate_canonical_exclusions(after)
            elif operation in {"move", "duplicate"}:
                path = _allowed_path(scope, requested_path)

        before_path = (
            None if operation in {"create", "restore"}
            else str(target["path"]) if target else None
        )
        after_path = (
            None if operation == "trash"
            else path
        )
        diff = DecisionJournal.diff(
            before,
            after if operation not in {"move", "duplicate"} else before,
            before_path=before_path,
            after_path=after_path,
        )
        return {
            "operation": operation,
            "scope": scope,
            "target": address or restore_token or path,
            "address": address or None,
            "path": path or None,
            "section": section or None,
            "restore_token": restore_token or None,
            "expected_hash": expected_hash,
            "before_markdown": before,
            "after_markdown": after,
            "diff": diff,
            "rationale": draft.rationale or draft.message or "Update Shared Memory as requested.",
            "destructive": operation == "trash",
            "status": "pending",
        }

    @staticmethod
    def _proposal_message(proposal: dict[str, Any]) -> str:
        operation = str(proposal["operation"])
        target = str(proposal.get("path") or proposal.get("target") or "Shared Memory")
        return f"I prepared one {operation} proposal for {target}. Review the complete change before applying it."

    def execute(
        self,
        proposal: dict[str, Any],
        *,
        actor_surface: str,
        actor_harness: str = "docmancer-agent",
    ) -> dict[str, Any]:
        operation = str(proposal["operation"])
        scope = str(proposal["scope"])
        store = self._store(scope)
        address = str(proposal.get("address") or "")
        expected_hash = str(proposal.get("expected_hash") or "")
        path = str(proposal.get("path") or "")

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            if scope == "machine" and path == CANONICAL_EXCLUSIONS_PATH:
                result["canonical_reconcile"] = self._reconciler().reconcile(
                    use_provider=False,
                    force=True,
                )
            return result

        if operation == "pin":
            return self._reconciler().set_pinned(
                str(proposal["section"]),
                str(proposal["after_markdown"]).rstrip(),
                expect=expected_hash,
            )
        if operation == "create":
            entry = store.write(
                relative_path=_allowed_path(scope, path),
                text=str(proposal["after_markdown"]),
                scope="global" if scope == "machine" else "project",
                project_id=(
                    None
                    if scope == "machine"
                    else hashlib.sha256(str(self.project_path).encode()).hexdigest()[:16]
                ),
                expect="absent",
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return finish({"address": entry.address, "path": path, "content_hash": entry.content_hash})
        if operation == "edit":
            entry = store.edit(
                address,
                text=str(proposal["after_markdown"]),
                expected_hash=expected_hash,
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return finish({"address": entry.address, "path": path, "content_hash": entry.content_hash})
        if operation == "move":
            entry = store.move(
                address,
                _allowed_path(scope, path),
                expected_hash=expected_hash,
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return {"address": entry.address, "path": path, "content_hash": entry.content_hash}
        if operation == "duplicate":
            entry = store.duplicate(
                address,
                _allowed_path(scope, path),
                expected_hash=expected_hash,
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return {"address": entry.address, "path": path, "content_hash": entry.content_hash}
        if operation == "trash":
            token = store.trash(
                address,
                expected_hash=expected_hash,
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return {"trashed": True, "restore_token": token, "path": path}
        if operation == "restore":
            entry = store.restore(
                str(proposal["restore_token"]),
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return {
                "address": entry.address,
                "path": entry.path.relative_to(store.root).as_posix(),
                "content_hash": entry.content_hash,
            }
        raise ValueError(f"unsupported memory action {operation!r}")


def new_action_id() -> str:
    return f"act_{secrets.token_urlsafe(12)}"


__all__ = [
    "ACTION_OPERATIONS",
    "ACTION_STATUSES",
    "MAX_AI_FILE_CHARS",
    "MAX_AI_EXACT_GENERATED_CHARS",
    "MemoryActionDraft",
    "MemoryActionEngine",
    "is_mutation_request",
    "new_action_id",
]
