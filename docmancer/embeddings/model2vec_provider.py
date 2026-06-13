"""Static (Model2Vec / Potion) embeddings provider.

Default model is potion-base-8M (256-dim, ~8 MB), vendored in the package and
loaded locally so the default path needs no network at runtime. If the
vendored copy is absent (a dev checkout before the build asset is fetched), we
fall back to a one-time download by name. The optional potion-retrieval-32M
(512-dim) can be selected via config; it is download-only because it exceeds
PyPI's per-file size limit.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import EmbeddingsCache, EmbeddingsProvider

if TYPE_CHECKING:
    from docmancer.core.config import EmbeddingsConfig

logger = logging.getLogger(__name__)

_DEFAULT_NAME = "minishlab/potion-base-8M"
_VENDORED_DIRNAME = "potion-base-8M"


def vendored_model_dir() -> Path:
    """Path to the build-time vendored model dir inside the package tree."""
    return Path(__file__).resolve().parent.parent / "_models" / _VENDORED_DIRNAME


class Model2VecProvider(EmbeddingsProvider):
    """Local static embeddings via Model2Vec (Potion).

    Construction is cheap and never loads the model; the model is loaded
    lazily on first ``embed``/``embed_query``/``_ensure_dense`` call.
    """

    name = "model2vec"

    def __init__(self, config: "EmbeddingsConfig") -> None:
        self._config = config
        self.model_name = config.model or _DEFAULT_NAME
        # Treat the config dimension as a hint only; the real dimension comes
        # from probing the loaded model so the vec0 collection is sized from
        # reality (256 for base-8M, 512 for retrieval-32M).
        self.dimensions = int(config.dimensions or 256)
        self._dimensions_resolved = False
        self.max_batch_size = int(getattr(config, "batch_size", 256) or 256)
        self._model: Any | None = None
        self.cache = EmbeddingsCache(config.cache)

    def _ensure_model(self) -> Any:
        if self._model is None:
            try:
                from model2vec import StaticModel  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "model2vec is required for the default embeddings provider; "
                    "reinstall docmancer; this dependency ships in core."
                ) from exc
            vendored = vendored_model_dir()
            # Use the vendored copy only when the configured model IS the
            # vendored default; a user who selected retrieval-32M must download it.
            if self.model_name == _DEFAULT_NAME and vendored.is_dir() and any(vendored.iterdir()):
                self._model = StaticModel.from_pretrained(str(vendored))
            else:
                logger.info("loading static model %s (download if not cached)", self.model_name)
                self._model = StaticModel.from_pretrained(self.model_name)
            self._resolve_dimension(self._model)
        return self._model

    # Alias so embeddings/pipeline.py:sync_vector_store resolves the true
    # dimension (via provider.dimensions) before creating the vec0 collection.
    # Without this the collection would be sized from the config hint.
    def _ensure_dense(self) -> Any:
        return self._ensure_model()

    def _resolve_dimension(self, model: Any) -> None:
        if self._dimensions_resolved:
            return
        try:
            arr = model.encode(["dim-probe"])
            resolved = int(arr.shape[1]) if hasattr(arr, "shape") else int(len(list(arr)[0]))
            if resolved > 0:
                self.dimensions = resolved
        except Exception:
            pass
        self._dimensions_resolved = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        arr = model.encode(list(texts), batch_size=self.max_batch_size)
        return [[float(x) for x in row] for row in arr]

    def embed_query(self, query: str) -> list[float]:
        return self.embed([query])[0]

    def health_check(self) -> bool:
        try:
            self._ensure_model()
            return True
        except Exception:
            return False


__all__ = ["Model2VecProvider", "vendored_model_dir"]
