"""Registry for bench backend adapters."""

from __future__ import annotations

from typing import Callable

from docmancer.bench.backends.base import BenchBackend


_REGISTRY: dict[str, Callable[[], BenchBackend]] = {}


def register(name: str, factory: Callable[[], BenchBackend]) -> None:
    _REGISTRY[name] = factory


def available() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_backend(name: str) -> BenchBackend:
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown bench backend: {name!r}. Available: {', '.join(available()) or 'none'}."
        )
    return _REGISTRY[name]()


def _register_builtins() -> None:
    from docmancer.bench.backends.fts import FTSBackend

    register("fts", FTSBackend)

    def _qdrant_factory():
        from docmancer.bench.backends.qdrant import QdrantBackend

        return QdrantBackend()

    def _rlm_factory():
        from docmancer.bench.backends.rlm import RLMBackend

        return RLMBackend()

    register("qdrant", _qdrant_factory)
    register("rlm", _rlm_factory)


_register_builtins()
