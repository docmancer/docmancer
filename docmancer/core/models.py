from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class Document(BaseModel):
    """A loaded document before chunking."""
    source: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A chunk of text after splitting a document."""
    text: str
    source: str
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    """A section returned from the local docs index with a relevance score."""
    source: str
    chunk_index: int
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
