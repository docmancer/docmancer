# Architecture

## How Docmancer Fixes Hallucinations

**Chunk and embed locally.** Docmancer splits docs into 800-token chunks and embeds them with FastEmbed, fully on your machine. No embedding API costs, no data leaving your system.

**Hybrid retrieval.** Queries run dense + sparse (BM25) retrieval in parallel and merge results with reciprocal rank fusion. Dense vectors catch semantic meaning; BM25 catches exact terms like flag names, error codes, and method signatures.

**Return only what matches.** A query returns 5 chunks by default (a few hundred tokens). The whole site stays indexed; only the relevant slice lands in context.

**Concurrent-safe.** Multiple CLI calls from parallel agents or different terminals are serialized with a file lock. No corruption.

## Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DOCMANCER FLOW                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  INGEST                 INDEX                      RETRIEVE              │
│  ┌────────────┐         ┌────────────┐         ┌──────────────────────┐  │
│  │ GitBook    │         │ Chunk text │         │ docmancer query      │  │
│  │ Mintlify   │   ─►    │ FastEmbed  │   ─►    │ e.g. how to auth?    │  │
│  │ Web docs   │         │ vectors on │         │                      │  │
│  │ Local docs │         │ disk Qdrant│         │ → top matching       │  │
│  │ .md / .txt │         │            │         │   chunks only        │  │
│  └────────────┘         └────────────┘         │                      │  │
│       │                       ▲                └──────────────────────┘  │
│       └───────────────────────┴── dense + sparse (BM25); file lock       │
│                                                                          │
│  SKILL INSTALL                           AGENT                           │
│  ┌──────────────────────────┐            ┌──────────────────────────┐    │
│  │ docmancer install        │            │ Claude Code, Cursor,     │    │
│  │ claude-code, cursor, …   │    ─►      │ Codex, … run the CLI     │    │
│  └──────────────────────────┘            │ via installed SKILL.md   │    │
│                                          └──────────────────────────┘    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

1. **`docmancer ingest`:** fetches docs from GitBook, Mintlify, generic web docs, or local files. Chunks and embeds them locally with FastEmbed. Stores vectors in on-disk Qdrant.
2. **`docmancer install`:** drops a `SKILL.md` into your agent's skills directory. The skill teaches the agent when and how to call the CLI.
3. **Agent queries automatically:** when your agent needs docs, it runs `docmancer query` and gets back only the relevant chunks.
