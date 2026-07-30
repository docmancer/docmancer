# Security Policy

## Supported versions

Security fixes land on the latest published release of the `docmancer` package. Please upgrade before reporting an issue:

```bash
pipx upgrade docmancer
docmancer doctor
```

| Version | Supported |
| --- | --- |
| Latest release on PyPI | Yes |
| Older releases | No |

## Reporting a vulnerability

Please do not open a public GitHub issue for a security problem.

Report privately through GitHub's [security advisory form](https://github.com/docmancer/docmancer/security/advisories/new), or email **security@docmancer.dev**.

Include as much of the following as you can:

- The version reported by `docmancer --version` and your operating system.
- What an attacker can do, and what access they need to start.
- Steps to reproduce, ideally with a minimal command sequence.
- Any logs or output, with your own memory content and credentials removed.

## What to expect

- We aim to acknowledge a report within three working days.
- We will tell you whether we consider the report in scope, and why.
- We will agree a disclosure timeline with you before publishing anything.
- We are happy to credit you in the advisory and the changelog unless you prefer otherwise.

## Scope

In scope:

- The `docmancer` Python package and its CLI.
- The packaged MCP server.
- The local web app served by `docmancer web`, including its loopback bindings, session handling, and browser protections.
- Skill and hook files installed into coding agents.
- Client-side cryptography used for optional Cloud sync.

Out of scope:

- Vulnerabilities in third-party coding agents, editors, or model providers. Report those to their maintainers.
- Findings that require an attacker to already have local shell access as your user, since Docmancer stores memory as readable files under your home directory by design.
- Missing hardening headers on documentation pages that carry no user data.

## Handling your data in a report

Docmancer indexes real project memory, so reproduction steps often contain private content. Redact anything you would not want stored in a GitHub advisory. If a reproduction genuinely needs sensitive input, say so in the report and we will arrange another channel.

For the hosted service boundary, encryption design, and what the server can see, read the [security architecture](https://docmancer.dev/security) and the [disclosure policy](https://docmancer.dev/security/disclosure).
