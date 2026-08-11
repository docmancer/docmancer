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
    parse_canonical_exclusions,
    validate_canonical_exclusions,
)
from docmancer.memory.tree.journal import DecisionJournal
from docmancer.memory.tree.errors import AddressNotFoundError
from docmancer.memory.tree.parser import parse_tree_file
from docmancer.memory.tree.project import resolve_project_root, tree_paths
from docmancer.memory.tree.store import TreeStore
from docmancer.memory.tree.zones import split_zones


ACTION_OPERATIONS = ("create", "edit", "pin", "move", "duplicate", "trash", "restore")
ACTION_STATUSES = ("pending", "applied", "cancelled", "superseded", "conflict", "failed")
PROJECT_FOLDERS = ("decisions", "constraints", "workflows", "lessons")
MACHINE_FOLDERS = ("profile", "principles", "projects", "shared")
MAX_AI_FILE_CHARS = 16_000
MAX_AI_EXACT_GENERATED_CHARS = 24_000

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.IGNORECASE)


class MemoryActionDraft(BaseModel):
    """Semantic turn interpretation plus an optional memory proposal."""

    request_kind: Literal["read", "mutate", "mixed"]
    outcome: Literal["proposal", "clarification", "none"]
    message: str = ""
    read_question: str | None = None
    retrieval_queries: list[str] = Field(default_factory=list)
    operation: Literal["create", "edit", "pin", "move", "duplicate", "trash", "restore"] | None = None
    scope: Literal["project", "machine"] | None = None
    target_address: str | None = None
    path: str | None = None
    markdown: str | None = None
    section: str | None = None
    restore_token: str | None = None
    desired_visibility: Literal["unchanged", "absent_from_generated_shared_memory"] = "unchanged"
    preserve_source_evidence: bool = True
    rationale: str = ""


class ActionPlanningResult(BaseModel):
    kind: Literal["proposal", "clarification", "none", "unavailable"]
    message: str
    proposal: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    request_kind: Literal["read", "mutate", "mixed"] = "read"
    read_question: str | None = None
    retrieval_queries: list[str] = Field(default_factory=list)


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


def _strengthen_canonical_exclusions(markdown: str) -> str:
    """Add path-safe variants when a provider only returns a display name.

    Repository names commonly use underscores even when their display names use
    spaces. A text-only exclusion can therefore leave branded-neutral evidence
    from that repository in generated canonical files.
    """
    rules = parse_canonical_exclusions(markdown)
    if not any(rules.values()):
        return markdown
    existing = set(rules["evidence_path_contains"])
    additions: list[str] = []
    for value in rules["text_contains"]:
        slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
        if "_" in slug and slug not in existing and slug not in additions:
            additions.append(slug)
    if not additions:
        return markdown

    lines = markdown.rstrip("\n").splitlines()
    heading = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().casefold() == "## evidence path contains"
        ),
        None,
    )
    if heading is None:
        return markdown
    insert_at = next(
        (
            index
            for index in range(heading + 1, len(lines))
            if lines[index].strip().startswith("## ")
        ),
        len(lines),
    )
    while insert_at > heading + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = [f"- {value}" for value in additions]
    return "\n".join(lines).rstrip() + "\n"


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
        if redact_secrets(task) != task:
            return ActionPlanningResult(
                kind="unavailable",
                message="This request may contain a secret. Edit the memory file manually instead.",
                request_kind="mutate",
            ).model_dump()

        candidates = self._candidates(task)
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
        hint = None
        exact_scopes = {
            str(row["scope"])
            for row in candidates
            if str(row["address"]) in task or str(row["path"]) in task
        }
        if len(exact_scopes) == 1:
            hint = next(iter(exact_scopes))
        safe_candidates = []
        planner_candidates = []
        blocked_targets: dict[str, str] = {}
        for row in candidates:
            body = str(row["markdown"])
            exact_target = str(row["address"]) in task or str(row["path"]) in task
            size_limit = (
                MAX_AI_EXACT_GENERATED_CHARS
                if exact_target and row.get("generated_section")
                else MAX_AI_FILE_CHARS
            )
            if len(body) > size_limit or redact_secrets(body) != body:
                reason = (
                    f"The complete target file exceeds {size_limit:,} characters."
                    if len(body) > size_limit
                    else "Secret redaction would change the complete target file."
                )
                blocked_targets[str(row["address"])] = reason
                planner_candidates.append({
                    **row,
                    "markdown": "",
                    "content_available": False,
                    "unavailable_reason": reason,
                })
                continue
            safe_candidates.append(row)
            planner_candidates.append({
                **row,
                "content_available": True,
                "unavailable_reason": None,
            })

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
                "Use scope_hint when present. Otherwise infer scope from the request and current "
                "targets. Ask one clarification only when both scopes remain materially plausible."
            ),
            "shared_memory_reference": {
                "definition": (
                    "Shared Memory is Docmancer's machine-wide canonical memory. It is the local "
                    "cross-agent view assembled from attributable evidence, user-approved pinned "
                    "notes, and durable machine-wide controls."
                ),
                "terminology": {
                    "same_product_surface": (
                        "Treat unambiguous natural-language references to machine-wide memory shared "
                        "across agents as references to Shared Memory."
                    ),
                    "not_the_same_thing": (
                        "Do not treat source repositories, agent-owned source memory, project-scoped "
                        "curated memory, the technical-documentation index, or chat history as Shared Memory."
                    ),
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
                        "Interpret language that asks for material to stop appearing in Shared Memory by "
                        "its semantic intent, not by matching a fixed vocabulary."
                    ),
                    (
                        "Lifecycle commentary strengthens an accompanying removal or exclusion request, "
                        "but never authorizes source deletion by itself."
                    ),
                    (
                        "When the user offers removal and unsupported ranking as alternatives and says the "
                        "subject is inactive or unused, choose the supported canonical exclusion. Do not "
                        "return a proposal without an operation."
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
                "output_requirements": [
                    "Classify the request as read, mutate, or mixed by meaning.",
                    "For read requests return outcome none and a self-contained read_question.",
                    "For mixed requests return a proposal and a self-contained read_question.",
                    "Return exactly one proposal, one necessary clarification, or none.",
                    "A proposal must always include exactly one supported operation.",
                    "Never invent an address, path, operation, or restore token.",
                    "Never convert a Shared Memory cleanup into source-file deletion.",
                    "Never treat approval language or lifecycle commentary by itself as authorization to apply an action.",
                ],
            },
            "rules": [
                "Return no action for a read-only request.",
                "Return exactly one action or one necessary clarification for a mutation request.",
                "Provide up to four focused retrieval queries for the read part of the request.",
                "scope_hint is authoritative when present; never ask the user to repeat that scope.",
                "Use only a supplied target_address for existing files.",
                (
                    "Generated sections permit pin only. A pin replaces the complete preserved "
                    "pinned zone and never replaces the generated evidence below it. If a request "
                    "asks to rewrite generated evidence, ask whether to add a concise pinned note instead."
                ),
                "For create, edit, or pin, markdown is the complete proposed body or complete pinned zone.",
                "Move and duplicate stay within one scope.",
                "Never interpret approval language by itself as an action.",
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
                    "content_available": row["content_available"],
                    "unavailable_reason": row["unavailable_reason"],
                }
                for row in planner_candidates
            ],
            "trash": self._trash_candidates(),
            "recent_conversation": list(history or [])[-6:],
            "canonical_exclusion_target": {
                "scope": "machine",
                "path": CANONICAL_EXCLUSIONS_PATH,
                "address": exclusion["address"] if exclusion is not None else None,
                "required_operation": "edit" if exclusion is not None else "create",
            },
        }
        try:
            draft = planner.parse(
                [
                    {
                        "role": "system",
                        "content": (
                            "Interpret the turn semantically. Separate its read and mutation parts, "
                            "then plan at most one safe Shared Memory file action under the supplied "
                            "constraints. Do not rely on fixed phrases or named cases. Do not ask for "
                            "information the request, conversation, or current targets already supply."
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
        request_kind = str(draft.request_kind or "read")
        read_question = str(draft.read_question or "").strip() or (
            task if request_kind in {"read", "mixed"} else None
        )
        retrieval_queries = []
        for query in draft.retrieval_queries:
            value = " ".join(str(query or "").split())
            if value and value not in retrieval_queries:
                retrieval_queries.append(value)
            if len(retrieval_queries) == 4:
                break
        if read_question and read_question not in retrieval_queries:
            retrieval_queries.insert(0, read_question)
            retrieval_queries = retrieval_queries[:4]
        routing = {
            "request_kind": request_kind,
            "read_question": read_question,
            "retrieval_queries": retrieval_queries,
        }
        if draft.outcome != "proposal":
            if draft.outcome == "none" and request_kind != "read":
                return ActionPlanningResult(
                    kind="unavailable",
                    message="Docmancer could not produce the requested memory change. Shared Memory is unchanged.",
                    provider=provider,
                    model=model,
                    **routing,
                ).model_dump()
            return ActionPlanningResult(
                kind="clarification" if draft.outcome == "clarification" else "none",
                message=draft.message or (
                    "Should this be saved machine-wide or only for the current project?"
                    if draft.outcome == "clarification"
                    else "No memory change was proposed."
                ),
                provider=provider,
                model=model,
                **routing,
            ).model_dump()
        if request_kind == "read":
            return ActionPlanningResult(
                kind="unavailable",
                message="Docmancer received an inconsistent action plan. Shared Memory is unchanged.",
                provider=provider,
                model=model,
                **routing,
            ).model_dump()
        target_block = blocked_targets.get(str(draft.target_address or ""))
        if target_block:
            return ActionPlanningResult(
                kind="unavailable",
                message=f"{target_block} Shared Memory is unchanged; use the manual editor.",
                provider=provider,
                model=model,
                **routing,
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
                    **routing,
                ).model_dump()
        canonical_forget = (
            draft.desired_visibility == "absent_from_generated_shared_memory"
        )
        if canonical_forget and not draft.preserve_source_evidence:
            return ActionPlanningResult(
                kind="unavailable",
                message=(
                    "Ask can remove material from generated Shared Memory, but it cannot delete "
                    "the underlying repositories or agent-owned evidence. Shared Memory is unchanged."
                ),
                provider=provider,
                model=model,
                **routing,
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
            if str(draft.markdown or "").strip():
                draft.markdown = _strengthen_canonical_exclusions(str(draft.markdown))
        try:
            proposal = self._validate_draft(draft, safe_candidates)
        except ValueError as exc:
            return ActionPlanningResult(
                kind="unavailable",
                message=f"Docmancer refused the proposed memory action: {exc}. Shared Memory is unchanged.",
                provider=provider,
                model=model,
                **routing,
            ).model_dump()
        proposal.update(id=new_action_id(), provider=provider, model=model)
        return ActionPlanningResult(
            kind="proposal",
            message=self._proposal_message(proposal),
            proposal=proposal,
            provider=provider,
            model=model,
            **routing,
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

    def _postcondition(
        self,
        proposal: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify the requested local state after the guarded operation completes."""
        operation = str(proposal["operation"])
        scope = str(proposal["scope"])
        store = self._store(scope)
        checks: list[dict[str, Any]] = []

        def check(name: str, passed: bool, detail: str = "") -> None:
            checks.append({"name": name, "passed": bool(passed), "detail": detail})

        try:
            if operation == "pin":
                section = str(proposal["section"])
                current = self._reconciler().read_section(section)
                expected = str(proposal["after_markdown"]).strip()
                check("pinned_zone_matches", str(current.get("pinned") or "").strip() == expected)
            elif operation == "trash":
                try:
                    store.read(str(proposal["address"]))
                except (AddressNotFoundError, FileNotFoundError, KeyError):
                    check("source_no_longer_active", True)
                else:
                    check("source_no_longer_active", False)
                check("restore_token_returned", bool(result.get("restore_token")))
            else:
                address = str(result.get("address") or proposal.get("address") or "")
                current = store.read(address)
                current_path = current.path.relative_to(store.root).as_posix()
                if operation in {"create", "edit", "duplicate", "restore"}:
                    expected_body = str(proposal.get("after_markdown") or "")
                    if operation in {"create", "edit"}:
                        check("file_body_matches", current.body == expected_body)
                    else:
                        check("file_is_readable", bool(current.body or current_path))
                if operation in {"move", "duplicate", "restore"}:
                    check("file_path_matches", current_path == str(result.get("path") or proposal.get("path") or ""))

            if scope == "machine" and str(proposal.get("path") or "") == CANONICAL_EXCLUSIONS_PATH:
                rules = parse_canonical_exclusions(str(proposal.get("after_markdown") or ""))
                previous_rules = parse_canonical_exclusions(
                    str(proposal.get("before_markdown") or "")
                )
                previous_text = {
                    value.casefold() for value in previous_rules["text_contains"]
                }
                requested_text = [
                    value for value in rules["text_contains"]
                    if value.casefold() not in previous_text
                ]
                surviving: list[str] = []
                for section, relative_path in CANONICAL_SECTION_PATHS.items():
                    if section == "canonical-memory":
                        continue
                    path = self.machine_store.root / relative_path
                    if not path.is_file():
                        continue
                    generated = split_zones(
                        parse_tree_file(path).body
                    ).generated.casefold()
                    for literal in requested_text:
                        if literal.casefold() in generated:
                            surviving.append(f"{relative_path}: {literal}")
                check(
                    "excluded_text_absent_from_generated_sections",
                    not surviving,
                    "; ".join(surviving),
                )
        except Exception as exc:  # noqa: BLE001 - verification must report, not hide, an applied write
            check("verification_completed", False, f"{type(exc).__name__}: {exc}")

        return {
            "status": "satisfied" if checks and all(row["passed"] for row in checks) else "not_satisfied",
            "checks": checks,
        }

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
            result["postcondition"] = self._postcondition(proposal, result)
            return result

        if operation == "pin":
            return finish(self._reconciler().set_pinned(
                str(proposal["section"]),
                str(proposal["after_markdown"]).rstrip(),
                expect=expected_hash,
            ))
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
            return finish({"address": entry.address, "path": path, "content_hash": entry.content_hash})
        if operation == "duplicate":
            entry = store.duplicate(
                address,
                _allowed_path(scope, path),
                expected_hash=expected_hash,
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return finish({"address": entry.address, "path": path, "content_hash": entry.content_hash})
        if operation == "trash":
            token = store.trash(
                address,
                expected_hash=expected_hash,
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return finish({"trashed": True, "restore_token": token, "path": path})
        if operation == "restore":
            entry = store.restore(
                str(proposal["restore_token"]),
                actor_surface=actor_surface,
                actor_harness=actor_harness,
            )
            return finish({
                "address": entry.address,
                "path": entry.path.relative_to(store.root).as_posix(),
                "content_hash": entry.content_hash,
            })
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
    "new_action_id",
]
