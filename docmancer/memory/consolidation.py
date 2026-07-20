"""Shared provider-backed memory consolidation orchestration.

CLI, MCP, and TUI callers supply presentation callbacks. This module owns
batching and map-reduce flow and never writes a draft or changes memory.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable


Progress = Callable[[str, dict], None]


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _entry_tokens(entry: dict) -> int:
    header = f"scope:{entry.get('scope', '')}\ntitle:{entry.get('title', '')}\nsource:{entry.get('source_path', '')}\n"
    return _estimate_tokens(header) + _estimate_tokens(str(entry.get("text") or ""))


def chunk_payload(payload: list[dict], budget: int | None) -> tuple[list[list[dict]], dict]:
    expanded: list[dict] = []
    split_entries = 0
    for entry in payload:
        if not budget or budget <= 0 or _entry_tokens(entry) <= budget:
            expanded.append(entry)
            continue
        overhead = _entry_tokens({**entry, "text": ""})
        max_chars = max(1, (budget - overhead) * 4)
        text = str(entry.get("text") or "")
        parts = [text[index : index + max_chars] for index in range(0, len(text), max_chars)] or [""]
        split_entries += 1
        for index, part in enumerate(parts, start=1):
            expanded.append({**entry, "title": f"{entry.get('title', '')} (part {index}/{len(parts)})", "text": part})
    batches: list[list[dict]] = []
    current: list[dict] = []
    tokens = 0
    request_tokens: list[int] = []
    for entry in expanded:
        entry_tokens = _entry_tokens(entry)
        if budget and budget > 0 and current and tokens + entry_tokens > budget:
            batches.append(current)
            request_tokens.append(tokens)
            current, tokens = [], 0
        current.append(entry)
        tokens += entry_tokens
    if current:
        batches.append(current)
        request_tokens.append(tokens)
    return batches, {
        "original_tokens": sum(_entry_tokens(entry) for entry in payload),
        "request_tokens": request_tokens,
        "split_entries": split_entries,
        "expanded_entries": len(expanded),
    }


def consolidate_payload(
    payload: list[dict],
    *,
    instruction: str | None,
    client,
    model: str | None,
    budget: int | None,
    draft_quality: str,
    max_output_tokens: int | None,
    concurrency: int,
    on_event: Progress | None = None,
):
    """Map-reduce every selected entry into one review-only draft."""
    from docmancer.ai.memory_features import consolidate_memory, draft_to_merge_text

    emit = on_event or (lambda _name, _data: None)
    current = payload
    current_instruction = instruction
    for round_no in range(1, 7):
        chunks, stats = chunk_payload(current, budget)
        emit("plan", {"round": round_no, "chunks": len(chunks), **stats})
        if len(chunks) == 1:
            emit("request", {"round": round_no, "batch": 1, "batches": 1})
            return consolidate_memory(
                entries=chunks[0], instruction=current_instruction, client=client, model=model,
                draft_quality=draft_quality, max_tokens=max_output_tokens,
                on_progress=lambda chars: emit("stream", {"round": round_no, "batch": 1, "chars": chars}),
            )

        def run_batch(index: int, chunk: list[dict]):
            emit("request", {"round": round_no, "batch": index, "batches": len(chunks)})
            draft = consolidate_memory(
                entries=chunk,
                instruction=(
                    f"{current_instruction or 'Consolidate these into a coherent master memory draft.'}\n\n"
                    f"This is batch {index} of {len(chunks)} in round {round_no}. Preserve every unique durable detail."
                ),
                client=client,
                model=model,
                draft_quality=draft_quality,
                max_tokens=max_output_tokens,
                on_progress=lambda chars: emit("stream", {"round": round_no, "batch": index, "chars": chars}),
            )
            sources = list(dict.fromkeys(str(entry.get("source_path") or "") for entry in chunk if entry.get("source_path")))
            draft.source_paths = list(dict.fromkeys([*draft.source_paths, *sources]))
            return index, {
                "scope": "docmancer-consolidation",
                "title": f"Round {round_no} batch {index} consolidated draft",
                "source_path": f"docmancer://memory-consolidate/round-{round_no}/batch-{index}",
                "text": draft_to_merge_text(draft, source_files=sources, max_chars=80_000),
            }

        workers = max(1, min(concurrency, len(chunks)))
        results: dict[int, dict] = {}
        if workers == 1:
            for index, chunk in enumerate(chunks, start=1):
                key, value = run_batch(index, chunk)
                results[key] = value
                emit("complete", {"round": round_no, "batch": key, "batches": len(chunks)})
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(run_batch, index, chunk) for index, chunk in enumerate(chunks, start=1)]
                for future in as_completed(futures):
                    key, value = future.result()
                    results[key] = value
                    emit("complete", {"round": round_no, "batch": key, "batches": len(chunks)})
        current = [results[index] for index in range(1, len(chunks) + 1)]
        current_instruction = (
            "Merge these batch drafts into one review-only master memory draft. Preserve all unique facts, "
            "conflicts, warnings, and original source paths while removing exact repetition."
        )
    raise RuntimeError("consolidation exceeded six merge rounds; increase the budget or narrow the selection")


__all__ = ["chunk_payload", "consolidate_payload"]
