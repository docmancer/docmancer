from __future__ import annotations
from typing import Protocol, runtime_checkable
from docmancer.core.models import Document


@runtime_checkable
class Fetcher(Protocol):
    def fetch(self, url: str) -> list[Document]: ...
