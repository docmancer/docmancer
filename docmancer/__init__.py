"""docmancer: Fetch docs, index sections locally, and return compact context packs."""

from docmancer._version import __version__

__all__ = [
    "__version__",
    "DocmancerAgent",
    "DocmancerConfig",
    "Chunk",
    "Document",
    "RetrievedChunk",
]


def __getattr__(name: str):
    if name == "DocmancerAgent":
        from docmancer.agent import DocmancerAgent

        return DocmancerAgent
    if name == "DocmancerConfig":
        from docmancer.core.config import DocmancerConfig

        return DocmancerConfig
    if name in {"Chunk", "Document", "RetrievedChunk"}:
        from docmancer.core.models import Chunk, Document, RetrievedChunk

        return {
            "Chunk": Chunk,
            "Document": Document,
            "RetrievedChunk": RetrievedChunk,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
