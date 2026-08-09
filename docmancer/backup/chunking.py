"""Content-defined chunking and versioned Zstandard compression."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator


MIN_CHUNK = 256 * 1024
AVG_CHUNK = 4 * 1024 * 1024
MAX_CHUNK = 4 * 1024 * 1024
CHUNKER_ID = "jsonl-lines-v2-256k-4m-4m"
DICTIONARY_VERSION = "agent-jsonl-static-v2"

# This is a shipped raw-content dictionary, not a dictionary trained by the
# installed libzstd. Keeping the bytes in source makes archives portable across
# libzstd versions and lets restore select the exact format version recorded in
# the encrypted manifest.
_DICTIONARY_BYTES = (
    b'{"type":"message","agent":"claude-code","role":"user","assistant":'
    b'"tool","cwd":"/Users/example/project","timestamp":"2026-01-01T00:00:00Z",'
    b'"content":"[DOCMANCER_REDACTED]","metadata":{"session_id":"00000000-0000-'
    b'4000-8000-000000000000","tool":"shell"}}\n'
    b'{"type":"response_item","payload":{"type":"message","role":"assistant",'
    b'"content":[{"type":"output_text","text":"decision constraint workflow lesson"}]}}\n'
    b'project instructions skills hooks mcp_servers command args environment memory '
    b'session rollout summary decision reason verification source evidence restore backup'
)
_DICTIONARY_ID = DICTIONARY_VERSION + ":" + hashlib.sha256(_DICTIONARY_BYTES).hexdigest()[:16]

def iter_content_defined_chunks(path: Path) -> Iterator[bytes]:
    """Chunk transcript-oriented files without a Python per-byte hot loop.

    JSONL record boundaries are stable when records are inserted or removed,
    which is the useful content boundary for the supported corpus. Extremely
    large records and binary attachments fall back to bounded fixed slices.
    """
    buffer = bytearray()
    record_count = 0
    record_mask = (1 << 16) - 1
    with path.open("rb") as handle:
        while True:
            record = handle.readline(MAX_CHUNK)
            if not record:
                break
            if buffer and len(buffer) + len(record) > MAX_CHUNK:
                yield bytes(buffer)
                buffer.clear()
                record_count = 0
            buffer.extend(record)
            record_count += 1
            record_hash = int.from_bytes(hashlib.sha256(record).digest()[:8], "big")
            if len(buffer) >= MIN_CHUNK and (
                (record_hash & record_mask) == 0
                or record_count >= 32_768
                or len(buffer) >= MAX_CHUNK
            ):
                yield bytes(buffer)
                buffer.clear()
                record_count = 0
    if buffer:
        yield bytes(buffer)


def shared_dictionary(dictionary: str | None = None):
    import zstandard as zstd
    selected = dictionary or _DICTIONARY_ID
    if selected != _DICTIONARY_ID:
        raise ValueError(f"unsupported backup compression dictionary: {selected}")
    return zstd.ZstdCompressionDict(_DICTIONARY_BYTES, dict_type=zstd.DICT_TYPE_RAWCONTENT)


def dictionary_id() -> str:
    return _DICTIONARY_ID


def compress(data: bytes) -> bytes:
    import zstandard as zstd

    return zstd.ZstdCompressor(level=7, dict_data=shared_dictionary()).compress(data)


def decompress(data: bytes, *, dictionary: str) -> bytes:
    import zstandard as zstd
    try:
        return zstd.ZstdDecompressor(dict_data=shared_dictionary(dictionary)).decompress(data)
    except zstd.ZstdError as exc:
        raise ValueError(f"backup chunk cannot be decoded with dictionary {dictionary}") from exc


__all__ = [
    "AVG_CHUNK", "CHUNKER_ID", "DICTIONARY_VERSION", "MAX_CHUNK", "MIN_CHUNK",
    "compress", "decompress", "dictionary_id", "iter_content_defined_chunks",
]
