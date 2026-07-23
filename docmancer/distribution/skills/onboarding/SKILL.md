---
name: docmancer-onboarding
description: Set up machine-wide agent memory and open the local project workbench.
---

# Onboard Docmancer

1. Run `docmancer setup` once on the machine.
2. Change to the project and run `docmancer web`. The workbench safely creates or adopts the project tree and refreshes changed agent sources.
3. Run `docmancer status` to inspect local health.
4. Use `docmancer import <path>` only when the user asks to copy arbitrary Markdown into the project inbox.

Onboarding does not enable capture hooks, connect Cloud, publish Team memory, or rewrite existing memory files.
