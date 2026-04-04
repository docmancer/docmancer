from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Span:
    name: str
    start_time: float = field(default_factory=time.perf_counter)
    end_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def stop(self) -> None:
        self.end_time = time.perf_counter()

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "metadata": self.metadata,
        }


@dataclass
class QueryTrace:
    query_text: str
    spans: list[Span] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def start_span(self, name: str, **metadata: Any) -> Span:
        span = Span(name=name, metadata=metadata)
        self.spans.append(span)
        return span

    @property
    def total_duration_ms(self) -> float:
        return sum(s.duration_ms for s in self.spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query_text,
            "timestamp": self.timestamp,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "spans": [s.to_dict() for s in self.spans],
            "results": self.results,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def save(self, traces_dir: Path) -> Path:
        traces_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        path = traces_dir / f"trace_{ts}.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path


def format_trace_for_terminal(trace: QueryTrace) -> str:
    lines = [
        f"Query: {trace.query_text}",
        f"Total: {trace.total_duration_ms:.1f}ms",
        "",
        "Spans:",
    ]
    for span in trace.spans:
        lines.append(f"  {span.name}: {span.duration_ms:.1f}ms")
        for k, v in span.metadata.items():
            lines.append(f"    {k}: {v}")
    if trace.results:
        lines.append("")
        lines.append(f"Results ({len(trace.results)}):")
        for i, r in enumerate(trace.results):
            source = r.get("source", "?")
            score = r.get("score", 0)
            text_preview = r.get("text", "")[:80]
            lines.append(f"  [{i+1}] score={score:.4f} source={source}")
            lines.append(f"      {text_preview}...")
    return "\n".join(lines)
