"""Release A canonical Markdown memory tree: production write path, stable
addressing, and Context Compiler v1.

This package is the production evolution of the Release 0 prototype at
``docmancer.memory.tree_prototype`` (see
``docs/memory-harness/2026-07-22-release-0-tree-prototype-evidence.md``).
The prototype validated the tree shape and file-first mechanics; this
package hardens that into the versioned contracts required by the Release A
checklist (frontmatter schema, addressing forms, mutation typed errors,
Context Compiler contract).

Clean-room note (plan section 2): every module here is independently
designed. No Basic Memory source was read, ported, translated, or adapted.

This package is additive: it does not modify or remove
``docmancer.memory.records`` (the current production record store) or any
currently-shipped CLI/MCP command. Existing surfaces keep working unchanged
while this package is developed, tested, and progressively wired in.
"""
from __future__ import annotations
