"""Document loader that extracts markdown from PDFs/images via Mistral OCR.

Opt-in: only used when ``docmancer ingest --ocr mistral`` is passed. Requires
``MISTRAL_API_KEY``. The default ingest path stays local and keyless.
"""
from __future__ import annotations

from pathlib import Path

from docmancer.core.models import Document


class MistralOCRLoader:
    supported_extensions = [".pdf", ".png", ".jpg", ".jpeg", ".webp"]
    chunking_strategy = "heading"

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    def load(self, path: Path) -> Document:
        from docmancer.ai.mistral_client import MistralClient

        client = MistralClient()
        markdown = client.ocr_file(path, model=self._model)
        return Document(
            source=str(path),
            content=markdown,
            metadata={"format": "markdown", "ocr": "mistral", "title": path.stem},
        )


__all__ = ["MistralOCRLoader"]
