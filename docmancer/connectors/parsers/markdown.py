from __future__ import annotations
from pathlib import Path
import re
import yaml

from docmancer.core.models import Document


_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class MarkdownLoader:
    supported_extensions = [".md"]
    chunking_strategy = "heading"

    def load(self, path: Path) -> Document:
        content = path.read_text(encoding="utf-8")
        title = path.stem
        metadata: dict = {"format": "markdown"}
        match = _FRONT_MATTER_RE.match(content)
        if match:
            try:
                front_matter = yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                front_matter = {}
            if isinstance(front_matter, dict):
                if front_matter.get("title"):
                    title = str(front_matter["title"])
                # Lift OKF frontmatter into queryable metadata. ``type`` is
                # stored as ``okf_type`` to avoid colliding with internal keys.
                if front_matter.get("type"):
                    metadata["okf_type"] = front_matter["type"]
                for key in ("tags", "resource", "timestamp"):
                    if front_matter.get(key) is not None:
                        metadata[key] = front_matter[key]
        metadata["title"] = title
        return Document(source=str(path), content=content, metadata=metadata)
