"""Pydantic schemas for cloud structured-output memory features.

These are passed as ``response_format`` to ``client.chat.parse(...)`` so the
model returns a validated instance, never free-form JSON we have to parse.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ConsolidatedMemorySection(BaseModel):
    heading: str
    body: str


class ConsolidatedMemoryDraft(BaseModel):
    title: str
    summary: str
    sections: list[ConsolidatedMemorySection] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "ConsolidatedMemorySection",
    "ConsolidatedMemoryDraft",
]
