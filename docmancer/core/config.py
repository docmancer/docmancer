from __future__ import annotations

import warnings
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_user_db_path() -> str:
    return str(Path.home() / ".docmancer" / "docmancer.db")


class IndexConfig(BaseSettings):
    provider: str = "sqlite"
    db_path: str = Field(default_factory=default_user_db_path)
    extracted_dir: str = ""
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_INDEX_", extra="ignore")


class QueryConfig(BaseSettings):
    default_budget: int = Field(default=2400, ge=100)
    default_limit: int = Field(default=8, ge=1)
    default_expand: str = "adjacent"
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_QUERY_", extra="ignore")


class WebFetchConfig(BaseSettings):
    workers: int = Field(default=8, ge=1)
    default_page_cap: int = Field(default=500, ge=1)
    browser_fallback: bool = False
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_WEB_FETCH_", extra="ignore")


class LoaderFormatConfig(BaseModel):
    chunk_size: int | None = Field(default=None, ge=100)
    chunk_overlap: int | None = Field(default=None, ge=0)


class LoadersConfig(BaseModel):
    default_chunk_size: int = Field(default=800, ge=100)
    default_chunk_overlap: int = Field(default=100, ge=0)
    formats: dict[str, LoaderFormatConfig] = Field(default_factory=dict)

    def settings_for(self, format_name: str) -> tuple[int, int]:
        override = self.formats.get(format_name.lower())
        chunk_size = override.chunk_size if override and override.chunk_size is not None else self.default_chunk_size
        chunk_overlap = (
            override.chunk_overlap
            if override and override.chunk_overlap is not None
            else self.default_chunk_overlap
        )
        if chunk_overlap >= chunk_size:
            raise ValueError("loader chunk_overlap must be smaller than chunk_size")
        return chunk_size, chunk_overlap


class VectorStoreConfig(BaseSettings):
    provider: str = "sqlite-vec"
    url: str | None = None
    api_key_env: str | None = None
    collection: str | None = None
    options: dict = Field(default_factory=dict)
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_VECTOR_STORE_", extra="ignore")


class EmbeddingsConfig(BaseSettings):
    provider: str = "model2vec"
    model: str = "minishlab/potion-base-8M"
    dimensions: int = 256
    sparse_model: str | None = None
    cache: str = Field(default_factory=lambda: str(Path.home() / ".docmancer" / "embeddings-cache"))
    batch_size: int = 64
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_EMBEDDINGS_", extra="ignore")


class FusionConfig(BaseModel):
    method: str = "rrf"
    rrf_k: int = 60
    weights: dict[str, float] = Field(default_factory=dict)


class HierarchicalConfig(BaseModel):
    """Two-stage hierarchical retrieval: pick top documents, then top sections inside them.

    By default the dispatcher decides per-index: ``auto=True`` turns the
    two-stage pass on when the index contains at least
    ``auto_min_documents`` distinct ``document_title_hash`` values, and
    leaves it off on smaller / flatter corpora where the extra round-trip
    just costs latency. Set ``enabled=True`` to force it on regardless of
    corpus size; set ``auto=False`` to force it off unless ``enabled``
    is also true.
    """

    enabled: bool = False
    auto: bool = True
    auto_min_documents: int = Field(default=10, ge=1)
    documents_limit: int = Field(default=5, ge=1)
    candidate_pool: int = Field(default=200, ge=10)
    sections_per_document: int = Field(default=10, ge=1)


class QueryRouter(BaseModel):
    """A regex-matched query router.

    When ``match`` matches the query (case-insensitive), the router's
    ``filters`` are merged into the dispatcher filters for that call.
    The first matching router wins; routers do not stack.
    """

    match: str
    filters: dict = Field(default_factory=dict)
    description: str | None = None


class RetrievalConfig(BaseSettings):
    default_mode: str = "hybrid"
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    hierarchical: HierarchicalConfig = Field(default_factory=HierarchicalConfig)
    routers: list[QueryRouter] = Field(default_factory=list)
    expand: str | None = None
    budget: int | None = None
    limit: int | None = None
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_RETRIEVAL_", extra="ignore")


class DiscoveryExtraSource(BaseModel):
    """A user-declared custom memory source for harness discovery."""

    harness: str = "custom"
    path: str
    kind: str = "instructions"  # agent-memory | instructions | rules
    scope: str | None = None


class DiscoveryConfig(BaseSettings):
    """Tune memory-harness discovery without a new release.

    ``disabled`` turns off specific harnesses by name; ``extra_sources`` adds
    custom files or directories to harvest.
    """

    disabled: list[str] = Field(default_factory=list)
    extra_sources: list[DiscoveryExtraSource] = Field(default_factory=list)
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_DISCOVERY_", extra="ignore")


_LEGACY_VECTOR_STORE_FIELDS = {"db_path", "local_path"}
_NEW_VECTOR_STORE_FIELDS = {"provider", "url", "collection", "api_key_env", "options"}


class DocmancerConfig(BaseModel):
    index: IndexConfig = Field(default_factory=IndexConfig)
    query: QueryConfig = Field(default_factory=QueryConfig)
    web_fetch: WebFetchConfig = Field(default_factory=WebFetchConfig)
    loaders: LoadersConfig = Field(default_factory=LoadersConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

    @classmethod
    def from_yaml(cls, path: Path | str) -> DocmancerConfig:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        if "bench" in data:
            warnings.warn(
                "bench config is obsolete and has been removed; the key is ignored.",
                DeprecationWarning,
                stacklevel=2,
            )
            data.pop("bench", None)

        if "eval" in data:
            warnings.warn(
                "eval config is obsolete and has been removed; the key is ignored.",
                DeprecationWarning,
                stacklevel=2,
            )
            data.pop("eval", None)

        # Pre-0.5.0 used `embedding:` (singular). The new schema is plural
        # `embeddings:`. We do not migrate the value: the old block usually
        # pinned a smaller model (`bge-small-en-v1.5`) that defeats the
        # 0.5.0 default upgrade to `bge-base-en-v1.5`. Silently drop the
        # legacy block so the new defaults take effect.
        data.pop("embedding", None)

        if isinstance(data.get("vector_store"), dict):
            vector_store = data["vector_store"]

            # Pre-0.5.0 configs used `collection_name` for the Qdrant
            # collection name; the new schema uses `collection`. Rename
            # before legacy/new field detection so the rename does not
            # itself count as a legacy/new shape mix.
            if "collection_name" in vector_store and "collection" not in vector_store:
                vector_store["collection"] = vector_store.pop("collection_name")
            else:
                vector_store.pop("collection_name", None)

            present_keys = set(vector_store.keys())
            has_legacy = bool(present_keys & _LEGACY_VECTOR_STORE_FIELDS)
            has_new = bool(present_keys & _NEW_VECTOR_STORE_FIELDS)

            if has_legacy and has_new:
                # Forgiving migration: keep the new fields (provider, url,
                # collection, ...) and drop the legacy ones. The managed
                # Qdrant lifecycle owns its storage path under
                # `~/.docmancer/qdrant`; a user-supplied legacy `local_path`
                # is ignored. This used to be a hard error, but in practice
                # it strands anyone upgrading from a pre-0.5.0 install with
                # a leftover `~/.docmancer/docmancer.yaml`.
                warnings.warn(
                    "vector_store has both legacy fields (db_path/local_path) and new fields "
                    "(provider/url/collection/api_key_env/options); keeping the new fields and "
                    "dropping the legacy ones. Managed Qdrant ignores local_path; the binary "
                    "lives under ~/.docmancer/qdrant.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                vector_store.pop("db_path", None)
                vector_store.pop("local_path", None)
            elif has_legacy:
                warnings.warn(
                    "vector_store.db_path/local_path is deprecated; move SQLite paths to "
                    "index.db_path and use vector_store.provider for the new vector store.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                local_path = vector_store.pop("db_path", None) or vector_store.pop("local_path", None)
                if "index" not in data and local_path:
                    legacy_path = Path(str(local_path))
                    if legacy_path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                        data["index"] = {"db_path": local_path}
                    else:
                        data["index"] = {"db_path": ".docmancer/docmancer.db"}
                if not vector_store:
                    data.pop("vector_store", None)

        config = cls(**data)
        # Hybrid is now the class default (RetrievalConfig.default_mode), and
        # the dispatcher falls back to lexical when no vector store/provider is
        # available, so the old YAML auto-flip is redundant and was removed.
        db_path = Path(config.index.db_path)
        if not db_path.is_absolute():
            config.index.db_path = str((path.parent / db_path).resolve())

        extracted_dir = config.index.extracted_dir
        if extracted_dir:
            extracted_path = Path(extracted_dir)
            if not extracted_path.is_absolute():
                config.index.extracted_dir = str((path.parent / extracted_path).resolve())

        return config

    @classmethod
    def from_env(cls) -> DocmancerConfig:
        return cls()
