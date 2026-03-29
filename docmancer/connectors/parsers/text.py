from __future__ import annotations
from pathlib import Path
from docmancer.core.models import Document

class TextLoader:
    supported_extensions = [".txt"]
    def load(self, path: Path) -> Document:
        return Document(source=str(path), content=path.read_text(encoding="utf-8"))
