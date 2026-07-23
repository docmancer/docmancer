"""Stable ``docmancer://memory/<id>`` addressing (checklist A.3).

Resolves stable IDs, permalinks (alias for stable ID in v1 -- there is no
separate short-permalink scheme yet), paths, and titles to a
``TreeMemoryFile``. Ambiguous title/path resolution returns a typed error
with every candidate address rather than guessing.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from urllib.parse import unquote

from docmancer.memory.tree.contracts import ADDRESS_PREFIX
from docmancer.memory.tree.errors import (
    AddressNotFoundError,
    AmbiguousAddressError,
    ForbiddenPathError,
)
from docmancer.memory.tree.parser import TreeMemoryFile, parse_tree_file


class AddressIndex:
    """A disposable id->path cache over one root. Fully rebuildable from files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._by_id: dict[str, Path] = {}

    def resolve_target(self, relative_path: str | Path) -> Path:
        """Resolve a caller-supplied relative path inside ``root``. Never
        accepts a path that escapes the root, even via ``..`` or a symlink."""
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ForbiddenPathError(str(relative_path))
        return candidate

    def drop(self) -> None:
        """Simulate deleting the disposable index. Files on disk are untouched."""
        self._by_id = {}

    def rebuild(self) -> int:
        """Rebuild purely from files on disk. No canonical state is touched."""
        self._by_id = {}
        count = 0
        if not self.root.is_dir():
            return 0
        for path in sorted(self.root.rglob("*.md")):
            entry = parse_tree_file(path)
            if entry is not None:
                self._by_id[entry.memory_id] = path
                count += 1
        return count

    def note_write(self, entry: TreeMemoryFile) -> None:
        self._by_id[entry.memory_id] = entry.path

    def note_move(self, memory_id: str, new_path: Path) -> None:
        self._by_id[memory_id] = new_path

    def note_delete(self, memory_id: str) -> None:
        self._by_id.pop(memory_id, None)

    def entries(self) -> list[TreeMemoryFile]:
        if not self._by_id:
            self.rebuild()
        out = []
        for path in self._by_id.values():
            entry = parse_tree_file(path)
            if entry is not None:
                out.append(entry)
        return out

    def by_id(self, memory_id: str) -> TreeMemoryFile | None:
        if not self._by_id:
            self.rebuild()
        path = self._by_id.get(memory_id)
        if path is None or not path.is_file():
            return None
        return parse_tree_file(path)

    def read(self, address: str) -> TreeMemoryFile:
        """Resolve a stable-ID, path, or title address. Ambiguous title/path
        matches raise AmbiguousAddressError with every candidate address."""
        if address.startswith(ADDRESS_PREFIX):
            target_id = address[len(ADDRESS_PREFIX):]
            entry = self.by_id(target_id)
            if entry is None:
                raise AddressNotFoundError(address)
            return entry

        if address.startswith("docmancer://project/"):
            remainder = address[len("docmancer://project/"):]
            project_id, separator, target = remainder.partition("/")
            if not separator or not project_id or not target:
                raise AddressNotFoundError(address)
            matches = [
                entry
                for entry in self._resolve_convenience(unquote(target))
                if entry.project_id == unquote(project_id)
            ]
            return self._one(address, matches)

        if address.startswith("docmancer://path/"):
            return self._one(address, self._path_matches(unquote(address[len("docmancer://path/"):])))

        if address.startswith("docmancer://title/"):
            title = unquote(address[len("docmancer://title/"):])
            return self._one(address, [entry for entry in self.entries() if entry.title == title])

        if address.startswith("docmancer://search/"):
            pattern = unquote(address[len("docmancer://search/"):])
            return self._one(address, self._wildcard_matches(pattern))

        try:
            as_path = self.resolve_target(address)
        except ForbiddenPathError:
            as_path = None
        if as_path is not None and as_path.is_file():
            entry = parse_tree_file(as_path)
            if entry is not None:
                return entry

        return self._one(address, [entry for entry in self.entries() if entry.title == address])

    def _one(self, address: str, matches: list[TreeMemoryFile]) -> TreeMemoryFile:
        if not matches:
            raise AddressNotFoundError(address)
        if len(matches) > 1:
            raise AmbiguousAddressError(address, [entry.address for entry in matches[:50]])
        return matches[0]

    def _path_matches(self, path_text: str) -> list[TreeMemoryFile]:
        normalized = path_text.strip("/")
        candidates = {normalized}
        if normalized and not normalized.endswith(".md"):
            candidates.add(f"{normalized}.md")
        matches: list[TreeMemoryFile] = []
        for entry in self.entries():
            try:
                relative = entry.path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if relative in candidates or relative.removesuffix(".md") in candidates:
                matches.append(entry)
        return matches

    def _resolve_convenience(self, target: str) -> list[TreeMemoryFile]:
        path_matches = self._path_matches(target)
        if path_matches:
            return path_matches
        return [entry for entry in self.entries() if entry.title == target]

    def _wildcard_matches(self, pattern: str) -> list[TreeMemoryFile]:
        pattern = pattern.strip("/")
        if not pattern or len(pattern) > 256 or pattern.count("*") > 4 or "**" in pattern:
            return []
        matches: list[TreeMemoryFile] = []
        for entry in sorted(self.entries(), key=lambda item: item.address):
            try:
                relative = entry.path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            path_without_suffix = relative.removesuffix(".md")
            if fnmatch.fnmatchcase(path_without_suffix, pattern) or fnmatch.fnmatchcase(entry.title, pattern):
                matches.append(entry)
                if len(matches) >= 51:
                    break
        return matches
