from __future__ import annotations
from pathlib import Path
from typing import Protocol
from docmancer.core.models import Document

class DocumentLoader(Protocol):
    supported_extensions: list[str]
    def load(self, path: Path) -> Document: ...
