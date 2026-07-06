"""Pydantic schemas for cloud structured-output memory features.

These are passed as ``response_format`` to ``client.chat.parse(...)`` so the
model returns a validated instance, never free-form JSON we have to parse.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedMemoryFact(BaseModel):
    subject: str = Field(description="What the fact is about (project, tool, decision).")
    fact: str = Field(description="The durable fact, stated plainly.")
    evidence: str = Field(description="Short quote or paraphrase supporting the fact.")
    confidence: Literal["low", "medium", "high"]
    source_path: str | None = None


class ExtractedMemoryFacts(BaseModel):
    facts: list[ExtractedMemoryFact] = Field(default_factory=list)


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
    "ExtractedMemoryFact",
    "ExtractedMemoryFacts",
    "ConsolidatedMemorySection",
    "ConsolidatedMemoryDraft",
]
