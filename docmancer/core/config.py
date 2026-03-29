from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingConfig(BaseSettings):
    provider: str = "fastembed"
    model: str = "BAAI/bge-small-en-v1.5"
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore")


class VectorStoreConfig(BaseSettings):
    provider: str = "qdrant"
    url: str = ""
    collection_name: str = "knowledge_base"
    local_path: str = ".docmancer/qdrant"
    retrieval_limit: int = 5
    score_threshold: float = 0.35
    dense_prefetch_limit: int = 20
    sparse_prefetch_limit: int = 20
    model_config = SettingsConfigDict(env_prefix="VECTOR_STORE_", extra="ignore")

    @property
    def use_local(self) -> bool:
        return not bool(self.url)


class IngestionConfig(BaseSettings):
    chunk_size: int = 800
    chunk_overlap: int = 120
    bm25_model: str = "Qdrant/bm25"
    model_config = SettingsConfigDict(env_prefix="INGESTION_", extra="ignore")


class DocmancerConfig(BaseModel):
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)

    @classmethod
    def from_yaml(cls, path: Path | str) -> DocmancerConfig:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        config = cls(**data)
        # Resolve a relative local_path against the YAML file's directory so the
        # vector store is always found regardless of the process's working directory.
        local_path = Path(config.vector_store.local_path)
        if not local_path.is_absolute():
            config.vector_store.local_path = str((path.parent / local_path).resolve())
        return config

    @classmethod
    def from_env(cls) -> DocmancerConfig:
        return cls()
