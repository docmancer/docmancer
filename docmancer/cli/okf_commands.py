"""``docmancer okf`` command group.

Validate Open Knowledge Format (OKF) bundles. OKF is a vendor-neutral spec
from Google Cloud: a directory of markdown files with YAML frontmatter, one
required field ``type``, and reserved ``index.md`` / ``log.md`` files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from docmancer.cli.help import (
    DocmancerCommand,
    DocmancerGroup,
    HELP_CONTEXT_SETTINGS,
    format_examples,
)


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Work with Open Knowledge Format bundles.",
    epilog=format_examples(
        "docmancer memory export --output memory.okf",
        "docmancer okf doctor memory.okf",
    ),
)
def okf_group():
    """Validate OKF bundles produced by docmancer or any other tool.

    Export a bundle with `docmancer memory export --format okf`, then check
    conformance here. OKF is just markdown with YAML frontmatter, so any
    OKF-aware agent or tool can read what docmancer writes.
    """


@okf_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Validate an OKF bundle.")
@click.argument("path")
def doctor(path: str):
    """Check that a directory conforms to OKF v0.1.

    Every non-reserved markdown file must have parseable YAML frontmatter and a
    non-empty `type`. Broken cross-links and missing optional fields are
    reported as warnings (the spec tolerates them). Exits non-zero on any error.
    """
    from docmancer.okf.validate import validate_bundle

    root = Path(path)
    issues = validate_bundle(root)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    for issue in errors:
        click.echo(f"error  {issue.path}: {issue.message}")
    for issue in warnings:
        click.echo(f"warn   {issue.path}: {issue.message}")

    if errors:
        click.echo(f"{len(errors)} error(s), {len(warnings)} warning(s). Bundle is not conformant.")
        sys.exit(1)
    click.echo(f"Bundle is conformant (OKF v0.1). {len(warnings)} warning(s).")


__all__ = ["okf_group"]
