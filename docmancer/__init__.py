"""docmancer: Fetch docs, index sections locally, and return compact context packs."""

from docmancer._version import __version__

__all__ = [
    "__version__",
    "AsyncDocmancerAgent",
    "DocmancerAgent",
    "DocmancerClient",
    "DocmancerConfig",
    "Chunk",
    "Document",
    "RetrievedChunk",
    "build_rag_prompt",
    "format_context",
]


def __getattr__(name: str):
    if name == "DocmancerAgent":
        from docmancer.agent import DocmancerAgent

        return DocmancerAgent
    if name == "AsyncDocmancerAgent":
        from docmancer.async_agent import AsyncDocmancerAgent

        return AsyncDocmancerAgent
    if name == "DocmancerClient":
        from docmancer.client import DocmancerClient

        return DocmancerClient
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
    if name == "format_context":
        from docmancer.context import format_context

        return format_context
    if name == "build_rag_prompt":
        from docmancer.context import build_rag_prompt

        return build_rag_prompt
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
