"""Project-root resolution and explicit curated-tree initialization."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_DENIED_ROOT_PARTS = {".ssh", ".aws", ".gnupg", "credentials", "wallet", "wallets", "keychain"}
PROJECT_SCAFFOLD_FOLDERS = (
    "decisions",
    "constraints",
    "workflows",
    "lessons",
)


def _validate_state_root(path: Path) -> None:
    lowered = [part.casefold() for part in path.resolve().parts]
    if any(part in _DENIED_ROOT_PARTS or part == ".env" or part.startswith(".env.") for part in lowered):
        raise ValueError("refusing to create or adopt a Docmancer tree inside a sensitive or denied root")


@dataclass(frozen=True)
class ProjectTree:
    project_root: Path
    tree_root: Path
    inbox_root: Path
    trash_root: Path
    context_path: Path
    created: bool
    adopted: bool


def resolve_project_root(project_path: str | Path | None = None) -> Path:
    """Resolve the project that owns local Docmancer state.

    An explicit path is authoritative. Otherwise, walk upward from the
    current directory and prefer an existing Git or Docmancer project marker.
    If neither exists, the current directory is the project root.
    """
    if project_path is not None:
        return Path(project_path).expanduser().resolve()
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / ".docmancer").exists():
            return candidate
    return current


def tree_paths(project_path: str | Path | None = None) -> tuple[Path, Path, Path]:
    project = resolve_project_root(project_path)
    state = project / ".docmancer"
    return state / "tree", state / "inbox", state / "trash"


def ensure_project(
    project_path: str | Path | None = None,
    *,
    project_id: str | None = None,
    tree_root: str | Path | None = None,
) -> ProjectTree:
    """Create or safely adopt one project's local curated-memory tree.

    Existing Markdown is validated before any context file is added. No hooks
    are installed and no existing file is rewritten.
    """
    from docmancer.memory.tree.parser import parse_tree_file
    from docmancer.memory.tree.store import TreeStore

    project = resolve_project_root(project_path)
    if tree_root is None:
        resolved_tree, inbox_root, trash_root = tree_paths(project)
    else:
        resolved_tree = Path(tree_root).expanduser().resolve()
        inbox_root = resolved_tree.parent / "inbox"
        trash_root = resolved_tree.parent / "trash"
    _validate_state_root(resolved_tree)
    existing_files = sorted(resolved_tree.rglob("*.md")) if resolved_tree.is_dir() else []
    malformed: list[str] = []
    for path in existing_files:
        try:
            if parse_tree_file(path) is None:
                malformed.append(str(path))
        except Exception:  # noqa: BLE001 - report all malformed files together
            malformed.append(str(path))
    if malformed:
        raise ValueError(
            "cannot adopt this tree because Markdown memory files have invalid frontmatter: "
            + ", ".join(malformed[:10])
        )

    existed = resolved_tree.exists()
    resolved_tree.mkdir(parents=True, exist_ok=True)
    inbox_root.mkdir(parents=True, exist_ok=True)
    trash_root.mkdir(parents=True, exist_ok=True)
    for folder in PROJECT_SCAFFOLD_FOLDERS:
        (resolved_tree / folder).mkdir(parents=True, exist_ok=True)
    context_path = resolved_tree / "overview.md"
    if not context_path.exists():
        TreeStore(resolved_tree).write(
            relative_path="overview.md",
            text=(
                "# Project memory\n\n"
                "Durable project decisions, constraints, workflows, and lessons live here.\n"
            ),
            memory_type="fact",
            scope="project",
            project_id=project_id,
            tags=["docmancer-scaffold"],
            curation_origin="deterministic_curation",
            expect="absent",
        )
    return ProjectTree(
        project_root=project,
        tree_root=resolved_tree,
        inbox_root=inbox_root,
        trash_root=trash_root,
        context_path=context_path,
        created=not existed,
        adopted=bool(existing_files),
    )


__all__ = [
    "PROJECT_SCAFFOLD_FOLDERS",
    "ProjectTree",
    "ensure_project",
    "resolve_project_root",
    "tree_paths",
]
